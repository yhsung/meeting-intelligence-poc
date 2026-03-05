"""
Component 2 — Transcript Chunker & Embedder

Reads a transcript JSON produced by fetcher.py, splits it into ~300-token
chunks with ~30-second overlap, generates embeddings for each chunk, and
saves the results to data/chunks/{video_id}_chunks.json.

Embedding backend is selected by the EMBEDDING_BACKEND env var:
  "openai"  — OpenAI text-embedding-3-small (requires OPENAI_API_KEY)
  anything else or unset — sentence-transformers all-MiniLM-L6-v2 (local)
"""

import json
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError as e:
    raise ImportError(
        "python-dotenv is required. Install it with: pip install python-dotenv"
    ) from e


# ---------------------------------------------------------------------------
# Token counting helper (simple whitespace split — sufficient for chunking)
# ---------------------------------------------------------------------------

def _count_tokens(text: str) -> int:
    """Approximate token count by splitting on whitespace."""
    return len(text.split())


# ---------------------------------------------------------------------------
# Embedding backends
# ---------------------------------------------------------------------------

def get_embedding(text: str) -> list[float]:
    """
    Return an embedding vector for the given text.

    Backend selection (EMBEDDING_BACKEND env var):
      "openai"  — text-embedding-3-small via OpenAI API (requires OPENAI_API_KEY)
      other/unset — all-MiniLM-L6-v2 via sentence-transformers (local, no API key)

    Args:
        text: The text to embed.

    Returns:
        List of floats representing the embedding vector.
    """
    backend = os.environ.get("EMBEDDING_BACKEND", "local").strip().lower()

    if backend == "openai":
        return _embed_openai(text)
    else:
        return _embed_local(text)


def _embed_openai(text: str) -> list[float]:
    """Call OpenAI text-embedding-3-small."""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImportError(
            "openai package is required for OpenAI embeddings. "
            "Install it with: pip install openai"
        ) from e

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY environment variable is not set. "
            "Set it in your .env file or environment, or switch to local embeddings "
            "by setting EMBEDDING_BACKEND=local."
        )

    client = OpenAI(api_key=api_key)
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return response.data[0].embedding


# Module-level cache so the model is only loaded once per process
_local_model = None


def _embed_local(text: str) -> list[float]:
    """Use sentence-transformers all-MiniLM-L6-v2 locally."""
    global _local_model
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise ImportError(
            "sentence-transformers is required for local embeddings. "
            "Install it with: pip install sentence-transformers"
        ) from e

    if _local_model is None:
        print("[chunker] Loading sentence-transformers model all-MiniLM-L6-v2 ...")
        _local_model = SentenceTransformer("all-MiniLM-L6-v2")

    vector = _local_model.encode(text, normalize_embeddings=True)
    return vector.tolist()


# ---------------------------------------------------------------------------
# Chunking logic
# ---------------------------------------------------------------------------

def _build_chunks(
    segments: list[dict],
    target_tokens: int = 300,
    overlap_seconds: float = 30.0,
) -> list[dict]:
    """
    Merge transcript segments into chunks of approximately `target_tokens` tokens.

    Overlap strategy: once a chunk is finalised, the next chunk starts from
    the earliest segment whose start_time is within `overlap_seconds` before
    the current chunk's end_time.

    Args:
        segments: List of {"start": float, "end": float, "text": str} dicts.
        target_tokens: Approximate token budget per chunk.
        overlap_seconds: How many seconds to rewind for chunk overlap.

    Returns:
        List of {"text": str, "start_time": float, "end_time": float} dicts.
    """
    if not segments:
        return []

    chunks = []
    seg_idx = 0
    n = len(segments)

    while seg_idx < n:
        chunk_texts = []
        chunk_tokens = 0
        chunk_start = segments[seg_idx]["start"]
        chunk_end = chunk_start

        # Accumulate segments until we hit the token target
        i = seg_idx
        while i < n:
            seg = segments[i]
            seg_tokens = _count_tokens(seg["text"])

            # Always include at least one segment per chunk to avoid infinite loop
            if chunk_tokens > 0 and chunk_tokens + seg_tokens > target_tokens:
                break

            chunk_texts.append(seg["text"])
            chunk_tokens += seg_tokens
            chunk_end = seg["end"]
            i += 1

        chunk_text = " ".join(chunk_texts).strip()
        chunks.append(
            {
                "text": chunk_text,
                "start_time": chunk_start,
                "end_time": chunk_end,
            }
        )

        if i >= n:
            break  # consumed all segments

        # Find where to restart for the next chunk with overlap
        overlap_start = chunk_end - overlap_seconds
        next_idx = i  # default: continue right after current chunk
        for j in range(seg_idx, i):
            if segments[j]["start"] >= overlap_start:
                next_idx = j
                break

        # Safeguard: always advance at least one segment to prevent infinite loop
        if next_idx <= seg_idx:
            next_idx = seg_idx + 1

        seg_idx = next_idx

    return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_transcript(transcript_path: str) -> list[dict]:
    """
    Read a transcript JSON, chunk it, embed each chunk, and save results.

    Args:
        transcript_path: Absolute or relative path to a transcript JSON file
                         produced by fetcher.fetch_transcript().

    Returns:
        List of chunk dicts, each containing:
          chunk_id, video_id, title, text, start_time, end_time, embedding
    """
    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = json.load(f)

    video_id = transcript["video_id"]
    title = transcript.get("title", "")
    segments = transcript.get("segments", [])

    print(f"[chunker] Processing {len(segments)} segments for video_id={video_id}")

    raw_chunks = _build_chunks(segments, target_tokens=300, overlap_seconds=30.0)
    print(f"[chunker] Created {len(raw_chunks)} chunks")

    chunks = []
    for idx, raw in enumerate(raw_chunks):
        print(f"[chunker] Embedding chunk {idx + 1}/{len(raw_chunks)} ...", end="\r")
        embedding = get_embedding(raw["text"])
        chunks.append(
            {
                "chunk_id": f"{video_id}_{idx:03d}",
                "video_id": video_id,
                "title": title,
                "text": raw["text"],
                "start_time": raw["start_time"],
                "end_time": raw["end_time"],
                "embedding": embedding,
            }
        )
    print()  # newline after progress indicator

    # Save to data/chunks/
    os.makedirs("data/chunks", exist_ok=True)
    output_path = f"data/chunks/{video_id}_chunks.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    print(f"[chunker] Saved {len(chunks)} chunks to {output_path}")

    return chunks


def load_chunks(video_id: str) -> list[dict]:
    """
    Load pre-computed chunks from disk.

    Args:
        video_id: The YouTube video ID whose chunks should be loaded.

    Returns:
        List of chunk dicts (same structure as returned by process_transcript).

    Raises:
        FileNotFoundError: If the chunks file does not exist.
    """
    chunks_path = f"data/chunks/{video_id}_chunks.json"
    if not os.path.exists(chunks_path):
        raise FileNotFoundError(
            f"Chunks file not found: {chunks_path}. "
            f"Run process_transcript() first for video_id={video_id}."
        )

    with open(chunks_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    print(f"[chunker] Loaded {len(chunks)} chunks from {chunks_path}")
    return chunks


if __name__ == "__main__":
    import sys

    # Accept an optional transcript path argument, else use a default
    if len(sys.argv) > 1:
        transcript_path = sys.argv[1]
    else:
        # Try to find any existing transcript as a demo target
        transcripts_dir = "data/transcripts"
        if os.path.isdir(transcripts_dir):
            files = [
                os.path.join(transcripts_dir, f)
                for f in os.listdir(transcripts_dir)
                if f.endswith(".json")
            ]
        else:
            files = []

        if not files:
            print(
                "No transcript files found in data/transcripts/. "
                "Run fetcher.py first, or pass a transcript path as an argument:\n"
                "  python src/chunker.py data/transcripts/<video_id>.json"
            )
            sys.exit(0)

        transcript_path = files[0]

    print(f"=== process_transcript({transcript_path!r}) ===")
    chunks = process_transcript(transcript_path)

    print(f"\nSummary:")
    print(f"  Total chunks : {len(chunks)}")
    if chunks:
        first = chunks[0]
        last = chunks[-1]
        print(f"  First chunk  : id={first['chunk_id']}  [{first['start_time']:.1f}s - {first['end_time']:.1f}s]")
        print(f"                 text preview: {first['text'][:100]!r}")
        print(f"                 embedding dims: {len(first['embedding'])}")
        print(f"  Last chunk   : id={last['chunk_id']}  [{last['start_time']:.1f}s - {last['end_time']:.1f}s]")

    print("\n=== load_chunks ===")
    video_id = chunks[0]["video_id"] if chunks else "unknown"
    loaded = load_chunks(video_id)
    print(f"  Loaded {len(loaded)} chunks for video_id={video_id}")
