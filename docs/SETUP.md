# vault-rag 搭建與配置指南

依序完成後，即可在本機 **建立索引**、**命令列試搜**，並在 **Cursor** 中透過 MCP 調用。

---

## 0. 前置條件

| 項目 | 要求 |
|------|------|
| OS | 本文以 **Windows** 為主（PowerShell） |
| Python | **3.11+**（建議 3.11–3.12；3.14 需自行驗證依賴） |
| Ollama | 已安裝，且建立索引與向量檢索時 **程序在運行** |
| 嵌入模型 | 執行：`ollama pull bge-m3` |
| Obsidian 庫 | 本倉預設路徑：`D:\Project\Obsidian\DJ Knowledge\DJ knowledge`（可改） |

---

## 1. 一鍵搭建（推薦）

在 **PowerShell** 中執行（路徑請依你的克隆位置調整）：

```powershell
Set-Location "D:\reseilion sync\UnityPackage\vault-rag"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup.ps1
```

腳本會：

1. 建立 **`vault-rag\.venv`**（若尚不存在）
2. 升級 **pip** 並 **`pip install -e .`**
3. 若無 **`.env`**，從 **`.env.example`** 複製
4. 嘗試 **`ollama pull bge-m3`**（失敗則僅提示，不中止安裝）
5. 寫入 **`_generated/cursor-mcp-vault-rag.fragment.json`**：可合併進全局 `mcp.json` 的 **`vault-rag`** 片段（已替換為本機 **絕對路徑**）

---

## 2. 手動搭建（與腳本等價）

```powershell
cd "D:\reseilion sync\UnityPackage\vault-rag"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e .
copy .env.example .env   # 若尚未有 .env
notepad .env             # 確認 VAULT_ROOT 等
ollama pull bge-m3
```

---

## 3. 配置環境變數（`.env` 或 MCP `env`）

| 變數 | 說明 | 預設 |
|------|------|------|
| `VAULT_ROOT` | Obsidian 庫根目錄（內含 `.obsidian` 的那一層） | 見 `.env.example` |
| `INDEX_IN_VAULT` | 為 `true` 時索引寫在 **`VAULT_ROOT` / `VAULT_INDEX_FOLDER`** | `true` |
| `VAULT_INDEX_FOLDER` | 庫內索引子目錄名（建議點目錄，如 `.vault-rag`） | `.vault-rag` |
| `INDEX_DIR` | 僅當 **`INDEX_IN_VAULT=false`**：索引相對於 `vault-rag` 專案根 | `_index` |
| `LOAD_RAGIGNORE_FILE` | 是否合併 **`VAULT_ROOT/.ragignore`**（gitignore 語法） | `true` |
| `EXCLUDE_DIR_NAMES_EXTRA` | 額外「路徑段」目錄名黑名單，`|` 或逗號分隔（與內建合併，不分大小寫匹配任一路徑段） | 空 |
| `OLLAMA_BASE_URL` | Ollama HTTP 根 | `http://127.0.0.1:11434` |
| `EMBEDDING_MODEL` | 嵌入模型名 | `bge-m3` |
| `EXCLUDE_GLOBS` | 可選，逗號分隔，相對路徑子字串排除（舊版簡單規則） | 空 |

整理庫結構、排除規則與 **`audit`** 流程見 [VAULT_ORGANIZATION.md](./VAULT_ORGANIZATION.md)。

---

## 4. 建立索引

1. （建議）先預檢：`vault-rag audit`；需要報告時：`vault-rag audit --write-report`（寫入索引目錄下的 **`AUDIT-last.md`**）。
2. 確認 Ollama 已啟動：`ollama list`
3. 在啟用 venv 的前提下：

```powershell
.\.venv\Scripts\Activate.ps1
vault-rag reindex
```

庫較大時會花較長時間（嵌入 + 寫 Lance）。完成後應存在（預設 **`INDEX_IN_VAULT=true`**）：

- `<VAULT_ROOT>/.vault-rag/lancedb/`
- `<VAULT_ROOT>/.vault-rag/nodes.jsonl`
- `<VAULT_ROOT>/.vault-rag/status.json`

若 **`INDEX_IN_VAULT=false`**，則為 **`vault-rag/_index/`** 下對應檔案。

驗證：

```powershell
vault-rag doctor
vault-rag search "測試關鍵詞" --top-k 5
```

---

## 5. 接入 Cursor（MCP）

### 5.1 配置文件位置

- **Windows**：`%USERPROFILE%\.cursor\mcp.json`

### 5.2 合併方式

1. 執行 **`scripts/setup.ps1`** 後，打開 **`vault-rag/_generated/cursor-mcp-vault-rag.fragment.json`**。
2. 將其中的 **`vault-rag`** 物件複製到全局 **`mcp.json`** 的 **`mcpServers`** 下（與現有 **`codely-agent`** 等並列）。
3. 若 **`vault-rag` 已存在**，以生成檔為準覆蓋，確保 **`command` 指向 `.venv\Scripts\python.exe`**。

### 5.3 必填欄位說明

| 欄位 | 說明 |
|------|------|
| `command` | 建議 **`...\vault-rag\.venv\Scripts\python.exe`**，避免系統 Python 缺依賴 |
| `args` | `["<vault-rag 根目錄>\\mcp_server.py"]` |
| `cwd` | **必須**為 **`vault-rag` 根目錄**，以便載入 `.env` |
| `env` | 至少 **`VAULT_ROOT`**、**`VAULT_CONTENT_FOLDER=RAG`**、**`OLLAMA_BASE_URL`**、**`EMBEDDING_MODEL`**；可選 **`INDEX_IN_VAULT`**、**`VAULT_INDEX_FOLDER`**、**`LOAD_RAGIGNORE_FILE`**、**`EXCLUDE_PATHSPEC_EXTRA`**、**`EXCLUDE_DIR_NAMES_EXTRA`** |

### 5.4 生效

**完全退出並重啟 Cursor**（僅重載窗口有時不夠）。在 MCP 面板確認 **`vault-rag`** 已連線，並可看到 **`vault_search`** 等工具。

---

## 6. 筆記規範（可選，強烈建議）

在 Markdown 頂部 YAML 使用 **`type`**、**`domain`**，便於 MCP 參數 **`note_type`**、**`domain`** 過濾：

```yaml
---
type: pitfall
domain: unity
---
```

`type` 缺失時服務會從 `type/*` tag 或一級目錄推導；`domain` 可寫單值、逗號分隔值或 YAML 陣列。服務會從 DCC 路徑及明確 metadata 推導部分舊筆記的域；`domain=general` 嚴格排除專用域，其他域仍可召回真正未分類的跨項目筆記。

`MIN_VECTOR_SCORE` 預設為 `0.40`。低於門檻的候選不返回，因此 `results=[]` / `no_relevant_hit=true` 是正常结果；若更換 embedding model，應用本地正負查詢重新校準，不要用 RRF `score` 當置信度。

---

## 7. 常見問題

| 現象 | 處理 |
|------|------|
| `Failed to connect to Ollama` | 啟動 Ollama；檢查防火牆；確認 `OLLAMA_BASE_URL` |
| `Missing ... nodes.jsonl` | 尚未 `reindex` 或索引路徑錯誤；執行 `vault-rag doctor` |
| Cursor 找不到工具 | 檢查 `mcp.json` JSON 語法；`cwd`；重啟 Cursor |
| `ModuleNotFoundError: pandas` | 在 **venv** 內執行 `pip install -e .` |
| `ollama` 指令找不到 | 關閉終端重開；或將 `C:\Users\<你>\AppData\Local\Programs\Ollama` 加到使用者 **PATH**；亦可：`"%LOCALAPPDATA%\Programs\Ollama\ollama.exe" pull bge-m3` |
| `vault-rag search` 在 PowerShell 印中文亂碼 / `UnicodeEncodeError` | 已改為 UTF-8 輸出；若仍有問題，先執行 `chcp 65001` 再試 |
| 更換模型後檢索怪 | 對新模型執行一次 **`reindex` 全量重建** |

## 8. 相關文檔

- [架構說明](./ARCHITECTURE.md)
- [知識庫整理與排除](./VAULT_ORGANIZATION.md)
- 上層 [README](../README.md)

## 2026-10 单目录范围

设置 `VAULT_CONTENT_FOLDER=RAG`，`VAULT_RULES_FOLDER=Rules` 是相对内容目录的子目录。RAG 必须先存在；旧索引需要重新构建，否则查询会报范围不匹配。状态同时返回 vault_root 和 vault_content_root。Notes 正文平铺，DCC 笔记明确 domain；Navigation、README 和附件固定排除。
