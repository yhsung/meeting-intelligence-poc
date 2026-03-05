"""
Tests for src/chunker.py

Run: pytest tests/test_chunker.py -v
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from chunker import _build_chunks, process_transcript, load_chunks


FAKE_TRANSCRIPT = {
    "video_id": "vid001",
    "title": "Q2 Planning",
    "url": "https://www.youtube.com/watch?v=vid001",
    "duration_seconds": 600,
    "language": "en",
    "segments": [
        {"start": float(i * 5), "end": float(i * 5 + 5), "text": f"Segment {i} " + "word " * 20}
        for i in range(30)
    ],
}

FAKE_EMBEDDING = [0.1] * 384  # all-MiniLM-L6-v2 dim


# --- _build_chunks ---

def test_build_chunks_returns_list():
    chunks = _build_chunks(FAKE_TRANSCRIPT["segments"])
    assert isinstance(chunks, list)
    assert len(chunks) > 0


def test_build_chunks_each_chunk_has_required_fields():
    chunks = _build_chunks(FAKE_TRANSCRIPT["segments"])
    for chunk in chunks:
        assert "text" in chunk
        assert "start_time" in chunk
        assert "end_time" in chunk
        assert chunk["end_time"] >= chunk["start_time"]


def test_build_chunks_timestamps_are_ordered():
    chunks = _build_chunks(FAKE_TRANSCRIPT["segments"])
    for i in range(1, len(chunks)):
        assert chunks[i]["start_time"] <= chunks[i - 1]["end_time"] + 1  # allow overlap


def test_build_chunks_target_token_size():
    # With 30 segments of ~21 words each (~630 total words), expect ~2-3 chunks at 300 tokens
    chunks = _build_chunks(FAKE_TRANSCRIPT["segments"], target_tokens=300)
    assert len(chunks) >= 2


def test_build_chunks_overlap():
    # With overlap, start of chunk N+1 should be before end of chunk N
    chunks = _build_chunks(FAKE_TRANSCRIPT["segments"], target_tokens=200, overlap_seconds=30.0)
    if len(chunks) > 1:
        assert chunks[1]["start_time"] < chunks[0]["end_time"]


# --- process_transcript ---

def test_process_transcript_produces_chunks(tmp_path):
    transcript_path = tmp_path / "vid001.json"
    transcript_path.write_text(json.dumps(FAKE_TRANSCRIPT))

    with (
        patch("chunker.DATA_DIR", str(tmp_path)),
        patch("chunker.get_embedding", return_value=FAKE_EMBEDDING),
    ):
        chunks = process_transcript(str(transcript_path))

    assert isinstance(chunks, list)
    assert len(chunks) > 0


def test_process_transcript_chunk_schema(tmp_path):
    transcript_path = tmp_path / "vid001.json"
    transcript_path.write_text(json.dumps(FAKE_TRANSCRIPT))

    with (
        patch("chunker.DATA_DIR", str(tmp_path)),
        patch("chunker.get_embedding", return_value=FAKE_EMBEDDING),
    ):
        chunks = process_transcript(str(transcript_path))

    required = {"chunk_id", "video_id", "title", "text", "start_time", "end_time", "embedding"}
    for chunk in chunks:
        assert required.issubset(chunk.keys()), f"Missing keys: {required - chunk.keys()}"
        assert chunk["video_id"] == "vid001"
        assert chunk["title"] == "Q2 Planning"
        assert len(chunk["embedding"]) == len(FAKE_EMBEDDING)


def test_process_transcript_saves_file(tmp_path):
    transcript_path = tmp_path / "vid001.json"
    transcript_path.write_text(json.dumps(FAKE_TRANSCRIPT))
    chunks_dir = tmp_path / "chunks"

    with (
        patch("chunker.DATA_DIR", str(tmp_path)),
        patch("chunker.get_embedding", return_value=FAKE_EMBEDDING),
    ):
        process_transcript(str(transcript_path))
        saved = load_chunks.__wrapped__("vid001") if hasattr(load_chunks, "__wrapped__") else None

    # Check file was saved
    chunks_file = tmp_path / "chunks" / "vid001_chunks.json"
    # Path may vary; just verify at least one .json was written under tmp_path
    json_files = list(tmp_path.rglob("*_chunks.json"))
    assert len(json_files) >= 1


def test_process_transcript_chunk_ids_unique(tmp_path):
    transcript_path = tmp_path / "vid001.json"
    transcript_path.write_text(json.dumps(FAKE_TRANSCRIPT))

    with (
        patch("chunker.DATA_DIR", str(tmp_path)),
        patch("chunker.get_embedding", return_value=FAKE_EMBEDDING),
    ):
        chunks = process_transcript(str(transcript_path))

    ids = [c["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids)), "Chunk IDs are not unique"
