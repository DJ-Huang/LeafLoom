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

- `VAULT_ROOT`：Obsidian 庫根目錄（預設已指向 `D:\Project\Obsidian\DJ Knowledge\DJ knowledge`）
- `OLLAMA_BASE_URL`：預設 `http://127.0.0.1:11434`
- `EMBEDDING_MODEL`：預設 `bge-m3`
- `MIN_VECTOR_SCORE`：語義相關性門檻（預設 `0.40`）；低於門檻的候選不為填滿 `top_k` 返回，設為 `-1` 可停用
- `PCG_RULES_FOLDER`：僅保留為全局經驗搜尋的舊規則根排除項；PCG-AI 規則改走工程 `.pcg-ai/` 的 `pcg_kb_*`
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
    "VAULT_ROOT": "D:\\Project\\Obsidian\\DJ Knowledge\\DJ knowledge",
    "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
    "EMBEDDING_MODEL": "bge-m3"
  }
}
```

重啟 Cursor 後應可看到工具：

- `rule_search`：混合檢索 `Rules/`；HMIRP 規則只在 Unity 查詢含 HMIRP 強信號時注入/保留，PCG-AI 不走全局規則庫
- `vault_search`：混合檢索經驗筆記（**自動排除**規則根；可選 `note_type`、`domain`）；每篇最多一個 chunk，弱命中會返回 `no_relevant_hit=true` 而不是填滿 `top_k`
- `vault_get_chunk`：依 `chunk_id` 取全文
- `vault_index_status`：索引狀態

### 按需查询与精简返回

普通改码和审查不固定调用检索；缺少相关项目历史、平台/兼容证据或用户要求时再查。项目硬约束直接加载，已知存于 Vault 且当前缺失的补充规则才用 `rule_search`。

- MCP 的 `vault_search`、`rule_search` 默认 `top_k=3`、`compact=true`。显式 `top_k` 仍生效，CLI 与底层 search 默认值不变。
- 精简返回保留 `chunk_id`、`file_path`、`note_type`、`trust`、原摘要和 `excerpt_truncated`，以及非空的域、规则 ID、技术栈、平台、验证日期/范围和适用前提。去掉检索分数、重复/空元数据与 JSON 排版空白，不再次缩短摘要。
- `excerpt_truncated=true` 表示底层摘要达到原有 900 字符上限；决定据此实施或下结论前，用 `vault_get_chunk` 核对全文。未验证提示始终保留。
- 需要原有完整字段时传 `compact=false`；复现原默认数量可显式传 `top_k=10`。完整结果新增 `excerpt_truncated`，已有字段与含义保持不变。
- `vault_get_chunk` 继续返回完整正文与元数据；搜索成功返回 `no_relevant_hit`；无命中为 `ok=true, no_relevant_hit=true, results=[]`，服务错误返回 `ok=false`。
- 本次仅调整输出和默认结果数量，不改变召回、排序、验证分层或索引。无需 reindex；重启/重新连接 vault-rag MCP 后加载新接口，旧连接继续使用旧代码。

## 筆記 frontmatter（建議）

在 Markdown 的 YAML 裡使用 `type`、`domain` 等欄位，可讓 `vault_search` 的過濾更準，例如：

```yaml
---
type: pitfall
domain: unity
---
```

未填 `type` 時會從 `type/*` tag 或一級目錄（如 `Pitfalls/`、`Tips/`、`Rules/`）推導。`domain` 支援逗號、`|`、JSON 陣列或 YAML 陣列；服務會從 DCC 路徑及明確的 Unity/ComfyUI/PCG metadata 補充推導。`domain=general` 嚴格排除專用域，其他明確域仍允許真正未分類的跨項目筆記。

`score` 是 RRF 相對排序，不是置信度；`vector_score` 才用於相關性門檻。所有返回內容都是候選證據，仍須由調用方核對項目、版本、平台與當前源碼。

## 維護

- 筆記變更後：再執行一次 `vault-rag reindex`（目前為**全量重建**；之後可再加增量）。
- 更換嵌入模型：需**重建索引**（向量空間不同）。

## 授權

與上層專案一致；本模組依賴 LlamaIndex、LanceDB、MCP 等各自授權條款。
