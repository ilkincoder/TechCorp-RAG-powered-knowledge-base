import sys
import os
import shutil
import uuid
from pathlib import Path

# Make src/ importable from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import json
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI

from retrieval.searcher import Searcher
from retrieval.file_scanner import scan_knowledge_base, check_indexed_status
from agent.rag_agent import RAGAgent
from prompts.onboarding_templates import build_onboarding_prompt
from ingestion.embedder import embed_and_upload_single

# ── App ───────────────────────────────────────────────────────────
STARTED_AT = datetime.now(timezone.utc).isoformat()

KB_PATH = str(Path(__file__).resolve().parent.parent.parent / "knowledge_base")

app = FastAPI(
    title="TechCorp Knowledge Base API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Services ──────────────────────────────────────────────────────
searcher = Searcher(
    host=os.getenv("QDRANT_HOST", "localhost"),
    port=int(os.getenv("QDRANT_PORT", "6333")),
)

agent = RAGAgent()

# Lazy LLM client — avoid httpx version conflicts at import time
_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        _llm = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )
    return _llm

def _deduplicate_sources(hits: list[dict]) -> list[dict]:
    """Deduplicate hits by unique source filename, keeping first occurrence."""
    seen = set()
    unique = []
    for h in hits:
        filename = h["source"].split("/")[-1]
        if filename not in seen:
            seen.add(filename)
            unique.append(h)
    return unique

def _deduplicate_with_pct(hits: list[dict]) -> list[dict]:
    """Deduplicate by source filename and compute percentage contribution.

    Percentage is based on how many chunks came from each document
    relative to total retrieved chunks. The percentage replaces the
    raw relevance score so the frontend shows meaningful contribution.
    """
    if not hits:
        return []

    # Count chunks per filename
    filenames = [h["source"].split("/")[-1] for h in hits]
    from collections import Counter
    counts = Counter(filenames)
    total = sum(counts.values())

    seen = set()
    unique = []
    for h in hits:
        filename = h["source"].split("/")[-1]
        if filename not in seen:
            seen.add(filename)
            pct = round((counts[filename] / total) * 100)
            unique.append({
                **h,
                "score": pct,           # percentage (0-100), replaces raw relevance
                "chunks": counts[filename],
                "total_chunks": total,
            })
    return unique

# In-memory session store: session_id → [{role, content}, ...]
sessions: dict[str, list[dict]] = {}

# ── Schemas ───────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class OnboardingRequest(BaseModel):
    role: str = Field(..., description="Job title, e.g. 'Junior Backend Engineer'")
    department: str = Field(..., description="Department, e.g. 'Engineering'")
    experience: str = Field(..., description="Experience, e.g. '2 years Python'")
    top_k: int = Field(default=5, ge=1, le=20)


class FileInfo(BaseModel):
    name: str
    path: str
    category: str
    size: int
    added: str
    indexed: bool


class SmartChatResponse(BaseModel):
    answer: str
    sources: list  # SearchResult objects or strings from n8n
    route: str  # "simple" or "complex"


class AuditRequest(BaseModel):
    departments: list[str]


class AuditConflict(BaseModel):
    topic: str
    docs_found: bool = True
    depts_compared: list[str]
    conflict_found: bool = True
    severity: str  # "low" | "medium" | "high"
    finding: str   # 1-2 sentence summary
    dept_a_doc: str
    dept_a_quote: str
    dept_b_doc: str
    dept_b_quote: str


class AuditSuggestion(BaseModel):
    topic: str
    action: str
    involved_depts: list[str] = []


class AuditResponse(BaseModel):
    departments: list[str]
    topics_checked: int
    conflicts: list[dict] = []
    clean: list[str] = []
    no_docs: list[str] = []
    summary: str
    suggestions: list[dict] = []
    steps: list[str] = []


# ── Knowledge Gap Schemas ──────────────────────────────────────────
class GapRequest(BaseModel):
    query: str = Field(..., description="Original user question")
    suggested_department: str = Field(..., description="AI-suggested department")
    requester_name: str = Field(default="Anonymous", description="Name of requester")
    message: str = Field(default="", description="Additional context from requester")


class GapRequestItem(BaseModel):
    id: str
    query: str
    suggested_department: str
    requester_name: str
    message: str
    status: str  # "pending" | "draft_ready" | "approved"
    draft_content: str | None = None
    draft_generated_at: str | None = None
    created_at: str
    approved_at: str | None = None
    confirmed_at: str | None = None


# ── Gap storage helpers ────────────────────────────────────────────
GAP_STORE = Path(KB_PATH) / "gap_requests.json"
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "http://host.docker.internal:5678/webhook/generate-draft")


def _load_gaps() -> list[dict]:
    if not GAP_STORE.exists():
        return []
    try:
        return json.loads(GAP_STORE.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save_gaps(gaps: list[dict]) -> None:
    GAP_STORE.write_text(json.dumps(gaps, indent=2, default=str))


# ── Classifier ────────────────────────────────────────────────────
COMPLEX_MARKERS = [
    "compare", "difference", "versus", " vs ", "contradiction",
    "audit", "evaluate", "assess", "analyze", "across",
    "between engineering and security", "between security and engineering",
    "between hr and", "both departments", "find all", "summarize all",
    "cross-reference", "side by side", "what's the difference",
    "how do they differ", "conflict", "inconsistent",
]

DEPARTMENT_NAMES = [
    "engineering", "security", "hr", "ai", "operations", "customer support",
]


def _classify_query(query: str) -> str:
    """Classify a user query as 'simple' or 'complex'.

    Pattern match first (free), LLM fallback for unclear cases (~0.3s).
    """
    q = query.lower().strip()

    # ── Pattern match ──────────────────────────────────────────
    # Multiple department mentions → complex
    dept_count = sum(1 for d in DEPARTMENT_NAMES if d in q)
    if dept_count >= 2:
        return "complex"

    # Known complex markers
    if any(m in q for m in COMPLEX_MARKERS):
        return "complex"

    # Very short factoid questions → simple
    if len(q.split()) <= 5 and q.startswith(("what is", "who is", "define", "when did")):
        return "simple"

    # If none of the above matched, ask the LLM
    try:
        response = _get_llm().chat.completions.create(
            model="deepseek-chat",
            messages=[{
                "role": "system",
                "content": (
                    "Classify this question. Answer with exactly one word.\n"
                    "SIMPLE = single fact lookup, definition, or one-document question.\n"
                    "COMPLEX = comparison, multi-document analysis, audit, contradiction check."
                ),
            }, {
                "role": "user",
                "content": query,
            }],
            max_tokens=2,
            temperature=0,
        )
        verdict = response.choices[0].message.content.strip().lower()
        return "complex" if "complex" in verdict else "simple"
    except Exception:
        return "simple"  # safe default on error


# ── Endpoints ─────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "started_at": STARTED_AT}


@app.get("/files", response_model=list[FileInfo])
def list_files():
    """Return metadata for every PDF in the knowledge_base directory.

    Checks Qdrant to determine which files are already indexed.
    Gracefully degrades if Qdrant is unreachable (all files
    reported as not indexed).
    """
    files = scan_knowledge_base(KB_PATH)
    indexed_paths = check_indexed_status(searcher)

    # Qdrant stores relative paths (knowledge_base/…), scanner returns
    # absolute paths (/app/knowledge_base/…) — match by filename.
    indexed_names = {Path(src).name for src in indexed_paths}

    result = [
        FileInfo(
            name=f["name"],
            path=f["path"],
            category=f["category"],
            size=f["size"],
            added=f["added"],
            indexed=f["name"] in indexed_names,
        )
        for f in files
    ]

    return result


@app.get("/files/view/{filename}")
def view_file(filename: str):
    """Serve a PDF file from the knowledge_base for in-browser viewing.

    Finds the file by name anywhere under KB_PATH, validates it lives
    inside the knowledge base directory, then returns it with inline
    Content-Disposition so the browser renders the PDF natively.
    """
    matches = list(Path(KB_PATH).rglob(filename))
    if not matches:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    file_path = matches[0].resolve()
    kb_root = Path(KB_PATH).resolve()

    # Prevent path-traversal: ensure the resolved file is inside KB_PATH
    if not str(file_path).startswith(str(kb_root) + os.sep):
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(
        file_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.get("/departments")
def list_departments():
    """Return the list of valid department (category) folder names.

    Scans the knowledge_base directory for immediate subdirectories.
    """
    kb = Path(KB_PATH)
    if not kb.exists():
        return []
    return sorted([
        d.name for d in kb.iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name != "Drafts"
    ])


@app.post("/files/upload", response_model=FileInfo)
def upload_file(file: UploadFile = File(...), category: str = Form(...)):
    """Upload a PDF to knowledge_base/<category>/ and index it incrementally.

    The file is written to disk, then embedded and upserted into Qdrant
    without touching existing chunks.  Returns the new file's metadata.
    """
    # 1. Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # 2. Validate category — must be a real subdirectory
    kb = Path(KB_PATH)
    target_dir = kb / category
    if not target_dir.exists():
        # Allow creating new department folders on the fly
        target_dir.mkdir(parents=True, exist_ok=True)

    # 3. Sanitise filename and write to disk
    safe_name = file.filename.replace(" ", "_")
    dest = target_dir / safe_name

    # Avoid overwriting — append a counter if file exists
    if dest.exists():
        stem, ext = os.path.splitext(safe_name)
        counter = 1
        while dest.exists():
            dest = target_dir / f"{stem}_{counter}{ext}"
            counter += 1

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_path = str(dest)

    # 4. Index incrementally in Qdrant
    try:
        num_chunks = embed_and_upload_single(
            file_path=file_path,
            category=category,
            host=os.getenv("QDRANT_HOST", "localhost"),
            port=int(os.getenv("QDRANT_PORT", "6333")),
        )
        indexed = num_chunks > 0
    except Exception as e:
        # File is saved — indexing can be retried later
        print(f"Indexing failed for {file_path}: {e}")
        indexed = False

    # 5. Return metadata
    stat = os.stat(dest)
    return FileInfo(
        name=dest.name,
        path=file_path,
        category=category,
        size=stat.st_size,
        added=datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
        indexed=indexed,
    )


@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    """Stream the answer token-by-token via SSE."""
    history = sessions.get(req.session_id, [])

    def event_stream():
        full_answer = ""

        for event in agent.ask_stream(req.message, history=history):
            if event["type"] == "gap":
                yield f"data: {json.dumps({'type': 'gap', 'suggested_department': event['suggested_department'], 'question': event['question']})}\n\n"

            elif event["type"] == "token":
                full_answer += event["content"]
                yield f"data: {json.dumps({'type': 'token', 'content': event['content']})}\n\n"

            elif event["type"] == "done":
                # Save to session
                history.append({"role": "user", "content": req.message})
                history.append({"role": "assistant", "content": full_answer})
                sessions[req.session_id] = history

                yield f"data: {json.dumps({'type': 'done', 'sources': _deduplicate_with_pct(event['sources']), 'gap': event.get('gap', False), 'suggested_department': event.get('suggested_department')})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Smart Chat with Classifier Router ─────────────────────────────
@app.post("/chat/smart", response_model=SmartChatResponse)
def chat_smart(req: ChatRequest):
    """Route simple queries to local RAG, complex queries to n8n+MCP agent.

    SIMPLE path:  FastAPI → RAGAgent → answer (2-3s, no n8n overhead)
    COMPLEX path: FastAPI → n8n webhook → MCP agent → answer (8-12s)
    """
    route = _classify_query(req.message)

    if route == "simple":
        # ── Simple: direct RAG (fast) ──────────────────────────
        history = sessions.get(req.session_id, [])
        result = agent.ask(req.message, history=history)

        history.append({"role": "user", "content": req.message})
        history.append({"role": "assistant", "content": result["answer"]})
        sessions[req.session_id] = history

        return SmartChatResponse(
            answer=result["answer"],
            sources=_deduplicate_with_pct(result["sources"]),
            route="simple",
        )

    else:
        # ── Complex: forward to n8n MCP agent workflow ─────────
        import httpx

        try:
            n8n_resp = httpx.post(
                "http://n8n:5678/webhook/chat-mcp",
                json={"message": req.message, "session_id": req.session_id},
                timeout=90.0,
            )
            n8n_resp.raise_for_status()
            data = n8n_resp.json()

            # n8n returns {answer, sources} — extract from possible nesting
            answer = (
                data.get("output")
                or data.get("answer")
                or data.get("data", {}).get("output", "")
                or "No answer returned."
            )
            raw_sources = data.get("sources") or data.get("data", {}).get("sources", [])

            # Update session
            history = sessions.get(req.session_id, [])
            history.append({"role": "user", "content": req.message})
            history.append({"role": "assistant", "content": answer})
            sessions[req.session_id] = history

            return SmartChatResponse(
                answer=answer,
                sources=raw_sources,
                route="complex",
            )

        except Exception as e:
            # Fallback: if n8n is unreachable, use local RAG
            history = sessions.get(req.session_id, [])
            result = agent.ask(req.message, history=history)

            history.append({"role": "user", "content": req.message})
            history.append({"role": "assistant", "content": result["answer"]})
            sessions[req.session_id] = history

            return SmartChatResponse(
                answer=result["answer"],
                sources=_deduplicate_with_pct(result["sources"]),
                route="simple",  # fell back to simple
            )


# ── Smart Chat Streaming ─────────────────────────────────────────
@app.post("/chat/smart/stream")
def chat_smart_stream(req: ChatRequest):
    """SSE streaming version of /chat/smart.

    Simple queries: native LLM token streaming.
    Complex queries: calls n8n, then simulates streaming from full response.
    """
    route = _classify_query(req.message)

    def event_stream():
        if route == "simple":
            # ── Simple: native token streaming ──────────────────
            history = sessions.get(req.session_id, [])
            for event in agent.ask_stream(req.message, history=history):
                if event["type"] == "gap":
                    yield f"data: {json.dumps({'type': 'gap', 'suggested_department': event['suggested_department'], 'question': event['question']})}\n\n"
                elif event["type"] == "token":
                    yield f"data: {json.dumps({'type': 'token', 'content': event['content']})}\n\n"
                elif event["type"] == "done":
                    history.append({"role": "user", "content": req.message})
                    history.append({"role": "assistant", "content": event.get("answer", "")})
                    sessions[req.session_id] = history
                    yield f"data: {json.dumps({'type': 'done', 'sources': _deduplicate_with_pct(event.get('sources', [])), 'route': 'simple', 'gap': event.get('gap', False), 'suggested_department': event.get('suggested_department')})}\n\n"

        else:
            # ── Complex: n8n + simulated streaming ──────────────
            yield f"data: {json.dumps({'type': 'route', 'route': 'complex'})}\n\n"
            yield f"data: {json.dumps({'type': 'status', 'message': 'Searching knowledge base...'})}\n\n"

            import httpx
            import time as _time
            try:
                n8n_resp = httpx.post(
                    "http://n8n:5678/webhook/chat-mcp",
                    json={"message": req.message, "session_id": req.session_id},
                    timeout=90.0,
                )
                n8n_resp.raise_for_status()
                data = n8n_resp.json()

                answer = (
                    data.get("output")
                    or data.get("answer")
                    or data.get("data", {}).get("output", "")
                    or "No answer returned."
                )
                sources = data.get("sources") or data.get("data", {}).get("sources", [])

                # Simulate streaming: emit tokens with small delay
                yield f"data: {json.dumps({'type': 'status', 'message': 'Generating response...'})}\n\n"
                pos = 0
                chunk_size = 6
                while pos < len(answer):
                    batch = answer[pos:pos + chunk_size]
                    pos += chunk_size
                    yield f"data: {json.dumps({'type': 'token', 'content': batch})}\n\n"
                    _time.sleep(0.02)

                yield f"data: {json.dumps({'type': 'done', 'sources': sources, 'route': 'complex'})}\n\n"

            except Exception:
                # Fallback: use simple RAG streaming
                yield f"data: {json.dumps({'type': 'route', 'route': 'simple-fallback'})}\n\n"
                history = sessions.get(req.session_id, [])
                for event in agent.ask_stream(req.message, history=history):
                    if event["type"] == "token":
                        yield f"data: {json.dumps({'type': 'token', 'content': event['content']})}\n\n"
                    elif event["type"] == "done":
                        yield f"data: {json.dumps({'type': 'done', 'sources': _deduplicate_with_pct(event.get('sources', [])), 'route': 'simple-fallback'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Onboarding via n8n + Streaming ───────────────────────────────
@app.post("/onboarding/n8n/stream")
def onboarding_n8n_stream(req: OnboardingRequest):
    """Parallel bypass: FastAPI retrieves + builds prompt, n8n handles DeepSeek.

    Flow:
    1. FastAPI searches Qdrant directly (5-8s, no MCP/AI Agent overhead)
    2. FastAPI builds the Few-Shot + CoT prompt (instant)
    3. FastAPI sends assembled prompt to n8n → DeepSeek generates plan (10-15s)
    4. FastAPI streams result to React via SSE
    """
    import httpx

    # ── 1. Direct retrieval (bypasses MCP protocol — same searcher, zero overhead) ─
    queries = [
        f"{req.department} onboarding handbook process",
        f"{req.role} technical skills tools guide",
        "IT onboarding computer accounts setup",
        "company security policy best practices",
        "team workflow code review deployment",
    ]

    all_hits: list[dict] = []
    seen = set()
    for q in queries:
        hits = searcher.search(q, top_k=req.top_k, rerank=True)
        for h in hits:
            key = h["source"] + h["text"][:80]
            if key not in seen:
                seen.add(key)
                all_hits.append(h)

    if not all_hits:
        raise HTTPException(status_code=404, detail="No relevant documents found")

    # ── 2. Build the full prompt (Few-Shot + CoT + context) ─
    context = "\n\n---\n\n".join(
        f"[{h['source'].split('/')[-1]}] (category: {h['category']})\n{h['text']}"
        for h in all_hits
    )

    prompt = build_onboarding_prompt(
        role=req.role,
        department=req.department,
        experience=req.experience,
        context=context,
    )

    # ── 3. Send ready-to-use prompt to n8n (no tools, no MCP, just DeepSeek) ─
    def event_stream():
        full_plan = ""
        n8n_url = "http://n8n:5678/webhook/generate-onboarding"

        # Notify UI that retrieval is done and generation is starting
        yield f"data: {json.dumps({'type': 'retrieval_done', 'sources_count': len(all_hits)})}\n\n"

        try:
            n8n_resp = httpx.post(
                n8n_url,
                json={"prompt": prompt},
                timeout=60.0,
            )
            n8n_resp.raise_for_status()
            n8n_data = n8n_resp.json()

            plan_text = (
                n8n_data.get("output")
                or n8n_data.get("text")
                or n8n_data.get("data", {}).get("output", "")
            )
        except Exception as e:
            # n8n failed — fall back to direct DeepSeek streaming
            stream = _get_llm().chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=1500,
                stream=True,
            )
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_plan += token
                    yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'plan': full_plan, 'fallback': True})}\n\n"
            return

        # ── 4. Simulate streaming from n8n's complete response ─
        sources = _deduplicate_sources(all_hits)[:10]

        if plan_text:
            pos = 0
            chunk_size = 8
            import time as _time

            while pos < len(plan_text):
                batch = plan_text[pos:pos + chunk_size]
                pos += chunk_size
                full_plan += batch
                yield f"data: {json.dumps({'type': 'token', 'content': batch})}\n\n"
                _time.sleep(0.015)

        yield f"data: {json.dumps({'type': 'done', 'plan': full_plan, 'sources': sources})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Onboarding Streaming (direct, no n8n) ─────────────────────────
@app.post("/onboarding/generate/stream")
def onboarding_generate_stream(req: OnboardingRequest):
    """Stream onboarding plan generation token-by-token via SSE.

    Same logic as /onboarding/generate but streams the LLM output
    so the React UI can display it in real-time.
    """
    # 1. Multi-query retrieval
    queries = [
        f"{req.department} onboarding handbook process",
        f"{req.role} technical skills tools guide",
        "IT onboarding computer accounts setup",
        "company security policy best practices",
        "team workflow code review deployment",
    ]

    all_hits: list[dict] = []
    seen = set()
    for q in queries:
        hits = searcher.search(q, top_k=req.top_k, rerank=True)
        for h in hits:
            key = h["source"] + h["text"][:80]
            if key not in seen:
                seen.add(key)
                all_hits.append(h)

    if not all_hits:
        raise HTTPException(status_code=404, detail="No relevant documents found")

    # 2. Build context & prompt
    context = "\n\n---\n\n".join(
        f"[{h['source'].split('/')[-1]}] (category: {h['category']})\n{h['text']}"
        for h in all_hits
    )

    prompt = build_onboarding_prompt(
        role=req.role,
        department=req.department,
        experience=req.experience,
        context=context,
    )

    # 3. Stream LLM tokens via SSE
    def event_stream():
        full_plan = ""

        stream = _get_llm().chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=1500,
            stream=True,
        )

        for chunk in stream:
            if chunk.choices[0].delta.content:
                token = chunk.choices[0].delta.content
                full_plan += token
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

        # Trim sources to top 10
        sources = _deduplicate_sources(all_hits)[:10]
        yield f"data: {json.dumps({'type': 'done', 'plan': full_plan, 'sources': sources})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Document Audit ─────────────────────────────────────────────────
AUDIT_TOPICS = [
    "deployment approval",
    "access control",
    "incident response",
    "data retention",
    "monitoring alerting",
    "remote work policy",
    "code review process",
    "onboarding process",
    "security compliance",
]

BATCH_SIZE = 3
TOP_K = 5
EXCERPT_CHARS = 350


def _extract_json(text: str) -> dict:
    """4-step JSON extraction from LLM response."""
    import re

    # 1. Raw parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. Code fence
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except (json.JSONDecodeError, TypeError):
            pass

    # 3. Brace-count extraction
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start:i + 1])
                except (json.JSONDecodeError, TypeError):
                    break

    # 4. Fallback
    return {
        "departments": [],
        "topics_checked": 0,
        "conflicts": [],
        "clean": [],
        "no_docs": [],
        "summary": "Failed to parse AI response",
    }


def _build_audit_prompt(
    batch_topics: list[str],
    dept_searches: dict[str, dict[str, list[dict]]],
    departments: list[str],
) -> str:
    """Build a focused prompt for one batch of topics."""
    dept_list = " and ".join(departments)
    topic_list = ", ".join(f'"{t}"' for t in batch_topics)

    context = ""
    for topic in batch_topics:
        for dept in departments:
            results = dept_searches[dept].get(topic, [])
            context += f'\n=== Topic: "{topic}" | Dept: {dept} ===\n'
            if not results:
                context += "(no documents found)\n"
            else:
                for j, r in enumerate(results):
                    filename = r["source"].split("/")[-1]
                    excerpt = r["text"][:EXCERPT_CHARS]
                    context += (
                        f"[{j + 1}] {filename} (score: {r['score']:.2f})\n"
                        f"{excerpt}\n\n"
                    )

    return (
        f"You are auditing internal documents from: {dept_list}.\n\n"
        f"Only analyze these topics: {topic_list}.\n\n"
        f"Below are search results for these topics across each department.\n"
        f"For each topic, check if documents from different departments "
        f"CONTRADICT each other.\n\n"
        f"{context}\n"
        f"=== INSTRUCTIONS ===\n"
        f'- If only one dept has docs for a topic → add to "no_docs"\n'
        f'- If both depts have docs but no contradiction → add to "clean"\n'
        f'- If docs CONTRADICT → add to "conflicts" with quotes from BOTH sides\n'
        f'- For each conflict, provide a concrete suggestion and recommended steps\n\n'
        f"Return ONLY valid JSON (no markdown, no extra text):\n"
        f'{{\n  "departments": {json.dumps(departments)},\n'
        f'  "topics_checked": {len(batch_topics)},\n'
        f'  "conflicts": [\n'
        f'    {{\n      "topic": "...",\n      "docs_found": true,\n'
        f'      "depts_compared": ["deptA", "deptB"],\n'
        f'      "conflict_found": true,\n'
        f'      "severity": "low/medium/high",\n'
        f'      "finding": "1-2 sentence summary",\n'
        f'      "dept_a_doc": "filename",\n'
        f'      "dept_a_quote": "quote from dept A",\n'
        f'      "dept_b_doc": "filename",\n'
        f'      "dept_b_quote": "quote from dept B"\n'
        f"    }}\n"
        f"  ],\n"
        f'  "clean": ["topic1"],\n'
        f'  "no_docs": ["topic2"],\n'
        f'  "summary": "X conflicts, Y clean, Z no docs",\n'
        f'  "suggestions": [\n'
        f'    {{\n      "topic": "deployment approval",\n'
        f'      "action": "Align deployment approval workflows across depts",\n'
        f'      "involved_depts": ["Engineering", "Security"]\n'
        f"    }}\n"
        f"  ],\n"
        f'  "steps": ["Step 1: Review current policies", "Step 2: Draft unified policy", "Step 3: Approve and publish"]\n'
        f"}}"
    )


def _call_llm_for_batch(prompt: str) -> dict:
    """Call DeepSeek and return parsed JSON. Runs in thread pool."""
    resp = _get_llm().chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a document auditor for TechCorp. All search results "
                    "are provided in the prompt. Do NOT search for anything — "
                    "just analyze the given data. Find contradictions across "
                    "departments. Return ONLY valid JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return _extract_json(resp.choices[0].message.content)


@app.post("/audit", response_model=AuditResponse)
def audit_documents(req: AuditRequest):
    """Run cross-department document audit.

    Searches 9 topics across selected departments directly via Qdrant,
    batches into 3 groups, calls DeepSeek in parallel for focused analysis,
    and merges results into one conflict report.
    """
    departments = req.departments
    if len(departments) < 2:
        raise HTTPException(400, "Select at least 2 departments to compare.")

    # ── Step 1: Search all topics × departments directly via Qdrant ──
    dept_searches: dict[str, dict[str, list[dict]]] = {}
    for dept in departments:
        dept_searches[dept] = {}
        for topic in AUDIT_TOPICS:
            results = searcher.search(
                topic, top_k=TOP_K, category=dept, rerank=True
            )
            dept_searches[dept][topic] = results

    # ── Step 2: Build batch prompts ──
    topic_batches = [
        AUDIT_TOPICS[i:i + BATCH_SIZE]
        for i in range(0, len(AUDIT_TOPICS), BATCH_SIZE)
    ]
    batch_prompts = [
        _build_audit_prompt(batch, dept_searches, departments)
        for batch in topic_batches
    ]

    # ── Step 3: Call LLM for each batch in parallel ──
    results_by_idx: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=len(batch_prompts)) as executor:
        futures = {
            executor.submit(_call_llm_for_batch, prompt): i
            for i, prompt in enumerate(batch_prompts)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results_by_idx[idx] = future.result()
            except Exception as e:
                results_by_idx[idx] = {
                    "departments": departments,
                    "topics_checked": len(topic_batches[idx]),
                    "conflicts": [],
                    "clean": [],
                    "no_docs": [],
                    "summary": f"Batch {idx + 1} failed: {str(e)[:100]}",
                }

    batch_results = [results_by_idx[i] for i in sorted(results_by_idx)]

    # ── Step 4: Merge results ──
    seen: dict[str, set] = {"conflicts": set(), "clean": set(), "no_docs": set()}
    conflicts: list = []
    clean: list = []
    no_docs: list = []
    suggestions: list = []
    steps: list = []

    for batch in batch_results:
        for c in batch.get("conflicts", []):
            if c["topic"] not in seen["conflicts"]:
                seen["conflicts"].add(c["topic"])
                conflicts.append(c)
        for t in batch.get("clean", []):
            if t not in seen["clean"]:
                seen["clean"].add(t)
                clean.append(t)
        for t in batch.get("no_docs", []):
            if t not in seen["no_docs"]:
                seen["no_docs"].add(t)
                no_docs.append(t)
        suggestions.extend(batch.get("suggestions", []))
        steps.extend(batch.get("steps", []))

    total_topics = sum(r.get("topics_checked", 0) for r in batch_results)

    return AuditResponse(
        departments=departments,
        topics_checked=total_topics,
        conflicts=conflicts,
        clean=clean,
        no_docs=no_docs,
        summary=(
            f"{len(conflicts)} conflicts, {len(clean)} clean, "
            f"{len(no_docs)} no docs ({len(batch_results)} batches)"
        ),
        suggestions=suggestions,
        steps=steps,
    )


# ── Knowledge Gap Endpoints ───────────────────────────────────────
@app.post("/knowledge-gap", response_model=GapRequestItem)
def create_gap_request(req: GapRequest):
    """Create a new knowledge-gap request when RAG can't answer.

    Stores the request in gap_requests.json so it appears in the
    Requests & Approvals dashboard.
    """
    gaps = _load_gaps()

    gap_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()

    item = {
        "id": gap_id,
        "query": req.query,
        "suggested_department": req.suggested_department,
        "requester_name": req.requester_name,
        "message": req.message,
        "status": "pending",
        "draft_content": None,
        "draft_generated_at": None,
        "created_at": now,
        "approved_at": None,
        "confirmed_at": None,
    }
    gaps.append(item)
    _save_gaps(gaps)
    return item


@app.get("/knowledge-gap", response_model=list[GapRequestItem])
def list_gap_requests(status: str | None = None):
    """List all knowledge-gap requests, optionally filtered by status."""
    gaps = _load_gaps()
    if status:
        gaps = [g for g in gaps if g.get("status") == status]
    return sorted(gaps, key=lambda g: g["created_at"], reverse=True)


class DraftCallbackPayload(BaseModel):
    draft_content: str


@app.post("/knowledge-gap/{gap_id}/approve", response_model=GapRequestItem)
def approve_gap_request(gap_id: str):
    """Trigger n8n webhook to generate a draft and read the response directly.

    Sends the gap data to n8n. n8n generates a draft with DeepSeek and
    returns it via the Respond node. The draft is stored immediately.
    """
    import httpx

    gaps = _load_gaps()
    gap = next((g for g in gaps if g["id"] == gap_id), None)
    if not gap:
        raise HTTPException(status_code=404, detail="Gap request not found")
    if gap["status"] != "pending":
        raise HTTPException(status_code=400, detail="Only pending requests can be approved")

    try:
        resp = httpx.post(
            N8N_WEBHOOK_URL,
            json={
                "id": gap["id"],
                "query": gap["query"],
                "suggested_department": gap["suggested_department"],
                "requester_name": gap.get("requester_name", "Anonymous"),
                "message": gap.get("message", ""),
                "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        if not resp.text or not resp.text.strip():
            raise HTTPException(status_code=502, detail="n8n returned empty response — is the workflow activated?")
        data = resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"n8n returned {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"n8n webhook failed: {e}")

    # Store the draft returned by n8n's Respond node
    now = datetime.now(timezone.utc).isoformat()
    gap["draft_content"] = data.get("draft_content", "")
    gap["draft_generated_at"] = now
    gap["status"] = "draft_ready"
    _save_gaps(gaps)
    return gap


@app.post("/knowledge-gap/{gap_id}/draft", response_model=GapRequestItem)
def save_gap_draft(gap_id: str, payload: DraftCallbackPayload):
    """Called by n8n after DeepSeek generates a draft.

    Stores the draft content inline in gap_requests.json and sets
    status to "draft_ready" so it appears in the Drafts tab.
    """
    gaps = _load_gaps()
    gap = next((g for g in gaps if g["id"] == gap_id), None)
    if not gap:
        raise HTTPException(status_code=404, detail="Gap request not found")

    if not payload.draft_content.strip():
        raise HTTPException(status_code=400, detail="Draft content is empty")

    now = datetime.now(timezone.utc).isoformat()
    gap["draft_content"] = payload.draft_content
    gap["draft_generated_at"] = now
    gap["status"] = "draft_ready"
    _save_gaps(gaps)
    return gap


def _slug_from_markdown(md_text: str, fallback: str = "draft") -> str:
    """Extract H1 title from markdown and return a URL-safe slug."""
    for line in md_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# ") and len(stripped) > 2:
            title = stripped[2:].strip()
            # Create slug: lowercase, replace non-alnum with hyphens, collapse
            slug = "".join(c.lower() if c.isalnum() or c == " " else "" for c in title)
            slug = "-".join(slug.split())[:80].strip("-")
            return slug or fallback
    return fallback


def _markdown_to_pdf(md_text: str, output_path: Path) -> None:
    """Convert markdown text to a PDF file using pymupdf (fitz)."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    rect = fitz.Rect(72, 72, page.rect.width - 72, page.rect.height - 72)
    y = rect.y0

    for line in md_text.split("\n"):
        # Skip empty lines
        if not line.strip():
            y += 6
            continue

        # Determine font size based on markdown heading level
        if line.startswith("# "):
            fontsize = 18
            text = line[2:].strip()
            y += 4
        elif line.startswith("## "):
            fontsize = 14
            text = line[2:].strip()
            y += 2
        elif line.startswith("### "):
            fontsize = 12
            text = line[3:].strip()
        elif line.startswith("- ") or line.startswith("* "):
            fontsize = 11
            text = "  • " + line[2:].strip()
        elif line.startswith("> "):
            fontsize = 10
            text = line[2:].strip()
        elif line.startswith("```"):
            fontsize = 9
            text = ""
        else:
            fontsize = 11
            text = line.strip()

        if not text:
            y += 4
            continue

        # Check if we need a new page
        if y + fontsize + 4 > rect.y1:
            page = doc.new_page()
            y = rect.y0

        # Bold markers
        text = text.replace("**", "")

        page.insert_text(
            fitz.Point(rect.x0, y + fontsize),
            text[:500],
            fontsize=fontsize,
            fontname="helv",
        )
        y += fontsize + 6

    doc.save(str(output_path))
    doc.close()


@app.post("/knowledge-gap/{gap_id}/confirm", response_model=GapRequestItem)
def confirm_gap_request(gap_id: str):
    """Save a reviewed draft to the department folder and index it in Qdrant.

    Only callable on items with status "draft_ready". Writes the markdown
    to knowledge_base/{dept}/gap_{id}.md, indexes it in Qdrant, and sets
    status to "approved".
    """
    gaps = _load_gaps()
    gap = next((g for g in gaps if g["id"] == gap_id), None)
    if not gap:
        raise HTTPException(status_code=404, detail="Gap request not found")
    if gap["status"] != "draft_ready":
        raise HTTPException(
            status_code=400,
            detail=f"Only draft_ready items can be confirmed. Current: {gap.get('status')}",
        )
    if not gap.get("draft_content", "").strip():
        raise HTTPException(status_code=400, detail="No draft content to confirm")

    dept = gap["suggested_department"]
    now = datetime.now(timezone.utc).isoformat()

    # Convert markdown to PDF with filename derived from the draft title
    slug = _slug_from_markdown(gap["draft_content"], gap_id)
    target_dir = Path(KB_PATH) / dept
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{slug}.pdf"

    # Avoid overwriting — append suffix if file exists
    if target_path.exists():
        target_path = target_dir / f"{slug}_{gap_id[:4]}.pdf"

    _markdown_to_pdf(gap["draft_content"], target_path)

    # Index in Qdrant
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import PointStruct
        from fastembed import TextEmbedding

        text = gap["draft_content"]
        embed_model = TextEmbedding()
        embedding = list(embed_model.embed([f"[{target_path.name}]\n{text[:2000]}"]))[0]

        client = QdrantClient(
            host=os.getenv("QDRANT_HOST", "localhost"),
            port=int(os.getenv("QDRANT_PORT", "6333")),
        )

        max_id = 0
        try:
            existing, _ = client.scroll(
                collection_name="knowledge_base", limit=100,
                with_payload=False, with_vectors=False,
            )
            if existing:
                max_id = max(p.id for p in existing)
        except Exception:
            pass

        point = PointStruct(
            id=max_id + 1,
            vector=embedding.tolist(),
            payload={
                "text": f"[{target_path.name}]\n{text[:2000]}",
                "source": str(target_path),
                "category": dept,
            },
        )
        client.upsert(collection_name="knowledge_base", points=[point])
        print(f"Indexed confirmed gap document: {target_path.name}")
    except Exception as e:
        print(f"Indexing failed for confirmed gap {gap_id}: {e}")

    gap["status"] = "approved"
    gap["approved_at"] = now
    gap["confirmed_at"] = now
    _save_gaps(gaps)
    return gap


@app.delete("/knowledge-gap/{gap_id}")
def delete_gap_request(gap_id: str):
    """Delete a gap request permanently. Works on any status except approved."""
    gaps = _load_gaps()
    gap = next((g for g in gaps if g["id"] == gap_id), None)
    if not gap:
        raise HTTPException(status_code=404, detail="Gap request not found")
    if gap["status"] == "approved":
        raise HTTPException(status_code=400, detail="Approved requests cannot be deleted")
    gaps = [g for g in gaps if g["id"] != gap_id]
    _save_gaps(gaps)
    return {"status": "deleted", "id": gap_id}