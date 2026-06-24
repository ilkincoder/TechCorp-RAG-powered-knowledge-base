# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# System dependencies (only what PyMuPDF and some wheels need)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies with persistent pip cache
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy project source
COPY . .

# Docker-internal hostnames
ENV QDRANT_HOST=qdrant
ENV QDRANT_PORT=6333
ENV MCP_PORT=8000
ENV MCP_SSE_PATH=/mcp/sse

EXPOSE 8000

CMD ["python", "src/agent/mcp_server.py"]