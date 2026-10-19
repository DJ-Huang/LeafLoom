# LeafLoom documentation · 文档目录 · ドキュメント

[Project home](../README.md) · [中文首页](zh-CN/README.md) · [日本語ホーム](ja/README.md)

**Help center · 帮助中心 · ヘルプセンター:** [English](https://dj-huang.github.io/LeafLoom/docs/en/) · [中文](https://dj-huang.github.io/LeafLoom/docs/zh-CN/) · [日本語](https://dj-huang.github.io/LeafLoom/docs/ja/)

The public help center has 39 task guides and four full guide/release references per language, with topic navigation, local full-text search, article contents, previous/next navigation, image zoom and copyable examples. Sources live in `docs/{en,zh-CN,ja}/help/`; [navigation.json](help/navigation.json) lists every article. The website build validates and publishes them with the existing guides. See [website maintenance](WEBSITE.md#help-center).

## Start here · 从这里开始 · はじめに

| Topic / 主题 / 内容 | English | 中文 | 日本語 |
| --- | --- | --- | --- |
| Install, write Markdown, open HTML projects, recover drafts | [User guide](en/GUIDE.md) | [使用指南](zh-CN/GUIDE.md) | [利用ガイド](ja/GUIDE.md) |
| AI Chat, MCP and Skills | [AI connections](en/AI.md) | [AI 接入](zh-CN/AI.md) | [AI 連携](ja/AI.md) |
| Attachment workspace, previews, organization and recovery | [Attachments](en/GUIDE.md#attachment-manager) | [附件管理](zh-CN/GUIDE.md#附件管理) | [添付ファイル](ja/GUIDE.md#添付ファイルの管理) |
| Change history | [Changelog](../CHANGELOG.md) | [更新记录](zh-CN/CHANGELOG.md) | [変更履歴](ja/CHANGELOG.md) |
| LeafLoom 0.1.3 release notes | [Release notes](en/RELEASE_NOTES_0.1.3.md) | [版本说明](zh-CN/RELEASE_NOTES_0.1.3.md) | [リリースノート](ja/RELEASE_NOTES_0.1.3.md) |
| Contributing | [Contributing](../CONTRIBUTING.md) | [参与贡献](zh-CN/COMMUNITY.md) | [貢献ガイド](ja/COMMUNITY.md) |

## Feature and setup references · 功能与配置

- [Public website build, downloads and GitHub Pages maintenance](WEBSITE.md)

- [Desktop installation, builds and ChatGPT connection](DESKTOP.md)
- [GitHub dual-platform builds, Release drafts and retries](DESKTOP.md#automatic-release-drafts)
- [Run the source desktop with automatic frontend updates](DESKTOP.md#source-development)
- [Optional browser development, isolated state and managed-browser limits](DESKTOP.md#optional-browser-development)
- [Desktop installation and source development setup](SETUP.md)
- [HTML project folders, sessions, storage migration and Safari compatibility](HTML_PROJECTS.md)
- [Design Studio workflows, portable documents, scripts and validation boundaries](DESIGN_STUDIO.md)
- [Bound design content, language variants and static publishing](DESIGN_STUDIO.md#bound-content-variants-and-static-publishing)
- [Folder organization and indexing scope](VAULT_ORGANIZATION.md)
- [AI assistant implementation](AI_ASSISTANT.md)
- [Complete MCP tools, credentials, note workflows and the two general file tools](MCP.md)
- [Feishu / Lark connection, CLI ownership and MCP tools](FEISHU.md)
- [Local access and privacy boundaries](SECURITY.md)
- [Architecture and workflow](ARCHITECTURE.md)
- [Screenshots and public media](MEDIA.md)

## Validation records · 验收记录

These records describe particular builds and environments. Use the current user guides for everyday operations; historical results do not certify later builds.

以下记录对应特定版本和环境；日常操作以当前使用指南为准，历史结果不代表后续版本已完成同样验收。

- [LeafLoom 0.1.3 PR audit and release preparation checklist](RELEASE_PREP_0.1.3.md)

- [HTML project checks and browser CI](HTML_PROJECTS.md#targeted-validation)
- [Feishu Windows Dev settings and live document/Base acceptance](FEISHU_VALIDATION.md)
- [Desktop acceptance](DESKTOP_VALIDATION.md)
- [ChatGPT Tunnel acceptance](TUNNEL_VALIDATION.md)
- [Installer acceptance](INSTALL_VALIDATION.md)
- [Productization acceptance](PRODUCTIZATION_VALIDATION.md)
- [Startup and reading measurements](READING_PERFORMANCE.md)
- [Browsing performance](BROWSING_PERFORMANCE.md)
- [Earlier UI, settings and graph changes](NOTION_UI.md)

Editor regression commands and the disposable browser harness are documented in [Contributing](../CONTRIBUTING.md). The current formatted Markdown editor is described in the three user guides above.
