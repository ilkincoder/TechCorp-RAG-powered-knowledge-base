"""
Parent-Child chunking strategy — V2 improvement over naive chunking.

Creates two granularities from each PDF:
- Parent chunks (1000 chars, 100 overlap) — full context for the LLM
- Child chunks (250 chars, 50 overlap) — fine-grained for precise retrieval

Both are upserted into a separate collection ``knowledge_base_v2``.
Children carry a ``parent_id`` so retrieval can expand back to full context.
"""

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from fastembed import TextEmbedding
from langchain.text_splitter import RecursiveCharacterTextSplitter
import fitz


def _load_and_chunk_parent_child(file_path: str, category: str) -> list[dict]:
    """Load a single PDF and produce parent + child chunks.

    Returns list of dicts, each with:
        text, source, category, chunk_type ("parent" | "child"), parent_id
    """
    doc = fitz.open(file_path)
    text = " ".join([page.get_text() for page in doc])
    doc.close()

    # ── Parent chunks (coarse) ─────────────────────────────────
    parent_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000, chunk_overlap=100
    )
    parent_texts = parent_splitter.split_text(text)

    # ── Child chunks (fine) ────────────────────────────────────
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=250, chunk_overlap=50
    )

    # Build parent + child data (parent_point_id assigned later in upload fn)
    chunks_data = []
    for parent_idx, parent_text in enumerate(parent_texts):
        chunks_data.append({
            "text": parent_text,
            "source": file_path,
            "category": category,
            "chunk_type": "parent",
            "parent_idx": parent_idx,  # local index, mapped to real point ID later
        })

        child_texts = child_splitter.split_text(parent_text)
        for child_text in child_texts:
            chunks_data.append({
                "text": child_text,
                "source": file_path,
                "category": category,
                "chunk_type": "child",
                "parent_idx": parent_idx,
            })

    return chunks_data


def embed_and_upload_parent_child(
    file_path: str,
    category: str,
    host: str = "localhost",
    port: int = 6333,
    collection_name: str = "knowledge_base_v2",
) -> int:
    """Incrementally index a PDF with parent-child chunking.

    Creates collection if needed, builds parent+child chunks, embeds them,
    and upserts to Qdrant. Returns the number of chunks indexed.
    """
    # 1. Load and chunk
    chunks_data = _load_and_chunk_parent_child(file_path, category)
    if not chunks_data:
        print(f"No text extracted from {file_path}")
        return 0

    # 2. Connect to Qdrant
    client = QdrantClient(host=host, port=port)

    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        )

    # 3. Find next available point ID
    max_id = -1
    next_offset = None
    while True:
        points, next_offset = client.scroll(
            collection_name=collection_name,
            limit=1000,
            offset=next_offset,
            with_vectors=False,
        )
        for p in points:
            if p.id > max_id:
                max_id = p.id
        if next_offset is None:
            break

    # 4. Separate parents & children, assign real point IDs to parents
    parents = [d for d in chunks_data if d["chunk_type"] == "parent"]
    children = [d for d in chunks_data if d["chunk_type"] == "child"]

    next_id = max_id + 1

    # Build parent_idx → real point_id map
    parent_id_map = {}
    for i, p in enumerate(parents):
        parent_id_map[p["parent_idx"]] = next_id + i

    # Assign children their parent_point_id using the map
    for c in children:
        c["parent_point_id"] = parent_id_map[c["parent_idx"]]
        del c["parent_idx"]

    # Strip parent_idx from parents too (not needed in payload)
    for p in parents:
        del p["parent_idx"]

    # Combine: parents first (so they get contiguous IDs matching the map)
    final_chunks = parents + children

    # 5. Embed + prepare points
    model = TextEmbedding()
    points = []
    for i, chunk in enumerate(final_chunks):
        embedding = list(model.embed([chunk["text"]]))[0].tolist()
        payload = {
            "text": chunk["text"],
            "source": chunk["source"],
            "category": chunk["category"],
            "chunk_type": chunk["chunk_type"],
        }
        if chunk["chunk_type"] == "child":
            payload["parent_point_id"] = chunk["parent_point_id"]

        points.append(
            PointStruct(
                id=next_id + i,
                vector=embedding,
                payload=payload,
            )
        )

    # 5. Upsert in batches
    batch_size = 100
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        client.upsert(collection_name=collection_name, points=batch)

    print(
        f"Parent-child indexed {len(points)} chunks from {file_path} "
        f"(IDs {next_id}–{next_id + len(points) - 1})"
    )
    return len(points)


def index_all_pdfs(
    kb_path: str,
    host: str = "localhost",
    port: int = 6333,
    collection_name: str = "knowledge_base_v2",
) -> int:
    """Index every PDF under kb_path into the parent-child collection.

    Walks all subdirectories, derives category from the folder name,
    and incrementally indexes each file. Returns total chunk count.
    """
    from pathlib import Path

    total = 0
    for pdf_path in Path(kb_path).rglob("*.pdf"):
        category = pdf_path.parent.name
        try:
            n = embed_and_upload_parent_child(
                file_path=str(pdf_path),
                category=category,
                host=host,
                port=port,
                collection_name=collection_name,
            )
            total += n
        except Exception as e:
            print(f"Failed to index {pdf_path.name}: {e}")

    print(f"\nDone — {total} total chunks indexed into '{collection_name}'")
    return total