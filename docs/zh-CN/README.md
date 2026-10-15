<p align="center"><img src="../../assets/brand/logo.svg" width="88" alt="LeafLoom logo" /></p>

# LeafLoom · 知织

**让零散笔记，织成知识。**

[English](../../README.md) · [中文](../../docs/zh-CN/README.md) · [日本語](../../docs/ja/README.md)

一个面向个人的本地知识工作台。保留自己的文件，阅读与记录想法，检索并打开原文，探索笔记之间的连接。

**演示视频（英文）：**

https://github.com/user-attachments/assets/56f37418-23cc-4763-af3c-3253fb06f517

| 自己的文件 | 阅读与记录 | 找到原文依据 | 看见知识连接 |
| --- | --- | --- | --- |
| 直接使用本地 Markdown、文本和附件，无需迁移正文。 | 默认阅读，支持 Markdown 编辑、属性、模板和可恢复历史。 | 结合关键词、Wiki 与本地 BGE-M3，只检索你明确选择的目录。 | 通过双链、反向链接和交互图谱，找回想法之间的线索。 |

**可选 AI.** 连接已登录的 CLI 或 HTTP MCP 客户端。AI 修改先检查再保存；外部模型服务可能收到你发送的内容。

## 在 ChatGPT 中使用本地知识库

**随时随地，访问自己的本地知识库。** 在 ChatGPT 网页对话中选择 LeafLoom，即可检索已选择的目录、读取笔记，并沿着来源继续交流。运行 LeafLoom 的电脑需要保持联网、应用保持运行。当前连接支持检索和读取，笔记编辑在 LeafLoom 中完成。

![英文示意图：选中 Chat，在对话输入框中使用 LeafLoom 插件](../../assets/promo/leafloom-chatgpt.png)

*上图为 Chat 使用场景示意；下方设置页来自实际桌面应用。*

### 配置一次，随应用自动连接

1. 在 LeafLoom 桌面应用中打开 **设置 → ChatGPT 连接**，填写已有的 **Tunnel ID** 和具有 **Tunnels Read + Use** 权限的 **App Key**，点击 **保存并连接**。客户端已内置，无需另外下载、编写配置文件或打开终端。
2. 在 ChatGPT 中添加自定义 MCP，连接方式选择 **Tunnel**，填写同一 Tunnel ID，认证选择 **无认证**。安装连接后，在对话中选择 **LeafLoom**。ChatGPT 账号或工作区需要允许自定义 MCP 连接；详见[官方接入指南](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。
3. 试着问：“找到与这个主题有关的笔记，并列出来源。”先在 LeafLoom 中选择检索目录；默认不索引任何目录。

![LeafLoom 的 ChatGPT 连接设置：Tunnel ID、加密保存的 App Key、自动连接开关与连接状态](../../assets/screenshots/zh-CN/showcase-chatgpt-settings.png)

App Key 由操作系统加密保存。连接随应用启动，关闭窗口留在托盘时继续运行，退出应用时停止。点击 **断开** 会停用自动连接，直到再次启用。笔记保存在自己的电脑上；调用工具时，请求的结果会发送给 ChatGPT。

[桌面安装与连接详情](../DESKTOP.md#chatgpt-connection) · [平台验证与当前限制](../TUNNEL_VALIDATION.md)

## 看见知识工作台

首次启动时点击「体验演示知识库」，即可打开内置的[阅读与学习工作室](../../vault_rag/examples/zh-CN)。示例包含相互连接的笔记、本地 HTML 阅览室，以及项目、阅读和决策模板。可以直接修改，再次打开会保留已有编辑。

### Markdown 文档：从阅读到记录

用表格梳理项目，用清单安排下一步，用双链连接思考；正文始终是自己的本地 Markdown 文件。

![Markdown 项目笔记：表格、任务清单、双链与文档目录](../../assets/screenshots/zh-CN/showcase-markdown.png)

### 知识图谱：沿着连接发现线索

从知识卡片到项目、阅读资料和学习日志，图谱展示示例笔记之间的真实链接。

![阅读与学习工作室的知识图谱](../../assets/screenshots/zh-CN/showcase-graph.png)

### AI Chat：围绕当前笔记展开思考

把原文与对话放在一起，从回答中的引用回到关联笔记。图中对话明确标注为虚构演示，未调用外部 AI。

![阅读项目旁的 AI Chat，回答引用关联笔记](../../assets/screenshots/zh-CN/showcase-ai.png)

### HTML 预览：把本地网页也放进知识库

直接在工作区阅读完整的 HTML 指南，连同本地样式和插图一起呈现。

![LeafLoom 内的本地 HTML 阅览室预览](../../assets/screenshots/zh-CN/showcase-html.png)

## 开始使用

```sh
git clone https://github.com/DJ-Huang/LeafLoom.git
cd LeafLoom
```

1. 下载或克隆仓库到可写的本机目录，完整解压。
2. Windows 10/11 x64：双击 `Start.cmd`。 macOS 14+ Apple 芯片：在仓库目录运行 `sh Start.sh`。
3. 首次准备私有运行环境和依赖后打开工作区；检索模型在设置中按需准备，无需预装 Python、Node 或 Ollama。
4. 选择语言，体验虚构演示库或关联自己的目录，再明确选择检索范围。

默认不索引任何目录，可以先浏览、以后再开启检索。

[📖 新手指南与常见问题](GUIDE.md) · [✨ AI 接入](AI.md) · [▶ 英文宣传短视频](../../assets/promo/leafloom-en.mp4)

[![英文宣传短视频](../../assets/promo/cover.png)](../../assets/promo/leafloom-en.mp4)

## 三种语言

网页、新手引导和共享桌面文案支持中文、English 和日本語。语言偏好独立保存，不改变索引设置。

**自己的知识，自己部署，自己掌控。** 在受支持的电脑上自主运行，使用仅本机访问、私有身份校验与目录边界保护。[部署与安全](../SECURITY.md)。

## 能力与边界

笔记与索引保存在本机。可选外部 AI 遵循所选服务的联网与数据处理方式；完成初次准备后，本地浏览和检索可离线运行。

桌面安装器支持上方平台；不提供云同步、通用 Obsidian 插件兼容或媒体转写。

## 更新与参与

更新仓库后运行 `Install.cmd` 或 `sh Install.sh` 并重启服务。仅刷新浏览器不会更新服务器代码。

[Contributing](../../CONTRIBUTING.md) · [Changelog](../../CHANGELOG.md) · [Third-party notices](../../THIRD_PARTY_NOTICES.md) · [Media](../../docs/MEDIA.md)

MIT © 2026 DJ。依赖和模型保留各自许可。 [License](../../LICENSE)

Technical compatibility: `vault-rag`, `VAULT_RAG_HOME`, `.vault-rag/`, HTTP MCP `/mcp`.
