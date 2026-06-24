import fitz
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from fastembed import TextEmbedding
from langchain.text_splitter import RecursiveCharacterTextSplitter


def _load_and_chunk_single(file_path: str, category: str) -> list[dict]:
    """Load a single PDF and chunk it. Returns list of {text, source, category} dicts."""
    doc = fitz.open(file_path)
    text = " ".join([page.get_text() for page in doc])
    doc.close()

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = []
    for split in splitter.split_text(text):
        chunks.append({"text": split, "source": file_path, "category": category})
    return chunks


def embed_and_upload(chunks: list[dict], collection_name: str = "knowledge_base") -> None:
    """
    Embed chunks using fastembed and upload to Qdrant.
    Each chunk dict: {"text": str, "source": str, "category": str}
    """
    # 1. Init clients
    client = QdrantClient(host="localhost", port=6333)
    model = TextEmbedding()  # default: BAAI/bge-small-en-v1.5 → 384 dims

    # 2. Recreate collection
    if client.collection_exists(collection_name):
        client.delete_collection(collection_name)

    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(
            size=384,
            distance=Distance.COSINE,
        ),
    )

    # 3. Embed + prepare points
    points = []
    for idx, chunk in enumerate(chunks):
        embedding = list(model.embed([chunk["text"]]))[0].tolist()

        points.append(
            PointStruct(
                id=idx,
                vector=embedding,
                payload={
                    "text": chunk["text"],
                    "source": chunk["source"],
                    "category": chunk["category"],
                },
            )
        )

    # 4. Upload in batches (Qdrant accepts max 100MB per request)
    batch_size = 100
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        client.upsert(collection_name=collection_name, points=batch)
        print(f"Uploaded {min(i + batch_size, len(points))}/{len(points)} points")

    print(f"Done: {len(points)} chunks indexed in '{collection_name}'")


def embed_and_upload_single(
    file_path: str,
    category: str,
    host: str = "localhost",
    port: int = 6333,
    collection_name: str = "knowledge_base",
) -> int:
    """Incrementally index a single PDF without touching existing chunks.

    Loads and chunks the file, finds the next available point IDs in Qdrant,
    embeds and upserts only the new chunks. Returns the number of chunks indexed.
    """
    # 1. Load and chunk the single file
    chunks = _load_and_chunk_single(file_path, category)
    if not chunks:
        print(f"No text extracted from {file_path}")
        return 0

    # 2. Connect to Qdrant
    client = QdrantClient(host=host, port=port)

    # Make sure the collection exists (should already, but be safe)
    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        )

    # 3. Find the next available point ID (max existing + 1)
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

    next_id = max_id + 1

    # 4. Embed + prepare new points (sequential IDs from next_id)
    model = TextEmbedding()
    points = []
    for i, chunk in enumerate(chunks):
        embedding = list(model.embed([chunk["text"]]))[0].tolist()
        points.append(
            PointStruct(
                id=next_id + i,
                vector=embedding,
                payload={
                    "text": chunk["text"],
                    "source": chunk["source"],
                    "category": chunk["category"],
                },
            )
        )

    # 5. Upsert in batches
    batch_size = 100
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        client.upsert(collection_name=collection_name, points=batch)

    print(f"Incrementally indexed {len(points)} chunks from {file_path} (IDs {next_id}–{next_id + len(points) - 1})")
    return len(points)