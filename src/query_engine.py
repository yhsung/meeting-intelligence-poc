import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Allow running from project root or src/
sys.path.insert(0, str(Path(__file__).parent))

from vector_store import VectorStore

# ---------------------------------------------------------------------------
# Provider configuration
# Set LLM_PROVIDER in .env to switch backends. Supported values:
#   anthropic  (default) — requires ANTHROPIC_API_KEY
#   openai               — requires OPENAI_API_KEY
#   deepseek             — requires DEEPSEEK_API_KEY
#   glm                  — requires GLM_API_KEY
# ---------------------------------------------------------------------------

PROVIDER_CONFIGS = {
    "anthropic": {
        "base_url": None,  # uses Anthropic SDK directly
        "api_key_env": "ANTHROPIC_API_KEY",
        "default_model": "claude-sonnet-4-6",
    },
    "openai": {
        "base_url": None,  # official OpenAI endpoint
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
    },
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4/",
        "api_key_env": "GLM_API_KEY",
        "default_model": "glm-4-flash",
    },
}

SYSTEM_PROMPT = """You are an intelligent meeting assistant. You have been given excerpts from meeting transcripts as context.

Your job is to answer the user's question based ONLY on the provided meeting context.

Rules:
- Answer concisely and directly.
- If the context does not contain enough information to answer, say so clearly.
- Always cite your sources using the format [Meeting: <title>, <timestamp>] inline in your answer.
- Do not fabricate information not present in the context.
- If multiple meetings are relevant, synthesize across them.
"""


def _format_timestamp(seconds: float) -> str:
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes:02d}:{secs:02d}"


def _build_context(chunks: list[dict]) -> str:
    lines = []
    for i, chunk in enumerate(chunks, 1):
        ts = _format_timestamp(chunk["start_time"])
        lines.append(
            f"[Source {i}] Meeting: \"{chunk['title']}\" | Timestamp: {ts}\n{chunk['text']}\n"
        )
    return "\n---\n".join(lines)


def _extract_sources(chunks: list[dict]) -> list[dict]:
    seen = set()
    sources = []
    for chunk in chunks:
        key = (chunk["video_id"], chunk["start_time"])
        if key not in seen:
            seen.add(key)
            sources.append({
                "video_id": chunk["video_id"],
                "title": chunk["title"],
                "timestamp": _format_timestamp(chunk["start_time"]),
                "excerpt": chunk["text"][:200].strip() + ("..." if len(chunk["text"]) > 200 else ""),
            })
    return sources


def _make_client(provider: str):
    """Instantiate the appropriate LLM client for the given provider."""
    config = PROVIDER_CONFIGS.get(provider)
    if config is None:
        raise ValueError(f"Unknown provider '{provider}'. Choose from: {list(PROVIDER_CONFIGS)}")

    api_key = os.environ.get(config["api_key_env"])
    if not api_key:
        raise EnvironmentError(
            f"Missing env var: {config['api_key_env']} (required for provider '{provider}')"
        )

    if provider == "anthropic":
        try:
            import anthropic as _anthropic
        except ImportError:
            raise ImportError("pip install anthropic")
        return _anthropic.Anthropic(api_key=api_key)

    # All other providers use the OpenAI-compatible SDK
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("pip install openai")

    kwargs = {"api_key": api_key}
    if config["base_url"]:
        kwargs["base_url"] = config["base_url"]
    return OpenAI(**kwargs)


class QueryEngine:
    def __init__(self, db_path: str = "data/vectordb", top_k: int = 5):
        self.store = VectorStore(db_path=db_path)
        self.top_k = top_k
        self.provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()
        self.model = os.environ.get(
            "LLM_MODEL", PROVIDER_CONFIGS[self.provider]["default_model"]
        )
        self.client = _make_client(self.provider)

    def _complete(self, user_message: str) -> str:
        """Call the configured LLM and return the response text."""
        if self.provider == "anthropic":
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            return response.content[0].text

        # OpenAI-compatible (openai / deepseek / glm)
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content

    def _complete_stream(self, user_message: str):
        """Yield text chunks from the configured LLM."""
        if self.provider == "anthropic":
            with self.client.messages.stream(
                model=self.model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                for text in stream.text_stream:
                    yield text
            return

        # OpenAI-compatible streaming
        stream = self.client.chat.completions.create(
            model=self.model,
            max_tokens=1024,
            stream=True,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    def ask(self, question: str, selected_video_ids: list[str]) -> dict:
        """
        Query the knowledge base and return an AI-generated answer with sources.

        Returns:
            {"answer": str, "sources": [{"video_id", "title", "timestamp", "excerpt"}]}
        """
        if not selected_video_ids:
            return {
                "answer": "Please select at least one meeting from the sidebar to query.",
                "sources": [],
            }

        chunks = self.store.query(
            query_text=question,
            video_ids=selected_video_ids,
            top_k=self.top_k,
        )

        if not chunks:
            return {
                "answer": "No relevant content found in the selected meetings for your question.",
                "sources": [],
            }

        context = _build_context(chunks)
        user_message = f"Context from meetings:\n\n{context}\n\nQuestion: {question}"
        answer = self._complete(user_message)
        return {"answer": answer, "sources": _extract_sources(chunks)}

    def ask_stream(self, question: str, selected_video_ids: list[str]):
        """
        Streaming variant. Yields text chunks, then yields a final dict:
            {"type": "sources", "sources": [...]}
        """
        if not selected_video_ids:
            yield "Please select at least one meeting from the sidebar to query."
            yield {"type": "sources", "sources": []}
            return

        chunks = self.store.query(
            query_text=question,
            video_ids=selected_video_ids,
            top_k=self.top_k,
        )

        if not chunks:
            yield "No relevant content found in the selected meetings for your question."
            yield {"type": "sources", "sources": []}
            return

        context = _build_context(chunks)
        user_message = f"Context from meetings:\n\n{context}\n\nQuestion: {question}"

        yield from self._complete_stream(user_message)
        yield {"type": "sources", "sources": _extract_sources(chunks)}


if __name__ == "__main__":
    import tempfile
    from vector_store import VectorStore
    from chunker import get_embedding

    print(f"=== QueryEngine smoke test (provider: {os.environ.get('LLM_PROVIDER', 'anthropic')}) ===\n")

    with tempfile.TemporaryDirectory() as tmp:
        store = VectorStore(db_path=tmp)

        fake_text = "We decided to prioritize the mobile app redesign based on Q1 user feedback surveys showing 70% of users prefer mobile."
        embedding = get_embedding(fake_text)
        fake_chunks = [
            {
                "chunk_id": "vid001_000",
                "video_id": "vid001",
                "title": "Q2 Planning Meeting",
                "text": fake_text,
                "start_time": 872.0,
                "end_time": 930.0,
                "embedding": embedding,
            }
        ]
        store.add_meeting("vid001", fake_chunks)

        engine = QueryEngine(db_path=tmp)
        result = engine.ask("Why did we prioritize mobile?", selected_video_ids=["vid001"])

        print("Answer:", result["answer"])
        print("\nSources:")
        for s in result["sources"]:
            print(f"  - {s['title']} @ {s['timestamp']}: {s['excerpt'][:80]}...")
