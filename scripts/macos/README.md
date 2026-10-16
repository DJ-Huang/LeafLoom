# macOS 开发与内部兼容脚本

当前支持 macOS 14+ Apple 芯片。安装版从「应用程序」启动，并通过自己的窗口、菜单栏和设置管理。

源码开发预装 Node 22+（含 npm）和 uv 后，在仓库根目录双击 `Dev.command`，或在终端运行 `sh Dev.sh`。前端修改自动更新；退出使用开发实例自己的菜单栏 **退出** 或启动终端的 Ctrl+C。详见[源码开发](../../docs/DESKTOP.md#source-development)。

本目录的 `launch.sh`、`menu.js`、`start_menu.sh` 与 `install_menu.py` 等旧服务实现保留为内部兼容、迁移及历史回归检查代码，不再提供根目录旧启动入口。不要将这些脚本视作当前安装版或 Dev 的日常启动流程。

静态检查不能替代 Mac 实机启动、菜单显示和退出验证。历史结果见[桌面验收](../../docs/DESKTOP_VALIDATION.md)。
