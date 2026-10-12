# 本地知识库架构

## 进程和接口

一个 Python ASGI 进程同时提供本地网页、文件 API、HTTP MCP 和 BGE-M3 推理。网页由预构建静态文件提供，Node 只用于安装/构建；模型在服务中延迟加载，共用一个模型对象。正常客户端不通过 stdio 再启动服务或加载模型。

- 网页：`http://127.0.0.1:18080/`
- HTTP MCP：`http://127.0.0.1:18080/mcp`
- 健康检查：`/healthz`；启动入口随后使用本机令牌验证 `/api/status`，避免复用另一安装实例。
- 文件写入采用版本校验、草稿保留、原子替换；历史、移动回滚和回收区位于知识目录的 `.vault-rag`。

## 平台边界

`platform_support` 处理配置目录、权限、Windows 文件名、链接/junction、目录选择和错误弹窗。私有状态默认位于 macOS Application Support/VaultRag 或 Windows LocalAppData/VaultRag，支持 `VAULT_RAG_HOME` 覆盖。文本明确使用 UTF-8；知识库内容保存保留 BOM 和换行形式。

`service_control` 保留统一的 install/start/stop/restart/status/open/uninstall 接口。macOS 使用现有 LaunchAgent 与 AppKit 菜单栏；Windows 使用当前用户、交互式登录、普通权限的计划任务，分别托管服务和 pystray 托盘。任务绑定安装时的解释器、仓库及私有状态路径。登录启动开关只修改登录触发器，不影响手动启动能力。

Windows `windows_native` 以用户 SID 和配置目录生成命名对象身份，在当前登录会话中用独立互斥量保证服务、托盘各一个实例，用事件请求正常退出。服务退出等待同步线程完成当前安全事务/批次；停止超时报告失败，不按名称或陈旧 PID 终止进程。服务任务关闭硬终止和运行时间限制，显式停止以正常退出码结束；仅服务异常退出使用有限次数重试。

`windows_entry` 为隐藏窗口启动准备 UTF-8 输出和日志。托盘独立查询状态，每五秒刷新，不导入或加载模型权重；耗时操作在后台线程执行，退出图标不停止服务。它与双击入口调用相同的服务控制层。

## 安装与依赖

Windows `.cmd` 入口调用 PowerShell 引导脚本。安装脚本保护私有状态目录、验证固定运行环境下载的 SHA256、准备私有 Python/Node、使用跨平台 `uv.lock` 安装项目、构建网页、下载固定修订的 BGE-M3，再安装任务。所有步骤成功后才写安装完成标记；启动入口核对仓库路径、解释器及锁文件指纹。

Windows 默认使用官方 CPU PyTorch 软件源；通过锁定的 `msvc-runtime` wheel 将 Visual C++ DLL 安装在项目虚拟环境中，包入口注册 DLL 搜索目录，安装脚本执行原生导入与小规模 CPU 张量检查，避免仅凭安装完成就误判可运行；LanceDB、模型和托盘库使用对应 Windows wheel。现有 `requirements.lock` 是历史 macOS 安装快照，保留用于该环境记录，Windows 安装依据为 `uv.lock`。自动下载的 Python 是 uv 管理的 python-build-standalone 分发，Node 和 uv 归档的固定版本/校验值在运行环境清单中。安装不修改系统 PATH、注册全局 Python或持久执行策略。

## 知识范围和索引

网页浏览完整关联目录，检索仅使用用户选择的目录。隐藏目录、应用目录、符号链接和 junction 不进入浏览或检索；规则、导航和工时保持各自领域隔离，退出文件立即过滤。

同步线程扫描资料、分块、按模型/输入指纹复用 embedding 缓存，构建独立 generation，验证范围版本后原子发布。失败保留旧快照，保留最近两代索引。SQLite 缓存以事务写入，LanceDB 提供向量索引；关键词和 Wiki 通道在向量尚未就绪时明确降级。

BGE-M3 使用本地已准备的权重；macOS 优先 MPS 并可回退 CPU，Windows 默认 CPU。官方模型修订、pooling、归一化和维度写入指纹。普通推理不联网下载模型，不依赖 Ollama。

## 本机安全

仅监听回环地址。Host/Origin 校验、网页会话、写入 CSRF 和 MCP bearer token 分别实施。本机令牌放在私有配置目录，不输出到共享 MCP 示例。macOS 使用 POSIX 权限；Windows 状态目录取消继承并授予当前用户和 SYSTEM 权限，子文件继承此保护，不改用户知识目录 ACL。

HTML 网页预览使用隔离的只读快照接口和 CSP，保留既有安全边界。Windows 路径还拒绝备用数据流、设备名、尾随点/空格和无效字符；目录范围与链接解析按 Windows 大小写行为比较，外部路径不能借 junction 越界。

安装和实际 Windows 验收步骤见 [SETUP.md](SETUP.md)。
