"""
Multi-turn RAG agent built with LangGraph.

Nodes: rewrite → retrieve → generate
- rewrite: makes follow-up questions self-contained using chat history
- retrieve: searches Qdrant for relevant chunks
- generate: answers from retrieved context + history
"""

import sys
import os
from pathlib import Path
from typing import TypedDict, Generator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
from langgraph.graph import StateGraph, START, END

from retrieval.searcher import Searcher

# ── State ─────────────────────────────────────────────────────────
class AgentState(TypedDict):
    messages: list[dict]        # [{"role": "user", "content": ...}, ...]
    question: str               # current (rewritten) question
    context: list[dict]         # retrieved chunks
    answer: str                 # final answer
    suggested_department: str | None  # closest dept when no context found

# ── Agent ─────────────────────────────────────────────────────────
class RAGAgent:
    # Department names for gap suggestion
    DEPARTMENT_NAMES = [
        "AI", "Customer_Support", "Engineering",
        "HR", "Operations", "Security",
    ]

    def __init__(self):
        self.searcher = Searcher(
            host=os.getenv("QDRANT_HOST", "localhost"),
            port=int(os.getenv("QDRANT_PORT", "6333")),
        )
        self._llm = None  # lazy init to avoid import-time httpx issues
        self.graph = self._build_graph()

    @property
    def llm(self):
        if self._llm is None:
            self._llm = OpenAI(
                api_key=os.getenv("DEEPSEEK_API_KEY"),
                base_url="https://api.deepseek.com",
            )
        return self._llm

    # ── Nodes ─────────────────────────────────────────────────
    def rewrite_question(self, state: AgentState) -> AgentState:
        """Rewrite the latest user question to be self-contained using history."""
        messages = state["messages"]
        question = messages[-1]["content"]

        # Only rewrite if there's prior conversation
        if len(messages) <= 1:
            return {**state, "question": question}

        history = "\n".join(
            f"{m['role']}: {m['content']}" for m in messages[:-1]
        )

        response = self.llm.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Rewrite the user's follow-up question so it is self-contained "
                        "and can be understood without the chat history. "
                        "If the question is already self-contained, return it unchanged. "
                        "Return ONLY the rewritten question, no explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": f"History:\n{history}\n\nFollow-up: {question}",
                },
            ],
            temperature=0,
            max_tokens=200,
        )

        rewritten = response.choices[0].message.content.strip()
        return {**state, "question": rewritten}

    def retrieve(self, state: AgentState) -> AgentState:
        """Search Qdrant for relevant chunks with fallback recovery."""
        query = state["question"]
        hits = self.searcher.search(query, top_k=5, rerank=True)

        # Step 5 — Fallback: if no results, rephrase and retry
        if not hits:
            hits = self._fallback_retrieve(query)

        return {**state, "context": hits}

    def _fallback_retrieve(self, query: str) -> list[dict]:
        """Rephrase the query and retry when first search returns nothing."""
        try:
            response = self.llm.chat.completions.create(
                model="deepseek-chat",
                messages=[{
                    "role": "user",
                    "content": (
                        f"The search query \"{query}\" returned no results from our "
                        f"knowledge base. Rephrase this query to be more general or use "
                        f"different keywords that might match our internal docs. "
                        f"Return ONLY the rephrased query, no explanation."
                    ),
                }],
                temperature=0.3,
                max_tokens=80,
            )
            rephrased = response.choices[0].message.content.strip()
            if rephrased and rephrased != query:
                return self.searcher.search(rephrased, top_k=5, rerank=True)
        except Exception:
            pass
        return []

    def _find_closest_department(self, query: str) -> str | None:
        """Use LLM to classify which department the question belongs to."""
        try:
            dept_list = ", ".join(self.DEPARTMENT_NAMES)
            response = self.llm.chat.completions.create(
                model="deepseek-chat",
                messages=[{
                    "role": "system",
                    "content": (
                        f"Classify the user's question into exactly ONE of these "
                        f"departments: {dept_list}. Return ONLY the department name, "
                        f"no explanation. If unsure, pick the best fit."
                    ),
                }, {
                    "role": "user",
                    "content": query,
                }],
                temperature=0,
                max_tokens=10,
            )
            dept = response.choices[0].message.content.strip()
            if dept in self.DEPARTMENT_NAMES:
                return dept
        except Exception:
            pass
        return None

    def generate(self, state: AgentState) -> AgentState:
        """Generate answer from context and history."""
        context = state["context"]
        if not context:
            return {**state, "answer": "I couldn't find any relevant information to answer your question."}

        # Build context block
        ctx_text = "\n\n".join(
            f"[{c['source'].split('/')[-1]}]\n{c['text']}" for c in context
        )

        # Build messages for LLM
        system = (
            "You are a helpful assistant for TechCorp. "
            "Answer the user's question using ONLY the provided context. "
            "If the context doesn't contain the answer, say so clearly. "
            "Be concise and cite the source file name."
        )

        llm_messages = [{"role": "system", "content": system}]

        # Include chat history (skip the last user message — it's the current question)
        history = state["messages"][:-1]
        if history:
            llm_messages.extend(history)

        # Add context + current question
        llm_messages.append({
            "role": "user",
            "content": f"Context:\n{ctx_text}\n\nQuestion: {state['question']}",
        })

        response = self.llm.chat.completions.create(
            model="deepseek-chat",
            messages=llm_messages,
            temperature=0.3,
            max_tokens=500,
        )

        answer = response.choices[0].message.content
        return {**state, "answer": answer}

    def _is_no_answer(self, question: str, answer: str) -> bool:
        """Quick LLM check: does the answer indicate the KB lacks the information?"""
        try:
            response = self.llm.chat.completions.create(
                model="deepseek-chat",
                messages=[{
                    "role": "system",
                    "content": (
                        "Determine if the assistant's answer indicates it COULD NOT find "
                        "the requested information in its knowledge base. Answer ONLY 'yes' or 'no'. "
                        "Indicators: 'I couldn't find', 'context does not contain', 'no relevant', "
                        "'not covered', 'no information about', 'don't have information', "
                        "'no documents mention', etc."
                    ),
                }, {
                    "role": "user",
                    "content": f"Question: {question}\n\nAnswer: {answer}\n\nDid the assistant fail to find the information?",
                }],
                temperature=0,
                max_tokens=5,
            )
            result = response.choices[0].message.content.strip().lower()
            return result.startswith("yes")
        except Exception:
            return False

    def should_generate(self, state: AgentState) -> str:
        """Decide whether to generate or fallback."""
        if state["context"]:
            return "generate"
        return "no_context"

    def no_context(self, state: AgentState) -> AgentState:
        dept = self._find_closest_department(state["question"])
        return {
            **state,
            "answer": "I couldn't find any relevant documents to answer your question. Try rephrasing or broadening your search.",
            "suggested_department": dept,  # added to state for gap detection
        }

    # ── Build Graph ──────────────────────────────────────────
    def _build_graph(self):
        builder = StateGraph(AgentState)

        builder.add_node("rewrite", self.rewrite_question)
        builder.add_node("retrieve", self.retrieve)
        builder.add_node("generate", self.generate)
        builder.add_node("no_context", self.no_context)

        builder.add_edge(START, "rewrite")
        builder.add_edge("rewrite", "retrieve")
        builder.add_conditional_edges(
            "retrieve",
            self.should_generate,
            {"generate": "generate", "no_context": "no_context"},
        )
        builder.add_edge("generate", END)
        builder.add_edge("no_context", END)

        return builder.compile()

    # ── Public API ───────────────────────────────────────────
    def ask(self, question: str, history: list[dict] | None = None) -> dict:
        """Ask a question. history = [{'role': 'user'|'assistant', 'content': ...}, ...]"""
        messages = list(history or [])
        messages.append({"role": "user", "content": question})

        result = self.graph.invoke({
            "messages": messages,
            "question": question,
            "context": [],
            "answer": "",
            "suggested_department": None,
        })

        # Post-process: context was found but answer may still be a "no-answer"
        suggested_dept = result.get("suggested_department")
        if not suggested_dept and result["context"]:
            if self._is_no_answer(result["question"], result["answer"]):
                suggested_dept = self._find_closest_department(result["question"])

        return {
            "answer": result["answer"],
            "question_used": result["question"],
            "sources": result["context"],
            "suggested_department": suggested_dept,
        }

    def ask_stream(
        self, question: str, history: list[dict] | None = None
    ) -> Generator[dict, None, None]:
        """Ask a question and stream the answer token-by-token.

        Yields:
            {"type": "token", "content": "..."} — answer tokens
            {"type": "done", "sources": [...], "question_used": "..."} — final
        """
        messages = list(history or [])
        messages.append({"role": "user", "content": question})

        # Step 1: Rewrite (using the graph's node)
        state = {"messages": messages, "question": question, "context": [], "answer": ""}
        state = self.rewrite_question(state)

        # Step 2: Retrieve
        state = self.retrieve(state)

        context = state["context"]
        if not context:
            # Find the closest department for the knowledge gap suggestion
            dept = self._find_closest_department(state["question"])
            if dept:
                yield {
                    "type": "gap",
                    "suggested_department": dept,
                    "question": state["question"],
                }
            yield {"type": "token", "content": "I couldn't find any relevant documents."}
            yield {
                "type": "done",
                "sources": [],
                "question_used": state["question"],
                "gap": dept is not None,
                "suggested_department": dept,
            }
            return

        # Step 3: Generate with streaming
        ctx_text = "\n\n".join(
            f"[{c['source'].split('/')[-1]}]\n{c['text']}" for c in context
        )

        system = (
            "You are a helpful assistant for TechCorp. "
            "Answer the user's question using ONLY the provided context. "
            "If the context doesn't contain the answer, say so clearly. "
            "Be concise and cite the source file name."
        )

        llm_messages = [{"role": "system", "content": system}]

        history_msgs = state["messages"][:-1]
        if history_msgs:
            llm_messages.extend(history_msgs)

        llm_messages.append({
            "role": "user",
            "content": f"Context:\n{ctx_text}\n\nQuestion: {state['question']}",
        })

        stream = self.llm.chat.completions.create(
            model="deepseek-chat",
            messages=llm_messages,
            temperature=0.3,
            max_tokens=500,
            stream=True,
        )

        full_answer = ""
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                full_answer += delta.content
                yield {"type": "token", "content": delta.content}

        # After generation: check if the answer is a "no-answer" despite having context
        is_gap = self._is_no_answer(state["question"], full_answer)
        suggested_dept = None
        if is_gap:
            suggested_dept = self._find_closest_department(state["question"])
            if suggested_dept:
                yield {
                    "type": "gap",
                    "suggested_department": suggested_dept,
                    "question": state["question"],
                }

        yield {
            "type": "done",
            "sources": context,
            "question_used": state["question"],
            "gap": is_gap,
            "suggested_department": suggested_dept,
        }