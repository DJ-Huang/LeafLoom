# 桌面安装包维护

## 应用结构

Electron 主进程管理窗口、托盘/菜单栏、登录启动和一个独立冻结后台。主窗口加载经过本机令牌与版本校验的回环地址，现有网页会话、CSRF、Host/Origin 和 HTTP MCP 保持有效。目录选择通过只向主窗口暴露的接口完成；HTML 独立预览窗口没有 preload 或桌面权限。

桌面版沿用 LeafLoom 品牌、MIT 许可、三语界面、引导和示例，以及现有 AI 助手。冻结包附带三语目录与示例资源；AI 草稿仍需手动保存，退出不会自动把 AI 建议写进笔记。可选 AI CLI 仍由用户单独安装和登录；App 会补查常见用户安装路径，不执行 shell 启动脚本。

Python 用 PyInstaller onedir 打包。静态网页、技能、Python、Torch、LanceDB 与依赖元数据随包分发，不复制开发机虚拟环境，不在用户机器执行 pip/npm。父子管道发送正常停止请求；管道 EOF 同样触发收尾。仅操作当前 App 启动的子进程，不按 PID 或进程名称强杀。后台异常退出最多自动重试三次。

状态 API 增量提供 `app_version`、`desktop_protocol_version`、`distribution` 和 `desktop_instance_id`。MCP 地址默认仍是 `http://127.0.0.1:18080/mcp`，令牌和已有连接配置保持不变。App 版本与后端版本由构建参数统一传入。

## 原生构建

必须在 Windows x64、macOS ARM64 分别构建；开发维护机器需要 Node 22.23.3 与 uv 0.13.0，用户安装机器不需要。

```sh
uv sync --locked --python 3.12.13 --group desktop-build
npm ci --prefix web
npm ci --prefix desktop
node desktop/node_modules/electron/install.js
uv run --no-sync python scripts/prepare_desktop.py --version 0.2.0-beta.1
npm --prefix desktop run dist -- --publish never
uv run --no-sync python scripts/desktop_checksums.py
```

产物在 `desktop/release/`。构建缓存、后端和许可清单在 `_generated/`，不提交生成物。`prepare_desktop.py` 会同步桌面包和锁文件根版本、构建网页、冻结后台、执行原生依赖检查、收集第三方许可。Python 构建工具与运行依赖统一锁定在 `uv.lock`。

模型修订固定在 `desktop/model.json`。新下载使用该修订；已有完整模型和正在恢复的下载沿用原修订，避免升级无故重建索引。普通推理不联网下载。

## 发布工作流与签名

运行 GitHub Actions 的 **Desktop release**，设置版本、是否验收首次模型下载、是否正式签名、是否准备 release 草稿。默认双平台通过自动验收后准备 GitHub prerelease 草稿，保留人工检查项。工作流不自动公开发布草稿。

默认 Windows 不签名，Mac 临时签名且不公证。正式模式使用 CI Secrets：

- 两端分别配置 `WINDOWS_CSC_LINK` / `MAC_CSC_LINK` 与对应 `*_CSC_KEY_PASSWORD`。
- Mac 额外配置 `MAC_SIGNING_IDENTITY`、`APPLE_API_KEY_CONTENT`（p8 内容）、`APPLE_API_KEY_ID`、`APPLE_API_ISSUER`。
- 证书链接使用 electron-builder 支持的受保护 URL 或 base64 P12；Apple p8 仅在 runner 的临时目录落盘。

签名与公证缺少必需凭据时正式构建失败，不能自动降级为未签名包。release 包含两端安装程序、SHA256、分别打包的第三方许可和平台验收 JSON。

## 迁移、升级和卸载

私有数据继续使用 macOS `~/Library/Application Support/VaultRag` 或 Windows `%LOCALAPPDATA%\VaultRag`；支持 `VAULT_RAG_HOME`。Electron 草稿及界面状态在其 `desktop/` 子目录。知识库内部 `.vault-rag/` 保留。

首次接管旧版先让用户保存浏览器草稿，核对当前用户及配置目录，备份 LaunchAgent/计划任务到私有目录 `backups/desktop-migration-*`，再正常停止旧后台并移除旧注册。失败尝试恢复原注册；不修改知识库、配置、模型或令牌。备份 manifest 记录原注册位置，Mac 可将对应 plist 恢复到原位置再 `launchctl bootstrap`，Windows 可用原任务名和 XML 重新注册。只恢复确认属于自己的备份。

Windows 安装程序替换或卸载前请求 App 保存并收尾，失败则中止。卸载移除登录启动项，保留私有数据。Mac 删除 App 前先在设置关闭登录启动并正常退出，再移到废纸篓；Finder 删除没有应用卸载钩子。不要在 App 运行时覆盖其 bundle。

## 验收边界

```sh
node desktop/acceptance.cjs --installer desktop/release/VaultRag-0.2.0-beta.1-mac-arm64.dmg
# 完整首次下载与冻结模型推理：
node desktop/acceptance.cjs --installer <安装包路径> --with-model
```

验收实际从 DMG 复制安装或执行 NSIS 安装，再从安装目录启动，隐藏全局开发工具，使用独立中文/空格路径与临时端口，检查原生依赖、桌面权限、编辑保存、外部冲突、HTML 预览隔离、MCP 和正常退出。不带 `--with-model` 时使用离线模型失败场景，不将模型下载或推理算作通过。临时目录和失败日志保留以便检查。

原生目录/保存对话框、PDF、真正重新登录、覆盖升级和卸载需要分别记录原生验收；JSON 中 `pending` 不能被当成通过。Windows 与 Mac 不互相代替验收。目前本机执行结果见实际产物旁的 `acceptance-*.json`。
