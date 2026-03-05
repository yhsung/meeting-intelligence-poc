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
        MOCK_MODE = True

# ---------------------------------------------------------------------------
# Mock data & helpers
# ---------------------------------------------------------------------------
MOCK_MEETINGS = [
    {"video_id": "mock001", "title": "Q2 Planning Meeting (Mock)", "chunk_count": 42},
    {"video_id": "mock002", "title": "Team Retrospective (Mock)", "chunk_count": 38},
    {"video_id": "mock003", "title": "Product Review (Mock)", "chunk_count": 55},
]


def mock_ask(question, video_ids):
    return {
        "answer": (
            f"[MOCK] Based on the selected meetings, here is a simulated answer to: '{question}'\n\n"
            "The meetings discussed several key points related to your question. "
            "The team reached a consensus on the main direction and identified action items for follow-up."
        ),
        "sources": [
            {
                "video_id": video_ids[0] if video_ids else "mock001",
                "title": "Q2 Planning Meeting (Mock)",
                "timestamp": "14:32",
                "excerpt": "We decided to prioritize the new feature based on user feedback...",
            },
            {
                "video_id": video_ids[0] if video_ids else "mock001",
                "title": "Q2 Planning Meeting (Mock)",
                "timestamp": "28:15",
                "excerpt": "The timeline was set for end of quarter delivery...",
            },
        ],
    }


def mock_add_meeting(url: str):
    """Simulate adding a meeting from a YouTube URL in mock mode."""
    import random
    fake_id = f"mock{random.randint(100, 999)}"
    fake_title = f"New Meeting ({url[-11:] if len(url) >= 11 else url}) (Mock)"
    return {"video_id": fake_id, "title": fake_title, "chunk_count": random.randint(20, 80)}


# ---------------------------------------------------------------------------
# Real-mode helpers
# ---------------------------------------------------------------------------

def real_list_meetings():
    """Return list of indexed meetings from the vector store."""
    try:
        return vector_store.list_meetings()
    except Exception as exc:
        st.error(f"Failed to load meetings: {exc}")
        return []


def real_add_meeting(url: str):
    """Fetch, chunk and index a meeting from a YouTube URL."""
    transcript = fetcher.fetch(url)
    chunks = chunker.chunk(transcript)
    vector_store.index(chunks)
    return vector_store.get_meeting_by_url(url)


def real_ask(question: str, video_ids):
    """Query the indexed meetings and return answer + sources."""
    return query_engine.ask(question, list(video_ids))


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def render_source_card(source):
    st.markdown(
        f"""
    <div style="background:#f0f2f6;border-radius:8px;padding:12px;margin:4px 0;border-left:3px solid #4CAF50">
      <b>&#128249; {source['title']}</b> &nbsp; <code>{source['timestamp']}</code><br>
      <small>{source['excerpt']}</small>
    </div>
    """,
        unsafe_allow_html=True,
    )


def extract_video_id(url: str) -> str | None:
    """Return the YouTube video ID from a URL, or None if not parseable."""
    import re
    patterns = [
        r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Meeting Intelligence")

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
    st.session_state.indexed_meetings = list(MOCK_MEETINGS) if st.session_state.mock_mode else real_list_meetings()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("Meeting Knowledge Base")

    if st.session_state.mock_mode:
        st.caption("Running in MOCK mode — no real API calls are made.")

    st.subheader("Indexed Meetings")

    meetings = st.session_state.indexed_meetings

    if not meetings:
        st.info("No meetings indexed yet. Add one below.")
    else:
        # Build a set of currently checked ids outside the loop to avoid mutation issues
        new_selected = set()
        for meeting in meetings:
            vid = meeting["video_id"]
            checked = vid in st.session_state.selected_video_ids
            label = f"{meeting['title']}  \n_({meeting['chunk_count']} chunks)_"
            if st.checkbox(label, value=checked, key=f"chk_{vid}"):
                new_selected.add(vid)
        st.session_state.selected_video_ids = new_selected

    st.divider()

    # ------------------------------------------------------------------
    # Add meeting
    # ------------------------------------------------------------------
    st.subheader("Add Meeting")
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
            st.error("Invalid YouTube URL. Please check and try again.")
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
                        transcript = fetcher.fetch(url)
                    with st.spinner("Creating embeddings..."):
                        chunks = chunker.chunk(transcript)
                    with st.spinner("Indexing..."):
                        new_meeting = vector_store.index_and_return(chunks)

                # Avoid duplicates
                existing_ids = {m["video_id"] for m in st.session_state.indexed_meetings}
                if new_meeting["video_id"] not in existing_ids:
                    st.session_state.indexed_meetings.append(new_meeting)

                st.success(f"Added: {new_meeting['title']}")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to add meeting: {exc}")

    st.divider()

    # ------------------------------------------------------------------
    # Clear conversation
    # ------------------------------------------------------------------
    if st.button("Clear Conversation", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------
st.title("Ask Your Meetings")

# Selected-meeting badges
selected_ids = st.session_state.selected_video_ids
if selected_ids:
    selected_titles = [
        m["title"]
        for m in st.session_state.indexed_meetings
        if m["video_id"] in selected_ids
    ]
    badge_html = " ".join(
        f'<span style="background:#4CAF50;color:white;border-radius:12px;padding:2px 10px;margin:2px;font-size:0.85em">{t}</span>'
        for t in selected_titles
    )
    st.markdown(f"**Selected:** {badge_html}", unsafe_allow_html=True)
else:
    st.markdown(
        '<span style="color:#888;font-size:0.9em">No meetings selected</span>',
        unsafe_allow_html=True,
    )

st.divider()

# ---------------------------------------------------------------------------
# Chat history
# ---------------------------------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and msg.get("sources"):
            with st.expander("Sources", expanded=False):
                for src in msg["sources"]:
                    render_source_card(src)

# ---------------------------------------------------------------------------
# Chat input
# ---------------------------------------------------------------------------
user_input = st.chat_input("Ask a question about your meetings...")

if user_input:
    if not st.session_state.selected_video_ids:
        st.warning("Please select at least one meeting from the sidebar.")
    else:
        # Append user message
        st.session_state.messages.append({"role": "user", "content": user_input, "sources": []})
        with st.chat_message("user"):
            st.markdown(user_input)

        # Get answer
        with st.chat_message("assistant"):
            with st.spinner("Searching meetings..."):
                try:
                    if st.session_state.mock_mode:
                        time.sleep(0.8)  # simulate latency
                        result = mock_ask(user_input, list(st.session_state.selected_video_ids))
                    else:
                        result = real_ask(user_input, st.session_state.selected_video_ids)

                    answer = result.get("answer", "No answer returned.")
                    sources = result.get("sources", [])
                except Exception as exc:
                    answer = f"An error occurred while querying meetings: {exc}"
                    sources = []

            st.markdown(answer)

            if sources:
                with st.expander("Sources", expanded=True):
                    for src in sources:
                        render_source_card(src)

        # Persist assistant message
        st.session_state.messages.append(
            {"role": "assistant", "content": answer, "sources": sources}
        )
