# Meeting Intelligence POC

將 YouTube 會議錄影轉化為可對話的 AI 知識庫。選定過去幾次會議，任何人都能用自然語言提問，獲取帶時間戳來源的回答——不再需要重看錄影或翻閱靜態會議記錄。

![UI screenshot — 水藍色系介面，左側會議清單，右側 AI 對話](docs/screenshot.png)

## 功能

- **多會議知識庫** — 勾選任意幾場過去的會議組合成查詢範圍
- **來源溯源** — 每則回答附帶會議名稱與時間戳（如 `14:32`），可追溯原始段落
- **YouTube 原生支援** — 貼上 YouTube URL 自動抓取字幕；無字幕時 fallback 到 Whisper 語音轉錄
- **多 LLM Provider** — 支援 Anthropic Claude、OpenAI、DeepSeek、GLM，切換只需改環境變數
- **Mock 模式** — 無需任何 API Key 即可啟動 UI，適合快速 Demo

## 快速開始

### 1. 安裝依賴

```bash
pip install -r requirements.txt
```

### 2. 設定環境變數

```bash
cp .env.example .env
# 編輯 .env，填入 API Key
```

### 3. 啟動

```bash
# Mock 模式（無需 API Key）
MOCK_MODE=true streamlit run src/app.py

# 正式模式
streamlit run src/app.py
```

## 環境變數

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `LLM_PROVIDER` | LLM 後端：`anthropic` / `openai` / `deepseek` / `glm` | `anthropic` |
| `LLM_MODEL` | 指定模型名稱（選填，有各 provider 預設值） | — |
| `ANTHROPIC_API_KEY` | Anthropic API Key | — |
| `OPENAI_API_KEY` | OpenAI API Key | — |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | — |
| `GLM_API_KEY` | Zhipu GLM API Key | — |
| `EMBEDDING_BACKEND` | Embedding 方式：`openai` 或 `local`（sentence-transformers） | `local` |
| `MOCK_MODE` | 設為 `true` 啟用 mock 模式 | `false` |

## 系統架構

```
YouTube URL
    │
    ▼
fetcher.py          → data/transcripts/{video_id}.json
    │
    ▼
chunker.py          → data/chunks/{video_id}_chunks.json
    │
    ▼
vector_store.py     → data/vectordb/  (ChromaDB)
    │
    ▼
query_engine.py     ← 使用者問題 + 選定的 video_ids
    │
    ▼
app.py              (Streamlit UI)
```

| 元件 | 檔案 | 說明 |
|------|------|------|
| YouTube Fetcher | `src/fetcher.py` | 字幕 API 優先，fallback Whisper |
| Chunker & Embedder | `src/chunker.py` | ~300 token 切片，30s 重疊 |
| Vector Store | `src/vector_store.py` | ChromaDB，支援多會議 filter |
| RAG Query Engine | `src/query_engine.py` | 多 provider LLM + 來源標記 |
| Frontend UI | `src/app.py` | Streamlit，含 mock 模式 |

## 執行測試

```bash
# 所有測試（不需要 API Key，全部使用 mock）
pytest tests/ -v

# 單一元件
pytest tests/test_fetcher.py -v
pytest tests/test_chunker.py -v
pytest tests/test_vector_store.py -v
pytest tests/test_query_engine.py -v
```

## 切換 LLM Provider

只需修改 `.env`，無需改程式碼：

```bash
# DeepSeek
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-xxx

# GLM (Zhipu AI)
LLM_PROVIDER=glm
GLM_API_KEY=xxx

# OpenAI，指定特定模型
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-xxx
LLM_MODEL=gpt-4o
```

## 自訂主題

本專案使用 Streamlit 原生的 [theming system](https://docs.streamlit.io/develop/concepts/configuration/theming) 搭配自訂字型與 CSS 來定義介面風格。相關資產不納入版本控制，需在本機建立：

### `.streamlit/config.toml`

透過 `[theme]` 區塊設定色彩、字型、圓角等，並用 `[[theme.fontFaces]]` 載入本地字型檔。範例：

```toml
[server]
enableStaticServing = true

[theme]
primaryColor = "#cb785c"
backgroundColor = "#fdfdf8"
secondaryBackgroundColor = "#ecebe3"
textColor = "#3d3a2a"
font = "SpaceGrotesk"
codeFont = "SpaceMono"

[[theme.fontFaces]]
family = "SpaceGrotesk"
url = "app/static/SpaceGrotesk-VariableFont_wght.ttf"
```

### `static/`

將字型檔（如 `.ttf`）放在專案根目錄的 `static/` 資料夾，Streamlit 在 `enableStaticServing = true` 時會自動提供 `/app/static/` 路徑。

### `src/style.css`

額外的 CSS 覆寫透過 `src/style.css` 注入（已納入版本控制），用於微調 Streamlit 預設元件的外觀。

## 專案文件

- [PROPOSAL.md](PROPOSAL.md) — 產品提案與價值主張
- [IMPLEMENTATION.md](IMPLEMENTATION.md) — 元件架構與介面定義
