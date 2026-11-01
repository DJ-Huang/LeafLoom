<p align="center"><img src="../../assets/brand/logo.svg" width="88" alt="LeafLoom logo" /></p>

# LeafLoom · 知织

**让知识留在本地，让 AI 用上你的知识。**

[English](../../README.md) · [中文](../../docs/zh-CN/README.md) · [日本語](../../docs/ja/README.md)

**[访问官网与下载安装包](https://dj-huang.github.io/LeafLoom/zh-CN/)** · 查看产品截图、Windows / Mac 下载和版本说明。

**[帮助中心](https://dj-huang.github.io/LeafLoom/docs/zh-CN/)** · 搜索笔记、附件、设计工作台、AI 接入与恢复指南。

**[0.1.6 更新：笔记数据库、任务看板与统一工作区](RELEASE_NOTES_0.1.6.md)**

让零散笔记、项目文档和收藏网页，成为查得到、连得起、用得上的知识。**LeafLoom 是开源、本地优先的知识库管理工具与个人 Wiki**，支持 Markdown 与 HTML，集成来源可追溯的检索、知识图谱、MCP、Skill、AI Chat 和 ChatGPT 连接。

文件和检索索引保存在自己的电脑上。日常阅读、记录与检索在本地完成；需要 AI 时，再把知识带进对话。

**[下载 Windows 安装包](https://github.com/DJ-Huang/LeafLoom/releases/latest) · [下载 Mac 安装包](https://github.com/DJ-Huang/LeafLoom/releases/latest)**

安装前请先确认[支持的系统与签名状态](#开始使用)。

[开始使用](#开始使用) · [连接 ChatGPT](#在-chatgpt-中使用本地知识库) · [MCP、Skill 与 AI Chat](#ai-connections) · [新手指南](GUIDE.md) · [文档目录](../README.md)

![LeafLoom 欢迎页：选择语言、打开文件夹或体验演示知识库](../../assets/screenshots/zh-CN/01-welcome.png)

## 给你的知识，一个自己的家

| 你需要的 | LeafLoom 带来的 |
| --- | --- |
| **越用越有价值的知识库** | 用双链、反向链接、模板与知识图谱，把笔记、研究资料和项目文档组织成个人 Wiki。 |
| **自己掌控的隐私** | 文件与索引留在本机，检索目录由你选择，无需把知识库托管到云端。 |
| **Markdown + HTML** | 用 Markdown 记录表格、任务和想法；在同一工作区打开带有样式、图片和受支持脚本的本地 HTML 网页。 |
| **可编辑的游戏画面** | 用[设计工作台](../DESIGN_STUDIO.md)管理项目与素材，组合页面与组件，添加脚本和动画，撤销人工或 AI 修改，并导出独立 HTML。 |
| **找得到，也追得回原文** | 结合关键词检索、Wiki 导航与可选的本地 BGE-M3 语义检索，从结果直接回到原始笔记。 |
| **完整的 AI 工作流** | 接入 MCP 客户端，安装内置 `wiki-search` Skill，或在笔记旁打开 AI Chat；内置对话先审阅，授权后的 MCP 可直接保存并保留历史。 |
| **让 AI 找到已有素材** | 统一检索本地／NAS 素材资料、查看真实预览，并将原文件保存到稳定本机路径供 AI 使用。可选本地语义排序独立于笔记检索。[使用说明](../ASSET_WORKFLOWS.md)。 |
| **ChatGPT 也能用你的知识** | 桌面端内置 Tunnel 客户端，在 ChatGPT 对话中检索、读取本地笔记。 |

整理个人资料、搭建项目 Wiki、积累阅读笔记，或给 AI 助手一份有据可查的知识来源，都可以从自己的文件夹开始。

## 知识留在本地，分享由你决定

- **资料就在自己的文件夹里。** 浏览、编辑、图谱和本地检索不向托管知识库上传笔记。完成依赖和所需模型的初次准备后，这些功能可以离线使用。
- **检索范围由你选择。** 默认不索引任何目录；本地服务仅监听本机，文件访问限制在关联目录内。
- **AI 按需连接。** AI Chat 可能向所选服务发送问题、选文、已启用的笔记上下文和检索依据；使用 ChatGPT 连接时，请求的工具结果会发送给 ChatGPT。

[了解本地存储、访问边界与 AI 隐私](../SECURITY.md)

## 在 ChatGPT 中使用本地知识库

**让 ChatGPT 带着你的知识回答。** 在 ChatGPT 网页对话中选择 LeafLoom，即可检索已选择的目录、读取笔记，并沿着来源继续交流。运行 LeafLoom 的电脑需要保持联网、应用保持运行。在设置中启用完整笔记访问及独立写入开关后，可让 ChatGPT 创建、编辑、整理和恢复笔记；RAG 继续使用原有勾选范围。

[打开 ChatGPT](https://chatgpt.com/) · [前往 ChatGPT 插件页添加连接](https://chatgpt.com/plugins) · [官方 Tunnel 接入指南](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)

![英文示意图：选中 Chat，在对话输入框中使用 LeafLoom 插件](../../assets/promo/leafloom-chatgpt.png)

*上图为 Chat 使用场景示意；下方设置页来自实际桌面应用。*

### 配置一次，随应用自动连接

开始前，需要已有的 OpenAI Tunnel、对应的运行时 App Key，以及允许自定义 MCP 连接的 ChatGPT 工作区。安装 LeafLoom 不会自动创建这些资源；如尚未准备，请先阅读[官方接入指南](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。本地工作区无需此连接即可使用。

1. 在 LeafLoom 桌面应用中打开 **设置 → AI 连接 → ChatGPT 连接**，填写已有的 **Tunnel ID** 和具有 **Tunnels Read + Use** 权限的 **App Key**，点击 **保存并连接**。客户端已内置，无需另外下载、编写配置文件或打开终端。
2. 在 ChatGPT 中添加自定义 MCP，连接方式选择 **Tunnel**，填写同一 Tunnel ID，认证选择 **无认证**。安装连接后，在对话中选择 **LeafLoom**。Tunnel 需要关联到目标 ChatGPT 工作区，该工作区需允许自定义 MCP 连接；详见[官方接入指南](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。
3. 试着问：“找到与这个主题有关的笔记，并列出来源。”先在 LeafLoom 中选择检索目录；默认不索引任何目录。

![LeafLoom 的 ChatGPT 连接设置：Tunnel ID、加密保存的 App Key、自动连接开关与连接状态](../../assets/screenshots/zh-CN/showcase-chatgpt-settings.png)

App Key 由操作系统加密保存。连接随应用启动，关闭窗口留在托盘时继续运行，退出应用时停止。点击 **断开** 会停用自动连接，直到再次启用。笔记保存在自己的电脑上；调用工具时，请求的结果会发送给 ChatGPT。

[桌面安装与连接详情](../DESKTOP.md#chatgpt-connection) · [平台验证与当前限制](../TUNNEL_VALIDATION.md)

<a id="ai-connections"></a>

## MCP、Skill 与 AI Chat

在熟悉的工具里使用自己的知识，并随时核对原文依据。

| 连接方式 | 可以怎么用 |
| --- | --- |
| **MCP** | 将 Codex、Cursor、Claude Code 等客户端接入本地 HTTP MCP：`http://127.0.0.1:18080/mcp`（默认端口）。启用完整访问后可查找、创建、编辑、整理和恢复关联笔记；RAG 保持勾选范围，写入默认关闭。 |
| **飞书** | 使用自行配置的 lark-cli 验证账号，让 MCP 客户端操作飞书文档与多维表格。本机和 Tunnel 权限分别设置，默认关闭。[接入指南](GUIDE.md#可选飞书接入)。 |
| **Skill** | 在 **设置 → Skill → 安装技能** 中安装内置的 [`wiki-search` Skill](../../wiki-search/SKILL.md)，引导兼容的 AI 助手完成检索、Wiki 导航与来源核对；MCP 连接需另行配置。 |
| **AI Chat** | 需另外安装并登录 Codex 或 Codely CLI。围绕当前笔记或选文对话，打开回答中的引用。先预览修改差异，接受到草稿后再决定何时保存。 |

[配置 AI Chat、MCP 与 Skill](AI.md)

## 看见知识工作台

首次启动时点击「体验演示知识库」，即可打开内置的[阅读与学习工作室](../../vault_rag/examples/zh-CN)。示例包含相互连接的笔记、本地 HTML 阅览室，以及项目、阅读和决策模板。可以直接修改，再次打开会保留已有编辑。

### Markdown 文档：从阅读到记录

直接在排版后的正文中编辑，用 `/` 命令插入内容、拖动块、修改表格、粘贴截图或拖入附件。正文与 Markdown 源码共用撤销历史，未修改原文和属性保持不变；普通编辑自动保存，AI 草稿手动保存。参阅 [Markdown 编辑指南](GUIDE.md#用命令快速编辑)。

![Markdown 项目笔记：表格、任务清单、双链与文档目录](../../assets/screenshots/zh-CN/showcase-markdown.png)

### 知识图谱：沿着连接发现线索

沿着反向链接，找回一个决策背后的想法；打开图谱，发现曾经忽略的关联。示例展示知识卡片、项目、阅读资料和学习日志之间的真实链接。

![阅读与学习工作室的知识图谱](../../assets/screenshots/zh-CN/showcase-graph.png)

### AI Chat：围绕当前笔记展开思考

把原文与对话放在一起，从回答中的引用回到关联笔记。图中对话明确标注为虚构演示，未调用外部 AI。

![阅读项目旁的 AI Chat，回答引用关联笔记](../../assets/screenshots/zh-CN/showcase-ai.png)

### HTML 预览：把本地网页也放进知识库

打开本地 `.html`、`.htm` 文件，确认一次项目文件夹，即可运行带有配套样式、脚本和资源的网站。支持网页导航、下载与可选 SPA 路由，也可从侧栏「网页」打开已有 HTTP/HTTPS 网站或开发服务。参阅 [HTML 项目指南](GUIDE.md#打开-html-项目网站与设计工作台)。下图的 HTML 阅览室已包含在演示库中。

![LeafLoom 内的本地 HTML 阅览室预览](../../assets/screenshots/zh-CN/showcase-html.png)

## 开始使用

**推荐直接安装 [最新 Release](https://github.com/DJ-Huang/LeafLoom/releases/latest) 中的桌面应用。** 无需克隆仓库，也无需预装 Python、Node 或 Ollama。

| 系统 | 下载 | 安装方式 |
| --- | --- | --- |
| Windows 10/11 x64 | [Windows 安装包](https://github.com/DJ-Huang/LeafLoom/releases/latest) · `.exe` | 运行安装程序，完成后从开始菜单或桌面快捷方式打开 LeafLoom。 |
| macOS 14+ · Apple 芯片 | [Mac 安装包](https://github.com/DJ-Huang/LeafLoom/releases/latest) · `.dmg` | 打开磁盘映像，将 LeafLoom 拖入「应用程序」，再启动应用。 |

**安装前须知：** Windows 安装包未签名；Mac 安装包采用临时签名，未经 Apple 公证。SmartScreen 或 Gatekeeper 可能警告或阻止安装。不提供 Linux、Intel Mac 或 Windows ARM 安装包。请查看[当前版本的签名状态](https://github.com/DJ-Huang/LeafLoom/releases/latest)与[桌面验证边界](../DESKTOP.md#signing-and-release)。

### 完成第一次可追溯检索

以下步骤无需 AI 账号、CLI 或语义检索模型。

1. 选择 **中文 → 体验演示知识库**。内置笔记为虚构示例，与自己的文件分开；再次打开演示库会保留修改。
2. 在检索范围步骤勾选 **Concepts**，再点击 **保存范围并继续 → 开始探索**。模型可以稍后准备；默认不会勾选任何目录。
3. 打开侧栏的 **知识检索**，搜索 **原子笔记**。打开 `Concepts/Atomic-notes.md` 对应的结果阅读原文，再沿 **来源笔记** 链接继续浏览。
4. 如果没有结果，在 **设置 → 检索与索引** 中检查勾选范围与索引状态。未准备语义模型时，关键词/Wiki 回退是正常情况，不代表语义索引已经完成。

**检索范围：** 只有选中目录内的 `.md`、`.txt` 笔记会被索引。HTML、图片、视频和附件可以浏览，但不会被纳入知识检索或转写。`Ctrl/⌘+K` 按文件名查找；**知识检索** 搜索符合条件的笔记正文。

准备好后，在设置中关联自己的目录。文件保留原位，保存的编辑会修改原始文件。需要本地语义检索时，再在检索设置中准备 BGE-M3。

[详细安装要求与平台验证说明](../DESKTOP.md)

<details>
<summary>从源码启动（供开发使用）</summary>

```sh
git clone https://github.com/DJ-Huang/LeafLoom.git
cd LeafLoom
```

1. 下载或克隆仓库到可写的本机目录，完整解压。
2. 安装 Node 22+（含 npm）和 uv。Windows 10/11 x64：双击 `Dev.cmd`。macOS 14+ Apple 芯片：双击 `Dev.command` 或运行 `sh Dev.sh`。
3. 首次自动准备独立 Python 环境与依赖，打开源码桌面并启用前端自动更新。Dev 与安装版共用用户配置、模型和数据，只有开发依赖位于 `.cache/desktop-dev/.venv`；切换前先退出当前应用。检索模型在设置中按需准备。
4. 选择语言，体验虚构演示库或关联自己的目录，再明确选择检索范围。

**可选浏览器开发：** 使用专用状态目录和浏览器 profile，在不启动 Electron 的情况下运行真实后端。受管浏览器无法打开 `*.localhost` 时，可显式启用 `--loopback-ui`，让管理界面使用 `localhost`；隔离的 HTML 项目预览仍可能受影响。详见[启动步骤与边界](../DESKTOP.md#optional-browser-development)。这不代表新增 Linux 桌面安装支持。

</details>

[📖 新手指南与常见问题](GUIDE.md) · [✨ AI 接入](AI.md)

## 三种语言

用熟悉的 **中文、English 或日本語** 开始。界面、新手引导、使用指南和功能截图覆盖三种语言；语言偏好独立保存，不改变索引设置。

**自己的知识，自己部署，自己掌控。** 在受支持的电脑上自主运行，使用仅本机访问、私有身份校验与目录边界保护。[部署与安全](../SECURITY.md)。

## 能力与边界

阅读、编辑、图谱和关键词检索无需模型；需要本地语义检索时，再在设置中准备 BGE-M3。外部 AI 和 ChatGPT 需要各自的账号、权限与网络连接。

桌面安装器支持上方平台；不提供云同步、通用 Obsidian 插件兼容或媒体转写。

## 更新与参与

**桌面应用：** 退出 LeafLoom，从 [Releases](https://github.com/DJ-Huang/LeafLoom/releases/latest) 下载对应系统的新版安装包，安装后重新打开。

**源码开发：** 更新仓库后重新运行 Dev。前端修改自动更新；修改 Python/Electron 后，从开发实例的托盘／菜单栏退出再启动。安装版通过自己的快捷方式和菜单管理。

[Contributing](../../CONTRIBUTING.md) · [Changelog](../../CHANGELOG.md) · [Third-party notices](../../THIRD_PARTY_NOTICES.md) · [Media](../../docs/MEDIA.md)

MIT © 2026 DJ。依赖和模型保留各自许可。 [License](../../LICENSE)

Technical compatibility: `vault-rag`, `VAULT_RAG_HOME`, `.vault-rag/`, HTTP MCP `/mcp`.

将 Markdown 笔记组织为本地数据库，支持表格、列表、看板、画廊和可拖动时间线。[数据库指南](GUIDE.md#笔记数据库)。
