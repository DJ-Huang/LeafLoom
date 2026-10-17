# Your first steps with LeafLoom

Use **Settings → Skill** to install or update the bundled `wiki-search` skill.

[English](GUIDE.md) · [中文](../zh-CN/GUIDE.md) · [日本語](../ja/GUIDE.md)

[All documentation](../README.md)

## Install and open

**Developers:** In a source checkout, double-click `Dev.cmd` on Windows or `Dev.command` on macOS 14+ Apple Silicon; on Mac, `sh Dev.sh` also works in Terminal. Run `chmod +x Dev.command Dev.sh` once if a copied/downloaded checkout loses execute permissions. You can also run `node scripts/dev-desktop.cjs` on either platform. Requires Node 22+ and uv; the first launch installs dependencies. The desktop runs directly from source and frontend edits update automatically. Dev shares the installed app's settings, models, credentials and desktop data, including its configured backend port (18080 by default). Only development dependencies stay in `.cache/desktop-dev/.venv`; Vite uses port 5173. Quit the running app before switching modes. For isolated testing, explicitly set a disposable `VAULT_RAG_HOME`. Quit from the tray before relaunching after Python/Electron edits. See [source development](../DESKTOP.md#source-development).

**Optional browser development:** Follow [the two-terminal setup](../DESKTOP.md#optional-browser-development) to start Vite at `http://127.0.0.1:5173`, then run `uv run --locked python scripts/dev-browser.py --home /tmp/leafloom-browser-dev --port 36229 --loopback-ui`. Open the printed `http://localhost:36229/` in a dedicated browser profile. The required home must be new/empty or previously marked by this launcher; it pins the port and UI mode, so changes require a fresh home and profile. Omitting `--loopback-ui` keeps the normal `app.<installation-id>.localhost` UI. The real runtime and background workers remain active, without automatic model downloads or external AI calls. Separate HTML-project origins may still fail in affected managed browsers; do not bypass security warnings. This is browser development, not Linux desktop installer support.

Previous Dev settings remain in `.cache/desktop-dev/` for recovery and do not override installed settings. If the shared data directory has no `models/` directory, Dev copies the previous model files while keeping the originals; existing model directories are preserved.

The old repository launchers have been removed. Manage installed apps through their own shortcuts and menus. During development, use Dev and quit through its own tray/menu-bar menu or Ctrl+C.
The [LeafLoom website](https://dj-huang.github.io/LeafLoom/) offers English, Chinese and Japanese pages with screenshots and direct downloads of the latest available stable installer for each platform. Choose Windows or Mac explicitly; release notes and SHA-256 files are linked beside the installers. When a new Release has no installer for a platform, its download keeps the latest available stable version, with that version’s release notes and checksum. A platform is unavailable only if no stable Release provides its installer.

The website’s About page links to the creator’s GitHub and X profiles; open it from the top navigation or footer. Language switching keeps you on About.

Supported: Windows 10/11 x64 and macOS 14+ on Apple Silicon. Linux, Intel Mac and Windows ARM are not supported by the desktop installer.

**Recommended: download the desktop installer from the [latest Release](https://github.com/DJ-Huang/LeafLoom/releases/latest).** You do not need to clone the repository or install Python, Node or Ollama.

1. **Windows:** Download the Windows x64 `.exe`, run the installer, then open LeafLoom from Start or the desktop shortcut.
2. **Mac:** Download the macOS Apple Silicon `.dmg`, open it, drag LeafLoom to Applications, then launch it.
3. Choose a language and try the included demo or connect your own folder. Reading, editing, graphs and keyword search work without downloading the semantic-search model. Prepare BGE-M3 in search settings when needed.

Closing the window keeps LeafLoom in the tray/menu bar; use **Quit** to stop the application and its local service. Login startup is off for new installations and can be changed in desktop settings or the tray. To update, open **Settings → General → App updates → Check for updates**. The current and latest versions are shown. Choose **Download and install** to see the percentage and downloaded/total size. After SHA-256 verification, LeafLoom quits normally (including unsaved-draft prompts) and opens the Windows installer or Mac DMG. Complete the installer; on Mac, drag the new app to Applications. Reopen LeafLoom afterward. A canceled quit leaves **Continue installation** available. Failed requests/downloads can be retried. Dev only checks versions; update the source and restart Dev.

The service binds to `127.0.0.1`, normally on port `18080`. See [desktop installation details](../DESKTOP.md) for requirements and validation limits. Developers can use the [source installation instructions](../../README.md#get-started).

For maintainers, pushing a matching `vX.Y.Z` version tag automatically builds both
installers on GitHub and prepares a Release draft with `SHA256SUMS.txt`. Review the
Actions results and draft, then publish manually. Failed builds can be rerun;
published Releases are protected from replacement. Manual **Run workflow** builds
only provide Actions downloads. Current tag builds have no trusted publisher
signature (Mac uses ad-hoc signing without notarization), so system warnings or
blocks remain possible. See [build, retry and release instructions](../DESKTOP.md#automatic-release-drafts).

## Choose a language and folder

The welcome page follows your system language, with English as fallback. Select 中文, English or 日本語 to save a preference. Change it later in **Settings → General → Language**. Changing language keeps your open document, draft and position; it does not rebuild search indexes.

Choose **Try the demo** to explore fictional notes in a separate folder. You may edit them; returning preserves edits. Each language has its own demo. Choose **Connect your folder** to use an existing Markdown/Obsidian folder instead. LeafLoom keeps original files in place; it is a file editor, so edits you save change those files.

![Welcome](../../assets/screenshots/en/01-welcome.png)

## Select what to search

You can browse the entire connected folder. Knowledge search only uses the folders you explicitly select. Choose the whole folder or specific subfolders; exclude a child folder independently. Nothing is selected automatically. **Browse for now** leaves the knowledge corpus empty.

Only `.md` and `.txt` are indexed. Images, videos and other attachments remain browsable but are not transcribed. Hidden/application folders, `.ragignore` exclusions and opted-out notes remain excluded. Special rule, topic-navigation and estimation folders are advanced settings; ordinary notes do not need them.

![Search scope](../../assets/screenshots/en/07-settings.png)

## Read, write, find and connect

1. Open a Markdown note from the sidebar and edit directly on the formatted page. **View source** opens its Markdown text. Ordinary edits autosave; save conflicts keep your draft so you can review and merge.
2. Use **New note** to write an idea. Add `[[other note]]` to connect it to another note.
3. Use `Ctrl/⌘+K` to find a file by name. Use **Knowledge search** for questions and keywords in your notes.
4. Open a search result to read the original evidence. Check its context and verification status before relying on it.
5. Explore **Knowledge graph**. Search a note, filter folders, and follow nearby connections. A backlink needs another note that links to this one.
6. The home checklist is optional. Mark steps complete, hide it, or reopen it with **Getting started** in the sidebar.

![Reading](../../assets/screenshots/en/03-reading.png)
![Knowledge search](../../assets/screenshots/en/04-search.png)
![Knowledge graph](../../assets/screenshots/en/05-graph.png)

## Write with commands

Type `/` at the start of a line or after a space to insert headings, lists, tasks, quotes, tables, code, images, links, equations or Mermaid diagrams. The menu includes icons, descriptions, categories and recently used items. Search by name or aliases such as `/h2` and `/todo`; use the arrow keys and Enter, or Esc to keep the literal text. Code, formulas, properties and URLs do not open the menu.

Select text for the formatting toolbar. `Ctrl/⌘+B`, `Ctrl/⌘+I` and `Ctrl/⌘+E` toggle bold, italic and inline code. Paste a URL over selected text to make a link, or use `Ctrl/⌘+Shift+K` to enter one. Type `[[` and a note name to choose a note by its full path.

Hover beside a block to insert with **+**, or use its handle to convert, duplicate, move or delete it. Drag the handle to reorder paragraphs, list items or whole blocks. Select text across paragraphs and type directly in table cells. Tab moves between cells and adds a row from the last cell; the table toolbar manages rows, columns, the header and alignment. Paste screenshots or drop files into the editor: attachments go in the note's neighboring `attachments` folder with unique names. Uploading does not replace existing files; undoing the inserted link keeps the uploaded file. Failed or cancelled uploads may leave completed files in that folder.

Files remain ordinary Markdown; unchanged blocks and document properties retain their original source. The page and source views share undo history. Equations and Mermaid stay rendered and have dedicated editing panels. Complex or unsupported content is preserved for display and can be located in source. Changing the interface language keeps the editor and its history. Tables use simple Markdown structures, without merged cells or nested blocks inside cells.

## Open HTML projects, websites and Design Studio

1. Open a local `.html` or `.htm` file from the directory. Confirm its **Project folder** and choose **Save and open**. Select a folder containing the entry and all companion resources; the website's `/` maps to this folder. An empty folder value uses the connected knowledge folder's root.
2. Use **Project settings** to change the folder or enable **SPA routing** for a client-side application. This opens the project entry for missing page routes; missing scripts, images and JSON still return errors.
3. Use back, forward, refresh, full screen or **Open in new tab** in the website toolbar. In the desktop app, the same website runs inside its window. Browser and desktop website storage are independent.
4. To open an existing website or development server, choose **Preview → Open website** and enter its HTTP/HTTPS URL. LeafLoom does not install dependencies or start a backend. A site may refuse embedding or require sign-in.
5. Open **Design Studio** from the sidebar or a folder's **New design project here** menu. New projects use a managed visual document; existing `1.1.0` projects keep their layer-review tools and can be converted into a separate editable copy. Choose mobile portrait `720×1560`, mobile landscape `1560×720`, desktop `1440×900` or custom page dimensions.

**Source** opens the HTML text. Ordinary edits autosave; if an unsaved draft remains, the website view previews it in a temporary origin without saving it. Companion resources still come from disk. HTML remains browsable independently of the selected search folders and is not indexed for knowledge search.

On macOS 14/15 Safari, use **Settings → General → Safari local website compatibility** if local websites do not open. macOS requests administrator authorization for this installation's resolver configuration. See [HTML project details](../HTML_PROJECTS.md) for removal and platform limits.

When an older loopback address opens the new workspace address, local drafts and view state migrate automatically. Existing destination values win; a conflict banner offers a backup download. Original browser storage is retained. This migration does not synchronize browsers or the desktop app.

## Build game screens in Design Studio

- The project home offers search, recent/favorite projects, rename, copy, move, archive and a recoverable recycle bin. Workspace undo/redo covers project management; project history covers design edits across pages and restarts.
- Use **Pages** to add, group, reorder or duplicate screens. Insert text, images, containers, buttons, shapes, SVG, custom HTML, embedded pages, or game starters such as a HUD, character card, gallery and dialog. Select layers, Shift-select several, then use the canvas and inspector for position, size, rotation, text, appearance and row/column/grid layout. Child pages and component instances retain separate identities.
- Upload or paste artwork in **Assets**. Inspect dimensions/transparency, set names/categories/tags, locate uses and replace one image or all references. Publish components and assets to the personal shared library; import a newer version explicitly. Dependencies are copied into the project for offline use. A referenced asset cannot be removed until its uses are replaced or deleted.
- The **Animation** inspector offers fade, slide, scale, bounce, breathe and spin. In **Scripts and source**, attach `mount(ctx)` JavaScript to an element or page and expose parameters as inspector controls. Scripts pause during editing. Preview a component or the whole screen, then stop to restore the design state; logs identify the affected element. Source changes and parameters share the same undo history.
- **Send to AI** includes stable element IDs and the current revision. Managed design edits apply directly and one AI batch is one undo step. `Ctrl/⌘+Z` undoes and `Ctrl/⌘+Shift+Z` redoes, including after closing and reopening. Save conflicts retain pending changes; inspect them before choosing reload/reapply. Export after pending saves finish, unzip the result and open `index.html` with its companion files.

- HTML conversion retains document-root context, native mixed text and responsive image candidates. Unreadable external stylesheets are omitted with a warning; original source remains intact. Viewport/rem units and media queries still use the renderer environment. Native text runs expose content editing; select their parent for layout and typography. Compare the converted page with its original before relying on it.

- Navigate the canvas with **Select** (`V`) and **Hand** (`H`), or hold Space while dragging. Use the zoom percentage, +/−, fit page (`Shift+1`) and fit selection (`Shift+2`); Ctrl/⌘+wheel zooms around the pointer. Camera position stays steady while editing. Expand/collapse containers in **Layers**, use the selected-layer breadcrumb to reach ancestors, and edit grouped **Layout**, **Appearance** and **Typography** properties. If the isolated canvas cannot connect, use its retry action; the management shell can still show saved layers and properties.
- **Convert a copy** preserves the original project and imports authored DOM/CSS, text and assets, adapting recognized navigation, settings switches and context-dependent page states. Original scripts remain in the copied source; other legacy event handlers and runtime state need new scripts. Review conversion notices and compare the copy with the original before replacing a workflow. See the [workflow and script API](../DESIGN_STUDIO.md) for commands, import limits and performance acceptance targets.

The design project **Recycle bin** supports restore, **Delete project permanently** and **Empty project recycle bin**. Permanent actions list affected projects and require confirmation; their files, design histories and related management undo records are removed. Other projects and shared libraries are retained.

If project home reports that the service has not loaded project management, quit the app from the tray/menu bar and reopen it. Refreshing the page does not reload backend interfaces. Delete, move and related actions remain disabled until management loads; use **Retry** to reconnect.

## Recovery and everyday use

External file changes are watched. **Refresh data** refreshes views; browser reload does not upgrade the background service. Switch folders in Settings. Delete sends content to Trash; use **Settings → Trash** to restore it. **History** keeps saved versions and file operations. Emptying Trash permanently cannot be undone.

Files and local history are not a cloud backup. Back up your folder using your preferred tool. LeafLoom does not supply cloud sync or universal Obsidian plugin compatibility.

## Optional AI

See [AI connections](AI.md). Browsing and local retrieval work without an AI subscription or CLI. A configured external AI service may receive selected content. AI note suggestions enter a reviewable draft and require manual saving; managed design edits apply directly and can be undone in project history.

## Optional Feishu / Lark connection

1. Install, configure and log in to [official lark-cli](https://github.com/larksuite/cli) separately. Its credentials stay with the CLI.
2. Open **Settings → AI connections → Feishu / Lark**, enable integration, optionally enter a native executable path and CLI profile, then save and select **Verify connection**. A blank path uses automatic detection.
3. In **MCP access permissions**, enable Feishu reading and, if wanted, writing separately for local AI clients and Tunnel. Copy the dedicated local connection configuration when first enabled; refresh the client's tools after a backend update.

4. Ask your AI client to inspect the installed CLI help and embedded Skill, then use the generic read/write tools for documents, Base and other business commands. Block edits support XML headings and rich structure. Document updates need the revision returned by reading. A verified account does not guarantee access to every resource.
5. High-risk commands and raw API calls require the separate local/Tunnel **high-risk** switch (off by default), plus explicit confirmation of each operation. Turning off read or write also turns off high-risk access.
6. Transfer attachments with temporary file IDs and chunked upload/download. Importing an existing connected file additionally needs note-read permission. After upgrading, refresh the client tool list: the four previous document/Base tools are replaced by CLI discovery, read/write execution and file transfer.

Tunnel conversations share the permissions configured for that Tunnel connection. LeafLoom authenticates its runtime separately from a conversation's connector bearer; changing chats does not require a permission refresh or reconnect. Disabling a resource still revokes access immediately.

Dev and the installed app use the same saved Tunnel configuration and application lifecycle: connect on startup when enabled, stop on Quit. Dev reuses the registered installation's runtime when available. One shared-directory owner is allowed; do not also run a standalone tunnel-client for the same connection. MCP authorization errors identify `leafloom_mcp`; they do not require Feishu reauthorization. For Base tables, use an ID returned by the table list, rather than an unverified URL query value.

Connection status distinguishes missing/incompatible CLI, missing configuration/login, expired login and network problems. Complete setup or reauthorization externally, then verify again. Cloud operations need network access and return requested content to the calling AI. They do not automatically import or index it in your local knowledge base. See [capabilities and limits](../FEISHU.md).

## Frequently asked questions

**Why are there no search results?** Check the selected folders, file extensions and exclusions. Check indexing in Settings. If the semantic model/index is not ready, the app reports a keyword/Wiki fallback. Do not treat that as completed semantic indexing.

**Do I need to download a model before starting?** No. The desktop package includes its private runtime; reading, editing, graphs and keyword search work without BGE-M3. Download the model from search settings only when you want semantic retrieval. Source installations prepare their dependencies separately.

Model preparation shows the current connection, download and verification stages in Settings → Search & index and in setup. Downloaded file counts, received bytes, speed and elapsed time update in place. After 30 seconds without progress, a waiting hint appears; failures retain details and a retry button. Close Settings to keep reading while preparation continues; quitting the app interrupts it. Retrying reuses available downloads. Once the files are ready, indexing has its own progress.

The model section also shows the actual storage path. Select **Open folder** to view it in your system file manager; if it does not exist yet, an empty folder is created without downloading the model.

**Where is my data?** Notes remain in the connected folder. Indexes, history and Trash are in its `.vault-rag/`. Private configuration, models, tokens and AI history are in `%LOCALAPPDATA%\VaultRag` on Windows or `~/Library/Application Support/VaultRag` on macOS. `VAULT_RAG_HOME` can override the private location.

**Does it work offline?** The installed desktop app supports local reading, editing, graphs and keyword search offline. Semantic retrieval also needs the local model prepared first. External AI depends on the chosen provider's network requirements.

**The page is blank or changes do not appear.** Complete the frontend build/install, restart the service, then reload the page. Check the service logs and port conflicts. Restarting a browser alone does not load new server code.

**Can I use a network folder?** The desktop app expects a local folder. UNC shares and symbolic-link/junction access are rejected to keep file operations inside the connected folder.

**How do I uninstall?** Quit LeafLoom, then uninstall it through Windows Settings or remove it from Applications on Mac. Notes, configuration, indexes and models are retained. For a legacy source-installed service, use `vault-rag service uninstall` from that environment. Remove retained data separately only when you no longer need it.

## Full note and design access from AI clients

In **Settings → AI connections**, enable full MCP reading for your local AI client or ChatGPT. Enable each connection's write switch separately to allow direct saves with history and recoverable deletion. Clients can edit connected Markdown/TXT/HTML and designs. Managed projects use `design_document`, `design_operations`, `design_history`, asset import, shared-library and export tools; the six legacy design tools remain available. RAG still uses only selected folders. Older connections retain their original five read-only capabilities. See [AI setup](AI.md), the [tool contract](../MCP.md) and [Design Studio](../DESIGN_STUDIO.md).

Dev and the installed app use the same MCP address and access settings (normally `http://127.0.0.1:18080/mcp`). After upgrading the server or changing its dedicated credential, reload the local client connection and refresh the ChatGPT plugin tools. A cached session can still report legacy access even when a fresh connection has full access; check `vault_index_status.capabilities` as well as the tool list.

## Start from the FORMA template

Folder clicks only select and expand a parent folder; they never create a project. Review the selected parent path and the complete new-project path, enter a single new folder name, and choose a template before clicking **Create and open Design Studio**. Enter in a name field, Cancel, and closing the dialog do not create files. While creation is pending, fields and repeated creation are disabled. Existing project folders are opened from the project list, not recreated.

Open **Design projects → New design project**, choose **FORMA · Editorial Studio**, then enter a project name and a new folder. The preview shows its editorial layout. Creating it opens an independent, editable project with four desktop/mobile artboards and 328 native layers. Text, layout, colors, interactions and original CSS artwork can be edited and saved normally. All artwork is bundled; no external asset download is needed. Existing folders are rejected rather than overwritten: choose a different folder name. Each creation has its own project ID and history, so edits never change the built-in starter or other copies.

### Everyday visual editing

Drag on empty canvas space to select a region; Shift adds to the selection. Arrow keys nudge selected free-positioned layers by 1 px, or 10 px with Shift. Dragging shows nearby alignment guides; use the alignment and equal-gap controls for a precise arrangement across nested containers. Multi-selection resize acts on the selected group. Layout children are reordered within their parent instead of receiving free-position offsets.

The inspector groups relevant properties by object. Mixed values are shown as mixed, and editing a shared field applies to the selection. Choose Fixed, Hug content or Fill parent separately for width and height. Row/column layouts expose wrap, alignment, gap, per-side padding and minimum/maximum sizes. Fill requires a layout parent with available space; use a fixed outer width and hugging height for a text-heavy card. Test long copy and narrow widths before exporting.

Typography includes weight, line height and letter spacing. Appearance exposes stroke, shadow and gradients; image controls offer cover/contain plus crop-position sliders. Save named color, typography and spacing styles, apply them to several layers and update the linked definition. Local overrides stay explicit; detach a style when a layer should keep its own appearance. FORMA includes named brand styles and recognizable content layers for rebranding.

Component instances expose editable content, color, image and state properties for their source layers. Overrides remain local while unchanged properties inherit the master; Reset removes an override so inheritance resumes. Review the separate retained, converted and unsupported import notes. Arbitrary JavaScript listeners and live runtime state are not reconstructed. Save errors retain pending operations; retry the original operation for connection failures, or deliberately reapply against the newest revision after inspecting a conflict. Export only once the saved indicator is confirmed.


## Play with Motion Playground

Choose **Motion Playground** in **New design project**. The self-contained starter demonstrates two editable approaches: native **Animation** settings for staggered entrances, hover/focus feedback and click bounce; and **Script** modules for pointer tilt and click-driven state. Select the named example layer, adjust its Animation settings or open its readable `mount(ctx)` source and parameters, then use **Preview**. Editing mode pauses motion. The guide explains each example; a narrow artboard makes the touch layout easy to inspect.

There are no external dependencies or automatic endless effects. Preset motion honors the operating system’s reduced-motion preference, including changes during preview; hover examples also respond to keyboard focus and touch. Scripts provide click/touch alternatives and clean up through the runtime context and their returned cleanup function. Changes save with the project and run in the exported HTML ZIP. The picker illustration is static, not an animation recording.

## Switch between editing and preview

Choose **Preview** at the top of the workbench to play the current page’s animation, scripts and navigation without exporting a ZIP. The workbench commits active text input and waits for pending saves first. If saving fails, your changes remain queued and editing stays open with retry guidance, rather than showing stale content. Preview hides layers, properties, selection outlines and handles. Use **Preview page** to switch existing artboards, including desktop/mobile layouts included in a template, and **Replay** to restart the current page. **Edit** or **Back to editing** restores the page, selected layers and canvas position from before preview.

## Reuse content and publish page variants

In Design Studio, open the inspector's **Data** tab. Bind a text, button or image
to a stable key, create a language or general variant, and edit its values. Images
share existing asset IDs. Source changes mark older translations for review;
variant layout overrides adjust text boxes and page dimensions without replacing
the source. These edits use normal save, undo and conflict recovery.

Open **Batch publish**, select pages and variants, check the explicit dimensions,
and run the output check. Export PNG images in a ZIP or one multi-page PDF. The
current-canvas check locates overflow and font/resource risks. Prefer editing the
content or box; bounded text fitting only runs when explicitly clicked and obeys
a minimum font size and reduction limit. Glyph/fallback detection is not a full
font audit. Failed export items can be retried from the same saved snapshot.
Desktop uses its built-in renderer; web/headless hosting needs the optional
publishing dependencies. Interactive preview and the original HTML ZIP export
remain available. See [publishing details](../DESIGN_STUDIO.md#bound-content-variants-and-static-publishing).

Bindings and variants belong to their project. Shared-library component publication freezes source content and removes its project binding links; imported components can be bound to keys in the destination project.

### An editorial starter and a focused publishing workspace

Choose **ATELIER** when creating a project for a three-artboard lighting campaign with editable type, original sculptural artwork and complete English, Chinese and Japanese variants. Use **Data** to edit bound source copy or switch variants; retain the general-purpose blank, FORMA and Motion starters for other work.

The workbench separates editing tools from Export and Publish. Page reorder, duplicate and delete controls are grouped under **Page actions** in the page inspector. Batch publishing keeps its action bar visible while you choose pages, variants and format. Review the output summary, run the selected-output check, then publish. Completed items use compact expandable rows; failed items expand their diagnostics. Text fitting limits and shared check limitations remain available in disclosure sections. Static export checks do not replace visual review of fonts and layout. Use the canvas toolbar’s **Hide panels** control for more canvas space on a narrow window; **Show panels** restores the previous inspector and layer selection.
