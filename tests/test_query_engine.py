"""
Tests for src/query_engine.py

Run: pytest tests/test_query_engine.py -v
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from query_engine import QueryEngine, _format_timestamp, _build_context, _extract_sources


# --- Helpers ---

FAKE_CHUNKS = [
    {
        "chunk_id": "vid001_000",
        "video_id": "vid001",
        "title": "Q2 Planning Meeting",
        "text": "We decided to prioritize the mobile app based on user feedback showing 70% prefer mobile.",
        "start_time": 872.0,
        "end_time": 930.0,
        "score": 0.92,
    },
    {
        "chunk_id": "vid001_001",
        "video_id": "vid001",
        "title": "Q2 Planning Meeting",
        "text": "The delivery timeline was set for end of Q2, with a mid-quarter review checkpoint.",
        "start_time": 1200.0,
        "end_time": 1260.0,
        "score": 0.85,
    },
]


# --- _format_timestamp ---

@pytest.mark.parametrize("seconds,expected", [
    (0.0, "00:00"),
    (65.0, "01:05"),
    (872.0, "14:32"),
    (3600.0, "60:00"),
])
def test_format_timestamp(seconds, expected):
    assert _format_timestamp(seconds) == expected


# --- _build_context ---

def test_build_context_includes_title():
    ctx = _build_context(FAKE_CHUNKS)
    assert "Q2 Planning Meeting" in ctx


def test_build_context_includes_text():
    ctx = _build_context(FAKE_CHUNKS)
    assert "mobile app" in ctx


def test_build_context_includes_timestamp():
    ctx = _build_context(FAKE_CHUNKS)
    assert "14:32" in ctx  # 872s = 14:32


def test_build_context_numbers_sources():
    ctx = _build_context(FAKE_CHUNKS)
    assert "[Source 1]" in ctx
    assert "[Source 2]" in ctx


# --- _extract_sources ---

def test_extract_sources_deduplicates():
    # Same chunk twice
    sources = _extract_sources(FAKE_CHUNKS + [FAKE_CHUNKS[0]])
    ids = [(s["video_id"], s["timestamp"]) for s in sources]
    assert len(ids) == len(set(ids))


def test_extract_sources_schema():
    sources = _extract_sources(FAKE_CHUNKS)
    required = {"video_id", "title", "timestamp", "excerpt"}
    for s in sources:
        assert required.issubset(s.keys())


def test_extract_sources_truncates_excerpt():
    long_chunk = {**FAKE_CHUNKS[0], "text": "word " * 100}
    sources = _extract_sources([long_chunk])
    assert len(sources[0]["excerpt"]) <= 203  # 200 chars + "..."


# --- QueryEngine.ask ---

@pytest.fixture
def engine(tmp_path):
    mock_store = MagicMock()
    mock_store.query.return_value = FAKE_CHUNKS

    mock_anthropic = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="The team prioritized mobile due to user feedback [Meeting: Q2 Planning Meeting, 14:32].")]
    mock_anthropic.messages.create.return_value = mock_response

    with (
        patch("query_engine.VectorStore", return_value=mock_store),
        patch("query_engine.anthropic.Anthropic", return_value=mock_anthropic),
    ):
        eng = QueryEngine(db_path=str(tmp_path))
        eng.store = mock_store
        eng.client = mock_anthropic
    return eng


def test_ask_returns_answer(engine):
    result = engine.ask("Why mobile?", selected_video_ids=["vid001"])
    assert "answer" in result
    assert isinstance(result["answer"], str)
    assert len(result["answer"]) > 0


def test_ask_returns_sources(engine):
    result = engine.ask("Why mobile?", selected_video_ids=["vid001"])
    assert "sources" in result
    assert isinstance(result["sources"], list)
    assert len(result["sources"]) > 0


def test_ask_source_schema(engine):
    result = engine.ask("Why mobile?", selected_video_ids=["vid001"])
    required = {"video_id", "title", "timestamp", "excerpt"}
    for s in result["sources"]:
        assert required.issubset(s.keys())


def test_ask_no_meetings_selected(engine):
    result = engine.ask("Why mobile?", selected_video_ids=[])
    assert "answer" in result
    assert result["sources"] == []
    # Should not call Claude API
    engine.client.messages.create.assert_not_called()


def test_ask_no_chunks_found(engine):
    engine.store.query.return_value = []
    result = engine.ask("totally unrelated question", selected_video_ids=["vid001"])
    assert result["sources"] == []
    engine.client.messages.create.assert_not_called()


def test_ask_passes_correct_video_ids_to_store(engine):
    engine.ask("question", selected_video_ids=["vid001", "vid002"])
    call_kwargs = engine.store.query.call_args
    assert "vid001" in call_kwargs[1].get("video_ids", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else [])
