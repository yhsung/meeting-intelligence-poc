import os
import time
import streamlit as st

# ---------------------------------------------------------------------------
# Mock / real module imports
# ---------------------------------------------------------------------------
MOCK_MODE = os.environ.get("MOCK_MODE", "").lower() in ("true", "1", "yes")

_real_modules_loaded = False
fetcher = chunker = vector_store = query_engine = None

if not MOCK_MODE:
    try:
        # Streamlit adds src/ to sys.path when running `streamlit run src/app.py`,
        # so direct imports work. We also try the src-package form as fallback.
        try:
            import fetcher as _fetcher
            import chunker as _chunker
            import vector_store as _vector_store
            import query_engine as _query_engine
        except ImportError:
            from src import fetcher as _fetcher
            from src import chunker as _chunker
            from src import vector_store as _vector_store
            from src import query_engine as _query_engine

        fetcher = _fetcher
        chunker = _chunker
        vector_store = _vector_store
        query_engine = _query_engine
        _real_modules_loaded = True
    except Exception:
        import traceback
        _import_error_detail = traceback.format_exc()
        MOCK_MODE = True

_import_error_detail = locals().get("_import_error_detail", "")

# ---------------------------------------------------------------------------
# Mock data & helpers
# ---------------------------------------------------------------------------
MOCK_MEETINGS = [
    {"video_id": "mock001", "title": "Q2 Planning Meeting", "chunk_count": 42},
    {"video_id": "mock002", "title": "Team Retrospective", "chunk_count": 38},
    {"video_id": "mock003", "title": "Product Review", "chunk_count": 55},
]


def mock_ask(question, video_ids):
    return {
        "answer": (
            f"Based on the selected meetings, here is a simulated answer to: *'{question}'*\n\n"
            "The meetings discussed several key points related to your question. "
            "The team reached a consensus on the main direction and identified action items for follow-up."
        ),
        "sources": [
            {
                "video_id": video_ids[0] if video_ids else "mock001",
                "title": "Q2 Planning Meeting",
                "timestamp": "14:32",
                "excerpt": "We decided to prioritize the new feature based on user feedback showing strong demand across all segments.",
            },
            {
                "video_id": video_ids[0] if video_ids else "mock001",
                "title": "Q2 Planning Meeting",
                "timestamp": "28:15",
                "excerpt": "The timeline was set for end of quarter delivery with a mid-sprint checkpoint scheduled.",
            },
        ],
    }


def mock_add_meeting(url: str):
    import random
    fake_id = f"mock{random.randint(100, 999)}"
    fake_title = f"New Meeting ({url[-11:] if len(url) >= 11 else url})"
    return {"video_id": fake_id, "title": fake_title, "chunk_count": random.randint(20, 80)}


# ---------------------------------------------------------------------------
# Real-mode helpers
# ---------------------------------------------------------------------------

def _get_store():
    """Return a cached VectorStore instance from session state."""
    if "store" not in st.session_state:
        st.session_state.store = vector_store.VectorStore(db_path="data/vectordb")
    return st.session_state.store


def _get_engine():
    """Return a cached QueryEngine instance from session state."""
    if "engine" not in st.session_state:
        st.session_state.engine = query_engine.QueryEngine(db_path="data/vectordb")
    return st.session_state.engine


def real_list_meetings():
    try:
        return _get_store().list_meetings()
    except Exception as exc:
        st.error(f"Failed to load meetings: {exc}")
        return []


def real_add_meeting(url: str):
    # 1. Fetch transcript (cached to data/transcripts/{video_id}.json)
    transcript = fetcher.fetch_transcript(url)
    video_id = transcript["video_id"]

    # 2. Chunk + embed (saved to data/chunks/{video_id}_chunks.json)
    transcript_path = f"data/transcripts/{video_id}.json"
    chunks = chunker.process_transcript(transcript_path)

    # 3. Index into vector store
    _get_store().add_meeting(video_id, chunks)

    return {
        "video_id": video_id,
        "title": transcript["title"],
        "chunk_count": len(chunks),
    }


def real_ask(question: str, video_ids):
    return _get_engine().ask(question, list(video_ids))


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def render_source_card(source):
    st.markdown(
        f"""
        <div style="
            background: linear-gradient(135deg, rgba(13,20,36,0.98) 0%, rgba(15,26,46,0.98) 100%);
            border: 1px solid rgba(34,211,238,0.18);
            border-radius: 10px;
            padding: 14px 16px;
            margin: 6px 0;
            position: relative;
            overflow: hidden;
        ">
            <div style="
                position: absolute; top: 0; left: 0; right: 0; height: 1px;
                background: linear-gradient(90deg, transparent 0%, rgba(34,211,238,0.6) 50%, transparent 100%);
            "></div>
            <div style="display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:8px">
                <span style="
                    font-family: 'Syne', sans-serif;
                    font-weight: 700;
                    font-size: 0.82rem;
                    color: #CBD5E1;
                    line-height: 1.3;
                ">&#9654; {source['title']}</span>
                <code style="
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 0.7rem;
                    color: #22D3EE;
                    background: rgba(34,211,238,0.08);
                    border: 1px solid rgba(34,211,238,0.25);
                    padding: 2px 8px;
                    border-radius: 4px;
                    letter-spacing: 0.06em;
                    white-space: nowrap;
                    flex-shrink: 0;
                ">{source['timestamp']}</code>
            </div>
            <p style="
                font-family: 'Instrument Sans', sans-serif;
                font-size: 0.8rem;
                color: #475569;
                margin: 0;
                line-height: 1.55;
                font-style: italic;
            ">"{source['excerpt']}"</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_active_sources_tag(titles: list[str]):
    if not titles:
        return
    pills = " ".join(
        f'<span style="'
        f'font-family:\'JetBrains Mono\',monospace;font-size:0.62rem;'
        f'color:#0891B2;background:rgba(34,211,238,0.07);'
        f'border:1px solid rgba(34,211,238,0.2);border-radius:4px;'
        f'padding:2px 7px;white-space:nowrap">{t}</span>'
        for t in titles
    )
    st.markdown(
        f'<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:4px;align-items:center">'
        f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:0.58rem;'
        f'color:#334155;letter-spacing:0.1em;text-transform:uppercase;margin-right:2px">'
        f'sources</span>{pills}</div>',
        unsafe_allow_html=True,
    )


def extract_video_id(url: str) -> str | None:
    import re
    m = re.search(r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Meeting Intelligence", page_icon="◈")


# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "selected_video_ids" not in st.session_state:
    st.session_state.selected_video_ids = set()

if "mock_mode" not in st.session_state:
    st.session_state.mock_mode = MOCK_MODE

if "indexed_meetings" not in st.session_state:
    st.session_state.indexed_meetings = (
        list(MOCK_MEETINGS) if st.session_state.mock_mode else real_list_meetings()
    )

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    # Brand header
    st.markdown(
        """
        <div style="padding: 4px 0 24px 0">
            <h2>MEETING<br>INTELLIGENCE</h2>
            <div style="
                font-family: 'JetBrains Mono', monospace;
                font-size: 0.6rem;
                color: #334155;
                letter-spacing: 0.14em;
                margin-top: 5px;
            ">KNOWLEDGE BASE v1.0</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.session_state.mock_mode:
        st.markdown(
            """
            <div style="
                font-family: 'JetBrains Mono', monospace;
                font-size: 0.62rem;
                color: #0891B2;
                background: rgba(34,211,238,0.06);
                border: 1px solid rgba(34,211,238,0.15);
                border-radius: 5px;
                padding: 5px 9px;
                letter-spacing: 0.08em;
                margin-bottom: 12px;
            ">◈ MOCK MODE — no API calls</div>
            """,
            unsafe_allow_html=True,
        )
        if _import_error_detail:
            with st.expander("Import error detail", expanded=False):
                st.code(_import_error_detail, language="text")

    # Section label
    st.markdown(
        '<p style="font-family:\'JetBrains Mono\',monospace;font-size:0.62rem;color:#22D3EE;'
        'letter-spacing:0.12em;text-transform:uppercase;margin:0 0 10px 0">// Indexed Meetings</p>',
        unsafe_allow_html=True,
    )

    meetings = st.session_state.indexed_meetings

    if not meetings:
        st.info("No meetings indexed yet.")
    else:
        new_selected = set()
        for meeting in meetings:
            vid = meeting["video_id"]
            checked = vid in st.session_state.selected_video_ids
            label = (
                f"{meeting['title']}  \n"
                f"<span style=\"font-family:'JetBrains Mono',monospace;font-size:0.65rem;"
                f"color:#334155\">{meeting['chunk_count']} chunks</span>"
            )
            if st.checkbox(meeting["title"], value=checked, key=f"chk_{vid}"):
                new_selected.add(vid)
            # Chunk count hint below each checkbox
            st.markdown(
                f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.6rem;'
                f'color:#22415A;margin:-10px 0 8px 28px">{meeting["chunk_count"]} segments indexed</div>',
                unsafe_allow_html=True,
            )
        st.session_state.selected_video_ids = new_selected

    st.divider()

    # Add meeting
    st.markdown(
        '<p style="font-family:\'JetBrains Mono\',monospace;font-size:0.62rem;color:#22D3EE;'
        'letter-spacing:0.12em;text-transform:uppercase;margin:0 0 10px 0">// Add Meeting</p>',
        unsafe_allow_html=True,
    )
    new_url = st.text_input(
        "YouTube URL",
        placeholder="https://www.youtube.com/watch?v=...",
        key="new_url_input",
    )

    if st.button("Add Meeting", use_container_width=True):
        url = new_url.strip()
        if not url:
            st.error("Please enter a YouTube URL.")
        elif extract_video_id(url) is None and not st.session_state.mock_mode:
            st.error("Invalid YouTube URL.")
        else:
            try:
                if st.session_state.mock_mode:
                    with st.spinner("Fetching transcript..."):
                        time.sleep(0.4)
                    with st.spinner("Creating embeddings..."):
                        time.sleep(0.4)
                    with st.spinner("Indexing..."):
                        time.sleep(0.3)
                    new_meeting = mock_add_meeting(url)
                else:
                    with st.spinner("Fetching transcript..."):
                        transcript = fetcher.fetch_transcript(url)
                        video_id = transcript["video_id"]
                        transcript_path = f"data/transcripts/{video_id}.json"
                    with st.spinner("Creating embeddings..."):
                        chunks = chunker.process_transcript(transcript_path)
                    with st.spinner("Indexing..."):
                        _get_store().add_meeting(video_id, chunks)
                    new_meeting = {
                        "video_id": video_id,
                        "title": transcript["title"],
                        "chunk_count": len(chunks),
                    }

                existing_ids = {m["video_id"] for m in st.session_state.indexed_meetings}
                if new_meeting["video_id"] not in existing_ids:
                    st.session_state.indexed_meetings.append(new_meeting)

                st.success(f"Added: {new_meeting['title']}")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to add meeting: {exc}")

    st.divider()

    if st.button("Clear Conversation", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# ---------------------------------------------------------------------------
# Main area — header
# ---------------------------------------------------------------------------
selected_ids = st.session_state.selected_video_ids
selected_titles = [
    m["title"]
    for m in st.session_state.indexed_meetings
    if m["video_id"] in selected_ids
]

st.markdown(
    """
    <div style="padding: 4px 0 24px 0">
        <h1>Ask Your Meetings</h1>
        <p style="
            font-family: 'Instrument Sans', sans-serif;
            font-size: 0.875rem;
            color: #334155;
            margin: 0;
        ">Query the knowledge base with natural language — sources included.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Selected-meeting badges
if selected_titles:
    badges = " ".join(
        f'<span style="'
        f'display:inline-flex;align-items:center;gap:5px;'
        f'border:1px solid rgba(34,211,238,0.35);'
        f'color:#22D3EE;border-radius:20px;padding:3px 11px;margin:2px;'
        f'font-family:\'Instrument Sans\',sans-serif;font-size:0.78rem;font-weight:600;'
        f'background:rgba(34,211,238,0.06);letter-spacing:0.01em'
        f'"><span style="width:5px;height:5px;border-radius:50%;background:#22D3EE;'
        f'display:inline-block;box-shadow:0 0 6px #22D3EE"></span>{t}</span>'
        for t in selected_titles
    )
    st.markdown(
        f'<div style="margin-bottom:16px"><span style="font-family:\'JetBrains Mono\',monospace;'
        f'font-size:0.62rem;color:#334155;letter-spacing:0.1em;text-transform:uppercase;'
        f'margin-right:8px">Active</span>{badges}</div>',
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        '<div style="margin-bottom:16px;font-family:\'JetBrains Mono\',monospace;'
        'font-size:0.7rem;color:#22415A;letter-spacing:0.08em">'
        '◌ No meetings selected — choose from sidebar</div>',
        unsafe_allow_html=True,
    )

st.divider()

# ---------------------------------------------------------------------------
# Chat history
# ---------------------------------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "user" and msg.get("active_titles"):
            render_active_sources_tag(msg["active_titles"])
        if msg["role"] == "assistant" and msg.get("sources"):
            with st.expander("SOURCES", expanded=False):
                for src in msg["sources"]:
                    render_source_card(src)

# ---------------------------------------------------------------------------
# Chat input
# ---------------------------------------------------------------------------
user_input = st.chat_input("Ask anything about your selected meetings...")

if user_input:
    if not st.session_state.selected_video_ids:
        st.warning("Select at least one meeting from the sidebar first.")
    else:
        active_titles = [
            m["title"]
            for m in st.session_state.indexed_meetings
            if m["video_id"] in st.session_state.selected_video_ids
        ]
        st.session_state.messages.append({
            "role": "user",
            "content": user_input,
            "active_titles": active_titles,
            "sources": [],
        })
        with st.chat_message("user"):
            st.markdown(user_input)
            render_active_sources_tag(active_titles)

        with st.chat_message("assistant"):
            with st.spinner("Searching meetings..."):
                try:
                    if st.session_state.mock_mode:
                        time.sleep(0.8)
                        result = mock_ask(user_input, list(st.session_state.selected_video_ids))
                    else:
                        result = real_ask(user_input, st.session_state.selected_video_ids)

                    answer = result.get("answer", "No answer returned.")
                    sources = result.get("sources", [])
                except Exception as exc:
                    answer = f"An error occurred: {exc}"
                    sources = []

            st.markdown(answer)

            if sources:
                with st.expander("SOURCES", expanded=True):
                    for src in sources:
                        render_source_card(src)

        st.session_state.messages.append(
            {"role": "assistant", "content": answer, "sources": sources}
        )
