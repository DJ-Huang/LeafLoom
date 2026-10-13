# macOS 菜单栏与启动

支持 macOS 14+ Apple 芯片。在仓库目录的终端运行 `sh Start.sh` 自动准备运行环境、网页、依赖、模型及服务；主动安装或修复运行 `sh Install.sh`，停止运行 `sh Stop.sh`。无需预装 Homebrew、Python、Node、Swift 或 Xcode。仓库不再分发 `.app` 启动包。

`menu.js` 使用系统 JavaScript for Automation 的 AppKit 桥接提供菜单栏，`start_menu.sh` 按私有状态目录保证只有一个菜单栏实例。菜单每五秒查询服务状态，不加载 embedding 模型；提供打开网页、刷新、启动、停止、重启、日志文件夹及退出菜单栏。退出菜单栏不会停止服务。

`install_menu.py` 创建当前用户登录项 `~/Library/LaunchAgents/com.djhuang.vault-rag.menubar.plist`，直接运行仓库内脚本，固定保存仓库路径和 `VAULT_RAG_HOME`。它独立于服务的 LaunchAgent，保留已有登录启动设置且不设置 KeepAlive，所以退出菜单栏后不会自动重新打开。移动仓库后，在新目录运行 `sh Install.sh` 更新路径。

旧版本已安装到 `~/Applications` 的 `.app` 不再由此流程使用；无需删除用户机器上的文件即可更新登录项。安装器通过正常退出信号停止旧菜单栏，再安装并启动脚本菜单。

Windows 上的脚本与配置检查不能替代 macOS 菜单显示、服务控制和实际登录验收。这些行为需在目标 Mac 上验证。
