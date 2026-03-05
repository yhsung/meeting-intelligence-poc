"""
Tests for src/fetcher.py

Run: pytest tests/test_fetcher.py -v
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from fetcher import _parse_video_id, get_video_metadata, fetch_transcript


# --- _parse_video_id ---

@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?si=abc", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s", "dQw4w9WgXcQ"),
])
def test_parse_video_id_valid(url, expected):
    assert _parse_video_id(url) == expected


def test_parse_video_id_invalid():
    with pytest.raises((ValueError, Exception)):
        _parse_video_id("https://vimeo.com/123456")


# --- fetch_transcript: cache hit ---

def test_fetch_transcript_uses_cache(tmp_path):
    cached = {
        "video_id": "abc123",
        "title": "Cached Meeting",
        "url": "https://www.youtube.com/watch?v=abc123",
        "duration_seconds": 1800,
        "language": "en",
        "segments": [{"start": 0.0, "end": 5.0, "text": "Hello world"}],
    }
    transcripts_dir = tmp_path / "data" / "transcripts"
    transcripts_dir.mkdir(parents=True)
    cache_file = transcripts_dir / "abc123.json"
    cache_file.write_text(json.dumps(cached))

    with patch("fetcher.DATA_DIR", str(tmp_path / "data")):
        result = fetch_transcript("https://www.youtube.com/watch?v=abc123")

    assert result["video_id"] == "abc123"
    assert result["title"] == "Cached Meeting"
    assert len(result["segments"]) == 1


# --- fetch_transcript: youtube-transcript-api success ---

def test_fetch_transcript_via_caption_api(tmp_path):
    mock_segments = [
        MagicMock(start=0.0, duration=5.0, text="Hello"),
        MagicMock(start=5.0, duration=4.0, text="World"),
    ]
    mock_transcript = MagicMock()
    mock_transcript.fetch.return_value = mock_segments

    mock_list = MagicMock()
    mock_list.find_transcript.return_value = mock_transcript

    mock_metadata = {
        "id": "testid1",
        "title": "Test Meeting",
        "duration": 600,
        "webpage_url": "https://www.youtube.com/watch?v=testid1",
    }

    with (
        patch("fetcher.DATA_DIR", str(tmp_path / "data")),
        patch("fetcher.YouTubeTranscriptApi.list_transcripts", return_value=mock_list),
        patch("fetcher._get_ydl_metadata", return_value=mock_metadata),
    ):
        result = fetch_transcript("https://www.youtube.com/watch?v=testid1")

    assert result["video_id"] == "testid1"
    assert result["title"] == "Test Meeting"
    assert len(result["segments"]) == 2
    assert result["segments"][0]["text"] == "Hello"
    assert result["segments"][0]["start"] == 0.0


# --- output schema validation ---

def test_transcript_schema(tmp_path):
    cached = {
        "video_id": "schema_test",
        "title": "Schema Test",
        "url": "https://www.youtube.com/watch?v=schema_test",
        "duration_seconds": 900,
        "language": "en",
        "segments": [
            {"start": 0.0, "end": 10.0, "text": "First segment"},
            {"start": 10.0, "end": 20.0, "text": "Second segment"},
        ],
    }
    transcripts_dir = tmp_path / "data" / "transcripts"
    transcripts_dir.mkdir(parents=True)
    (transcripts_dir / "schema_test.json").write_text(json.dumps(cached))

    with patch("fetcher.DATA_DIR", str(tmp_path / "data")):
        result = fetch_transcript("https://www.youtube.com/watch?v=schema_test")

    required_keys = {"video_id", "title", "url", "duration_seconds", "language", "segments"}
    assert required_keys.issubset(result.keys())
    for seg in result["segments"]:
        assert {"start", "end", "text"}.issubset(seg.keys())
