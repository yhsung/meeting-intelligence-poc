# Meeting Intelligence POC — 實作拆解

## 系統架構

```
[Component 1]          [Component 2]          [Component 3]
YouTube Fetcher   →    Chunker & Embedder  →   Vector Store
(transcript)           (chunks + vectors)        (ChromaDB)
                                                      │
                                                      ▼
[Component 5]    ←←←←←←←←←←  [Component 4]
Frontend UI                     RAG Query Engine
(Streamlit)                     (Claude API + retrieval)
```

---

## Component 1 — YouTube Transcript Fetcher

**職責：** 輸入 YouTube URL，輸出結構化逐字稿

**介面：**
```python
# Input
fetch_transcript(url: str) -> MeetingTranscript

# Output (儲存為 data/transcripts/{video_id}.json)
{
  "video_id": "abc123",
  "title": "...",
  "url": "...",
  "duration_seconds": 3600,
  "segments": [
    { "start": 0.0, "end": 5.2, "text": "..." },
    ...
  ]
}
```

**實作重點：**
- 優先用 `youtube-transcript-api`（有字幕直接取）
- Fallback：`yt-dlp` 下載音訊 + `faster-whisper` 轉錄
- 處理多語言、自動字幕

**獨立測試：** 給 3 個 YouTube URL，驗證輸出 JSON 格式正確

---

## Component 2 — Chunker & Embedder

**職責：** 讀取逐字稿 JSON，切片並產生向量

**介面：**
```python
# Input
process_transcript(transcript_path: str) -> list[Chunk]

# Output (儲存為 data/chunks/{video_id}_chunks.json)
{
  "chunk_id": "abc123_042",
  "video_id": "abc123",
  "text": "...",
  "start_time": 250.0,
  "end_time": 310.0,
  "embedding": [0.12, -0.34, ...]  # 1536-dim
}
```

**實作重點：**
- 切片策略：以 ~300 tokens 為單位，保留 30s 重疊避免語義斷裂
- Embedding：`text-embedding-3-small`（OpenAI）或 `sentence-transformers`（本地）
- 保留時間戳記，供溯源使用

**獨立測試：** 輸入一份 transcript JSON，驗證 chunk 數量與時間戳正確

---

## Component 3 — Vector Store

**職責：** 管理向量資料庫，支援新增/查詢

**介面：**
```python
# 新增
store = VectorStore(db_path="data/vectordb")
store.add_meeting(video_id: str, chunks: list[Chunk])
store.remove_meeting(video_id: str)

# 查詢
results = store.query(
  query_text: str,
  video_ids: list[str],  # 選定的會議範圍
  top_k: int = 5
) -> list[RetrievedChunk]

# 列表
store.list_meetings() -> list[MeetingMeta]
```

**實作重點：**
- 使用 ChromaDB（持久化，支援 metadata filter）
- 以 `video_id` 作為 collection namespace，方便多選會議
- 提供 `list_meetings()` 供前端顯示已索引會議

**獨立測試：** 新增 2 個 meeting，查詢並驗證結果只來自指定 meeting

---

## Component 4 — RAG Query Engine

**職責：** 接收用戶問題 + 選定的 meeting IDs，回傳帶來源的 AI 回答

**介面：**
```python
# Input
query_engine.ask(
  question: str,
  selected_video_ids: list[str]
) -> Answer

# Output
{
  "answer": "...",
  "sources": [
    {
      "video_id": "abc123",
      "title": "Q2 Planning Meeting",
      "timestamp": "14:32",
      "excerpt": "..."
    }
  ]
}
```

**實作重點：**
- 呼叫 Component 3 取得 top-k chunks
- 組裝 system prompt，注入 context + 來源標記指令
- 呼叫 Claude API（claude-sonnet-4-6），要求回答附上來源 reference
- 支援串流輸出（streaming）

**獨立測試：** Mock Vector Store 回傳固定 chunks，驗證 Claude 回答格式與來源標記

---

## Component 5 — Frontend UI

**職責：** 提供會議選擇 + 對話介面

**頁面結構：**
```
左側欄：
  - 已索引會議列表（呼叫 store.list_meetings()）
  - Checkbox 勾選 → 更新 selected_video_ids
  - 新增會議：貼上 YouTube URL → 觸發 C1 → C2 → C3

右側主區：
  - 聊天介面（呼叫 query_engine.ask()）
  - 每則 AI 回答顯示來源卡片（video title + timestamp）
  - 處理中狀態（spinner + 進度提示）
```

**實作重點：**
- Streamlit（最快）或 Gradio
- Session state 管理 selected_video_ids
- 處理處理中狀態（spinner + 進度提示）

**獨立測試：** Mock query_engine，驗證 UI 選擇/對話流程正常

---

## 開發順序

### 第一波（可並行）

| Subagent | 負責 | 產出 |
|----------|------|------|
| A | Component 1 + 2 | `src/fetcher.py` + `src/chunker.py` + `data/` 結構 |
| B | Component 3 | `src/vector_store.py` + ChromaDB schema |
| C | Component 5 | `src/app.py`（Streamlit，含 mock data） |

### 第二波（串行，等第一波完成）

1. Component 4 — 整合 C3 + Claude API → `src/query_engine.py`
2. 整合測試 — C1 → C2 → C3 → C4 → C5 全流程

---

## 專案結構

```
meeting-intelligence-poc/
├── src/
│   ├── fetcher.py          # Component 1
│   ├── chunker.py          # Component 2
│   ├── vector_store.py     # Component 3
│   ├── query_engine.py     # Component 4
│   └── app.py              # Component 5
├── data/
│   ├── transcripts/        # {video_id}.json
│   ├── chunks/             # {video_id}_chunks.json
│   └── vectordb/           # ChromaDB 持久化
├── tests/
│   ├── test_fetcher.py
│   ├── test_chunker.py
│   ├── test_vector_store.py
│   └── test_query_engine.py
├── requirements.txt
├── PROPOSAL.md
└── IMPLEMENTATION.md
```

---

## 依賴套件

```txt
# Component 1
youtube-transcript-api
yt-dlp
faster-whisper

# Component 2 & 3
chromadb
openai                  # embedding + (optional) completions
sentence-transformers   # 本地 embedding 替代方案

# Component 4
anthropic

# Component 5
streamlit
```
