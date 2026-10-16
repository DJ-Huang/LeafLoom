[English](en/GUIDE.md) · [中文](zh-CN/GUIDE.md) · [日本語](ja/GUIDE.md)

# 安装与配置

## 安装版

普通用户从 [最新 Release](https://github.com/DJ-Huang/LeafLoom/releases/latest) 下载桌面应用，无需克隆仓库或预装 Python、Node、Ollama。

- **Windows 10/11 x64：** 运行 `.exe` 安装程序，通过开始菜单或桌面快捷方式启动。
- **macOS 14+ Apple 芯片：** 打开 `.dmg`，将 LeafLoom 拖入「应用程序」后启动。

安装版通过自己的窗口、托盘／菜单栏管理。关闭窗口会保留后台运行，选择 **退出** 才停止应用和本地服务；登录启动在应用设置或托盘中调整。更新时先退出，再安装新版 Release 并重新打开。

首次打开可体验演示库或关联自己的目录，再选择检索范围。阅读、编辑、图谱和关键词检索无需模型；需要语义检索时再从设置准备 BGE-M3。

[桌面安装、运行方式与构建](DESKTOP.md)。

## 源码开发

将仓库放到可写的本机目录，预装 **Node 22+（含 npm）和 uv**：

- **Windows：** 双击根目录 `Dev.cmd`。
- **Mac：** 双击 `Dev.command`，或在仓库目录运行 `sh Dev.sh`。若复制或下载后丢失执行权限，先运行 `chmod +x Dev.command Dev.sh`。
- 两端也可运行 `node scripts/dev-desktop.cjs`。

首次启动按 `uv.lock` 自动准备独立 Python 3.12 环境，安装缺失的前端／桌面依赖，然后启动 Vite 与源码桌面端。后续复用依赖；前端修改自动更新，无需手动构建或打安装包。修改 Python／Electron 主进程或 preload 后，从开发实例的托盘／菜单栏退出，再重新运行 Dev。

开发设置和 Python 环境位于 `.cache/desktop-dev/`；后端默认端口 **18081**，Vite 使用 **5173**。Dev 不使用安装版配置或仓库原来的 `.venv`。首次用示例库或虚构目录验证；关联真实目录仍会修改原始文件。

退出开发实例可选择其托盘／菜单栏 **退出**，或在启动终端按 Ctrl+C；若出现未保存提示，应先在窗口中处理。正常退出会一并关闭自己的后端和 Vite。旧仓库启动、停止和安装入口已移除，不再提供旧源码服务的日常管理流程。

更多依赖更新、端口与访问隔离说明见[源码开发](DESKTOP.md#source-development)。

## 配置与数据位置

| 内容 | Windows 安装版 | macOS 安装版 |
|---|---|---|
| 私有配置、模型和令牌 | `%LOCALAPPDATA%\VaultRag` | `~/Library/Application Support/VaultRag` |
| 日志 | 上述目录的 `logs` | 上述目录的 `logs` |
| 元数据、索引、历史和回收区 | 已关联目录的 `.vault-rag` | 已关联目录的 `.vault-rag` |

源码开发使用自己的 `.cache/desktop-dev/`，其中 `.venv` 为开发依赖环境。笔记始终保存在所关联的用户目录中；安装版更新与开发启动均不应覆盖笔记目录。

`VAULT_RAG_HOME` 是底层私有状态目录兼容接口；Dev 固定使用自己的独立目录。目录和检索范围通过界面设置管理，桌面使用无需 `.env`。已有 `.env` 仅供旧版审计助手使用，不会自动关联知识库。

旧版审计命令通过 `vault_rag.settings.Settings` 读取环境变量或私有 `.env`；这些内部兼容接口不作为桌面启动流程。保留 `vault-rag`、`VAULT_RAG_HOME`、`.vault-rag/` 与 `/mcp` 的兼容性。

HTTP 服务只监听本机回环地址。安装版默认使用端口 18080，Dev 默认使用 18081；修改各自私有 `config.json` 的 `port` 后需退出并重新启动。端口冲突不会结束占用端口的其他应用。关联目录仅支持本机目录，拒绝 UNC 网络共享和符号链接／junction 越界。

## MCP 客户端

优先通过应用的 AI 接入设置管理本机／ChatGPT 的 MCP 凭据和权限；安装版与 Dev 使用各自的状态和端口。完整工具与只读／写入授权见 [MCP](MCP.md)，外部连接见三语 [AI 指南](en/AI.md)。

底层 `scripts/write_mcp_fragment.py` 可生成 `_generated/cursor-mcp-vault-rag.fragment.json`，使用实际配置端口和 `<LOCAL_TOKEN>` 占位符。凭据只保存在私有配置中，不要提交到仓库或共享文档。Codex 使用 `url` 与 `http_headers.Authorization`；Cursor 使用 `url` 与 `headers.Authorization`；Claude Code 使用 `type: http`、`url` 与 `headers.Authorization`。客户端连接共享 HTTP 服务，不各自启动模型进程。

## 平台验证

开发入口与安装版应分别在目标系统验证。Shell 语法、静态检查或 Windows 启动结果不能替代 Mac 实机验证；构建安装包也不等于完成桌面和设备验收。参见[桌面验收](DESKTOP_VALIDATION.md)与[安装验收记录](INSTALL_VALIDATION.md)。
