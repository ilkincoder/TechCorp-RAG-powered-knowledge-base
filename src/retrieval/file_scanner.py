"""Lightweight filesystem scanner for knowledge-base file metadata.

Unlike pdf_loader.py (which extracts full text via PyMuPDF), this module
only reads filesystem metadata — filename, size, modification date, and
category — and optionally checks Qdrant to see which files are indexed.
"""

import os
from pathlib import Path
from datetime import datetime


def scan_knowledge_base(base_path: str) -> list[dict]:
    """Scan the knowledge_base directory for all PDF files.

    Returns a list of dicts with keys:
        name     — filename only (e.g. "security-policy.pdf")
        path     — absolute filesystem path
        category — parent subdirectory name (e.g. "Security")
        size     — file size in bytes
        added    — modification date as "YYYY-MM-DD"
    """
    results: list[dict] = []
    for pdf_path in Path(base_path).rglob("*.pdf"):
        stat = os.stat(pdf_path)

        # Derive category from the directory immediately under knowledge_base/
        parts = pdf_path.parts
        try:
            kb_index = next(i for i, p in enumerate(parts) if p == "knowledge_base")
            category = (
                parts[kb_index + 1]
                if kb_index + 1 < len(parts) - 1
                else "general"
            )
        except StopIteration:
            category = "general"

        results.append({
            "name": pdf_path.name,
            "path": str(pdf_path),
            "category": category,
            "size": stat.st_size,
            "added": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
        })

    return results


def check_indexed_status(searcher) -> set[str]:
    """Return the set of source file paths that have chunks in Qdrant.

    Uses Qdrant's scroll API to collect unique ``source`` values from
    every point in the collection.  If Qdrant is unreachable the
    exception is caught and an empty set is returned so the caller can
    treat every file as "not indexed" instead of crashing.
    """
    indexed_sources: set[str] = set()
    try:
        next_offset = None
        while True:
            points, next_offset = searcher.client.scroll(
                collection_name=searcher.collection,
                limit=1000,
                offset=next_offset,
                with_payload=["source"],
                with_vectors=False,
            )
            for p in points:
                if p.payload and "source" in p.payload:
                    indexed_sources.add(p.payload["source"])
            if next_offset is None:
                break
    except Exception:
        # Qdrant unavailable — return empty set gracefully
        pass

    return indexed_sources