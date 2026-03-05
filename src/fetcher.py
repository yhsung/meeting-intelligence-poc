"""
Component 1 — YouTube Transcript Fetcher

Fetches transcripts from YouTube videos using youtube-transcript-api first,
falling back to yt-dlp + faster-whisper audio transcription when captions
are unavailable. Saves results to data/transcripts/{video_id}.json.
"""

import json
import os
import re
from urllib.parse import urlparse, parse_qs

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError as e:
    raise ImportError(
        "python-dotenv is required. Install it with: pip install python-dotenv"
    ) from e

try:
    from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
except ImportError as e:
    raise ImportError(
        "youtube-transcript-api is required. Install it with: pip install youtube-transcript-api"
    ) from e

try:
    import yt_dlp
except ImportError as e:
    raise ImportError(
        "yt-dlp is required. Install it with: pip install yt-dlp"
    ) from e


def _parse_video_id(url: str) -> str:
    """Extract YouTube video ID from various URL formats."""
    # Handle youtu.be short links
    parsed = urlparse(url)
    if parsed.netloc in ("youtu.be", "www.youtu.be"):
        video_id = parsed.path.lstrip("/")
        # Strip any query params appended to the path segment
        video_id = video_id.split("?")[0]
        if video_id:
            return video_id

    # Handle youtube.com/watch?v=... and youtube.com/shorts/...
    if "youtube.com" in parsed.netloc:
        qs = parse_qs(parsed.query)
        if "v" in qs:
            return qs["v"][0]
        # /shorts/<id> or /embed/<id>
        path_match = re.match(r"^/(?:shorts|embed|v)/([A-Za-z0-9_-]+)", parsed.path)
        if path_match:
            return path_match.group(1)

    # Last resort: look for an 11-char video ID anywhere in the URL
    match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    if match:
        return match.group(1)

    raise ValueError(f"Could not extract YouTube video ID from URL: {url}")


def _fetch_transcript_api(video_id: str) -> tuple[list[dict], str]:
    """
    Try youtube-transcript-api. Prefer English then Chinese, then first available.
    Returns (segments, language_code).
    """
    transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

    # Priority language order
    preferred = ["en", "en-US", "en-GB", "zh", "zh-TW", "zh-CN", "zh-Hans", "zh-Hant"]

    transcript = None
    for lang in preferred:
        try:
            transcript = transcript_list.find_transcript([lang])
            break
        except Exception:
            continue

    if transcript is None:
        # Fall back to the first available transcript
        try:
            transcript = next(iter(transcript_list))
        except StopIteration:
            raise NoTranscriptFound(video_id, preferred, {})

    raw = transcript.fetch()
    language = transcript.language_code

    segments = []
    for entry in raw:
        start = float(entry.get("start", 0.0))
        duration = float(entry.get("duration", 0.0))
        segments.append(
            {
                "start": round(start, 3),
                "end": round(start + duration, 3),
                "text": entry.get("text", "").strip(),
            }
        )

    return segments, language


def _fetch_transcript_whisper(video_id: str, url: str) -> tuple[list[dict], str]:
    """
    Download audio via yt-dlp and transcribe with faster-whisper.
    Returns (segments, language_code).
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise ImportError(
            "faster-whisper is required for audio transcription fallback. "
            "Install it with: pip install faster-whisper"
        ) from e

    audio_path = f"/tmp/{video_id}.%(ext)s"
    output_template = f"/tmp/{video_id}.%(ext)s"

    ydl_audio_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "64",
            }
        ],
    }

    downloaded_path = f"/tmp/{video_id}.mp3"

    with yt_dlp.YoutubeDL(ydl_audio_opts) as ydl:
        ydl.download([url])

    model = WhisperModel("base", device="cpu", compute_type="int8")
    whisper_segments, info = model.transcribe(downloaded_path, beam_size=5)

    segments = []
    for seg in whisper_segments:
        segments.append(
            {
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text.strip(),
            }
        )

    language = info.language if info.language else "unknown"

    # Clean up downloaded audio
    try:
        os.remove(downloaded_path)
    except OSError:
        pass

    return segments, language


def _get_ydlp_metadata(url: str) -> dict:
    """Use yt-dlp to fetch video metadata (title, duration)."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    return {
        "title": info.get("title", "Unknown Title"),
        "duration_seconds": int(info.get("duration", 0)),
    }


def get_video_metadata(url: str) -> dict:
    """
    Fetch only the title and duration of a YouTube video without downloading
    the transcript. Intended for UI preview purposes.

    Args:
        url: YouTube video URL.

    Returns:
        dict with keys: video_id, title, url, duration_seconds
    """
    video_id = _parse_video_id(url)
    meta = _get_ydlp_metadata(url)
    return {
        "video_id": video_id,
        "title": meta["title"],
        "url": url,
        "duration_seconds": meta["duration_seconds"],
    }


def fetch_transcript(url: str) -> dict:
    """
    Fetch the full transcript for a YouTube video.

    Strategy:
      1. Parse video_id from URL.
      2. Return cached result from data/transcripts/{video_id}.json if it exists.
      3. Try youtube-transcript-api (prefers en, then zh, then first available).
      4. On failure, fall back to yt-dlp audio download + faster-whisper transcription.
      5. Fetch metadata (title, duration) via yt-dlp.
      6. Save result to data/transcripts/{video_id}.json.

    Args:
        url: YouTube video URL (youtube.com/watch?v= or youtu.be/ formats).

    Returns:
        dict with keys: video_id, title, url, duration_seconds, language, segments
        where each segment is {"start": float, "end": float, "text": str}
    """
    video_id = _parse_video_id(url)

    # Check cache
    os.makedirs("data/transcripts", exist_ok=True)
    cache_path = f"data/transcripts/{video_id}.json"
    if os.path.exists(cache_path):
        print(f"[fetcher] Cache hit — loading from {cache_path}")
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    print(f"[fetcher] Fetching transcript for video_id={video_id}")

    # Step 1: Try caption-based transcript
    segments = None
    language = "unknown"
    try:
        segments, language = _fetch_transcript_api(video_id)
        print(f"[fetcher] Got caption transcript ({len(segments)} segments, lang={language})")
    except (NoTranscriptFound, TranscriptsDisabled) as exc:
        print(f"[fetcher] No captions available ({exc}). Falling back to Whisper.")
    except Exception as exc:
        print(f"[fetcher] Caption fetch error: {exc}. Falling back to Whisper.")

    # Step 2: Whisper fallback
    if segments is None:
        segments, language = _fetch_transcript_whisper(video_id, url)
        print(f"[fetcher] Got Whisper transcript ({len(segments)} segments, lang={language})")

    # Step 3: Metadata
    try:
        meta = _get_ydlp_metadata(url)
    except Exception as exc:
        print(f"[fetcher] Metadata fetch error: {exc}. Using defaults.")
        meta = {"title": "Unknown Title", "duration_seconds": 0}

    result = {
        "video_id": video_id,
        "title": meta["title"],
        "url": url,
        "duration_seconds": meta["duration_seconds"],
        "language": language,
        "segments": segments,
    }

    # Save to cache
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[fetcher] Saved transcript to {cache_path}")

    return result


if __name__ == "__main__":
    # Simple smoke test — uses a short public YouTube video
    TEST_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    print("=== get_video_metadata ===")
    meta = get_video_metadata(TEST_URL)
    print(f"  video_id : {meta['video_id']}")
    print(f"  title    : {meta['title']}")
    print(f"  duration : {meta['duration_seconds']}s")

    print("\n=== fetch_transcript ===")
    transcript = fetch_transcript(TEST_URL)
    print(f"  video_id : {transcript['video_id']}")
    print(f"  title    : {transcript['title']}")
    print(f"  language : {transcript['language']}")
    print(f"  segments : {len(transcript['segments'])} total")
    if transcript["segments"]:
        first = transcript["segments"][0]
        print(f"  first    : [{first['start']:.1f}s-{first['end']:.1f}s] {first['text'][:80]}")
