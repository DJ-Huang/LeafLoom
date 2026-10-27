# 本地知识库架构

[架构与工作流程图](assets/workflow.svg)

公开官网与帮助中心使用独立静态构建：`scripts/build_site.py` 调用 `scripts/build_docs.py`，从三语 Markdown、`docs/help/navigation.json` 和语言目录生成 `/docs/{en,zh-CN,ja}/`、搜索数据与 sitemap，再由 Pages 发布。`site/help/` 提供展示与渐进增强，搜索仅加载当前语言的公开文章 JSON，不调用应用 API 或访问知识库。应用侧栏只打开外部帮助链接。内容维护与构建依赖见[官网说明](WEBSITE.md#help-center)。

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
- 笔记工作流在配置／文件锁内仅完成文件、历史与回执，不同步调用 `Catalog.apply`。目录工作线程持有 `update_lock` 后会读取配置快照，反向等待会造成已落盘保存的回执死锁。变更通过 `Runtime.files_changed` 合并排队，并立即通知界面、使全局元数据失效；精确路径读取不依赖目录就绪，全局查询沿用 `metadata_pending` 与后台准备流程。

## 通用附件 MCP

公共 HTTP MCP 与 ChatGPT Tunnel 共用 `vault_files`（只读）和 `vault_files_update`（修改）两个入口，参数由 `file_commands.py` 的可辨识联合类型限制。`file_operations.py` 适配现有附件索引、整理恢复日志与 ZIP 任务；共用 `attachment_uploads.py` 的流式暂存与不覆盖发布逻辑。ChatGPT 文件参数元数据随工具发现返回，宿主文件引用通过 `file_downloads.py` 进行有界 HTTPS 下载，逐跳验证公网地址并固定连接地址和 TLS 主机名。

传输归属绑定连接凭据代际和知识库版本，原文件读取还绑定文件版本。后台任务在安全边界重新检查当前权限；恢复记录保留在原知识库。上传操作回执保存在 `.vault-rag/file-receipts/`，原始上传字节只在私有临时目录暂存。网络读取和大文件复制期间不持有全局权限锁，发布前短暂持锁重新校验。浏览器与 MCP 发起的恢复动作各自重新授权，内部失败恢复不依赖已撤销的旧连接。

## 设计素材的服务端引用导入

`design_import_asset` 保留 Base64 入口，并可用 `source_path` 引用已关联知识库内的文件，或用 `source_file_id` 引用飞书 CLI / 临时文件池返回的文件。MCP 只传小型引用，避免媒体经过调用方往返及 Base64 膨胀；`include_document:false` 也避免每个素材重复返回完整项目。文件读取有 128 MiB 上限、普通文件与前后身份检查，可用 SHA-256 固定内容，之后复用现有设计资产注册事务与撤销历史。

相对路径继续经过 `LocalConfig.path_for`，不开放任意服务主机路径。飞书文件 ID 在当前连接身份下重新检查飞书读取权限、凭据归属、完成状态及原知识库来源授权；ID 本身不授予额外访问。旧 Base64 参数与默认完整返回兼容，外层 HTTP 请求限制不因此扩大。

## 飞书接入

可选飞书接入由 `feishu.py` 包装使用者自行配置的原生 lark-cli，设置 API 和 HTTP MCP 共用一个适配器。CLI 负责登录与凭据；LeafLoom 的私有 `feishu.json` 仅保存接入选项和脱敏验证快照。按参数数组调用，文档正文经 stdin 传递；命令有超时与输出限制，固定使用 user 身份及所选 profile。本机与 Tunnel 的飞书读写权限独立于笔记权限，复用各连接的 MCP 专用凭据；旧配置不自动授权飞书。适配器在本实例内串行操作，不自动导入或索引远端内容。详见[飞书接入](FEISHU.md)。

## 平台边界

`platform_support` 处理配置目录、权限、Windows 文件名、链接/junction、目录选择和错误弹窗。私有状态默认位于 macOS Application Support/VaultRag 或 Windows LocalAppData/VaultRag，支持 `VAULT_RAG_HOME` 覆盖。文本明确使用 UTF-8；知识库内容保存保留 BOM 和换行形式。

安装版由 Electron 管理窗口、托盘／菜单栏、登录启动和私有 Python sidecar，退出时正常停止自己拥有的后端及检索工作进程。开发模式通过 Dev 启动 Vite 与源码 Electron，复用安装版的用户数据与单实例锁；切换前正常退出当前应用。开发依赖保持独立，隔离测试通过显式临时 `VAULT_RAG_HOME` 指定。旧 Dev 模型仅在共享 `models/` 缺失时经暂存复制复用，旧配置与源模型保留。

应用菜单和托盘提供“重启 LeafLoom”，复用主窗口的草稿准备与 `beforeunload` 确认。取消确认会清理重启意图；本地服务停止后，只有真正进入 `will-quit` 才安排重新启动。安装版用 Electron `app.relaunch`，保留状态目录和自定义参数、移除 `--background` / `--quit`，以前台打开。Dev 启动器为本次会话传入独立重启请求文件；只有正常退出且有请求才继续启动，崩溃、普通退出或 Ctrl+C 均不触发重启循环。Dev 重启保留 Vite，先同步锁定的 Python 依赖并重新检查品牌运行文件，再打开当前源码。桌面菜单的新翻译同样由 `messages.tsv` 经 `compile_locales.py` 生成 `desktop/menu-messages.cjs`。

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

`design_inspection.py` 为公共 MCP 与内置 AI 提供独立的分页投影：默认只返回页面、元素或资源摘要，按 ID 显式读取原始源码；节点索引和计数随现有有界解析缓存按内容版本复用，不深拷贝全项目。分页可传 `expected_revision` 固定版本。MCP 修改、撤销和导入默认返回短回执，`full`／`include_document` 显式保留完整读取方式；网页编辑器的数据契约不变。公共 MCP 的 JSON 归一化与编码在工作线程中执行，保留文本和结构化结果兼容性；完成日志仅记录操作名、耗时、文本字符数与错误标志。

`design_workspace.py` 管理项目组织、移动与回收、版本共享库和独立 ZIP 导出，工作区管理历史与项目编辑历史分离；项目回收站的永久清理先提交移除元数据与相关管理历史，再按持久日志清理文件和该项目的设计数据库，启动恢复可继续未完成清理；项目管理中的显示名称用于工作台、复制和导出。跨项目组件导入将闭包依赖及二进制资源落盘，显式选择版本更新。`design_references.py` 静态识别声明式引用、原生资源路径和受支持的脚本字面量调用，供素材保护、替换、引用展示及共享库闭包收集复用，不执行项目代码。迁移先复制旧项目，再由隔离来源捕获原生 DOM/CSS；原脚本保留在副本源码，任意动态行为不自动转译。

`design_routes.py` 提供网页接口；React `design-workbench` 按需加载，串行保存并保留待处理指令及源码草稿。页面投影只传输活动页面和递归嵌入依赖，其他页面保留摘要；引用索引按版本缓存，避免丢失未加载页面的素材使用位置。素材列表虚拟化，缩略图在 Worker 中以有界队列生成。项目来源的 `design_assets/studio/runtime` 接收经过来源、父窗口与会话校验的文档，按活动页面渲染，命名空间隔离嵌入内容。拖动只在帧内更新选中节点，结束提交一次操作；同页简单修改增量应用到已有 DOM。顶部编辑/预览切换先通过同源校验的消息提交帧内文字，等待保存队列完成后才用最新文档进入预览；保存失败保留队列并阻止旧内容预览。返回时恢复编辑页与选择，运行时按页面/模式保留相机。编辑状态暂停脚本，预览通过 `mount(ctx)` 提供受跟踪事件、计时器、动画、消息和页面导航，停止时清理并从设计文档重建。导出复用同一渲染器，包含素材与本地脚本依赖。数据契约、运行限制和验收目标见 [Design Studio](DESIGN_STUDIO.md)。

## Markdown 行内标注与评论

`vault_rag/annotations.py` 使用每个知识库内部的 `.vault-rag/annotations.sqlite` 保存不可重建的用户标注。文档持有独立 ID，文本高亮和评论线程保存类型、颜色、状态、修订号；评论消息与主线程分离，支持回复和修订检测。前端 `annotations.ts` 使用 UTF-16 原文偏移、引文和上下文进行混合锚点匹配；`annotation-decorations.ts` 以 ProseMirror/CodeMirror Decoration 绘制，绝不进入 Markdown 原文序列化。找不到唯一可信位置时标注为失效，不静默绑定其它相同文本。

浏览器通过认证与 CSRF 保护的 `/api/annotations` 访问，MCP 通过现有连接权限保护独立的读写工具；评论内容不自动进入 RAG。笔记移动、回收和恢复调用 `Files.annotation_changed` 使浏览器及 MCP 文件操作共享相同的身份迁移。评论数据库随知识库备份，不应与可重建的检索索引一起删除。相关设计、操作及测试见 [Annotations](ANNOTATIONS.md)。

## Markdown 编辑与原文保存

Markdown 默认在 Tiptap/ProseMirror 正文编辑器中打开，CodeMirror 提供源码编辑。`rich-markdown` 将可编辑块与原文片段关联，仅重新序列化发生变化的块，保留未修改原文、文档前缀与后缀；复杂或不支持直接编辑的内容通过保留节点展示并可跳转源码。较大正文的初始解析交给 `rich-markdown.worker`。

`document-state` 管理正文、版本标识、本地草稿和自动保存；`edit-history` 在正文、源码与标注操作之间共享当前会话的撤销记录；标注异步写入预先占位，恢复成功后才移动历史步骤。标注数据库 v3 的 `annotation_history` 保存服务端生成的线程前后快照，使用 `group_id` 将选区高亮清除及分割归为一个原子操作，按文档保留最近 200 组操作；恢复先核对完整线程，保留身份及创建时间并递增修订号，同步更新相邻历史的匹配状态，防止覆盖外部修改。正文映射与 `source-offsets` 处理编辑位置及换行偏移；后端保存继续校验版本并保留 BOM 和原文换行。外部修改与保存冲突保留当前草稿，AI 草稿仍需明确保存。

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

`vault_rag/attachment_index.py` 在应用私有数据目录的 `attachment-workspaces/<workspace-key>/attachments.sqlite` 保存可重建的路径、文件名、大小、修改时间与 MIME 元数据；原文件仍为事实来源，不迁移文件、不改写链接。附件管理器先只读检查状态，首次初始化或已知旧版升级必须点击按钮；后台刷新与文件变更批次用于核对可用索引；扫描不解析笔记或读取附件正文，独立于 RAG。名称索引也服务于文件名解析。

`GET /api/attachments?query=&after=&limit=100` 保留旧的路径升序行为；新增 `root`、`kind`、`sort`、`order`、`cursor`，按排序值与路径稳定分页，并返回全库数量、空间与类型汇总。游标绑定根目录、查询、筛选、排序、扫描版本与本服务的增量变更代次，过期时要求重新加载。`GET /api/attachments/status` 只读返回状态、目录与索引作业；显式 `initialize`、`rebuild`、`index-cancel` 管理后台索引。已知旧版本先备份，未知版本拒绝覆盖。列表只包含 `.md`、`.txt`、`.base` 之外的可浏览文件。

主导航按需加载 `?view=attachments` 独立工作区，默认最近修改的缩略图网格。单页最多 100 项，全选只针对当前页。搜索防抖、AbortController 与响应代次保护阻止过期结果覆盖；根目录以组件 key 隔离旧列表、选择、上传和预览。离开页面暂停媒体并保留浏览条件及滚动位置。侧栏预览复用媒体组件与受保护的 `/api/media?root=`，PDF 内嵌、SVG 按图片显示，HTML 不执行，项目仍运行在独立来源。

`vault_rag/attachment_workspace.py` 提供 `details` 保护提示、缩略图、操作规划与 ZIP 作业。`GET /api/attachments/thumbnail?root=&path=` 只解码受支持的栅格图片，限制 64 MiB 源文件、3200 万像素和两个并发，按根目录、路径与文件版本生成静态 WebP；缓存最多 1024 项。Pillow 为两端共享依赖，缩略图失败回退图标，不批量加载原图。`POST /api/upload` 的可选 `unique=true` 配合根目录确认，在发布锁内选择不覆盖的文件名，旧调用默认行为不变。

`POST /api/attachments/operations` 携带 `root,kind,paths` 及 `destination` 或 `name`，复用迁移管理器的依赖保护、引用规划、漂移校验、执行锁和恢复日志，单批最多 100 项；执行、状态和恢复继续使用任务接口。重命名／移动修复支持的笔记引用；回收列出已发现引用并在确认后创建普通 `.vault-rag/trash/` 记录，不改写笔记。保护资源的提示为短期缓存，执行规划仍重新检查。`POST /api/attachments/downloads` 后台生成最多 100 文件的 ZIP，最多两个并发，状态／取消／文件接口携带根目录；逐文件核对版本与配置代次，访问范围变化后拒绝旧 ZIP；不执行内容，下载一小时后过期，清理时回收对应临时任务记录。缓存与下载存于各知识库的 `.vault-rag/`。

本地 `attachments.sqlite` 仍是可重建的路径索引，同名文件保留多个候选，笔记相对路径优先，不自动选择任意同名文件；远程存储 manifest 另行保存稳定资产身份和用户编辑的元数据。现有 `catalog.sqlite` 仍负责笔记元数据与链接；附件名称索引专门避免冷启动／懒加载目录中的文件名解析反复遍历整库。完整目录索引的名称查找也使用平台规范化键直接查表。

索引事务只在完整扫描成功且关联根目录未变化时提交；读取失败保留上一代，较新数据库版本拒绝打开，原文件不受影响。列表和解析候选均重新检查访问边界。`last_scanned_at` 表示最近一次成功的完整扫描时间，`total` 是缓存索引中的匹配数量，不是文件仍存在或没有引用的证明。重新启动复用索引；关闭期间的变化、监听失效或外部变更尚未同步时，应手动刷新。

本阶段不保存二进制 BLOB：这不会减少图片解码成本，反而会引入文件迁移、备份与流式 Range 读取的兼容成本。缩略图应作为按需生成的派生缓存；重复检测应按需计算内容摘要，并且不能仅凭同名或摘要删除原文件。完整引用分析还需要覆盖 Markdown、HTML/CSS、历史与外部链接，不能把“未发现引用”直接解释为“可删除”。

隔离云端夹具测试（5,000 个附件、50 个目录、20 次缺失文件名查找）中，原重复遍历约 2.689 秒，新索引一次构建约 0.277 秒，20 次热查询约 0.0145 秒，重启后查询约 0.0011 秒。此结果仅衡量文件名解析，不代表真实笔记整体渲染或大图解码加速比例。

## 通用远程附件存储

设置入口为“设置 → 文件与导入 → 附件存储”。`attachment_storage_routes.py` 提供同一工作区认证下的 `/api/attachments/storage` 设置、连接测试和显式扫描、元数据编辑、缓存清理与后台任务接口；`file_operations.py` 让公共 MCP 使用相同的来源和任务，并继续按连接检查读取与修改授权。来源使用 UUID、WebDAV 服务地址、服务器根目录和上传子目录，配置及默认上传目标按关联知识库保存在 应用私有目录的 `attachment-workspaces/<workspace-key>/remote-attachments/settings.json`。打开设置或列出已有资产不会触发 NAS 扫描。显式扫描在后台逐目录提交元数据，不读取附件正文；页面和 MCP 的 `vault_files status.attachment_storage` 返回扫描数量和连接状态，失败保留已发现记录。

`remote_attachments.py` 在该目录的 `manifest.sqlite` 保存稳定 `asset_id`、来源、服务器物理路径、逻辑别名、标签、分类、简介、对象版本、缓存记录与上传／迁移日志。用户元数据不是可随意删除的派生索引。`attachment_catalog.py` 将本地路径索引与 manifest 在 SQLite 内合并、筛选、汇总和分页，只将当前页交给 Python；游标同时绑定来源配置、本地索引和 manifest 代次。验证并释放本地原件后，迁移别名覆盖本地旧索引残留；迁移尚未完成时保留本地入口。远程 Markdown、HTML 和明确源码扩展默认不参与附件发现；它们不会自动加入笔记读取或检索范围。

迁移通过持久身份重定向保留旧本地资产 ID，并退役原路径槽，避免同路径新文件复用旧身份。目录响应缺少 ETag 不作为版本已变化的证据；大小与修改时间不变时保留既有验证标记。未缓存读取先用 HEAD 同步实际版本，再将内容与该版本绑定；大媒体的条件响应和 Range 头也使用同一版本。未知的当前 SHA 不从历史迁移日志推断，只有实际完整读取并计算后才记录。

服务器只保存附件原件。预览、文本处理、缩略图、标签和查询均在本地执行。`remote_webdav.py` 使用显式 Basic 凭据，通过标准 WebDAV 和有界 Range 读取访问对象，不跟随登录重定向、不使用浏览器 cookie 或环境代理。普通外网连接要求 HTTPS；只有用户显式允许时才能使用私有／回环 IP 的 HTTP。`remote_media` 通过已有 LeafLoom 媒体入口返回内容，远程内嵌响应使用 CSP sandbox 和 nosniff。完整文件和部分 Range 缓存共用默认 2 GiB 预算；上传 outbox 使用独立的默认 10 GiB 预算，清缓存不删除待同步原件。离线上传先持久暂存，恢复可用连接及授权后后台补传，远端写入与校验完成前不视为完成。

NAS 迁移使用 `/api/attachments/storage/migrations`：先预览候选文件、依赖排除项与释放空间，明确确认后上传唯一对象，流式读回核验 SHA-256，提交稳定身份与旧路径别名，再复核源文件身份与内容后释放本地原件。恢复日志覆盖提交和释放之间的中断；失败保留原件，不新建永久原件归档，既有历史和回收区由原流程管理。原笔记链接通过 LeafLoom 后端解析。大于 64 MiB 的媒体直接使用有界分段缓存，首次预览无需等待完整下载；远程缩略图另行长期保留。

桌面端的 `desktop/attachment-secrets.cjs` 只在主进程使用系统 `safeStorage` 加密保存密码及凭据代次，原子写入私有文件，拒绝明文后备。可信主 frame 只能保存／清除凭据、读取脱敏恢复状态或请求重试，不能读取密码；后端就绪后，主进程经私有 bearer 接口恢复到后端内存。密钥库暂不可用或本地同步失败时按 1、3、10、30 秒有限重试，解锁／唤醒或设置页手动重试可开启新一轮恢复；损坏文件不会被空映射覆盖。恢复请求携带单调序号，后端持锁拒绝迟到的旧快照；桌面启动代次在停止旧服务前失效，防止旧回调重新绑定已退役的服务。浏览器版密码仅保留在当前后端会话内。NAS 密码不返回 MCP、网页设置或错误详情。

附件连接恢复状态按知识库、服务器配置及凭据代次隔离，并持久保存在附件 manifest。后台只对已启用且已有凭据的配置地址做健康检查，不扫描端口或自动导入正文。网络中断及 HTTP 502／503／504 按 2 至 60 秒退避，健康连接约每 60 秒检查一次；服务器拒绝认证后暂停同一凭据的自动尝试，测试连接或明确恢复任务可以重新验证。更换账号或权限后，旧任务仍须通过原有 owner／revision 检查，不能自动改绑。设置界面与 MCP 的连接状态返回尝试次数、下次检查时间及暂停标志，以及任务、缓存和队列概况，不返回密码或恢复凭据代次。

`attachment_metadata_hooks.py` 保留既有标注回调，为显式本地文件／目录移动、重命名及撤销同步 local 资产路径和别名，保留原身份、标签、分类与简介；目标有另一份元数据时拒绝覆盖。附件组织迁移在动文件前将原资产身份写入恢复日志，完成和回滚都按该身份幂等同步，旧日志不凭目标路径推断元数据所有权。此机制不推断外部文件管理器的任意移动。

极空间等官方客户端的本地转接作为普通 `base_url` 使用，`official-client` 仅提供连接提示，不自动登录 NAS、不读取官方客户端凭据或控制其内部 SDK。客户端转接窗口需要保持打开；官方客户端重启后，用户须手动重新打开附件入口，端口变化时更新服务地址。通用 WebDAV 配置也可连接其他服务器。具体设置与操作见[英文](en/GUIDE.md#attachment-manager)、[中文](zh-CN/GUIDE.md#附件管理)和[日文](ja/GUIDE.md#添付ファイルの管理)指南。

## 可恢复的附件迁移

附件列表仍只查询可重建元数据，迁移通过独立的异步作业执行。`POST /api/attachments/migrations` 携带 `root` 与相对路径 `destination` 创建只读预览；`GET /api/attachments/migrations` 列出保存的任务，`GET /api/attachments/migrations/{id}` 读取状态、可选的展示阶段、进度、摘要、已发现引用、逐文件结果、路径变更、排除项和阻止项；未知总量显示活动进度。路径列表可以只返回前 200 项，文件总数以摘要为准。默认目标为 `_attachments`；成功迁移后的编辑器上传使用配置中的 `attachment_folder`。

只有就绪且没有阻止项的计划才可通过 `POST .../{id}/execute` 并携带 `{root, confirm:true}` 执行。`cancel` 请求在安全边界停止；`resume` 和 `rollback` 均需明确确认。前端关闭、切换根目录或卸载只取消客户端等待与轮询，重开后从服务端读取持久化任务。服务重启后必须从日志重新验证，而不是假定此前全部成功。

每个任务的恢复目录为 `.vault-rag/attachment-migrations/{id}/`，包括 `manifest.json`、原附件 `originals/`、笔记备份 `notes/`。应用前校验文件漂移、目标冲突、访问边界和可用空间；恢复时遇到后续编辑应报告冲突，不得覆盖用户新内容。该流程不永久删除恢复材料，也不按同名或相同摘要自动去重。

静态引用规划独立于附件列表扫描，本阶段仅改写支持的 Markdown／Wiki 引用。按用户范围，HTML 文件、项目拥有的资源和 HTML 共享资源保持原位，列为明确排除项，不改写 HTML/CSS。HTML／源码项目、独立脚本和原生工程资源按目录保留，文件字面量引用和目录前缀递归扩大共享资源保留范围；配置文件作为只读依赖源，不作为待改写笔记。保留范围内的动态代码不再单独形成全库阻止项。依赖源无法安全读取、笔记中无法解释或存在歧义的引用仍阻止迁移，不能承诺“没有发现引用”等同于“无引用”。原生二进制文件不作文本解析：其大小、mtime_ns 与 inode 纳入只读漂移快照；文本源仍用流式摘要校验，执行／回滚同时校验完整非附件路径清单，兼容旧日志的纯摘要快照。外部引用与工具不可审计，因此执行前需用户核对风险。操作说明与恢复步骤见三语使用指南的附件管理章节。

服务器目录刷新使用独立的 `scan_id`／`scan_state` 生命周期，不能以健康检查的 ready 代替完成。WebDAV 207 须验证每个响应及目录自身必需属性；成功扫描后，对开始快照中未见的 ready 条目追加 HEAD，只有明确 404／410 且整批确认、来源／凭据／知识库未变，才事务标记 missing。并发上传、迁移保留键及资产修改代次保护未完成或变化的对象。missing 不删除身份、标签、别名或迁移回执，只清可重建正文与 Range 缓存；列表和容量隐藏它，旧引用读取明确返回缺失。content_generation 在标记缺失时递增，防止同路径恢复且 ETag／大小／时间相同时旧缓存或旧缩略图重新生效。扫描失败、取消、权限变化或不完整结果都不清除未见条目。

`remote_ignore.py` 使用有界 UTF-8 `leafloom.ignore` 和固定首行 `# leafloom-ignore v1` 维护默认与逐层目录规则，复用 pathspec 的匹配语法。目录始终遍历以发现子级覆盖；控制文件本身永不成为附件。规则每文件最多 64 KiB／2048 行、每行 2048 字符，整扫描最多 1 MiB；只通过既有 WebDAV 只读 GET 取得，不放宽隐藏路径访问。全部规则读取和最终哈希复核成功后，才提交 excluded 状态及恢复变更。excluded 隐藏发现／统计，但保留 ID、标签、别名、缓存和旧引用读取；未见的旧路径也先匹配有效规则，被排除时不执行缺失确认或清理。MCP 扫描状态另返回 scan_excluded，确认删除阶段可返回 phase／pending_missing。

桌面附件凭据恢复在可信后台 target 建立后异步运行，不阻塞工作区导航；Electron 44 的异步系统加密接口优先，无异步接口的平台维持兼容且从不回退明文。恢复按 target 单飞合并，系统调用返回后再次核对连接代次，过期 target 的结果不会发送给旧后台；恢复不重写现有密文文件。

## Unity 资源商品目录与独立下载

`asset_library.py` 在已配置的 WebDAV/NAS 元数据目录维护商品目录，默认 `Incoming/LeafLoomCatalog/v1`。原资源包和附件 alias 保持不变；同一官方产品 ID 可关联多份包版本／副本，未关联包作为独立 candidate。NAS 保存带父修订的不可变 JSON 事件和封面，本地 `asset-library/library.sqlite` 保存可重建查询投影、离线待同步事件与操作回执。官方信息与个人标签／分类／笔记分区；文件级个人信息不隐式提升为产品信息。并发分支保留为冲突，不采用后写覆盖。已有绑定禁止静默换服务器或元数据目录。

`asset_library_routes.py` 复用管理会话与 CSRF，提供商品列表、详情、封面、设置和显式动作。React `asset-library.tsx` 与原附件文件页共存，显示 candidate／product、真实 review 和 sync 状态；文件名版本标明推断来源，未知不补造。官方链接、实际采集成功、人工匹配确认及账号购买权属分别处理。批量官方资料采集必须显式触发，返回真实取得／待核对／失败进度；资料不可得时保留空描述与封面图标，不生成替代图片，中文摘要待整理时保持明确状态。人工 URL 提案不因标题或发布者不一致而自动绑定；确认用 candidate 当前修订绑定文件，再按返回的商品修订确认 review。

`asset_downloads.py` 将大型包流式下载到独立私有暂存，默认 20 GiB，与预览缓存和上传 outbox 分开。任务绑定知识库、来源版本、连接 owner 和权限代次，文件校验完成后才进入 ready 并发放有期限的 opaque handle。读取端点仅接受受控 handle，不接受任意磁盘路径；HTTP 响应持有读取租约，完成或断线时释放，防止传输期间的淘汰／主动释放导致容量漏计；界面与 MCP 不获得内部缓存路径或 NAS 凭据。暂停、失败、重试及手动释放保持独立状态，释放不删除 NAS 原包。下载准备和浏览器下载都不等同于导入 Unity，也不修改任何 Unity 工程。

现有两个公共文件 MCP 工具扩展 products／product／prepare_download／download_status 读取和 product_update 写入，沿用 workspace_revision、读写授权、操作回执和乐观修订检查；不扩张账号所有权或工程修改权限。


## 通用附件分组与下载页面

`AttachmentGroups` 在知识库 `.vault-rag/attachment-groups/` 保存追加事件及设备身份；成员与分类独立。分组规则在统一附件查询的同一 SQL 快照中应用，因此分页、来源与容量统计不下载原件。`AttachmentPresentation` 将已有来源资料投影至文件，个人非空字段优先，编辑器仅提交个人字段。原商品实体和接口继续兼容，前端不再固定提供商品入口。

服务器副本位于所选资料目录的 `attachment-groups/events/`，不混入商品事件流；独立 `attachment-groups/library.json` 校验远端资料身份，记录绑定后拒绝静默改投其他目录。事件有 SHA-256、父修订及不可变写入，服务器读回确认后才标记同步。分叉保留双方，显式解决需基于当前 revision；本地成员带设备作用域，主服务器成员按共享资料作用域和服务器相对位置标识。受控迁移的身份重定向保留原成员关系；外部改名不按同名猜测关联。

`/?view=downloads` 独立展示服务器流式暂存和现有本地 ZIP 任务；`/api/attachment-downloads` 是兼容既有任务模型的浏览器汇总，`/api/attachment-downloads/settings` 管理下载容量。现有下载记录、句柄、校验、容量、租约及 MCP 访问者边界不迁移或重置；ZIP 保留一小时有效期及中断后重建行为。下载暂存就绪不代表文件已保存至用户选择的目录。


## AI 素材检索与稳定交付

`asset_search.py` 从当前附件与商品目录构建独立元数据投影，按已关联身份合并商品的版本／副本；本地记录按完整相对路径标识，远程记录按附件 ID 标识，不按同名推断。关键词复用现有分词，精确名称优先；语义索引由 `rag_worker` 的 `asset_build`／`asset_dense` 操作通过 `asset_vectors.py` 构建／查询，复用唯一 BGE-M3。小批量元数据向量按文本／模型指纹复用，manifest 原子发布；检索再次限定当前可见身份与文本指纹，3 秒超时明确降级。关闭语义索引不影响关键词，不改变笔记 RAG 范围。预览沿用受控缩略图与真实封面，MCP 只将经授权的 `_image` 内部结果转换为原生 ImageContent，不进入 JSON 文本。

`asset_deliveries.py` 使用独立持久化任务，将选定原文件复制到可信管理设置中的固定交付目录。MCP 仅接受资产路径与修订，不能指定目标目录。远程复用暂存及读取租约，本地受控复制；先写临时文件并校验 SHA-256，再独占发布。交付状态绑定工作区、owner、权限代次及设置修订，重启后由原连接轮询触发重新校验恢复。完成后仅输出持久副本的完整路径及服务设备身份，不泄露暂存内部位置；交付副本不受缓存淘汰，也不自动导入工程。`asset_workflow_routes.py` 复用管理会话／CSRF，提供目录与语义开关；下载页展示设置、索引和交付状态。详见 [素材工作流](ASSET_WORKFLOWS.md)。


### 按附件分组选择素材检索范围

分组查询增加 `search_enabled`、`search_scope_revision`、`search_scope_conflicts`，默认关闭。范围布尔值通过同一 SQLite 内独立 `scope_events` 记录，与分组修改同事务提交；旧请求省略开关保留原值。NAS 事件单独存放于 `attachment-groups/search-scope/events/`，复用原资料库身份、父修订、不可变校验及读回确认，不改变原 `events/` 格式，避免旧客户端覆盖新开关。范围或成员分叉未解决时该分组不参与检索。

素材检索先读取有效组，再逐组取得成员并集，不为范围判断枚举全库；无启用组时直接返回 `scope_not_configured`，不启动模型。商品关联文件及嵌套详情只保留范围内副本。组事件更新／同步通知素材索引刷新；范围修订贯穿检索和构建，发布前再次核对范围及当前文档指纹，范围变化废弃旧投影。升级时移除旧全库派生清单，保留原件和不参与召回的历史向量缓存。此范围不改变普通附件读写授权、笔记引用或下载权限。


### 服务器附件模式与跨设备状态

`attachment_state.py` 将附件数据库、服务器配置、缓存、上传队列、商品投影和分组状态路由到 `LocalConfig.directory/attachment-workspaces/<sha256(path_key(root))>/`，不受知识库目录同步覆盖。首次访问使用 SQLite Backup API 和普通文件版本检查取得旧 `.vault-rag` 状态快照，完整目录原子发布；不删除旧状态、恢复材料或原件。缓存字节不复制，缓存表同步清空。临时 `remote-attachments/release/` 仍在知识库侧，保证原件声明使用同文件系统 rename。更换本地目录需重新关联服务器，不能借用其他目录的传输授权。

默认附件源只决定后续上传目标，服务器配置存在时即可浏览已有服务器目录，不要求本机目录初始化。附件列表合并已准备的本地索引与服务器 manifest；本地索引未就绪或版本不兼容时以临时内存空 schema 查询服务器，保留原数据库，并由 `local_index` 单独报告本地状态。初始化／重建接口始终只建本机目录，服务器刷新使用独立接口。切换默认目标不隐藏任一来源，也不迁移或复制原件。

`attachment_server_references.py` 在配置的元数据目录 `attachments/v1/<sha256>.json` 保存不含密码或本地绝对路径的不可变引用，包含服务器相对物理路径、逻辑别名与公开资产 ID。写入经独立读回校验；失败保留上传队列和迁移原件。显式服务器扫描下载受限的引用元数据并在单事务中恢复 aliases/reference_ids，支持不同本地目录和附件配置 ID。相同别名／身份指向不同对象或不同源时报告冲突，完整路径失效不降级为同名远程文件。旧版已迁移的引用由 `/api/attachments/storage/references` 显式回填。商品事件、分组事件仍按各自协议同步；这些本机数据库包含未同步用户数据，不能当作纯缓存随意删除。离线读取仍以已有完整／分段缓存为限。

旧引用回填最多使用四个独立 HTTP 会话并行写入，小批次复用已核实目录；所有不可变记录仍读回校验。`reference_records` 只复用摘要校验正确、位于当前服务目录列表中的引用记录，后续扫描无需重复 GET 同一记录；限制单记录 128 KiB、每次总量 16 MiB、最多一万个引用记录。跨操作系统或本地绝对目录变化时，仅导入公开服务器配置，不接管其他根目录的未完成队列或恢复任务；仍需本机密码授权与服务器扫描。


### 附件来源切换与同步延迟

已有文件的读取优先级独立于默认上传目标：准确存在的本地路径、准确的服务器别名／逻辑路径，再进行无歧义的文件名匹配。本地与服务器同名但不同对象时，文件名匹配不任选其一。列表对仍存在的本地原件保留本地条目，服务器副本使用不冲突的逻辑路径；已删除的本地索引残留不作为原件展示。实际本地存在状态纳入分页游标作用域，外部同步先改变文件、监听尚未更新索引时也会使旧游标失效。

服务器引用导入遇到仍存在的同路径本地身份时，建立不激活的 `asset_redirects`，不删除或重命名原件。同步删除到达前按本地身份读取，删除后同一旧身份跟随服务器对象。已排队上传保留 source_id，切换默认目标只影响以后创建的上传。HTTP 服务器上传临时文件也放在本机应用数据目录，避免进入知识库同步。

目录同步不能给多电脑的整理／重命名／迁移提供事务隔离，界面确认和三语指南要求一次只在一台电脑操作，期间暂停外部编辑与文件同步。纯本地原文件的同步也不等于本机标签、分组、未同步元数据和队列的同步；后者必须保留，不能以“缓存”为由删除。服务器原件在切回本地后仍需服务器或已有缓存，未实现自动反向迁移。

Desktop Design presenter mode has one audience BrowserWindow with a minimal
audience-only preload, plus the existing management window as the console.
A complete saved document is frozen at start, while notes keep using the normal
versioned save queue. The console receives bounded captures of that window only
and forwards allowlisted, normalized Chromium Input events through a debugger
attached exclusively to its WebContents. Project code never receives desktop
permissions. Display loss or missed heartbeats mute, pause and hide output.
