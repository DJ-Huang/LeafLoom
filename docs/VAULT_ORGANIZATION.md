# Vault RAG 目录约定

`VAULT_ROOT` 是完整 Obsidian 库，`VAULT_CONTENT_FOLDER=RAG` 是唯一扫描子树。
`RAG/Notes/` 平铺知识正文，`RAG/Rules/` 平铺规则，`RAG/Navigation/` 放导航。
附件在 `RAG/Notes/Attachments/`。文件名前缀、type 或 type/* 标签区分笔记类型。

库外、RAG 外的新内容自动不入索引，无需修改 `.ragignore`。
RAG 下的 README、Navigation、Attachments 固定不入索引；`.ragignore` 的模式仍相对完整 Vault 根，仅负责细粒度排除。
单篇仍可使用 `rag_index: false` 或 `vault_rag_exclude: true`。移动目录不重新纳入已退出的内容。
缺少验证状态或 unverified 仅补充，limited/verified_true 优先。
规则通过稳定 rule_id 识别，source_path 对应 Rules 下真实文件名。

Templates、docs、Inbox、WorkLog、Projects、StudyWiki 等留在库根。
AI 写入流程从状态接口读取 vault_content_root，合格的通用正文写 Notes，过程稿写 WorkLog/Inbox。
笔记变化后 `vault-rag reindex`；工具代码变化后重新连接 MCP。
