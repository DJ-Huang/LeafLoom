<p align="center"><img src="assets/brand/logo.svg" width="88" alt="LeafLoom logo" /></p>

# LeafLoom

**Keep your knowledge local. Put it to work with AI.**

[English](README.md) · [中文](docs/zh-CN/README.md) · [日本語](docs/ja/README.md)

**[Visit the website & download](https://dj-huang.github.io/LeafLoom/)** · Product screenshots, Windows and Mac installers, and release notes.

Turn scattered notes, project docs and saved webpages into a connected knowledge base. **LeafLoom is an open-source, local-first knowledge management workspace and personal wiki** for Markdown and HTML, with source-linked search, a knowledge graph, MCP, Skills, AI Chat and ChatGPT integration.

Your files and search indexes live on your computer. Browse, write and search locally; connect AI when you want your knowledge in the conversation.

**[Download for Windows](https://github.com/DJ-Huang/LeafLoom/releases/latest) · [Download for Mac](https://github.com/DJ-Huang/LeafLoom/releases/latest)**

Check [supported systems and signing status](#get-started) before installing.

[Get started](#get-started) · [Connect ChatGPT](#your-local-knowledge-in-chatgpt) · [MCP, Skills & AI Chat](#ai-connections) · [User guide](docs/en/GUIDE.md) · [Documentation](docs/README.md)

![LeafLoom welcome screen: choose a language, open a folder or try the demo](assets/screenshots/en/01-welcome.png)

## One home for your knowledge

| What you need | What LeafLoom brings |
| --- | --- |
| **A knowledge base that grows with you** | Organize notes, research and project docs into a personal wiki with bidirectional links, backlinks, templates and a knowledge graph. |
| **Privacy you control** | Keep files and indexes on your own computer. Choose exactly which folders enter search; no hosted knowledge base is required. |
| **Markdown + HTML** | Write Markdown with tables and tasks, and open local HTML pages with their styles, images and supported scripts inside the same workspace. |
| **Game screens you can edit** | Use [Design Studio](docs/DESIGN_STUDIO.md) to organize projects and assets, combine reusable pages/components, add scripts and animation, undo human or AI edits, and export portable HTML. |
| **Answers you can trace** | Use keyword search, Wiki navigation and optional local BGE-M3 semantic retrieval. Follow results back to the original notes. |
| **AI in your workflow** | Connect MCP clients, install the bundled `wiki-search` Skill, or use AI Chat beside your notes. The built-in chat previews edits; authorized MCP clients can save directly with history. |
| **Your knowledge in ChatGPT** | Connect the desktop app through its built-in Tunnel client to search and read local notes from a ChatGPT conversation. |

Keep a research library, build a project wiki, collect reading notes, or give your AI assistant a source it can actually cite.

## Local by design. Sharing by choice.

- **Your knowledge stays in your folders.** Browsing, editing, graphs and local retrieval do not upload notes to a hosted knowledge service. After dependencies and any chosen search model are prepared, these features work offline.
- **You choose the search scope.** No folders are indexed by default. The local service listens only on your computer, and file access stays within the connected folder.
- **AI connections are optional.** AI Chat may send your question, selected text, enabled note context and retrieved references to your chosen provider. ChatGPT receives requested tool results when you use the connection.

[How local storage, access boundaries and AI privacy work](docs/SECURITY.md)

## Your local knowledge, in ChatGPT

**Bring your own knowledge into the conversation.** Select LeafLoom in a ChatGPT web conversation to search your chosen folders, read notes and follow the sources while you chat. Your LeafLoom computer must be online with the app running. Enable full note access and its separate write switch in Settings to let ChatGPT create, edit, organize and recover notes. RAG keeps your selected scope.

[Open ChatGPT](https://chatgpt.com/) · [Add a connection in ChatGPT Plugins](https://chatgpt.com/plugins) · [Official Tunnel setup guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)

![Illustration of Chat selected with the LeafLoom plugin in the conversation composer](assets/promo/leafloom-chatgpt.png)

*Illustrative Chat experience; the settings below are captured from the actual desktop app.*

### Connect once, start with the app

Before starting, you need an existing OpenAI Tunnel, its runtime App Key and a ChatGPT workspace that allows custom MCP connections. Installing LeafLoom does not create these. Follow the [official setup guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) first if needed; the local workspace works without this connection.

1. In the LeafLoom desktop app, open **Settings → AI connections → ChatGPT connection**. Enter your existing **Tunnel ID** and **App Key** with **Tunnels Read + Use** permissions, then choose **Save and connect**. The client is built in: no separate download, configuration file or terminal is needed.
2. In ChatGPT, add a custom MCP server, choose **Tunnel**, enter the same Tunnel ID and select **No authentication**. Install the connection and select **LeafLoom** in your chat. The Tunnel must be associated with your ChatGPT workspace, which must allow custom MCP connections; see the [official setup guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
3. Ask, for example: “Find my notes about this topic and show the sources.” Choose your searchable folders in LeafLoom first; no folders are indexed by default.

![LeafLoom desktop settings for ChatGPT connection: Tunnel ID, encrypted App Key, automatic connection and connection status](assets/screenshots/en/showcase-chatgpt-settings.png)

The App Key is encrypted by the operating system. Connections start with LeafLoom, continue while the window is closed to the tray, and stop when you quit. **Disconnect** disables automatic connection until you enable it again. Notes stay on your computer; requested tool results are sent to ChatGPT.

[Desktop installation and connection details](docs/DESKTOP.md#chatgpt-connection) · [Platform validation and current limits](docs/TUNNEL_VALIDATION.md)

<a id="ai-connections"></a>

## MCP, Skills and AI Chat

Use your knowledge where you already work, with source references you can check.

| Connection | How you use it |
| --- | --- |
| **MCP** | Connect clients such as Codex, Cursor or Claude Code to the local HTTP MCP endpoint at `http://127.0.0.1:18080/mcp` (default port). Enable full access to find, create, edit, organize and recover connected notes. RAG keeps your selected scope; writing starts disabled. |
| **Feishu / Lark** | Connect an externally configured lark-cli to verify your account and let MCP clients work with documents and Base records. Local and Tunnel permissions are separate and start disabled. [Setup](docs/en/GUIDE.md#optional-feishu--lark-connection). |
| **Skills** | Install the included [`wiki-search` Skill](wiki-search/SKILL.md) from **Settings → Skill → Install skill**. It guides compatible assistants through retrieval, Wiki navigation and source checking. Configure MCP separately. |
| **AI Chat** | Requires a separately installed, signed-in Codex or Codely CLI. Discuss a note or selection and open cited sources. Preview suggested changes, accept them into a draft, then save when ready. |

[Set up AI Chat, MCP and Skills](docs/en/AI.md)

## A workspace for connected thinking

Try the built-in [learning studio](vault_rag/examples/en) from **Try the demo** on first launch. It includes connected notes, a local HTML reading room, and reusable project, reading and decision templates. You can edit the examples; reopening the demo keeps your changes.

### Markdown, ready to read and write

Edit directly on the formatted page: use `/` commands, drag blocks, edit tables, and paste screenshots or drop attachments. Switch to Markdown source with shared undo history; unchanged source and properties are preserved. Ordinary edits autosave, while AI drafts require manual saving. [Markdown editing guide](docs/en/GUIDE.md#write-with-commands).

![Markdown project brief with a table, tasks, linked notes and document outline](assets/screenshots/en/showcase-markdown.png)

### See how your ideas connect

Follow a backlink to the idea behind a decision, or explore the graph to discover a connection you had forgotten. The starter vault shows real links across concepts, projects, reading notes and journals.

![Knowledge graph of the connected learning studio](assets/screenshots/en/showcase-graph.png)

### Think alongside your notes with AI Chat

Keep the current note beside a conversation and follow references back to the source. This screenshot uses an explicitly labeled fictional conversation; no external AI was called.

![AI Chat beside a reading project, with references to related notes](assets/screenshots/en/showcase-ai.png)

### Open local HTML inside your workspace

Open a local `.html` or `.htm` file, confirm its project folder once, and run the website with its companion styles, scripts and resources. Use project navigation, downloads, optional SPA routing, or open an existing HTTP/HTTPS site or development server from **Preview**. [HTML project guide](docs/en/GUIDE.md#open-html-projects-websites-and-design-studio). The HTML reading room below is included in the demo.

![Local HTML reading room previewed inside LeafLoom](assets/screenshots/en/showcase-html.png)

## Get started

**Recommended: install the desktop app from the [latest Release](https://github.com/DJ-Huang/LeafLoom/releases/latest).** No repository clone or preinstalled Python, Node or Ollama is needed.

| Platform | Download | Install |
| --- | --- | --- |
| Windows 10/11 x64 | [Windows installer](https://github.com/DJ-Huang/LeafLoom/releases/latest) · `.exe` | Run the installer, then open LeafLoom from Start or the desktop shortcut. |
| macOS 14+ · Apple Silicon | [Mac installer](https://github.com/DJ-Huang/LeafLoom/releases/latest) · `.dmg` | Open the disk image, drag LeafLoom to Applications, then launch it. |

**Before installing:** Windows packages are unsigned; Mac packages use ad-hoc signing and are not Apple-notarized. SmartScreen or Gatekeeper may warn or block installation. No Linux, Intel Mac or Windows ARM installer is provided. See the [release's signing status](https://github.com/DJ-Huang/LeafLoom/releases/latest) and [desktop validation limits](docs/DESKTOP.md#signing-and-release).

### Try your first source-linked search

No AI account, CLI or semantic-search model is needed for this walkthrough.

1. Choose **English → Try the demo**. The included notes are fictional and separate from your own files; demo edits are kept when you return.
2. In the search-scope step, select **Concepts**, then **Save and continue → Start exploring**. You can leave model preparation for later. No folders are selected automatically.
3. Open **Knowledge search** in the sidebar and search for **Atomic notes**. Open the result for `Concepts/Atomic-notes.md` to read the original note, then follow its **Source notes** link.
4. If there are no results, check **Settings → Search and indexing** for the selected scope and indexing status. A keyword/Wiki fallback without a prepared semantic model is expected; it does not mean semantic indexing is complete.

**Search scope:** Only selected `.md` and `.txt` notes are indexed. HTML, images, videos and attachments can be browsed, but are not indexed or transcribed for knowledge search. `Ctrl/⌘+K` finds files by name; **Knowledge search** searches eligible note content.

When ready, connect your own folder in Settings. Files stay in place, and edits you save change those original files. Prepare BGE-M3 from search settings only when you want local semantic retrieval.

[Detailed installation and platform validation](docs/DESKTOP.md)

<details>
<summary>Run from source (for development)</summary>

```sh
git clone https://github.com/DJ-Huang/LeafLoom.git
cd LeafLoom
```

1. Download or clone this repository into a writable local folder.
2. Install Node 22+ (with npm) and uv. Windows 10/11 x64: double-click `Dev.cmd`. macOS 14+ Apple Silicon: double-click `Dev.command` or run `sh Dev.sh`.
3. First launch prepares a separate Python environment and dependencies, then opens the source desktop with automatic frontend updates. Dev shares the installed app's user settings, models and data. Only development dependencies stay in `.cache/desktop-dev/.venv`. Quit the running app before switching modes. The local search model is prepared only when requested in settings.
4. Choose a language, try the fictional demo or connect your folder, then explicitly select what to search.

**Optional browser development:** Run the real backend with a dedicated state directory and browser profile, without Electron. The opt-in `--loopback-ui` mode uses literal `localhost` when a managed browser cannot open `*.localhost`; isolated HTML project previews may still be affected. See [setup and limits](docs/DESKTOP.md#optional-browser-development). This does not add Linux desktop installer support.

</details>

[📖 User guide and FAQ](docs/en/GUIDE.md) · [✨ AI connections](docs/en/AI.md)

## Languages

Feel at home in **English, 简体中文 or 日本語**. The interface, onboarding, user guides and feature screenshots cover all three languages. Language preferences are saved separately from indexing settings.

**Your knowledge. Your deployment. Your control.** Run LeafLoom on your own supported computer. Local-only access, private authentication and folder boundaries keep you in control. [Deployment and security](docs/SECURITY.md).

## What to expect

Reading, editing, graphs and keyword search work without a model. Prepare BGE-M3 in search settings when you want local semantic retrieval. External AI and ChatGPT require their own accounts, permissions and network access.

The desktop installer supports the platforms above. This is not cloud sync, universal Obsidian plugin support or media transcription.

## Update and contribute

**Desktop app:** Quit LeafLoom, install the updated package for your platform from [Releases](https://github.com/DJ-Huang/LeafLoom/releases/latest), then reopen it.

**Source development:** Update the repository and relaunch Dev. Frontend edits update automatically; Python/Electron edits require quitting Dev from its tray/menu-bar menu and relaunching. Installed apps are managed through their own shortcuts and menus.

[Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Third-party notices](THIRD_PARTY_NOTICES.md) · [Media](docs/MEDIA.md)

MIT © 2026 DJ. Dependencies and models keep their own licenses. [License](LICENSE)

Technical compatibility: `vault-rag`, `VAULT_RAG_HOME`, `.vault-rag/`, HTTP MCP `/mcp`.
