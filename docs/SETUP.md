[English](en/GUIDE.md) · [中文](zh-CN/GUIDE.md) · [日本語](ja/GUIDE.md)

# 安装与配置

## 推荐：使用 Windows / Mac Release 安装包

普通用户请从 [最新 Release](https://github.com/DJ-Huang/LeafLoom/releases/latest) 下载桌面应用，无需克隆仓库或安装 Python、Node、Ollama。

- **Windows 10/11 x64：** 下载并运行 `.exe` 安装程序，再从开始菜单或桌面快捷方式打开 LeafLoom。
- **macOS 14+ Apple 芯片：** 下载并打开 `.dmg`，将 LeafLoom 拖入「应用程序」后启动。

首次打开可体验演示库或关联自己的目录，再选择检索范围。阅读、编辑、图谱和关键词检索无需模型；需要语义检索时再从设置准备 BGE-M3。更新时先退出应用，再安装新版 Release 安装包。

[桌面安装、运行方式与平台验证](DESKTOP.md)。以下内容面向源码开发和旧版服务维护。

## 从源码启动与安装

支持 Windows 10/11 x64（内置 Windows PowerShell 5.1）和 macOS 14+ Apple 芯片。将仓库放到可写的本机目录，允许中文和空格路径。Windows 双击 `Start.cmd`，macOS 在仓库目录的终端运行 `sh Start.sh` 或双击仓库内 `.app`；首次或需要修复时显示安装进度。Windows 用 `Install.cmd`，macOS 在仓库目录的终端运行 `sh Install.sh`，可主动安装或更新。

安装按顺序进行：

1. 保护当前用户的私有配置目录，准备已固定版本与 SHA256 的 uv。
2. 准备私有 Python 3.12.13 和 Node 22.23.3，固定版本和校验值统一保存在 `scripts/runtimes.json`，不注册全局 Python 或修改系统 PATH。
3. 按前端锁文件安装依赖并构建网页，确认 `index.html` 与静态资源存在。必须先完成这一步，才能安装包含网页的 Python 项目。
4. 正常停止旧服务，复用兼容环境或自动备份不兼容环境；按 `uv.lock` 安装 Python 项目和依赖，检查原生库。Windows 使用 CPU PyTorch 和项目内 Visual C++ DLL，macOS 保留 MPS/CPU 回退。
5. 准备并校验 BGE-M3，记录固定模型修订与文件完整性信息；已有完整模型复用。生成不含真实令牌的 MCP 配置示例。
6. 更新当前用户的服务及托盘/菜单栏，启动服务，验证带身份认证的状态接口和网页资源；全部完成后写安装成功记录并打开网页。

不需要手动安装 Python、Node、Homebrew、Xcode 或 Ollama。首次模型与依赖下载可能耗时较长；后续启动只做一次轻量检查，不在启动器中加载 PyTorch 或模型，只使用本地文件。需要修复时自动进入安装流程，Windows 只显示安装进度窗口。网页缓存只随网页源码和构建配置变化，不因托盘或启动脚本修改而重建。暂时性网络失败最多尝试三次，保留可复用的下载。运行时仅启动 Python 服务及轻量托盘/菜单栏，不启动 Node 网页服务器。

依赖或模型下载失败会显示失败阶段、原始错误摘要和日志位置；再次双击同一入口即可重试。当前平台可运行且依赖完整的 Python 3.12.13 `.venv` 会复用；版本不兼容、来自其他平台或依赖损坏的旧环境会自动改名为 `.venv-backup-时间戳-唯一标识`，完整保留原文件。备份不自动删除，也不覆盖已有备份。若旧环境被其他程序占用导致无法改名，关闭该程序后重试。配置、模型和知识库数据不参与环境备份。模型文件校验失败时，损坏文件单独保留在私有目录的 `models/damaged-唯一标识/`，重新下载同一修订的文件。若组织策略禁止脚本、联网下载或后台服务，应由管理员调整策略；安装器不绕过策略或关闭证书校验。

## 日常入口与托盘

- `Start.cmd`：确保服务和托盘启动，等待服务就绪，再打开网页。
- `Stop.cmd`：正常停止服务，保留托盘和登录启动设置。
- `Install.cmd`：安装或更新运行环境、网页和登录任务。

登录时默认启动服务和右下角托盘，不自动弹浏览器。托盘显示服务、模型与索引同步状态；菜单提供打开网页、刷新、启停、重启、日志、取消/恢复登录启动和退出。双击图标打开网页。“退出”正常停止服务并关闭托盘，不改变下次登录启动的设置。重复点击 Start 会复用同一个服务和托盘，启动中的请求排队处理，不会增加模型实例。

Windows 可将新图标放入“隐藏图标”；在任务栏设置中选择显示。服务与图标各使用一项当前用户计划任务，无需管理员或账户密码。服务任务没有运行时长限制，允许电池运行；异常退出每分钟重试一次，最多三次。主动停止正常退出，不触发失败重试。停止超时会报告错误，不强制结束其他 Python 程序。

手动管理：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m vault_rag.cli service status
.\.venv\Scripts\python.exe -X utf8 -m vault_rag.cli service restart
.\.venv\Scripts\python.exe -X utf8 -m vault_rag.cli service disable-autostart
.\.venv\Scripts\python.exe -X utf8 -m vault_rag.cli service enable-autostart
.\.venv\Scripts\python.exe -X utf8 -m vault_rag.cli service uninstall
```

`uninstall` 停止服务与托盘并删除对应任务，保留模型、配置和知识库文件。移动仓库后，重新运行安装入口更新任务路径。

## 配置与数据位置

| 内容 | Windows | macOS |
|---|---|---|
| 私有配置、模型和令牌 | `%LOCALAPPDATA%\VaultRag` | `~/Library/Application Support/VaultRag` |
| 日志 | 上述目录的 `logs` | 上述目录的 `logs` |
| 自动下载运行环境 | 上述目录的 `runtimes` | 上述目录的 `runtimes` |
| 元数据、索引、历史和回收区 | 已关联目录的 `.vault-rag` | 已关联目录的 `.vault-rag` |

`VAULT_RAG_HOME` 可覆盖私有配置目录；任务会固定保存该路径。目录和检索范围通过网页设置管理，正常 HTTP 服务无需 `.env`。已有 `.env` 仅供旧版审计助手使用，不会自动关联知识库。

旧版审计助手通过 `vault_rag.settings.Settings` 读取环境变量或私有 `.env`。需要兼容命令时，自行指定 `VAULT_ROOT`，并按需设置 `VAULT_CONTENT_FOLDER`（默认 `RAG`）、`VAULT_RULES_FOLDER`（默认 `Rules`）、`INDEX_IN_VAULT`（默认 `true`）和 `VAULT_INDEX_FOLDER`（默认 `.vault-rag`）。通用 `.env.example` 已移除，避免将旧版助手的配置误用于产品服务；私有 `.env` 不应提交。

服务默认监听 `127.0.0.1:18080`，网页在 `/`，MCP 在 `/mcp`。端口冲突会提示错误，不结束占用端口的其他应用。修改私有 `config.json` 的 `port` 后重启，并重新生成 MCP 示例。关联目录仅支持本机盘符目录，不支持 UNC 网络共享；符号链接、junction 越界以及 Windows 非法相对文件名会被拒绝。

## MCP 客户端

运行 `scripts/write_mcp_fragment.py` 可生成 `_generated/cursor-mcp-vault-rag.fragment.json`，使用实际配置端口和 `<LOCAL_TOKEN>` 占位符。将占位符替换为私有目录 `auth-token` 的内容，再合并到自己的 Cursor 全局配置。不要将真实令牌提交到仓库或共享文档。

Codex 使用 `url` 与 `http_headers.Authorization`；Cursor 使用 `url` 与 `headers.Authorization`；Claude Code 使用 `type: http`、`url` 与 `headers.Authorization`。不再使用 stdio 启动每个客户端各自的模型进程。

## macOS

首次在仓库目录的终端运行 `sh Start.sh`；主动修复在仓库目录的终端运行 `sh Install.sh`，停止运行 `sh Stop.sh`。三个 `.sh` 入口均不需要可执行权限。服务使用当前用户 LaunchAgent，菜单栏通过系统 AppKit 脚本运行，不依赖 `.app` 包或管理员权限。正常登录只启动服务和菜单栏，不打开网页；退出菜单栏后服务继续运行。移动仓库后在新目录运行 `sh Install.sh` 更新路径。

`Install.sh` 会先检查现有环境，依赖、网页和模型完整且安装输入未变化时跳过安装。需要更新或修复时按组件处理：网页未变化不重建，Python 依赖未变化且检查通过不重新同步，完整模型不重新准备；缺失依赖在原有兼容环境中补齐，损坏的原生依赖重新安装修复，Python 版本不兼容时保留旧环境备份。跳过安装后仍按原有行为打开网页，传入 `--no-open` 可禁止打开。这里的更新以当前仓库的版本和锁定文件为准，不检查远程最新版本。

Intel Mac 和 macOS 13 及以下不在支持范围。菜单栏和登录项说明见 [macOS 说明](../scripts/macos/README.md)，无需安装 Swift 或 Xcode。

## 定向检查与 Windows 实机验收

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\check.ps1
# 额外执行独立配置下的真实后台任务启停：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\check.ps1 -ServiceSmoke
```

定向检查不下载或加载模型；覆盖 UTF-8/中文路径、CRLF/历史恢复、原子写失败、路径边界、服务状态与控制，以及 Windows 原生互斥量/junction。没有符号链接创建权限时，只跳过需要该权限的场景，junction 仍独立验证。后台任务 smoke 使用临时配置和独立端口，不改已有关联目录，结束后删除自己的任务。

实际 Windows 验收还需逐项记录：

- 无 Python/Node 环境首次安装；中文和空格仓库路径；下载失败后重试。
- 登录后自动启动服务和托盘、不打开网页；取消和恢复登录启动有效。
- 托盘显示状态，双击打开网页，菜单启停/重启/日志可用；“退出”停止服务并关闭托盘。
- 网页关联目录、中文编辑、模型索引与 HTTP MCP 检索；网页和 MCP 的模型 `load_count` 保持单实例。
- 重复双击不新增服务；端口被其他应用占用、服务未就绪时显示正确错误；断网后正常启动不下载。

安装器回归检查：`python -m unittest discover -s tests -p 'test_installer*.py'`。完整安装验收：使用已安装的 Python 运行 `scripts/install_smoke.py`，在独立中文/空格临时目录中复制源码，从无 `.venv`、网页和运行环境缓存开始安装，验证模型推理、网页、HTTP MCP 及服务启停，结束后删除自己的后台任务，保留日志与 `_generated/install-validation.json`。可用 `--reuse-model-from 私有配置目录` 复用模型，报告会明确记录。

GitHub 的 `Desktop installer acceptance` 手动工作流提供 Windows 与 macOS ARM64 检查。CI 使用独立子服务，不创建桌面登录任务，报告中的 `desktop_tasks=false` 不能算作托盘或登录启动验收。实际结果见 [安装验收](INSTALL_VALIDATION.md)。平台验收应在目标系统上记录；Windows 图标、macOS 菜单栏显示和实际重新登录不能用静态检查代替。
