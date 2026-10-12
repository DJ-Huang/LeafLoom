# 安装与配置

## Windows：首次双击即可安装

支持 Windows 10/11 x64 和内置 Windows PowerShell 5.1。将仓库放到可写的本机目录，允许中文和空格路径。双击根目录的 `本地知识库.cmd`，未安装时会打开安装进度窗口；`安装本地知识库.cmd` 可主动安装或更新。

安装按顺序进行：

1. 保护当前用户的私有配置目录，准备已固定版本与 SHA256 的 uv。
2. 复用 Python 3.12；缺失时由 uv 下载固定的 Python 3.12.13，不注册全局 Python 或修改 PATH。
3. 使用 `uv.lock` 安装项目虚拟环境、CPU 版 PyTorch 和项目内的 Visual C++ 运行库，并实际导入原生依赖检查 DLL；不安装系统级运行库。
4. 复用 Node 22.12+；缺失时下载已固定版本与 SHA256 的 Node 22 便携版，构建网页。
5. 准备并记录 BGE-M3 的模型版本，生成不含真实令牌的 MCP 配置示例。
6. 注册当前用户的服务和托盘登录任务，启动服务和托盘，再记录安装成功并打开网页。

不需要手动安装 Python、Node 或 Ollama。首次模型与依赖下载可能耗时较长；后续启动只使用本地文件。运行时仅启动 Python 服务及轻量托盘，不启动 Node 网页服务器。

依赖或模型下载失败会显示错误和日志位置；重新双击安装入口可复用有效下载。已有非 Windows 或非 Python 3.12 的 `.venv` 不会被删除，会提示先将其改名。若组织策略禁止脚本、联网下载或计划任务，应由管理员调整策略；脚本只对当前进程使用 ExecutionPolicy Bypass，不修改系统策略。

## 日常入口与托盘

- `本地知识库.cmd`：确保服务和托盘启动，等待服务就绪，再打开网页。
- `停止本地知识库.cmd`：正常停止服务，保留托盘和登录启动设置。
- `安装本地知识库.cmd`：安装或更新运行环境、网页和登录任务。

登录时默认启动服务和右下角托盘，不自动弹浏览器。托盘显示服务、模型与索引同步状态；菜单提供打开网页、刷新、启停、重启、日志、取消/恢复登录启动、退出托盘。双击图标打开网页。退出托盘后服务继续运行；重复打开不会增加模型实例。

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
| 自动下载运行环境 | 上述目录的 `runtimes` | 使用已有 Python 环境 |
| 元数据、索引、历史和回收区 | 已关联目录的 `.vault-rag` | 已关联目录的 `.vault-rag` |

`VAULT_RAG_HOME` 可覆盖私有配置目录；任务会固定保存该路径。目录和检索范围通过网页设置管理，正常 HTTP 服务无需 `.env`。已有 `.env` 仅供旧版审计助手使用，不会自动关联知识库。

服务默认监听 `127.0.0.1:18080`，网页在 `/`，MCP 在 `/mcp`。端口冲突会提示错误，不结束占用端口的其他应用。修改私有 `config.json` 的 `port` 后重启，并重新生成 MCP 示例。关联目录仅支持本机盘符目录，不支持 UNC 网络共享；符号链接、junction 越界以及 Windows 非法相对文件名会被拒绝。

## MCP 客户端

运行 `scripts/write_mcp_fragment.py` 可生成 `_generated/cursor-mcp-vault-rag.fragment.json`，使用实际配置端口和 `<LOCAL_TOKEN>` 占位符。将占位符替换为私有目录 `auth-token` 的内容，再合并到自己的 Cursor 全局配置。不要将真实令牌提交到仓库或共享文档。

Codex 使用 `url` 与 `http_headers.Authorization`；Cursor 使用 `url` 与 `headers.Authorization`；Claude Code 使用 `type: http`、`url` 与 `headers.Authorization`。不再使用 stdio 启动每个客户端各自的模型进程。

## macOS

保留现有 LaunchAgent 和原生菜单栏入口：

```sh
.venv/bin/python -m pip install -e .
npm ci --prefix web
npm run build --prefix web
.venv/bin/python -m vault_rag.cli model-prepare
.venv/bin/python -m vault_rag.cli service install
.venv/bin/python -m vault_rag.cli service open
```

菜单栏安装见 [macOS 说明](../scripts/macos/README.md)。

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
- 托盘显示状态，双击打开网页，菜单启停/重启/日志可用；退出托盘保留服务。
- 网页关联目录、中文编辑、模型索引与 HTTP MCP 检索；网页和 MCP 的模型 `load_count` 保持单实例。
- 重复双击不新增服务；端口被其他应用占用、服务未就绪时显示正确错误；断网后正常启动不下载。

当前开发环境为 macOS，Windows 实机验收未完成。PowerShell 语法检查与跨平台自动检查不能替代上述验收。
