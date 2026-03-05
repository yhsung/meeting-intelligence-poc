"""
Tests for src/vector_store.py

Run: pytest tests/test_vector_store.py -v
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from vector_store import VectorStore

FAKE_DIM = 384
FAKE_EMBEDDING_A = [0.1] * FAKE_DIM
FAKE_EMBEDDING_B = [0.9] * FAKE_DIM


def _make_chunks(video_id: str, title: str, n: int = 3, embedding=None) -> list[dict]:
    emb = embedding or FAKE_EMBEDDING_A
    return [
        {
            "chunk_id": f"{video_id}_{i:03d}",
            "video_id": video_id,
            "title": title,
            "text": f"This is chunk {i} of {title}. It discusses important topics related to the project.",
            "start_time": float(i * 60),
            "end_time": float(i * 60 + 55),
            "embedding": emb,
        }
        for i in range(n)
    ]


@pytest.fixture
def store(tmp_path):
    with patch("vector_store._embed", return_value=FAKE_EMBEDDING_A):
        s = VectorStore(db_path=str(tmp_path))
    return s


# --- add_meeting / list_meetings ---

def test_add_meeting_appears_in_list(store):
    chunks = _make_chunks("vid001", "Q2 Planning")
    store.add_meeting("vid001", chunks)
    meetings = store.list_meetings()
    ids = [m["video_id"] for m in meetings]
    assert "vid001" in ids


def test_add_meeting_chunk_count(store):
    chunks = _make_chunks("vid001", "Q2 Planning", n=5)
    store.add_meeting("vid001", chunks)
    meetings = store.list_meetings()
    meeting = next(m for m in meetings if m["video_id"] == "vid001")
    assert meeting["chunk_count"] == 5


def test_add_multiple_meetings(store):
    store.add_meeting("vid001", _make_chunks("vid001", "Q2 Planning"))
    store.add_meeting("vid002", _make_chunks("vid002", "Retrospective"))
    meetings = store.list_meetings()
    ids = {m["video_id"] for m in meetings}
    assert {"vid001", "vid002"}.issubset(ids)


def test_add_meeting_idempotent(store):
    chunks = _make_chunks("vid001", "Q2 Planning", n=3)
    store.add_meeting("vid001", chunks)
    store.add_meeting("vid001", chunks)  # re-add same meeting
    meetings = store.list_meetings()
    count = sum(1 for m in meetings if m["video_id"] == "vid001")
    assert count == 1  # should not duplicate


# --- remove_meeting ---

def test_remove_meeting(store):
    store.add_meeting("vid001", _make_chunks("vid001", "Q2 Planning"))
    store.add_meeting("vid002", _make_chunks("vid002", "Retrospective"))
    store.remove_meeting("vid001")
    meetings = store.list_meetings()
    ids = [m["video_id"] for m in meetings]
    assert "vid001" not in ids
    assert "vid002" in ids


def test_remove_nonexistent_meeting_does_not_raise(store):
    store.remove_meeting("does_not_exist")  # should not raise


# --- query ---

def test_query_returns_results(store):
    store.add_meeting("vid001", _make_chunks("vid001", "Q2 Planning"))
    with patch("vector_store._embed", return_value=FAKE_EMBEDDING_A):
        results = store.query("What was discussed?", video_ids=["vid001"], top_k=2)
    assert isinstance(results, list)
    assert len(results) <= 2


def test_query_respects_video_id_filter(store):
    store.add_meeting("vid001", _make_chunks("vid001", "Q2 Planning", embedding=FAKE_EMBEDDING_A))
    store.add_meeting("vid002", _make_chunks("vid002", "Retrospective", embedding=FAKE_EMBEDDING_B))

    with patch("vector_store._embed", return_value=FAKE_EMBEDDING_A):
        results = store.query("project planning", video_ids=["vid001"], top_k=5)

    returned_ids = {r["video_id"] for r in results}
    assert "vid002" not in returned_ids, "Query should only return results from vid001"


def test_query_result_schema(store):
    store.add_meeting("vid001", _make_chunks("vid001", "Q2 Planning"))
    with patch("vector_store._embed", return_value=FAKE_EMBEDDING_A):
        results = store.query("planning", video_ids=["vid001"], top_k=3)

    required = {"chunk_id", "video_id", "title", "text", "start_time", "end_time", "score"}
    for r in results:
        assert required.issubset(r.keys()), f"Missing keys: {required - r.keys()}"
        assert 0.0 <= r["score"] <= 1.0


def test_query_empty_video_ids_returns_empty(store):
    store.add_meeting("vid001", _make_chunks("vid001", "Q2 Planning"))
    with patch("vector_store._embed", return_value=FAKE_EMBEDDING_A):
        results = store.query("anything", video_ids=[], top_k=5)
    assert results == []


def test_query_multiple_meetings(store):
    store.add_meeting("vid001", _make_chunks("vid001", "Q2 Planning", n=3))
    store.add_meeting("vid002", _make_chunks("vid002", "Retrospective", n=3))

    with patch("vector_store._embed", return_value=FAKE_EMBEDDING_A):
        results = store.query("project", video_ids=["vid001", "vid002"], top_k=6)

    assert len(results) > 0
