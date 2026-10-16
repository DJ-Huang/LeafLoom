# 本地知识库架构

[架构与工作流程图](assets/workflow.svg)

## 进程和接口

一个 Python ASGI 进程提供本地网页、文件 API 与 HTTP MCP；BGE-M3 和向量任务在独立的 `rag_process` 中运行。网页由预构建静态文件提供，Node 只用于安装/构建；模型由检索工作进程延迟加载。正常客户端不通过 stdio 再启动服务或加载模型。

源码桌面开发通过 `Dev.cmd`（Windows）、`Dev.command` / `sh Dev.sh`（Mac）或 `node scripts/dev-desktop.cjs` 启动：独立开发状态与 Python 环境位于 `.cache/desktop-dev/`，后端默认端口 18081，Vite 使用 5173。仅未打包桌面端显式传入开发地址时，`dev_frontend.py` 才从 Vite 获取入口和模块，保留原有工作区域名、API 认证与 HTML 项目隔离；前端通过本机 WebSocket 自动更新。生产桌面端移除该开发变量，普通服务不隐式读取它。详见[桌面开发](DESKTOP.md#source-development)。

生产 MCP 注册位于 `mcp_tools.py`，完整笔记工作流位于 `note_operations.py`，与网页共用 `Files` 的保存、历史、回收区和移动事务；网页模板与日记也复用该工作流。`mcp_access.py` 在私有配置保存本机凭据哈希与独立权限，Tunnel 凭据只驻留后端内存并通过环境引用注入运行时的发现及调用请求。旧五项只读工具与 `/ai-mcp` 保持原有范围；完整访问须显式启用，两个连接的写入分别授权。工具、分页、版本与错误契约见 [MCP](MCP.md)。

- 网页入口：`http://127.0.0.1:18080/`；浏览器迁移到 `http://app.<installation-id>.localhost:18080/`，端口跟随配置。
- HTTP MCP：`http://127.0.0.1:18080/mcp`
- 健康检查：`/healthz`；启动入口随后使用本机令牌验证 `/api/status`，避免复用另一安装实例。
- 文件写入采用版本校验、草稿保留、原子替换；历史、移动回滚和回收区位于知识目录的 `.vault-rag`。

## 平台边界

`platform_support` 处理配置目录、权限、Windows 文件名、链接/junction、目录选择和错误弹窗。私有状态默认位于 macOS Application Support/VaultRag 或 Windows LocalAppData/VaultRag，支持 `VAULT_RAG_HOME` 覆盖。文本明确使用 UTF-8；知识库内容保存保留 BOM 和换行形式。

安装版由 Electron 管理窗口、托盘／菜单栏、登录启动和私有 Python sidecar，退出时正常停止自己拥有的后端及检索工作进程。开发模式通过 Dev 启动 Vite 与源码 Electron，使用独立状态，不接管安装版。

Windows `windows_native` 使用当前用户与配置目录区分本地实例，正常退出不按进程名称强制结束其他 Python 程序。`service_control`、旧计划任务／LaunchAgent 和脚本托盘实现仅作为历史安装迁移与内部兼容代码保留；根目录旧服务启动入口已移除。

## 安装与依赖

安装版通过 Release 安装包分发，由应用自身管理启动、退出和更新。构建过程按 `uv.lock` 准备私有 Python 依赖并构建前端；流程见[桌面构建](DESKTOP.md)。源码开发通过 Dev 同步独立 Python 环境，直接运行 Vite，不构建安装包或注册旧服务任务。

Windows 使用官方 CPU PyTorch 软件源及锁定的 `msvc-runtime` wheel；包入口注册 DLL 搜索目录。Windows 与 macOS 共用跨平台 `uv.lock`，Dev 使用独立 uv 缓存与环境。检索模型按需准备；安装包资源的版本与校验信息仍由构建清单管理。

## 知识范围和索引

网页浏览完整关联目录，检索仅使用用户选择的目录。隐藏目录、应用目录、符号链接和 junction 不进入浏览或检索；规则、导航和工时保持各自领域隔离，退出文件立即过滤。

目录同步线程使用 watchfiles，事件最多合并 500 ms；启动和每 60 秒核对，监听失败时每十秒核对。所有可访问文件维护路径、名称、类型和目录表，只有 Markdown/TXT/Base 读取正文或元数据。SQLite 局部 upsert/delete，名称、ID 和引用解析维护内存索引；目录更名更新子树，超过一千项的批次转为后台核对。应用生成目录过滤，`.ragignore` 单独处理。

向量线程与目录线程独立，快速捕获配置与不可变目录快照后释放读取锁，再进行分块和推理。按模型/输入指纹复用 embedding 缓存，构建独立 generation，验证范围版本后原子发布。失败保留旧快照，保留最近两代索引；关键词和 Wiki 通道在向量尚未就绪时明确降级。模型仅一个实例，CPU 推理线程限制为两条。

BGE-M3 使用本地已准备的权重；macOS 优先 MPS 并可回退 CPU，Windows 默认 CPU。官方模型修订、pooling、归一化和维度写入指纹。普通推理不联网下载模型，不依赖 Ollama。

## 页面加载与缓存

`GET /api/session` 返回配置、CSRF、服务实例、目录版本与主界面地址；兼容保留 `/api/bootstrap`。`GET /api/events` 复用网页会话，通过有界异步队列发布文件、配置和状态变化；断线重连或版本缺口发送 reset。SSE 等待不占用文件读取线程池。模型状态接口读取内存，准备/加载/预热更新状态，磁盘校验每 30 秒后台执行；安装和加载仍执行完整校验。

前端入口不包含编辑器、图谱、Mermaid、KaTeX 或 Base。请求按服务实例、根目录、配置版本和路径隔离，合并同一读取，最后消费者离开时取消；仅读取允许重试。正文 LRU 上限 64 条或 32 MiB，不写入浏览器持久缓存。草稿和阅读状态另行保存，最多驻留三个文档，HTML/PDF 仅当前标签驻留。Markdown 正文初始解析在文本估算大小超过 256 KiB 时使用 Worker；源码编辑器与其他预览内容按各自模块加载。超过两百项的目录、列表、表格和任务视图使用 TanStack Virtual。

哈希命名的静态资源 immutable 一年，入口与会话 no-store。知识素材 private/no-cache，校验根目录与权限后处理 ETag/304、视频 Range；媒体 ETag 包含根目录与配置版本。HTML 快照正文 no-store，配套资源可条件校验，失效地址即使携带旧 ETag 也不能得到 304。

## Markdown 编辑与原文保存

Markdown 默认在 Tiptap/ProseMirror 正文编辑器中打开，CodeMirror 提供源码编辑。`rich-markdown` 将可编辑块与原文片段关联，仅重新序列化发生变化的块，保留未修改原文、文档前缀与后缀；复杂或不支持直接编辑的内容通过保留节点展示并可跳转源码。较大正文的初始解析交给 `rich-markdown.worker`。

`document-state` 管理正文、版本标识、本地草稿和自动保存；`edit-history` 在正文与源码之间共享撤销记录。正文映射与 `source-offsets` 处理编辑位置及换行偏移；后端保存继续校验版本并保留 BOM 和原文换行。外部修改与保存冲突保留当前草稿，AI 草稿仍需明确保存。

附件上传使用现有文件接口，显式携带所属根目录，在笔记旁创建 `attachments` 并生成唯一文件名。上传后的文件与插入链接分别管理，撤销链接或取消后续插入不会删除已上传的文件。操作说明见[使用指南](zh-CN/GUIDE.md#用命令快速编辑)，回归入口见[贡献说明](../CONTRIBUTING.md)。

## 本机安全

仅监听回环地址。Host/Origin 校验、网页会话、写入 CSRF 和 MCP bearer token 分别实施。本机令牌放在私有配置目录，不输出到共享 MCP 示例。macOS 使用 POSIX 权限；Windows 状态目录取消继承并授予当前用户和 SYSTEM 权限，子文件继承此保护，不改用户知识目录 ACL。

HTML 按项目作为独立来源的网站运行；桌面窗口和浏览器共用同一份前端与容器。主界面与项目使用同站不同源的 `.localhost` 地址，原回环网页入口迁移本地草稿后打开主界面，MCP 地址保持不变。原始网页字节不注入脚本，草稿使用临时来源；资源请求在进入管理路由前分流。项目设置、会话与迁移详见 [HTML 网页运行](HTML_PROJECTS.md)。Windows 路径还拒绝备用数据流、设备名、尾随点/空格和无效字符；目录范围与链接解析按 Windows 大小写行为比较，外部路径不能借 junction 越界。

安装和实际 Windows 验收步骤见 [SETUP.md](SETUP.md)。
