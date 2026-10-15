<p align="center"><img src="assets/brand/logo.svg" width="88" alt="LeafLoom logo" /></p>

# LeafLoom

**Weave your notes into knowledge.**

[English](README.md) · [中文](docs/zh-CN/README.md) · [日本語](docs/ja/README.md)

A local knowledge workspace for people who want to keep their files and make better use of them. Read and write Markdown, search your notes with source links, and explore how ideas connect.

**Demo:** 

https://github.com/user-attachments/assets/56f37418-23cc-4763-af3c-3253fb06f517

| Your files stay yours | Read and write | Find the source | See the connections |
| --- | --- | --- | --- |
| Work directly with local Markdown, text and attachments. No content migration required. | Reading-first notes, Markdown editing, properties, templates and recoverable history. | Keyword, Wiki and local BGE-M3 retrieval, limited to folders you choose. | Bidirectional links, backlinks and an interactive knowledge graph. |

**Optional AI.** Connect a signed-in CLI or an HTTP MCP client. Review AI suggestions before saving. External AI services may receive the content you send.

## Your local knowledge, in ChatGPT

**Access your local knowledge base from anywhere.** Select LeafLoom in a ChatGPT web conversation to search your chosen folders, read notes and follow the sources while you chat. Your LeafLoom computer must be online with the app running. The current connection supports searching and reading; edit notes in LeafLoom.

![Illustration of Chat selected with the LeafLoom plugin in the conversation composer](assets/promo/leafloom-chatgpt.png)

*Illustrative Chat experience; the settings below are captured from the actual desktop app.*

### Connect once, start with the app

1. In the LeafLoom desktop app, open **Settings → ChatGPT connection**. Enter your existing **Tunnel ID** and **App Key** with **Tunnels Read + Use** permissions, then choose **Save and connect**. The client is built in: no separate download, configuration file or terminal is needed.
2. In ChatGPT, add a custom MCP server, choose **Tunnel**, enter the same Tunnel ID and select **No authentication**. Install the connection and select **LeafLoom** in your chat. Your ChatGPT account or workspace must allow custom MCP connections; see the [official setup guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
3. Ask, for example: “Find my notes about this topic and show the sources.” Choose your searchable folders in LeafLoom first; no folders are indexed by default.

![LeafLoom desktop settings for ChatGPT connection: Tunnel ID, encrypted App Key, automatic connection and connection status](assets/screenshots/en/showcase-chatgpt-settings.png)

The App Key is encrypted by the operating system. Connections start with LeafLoom, continue while the window is closed to the tray, and stop when you quit. **Disconnect** disables automatic connection until you enable it again. Notes stay on your computer; requested tool results are sent to ChatGPT.

[Desktop installation and connection details](docs/DESKTOP.md#chatgpt-connection) · [Platform validation and current limits](docs/TUNNEL_VALIDATION.md)

## A workspace for connected thinking

Try the built-in [learning studio](vault_rag/examples/en) from **Try the demo** on first launch. It includes connected notes, a local HTML reading room, and reusable project, reading and decision templates. You can edit the examples; reopening the demo keeps your changes.

### Markdown, ready to read and write

Keep project briefs, tables, checklists and linked notes in ordinary local Markdown files.

![Markdown project brief with a table, tasks, linked notes and document outline](assets/screenshots/en/showcase-markdown.png)

### See how your ideas connect

Explore the starter vault's real links across concepts, projects, reading notes and journals.

![Knowledge graph of the connected learning studio](assets/screenshots/en/showcase-graph.png)

### Think alongside your notes with AI Chat

Keep the current note beside a conversation and follow references back to the source. This screenshot uses an explicitly labeled fictional conversation; no external AI was called.

![AI Chat beside a reading project, with references to related notes](assets/screenshots/en/showcase-ai.png)

### Open local HTML inside your workspace

Read a complete HTML guide with its local stylesheet and illustrations, without leaving LeafLoom.

![Local HTML reading room previewed inside LeafLoom](assets/screenshots/en/showcase-html.png)

## Get started

**Desktop app:** LeafLoom now has an Electron desktop build for Windows x64 and
Apple Silicon Mac, with a private Python backend and independent application
window. See [desktop installation, build and validation](docs/DESKTOP.md).
The repository launchers below remain available for source installation.

```sh
git clone https://github.com/DJ-Huang/LeafLoom.git
cd LeafLoom
```

1. Download or clone this repository into a writable local folder.
2. Windows 10/11 x64: double-click `Start.cmd`. macOS 14+ Apple Silicon: run `sh Start.sh` in the repository.
3. First launch prepares private runtimes and dependencies, then opens the workspace. The local search model is downloaded when explicitly prepared in settings. No preinstalled Python, Node or Ollama is required.
4. Choose a language, try the fictional demo or connect your folder, then explicitly select what to search.

No folders are indexed by default. You can start by browsing and enable search later.

[📖 User guide and FAQ](docs/en/GUIDE.md) · [✨ AI connections](docs/en/AI.md) · [▶ English promotional video](https://github.com/DJ-Huang/LeafLoom/raw/refs/heads/main/assets/promo/leafloom-en.mp4)

## Languages

The web interface, onboarding and shared desktop text support English, 简体中文 and 日本語. Language preferences are saved separately from indexing settings.

**Your knowledge. Your deployment. Your control.** Run LeafLoom on your own supported computer. Local-only access, private authentication and folder boundaries keep you in control. [Deployment and security](docs/SECURITY.md).

## What to expect

Notes and indexes stay local. Optional external AI follows your chosen provider’s network and data handling. After initial setup, local browsing/search can work offline.

The desktop installer supports the platforms above. This is not cloud sync, universal Obsidian plugin support or media transcription.

## Update and contribute

Update the repository, run `Install.cmd` or `sh Install.sh`, and restart the service. Browser reload alone does not update the server.

[Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Third-party notices](THIRD_PARTY_NOTICES.md) · [Media](docs/MEDIA.md)

MIT © 2026 DJ. Dependencies and models keep their own licenses. [License](LICENSE)

Technical compatibility: `vault-rag`, `VAULT_RAG_HOME`, `.vault-rag/`, HTTP MCP `/mcp`.
