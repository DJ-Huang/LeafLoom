# macOS 菜单栏应用

`MenuBar.swift` 是原生 AppKit 菜单栏程序。仓库根目录的 `本地知识库.app` 与 `/Applications/本地知识库.app` 使用同一份服务。

菜单提供服务状态（每 5 秒刷新）、打开网页、刷新状态、启动、停止、重启、日志文件夹及退出菜单栏。退出菜单栏不会停止服务；“打开网页”会在服务未运行时尝试启动。

构建：在仓库根目录运行 `.venv/bin/python scripts/create_mac_launcher.py`。需要 macOS Command Line Tools（Swift、iconutil）和当前 Python 环境中的 Pillow。构建结果默认写入仓库根目录；通过 `build(destination=...)` 可指定位置。

仓库内应用优先使用相邻仓库路径，安装版使用构建时记录的仓库路径。移动仓库后需要重新构建并更新安装版。

登录启动图标：`~/Library/LaunchAgents/com.djhuang.vault-rag.menubar.plist`。它独立于知识库服务的 LaunchAgent；没有 KeepAlive，所以退出菜单栏后不会自动重新打开，下一次登录会再次打开。菜单栏程序只轮询状态，不加载 embedding 模型。

安装及登录项配置：`.venv/bin/python scripts/macos/install_menu.py`。更新已运行的菜单栏应用时，先从菜单退出图标，再安装并重新打开。
