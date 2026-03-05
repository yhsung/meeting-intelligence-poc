# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Meeting Intelligence POC — converts YouTube meeting recordings into an AI-queryable knowledge base. Users select past meetings, ask questions in natural language, and receive answers with timestamped source references.

See [PROPOSAL.md](PROPOSAL.md) for the full product proposal and [IMPLEMENTATION.md](IMPLEMENTATION.md) for the component architecture.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the Streamlit app
streamlit run src/app.py

# Run all tests
pytest tests/

# Run a single test file
pytest tests/test_fetcher.py -v

# Run a single test
pytest tests/test_fetcher.py::test_fetch_with_captions -v
```

## Architecture

Five independent components connected via well-defined Python interfaces:

```
fetcher.py → chunker.py → vector_store.py
                                │
                         query_engine.py
                                │
                            app.py
```

**[src/fetcher.py](src/fetcher.py)** — Fetches YouTube transcripts. Tries `youtube-transcript-api` first (caption-based), falls back to `yt-dlp` + `faster-whisper` for audio transcription. Outputs `data/transcripts/{video_id}.json`.

**[src/chunker.py](src/chunker.py)** — Reads transcript JSON, splits into ~300-token chunks with 30s overlap, generates embeddings (`text-embedding-3-small` or `sentence-transformers`). Outputs `data/chunks/{video_id}_chunks.json`. Preserves `start_time`/`end_time` on every chunk for source attribution.

**[src/vector_store.py](src/vector_store.py)** — ChromaDB wrapper. Uses `video_id` as the metadata key so queries can be scoped to a user-selected subset of meetings. Key methods: `add_meeting()`, `remove_meeting()`, `query(video_ids=[...])`, `list_meetings()`.

**[src/query_engine.py](src/query_engine.py)** — RAG engine. Calls `vector_store.query()` to retrieve top-k chunks, builds a system prompt with context, calls `claude-sonnet-4-6` via the Anthropic SDK, and returns an `Answer` with `sources` list (video title + formatted timestamp + excerpt).

**[src/app.py](src/app.py)** — Streamlit UI. Left sidebar: meeting list with checkboxes + YouTube URL input for adding new meetings (triggers fetcher → chunker → vector_store pipeline). Right panel: chat interface that calls `query_engine.ask()` and renders source cards below each answer.

## Data Layout

```
data/
  transcripts/{video_id}.json     # raw segments with start/end times
  chunks/{video_id}_chunks.json   # chunked + embedded
  vectordb/                       # ChromaDB persistent storage
```

## Key Interfaces

```python
# fetcher
fetch_transcript(url: str) -> MeetingTranscript
# {"video_id", "title", "url", "duration_seconds", "segments": [{"start", "end", "text"}]}

# chunker
process_transcript(transcript_path: str) -> list[Chunk]
# {"chunk_id", "video_id", "text", "start_time", "end_time", "embedding"}

# vector_store
store.query(query_text, video_ids, top_k=5) -> list[RetrievedChunk]

# query_engine
query_engine.ask(question, selected_video_ids) -> Answer
# {"answer": str, "sources": [{"video_id", "title", "timestamp", "excerpt"}]}
```

## Environment Variables

```
ANTHROPIC_API_KEY   # required for query_engine (claude-sonnet-4-6)
OPENAI_API_KEY      # required if using text-embedding-3-small; omit if using sentence-transformers
```
