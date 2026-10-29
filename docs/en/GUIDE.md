# Your first steps with LeafLoom

[What changed in 0.1.5 and how to upgrade](RELEASE_NOTES_0.1.5.md)

Use **Settings → Skill** to install or update the bundled `wiki-search` skill.

[English](GUIDE.md) · [中文](../zh-CN/GUIDE.md) · [日本語](../ja/GUIDE.md)

[All documentation](../README.md)

## Help center

Open **Help center** in the app sidebar or [visit the online help center](https://dj-huang.github.io/LeafLoom/docs/en/). Browse task topics or search full article text with `Ctrl/⌘+K`. Articles include steps, expected results, troubleshooting, contents and previous/next links. Language switching retains the task and its standard section. Examples can be copied and screenshots enlarged; topic browsing and articles also work without JavaScript. Help search covers public documentation only and never reads your vault.

## Install and open

**Developers:** In a source checkout, double-click `Dev.cmd` on Windows or `Dev.command` on macOS 14+ Apple Silicon; on Mac, `sh Dev.sh` also works in Terminal. Run `chmod +x Dev.command Dev.sh` once if a copied/downloaded checkout loses execute permissions. You can also run `node scripts/dev-desktop.cjs` on either platform. Requires Node 22+ and uv; the first launch installs dependencies. The desktop runs directly from source and frontend edits update automatically. Dev shares the installed app's settings, models, credentials and desktop data, including its configured backend port (18080 by default). Only development dependencies stay in `.cache/desktop-dev/.venv`; Vite uses port 5173. Quit the running app before switching modes. For isolated testing, explicitly set a disposable `VAULT_RAG_HOME`. After Python/Electron edits, use **LeafLoom → Restart LeafLoom** or the tray menu’s **Restart LeafLoom**. See [source development](../DESKTOP.md#source-development).

On macOS, launching through **Dev.command** or **Dev.sh** also shows the LeafLoom logo and name in the Dock. Use **Restart LeafLoom** to reload desktop source and branding changes.

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

Closing the window keeps LeafLoom in the tray/menu bar; use **Quit** to stop the application and its local service. **LeafLoom → Restart LeafLoom** and the tray’s **Restart LeafLoom** close and reopen the app with the same settings and data directory. Restart prepares note drafts and waits for the local service to stop; an unsaved-content prompt lets you return and cancel. Dev keeps Vite running and synchronizes locked Python dependencies before opening the current source again. When first updating from a version without this menu, quit and launch Dev manually once. Login startup is off for new installations and can be changed in desktop settings or the tray. To update, open **Settings → General → App updates → Check for updates**. The current and latest versions are shown. Choose **Download and install** to see the percentage and downloaded/total size. After SHA-256 verification, LeafLoom quits normally (including unsaved-draft prompts) and opens the Windows installer or Mac DMG. Complete the installer; on Mac, drag the new app to Applications. Reopen LeafLoom afterward. A canceled quit leaves **Continue installation** available. Failed requests/downloads can be retried. Dev only checks versions; update the source and restart Dev.

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

Hover beside a block to insert with **+**, or use its handle to convert, duplicate, move or delete it. Drag the handle to reorder paragraphs, list items or whole blocks. Select text across paragraphs and type directly in table cells. Tab moves between cells and adds a row from the last cell; the table toolbar manages rows, columns, the header and alignment. Paste screenshots or drop files into the editor: attachments go in the vault's central `_attachments` folder (or configured `attachment_folder`) with unique names. Uploading does not replace existing files; undoing the inserted link keeps the uploaded file. Failed or cancelled uploads may leave completed files in that folder.

Files remain ordinary Markdown; unchanged blocks and document properties retain their original source. The page and source views share undo history. Equations and Mermaid stay rendered and have dedicated editing panels. Complex or unsupported content is preserved for display and can be located in source. Changing the interface language keeps the editor and its history. Tables use simple Markdown structures, without merged cells or nested blocks inside cells.

## Text highlights and comments

In a Markdown document, select text to reveal five **highlight** colors and **Add comment** in the floating formatting bar. Choose a color to mark a passage. To restore plain text, select highlighted text and choose **Clear highlight** (the slashed circle before the colors), also available in the context menu. Only the selected highlight is removed; outside portions and comments remain. One clear action is one undo/redo step. Click comment (or press `Ctrl/⌘+Shift+M`) to begin a thread. Use the toolbar's **Comments** button to see the right panel, add a **Page comment** without selecting text, reply to threads, edit your messages, resolve/reopen, filter or delete.

Click a quoted snippet to jump to the original passage. Comments try to follow moved text using the quote and its context; deleted or ambiguous quotes are flagged **Text no longer found**, so you can select a new range and **Relink to selected text**. The same decorations appear in Markdown source mode without modifying Markdown syntax. Highlights and comments share the page/source undo history: use the toolbar buttons or `Ctrl/⌘+Z` to undo and `Ctrl/⌘+Shift+Z` (or `Ctrl+Y`) to redo. Creation, deletion (including replies), message edits, resolve/reopen and relinking can be reversed in order with text edits during the current session. Comment input fields keep their own text undo. If another window or MCP changed a thread, undo/redo stops without overwriting it. Normal unsaved edits must save first; AI manual drafts must be saved explicitly.

Highlights and comments are **user data**, not a disposable index: back up `.vault-rag/annotations.sqlite` alongside your notes. When moved or restored through LeafLoom, note comments retain their identity. The first iteration supports annotated Markdown (the API also supports plain TXT); HTML projects and Design Studio are not yet covered. See [annotation architecture](../ANNOTATIONS.md).

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

Enable the Feishu connection in Settings and authorize the required Miaoda app permissions first. In Design Studio, choose **Publish to**, then **Miaoda**, select pages and create a course app or associate an existing Design Studio course app by app ID. Association checks the course identity and remote files; unrecognized changes pause the operation and cannot be bypassed by reassociating. Publishing replaces that app’s course with the selected pages; existing access settings are preserved. A new app first publishes an empty shell. Course content is uploaded only after organization access is confirmed, so two approvals may be required. The saved revision, assets and scripts are packaged into a background job. Missing links, dynamic references, authorization and approval requirements are shown in the dialog. If a job stops after an uncertain operation, inspect the app before acknowledging it or continue only after asset verification.

- The project home offers search, recent/favorite projects, rename, copy, move, archive and a recoverable recycle bin. Workspace undo/redo covers project management; project history covers design edits across pages and restarts.
- Use **Pages** to add, group, reorder or duplicate screens. Insert text, images, containers, buttons, shapes, SVG, custom HTML, embedded pages, or game starters such as a HUD, character card, gallery and dialog. Select layers, Shift-select several, then use the canvas and inspector for position, size, rotation, text, appearance and row/column/grid layout. Child pages and component instances retain separate identities.
- Upload or paste artwork in **Assets**. Inspect dimensions/transparency, set names/categories/tags, locate uses and replace one image or all references. Publish components and assets to the personal shared library; import a newer version explicitly. Dependencies are copied into the project for offline use. A referenced asset cannot be removed until its uses are replaced or deleted.
- The **Animation** inspector offers fade, slide, scale, bounce, breathe and spin. In **Scripts and source**, attach `mount(ctx)` JavaScript to an element or page and expose parameters as inspector controls. Scripts pause during editing. Preview a component or the whole screen, then stop to restore the design state; logs identify the affected element. Source changes and parameters share the same undo history.
- **Send to AI** includes stable element IDs and the current revision. Managed design edits apply directly and one AI batch is one undo step. `Ctrl/⌘+Z` undoes and `Ctrl/⌘+Shift+Z` redoes, including after closing and reopening. Save conflicts retain pending changes; inspect them before choosing reload/reapply. Export after pending saves finish, unzip the result and open `index.html` with its companion files.

- HTML conversion retains document-root context, native mixed text and responsive image candidates. Unreadable external stylesheets are omitted with a warning; original source remains intact. Viewport/rem units and media queries still use the renderer environment. Native text runs expose content editing; select their parent for layout and typography. Compare the converted page with its original before relying on it.

- Navigate the canvas with **Select** (`V`) and **Hand** (`H`), or hold Space while dragging. Use the zoom percentage, +/−, fit page (`Shift+1`) and fit selection (`Shift+2`); Ctrl/⌘+wheel zooms around the pointer. Camera position stays steady while editing. Expand/collapse containers in **Layers**, use the selected-layer breadcrumb to reach ancestors, and edit grouped **Layout**, **Appearance** and **Typography** properties. If the isolated canvas cannot connect, use its retry action; the management shell can still show saved layers and properties.
- **Convert a copy** preserves the original project and imports authored DOM/CSS, text and assets, adapting recognized navigation, settings switches and context-dependent page states. Original scripts remain in the copied source; other legacy event handlers and runtime state need new scripts. Review conversion notices and compare the copy with the original before replacing a workflow. See the [workflow and script API](../DESIGN_STUDIO.md) for commands, import limits and performance acceptance targets.

For AI media import, prefer `design_import_asset` with a connected-vault `source_path` or a `source_file_id` returned by the Feishu CLI. Videos stay on the service machine instead of making a Base64 round trip through the AI connection. Request `include_document:false` for a small receipt. Imports keep size/hash checks, current access permissions and undo history; paths outside the connected vault are not accepted. See the [MCP examples](../MCP.md).

MCP note saves return `saved:true` and the committed revision after the file and history are written. Catalog, attachment metadata and search indexes update in the background; `index_pending` describes search indexing, not an unsaved file. Exact-path reads and further revision-checked edits remain available while metadata is preparing. Global queries may briefly return `metadata_pending`; retry those reads rather than repeating a successful save. Restart LeafLoom to load backend fixes; the built-in restart flow handles local drafts.

To sync a design between computers, close LeafLoom on the sending computer, sync the entire project folder (including assets) and its `.vault-rag/design-studio` history, and wait for sync to finish before opening it on the receiving computer. Keep the same project path within the vault; the vault root may differ between Windows and Mac. Use the fixed version on both computers and edit on only one at a time. Opening does not rewrite history ownership, while duplicate project IDs in different folders and external content conflicts remain blocked. Use the project home’s **Copy** action for an independent copy.

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

Design MCP reads now open with small, paginated summaries (20 entries by default). Use `page_id` for element summaries and `section` for asset/component/style/script lists; use `full=true` with the needed page/node or resource ID to fetch exact source. Follow `next_offset` with the returned `revision` as `expected_revision`. Design edits, undo/redo and imports return short receipts; `include_document=true` requests their former full response. `design_get_project` also defaults to a compact managed view. The complete document remains available through `design_document(full=true)` without selectors. Restart the updated backend and refresh client tools; the built-in assistant uses the same defaults. See [MCP read options](../MCP.md).

The same workspace read/write grants now include attachments. After restarting the updated backend, refresh the tool list in the AI client you use; refresh the LeafLoom ChatGPT plugin only if you use that connection. `vault_files` searches metadata, returns file versions and Markdown links, reads original bytes, prepares ZIP downloads and checks tasks. `vault_files_update` uploads chat files or local byte chunks and prepares move/rename, trash or organization plans. Read the plan, then explicitly execute, resume or undo it with its current revision; later edits are never overwritten. Uploads go to the configured attachment folder, preserve duplicate names and do not edit a note automatically. Chat file uploads run in the background; inspect task results before retrying failed files. See the [file tool contract](../MCP.md#general-file-tools).

In **Settings → AI connections**, enable full MCP reading for your local AI client or ChatGPT. Enable each connection's write switch separately to allow direct saves with history and recoverable deletion. Clients can edit connected Markdown/TXT/HTML and designs. Managed projects use `design_document`, `design_operations`, `design_history`, asset import, shared-library and export tools; the six legacy design tools remain available. RAG still uses only selected folders. Older connections retain their original five read-only capabilities. See [AI setup](AI.md), the [tool contract](../MCP.md) and [Design Studio](../DESIGN_STUDIO.md).

Dev and the installed app use the same MCP address and access settings (normally `http://127.0.0.1:18080/mcp`). After upgrading the server or changing its dedicated credential, reload the connection in the client you use. If you use ChatGPT, refresh its plugin tools too. A cached session can still report legacy access even when a fresh connection has full access; check `vault_index_status.capabilities` as well as the tool list.

## Attachment manager

### Attachment servers and automatic sync

While scanning, the toolbar shows directories scanned and pending and refreshes every two seconds even with Sync status closed. The dialog retains discovery counts after a failure and explains connection-establishment timeouts, response timeouts or interrupted reads in plain language, with the failed-attempt time and next connection retry when available.

Temporary metadata connection failures show an automatic-retry message with the previous connection issue collapsed. An active retry displays **Reconnecting…**, then **Connection restored; syncing metadata** after a verified metadata response, even if there are no queued uploads. Old red errors disappear while that retry runs and after success. Authentication, authorization and invalid-response errors remain visible. Reconnection wakes metadata sync without waiting for the full attachment scan; retries retain the last successful-sync time.

Background scan notifications are coalesced while a list request is in progress, so large catalogs can finish loading. If reading takes over 20 seconds, existing rows remain visible and an error offers Retry; failed cold loads do not spin forever or claim that attachments were deleted.

Open **Settings → Attachment servers** and add a connection. Enter the address, account and password, then **Save and connect**. WebDAV uses an HTTP(S) service address; SMB uses `smb://host/share/subfolder` or a Windows shared-folder path. SMB2/3 uses explicit account/password authentication, not a system mount or the current OS login. DFS referrals and reparse paths are not followed. Public WebDAV requires HTTPS; numeric private/local HTTP addresses remain supported. No server brand is required. Existing profiles, roots, upload directories and metadata bindings are retained.

Each card offers **Edit connection**, enable/disable and **Use for new attachments**. The first server in a new configuration becomes the upload destination. Changing that destination affects future uploads only; it does not move originals or change an existing metadata-library binding. Notes stay in the local vault. New servers use `Incoming` for uploads and `Incoming/LeafLoomCatalog/v1` for metadata. Preview cache and upload-queue limits retain their existing values. Download capacity remains in Download settings.

Directory discovery starts after startup credential recovery, a successful connection or reconnection, then checks again five minutes after completion. Automatic scans run one server at a time. Metadata, groups, covers and attachment references synchronize in the background; originals download only when requested. A failed/incomplete scan preserves existing records. Authentication failures pause until credentials are updated. Sync stops when the app fully exits and resumes on its next launch. Desktop passwords remain system-encrypted; browser passwords remain in backend process memory. Existing official-client bridges retain their connection behavior and still require the official client to remain available.

Discovery now journals each completed directory on this device. After a network interruption or app restart, the unfinished pass reuses those directories and continues the remaining work. Later automatic checks reuse directory listings for ten minutes and independently revalidate expired child directories, even when their parent is cached. Each server uses at most two directory readers. The Sync status dialog identifies the initial, incremental or resumed pass and shows how many directories were reused. **Sync now** uses this same cache; **Check all directories** bypasses it to verify additions, changes and deletions immediately without downloading originals. Failed passes never mark files missing; deletion still needs a completed pass and a not-found check. Changing the vault, address, account, credential version or metadata namespace invalidates the old checkpoint. A first baseline is necessary after upgrading from a version without directory checkpoints.

Servers without a WebDAV change feed cannot report every nested change without directory queries. Parent timestamps and ETags are not used to skip expired descendants, so this fallback provides periodic reconciliation rather than an immediate server change stream. Unchanged file records are not rewritten, and cached listings do not roll back newer file metadata obtained when opening or uploading an attachment.

The attachment toolbar contains **Attachment overview**, **Sync status** and **Attachment information**. Detailed statistics and synchronization details appear on demand. The information panel starts collapsed and remembers your preference. Closing it keeps the selected file. Unsupported formats show an existing cover with an expand action, without downloading the original; missing/broken covers show a file icon and download action. Background updates preserve selections, filters, scroll and metadata drafts. If a paged snapshot expires, **List updated — show latest** loads the latest first page on request.

Selecting a group changes the page heading and loads only that group. During an explicit group/source/search change, the previous list and counts are cleared while the new scope loads; a failed read shows Retry instead of displaying the previous group under the new tab. Background synchronization continues to preserve the current list and drafts, and local index progress updates do not cancel an in-flight group request.

**Create and import** is in the file directory actions and sidebar, using the selected directory. It contains file/folder creation, import and template creation. Attachment uploads remain in Attachments. Migration and organization entry points are removed; uploading, downloading, renaming and recycling remain available. File changes retain their reference checks and confirmation.

If listing a directory times out during a scan, LeafLoom retries it up to twice. If the timeouts persist, the scan stops and retains existing records; check the connection or server load before refreshing again.

The server root and each subdirectory may contain a visible `leafloom.ignore`. It supports Gitignore-style paths, globs, `#` comments and `!` reinclusion; child-directory rules can override ancestor rules. Scanning always visits subdirectories to read their rules rather than applying Git's excluded-parent directory pruning, so child rules can reinclude files excluded by an ancestor. The defaults exclude `.md`, `.markdown`, `.base`, `.html`, `.htm` and script/source-code files; `!` can also override these defaults. `.txt`, `.json`, binary and design resources remain included. Edit rules through the NAS file manager: LeafLoom reads them without requiring Dufs write permission. Refresh the server directory after changes. Only a complete successful scan hides excluded entries from attachment lists, metadata searches and size totals. Exclusion does not delete NAS originals or mark them missing: existing asset IDs, tags, old references and cache remain, and old IDs/references can still read the original. Rule read/parse failures do not partially hide existing records under the new rules; correct them and refresh again.

Save the file as UTF-8 (an optional BOM and CRLF are accepted). Its first line must be exactly `# leafloom-ignore v1`, with no blank line before it; an absent or invalid header stops the refresh instead of treating an authentication/error page as rules. Each file is limited to 64 KiB, 2,048 lines and 2,048 characters per line. Copy this template to the root or a subdirectory and adapt its rules:

```text
# leafloom-ignore v1
# Exclude temporary files under this directory
*.tmp
# Reinclude this Markdown file as an attachment
!reference.md
```

### Attachment groups, source metadata and downloads

Attachments opens **All attachments**, with no store-specific or format-specific tabs. Use **New group** to create your own tabs, rename them, move them left or right, or delete them. Groups are separate from attachment categories. A file may belong to several groups; deleting a group never deletes files or metadata.

Groups support manual membership and rules for source, directory, format, category and tags. Conditions are combined with AND; values within a condition use OR. Directories include descendants and format matching ignores case. Select files and choose **Groups** to include, exclude or reset overrides. Results are rule matches plus manual inclusions minus manual exclusions. Source, search, format and sort controls remain available.

Definitions and persistent member identities are saved in the vault and automatically replicate to the bound metadata server under `attachment-groups/events/`, excluded from attachment scans. New connections use `Incoming/LeafLoomCatalog/v1`; existing bindings are preserved. Offline changes survive restart. Concurrent group edits preserve both versions for explicit resolution in the group editor. Unavailable local files from another device retain membership without binding to same-named files.

Existing source descriptions and official covers appear on their linked attachments. Files remain individual entries, with no product grouping or automatically created category tabs. Personal fields remain separate: nonempty personal description/category take precedence, while personal tags and source keywords are searchable together. Source refresh never overwrites personal fields. Missing covers receive no generated substitutes. Existing catalog associations and legacy MCP interfaces remain compatible; source-specific collectors are optional adapters.

The sidebar **Downloads** page lists remote attachment downloads and local ZIP tasks. **Download attachment** streams a remote original into verified staging. **Ready to save** means staging is complete; select **Save to device** to save a copy. Tasks continue while navigating and records recover after restart. A single local file downloads directly without extra staging. Legacy ZIP jobs retain their one-hour expiry and must be restarted after interruption.

**Download settings** controls the separate **20 GiB** remote staging budget, independent of the **2 GiB** preview cache and upload queue, with at least **5 GiB** disk reserve. Controlled handles last 24 hours; prepare expired files again. Staging follows capacity and seven-day retention rules while protecting active transfers. **Clear staged file** removes only the local temporary copy. Strong validators enable the existing resume behavior; other transfers restart completely.

For AI/MCP, `vault_files` supports `groups`, `list` with `group_id`, source-enriched `stat`, `prepare_download` and `download_status`. `vault_files_update` uses `group_update` for group and membership edits with revision checks and write authorization. Read-only connections cannot edit groups. Legacy `products`, `product` and `product_update` remain compatible. Full attachments are delivered through Downloads rather than MCP Base64 chunks.

#### Batch collection script

Some official pages omit JSON-LD. Collection can still read the official structured product and publisher entities when their IDs agree; a title or preview image alone is insufficient.

With LeafLoom running and the catalog configured, run the repository's [collection script](../../scripts/collect_unity_catalog.py) against the same vault:

```sh
python3 scripts/collect_unity_catalog.py --root /path/to/vault --start --wait --interval 10 --report /path/to/collection-report.json
python3 scripts/collect_unity_catalog.py --root /path/to/vault --status --report /path/to/status-report.json
python3 scripts/collect_unity_catalog.py --root /path/to/vault --apply-chinese /path/to/chinese.json --report /path/to/chinese-report.json
```

The script controls the local backend; it does not automate a browser, use store-account cookies or download package originals. Collection resumes the backend's saved progress, preserving completed review-needed judgments after interruption while retrying blocked access and network failures. Background synchronization coalesces repeated scans and resumes pending uploads before checking the remote catalog when a verified checkpoint is available; first-time or explicit synchronization still checks the remote catalog first. Stopping the monitor with Ctrl-C does not cancel the backend task. `succeeded` counts obtained official facts, not completed Chinese summaries; check Chinese summaries and translation status separately. A reported `legacy_unresolved` count is unverified work from an older checkpoint without sufficient identity data, not a success count; reconcile complete progress with the package inventory. Chinese input updates only supplied official translation fields and preserves personal tags and notes. See the [input format and connection options](../MCP.md#batch-script).

### File-operation recovery

Migration and organization are deferred; existing journals remain available for recovery. Rename, move and recycle operations still check versions, access and references before confirmation. Recovery data remains in `.vault-rag/attachment-migrations/<job-id>/`: `manifest.json` records the task, `originals/` contains original attachments and `notes/` contains note backups. Recycled files remain in `.vault-rag/trash/`. Keep these files while recovery is needed.

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

In **Preview**, choose **Present full screen** to hide the application chrome and fit the entire artboard to the screen without stretching. The current interaction continues without restarting. Move the pointer to the bottom to show page controls and **Exit full screen**, or press **Esc** to return to ordinary preview. You can then return to editing as usual. If native full screen is unavailable, presentation still fills the application window.

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

## Upload images and ordinary attachments over MCP

Use `vault_files_update` with `request.action="upload"` for knowledge-base attachments. ChatGPT should prefer `source="files"` with the host-provided top-level `files` array. Local clients can send one file up to 2 MiB with `source="base64"`, `name`, `data_base64`, and the original bytes' `sha256`; use begin/chunk/commit for larger files. Omit `folder` for the configured attachment directory, or specify a vault-relative directory such as `Comics/Project/assets`.

Read `workspace_revision` from `vault_index_status` and use a unique `operation_id`; keep the ID unchanged when retrying identical arguments. Upload results include the saved path, size, SHA-256, revision and `markdown_link`; images also return `markdown_embed`. Use `vault_files` stat with `source_note` to obtain a note-relative reference, then edit the note with its current revision. Existing files remain intact.

If only Design Studio import or Feishu temporary transfers appear, check the server's `tools/list`: it must include `vault_files` and `vault_files_update`. Restart an updated backend and refresh/rescan the client's plugin tool directory. Restarting LeafLoom alone does not refresh a cached client directory. Check workspace-write permission separately; these uploads do not require Feishu authorization. See [MCP file tools](../MCP.md#general-file-tools).

The single-request Base64 path requires a build containing this change.


### AI asset search and delivery

Before searching, enable **Use for AI asset search** in each desired attachment group. All groups start off; only the selected groups’ union enters keyword/semantic retrieval, and no selection returns `scope_not_configured` without a full-library fallback. This choice syncs to NAS with group metadata. Conflicted groups are excluded until explicitly resolved. Normal attachment browsing and note references remain available.

In **Downloads → Download settings**, set the **Asset delivery directory** and optionally enable semantic asset indexing with your prepared local model. AI can search existing local/NAS assets through `vault_files` actions `search_assets`, `asset_details` and `asset_preview`, then use `vault_files_update.deliver_asset` and poll `delivery_status`. Only completed deliveries return an absolute path on the identified service computer. Delivered files remain independently of cache cleanup; the calling AI handles project integration. Keyword search works without a model; package contents and visual similarity are not indexed.

## Present with a second display

In the desktop app, open **Preview → Presenter mode**. Select the audience display, use **Identify displays** if needed, then start. A single display offers a separate rehearsal window. Projects with page groups start with the current group; choose **Present all pages** to include the rest. **Swap displays** exchanges the audience and controller during playback.

The presenter console contains a resizable live operation preview and private speaker notes. Click, drag A/B sliders, scroll, select cases and control videos in the preview: only the audience window plays the media and produces sound. **Next step**, Space and Right advance registered talking points, then the next page; Left reverses. An expanded demo closes before advancing. Page buttons and the directory jump directly. Projects without a presenter adapter navigate by page.

Notes contain an overview and sections keyed to stable step/case IDs. Read or edit them, adjust text size, and follow the current point. Scrolling or editing suspends following; **Resume following** restores it. Parameter changes update the status without scrolling. Notes autosave with project revision checks and undo history; a failed save retains the local draft. Saving notes never reloads the audience's frozen presentation snapshot.

**Blackout** pauses and mutes media. **Restore picture** keeps it paused until **Resume playback**. A disconnected display or controller pauses and hides audience output; reconnect a selected display before continuing. **End presentation** closes the audience window and returns to the previous editor page, selection and camera. Notes stay in project copies and history, and are excluded from audience documents, HTML ZIPs and static publishing. macOS is the first acceptance target; Windows hardware verification remains separate.
