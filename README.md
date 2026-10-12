# 本地知识库

一个进程提供本地网页、HTTP MCP 和 BGE-M3 推理。原文件保留在关联目录内；不依赖 Ollama，也不另外启动 Node 网页服务。

- 网页：http://127.0.0.1:18080/
- MCP：http://127.0.0.1:18080/mcp
- 配置与模型：macOS 使用 `~/Library/Application Support/VaultRag`；Windows 使用 `%LOCALAPPDATA%\VaultRag`。本机令牌私有保存，也可用 `VAULT_RAG_HOME` 指定目录。
- 元数据、索引、版本历史和回收区：关联目录下 `.vault-rag/`，始终排除正文检索。

## 安装与启动

### Windows 10/11 x64

双击仓库根目录的 **`Start.cmd`**。首次会显示安装进度，自动补齐缺少的 Python/Node、安装依赖、构建网页和下载 BGE-M3；成功后打开本地网页。也可双击 **`Install.cmd`** 主动安装或更新。首次需联网，正常启动使用本地环境，不下载模型。

之后登录会自动运行后台服务和右下角托盘图标，不弹网页。双击启动入口或托盘图标打开网页；重复启动复用同一个服务。托盘右键提供状态、启动、停止、重启、日志、登录启动开关和退出。“退出”正常停止服务并关闭托盘。**`Stop.cmd`** 只停止服务，下次登录仍按登录启动设置运行。Windows 可能把托盘图标收进“隐藏图标”，可在系统设置中选择显示。

运行环境下载到用户私有目录，项目虚拟环境位于 `.venv`；无需管理员权限，不修改系统 PATH。固定版本和 SHA256 在 `scripts/runtimes.json`，Python 包使用跨平台 `uv.lock`，Windows 使用 CPU PyTorch。安装失败显示阶段、原始错误摘要和日志位置，重新双击可重试；不兼容的旧环境自动保留为备份。企业策略若禁止下载或创建计划任务，会明确失败，不绕过组织策略。

具体配置、排障和验收见 [安装指南](docs/SETUP.md)。

### macOS 14+ Apple 芯片

在仓库目录的终端运行 **`sh Start.sh`**，或双击仓库内的 **`本地知识库.app`**。首次自动下载私有 Python/Node、构建网页、安装依赖、准备模型和当前用户后台服务，完成后打开网页。主动安装或修复在仓库目录的终端运行 **`sh Install.sh`**（入口不需要可执行权限），停止运行 **`sh Stop.sh`**。三个 `.sh` 入口均不需要可执行权限。无需预装 Homebrew、Python、Node 或 Xcode。

`Install.sh` 先检查现有环境，完整且未变化时跳过安装；需要修复或更新时只处理受影响的依赖、网页和模型，复用其余组件。更新依据当前仓库的版本和锁定文件。

菜单栏应用安装到 `~/Applications/本地知识库.app`，登录时启动服务与图标，不弹网页。运行环境仅保存在用户私有目录；Intel Mac 和 macOS 13 及以下不在本次支持范围。macOS 原生验收本次按要求跳过，不能将 Windows 结果当作 Mac 实测结果。

`service start/stop/restart/status/uninstall` 管理当前平台的用户后台服务。macOS 使用 LaunchAgent，Windows 使用普通权限的当前用户计划任务。登录后启动、异常退出重启；只有一个 worker 和一个模型实例。首次网页关联本机目录，之后在设置中切换。手动运行用 `vault-rag serve`；启动前确保没有另一实例占用端口。

## 文件与日常功能

网页采用白色正文、浅灰侧栏的文档工作台布局。`Cmd/Ctrl+K` 打开文件快捷搜索；侧栏的“知识检索”独立展示知识与工时资料的检索依据，打开来源后可返回原查询。顶部显示当前文档的路径，点击父级目录可返回目录列表；导航可收起和调整宽度，窄屏使用抽屉；正文支持标准/宽版切换，属性、目录和关联文档放在可折叠的“文档信息”面板中。布局偏好与最近打开的路径按关联目录隔离保存。改版与验收记录见 [页面改版](docs/NOTION_UI.md)。

普通笔记默认阅读，新建笔记直接编辑。支持实时 Markdown 编辑、源码与阅读切换、自动保存、草稿保护、属性、双链与嵌入、目录和关系图。保存必须携带文件版本；外部修改自动更新未编辑正文，有草稿时提示冲突并保留内容。原子写入保留换行方式，属性修改保留 YAML 注释和未知字段。

目录旁的 **“刷新数据”** 更新当前正文、已展开目录和相关视图，保留当前位置与界面。浏览器 F5 会重新加载前端，后台服务和模型继续运行。页面先显示框架，编辑器、图谱、公式和图表按需加载；正文缓存仅在内存中保留，草稿、光标、阅读位置和媒体进度用于恢复。最多驻留三个近期文档，HTML/PDF 仅当前页面保留 iframe；重新打开 HTML 会重新执行页面脚本。

移动或重命名修复明确可解析的 Markdown/wikilink/附件引用；歧义不猜测，代码块不替换。删除进入回收区，历史和目录操作可恢复。媒体按需读取，视频支持 Range；HTML 默认作为网页浏览，可切换源码、全屏阅读或独立标签页；支持本地样式、脚本、图片、相对链接及 Markdown 下载。网页预览使用内存快照与临时只读地址，不因预览写入文件；脚本在隔离环境运行，不能访问知识库编辑器或写入 API。切换关联目录、重启服务或预览地址被回收后，点击刷新重新打开。网页主题与字号可调整，但不保存网页自身的 localStorage；远程 CDN 与联网接口不在支持范围内。普通媒体入口中的 HTML/SVG 仍不执行脚本。

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

文件监听自动检测外部修改，通常两秒内反映到前台；启动及每 60 秒进行后台核对。监听不可用时页面显示降级提示，改为每十秒检查。图片、网页资源和视频只维护路径信息，不读取为笔记正文，也不因素材修改重建向量。目录同步与模型构建独立运行，embedding 以模型/输入指纹缓存。每次发布完整独立 generation，失败保留旧版本；取消目录或退出文件立即过滤。保留最近两代索引，旧 Ollama 向量不复用。模型版本、pooling、维度和归一化写入指纹。

## 客户端

Codex 使用 `[mcp_servers.user-vault-rag]` 的 `url` 与 `http_headers.Authorization`。Cursor 使用 `url`、`headers.Authorization`；Claude Code 使用 `type: http`、`url`、`headers.Authorization`。本机令牌来自私有配置目录，勿提交到共享配置或日志。共享示例只使用占位符。

网页本地会话、写入 CSRF 校验、Host/Origin 检查以及 MCP bearer token 分别落实。服务仅监听 127.0.0.1。程序升级后重启服务，客户端重新连接。

## 检查

Windows 定向检查可运行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\check.ps1`；加 `-ServiceSmoke` 会在独立临时配置下检查真实 Windows 后台任务的启停，不下载模型，也不改当前关联目录。安装验收记录见 [安装验收](docs/INSTALL_VALIDATION.md)；图标视觉与实际重新登录仍待人工验收，不能用后台任务检查代替。

相关自动检查在 `tests/test_local_knowledge.py`，覆盖版本冲突、CRLF/YAML 保留、目录/符号链接隔离、移动回滚、查询解释器、领域隔离、构建失败和 HTTP/媒体 Range。本次部署的实际检索与浏览器验收记录保存在 `~/Library/Application Support/VaultRag/backups/local-knowledge-2026-10-12/`。

浏览性能、缓存和监听的验收方式与本机结果见 [浏览性能验收](docs/BROWSING_PERFORMANCE.md)。
