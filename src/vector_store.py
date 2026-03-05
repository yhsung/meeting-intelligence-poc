"""
Component 3: VectorStore
Uses ChromaDB as the persistent vector backend for meeting chunks.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import chromadb
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Embedding backend selection (mirrors chunker.py logic)
# ---------------------------------------------------------------------------
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "local").lower()

_openai_client: Optional[object] = None
_st_model: Optional[object] = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI  # type: ignore
        _openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _openai_client


def _get_st_model():
    global _st_model
    if _st_model is None:
        from sentence_transformers import SentenceTransformer  # type: ignore
        _st_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _st_model


def _embed(text: str) -> list[float]:
    """Produce an embedding vector for *text* using the configured backend."""
    if EMBEDDING_BACKEND == "openai":
        client = _get_openai_client()
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding
    else:
        model = _get_st_model()
        return model.encode(text).tolist()


# ---------------------------------------------------------------------------
# VectorStore
# ---------------------------------------------------------------------------

COLLECTION_NAME = "meetings"

# Project root is two levels up from this file (src/vector_store.py -> project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class VectorStore:
    """ChromaDB-backed vector store for meeting transcript chunks."""

    def __init__(self, db_path: str = "data/vectordb") -> None:
        path = Path(db_path)
        if not path.is_absolute():
            path = _PROJECT_ROOT / path
        path.mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(path=str(path))
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_meeting(self, video_id: str, chunks: list[dict]) -> None:
        """Add (or replace) all chunks for *video_id* in the collection."""
        # Remove stale data first so re-indexing is idempotent.
        self.remove_meeting(video_id)

        if not chunks:
            return

        ids: list[str] = []
        embeddings: list[list[float]] = []
        documents: list[str] = []
        metadatas: list[dict] = []

        for chunk in chunks:
            ids.append(chunk["chunk_id"])
            # Use pre-computed embedding when available; fall back to on-the-fly.
            emb = chunk.get("embedding")
            if not emb:
                emb = _embed(chunk["text"])
            embeddings.append(emb)
            documents.append(chunk["text"])
            metadatas.append(
                {
                    "video_id": chunk["video_id"],
                    "title": chunk.get("title", ""),
                    "start_time": float(chunk.get("start_time", 0.0)),
                    "end_time": float(chunk.get("end_time", 0.0)),
                }
            )

        self._collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def remove_meeting(self, video_id: str) -> None:
        """Delete all chunks belonging to *video_id*."""
        results = self._collection.get(
            where={"video_id": {"$eq": video_id}},
            include=[],  # only need IDs
        )
        existing_ids: list[str] = results.get("ids", [])
        if existing_ids:
            self._collection.delete(ids=existing_ids)

    def query(
        self,
        query_text: str,
        video_ids: list[str],
        top_k: int = 5,
    ) -> list[dict]:
        """
        Semantic search within the meetings specified by *video_ids*.

        Returns a list of RetrievedChunk dicts sorted by descending similarity.
        """
        if not video_ids:
            return []

        query_embedding = _embed(query_text)

        # Build a ChromaDB where-filter that restricts results to video_ids.
        if len(video_ids) == 1:
            where_filter: dict = {"video_id": {"$eq": video_ids[0]}}
        else:
            where_filter = {"video_id": {"$in": video_ids}}

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        retrieved: list[dict] = []
        ids_list = results.get("ids", [[]])[0]
        docs_list = results.get("documents", [[]])[0]
        meta_list = results.get("metadatas", [[]])[0]
        dist_list = results.get("distances", [[]])[0]

        for chunk_id, doc, meta, dist in zip(ids_list, docs_list, meta_list, dist_list):
            # ChromaDB cosine distance: score = 1 - distance
            score = float(1.0 - dist)
            retrieved.append(
                {
                    "chunk_id": chunk_id,
                    "video_id": meta.get("video_id", ""),
                    "title": meta.get("title", ""),
                    "text": doc,
                    "start_time": meta.get("start_time", 0.0),
                    "end_time": meta.get("end_time", 0.0),
                    "score": score,
                }
            )

        return retrieved

    def list_meetings(self) -> list[dict]:
        """
        Return aggregated metadata for every indexed meeting.

        Each entry: {"video_id": str, "title": str, "chunk_count": int}
        """
        results = self._collection.get(include=["metadatas"])
        metadatas: list[dict] = results.get("metadatas", []) or []

        aggregated: dict[str, dict] = {}
        for meta in metadatas:
            vid = meta.get("video_id", "")
            if vid not in aggregated:
                aggregated[vid] = {
                    "video_id": vid,
                    "title": meta.get("title", ""),
                    "chunk_count": 0,
                }
            aggregated[vid]["chunk_count"] += 1

        return list(aggregated.values())


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    print("=== VectorStore smoke test ===")

    with tempfile.TemporaryDirectory() as tmp_dir:
        store = VectorStore(db_path=tmp_dir)

        # --- Fabricate fake chunks with synthetic embeddings ----------------
        # Dimension must be consistent; we use 384 (all-MiniLM-L6-v2 default)
        # or just 4 for speed (local backend not invoked because we pre-supply
        # embeddings and then call query which DOES call _embed, so we skip
        # the query part if local model is unavailable).

        fake_embedding = [0.1] * 384

        chunks_a = [
            {
                "chunk_id": f"meet_a_{i:03d}",
                "video_id": "meet_a",
                "title": "Q2 Planning Meeting",
                "text": f"This is chunk {i} about quarterly planning and budget allocation.",
                "start_time": float(i * 60),
                "end_time": float((i + 1) * 60),
                "embedding": fake_embedding,
            }
            for i in range(3)
        ]

        chunks_b = [
            {
                "chunk_id": f"meet_b_{i:03d}",
                "video_id": "meet_b",
                "title": "Engineering Sync",
                "text": f"Engineering sync chunk {i}: discussing sprint velocity and blockers.",
                "start_time": float(i * 60),
                "end_time": float((i + 1) * 60),
                "embedding": fake_embedding,
            }
            for i in range(2)
        ]

        # Add meetings
        store.add_meeting("meet_a", chunks_a)
        store.add_meeting("meet_b", chunks_b)

        # List
        meetings = store.list_meetings()
        print(f"\nIndexed meetings ({len(meetings)}):")
        for m in meetings:
            print(f"  {m}")

        # Idempotency: re-adding should not duplicate
        store.add_meeting("meet_a", chunks_a)
        meetings_after_reindex = store.list_meetings()
        total_chunks = sum(m["chunk_count"] for m in meetings_after_reindex)
        assert total_chunks == 5, f"Expected 5 chunks total, got {total_chunks}"
        print("\nIdempotency check passed.")

        # Query (uses _embed internally; skip if model unavailable)
        try:
            results = store.query(
                query_text="quarterly budget planning",
                video_ids=["meet_a"],
                top_k=2,
            )
            print(f"\nQuery results ({len(results)}):")
            for r in results:
                print(f"  chunk_id={r['chunk_id']}  score={r['score']:.4f}  text={r['text'][:60]}")
        except Exception as exc:
            print(f"\nQuery skipped (embedding model unavailable): {exc}")

        # Remove meeting
        store.remove_meeting("meet_a")
        remaining = store.list_meetings()
        print(f"\nAfter removing meet_a: {remaining}")
        assert len(remaining) == 1 and remaining[0]["video_id"] == "meet_b"
        print("Remove check passed.")

    print("\n=== Smoke test complete ===")
