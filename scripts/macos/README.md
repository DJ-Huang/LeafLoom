# macOS 菜单栏应用

支持 macOS 14+ Apple 芯片。双击仓库的 `.command` 或 `.app` 自动准备运行环境、网页、依赖、模型及服务，不需要预装 Homebrew、Python、Node 或 Xcode。

`MenuBar.swift` 是原生 AppKit 菜单栏程序。仓库根目录的 `本地知识库.app` 与 `~/Applications/本地知识库.app` 使用同一份服务。`.app` 的 shell 入口先检查安装状态，需要安装或修复时在 Terminal 中显示进度，正常启动时直接打开网页。

仓库保留的旧预编译程序最低要求为 macOS 15，且不读取自定义配置目录。`start_menu.sh` 识别维护端构建标记：新程序直接运行；旧制品自动使用系统 JavaScript for Automation 的 AppKit 菜单（`menu.js`），支持 macOS 14 和 `VAULT_RAG_HOME`，用户无需安装额外工具。兼容菜单显示“知”与服务状态。

菜单提供服务状态（每 5 秒刷新）、打开网页、刷新状态、启动、停止、重启、日志文件夹及退出菜单栏。退出菜单栏不会停止服务；“打开网页”会在服务未运行时尝试启动。

维护端构建：运行 `scripts/create_mac_launcher.py`，需要 macOS Command Line Tools（Swift、iconutil）和 Pillow；这是发布包维护步骤，用户端仅复制预编译程序。构建目标固定为 ARM64/macOS 14，结果默认写入仓库根目录；`build(destination=...)` 可指定输出位置。手动 CI 工作流也会生成预编译菜单栏归档。

仓库内应用优先使用相邻仓库路径，安装版使用安装时写入的仓库路径和 `VAULT_RAG_HOME`，没有作者机器路径。移动仓库后重新双击安装入口更新安装版，不需要用户重编译。

登录启动图标：`~/Library/LaunchAgents/com.djhuang.vault-rag.menubar.plist`。它独立于知识库服务的 LaunchAgent；没有 KeepAlive，所以退出菜单栏后不会自动重新打开，下一次登录会再次打开。菜单栏程序只轮询状态，不加载 embedding 模型。

安装及登录项配置由一键安装流程执行，保留已有登录启动设置。兼容菜单通过正常退出信号停止，新版维护程序通过登录项停止；更新时自动重新启动菜单栏。

本次在 Windows 开发，按用户要求未执行原生 Mac 构建、AppKit 兼容菜单、Finder 双击或登录启动验收。已检查脚本语法；原生行为仍待 Mac 实机确认。维护端重建后替换 `Contents/MacOS/menubar` 与相应 Info.plist 标记，自动切换到预编译程序。
