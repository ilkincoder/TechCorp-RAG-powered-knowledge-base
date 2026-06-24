"""
RAG Evaluation Pipeline — real metrics against TechCorp knowledge base.

Generates a synthetic test set from actual PDFs, runs both the V1 (naive
chunking) and V2 (parent-child) pipelines against the same questions, and
computes RAGAS metrics. Output is written to ``frontend/public/eval_results.json``.

Usage:
    python src/evaluation/run_eval.py
"""

import sys
import os
import json
import time
import random
from pathlib import Path

# Make src/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import fitz
from openai import OpenAI
from datasets import Dataset

# ── RAGAS ────────────────────────────────────────────────────────────
from ragas import evaluate
from ragas.metrics import (
    context_precision,
    context_recall,
    faithfulness,
    answer_relevancy,
)
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_openai import ChatOpenAI
from langchain_core.outputs import LLMResult
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from ragas.llms import LangchainLLMWrapper
from ragas.run_config import RunConfig
import asyncio
from functools import partial

# ── Project imports ──────────────────────────────────────────────────
from retrieval.searcher import Searcher

# ── Config ───────────────────────────────────────────────────────────
KB_PATH = str(Path(__file__).resolve().parent.parent.parent / "knowledge_base")
OUTPUT_PATH = str(
    Path(__file__).resolve().parent.parent.parent / "frontend" / "public" / "eval_results.json"
)

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY")

QUESTIONS_PER_PDF = 3
PDF_SAMPLE_LIMIT = 8  # total PDFs to sample across departments
TOP_K = 5

# ── LLM clients ──────────────────────────────────────────────────────
_deepseek = None


def _get_llm():
    global _deepseek
    if _deepseek is None:
        _deepseek = OpenAI(
            api_key=DEEPSEEK_KEY,
            base_url="https://api.deepseek.com",
        )
    return _deepseek


def _answer_from_contexts(
    question: str, contexts: list[dict], model: str = "deepseek-chat"
) -> tuple[str, float]:
    """Generate an answer from retrieved contexts. Returns (answer, latency_ms)."""
    if not contexts:
        return "No relevant documents found.", 0.0

    ctx_text = "\n\n".join(
        f"[{c['source'].split('/')[-1]}]\n{c['text']}" for c in contexts
    )

    system = (
        "You are a helpful assistant for TechCorp. "
        "Answer the user's question using ONLY the provided context. "
        "If the context doesn't contain the answer, say so clearly. "
        "Be concise and cite the source file name."
    )

    t0 = time.perf_counter()
    response = _get_llm().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Context:\n{ctx_text}\n\nQuestion: {question}"},
        ],
        temperature=0.3,
        max_tokens=500,
    )
    latency = (time.perf_counter() - t0) * 1000

    return response.choices[0].message.content, latency


# ── Test set generation ──────────────────────────────────────────────
def _sample_pdfs(kb_path: str, limit: int) -> list[str]:
    """Return up to ``limit`` PDF paths, sampling across departments."""
    all_pdfs = sorted(Path(kb_path).rglob("*.pdf"))
    # Shuffle but seed for reproducibility
    random.seed(42)
    all_pdfs = list(all_pdfs)
    random.shuffle(all_pdfs)
    return [str(p) for p in all_pdfs[:limit]]


def _extract_text(file_path: str, max_chars: int = 6000) -> str:
    """Extract first ``max_chars`` of text from a PDF."""
    try:
        doc = fitz.open(file_path)
        text = " ".join([page.get_text() for page in doc])
        doc.close()
        return text[:max_chars]
    except Exception as e:
        print(f"  ⚠ Failed to extract {file_path}: {e}")
        return ""


def _generate_questions(text: str, filename: str) -> list[dict]:
    """Generate question-context-answer triplets from a document excerpt."""
    prompt = (
        f"You are a test-set generator for a RAG system. "
        f"Below is an excerpt from a company document called '{filename}'.\n\n"
        f"Document excerpt:\n{text}\n\n"
        f"Generate {QUESTIONS_PER_PDF} questions that a user might ask and that can be "
        f"answered from this text. For each question, provide:\n"
        f"1. The question\n"
        f"2. A concise, accurate answer based ONLY on the provided text\n"
        f"3. The exact passage from the text that supports the answer (quote verbatim)\n\n"
        f"Return ONLY valid JSON — a list of objects with keys: "
        f'"question", "answer", "passage" (no markdown, no extra text).'
    )

    try:
        response = _get_llm().chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=2000,
        )
        raw = response.choices[0].message.content

        # Extract JSON from response
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw[raw.find("\n") + 1:]
            if raw.endswith("```"):
                raw = raw[: raw.rfind("```")].strip()

        items = json.loads(raw)
        return [
            {
                "question": item["question"],
                "ground_truth": item["answer"],
                "ground_truth_context": item["passage"],
            }
            for item in items
        ]
    except Exception as e:
        print(f"  ⚠ Failed to generate questions: {e}")
        return []


# ── RAG Pipeline wrappers ────────────────────────────────────────────
def _run_baseline(question: str, searcher: Searcher) -> dict:
    """Run V1 pipeline: naive chunking via default Searcher.search()."""
    t0 = time.perf_counter()
    contexts = searcher.search(question, top_k=TOP_K, rerank=True)
    retrieval_ms = (time.perf_counter() - t0) * 1000

    answer, gen_ms = _answer_from_contexts(question, contexts)

    return {
        "contexts": contexts,
        "answer": answer,
        "retrieval_ms": round(retrieval_ms, 1),
        "generation_ms": round(gen_ms, 1),
        "total_ms": round(retrieval_ms + gen_ms, 1),
    }


def _run_parent_child(question: str, searcher: Searcher) -> dict:
    """Run V2 pipeline: parent-child chunking via Searcher.parent_child_retrieve()."""
    t0 = time.perf_counter()
    contexts = searcher.parent_child_retrieve(question, top_k=TOP_K)
    retrieval_ms = (time.perf_counter() - t0) * 1000

    answer, gen_ms = _answer_from_contexts(question, contexts)

    return {
        "contexts": contexts,
        "answer": answer,
        "retrieval_ms": round(retrieval_ms, 1),
        "generation_ms": round(gen_ms, 1),
        "total_ms": round(retrieval_ms + gen_ms, 1),
    }


# ── DeepSeek-compatible LLM wrapper ──────────────────────────────────
class DeepSeekRagasLLM(LangchainLLMWrapper):
    """LangchainLLMWrapper that splits n>1 calls into sequential n=1 calls.

    DeepSeek only supports n=1. RAGAS's answer_relevancy calls with n=3
    internally. This wrapper intercepts at the RAGAS LLM layer, makes N
    separate calls, and merges results.
    """

    async def generate(
        self,
        prompt,
        n: int = 1,
        temperature: float | None = None,
        stop: list[str] | None = None,
        callbacks=None,
    ):
        if n <= 1:
            return await super().generate(prompt, n=1, temperature=temperature, stop=stop, callbacks=callbacks)

        from langchain_core.outputs import LLMResult

        all_generations = []
        combined_usage = {}
        for _ in range(n):
            result = await super().generate(prompt, n=1, temperature=temperature, stop=stop, callbacks=callbacks)
            all_generations.extend(result.generations)
            if result.llm_output and "token_usage" in result.llm_output:
                tu = result.llm_output["token_usage"]
                combined_usage["total_tokens"] = combined_usage.get("total_tokens", 0) + tu.get("total_tokens", 0)

        return LLMResult(
            generations=all_generations,
            llm_output={"token_usage": combined_usage} if combined_usage else {},
        )


# ── RAGAS evaluation ─────────────────────────────────────────────────
def _compute_ragas_metrics(
    questions: list[str],
    answers: list[str],
    contexts: list[list[str]],
    ground_truths: list[str],
) -> dict:
    """Compute RAGAS metrics and return as a flat dict."""
    ds = Dataset.from_dict({
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths,
    })

    # Set up LLM for DeepSeek (wrapped to handle n>1 via sequential n=1 calls)
    os.environ["OPENAI_API_KEY"] = DEEPSEEK_KEY or ""
    base_llm = ChatOpenAI(
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key=DEEPSEEK_KEY,
    )
    eval_llm = DeepSeekRagasLLM(base_llm)

    # Use local fastembed embeddings (no API calls)
    eval_embeddings = LangchainEmbeddingsWrapper(
        FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")
    )

    result = evaluate(
        dataset=ds,
        metrics=[context_precision, context_recall, faithfulness, answer_relevancy],
        llm=eval_llm,
        embeddings=eval_embeddings,
    )

    # result is a dict-like object; convert to plain dict
    import math
    metrics_dict = {}
    for key in result:
        val = result[key]
        if val is None:
            metrics_dict[key] = 0.0
        else:
            fval = float(val)
            metrics_dict[key] = 0.0 if math.isnan(fval) else round(fval, 4)

    return metrics_dict


# ── Main ─────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("RAG Evaluation Pipeline")
    print("=" * 60)

    # ── Step 1: Generate test set ────────────────────────────────
    print("\n[1/4] Generating test questions from knowledge base PDFs...")
    pdf_paths = _sample_pdfs(KB_PATH, PDF_SAMPLE_LIMIT)
    print(f"  Sampled {len(pdf_paths)} PDFs")

    all_questions = []
    for fp in pdf_paths:
        fname = Path(fp).name
        print(f"  Processing: {fname}")
        text = _extract_text(fp)
        if not text:
            continue
        items = _generate_questions(text, fname)
        for item in items:
            item["source_pdf"] = fname
        all_questions.extend(items)
        print(f"    → {len(items)} questions generated")

    print(f"  Total test set: {len(all_questions)} questions")

    if len(all_questions) < 5:
        print("  ⚠ Too few questions generated — aborting.")
        return

    # ── Step 2: Run V1 Baseline ──────────────────────────────────
    print("\n[2/4] Running V1 baseline (naive chunking)...")
    searcher = Searcher(host=QDRANT_HOST, port=QDRANT_PORT)

    for i, q in enumerate(all_questions):
        print(f"  [{i+1}/{len(all_questions)}] {q['question'][:80]}...")
        result = _run_baseline(q["question"], searcher)
        q["baseline"] = result

    # ── Step 3: Run V2 Parent-Child ──────────────────────────────
    print("\n[3/4] Running V2 pipeline (parent-child chunking)...")

    for i, q in enumerate(all_questions):
        print(f"  [{i+1}/{len(all_questions)}] {q['question'][:80]}...")
        result = _run_parent_child(q["question"], searcher)
        q["parent_child"] = result

    # ── Step 4: Compute RAGAS metrics ────────────────────────────
    print("\n[4/4] Computing RAGAS metrics...")

    questions = [q["question"] for q in all_questions]
    ground_truths = [q["ground_truth"] for q in all_questions]

    # V1 metrics
    print("  Evaluating V1...")
    v1_answers = [q["baseline"]["answer"] for q in all_questions]
    v1_contexts = [[c["text"] for c in q["baseline"]["contexts"]] for q in all_questions]
    v1_metrics = _compute_ragas_metrics(questions, v1_answers, v1_contexts, ground_truths)

    # V2 metrics
    print("  Evaluating V2...")
    v2_answers = [q["parent_child"]["answer"] for q in all_questions]
    v2_contexts = [[c["text"] for c in q["parent_child"]["contexts"]] for q in all_questions]
    v2_metrics = _compute_ragas_metrics(questions, v2_answers, v2_contexts, ground_truths)

    # ── Aggregate latency & token data ───────────────────────────
    v1_latency = round(
        sum(q["baseline"]["total_ms"] for q in all_questions) / len(all_questions), 1
    )
    v2_latency = round(
        sum(q["parent_child"]["total_ms"] for q in all_questions) / len(all_questions), 1
    )

    # Estimate tokens (rough: ~1.3 chars per token for contexts, ~1.2 for answers)
    v1_tokens = round(
        sum(
            len(c["text"]) // 1.3 + len(q["baseline"]["answer"]) // 1.2
            for q in all_questions
            for c in q["baseline"]["contexts"]
        )
        / len(all_questions)
    )
    v2_tokens = round(
        sum(
            len(c["text"]) // 1.3 + len(q["parent_child"]["answer"]) // 1.2
            for q in all_questions
            for c in q["parent_child"]["contexts"]
        )
        / len(all_questions)
    )

    # Add latency & tokens to metric dicts
    v1_metrics["latency_ms"] = v1_latency
    v1_metrics["token_count"] = v1_tokens
    v2_metrics["latency_ms"] = v2_latency
    v2_metrics["token_count"] = v2_tokens

    # ── Build traces (keeping only what the frontend needs) ──────
    traces = []
    for q in all_questions:
        traces.append({
            "query": q["question"],
            "source_pdf": q.get("source_pdf", ""),
            "baseline": {
                "chunks": [
                    {"text": c["text"][:500], "source": c["source"].split("/")[-1], "score": c["score"]}
                    for c in q["baseline"]["contexts"]
                ],
                "answer": q["baseline"]["answer"],
                "retrieval_ms": q["baseline"]["retrieval_ms"],
                "generation_ms": q["baseline"]["generation_ms"],
            },
            "parent_child": {
                "chunks": [
                    {"text": c["text"][:500], "source": c["source"].split("/")[-1], "score": c["score"]}
                    for c in q["parent_child"]["contexts"]
                ],
                "answer": q["parent_child"]["answer"],
                "retrieval_ms": q["parent_child"]["retrieval_ms"],
                "generation_ms": q["parent_child"]["generation_ms"],
            },
        })

    # ── Assemble final output ────────────────────────────────────
    output = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "num_questions": len(all_questions),
        "pdfs_sampled": len(pdf_paths),
        "baseline": {
            "name": "V1 Naive Chunking",
            "description": "RecursiveCharacterTextSplitter, chunk_size=500, overlap=50",
            "metrics": {
                "context_precision": v1_metrics.get("context_precision", 0),
                "context_recall": v1_metrics.get("context_recall", 0),
                "faithfulness": v1_metrics.get("faithfulness", 0),
                "answer_relevancy": v1_metrics.get("answer_relevancy", 0),
                "latency_ms": v1_metrics["latency_ms"],
                "token_count": v1_metrics["token_count"],
            },
        },
        "parent_child": {
            "name": "V2 Parent-Child Retrieval",
            "description": "Two-pass: search fine-grained child chunks, return parent context",
            "metrics": {
                "context_precision": v2_metrics.get("context_precision", 0),
                "context_recall": v2_metrics.get("context_recall", 0),
                "faithfulness": v2_metrics.get("faithfulness", 0),
                "answer_relevancy": v2_metrics.get("answer_relevancy", 0),
                "latency_ms": v2_metrics["latency_ms"],
                "token_count": v2_metrics["token_count"],
            },
        },
        "traces": traces,
    }

    # ── Write output ─────────────────────────────────────────────
    os.makedirs(Path(OUTPUT_PATH).parent, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f"Results written to {OUTPUT_PATH}")
    print(f"V1 metrics: {json.dumps(output['baseline']['metrics'], indent=2)}")
    print(f"V2 metrics: {json.dumps(output['parent_child']['metrics'], indent=2)}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()