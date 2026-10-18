# 本地知识库架构

[架构与工作流程图](assets/workflow.svg)

## 进程和接口

Dev 和安装版共用 Tunnel 配置、应用启动／退出生命周期；存在已注册安装时，Dev 选择安装版的运行文件，纯源码环境使用已验证的仓库运行文件。`tunnel_owner.py` 用共享状态目录内的操作系统文件锁限制受管运行时单实例，随进程退出自动释放；`tunnel.py` 在退出和错误路径始终关闭持有的进程 Job。Windows Job 在后端异常退出时回收子进程。独立手动启动的旧 CLI 不会被当作已授权实例复用。

一个 Python ASGI 进程提供本地网页、文件 API 与 HTTP MCP；BGE-M3 和向量任务在独立的 `rag_process` 中运行。网页由预构建静态文件提供，Node 只用于安装/构建；模型由检索工作进程延迟加载。正常客户端不通过 stdio 再启动服务或加载模型。

源码桌面开发通过 `Dev.cmd`（Windows）、`Dev.command` / `sh Dev.sh`（Mac）或 `node scripts/dev-desktop.cjs` 启动：Dev 与安装版通过 `desktop/state-home.cjs` 共用同一用户数据目录、配置、模型、凭据与桌面 profile；后端沿用共享配置中的端口（新配置默认 18080），仅开发 Python 环境位于 `.cache/desktop-dev/.venv`，Vite 使用 5173。未打包桌面端显式传入开发地址时，`dev_frontend.py` 从 Vite 获取入口和模块，保留原有工作区域名、API 认证与 HTML 项目隔离；前端通过本机 WebSocket 自动更新。生产桌面端移除该开发变量，普通服务不隐式读取它。详见[桌面开发](DESKTOP.md#source-development)。

可选的 `scripts/dev-browser.py` 显式配置开发前端，直接运行正常 `Runtime` 与后台工作，不使用测试夹具、不自动下载模型或调用外部 AI。`--home` 必填，仅接受新建／空目录或此启动器标记过的专用目录；标记固定端口与界面模式，变更须新建目录并更换浏览器 profile。默认保留 `app.<installation-id>.localhost`，仅显式 `--loopback-ui` 将管理界面改为 `localhost`。Vite 必须单独运行在 `http://127.0.0.1:5173`，避免接收 localhost 管理会话 cookie。此入口不更改常规桌面启动，也不代表支持 Linux 桌面安装，详见[浏览器开发](DESKTOP.md#optional-browser-development)。

生产 MCP 注册位于 `mcp_tools.py`，完整笔记工作流位于 `note_operations.py`，设计项目与图层工作流位于 `design_studio.py`，与网页共用 `Files` 的访问边界；受管设计文档使用独立的版本事务与持久历史。网页模板和日记复用笔记工作流。`mcp_access.py` 在私有配置保存本机凭据哈希与独立权限，Tunnel 凭据只驻留后端内存并通过环境引用注入运行时的发现及调用请求。旧五项只读工具保持原有范围；内部 `/ai-mcp` 允许读取设计项目，但只有用户在当前对话附加的设计项目可以直接应用设计事务。完整 MCP 访问须显式启用，两个连接的写入分别授权。工具、分页、版本与错误契约见 [MCP](MCP.md)。

- 网页入口：`http://127.0.0.1:18080/`；浏览器迁移到 `http://app.<installation-id>.localhost:18080/`，端口跟随配置。

Tunnel 内部凭据通过 `X-LeafLoom-Tunnel-Authorization` 注入发现与业务请求，与聊天连接的 `Authorization` 分离，避免运行时转发聊天 bearer 时覆盖内部身份。HTTP 入口和工具执行前均校验真实回环来源及当前内存密钥；无效证明直接拒绝，不降级为 legacy。授权仍逐次从 `McpAccess` 检查，关闭资源权限继续立即生效，该请求头不提供网页管理 API 权限。
- HTTP MCP：`http://127.0.0.1:18080/mcp`
- 健康检查：`/healthz`；启动入口随后使用本机令牌验证 `/api/status`，避免复用另一安装实例。
- 文件写入采用版本校验、草稿保留、原子替换；历史、移动回滚和回收区位于知识目录的 `.vault-rag`。

## 飞书接入

可选飞书接入由 `feishu.py` 包装使用者自行配置的原生 lark-cli，设置 API 和 HTTP MCP 共用一个适配器。CLI 负责登录与凭据；LeafLoom 的私有 `feishu.json` 仅保存接入选项和脱敏验证快照。按参数数组调用，文档正文经 stdin 传递；命令有超时与输出限制，固定使用 user 身份及所选 profile。本机与 Tunnel 的飞书读写权限独立于笔记权限，复用各连接的 MCP 专用凭据；旧配置不自动授权飞书。适配器在本实例内串行操作，不自动导入或索引远端内容。详见[飞书接入](FEISHU.md)。

## 平台边界

`platform_support` 处理配置目录、权限、Windows 文件名、链接/junction、目录选择和错误弹窗。私有状态默认位于 macOS Application Support/VaultRag 或 Windows LocalAppData/VaultRag，支持 `VAULT_RAG_HOME` 覆盖。文本明确使用 UTF-8；知识库内容保存保留 BOM 和换行形式。

安装版由 Electron 管理窗口、托盘／菜单栏、登录启动和私有 Python sidecar，退出时正常停止自己拥有的后端及检索工作进程。开发模式通过 Dev 启动 Vite 与源码 Electron，复用安装版的用户数据与单实例锁；切换前正常退出当前应用。开发依赖保持独立，隔离测试通过显式临时 `VAULT_RAG_HOME` 指定。旧 Dev 模型仅在共享 `models/` 缺失时经暂存复制复用，旧配置与源模型保留。

Windows `windows_native` 使用当前用户与配置目录区分本地实例，正常退出不按进程名称强制结束其他 Python 程序。`service_control`、旧计划任务／LaunchAgent 和脚本托盘实现仅作为历史安装迁移与内部兼容代码保留；根目录旧服务启动入口已移除。

桌面更新由 `desktop/updater.cjs` 在主进程中处理：固定 GitHub Release 来源、按平台选择安装包、流式下载进度与大小／SHA-256 校验，安装前再次校验。可信工作区通过 IPC 检查版本、读取进度及发起下载安装；正常退出保护草稿后打开安装向导或 DMG。源码 Dev 只检查版本，详见[桌面更新](DESKTOP.md#update-implementation)。

## 安装与依赖

安装版通过 Release 安装包分发，由应用自身管理启动、退出和更新。构建过程按 `uv.lock` 准备私有 Python 依赖并构建前端；流程见[桌面构建](DESKTOP.md)。源码开发通过 Dev 同步独立 Python 环境，直接运行 Vite，不构建安装包或注册旧服务任务。

Windows 使用官方 CPU PyTorch 软件源及锁定的 `msvc-runtime` wheel；包入口注册 DLL 搜索目录。Windows 与 macOS 共用跨平台 `uv.lock`，Dev 使用独立 uv 缓存与环境。检索模型按需准备；安装包资源的版本与校验信息仍由构建清单管理。

## 知识范围和索引

网页浏览完整关联目录，检索仅使用用户选择的目录。隐藏目录、应用目录、符号链接和 junction 不进入浏览或检索；规则、导航和工时保持各自领域隔离，退出文件立即过滤。

目录同步线程使用 watchfiles，事件最多合并 500 ms；启动和每 60 秒核对，监听失败时每十秒核对。所有可访问文件维护路径、名称、类型和目录表，只有 Markdown/TXT/Base 读取正文或元数据。SQLite 局部 upsert/delete，名称、ID 和引用解析维护内存索引；目录更名更新子树，超过一千项的批次转为后台核对。应用生成目录过滤，`.ragignore` 单独处理。

向量线程与目录线程独立，快速捕获配置与不可变目录快照后释放读取锁，再进行分块和推理。按模型/输入指纹复用 embedding 缓存，构建独立 generation，验证范围版本后原子发布。失败保留旧快照，保留最近两代索引；关键词和 Wiki 通道在向量尚未就绪时明确降级。模型仅一个实例，CPU 推理线程限制为两条。

BGE-M3 使用本地已准备的权重；macOS 优先 MPS 并可回退 CPU，Windows 默认 CPU。官方模型修订、pooling、归一化和维度写入指纹。普通推理不联网下载模型，不依赖 Ollama。

## 页面加载与缓存

`GET /api/session` 返回配置、CSRF、服务实例、目录版本与主界面地址；兼容保留 `/api/bootstrap`。`GET /api/events` 复用网页会话，通过有界异步队列发布文件、配置和状态变化；断线重连或版本缺口发送 reset。SSE 等待不占用文件读取线程池。模型状态接口读取内存，准备/加载/预热更新状态，磁盘校验每 30 秒后台执行；安装和加载仍执行完整校验。模型准备通过状态流发布启动、连接、下载、校验与完成/失败阶段；Hub 进度回调提供文件完成数与网络接收量，前端显示速度、已用时间与等待提示。准备请求在启动后台线程前去重，下载等待不受普通检索的十分钟超时限制；工作进程退出仍会唤醒等待者。下载校验所得的权重摘要直接复用于准备凭据，避免重复读取大文件。模型状态同时返回实际保存路径；`POST /api/model-directory/open` 复用本机会话与 CSRF 校验，仅打开当前服务的固定模型目录，不接受客户端路径，必要时创建空目录。

前端入口不包含编辑器、图谱、Mermaid、KaTeX 或 Base。请求按服务实例、根目录、配置版本和路径隔离，合并同一读取，最后消费者离开时取消；仅读取允许重试。正文 LRU 上限 64 条或 32 MiB，不写入浏览器持久缓存。草稿和阅读状态另行保存，最多驻留三个文档，HTML/PDF 仅当前标签驻留。Markdown 正文初始解析在文本估算大小超过 256 KiB 时使用 Worker；源码编辑器与其他预览内容按各自模块加载。超过两百项的目录、列表、表格和任务视图使用 TanStack Virtual。

哈希命名的静态资源 immutable 一年，入口与会话 no-store。知识素材 private/no-cache，校验根目录与权限后处理 ETag/304、视频 Range；媒体 ETag 包含根目录与配置版本。HTML 快照正文 no-store，配套资源可条件校验，失效地址即使携带旧 ETag 也不能得到 304。

## Design Studio 编辑模型

`design_documents.py` 以项目内 `Design/studio/project.json` 为编辑真源，保存具有稳定 ID 的页面、元素、素材、组件、样式与脚本。网页、公共 MCP 和内置 AI 共用同一批量命令及版本校验；一次指令作为一个事务，旧版 `design_studio.py` 接口保留兼容适配。项目私有 `.vault-rag/design-studio/<id>/history.sqlite3` 保存正反差量、请求回执、周期检查点与未完成提交，衔接 SQLite 与 JSON 原子替换；恢复与撤销遇到外部修改时保留冲突数据，不覆盖新内容。

`design_workspace.py` 管理项目组织、移动与回收、版本共享库和独立 ZIP 导出，工作区管理历史与项目编辑历史分离；项目回收站的永久清理先提交移除元数据与相关管理历史，再按持久日志清理文件和该项目的设计数据库，启动恢复可继续未完成清理；项目管理中的显示名称用于工作台、复制和导出。跨项目组件导入将闭包依赖及二进制资源落盘，显式选择版本更新。`design_references.py` 静态识别声明式引用、原生资源路径和受支持的脚本字面量调用，供素材保护、替换、引用展示及共享库闭包收集复用，不执行项目代码。迁移先复制旧项目，再由隔离来源捕获原生 DOM/CSS；原脚本保留在副本源码，任意动态行为不自动转译。

`design_routes.py` 提供网页接口；React `design-workbench` 按需加载，串行保存并保留待处理指令及源码草稿。页面投影只传输活动页面和递归嵌入依赖，其他页面保留摘要；引用索引按版本缓存，避免丢失未加载页面的素材使用位置。素材列表虚拟化，缩略图在 Worker 中以有界队列生成。项目来源的 `design_assets/studio/runtime` 接收经过来源、父窗口与会话校验的文档，按活动页面渲染，命名空间隔离嵌入内容。拖动只在帧内更新选中节点，结束提交一次操作；同页简单修改增量应用到已有 DOM。顶部编辑/预览切换先通过同源校验的消息提交帧内文字，等待保存队列完成后才用最新文档进入预览；保存失败保留队列并阻止旧内容预览。返回时恢复编辑页与选择，运行时按页面/模式保留相机。编辑状态暂停脚本，预览通过 `mount(ctx)` 提供受跟踪事件、计时器、动画、消息和页面导航，停止时清理并从设计文档重建。导出复用同一渲染器，包含素材与本地脚本依赖。数据契约、运行限制和验收目标见 [Design Studio](DESIGN_STUDIO.md)。

## Markdown 编辑与原文保存

Markdown 默认在 Tiptap/ProseMirror 正文编辑器中打开，CodeMirror 提供源码编辑。`rich-markdown` 将可编辑块与原文片段关联，仅重新序列化发生变化的块，保留未修改原文、文档前缀与后缀；复杂或不支持直接编辑的内容通过保留节点展示并可跳转源码。较大正文的初始解析交给 `rich-markdown.worker`。

`document-state` 管理正文、版本标识、本地草稿和自动保存；`edit-history` 在正文与源码之间共享撤销记录。正文映射与 `source-offsets` 处理编辑位置及换行偏移；后端保存继续校验版本并保留 BOM 和原文换行。外部修改与保存冲突保留当前草稿，AI 草稿仍需明确保存。

附件上传使用现有文件接口，显式携带所属根目录，在知识库中创建统一的 `_attachments`（或配置的 `attachment_folder`）并生成唯一文件名。上传后的文件与插入链接分别管理，撤销链接或取消后续插入不会删除已上传的文件。操作说明见[使用指南](zh-CN/GUIDE.md#用命令快速编辑)，回归入口见[贡献说明](../CONTRIBUTING.md)。

## 本机安全

仅监听回环地址。Host/Origin 校验、网页会话、写入 CSRF 和 MCP bearer token 分别实施。本机令牌放在私有配置目录，不输出到共享 MCP 示例。macOS 使用 POSIX 权限；Windows 状态目录取消继承并授予当前用户和 SYSTEM 权限，子文件继承此保护，不改用户知识目录 ACL。

HTML 按项目作为独立来源的网站运行；桌面窗口和浏览器共用同一份前端与容器。主界面与项目使用同站不同源的 `.localhost` 地址，原回环网页入口迁移本地草稿后打开主界面，MCP 地址保持不变。原始网页字节不注入脚本，草稿使用临时来源；资源请求在进入管理路由前分流。项目设置、会话与迁移详见 [HTML 网页运行](HTML_PROJECTS.md)。Windows 路径还拒绝备用数据流、设备名、尾随点/空格和无效字符；目录范围与链接解析按 Windows 大小写行为比较，外部路径不能借 junction 越界。

浏览器开发的 `--loopback-ui` 不改变鉴权、CSRF、Host/Origin 校验或开发 CSP，也不将不可信 HTML 与草稿并入管理来源；`p-` / `d-` 项目来源保持独立。受管云浏览器中曾观察到 `*.localhost` 即使显式 HTTP 也报 TLS 错误，而 `localhost` 可用；浏览器升级／代理机制的具体原因尚未证实，项目预览仍可能受限。不要绕过安全警告。每个开发状态目录使用专用浏览器 profile：localhost cookie 不按端口隔离，同一来源用于无关目录还可能混用草稿。

安装和实际 Windows 验收步骤见 [SETUP.md](SETUP.md)。

飞书 MCP 改为五个通用入口：状态、CLI 发现、只读执行、写入执行、临时文件传输。能力与风险按已安装 CLI 的 help/schema 动态发现并缓存，不再逐项包装文档或 Base。高风险权限按连接独立保存，默认关闭，执行仍须明确确认。临时文件按凭据代际隔离，在独立命令工作目录内传递；已关联附件导入及其派生产物继续检查笔记读取权限。旧四个业务工具已移除，客户端升级后须刷新工具列表。接口、额度、版本保护和迁移规则见[飞书接入](FEISHU.md)。

### Built-in design starters

`vault_rag/design_templates.py` allowlists packaged starters in `design_assets/templates/`. The new-project UI submits a template ID through the existing rooted managed-project API. FORMA contains four pages and 328 native layers; its artwork is self-contained CSS. Creation validates the document, rejects existing destinations, deep-copies it with a fresh document ID and initializes ordinary project history. Runtime files continue to come from the installed Studio runtime; no template code runs in the management origin. Preview images are served through the authenticated design API.

### Design binding projections and offline publication

`design_bindings.py` validates stable text/image content keys and lightweight
variant deltas, resolves a detached rendering projection, and participates in
`DesignDocuments` atomic operations and durable undo. Canonical source nodes stay
consistent with their bindings. Layout override references are pruned when their
nodes are deleted. Assets remain shared by registry ID; source/variant image
references participate in replacement and deletion checks.

`design_publishing.py` snapshots a saved revision and registered asset bytes into
bounded jobs. Desktop's trusted main-frame IPC accepts only a job ID; it fetches
the authenticated manifest and renders it in an ephemeral sandboxed Electron
session with an in-memory resource allowlist, denied permissions, no preload and
no external network/filesystem access. Authored scripts and animation are disabled
only for static output. Headless publication uses an optional Playwright renderer
with the same offline boundary. The backend validates native output dimensions
and combines PDF pages or PNG files in selected order. Progress and retries are
job-scoped and retain accepted results and the frozen revision.

## 附件元数据索引与管理入口

`vault_rag/attachment_index.py` 在关联目录的 `.vault-rag/attachments.sqlite` 保存可重建的路径、文件名、大小、修改时间与 MIME 元数据；原文件仍为事实来源，不迁移文件、不改写链接。附件管理器先只读检查状态，首次初始化或已知旧版升级必须点击按钮；后台刷新与文件变更批次用于核对可用索引；扫描不解析笔记或读取附件正文，独立于 RAG。名称索引也服务于文件名解析。

`GET /api/attachments?query=&after=&limit=100` 按路径进行 keyset 分页，返回 `items`、`next_cursor` 与 `total`；`GET /api/attachments/status` 只读返回版本、可用性与作业状态；`POST /api/attachments/initialize` 显式启动初始化／已知旧版升级，`POST /api/attachments/rebuild` 启动后台元数据刷新，`POST /api/attachments/index-cancel` 请求停止。写请求携带 `root`，前端轮询状态直到终态，并对关闭与根目录切换取消请求。已知旧版本先备份，不支持的版本拒绝覆盖。只有可用数据库才加载附件列表；初始化不启动下文的文件迁移。列表只包含 `.md`、`.txt`、`.base` 之外的可浏览文件，包含 HTML 项目资源。耗时操作通过工作线程执行。

侧栏的附件管理弹窗每次仅保留一页（最多 100 项），通过现有受保护的 `media(..., true)` 接口下载。它不嵌入或运行 HTML，也不改变 HTML 项目的独立来源。请求采用 AbortController 和代次校验防止过期响应覆盖新结果；关闭、切换目录或配置版本会清理请求。取消客户端等待并不保证停止已经开始的服务端扫描。此阶段不提供引用分析、去重或缩略图。

这是路径索引而不是文件身份库：同名文件保留多个候选，笔记相对路径优先，不自动选择任意同名文件。现有 `catalog.sqlite` 仍负责笔记元数据与链接；新索引专门避免冷启动／懒加载目录中的附件名称解析反复遍历整库。完整目录索引的名称查找也使用平台规范化键直接查表。

索引事务只在完整扫描成功且关联根目录未变化时提交；读取失败保留上一代，较新数据库版本拒绝打开，原文件不受影响。列表和解析候选均重新检查访问边界。`last_scanned_at` 表示最近一次成功的完整扫描时间，`total` 是缓存索引中的匹配数量，不是文件仍存在或没有引用的证明。重新启动复用索引；关闭期间的变化、监听失效或外部变更尚未同步时，应手动刷新。

本阶段不保存二进制 BLOB：这不会减少图片解码成本，反而会引入文件迁移、备份与流式 Range 读取的兼容成本。缩略图应作为按需生成的派生缓存；重复检测应按需计算内容摘要，并且不能仅凭同名或摘要删除原文件。完整引用分析还需要覆盖 Markdown、HTML/CSS、历史与外部链接，不能把“未发现引用”直接解释为“可删除”。

隔离云端夹具测试（5,000 个附件、50 个目录、20 次缺失文件名查找）中，原重复遍历约 2.689 秒，新索引一次构建约 0.277 秒，20 次热查询约 0.0145 秒，重启后查询约 0.0011 秒。此结果仅衡量文件名解析，不代表真实笔记整体渲染或大图解码加速比例。

## 可恢复的附件迁移

附件列表仍只查询可重建元数据，迁移通过独立的异步作业执行。`POST /api/attachments/migrations` 携带 `root` 与相对路径 `destination` 创建只读预览；`GET /api/attachments/migrations` 列出保存的任务，`GET /api/attachments/migrations/{id}` 读取状态、阶段、进度、摘要、路径变更、排除项和阻止项。路径列表可以只返回前 200 项，文件总数以摘要为准。默认目标为 `_attachments`；成功迁移后的编辑器上传使用配置中的 `attachment_folder`。

只有就绪且没有阻止项的计划才可通过 `POST .../{id}/execute` 并携带 `{root, confirm:true}` 执行。`cancel` 请求在安全边界停止；`resume` 和 `rollback` 均需明确确认。前端关闭、切换根目录或卸载只取消客户端等待与轮询，重开后从服务端读取持久化任务。服务重启后必须从日志重新验证，而不是假定此前全部成功。

每个任务的恢复目录为 `.vault-rag/attachment-migrations/{id}/`，包括 `manifest.json`、原附件 `originals/`、笔记备份 `notes/`。应用前校验文件漂移、目标冲突、访问边界和可用空间；恢复时遇到后续编辑应报告冲突，不得覆盖用户新内容。该流程不永久删除恢复材料，也不按同名或相同摘要自动去重。

静态引用规划独立于附件列表扫描，本阶段仅改写支持的 Markdown／Wiki 引用。按用户范围，HTML 文件、项目拥有的资源和 HTML 共享资源保持原位，列为明确排除项，不改写 HTML/CSS。动态脚本、无法解释或存在歧义的引用必须阻止迁移，不能承诺“没有发现引用”等同于“无引用”。外部引用与工具不可审计，因此执行前需用户核对风险。操作说明与恢复步骤见三语使用指南的附件管理章节。
