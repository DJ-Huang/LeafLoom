# 本地知识库

一个进程提供本地网页、HTTP MCP 和 BGE-M3 推理。原文件保留在关联目录内；不依赖 Ollama，也不另外启动 Node 网页服务。

- 网页：http://127.0.0.1:18080/
- MCP：http://127.0.0.1:18080/mcp
- 配置与模型：macOS 用户 Application Support/VaultRag；本机令牌私有保存。
- 元数据、索引、版本历史和回收区：关联目录下 `.vault-rag/`，始终排除正文检索。

## 安装与启动

```sh
.venv/bin/python -m pip install -e .
npm ci --prefix web
npm run build --prefix web
.venv/bin/python -m vault_rag.cli model-prepare
.venv/bin/python -m vault_rag.cli service install
.venv/bin/python -m vault_rag.cli service open
```

`service start/stop/restart/status/uninstall` 管理 macOS 用户 LaunchAgent。登录后启动、异常退出重启；只有一个 worker 和一个模型实例。首次网页关联本机目录，之后在设置中切换。手动运行用 `vault-rag serve`；启动前确保没有另一实例占用端口。

## 文件与日常功能

实时 Markdown 编辑、源码与阅读切换、自动保存、草稿保护、属性、双链与嵌入、目录和关系图。保存必须携带文件版本；冲突保留编辑内容。原子写入保留换行方式，属性修改保留 YAML 注释和未知字段。

移动或重命名修复明确可解析的 Markdown/wikilink/附件引用；歧义不猜测，代码块不替换。删除进入回收区，历史和目录操作可恢复。媒体按需读取，视频支持 Range；HTML/SVG 隔离内容不执行脚本。

支持当前资料使用的 Dataview TABLE/LIST、FROM、WHERE、GROUP BY、SORT、LIMIT、contains/length 与 file 属性；不执行查询脚本。支持当前 `.base` 的表格、TaskNotes 看板、日历、迷你日历和任务列表。模板支持现有日期和光标占位符，不执行任意 Templater JavaScript。未实现通用 Obsidian 插件、Canvas 编辑器、云同步和通知提醒。

## 检索范围

网页浏览完整关联目录；知识检索仅使用设置里勾选的目录。默认 RAG，允许多目录和子目录排除，空选择是零语料。仅索引 `.md`/`.txt`，媒体不转写。保留 `.ragignore` 和 frontmatter 退出状态，拒绝路径与符号链接越界。Navigation 是路由资料，不作为正文证据；规则和工时保持专用范围。

- `vault_search(query, top_k=3, note_type=None, domain=None, compact=True, mode="hybrid")`
- `mode=hybrid|wiki|rag|keyword`；精确关键词可以独立命中，向量失败明确降级。
- `domain="estimation"` 查询 EstimationDB；一般技术检索排除工时。
- `rule_search` 仅查询选中的规则目录；PCG 项目知识仍由项目本地工具管理。
- `vault_get_chunk` 读取证据片段；`vault_get_note(note_id)` 读取合格笔记完整正文和公式。
- `vault_index_status` 返回范围、写入位置、模型、同步进度和最近错误。

`limited`/`verified_true` 优先，缺少状态或 unverified 补充；Wiki 不提高来源可信度。机械目录自动维护，主题总结仅在显式整理时修改；来源版本变化标记待更新。

文件变化自动检测，embedding 以模型/输入指纹缓存。每次发布完整独立 generation，失败保留旧版本；取消目录或退出文件立即过滤。保留最近两代索引，旧 Ollama 向量不复用。模型版本、pooling、维度和归一化写入指纹。

## 客户端

Codex 使用 `[mcp_servers.user-vault-rag]` 的 `url` 与 `http_headers.Authorization`。Cursor 使用 `url`、`headers.Authorization`；Claude Code 使用 `type: http`、`url`、`headers.Authorization`。本机令牌来自私有配置目录，勿提交到共享配置或日志。共享示例只使用占位符。

网页本地会话、写入 CSRF 校验、Host/Origin 检查以及 MCP bearer token 分别落实。服务仅监听 127.0.0.1。程序升级后重启服务，客户端重新连接。

## 检查

相关自动检查在 `tests/test_local_knowledge.py`，覆盖版本冲突、CRLF/YAML 保留、目录/符号链接隔离、移动回滚、查询解释器、领域隔离、构建失败和 HTTP/媒体 Range。本次部署的实际检索与浏览器验收记录保存在 `~/Library/Application Support/VaultRag/backups/local-knowledge-2026-10-12/`。
