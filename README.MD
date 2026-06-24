# TechCorp Knowledge Base

RAG-powered knowledge base with multi-agent orchestration — semantic search, onboarding plan generation, cross-department document auditing, and a knowledge-gap pipeline. Built for a fictional company ("TechCorp") with 6 departments.

## Architecture

```
React UI (Vite :3000)
      │  /api/* → FastAPI :8000
      │  /webhook/* → n8n :5678
      ▼
FastAPI Backend (:8000)
  ├─ Serves React static build
  ├─ RAG Agent (LangGraph: rewrite → retrieve → generate)
  ├─ MCP Server (SSE: /mcp/sse, POST /messages)
  ├─ Direct Qdrant search + LLM generation
  └─ Routes complex queries → n8n webhooks
      │                    │
      ▼                    ▼
Qdrant (:6333)       n8n (:5678)
  Vector DB             Workflow automation
                        ├─ MCP Client → calls FastAPI's MCP tools
                        ├─ AI Agent nodes → DeepSeek
                        └─ Webhook triggers / responses
```

### Docker services

| Service | Container | Port | Purpose |
|---------|----------|------|---------|
| `qdrant` | qdrant/qdrant | 6333 (REST), 6334 (gRPC) | Vector DB storing chunk embeddings |
| `backend` | techcorp-backend (Dockerfile) | 8000 | FastAPI + MCP server |
| `n8n` | docker.n8n.io/n8nio/n8n | 5678 | Workflow automation, MCP client, LLM chains |

## Project Structure

```
.
├── docker-compose.yml          # 3-service orchestration
├── Dockerfile                  # Python 3.11-slim backend image
├── .dockerignore               # Excludes build/runtime cruft from Docker context
├── .gitignore                  # Excludes runtime data, secrets, node_modules
├── requirements.txt            # Python dependencies
├── .env                        # API keys and host config
│
├── src/
│   ├── api/main.py             # FastAPI app (~1400 lines, all endpoints)
│   ├── agent/
│   │   ├── rag_agent.py        # LangGraph RAG agent (rewrite→retrieve→generate)
│   │   └── mcp_server.py       # MCP server (SSE transport, 2 tools)
│   ├── retrieval/
│   │   ├── searcher.py         # Qdrant semantic search + cross-encoder rerank
│   │   └── file_scanner.py     # Disk scanner for knowledge_base/ PDFs
│   ├── ingestion/
│   │   ├── embedder.py           # fastembed embedding + Qdrant upsert (single-file incremental)
│   │   └── embedder_v2.py        # Parent-child chunking ingestion (knowledge_base_v2 collection)
│   ├── prompts/
│   │   └── onboarding_templates.py  # Few-Shot + CoT prompt builder
│   ├── evaluation/
│   │   └── run_eval.py              # RAGAS eval: V1 (naive) vs V2 (parent-child)
│
├── frontend/
│   ├── .gitignore              # Excludes dist/, node_modules/, .DS_Store
│   ├── package.json            # React 18 + Vite 5
│   ├── vite.config.js          # Dev proxy: /api→:8000, /webhook→:5678
│   └── src/
│       ├── main.jsx            # React entry point
│       ├── App.jsx             # 3-column layout: sidebar | main | chat
│       ├── App.css             # Dark-theme styles (~500 lines)
│       ├── api.js              # All API client functions + SSE streamers
│       ├── OnboardingDashboard.jsx  # Onboarding plan generator UI
│       ├── DocumentAudit.jsx       # Cross-dept audit UI
│       └── ProjectsDashboard.jsx   # Knowledge gap requests & approvals
│
├── knowledge_base/             # Source documents (PDFs) by department
│   ├── AI/
│   ├── Customer_Support/
│   ├── Engineering/
│   ├── HR/
│   ├── Operations/
│   ├── Security/
│   └── gap_requests.json       # Knowledge gap request store (drafts stored inline)
│
├── n8n-workflow.json           # Audit workflow (direct REST calls, 7 nodes)
├── n8n-chat-workflow.json      # MCP chat workflow for complex queries
├── n8n-draft-generator.json    # Draft generation workflow (cron → DeepSeek)
│
├── qdrant_storage/             # Qdrant persistent volume
└── n8n_data/                   # n8n persistent volume (workflows, DB)
```

### Frontend Views

| View | Component | Description |
|------|-----------|-------------|
| **Home** | `App.jsx` → `HomeView` | File browser (grid/list) with upload, sort, and department filter. Drag-and-drop PDF upload with incremental indexing. |
| **Department** | `App.jsx` → `DepartmentFilesView` | Filtered file list for a single department. Links to inline PDF viewer. |
| **Requests & Approvals** | `ProjectsDashboard.jsx` | Full knowledge-gap lifecycle: pending requests, approve → n8n draft generation, review → confirm → PDF + Qdrant index. |
| **Onboarding** | `OnboardingDashboard.jsx` | Role + department + experience → streaming 4-week plan generation with source attribution. |
| **Audit** | `DocumentAudit.jsx` | Multi-department document contradiction finder. 9 topics × N departments, batch-parallel LLM analysis. |
| **Evaluations** | `EvalDashboard.jsx` | RAGAS metrics dashboard: radar charts, bar charts, per-query trace viewer comparing V1 vs V2 retrieval. |
| **Team** | `App.jsx` → `TeamView` | Project resume: tech stack, feature list, department tags. |

## API Endpoints

### Core

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check + server start time |
| `GET` | `/files` | List all PDFs in knowledge_base/ with indexing status |
| `GET` | `/files/view/{filename}` | Serve PDF inline (path-traversal protected) |
| `POST` | `/files/upload` | Upload PDF → save to disk → embed + index in Qdrant |
| `GET` | `/departments` | List department folders in knowledge_base/ |

### Chat & RAG

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/chat/stream` | Multi-turn chat via LangGraph RAG agent with SSE token streaming |

### Smart Chat (Classifier Router)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/chat/smart` | Classifies query → simple (direct RAG) or complex (n8n MCP agent) |
| `POST` | `/chat/smart/stream` | SSE streaming version with route info |

**Query classifier:** Pattern-matches for multi-department mentions and complex markers (compare, audit, contradiction, etc.). Falls back to LLM for ambiguous cases. Simple path takes ~2-3s, complex path ~8-12s. If n8n is unreachable, complex path silently falls back to simple RAG.

### Onboarding

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/onboarding/generate/stream` | SSE streaming version (direct LLM streaming) |
| `POST` | `/onboarding/n8n/stream` | FastAPI retrieves + builds prompt, n8n handles DeepSeek, streams back |

### Document Audit

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/audit` | Cross-department audit. Searches 9 topics × N departments, batches 3 topics per LLM call with ThreadPoolExecutor, merges results. Returns conflicts, clean topics, no-docs, suggestions, steps. |

### Knowledge Gap Pipeline

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/knowledge-gap` | Create gap request. Body: `{query, suggested_department, requester_name, message}` |
| `GET` | `/knowledge-gap` | List all gap requests. Query: `?status=pending\|draft_ready\|approved` |
| `POST` | `/knowledge-gap/{id}/approve` | Trigger n8n to generate a draft via DeepSeek. n8n responds with draft content → status becomes `draft_ready` |
| `POST` | `/knowledge-gap/{id}/draft` | Callback: n8n posts generated draft content. Sets status to `draft_ready` |
| `POST` | `/knowledge-gap/{id}/confirm` | Convert markdown draft → PDF → save to department folder → index in Qdrant. Sets status to `approved` |
| `DELETE` | `/knowledge-gap/{id}` | Delete a gap request (except approved ones) |

### MCP (Model Context Protocol)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/mcp/sse` | SSE connection endpoint for MCP clients (n8n) |
| `POST` | `/messages` | JSON-RPC message endpoint for MCP tool calls |

**MCP Tools exposed:**
- `search_knowledge_base(query, category?, top_k)` — semantic search
- `generate_onboarding_context(role, department, experience)` — curated retrieval + prompt assembly

## Key Data Flows

### Smart Chat Routing
```
User message
  → classify_query()
    → SIMPLE: RAGAgent.ask_stream() (LangGraph: rewrite→retrieve→generate, native SSE)
    → COMPLEX: httpx POST → n8n /webhook/chat-mcp → MCP Client calls search_knowledge_base
               → AI Agent generates answer → JSON response → simulated SSE to frontend
```

### Onboarding Plan Generation
```
User enters role + department + experience
  → 5 parallel semantic queries across Qdrant
  → Deduplicate chunks → build Few-Shot + CoT prompt
  → DeepSeek generates 4-week structured plan → SSE stream to React
```

### Document Audit
```
User selects 2+ departments
  → For each of 9 topics × N departments: search Qdrant directly
  → Batch 3 topics per LLM call (ThreadPoolExecutor, parallel)
  → Each batch: DeepSeek analyzes contradictions, returns JSON
  → Merge results: deduplicate conflicts/clean/no_docs across batches
  → Return unified report with suggestions and action steps
```

### Knowledge Gap Lifecycle
```
RAG fails to answer
  → Chat shows "gap" event with suggested department
  → User clicks "Send Request" → POST /knowledge-gap (status: pending)
  → Admin sees request in "Requests & Approvals" → clicks Approve
  → POST /knowledge-gap/{id}/approve → n8n generates draft via DeepSeek
  → n8n responds with draft → stored in gap_requests.json (status: draft_ready)
  → Admin reviews draft → clicks Confirm
  → Markdown → PDF conversion (PyMuPDF) → saved to knowledge_base/{dept}/
  → Auto-indexed in Qdrant (status: approved)
```

### File Upload & Incremental Indexing
```
User drags/drops or selects PDF + department
  → POST /files/upload (multipart form)
  → File saved to knowledge_base/{dept}/ (auto-rename on collision)
  → embedder.embed_and_upload_single(): chunk → embed with fastembed → upsert to Qdrant
  → Returns FileInfo with indexed status
```

### RAG Evaluation Pipeline

The evaluation compares two retrieval strategies side-by-side to **identify which areas can be improved** — not just overall scores, but per-query behavior where one strategy outperforms the other.

```
python src/evaluation/run_eval.py
  → Seeds random questions from knowledge_base/ PDFs
  → Runs each question through both retrieval strategies:
       V1 (naive): 500-char fixed-size chunks
       V2 (parent-child): fine-grained child chunks → parent context
  → Computes RAGAS metrics:
       context_precision, context_recall, faithfulness, answer_relevancy
  → Outputs eval_results.json → rendered by EvalDashboard.jsx
       (radar chart, bar chart, per-query trace viewer)
```

The dashboard lets you drill into individual queries to see **where** V2 beats V1 and **why** — is it better at precision? recall? faithfulness on long documents? This pinpoints the next retrieval improvements worth pursuing (e.g., reranker tuning, chunk sizing, embedding model choice).

## Environment Variables (.env)

| Variable | Purpose | Default |
|----------|---------|---------|
| `DEEPSEEK_API_KEY` | LLM API key (DeepSeek) | required |
| `QDRANT_HOST` | Qdrant hostname | `localhost` |
| `QDRANT_PORT` | Qdrant REST port | `6333` |
| `N8N_ENCRYPTION_KEY` | n8n encryption key | required |
| `MCP_SERVER_URL` | MCP server URL for n8n | `http://host.docker.internal:8000/mcp` |

## Running the Project

```bash
# Start all services
docker compose up -d

# Frontend dev server (with hot reload + proxy)
cd frontend && npm run dev     # → http://localhost:3000

# Production build (static files, serve with any web server)
cd frontend && npm run build   # → output in frontend/dist/
```

### After code changes
- **Backend:** `docker compose restart backend` (no hot-reload in Docker)
- **Frontend:** Vite hot-reloads automatically
- **n8n workflows:** Must be re-imported manually in n8n UI after JSON file changes

## Known Quirks & Design Decisions

1. **DeepSeek model:** Use `deepseek-chat` (NOT `deepseek-reasoner`/v4-pro). Thinking-mode models break n8n's AI Agent node.
2. **n8n workflow persistence:** Workflows live in n8n's internal DB (`n8n_data/database.sqlite`). The JSON files in the repo are export snapshots — re-import after editing.
3. **MCP Server entrypoint:** `src/agent/mcp_server.py` is the Docker CMD. It mounts MCP routes onto the FastAPI app from `src/api/main.py` and starts uvicorn. The same FastAPI app serves both the REST API and MCP protocol.
4. **SSE streaming from n8n:** n8n returns complete responses (no streaming). FastAPI simulates SSE by chunking the response with small delays.
5. **Score normalization:** Cross-encoder reranker raw logits pass through sigmoid → [0,1] range. Frontend SourceCard clamps to `Math.min(Math.max(score, 0), 1) * 100`.
6. **Vite proxy:** `/api/*` → `localhost:8000` (strips `/api` prefix). `/webhook/*` → `localhost:5678`. `/webhook-test/*` → `localhost:5678`.
7. **LLM client:** Uses OpenAI-compatible SDK pointed at `https://api.deepseek.com`. Lazy-initialized to avoid httpx version conflicts at import time.
8. **Embeddings:** Uses `fastembed` (local, no API calls) for both ingestion and on-the-fly indexing of confirmed gap drafts.
9. **Session storage:** In-memory `dict[session_id, list[messages]]` — not persisted across restarts.
10. **Knowledge gaps store:** `knowledge_base/gap_requests.json` — simple JSON file, no database.