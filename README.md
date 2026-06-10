# vault-rag

Obsidian 筆記庫的本地 RAG：**Ollama `bge-m3` 嵌入 + LanceDB 向量庫 + BM25 混合檢索 + MCP**（給 Cursor Agent 調用）。在本倉庫語境下，**可取代 Smart Connections MCP** 作為 Cursor 側的知識庫語義檢索（兩者擇一即可，不必並存）。

## 需求

- Python **3.11+**（本倉在 **3.14** 下已能安裝依賴；建議仍優先 **3.11–3.12** 以利長期相容）
- [Ollama](https://ollama.com/) 已安裝，且建立索引時 **Ollama 必須在執行中**（Windows 托盤或終端 `ollama serve`）
- 已拉取嵌入模型：

```bash
ollama pull bge-m3
```

## 安裝

**一鍵搭建（Windows）**：在 `vault-rag` 目錄執行 `.\scripts\setup.ps1`（見 [docs/SETUP.md](./docs/SETUP.md)）。

**手動安裝**：

```powershell
cd "D:\reseilion sync\UnityPackage\vault-rag"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e .
```

（若已安裝 [uv](https://github.com/astral-sh/uv)，可改用 `uv sync` 與 `uv run`。）

## 文檔

- [搭建與 Cursor 配置](./docs/SETUP.md)
- [架構與 RAG 構建說明](./docs/ARCHITECTURE.md)
- [知識庫整理與排除規則](./docs/VAULT_ORGANIZATION.md)

## 設定

複製 `.env.example` 為 `.env`，至少確認：

- `VAULT_ROOT`：Obsidian 庫根目錄（預設已指向 `C:\ExampleVault Knowledge\DJ knowledge`）
- `OLLAMA_BASE_URL`：預設 `http://127.0.0.1:11434`
- `EMBEDDING_MODEL`：預設 `bge-m3`
- **`INDEX_IN_VAULT`**（預設 `true`）：索引寫在 **`VAULT_ROOT` + `VAULT_INDEX_FOLDER`**（預設 **`.vault-rag/`**），與知識庫同備份。設為 `false` 時改寫到 `vault-rag` 專案下的 `INDEX_DIR`。
- 排除規則：見 [知識庫整理與排除規則](./docs/VAULT_ORGANIZATION.md)（目錄名 **`EXCLUDE_DIR_NAMES_EXTRA`**、`.ragignore`、`EXCLUDE_PATHSPEC_EXTRA`、YAML `rag_index` 等）。

## 建立索引前（建議）

```powershell
vault-rag audit
# 可選：在索引目錄寫出 AUDIT-last.md
vault-rag audit --write-report
```

## 建立索引

先確認 Ollama 可連線（否則嵌入階段會報 `Failed to connect to Ollama`）：

```powershell
ollama list
```

再在 `vault-rag` 目錄執行：

```powershell
.\.venv\Scripts\Activate.ps1
vault-rag reindex
```

完成後會生成（預設在 **`VAULT_ROOT/.vault-rag/`**）：

- `lancedb/`：LanceDB 向量表
- `nodes.jsonl`：BM25 與 `vault_get_chunk` 用的 chunk 正文
- `status.json`：上次索引時間、chunk 數等

## 本機試搜

```powershell
vault-rag doctor
vault-rag search "Unity URP depth prepass 問題" --top-k 8
```

## 接到 Cursor（MCP）

1. 執行 **`scripts/setup.ps1`** 後，會生成 **`_generated/cursor-mcp-vault-rag.fragment.json`**（內含本機 **`.venv` 的 `python.exe` 絕對路徑**）。
2. 將該 JSON 檔中的 **`vault-rag`** 物件合併進 **`%USERPROFILE%\.cursor\mcp.json`** 的 **`mcpServers`**（若已存在同名項，以生成檔為準覆寫）。
3. **完全重啟 Cursor**。

與倉庫示例一致時，亦可直接參考根目錄 **`.cursor/mcp.json.example`**（已指向 `.venv` 的 `python`）。

手動片段範例（路徑需與你機器一致）：

```json
"vault-rag": {
  "command": "D:\\reseilion sync\\UnityPackage\\vault-rag\\.venv\\Scripts\\python.exe",
  "args": ["D:\\reseilion sync\\UnityPackage\\vault-rag\\mcp_server.py"],
  "cwd": "D:\\reseilion sync\\UnityPackage\\vault-rag",
  "env": {
    "VAULT_ROOT": "C:\\ExampleVault Knowledge\\DJ knowledge",
    "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
    "EMBEDDING_MODEL": "bge-m3"
  }
}
```

重啟 Cursor 後應可看到工具：

- `rule_search`：混合檢索，**僅** `Rules/`（Codely 路由規則）
- `vault_search`：混合檢索經驗筆記（**自動排除** `Rules/`，規則請用 `rule_search`；可選 `note_type`、`domain`）
- `vault_get_chunk`：依 `chunk_id` 取全文
- `vault_index_status`：索引狀態

## 筆記 frontmatter（建議）

在 Markdown 的 YAML 裡使用 `type`、`domain` 等欄位，可讓 `vault_search` 的過濾更準，例如：

```yaml
---
type: pitfall
domain: unity
---
```

## 維護

- 筆記變更後：再執行一次 `vault-rag reindex`（目前為**全量重建**；之後可再加增量）。
- 更換嵌入模型：需**重建索引**（向量空間不同）。

## 授權

與上層專案一致；本模組依賴 LlamaIndex、LanceDB、MCP 等各自授權條款。
