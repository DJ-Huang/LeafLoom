# 参与 LeafLoom

[English](../../CONTRIBUTING.md) · [中文](COMMUNITY.md) · [日本語](../ja/COMMUNITY.md)

反馈问题时提供现象、预期、系统与版本、复现步骤。使用虚构笔记，移除路径、用户名、令牌和真实对话。安全问题优先使用 GitHub 私密漏洞报告，不公开凭证或私人资料。

改动保持聚焦，保留无关工作。`vault-rag`、`VAULT_RAG_HOME` 和 `.vault-rag` 是兼容接口。共享文案维护在 `vault_rag/locales/messages.tsv`，同步三种语言和占位符，再运行 `python scripts/compile_locales.py`；不要在生成 JSON 或构建产物中维护正文。

使用 Python 3.12 与锁定依赖，前端在 `web/` 中运行 `npm ci` 和 `npm run build`。按改动运行相关检查，产品化回归见 `tests/test_productization.py`。界面验证使用隔离的虚构知识库，清楚说明验证平台及未执行项目。截图与视频流程见 [媒体制作](../MEDIA.md)。贡献采用 MIT；第三方材料保留原许可。
