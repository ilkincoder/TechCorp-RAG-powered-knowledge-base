"""
MCP Server — exposes RAG tools for n8n consumption.

n8n's MCP Client node connects to this server (via SSE) and can call:
- search_knowledge_base: semantic search over the knowledge base
- generate_onboarding_context: curated document retrieval for onboarding

Run standalone:
    python src/agent/mcp_server.py
"""

import json
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent

from retrieval.searcher import Searcher
from prompts.onboarding_templates import build_onboarding_prompt

# ── MCP Server ──────────────────────────────────────────────────────
server = Server("techcorp-knowledge-base")

# Retry Qdrant connection on startup (container may still be booting)
import time as _time


def _create_searcher(max_retries: int = 30, delay: float = 2.0):
    host = os.getenv("QDRANT_HOST", "localhost")
    port = int(os.getenv("QDRANT_PORT", "6333"))

    for attempt in range(1, max_retries + 1):
        try:
            s = Searcher(host=host, port=port)
            print(f"Connected to Qdrant at {host}:{port}")
            return s
        except Exception as e:
            if attempt == max_retries:
                raise
            print(
                f"Qdrant connection attempt {attempt}/{max_retries} failed: {e}. "
                f"Retrying in {delay}s..."
            )
            _time.sleep(delay)


searcher = _create_searcher()


# ── Tool implementations ────────────────────────────────────────────
async def _search_knowledge_base(query: str, category: str | None = None, top_k: int = 5) -> list[dict]:
    """Semantic search over TechCorp's internal knowledge base."""
    results = searcher.search(query, top_k=top_k, category=category, rerank=True)
    return results


async def _generate_onboarding_context(role: str, department: str, experience: str) -> dict:
    """Retrieve curated documents specifically for creating an onboarding plan."""
    queries = [
        f"{department} onboarding process and handbook",
        f"{role} technical skills and tools setup guide",
        "IT onboarding computer access and accounts",
        "company security policy and best practices",
        "team workflow code review and deployment process",
    ]

    all_context: list[str] = []
    seen = set()

    for q in queries:
        hits = searcher.search(q, top_k=3, rerank=True)
        for h in hits:
            key = h["source"] + h["text"][:80]
            if key not in seen:
                seen.add(key)
                all_context.append(
                    f"[{h['source'].split('/')[-1]}] (category: {h['category']})\n{h['text']}"
                )

    context_text = "\n\n---\n\n".join(all_context) if all_context else "No relevant documents found."

    prompt = build_onboarding_prompt(
        role=role,
        department=department,
        experience=experience,
        context=context_text,
    )

    return {
        "context": context_text,
        "prompt": prompt,
        "sources_count": len(all_context),
    }


# ── MCP Tool registry ───────────────────────────────────────────────
@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """Return the list of available tools."""
    return [
        Tool(
            name="search_knowledge_base",
            description=(
                "Semantic search over TechCorp's internal knowledge base. "
                "Use this tool to find relevant documents, policies, and guides "
                "for any topic. Returns the most relevant text chunks with source info."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for (e.g. 'backend coding standards').",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional filter — 'AI', 'Customer_Support', 'Engineering', 'HR', 'Operations', 'Security'.",
                    },
                    "top_k": {
                        "type": "integer",
                        "default": 5,
                        "description": "Number of results (default 5, max 20).",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="generate_onboarding_context",
            description=(
                "Retrieve curated documents specifically for creating an onboarding plan. "
                "Searches across all relevant categories (HR, Engineering, IT, Security) "
                "and compiles context needed to generate a personalized training plan."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "description": "Job title (e.g. 'Junior Backend Engineer').",
                    },
                    "department": {
                        "type": "string",
                        "description": "Department name (e.g. 'Engineering').",
                    },
                    "experience": {
                        "type": "string",
                        "description": "Experience level description (e.g. '2 years Python').",
                    },
                },
                "required": ["role", "department", "experience"],
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls from MCP clients."""
    if name == "search_knowledge_base":
        results = await _search_knowledge_base(
            query=arguments["query"],
            category=arguments.get("category"),
            top_k=arguments.get("top_k", 5),
        )
        return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False, indent=2))]

    elif name == "generate_onboarding_context":
        result = await _generate_onboarding_context(
            role=arguments["role"],
            department=arguments["department"],
            experience=arguments["experience"],
        )
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    else:
        raise ValueError(f"Unknown tool: {name}")


# ── Entrypoint ──────────────────────────────────────────────────────
def main():
    import uvicorn
    from starlette.responses import Response
    from mcp.server.sse import SseServerTransport
    from api.main import app as fastapi_app

    sse = SseServerTransport("/messages")

    # ── Response proxies ──────────────────────────────────────────
    # Starlette calls response.__call__(scope, receive, send) to transmit.
    # We override it to delegate the raw ASGI triplet to the MCP transport
    # instead — no path stripping, no signature mismatch, no middleware.

    class MCPSSEResponse(Response):
        """Long-lived SSE connection: GET /mcp/sse"""

        async def __call__(self, scope, receive, send):
            async with sse.connect_sse(scope, receive, send) as streams:
                await server.run(
                    streams[0], streams[1], server.create_initialization_options()
                )

    class MCPMessagesResponse(Response):
        """POST /messages — JSON-RPC tool calls from the MCP client"""

        async def __call__(self, scope, receive, send):
            await sse.handle_post_message(scope, receive, send)

    # ── Routes ───────────────────────────────────────────────────
    @fastapi_app.get("/mcp/sse")
    async def mcp_sse_endpoint():
        return MCPSSEResponse()

    @fastapi_app.post("/messages")
    async def mcp_messages_endpoint():
        return MCPMessagesResponse()

    port = int(os.getenv("MCP_PORT", "8000"))
    print(f"Server running on http://0.0.0.0:{port}")
    print(f"  MCP SSE:     http://0.0.0.0:{port}/mcp/sse")
    print(f"  MCP messages: http://0.0.0.0:{port}/messages")
    print(f"  API docs:    http://0.0.0.0:{port}/docs")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
