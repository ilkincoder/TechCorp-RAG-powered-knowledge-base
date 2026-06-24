import math

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from fastembed import TextEmbedding
from sentence_transformers import CrossEncoder


class Searcher:
    """Two-stage retrieval with optional cross-encoder reranking.

    Stage 1 — Bi-encoder (BGE): fast semantic search over all chunks.
    Stage 2 — Cross-encoder: precision rerank of top candidates.
    """

    RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = "knowledge_base",
    ):
        self.client = QdrantClient(host=host, port=port)
        self.bi_encoder = TextEmbedding()  # BAAI/bge-small-en-v1.5
        self.collection = collection_name
        self._cross_encoder = None  # lazy load

    @property
    def cross_encoder(self) -> CrossEncoder:
        if self._cross_encoder is None:
            self._cross_encoder = CrossEncoder(self.RERANK_MODEL)
        return self._cross_encoder

    # ── Public API ──────────────────────────────────────────────
    def search(
        self,
        query: str,
        top_k: int = 5,
        category: str | None = None,
        rerank: bool = True,
        rerank_candidates: int = 20,
    ) -> list[dict]:
        """Search for chunks relevant to the query.

        Args:
            query: Natural-language search query.
            top_k: Number of results to return.
            category: Optional category filter (e.g. "Security", "HR").
            rerank: If True, use cross-encoder to rerank results.
            rerank_candidates: Number of candidates to fetch before reranking.

        Returns:
            List of result dicts with keys: text, source, category, score.
        """
        # Stage 1 — Bi-encoder retrieval
        limit = rerank_candidates if rerank else top_k
        hits = self._vector_search(query, limit=limit, category=category)

        results = [
            {
                "text": h.payload["text"],
                "source": h.payload["source"],
                "category": h.payload["category"],
                "score": round(h.score, 4),
            }
            for h in hits
        ]

        # Stage 2 — Cross-encoder rerank
        if rerank and len(results) > top_k:
            results = self._rerank(query, results, top_k)

        return results

    def parent_child_retrieve(
        self,
        query: str,
        top_k: int = 5,
        category: str | None = None,
        child_limit: int = 20,
        collection: str = "knowledge_base_v2",
    ) -> list[dict]:
        """Parent-child retrieval: search fine-grained child chunks, return parent context.

        Stage 1 — Search child chunks only (via Qdrant filter on chunk_type="child")
        Stage 2 — Look up parent chunks by parent_id, deduplicate, return expanded context.

        Returns the same shape as ``search()`` — list of dicts with text, source, category, score.
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny
        from collections import OrderedDict

        query_vec = list(self.bi_encoder.embed([query]))[0].tolist()

        # Build filter: category filter + chunk_type="child"
        qdrant_filter = Filter(
            must=[
                FieldCondition(key="chunk_type", match=MatchValue(value="child")),
            ]
        )
        if category:
            qdrant_filter.must.append(
                FieldCondition(key="category", match=MatchValue(value=category))
            )

        # Stage 1: Search child chunks
        child_hits = self.client.search(
            collection_name=collection,
            query_vector=query_vec,
            query_filter=qdrant_filter,
            limit=child_limit,
        )

        if not child_hits:
            return []

        # Collect unique parent_point_ids in score order
        parent_point_ids = list(dict.fromkeys(
            h.payload.get("parent_point_id") for h in child_hits
            if h.payload and h.payload.get("parent_point_id") is not None
        ))[:top_k]

        if not parent_point_ids:
            return []

        # Stage 2: Retrieve parent chunks by their actual Qdrant point IDs
        parent_hits = self.client.retrieve(
            collection_name=collection,
            ids=parent_point_ids,
            with_payload=True,
            with_vectors=False,
        )

        # Build results — map parent_point_id → payload, sort by original order
        parent_map = {p.id: p.payload for p in parent_hits if p.payload}
        results = []
        for pid in parent_point_ids:
            payload = parent_map.get(pid)
            if payload:
                results.append({
                    "text": payload["text"],
                    "source": payload["source"],
                    "category": payload["category"],
                    "score": 1.0,  # parent score is derived from child ranking
                })

        return results

    def search_batch(
        self,
        queries: list[str],
        top_k: int = 5,
        category: str | None = None,
        rerank: bool = True,
    ) -> list[list[dict]]:
        """Search for multiple queries at once."""
        return [
            self.search(q, top_k=top_k, category=category, rerank=rerank)
            for q in queries
        ]

    # ── Internals ───────────────────────────────────────────────
    def _vector_search(self, query: str, limit: int, category: str | None):
        query_vec = list(self.bi_encoder.embed([query]))[0].tolist()

        qdrant_filter = None
        if category:
            qdrant_filter = Filter(
                must=[FieldCondition(key="category", match=MatchValue(value=category))]
            )

        return self.client.search(
            collection_name=self.collection,
            query_vector=query_vec,
            query_filter=qdrant_filter,
            limit=limit,
        )

    def _rerank(self, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        """Score candidates with cross-encoder and return top_k.

        Cross-encoder outputs raw logits (unbounded, can be negative).
        We apply sigmoid to normalize into a [0, 1] relevance score suitable
        for display as a percentage in the UI.
        """
        pairs = [(query, c["text"]) for c in candidates]
        raw_scores = self.cross_encoder.predict(pairs)

        for i, c in enumerate(candidates):
            c["score"] = round(self._sigmoid(float(raw_scores[i])), 4)

        candidates.sort(key=lambda c: c["score"], reverse=True)
        return candidates[:top_k]

    @staticmethod
    def _sigmoid(x: float) -> float:
        """Squash a raw logit into [0, 1]."""
        return 1.0 / (1.0 + math.exp(-x))