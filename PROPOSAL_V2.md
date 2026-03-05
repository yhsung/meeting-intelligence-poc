# Meeting Intelligence POC v2 — Build Skills, Not Agents

> 將會議錄影轉化為一組可組合的 AI Skills，讓 Claude 按需調用，任何人都能用自然語言「進入」過去的會議。

## 從 v1 到 v2：為什麼要改？

v1 用硬編碼 pipeline（fetch → chunk → store → query）把能力串起來，前端負責 orchestration。這是典型的 **agent 思維**——寫死流程、靠程式碼決定什麼時候做什麼。

v2 採用 **skill 思維**：

| 差異 | v1 Agent | v2 Skill |
|------|----------|----------|
| 流程控制 | 硬編碼 pipeline | Claude 按意圖組合 skills |
| 能力暴露 | Python function call | 標準化 Tool Use / MCP |
| 擴展方式 | 改 pipeline 程式碼 | 加一個 skill，Claude 自動會用 |
| 互動模式 | 只有 RAG Q&A | 摘要、比較、時間線、action items... |
| 可移植性 | 綁死 Streamlit | 任何支援 tool use 的 client 都能用 |

**核心理念：** Skill 是最小可組合能力單元。Claude 是 orchestrator，不是我們的程式碼。

---

## Skills 定義

每個 Skill 是一個獨立、可測試、有明確 input/output 的能力單元。

### Skill 1 — `fetch_transcript`

**職責：** 從 YouTube URL 取得逐字稿

```
Input:  { url: string }
Output: { video_id, title, duration_seconds, segments: [{start, end, text}] }
Side effect: 儲存至 data/transcripts/{video_id}.json
```

**實作：** youtube-transcript-api（有字幕）→ fallback yt-dlp + faster-whisper
**MCP？** 否。YouTube 資料取得邏輯自包含，不需外部 MCP server。

---

### Skill 2 — `chunk_transcript`

**職責：** 將逐字稿切片並產生 embeddings

```
Input:  { video_id: string }  // 從 data/transcripts/ 讀取
Output: { video_id, chunks: [{chunk_id, text, start_time, end_time, embedding}] }
Side effect: 儲存至 data/chunks/{video_id}_chunks.json
```

**實作：** ~300 token 切片，30s overlap，text-embedding-3-small 或 sentence-transformers
**MCP？** 否。純計算邏輯。

---

### Skill 3 — `store_chunks`

**職責：** 將 chunks 寫入向量資料庫

```
Input:  { video_id: string }  // 從 data/chunks/ 讀取
Output: { status: "ok", chunks_stored: number }
```

**實作：** ChromaDB，以 video_id 做 metadata filter
**MCP？** 否。ChromaDB 是本地持久化，不需要 MCP 包裝。

---

### Skill 4 — `list_meetings`

**職責：** 列出所有已索引的會議

```
Input:  {}
Output: { meetings: [{video_id, title, url, duration_seconds, chunk_count}] }
```

---

### Skill 5 — `remove_meeting`

**職責：** 從知識庫移除指定會議

```
Input:  { video_id: string }
Output: { status: "ok" }
Side effect: 刪除 transcript、chunks、vector store 中的資料
```

---

### Skill 6 — `search_meetings`

**職責：** 在選定會議範圍中進行語意搜尋

```
Input:  { query: string, video_ids: string[], top_k?: number }
Output: { results: [{video_id, title, text, start_time, end_time, score}] }
```

**這是最核心的 skill。** 不包含 LLM 推理——只做 retrieval。讓 Claude 自己決定怎麼使用搜尋結果來回答用戶。

---

### Skill 7 — `get_transcript_segment`

**職責：** 取得指定時間範圍的原始逐字稿

```
Input:  { video_id: string, start_time: number, end_time: number }
Output: { text: string, segments: [{start, end, text}] }
```

**用途：** Claude 想深入了解某段落的上下文時，可以主動調用。v1 沒有這個能力。

---

## MCP 使用策略

**原則：只在跨系統邊界時用 MCP，內部邏輯用 native tool use。**

| 能力 | 實作方式 | 理由 |
|------|----------|------|
| Skills 1-7 | Native Tool Use | 本地邏輯，不需跨系統 |
| YouTube 資料 | 包在 Skill 1 內 | 單一外部 API，不值得獨立 MCP |
| 向量搜尋 | 包在 Skill 6 內 | ChromaDB 是本地 library |
| 未來：Confluence / Teams | MCP Server | 跨系統整合，適合 MCP |
| 未來：行事曆整合 | MCP Server | 跨系統整合，適合 MCP |

### 自建 MCP Server（未來延伸）

當 skills 穩定後，可以將 Skills 1-7 打包成一個 `meeting-intelligence-mcp-server`，讓 Claude Desktop 或其他 MCP client 直接使用。這是 v2 的進階目標，不是 MVP。

---

## 架構圖

```
                        ┌─────────────────────┐
                        │     Claude LLM      │
                        │   (Orchestrator)     │
                        └──────────┬──────────┘
                                   │ Tool Use
                    ┌──────────────┼──────────────┐
                    │              │              │
              ┌─────┴─────┐ ┌─────┴─────┐ ┌─────┴─────┐
              │  Ingest    │ │  Query    │ │  Manage   │
              │  Skills    │ │  Skills   │ │  Skills   │
              ├───────────┤ ├───────────┤ ├───────────┤
              │ fetch_    │ │ search_   │ │ list_     │
              │ transcript│ │ meetings  │ │ meetings  │
              │           │ │           │ │           │
              │ chunk_    │ │ get_      │ │ remove_   │
              │ transcript│ │ transcript│ │ meeting   │
              │           │ │ _segment  │ │           │
              │ store_    │ │           │ │           │
              │ chunks    │ │           │ │           │
              └─────┬─────┘ └─────┬─────┘ └─────┬─────┘
                    │              │              │
              ┌─────┴──────────────┴──────────────┴─────┐
              │          Local Data Layer                │
              │  transcripts/  chunks/  vectordb/       │
              └─────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────┐
  │                    Frontend Options                      │
  │                                                          │
  │  Option A: Streamlit UI ──→ 呼叫 Skills (Python)        │
  │  Option B: Claude Desktop ──→ 呼叫 Skills (MCP Server)  │
  └──────────────────────────────────────────────────────────┘
```

---

## v1 → v2 關鍵差異：Query Engine 消失了

v1 的 `query_engine.py` 做三件事：
1. 呼叫 vector store 取得 chunks
2. 組裝 system prompt
3. 呼叫 Claude API

v2 中，**Claude 本身就是 query engine。** 它：
1. 呼叫 `search_meetings` skill 取得相關片段
2. 如果需要更多上下文，呼叫 `get_transcript_segment`
3. 自己組織答案並引用來源

System prompt 不再硬編碼在 query_engine 裡，而是定義為前端（Streamlit 或 Claude Desktop）的 system instruction。

**好處：**
- Claude 可以決定搜尋幾次、要不要換關鍵字重搜
- Claude 可以主動要求更多上下文（v1 做不到）
- 新的互動模式（摘要、比較）不需改後端程式碼

---

## Demo 形式

### Demo A — Streamlit UI（視覺化展示）

適合 GM Demo，有完整的圖形介面：
- 左側欄：會議列表 + YouTube URL 輸入
- 右側：對話介面，Claude 透過 tool use 調用 skills
- 來源卡片：顯示時間戳，可點擊跳轉

### Demo B — Claude Desktop + MCP（技術深度展示）

適合展示 skill paradigm 的威力：
- 安裝 `meeting-intelligence-mcp-server`
- 在 Claude Desktop 直接對話：「幫我分析上週三場會議的共同決策」
- Claude 自行調用 skills，零 UI 開發

### Demo 腳本（10 分鐘）

1. **[2 min] 開場** — 展示問題：「你沒參加的會議，要怎麼 5 分鐘內掌握？」
2. **[2 min] Ingest** — 貼入 3 個 YouTube URL，展示 skills 逐步處理
3. **[4 min] 對話展示（Streamlit）** — 現場提問：
   - 「這三場會議的核心決策各是什麼？」
   - 「有沒有互相矛盾的觀點？」
   - 「幫我整理所有提到的 deadline」
4. **[2 min] 技術亮點** — 切到 Claude Desktop，展示同一組 skills 在不同 client 運作

---

## 價值主張（更新）

### 對個人
- 補課時間從 **1 小時 → 5 分鐘**
- 不再只能問固定問題，Claude 會主動深挖上下文

### 對團隊
- 決策理由有跡可查，附帶精確時間戳
- 跨會議知識串連：「過去三場都有討論這個議題，觀點演變是...」

### 對技術策略
- **展示 skill-based 架構** — 不是做一個 demo app，而是建立可組合能力
- 每個 skill 可獨立測試、獨立部署、獨立升級
- 今天跑在 Streamlit，明天接 Claude Desktop，後天接 Slack bot——零後端改動
- 這就是 **build skills, not agents** 的落地示範

---

## 執行時程

| 時間 | 任務 |
|------|------|
| Phase 1 | Skills 1-3（Ingest pipeline）：fetch → chunk → store |
| Phase 2 | Skills 4-7（Query & Manage）：list、remove、search、get_segment |
| Phase 3 | Streamlit UI — 接入 skills，實作對話介面 |
| Phase 4 | MCP Server 打包 — 讓 Claude Desktop 可用 |
| Phase 5 | Demo 腳本演練 + edge case 處理 |

---

## 延伸潛力

- **新 Skill 即新能力：** 加 `summarize_meeting` skill → Claude 自動會在適當時機使用
- **MCP 生態整合：** Confluence MCP、Slack MCP、Calendar MCP — 會議知識自動與其他系統串連
- **Multi-modal：** 加 `analyze_slide` skill 處理投影片截圖
- **Access Control：** 在 skill 層做權限檢查，不在 UI 層

---

## 這個提案本身就是最好的示範

> **v1 展示了 agentic coding 的速度。**
> **v2 展示了 skill-based architecture 的可組合性。**
>
> 同一組 skills，兩種 demo 形式，零重複開發。
> 這就是 build skills, not agents。
