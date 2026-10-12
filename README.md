# vault-rag

Obsidian Markdown 的 BM25 + Ollama 向量混合检索，供 MCP 使用。

## 内容范围

`VAULT_ROOT` 是完整 Vault 根目录；`VAULT_CONTENT_FOLDER` 默认 `RAG`，只扫描该子树。
子树必须存在且严格位于 Vault 内，不能设置为空、`.`、绝对路径、上级路径或符号链接根目录。
目录外内容不需要 `.ragignore`，即使关闭排除文件也不会进入索引。

内容结构：`RAG/Notes/`（正文平铺）、`RAG/Rules/`（规则平铺）、`RAG/Navigation/`（导航）。
`README.md`、`_README.md`、Navigation、Attachments 固定不入索引；目录符号链接不遍历，文件符号链接不能跨出内容子树。
库根 `.ragignore` 的模式仍相对 Vault 根，用于目录内细粒度排除；保留 `rag_index: false` / `vault_rag_exclude: true`。

## 配置与运行

使用 Python 3.11+ 建立虚拟环境并安装 `pip install -e .`，将 `.env.example` 复制为 `.env`。
配置 `VAULT_ROOT`、`VAULT_CONTENT_FOLDER=RAG`、本机 Ollama 地址及 embedding model。
`VAULT_RULES_FOLDER=Rules` 表示内容目录下的规则子目录，即 `RAG/Rules/`。
MCP 启动文件为 `mcp_server.py`，使用虚拟环境 Python；建议设置本仓为 cwd，并显式传入相同配置。

```sh
vault-rag doctor
vault-rag audit
vault-rag reindex
vault-rag search "关键词" --top-k 3
```

索引默认位于 `<VAULT_ROOT>/.vault-rag/`，包含 LanceDB、nodes.jsonl 和 status.json。
重建在旁路临时目录完成，成功后切换；加载/embedding 失败不会删除旧索引。
旧索引未记录内容范围，或与当前配置不一致时，搜索和全文读取会要求重新索引。
状态提供 `vault_content_folder`、`vault_content_root`、`indexed_content_root`、`content_scope_version`、`scope_matches_settings`。

## 检索

- `vault_search`：正文经验，排除规则；`rule_search`：仅内容目录下 Rules，保留领域及项目约束。
- 类型以 frontmatter `type` 或 `type/*` 标签识别；领域以 `domain` 或保守的技术标签识别，平铺 DCC 笔记须保留领域信息。
- `limited` / `verified_true` 优先；`unverified` 和缺少状态的笔记仅作补充，不因所在目录获得隐含信任。
- 相似度门槛默认 `MIN_VECTOR_SCORE=0.40`；RRF 分数仅用于排序，不是置信度。
- 默认返回最多 3 篇及证据范围，可用 `compact=false` 取得完整字段。
- `vault_get_chunk` 取得全文；`vault_index_status` 查询索引与当前扫描范围。
- 路径相对完整 Vault 根，例如 `RAG/Notes/pit-example.md`。移动路径会改变 chunk ID，需重新检索。

笔记变化后重建索引；程序变化后重新连接 MCP。PCG-AI 的项目知识仍由工程内工具维护。
