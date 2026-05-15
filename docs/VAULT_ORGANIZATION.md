# 知識庫整理與 RAG 索引約定

索引產物預設寫在庫內 **`VAULT_ROOT/.vault-rag/`**（與筆記一起備份、同步）。建立索引前建議先做輕量整理與排除規劃。

---

## 1. 建議目錄心智（可選）

| 區域 | 用途 |
|------|------|
| `Inbox/` | 快速捕獲，定期「蒸餾」到主題目錄 |
| `Experience/`、`Topics/`、`Projects/` | 長期保留的結構化知識 |
| `Archive/` | 過期但仍保留；通常應 **排除索引** |
| `Attachments/` | 二進位附件；若只有 md 索引可整夾排除 |

不必一次搬完；重點是 **之後新筆記遵守命名與 frontmatter**，再逐步歸檔。

---

## 2. 建立索引前：執行審計

在 `vault-rag` 目錄（已啟用 venv）：

```powershell
vault-rag audit
```

可選寫出報告到索引目錄（預設 `.vault-rag/AUDIT-last.md`）：

```powershell
vault-rag audit --write-report
```

報告含：各頂層資料夾 md 數量、預估會進索引的篇數、路徑規則排除樣本、YAML 排除樣本、體積最大的 md（方便你決定是否排除或拆檔）。

---

## 3. 排除機制（多層，可並用）

### 3.1 目錄名黑名單（路徑「任一段」資料夾名）

相對於庫根目錄的相對路徑中，**任意一層** 的資料夾名（或檔名）若與下列名稱之一相同（**不分大小寫**），該 `.md` 不會進索引：

- **內建**（無需配置）：`.obsidian`、`.git`、`.vault-rag`、`node_modules`、`_index`
- **擴充**：在 `vault-rag/.env` 或 MCP `env` 中設定 **`EXCLUDE_DIR_NAMES_EXTRA`**。欄位型別為 `tuple`，**須寫成 JSON 陣列字串**（單行即可），例如：

  ```env
  EXCLUDE_DIR_NAMES_EXTRA=["Art","Attachments",".sync","工程解析"]
  ```

  若仍想用純逗號分隔，可改寫進 **`.ragignore`** 的 pathspec（如 `Attachments/**`），語意更直觀。

若需按「完整路徑前綴」或萬用字排除整棵目錄，請用 **§3.2 `.ragignore`** 或 **§3.3 `EXCLUDE_PATHSPEC_EXTRA`**（如 `Export/**`），語意更精確。

### 3.2 路徑規則：`.ragignore`（推薦）

在 **Vault 根目錄** 放置 **`.ragignore`**，語法與 **`.gitignore` 相近**（使用 [pathspec](https://pypi.org/project/pathspec/) 的 `gitignore` 風格）。

範本：見倉庫 `vault-rag/templates/dot-ragignore.example`，複製為庫根的 `.ragignore` 後再編輯。

常見寫法示例：

```gitignore
Export/**
Attachments/**
Archive/**
Private/**
**/Drafts/**
```

### 3.3 路徑規則：環境變數 `EXCLUDE_PATHSPEC_EXTRA`

在 `vault-rag/.env` 或 Cursor MCP `env` 中，以 **`|` 分隔**多條規則（與 `.ragignore` 同語意），會與內建規則、`.ragignore` **合併**。

### 3.4 子字串排除：`EXCLUDE_GLOBS`（舊版簡單規則）

逗號分隔，對 **相對路徑** 做 **不分大小寫子字串** 匹配；適合快速拉黑某幾個資料夾名稱片段。

### 3.5 單篇筆記：YAML 不進索引

在該 Markdown 的 YAML 任選其一：

```yaml
rag_index: false
```

或：

```yaml
vault_rag_exclude: true
```

適合：剪藏全文、會議逐字、與程式知識無關的私人筆記。

---

## 4. Obsidian 顯示與圖譜

`.vault-rag` 為 **隱藏資料夾**（以點開頭）。若仍出現在檔案列表：

- **設定 → 檔案與連結 → 排除的資料夾**：加入 `.vault-rag`
- 圖譜中可同樣排除，避免節點被索引檔干擾

---

## 5. Git 與備份

若整庫用 Git 管理，建議在 **Vault 根 `.gitignore`** 加入：

```gitignore
.vault-rag/
```

索引可隨時用 `vault-rag reindex` 重建；一般不必版本控制向量檔。

---

## 6. 舊索引位置遷移

先前若索引在 **`UnityPackage/vault-rag/_index/`**，改為庫內預設後：

1. 執行 `vault-rag audit` 確認排除規則無誤。  
2. 執行 `vault-rag reindex`。  
3. 可手動刪除舊的 `vault-rag/_index/` 釋放磁碟。

---

## 7. 相關命令

| 命令 | 作用 |
|------|------|
| `vault-rag audit` | 預檢掃描 |
| `vault-rag audit --write-report` | 寫出 `AUDIT-last.md` |
| `vault-rag reindex` | 全量重建索引到 `resolved_index_dir` |
| `vault-rag doctor` | 檢查索引產物是否存在 |

更多技術細節見 [ARCHITECTURE.md](./ARCHITECTURE.md) 與 [SETUP.md](./SETUP.md)。
