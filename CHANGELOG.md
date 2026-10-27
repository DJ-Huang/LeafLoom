# Changelog

[English](CHANGELOG.md) · [中文](docs/zh-CN/CHANGELOG.md) · [日本語](docs/ja/CHANGELOG.md)

## Unreleased

- Reduce Design MCP output with paginated summaries, exact page/node/resource source reads, revision-pinned pagination and compact edit/undo/import receipts in public MCP and the built-in assistant. Keep explicit full-document options and HTTP editor behavior. Reuse revision-local inspection indexes and encode public MCP JSON off the event loop with compact formatting and duration/size logs.

- Add desktop dual-display presenter mode with one isolated audience renderer, bounded live preview and focus-preserving input, private editable notes, step/case navigation, blackout/reconnection and immutable presentation snapshots. Notes use normal revision/undo history and stay out of audience and export outputs.

- Add full-screen Design Studio presentations with proportional artboard fitting, unobtrusive page controls, Esc exit and a window-filling fallback. Keep interactions running and restore the existing editing position when preview ends.

- Fix a save-receipt deadlock between note writes and background catalog/attachment updates. Acknowledge committed files and history immediately, queue metadata updates, and keep later MCP calls and editor saves available without weakening revision or permission checks.

- Add server-side design asset imports from connected-vault paths or credential-scoped Feishu temporary files, avoiding large Base64 MCP requests and repeated byte transfers. Optional compact receipts omit the full document; preserve existing defaults, source/hash checks, access boundaries and undo history.

- Keep both local and server attachments visible when switching the new-upload destination. Separate local catalog readiness from server browsing, preserve exact paths across same-name files, retain peer originals until synced deletion, and clarify offline behavior and folder-sync limits in all three languages.

- Use server attachment catalogs directly when a server is selected, separating local catalog setup from optional organization. Isolate attachment SQLite, settings, caches and transfer queues in device-private application data with a non-destructive legacy snapshot upgrade. Publish verified immutable server references before upload completion or original release; other devices restore old paths and IDs without syncing SQLite. Report conflicting references explicitly and add a one-time legacy-reference sync action.

- Support numeric shared-network VPN attachment addresses (`100.64.0.0/10`), including Tailscale, in the existing private HTTP configuration flow. Keep explicit source opt-in and reject public HTTP endpoints.

- Fix saving older attachment server profiles that omit the metadata-directory field. Address changes now preserve the derived directory and existing credentials instead of failing with a server error.

- Add opt-in, NAS-synchronized per-group AI asset search scope. No selection returns empty results, group conflicts stay excluded, and product details cannot expose out-of-scope package copies.

- Add metadata-only AI asset search with optional local semantic ranking, real image previews and persistent original-file delivery to a configured directory. Completed owner-scoped jobs return a verified path on the identified service host; existing downloads and engine integration remain separate.

- Fix attachment details crashing the entire attachment view when Unity Asset compatibility metadata is an object. Support string, array and object values, including nested data, and omit empty compatibility information.
- Add user-defined attachment tabs with manual/rule membership, vault persistence and verified NAS event synchronization with explicit conflict resolution. Replace the fixed product view with file browsing enriched by existing source metadata and covers. Add a separate Downloads page for staged attachments and ZIP tasks, preserving existing jobs and moving staging capacity into download settings. Extend MCP with group queries and revision-checked edits.

- Support official product pages without JSON-LD when their structured product and publisher identities are verified; continue rejecting ambiguous or inconsistent identities.
- Reuse HTTP clients and verified directory checks during product synchronization to reduce repeated requests; the official-client bridge can use separate connections for compatibility. Retain per-item read-back verification and pending items after failures. Bound parallel synchronization to four small metadata objects, preserving dependency and authorization checks. Reuse a batch snapshot of locally verified events for large-catalog startup/background checks to reduce repeated disk reads, retaining identity, authorization and unverified-event SHA checks.

- Add a local batch script to start/resume official product collection, monitor saved progress and apply partial Chinese metadata with revision checks while preserving personal fields; official collection success and Chinese completion remain separate. Interrupted collection preserves completed review-needed decisions and retries blocked/network failures; background sync resumes pending uploads from a verified checkpoint before its remote check, while first/explicit sync checks remote first.
- Keep the last catalog sync result when normal shutdown interrupts a background check, instead of saving a service error for the next startup.
- Reuse the current transaction for catalog authorization checks to avoid database lock failures with large product metadata, while retaining checks before commit.

- Let official product collection reuse a supported existing macOS loopback HTTP proxy while retaining official-host restrictions, TLS verification and response limits, without changing system settings. Preserve Chinese text on refresh and mark changed source facts for translation updates; keep local product queries responsive while NAS synchronization waits on the network.

- Add an Asset products view for existing Unity packages, separate official/personal metadata, reviewable official URL associations and explicit collection progress. Keep multiple package versions, NAS-backed catalog metadata and independently limited 20 GiB verified download staging; no automatic Unity import or purchase verification.

- Restore saved attachment credentials in the background with asynchronous system-encryption APIs where available, so key-store recovery does not block opening the workspace. Coalesce retries and discard results for retired backend connections.

- Support per-directory server `leafloom.ignore` rules with Gitignore-style patterns, child overrides and `!` reinclusion; require the `# leafloom-ignore v1` first-line header. Successful refreshes report excluded entries and remove them from attachment discovery and totals while preserving IDs, tags, references and cache; rules are read without NAS write permission.

- Add an explicit per-server directory refresh in Attachments, with metadata-only progress and completion. Only complete successful scans hide missing NAS files from lists and size totals; IDs, tags and old references remain, and failed scans retain prior records.

- Show local and server attachment-original sizes separately for all sources, and only the selected source's size when filtered. Local cache is excluded from these totals.

- Add bounded attachment-credential recovery after 1/3/10/30 seconds, unlock/wake retries and status/manual recovery in Settings. NAS network and 502–504 failures back off from 2 to 60 seconds; 401/403 pauses automatic attempts with the same credentials. Health probes touch only configured URLs, existing tasks still check owner/credential revisions, and official attachment windows must stay open without automatic session rebuilding.

- Add an attachment-source dropdown for all, local, server or individual-server browsing. HTTP and MCP lists share server-side source filtering, pagination, storage totals and type counts.

- Add generic multi-server WebDAV attachment storage, system-encrypted desktop credentials, memory-only browser credentials, bounded local cache and a separate pending-upload queue. Add reviewed local-to-server migration with readback verification and stable LeafLoom references, plus editable asset tags/categories/descriptions and source/cache status. Official-client bridges remain dependent on their open attachment window and configured port.

- Add SHA-256-verified, single-request Base64 attachment uploads up to 2 MiB, image embeds in upload results, and discoverable upload capabilities with client tool-directory refresh guidance. Preserve the existing two-tool API, chunk transfers and ChatGPT file inputs.

- Fix Design Studio rejecting projects synced between computers with different vault root paths, including Windows-to-Mac transfers. Preserve document IDs and history ownership on reads, retain duplicate-directory/content-conflict guards, and support synced project moves, restore and trash cleanup.


- Add **Clear highlight** to the floating toolbar and text context menu. Clear only selected highlight ranges, preserve outside colors and comment threads, and undo/redo a multi-highlight clear as one action.

- Support undo/redo for highlights, comments, replies, edits, resolve/reopen, relinking and deletion in the shared rich/source document history. Add toolbar controls and guard replay against concurrent annotation changes.

- Add local-first Markdown text highlights and threaded inline/page comments with reply, edit, resolve/reopen, source decorations, quoted-text reattachment and a right comment panel. Store durable annotations separately from Markdown in per-vault SQLite and preserve comment identity across LeafLoom note moves/trash/restore, including MCP operations. Add explicit permission-gated MCP annotation tools.
- Add a three-language public help center with 39 task guides and four guide/release references per language, full-text search, grouped navigation, article contents, previous/next links, image zoom and copyable examples. Link the website and app sidebar to localized help and publish documentation changes through Pages.

- Add **Restart LeafLoom** to the application and tray menus, preserving draft checks and orderly backend shutdown. Dev keeps Vite running, refreshes locked Python dependencies and reopens the current source; canceling the unsaved-content prompt cancels restart.

- Replace the attachment dialog with a dedicated gallery/list workspace, global filename/path search, filters, sorting and inline media previews. Add one-click setup, clear background progress, safe duplicate-preserving uploads, reference-aware rename/move/recycle with recovery, and asynchronous ZIP downloads; keep project resources read-only and support narrow screens.

- Keep HTML/source projects and their shared resources in place during attachment migration; retain literal dependency directories and configuration references, stop treating engineering binaries as text, and allow independent attachments to migrate with drift checks and rollback.

- Distinguish blocked attachment migration previews from index initialization, localize common blocker reasons, and show displayed/total counts for blockers and exclusions.

- Show the LeafLoom logo and application name in the macOS Dock when launching Dev, using a cached branded runtime.

- Unify attachment index initialization/upgrade and directory migration into one workflow: automatic index preparation, preview, then one confirmation for copy, reference rewrite, recoverable original retirement and final index rebuild. Keep index-only maintenance under collapsed advanced options. Opening the manager remains read-only; HTML projects remain excluded from migration.

- Add explicit, asynchronous attachment migration previews with persisted progress, safety blockers, cancellation, journal-based recovery and confirmed rollback. Preserve original assets and note backups; completed migrations select the central folder for future uploads.

- Add a metadata-only SQLite attachment index and sidebar attachment manager with paginated name/path search, original-file downloads, refresh, cancellation and retry. Keep original files, HTML projects and existing URLs unchanged.

- Avoid duplicate Pages deployments when a GitHub Release is published, and refuse stale latest-version builds until the public Release API catches up.

## 0.1.3 — 2026-10-18

- Refine the Design Studio workbench hierarchy, group page actions, and introduce a focused publishing workspace with persistent actions and expandable results. Add the editable ATELIER lighting campaign with three artboards and complete English/Chinese/Japanese variants.

- Add stable text/image data bindings, reviewable language/general variants, per-variant layout overrides, text/resource preflight and bounded fitting, plus selected-page/variant PNG ZIP and multi-page PDF publishing with progress and retry. Preserve interactive HTML export and undo/conflict protection.

- Add an explicit Edit / Preview switch with a distraction-free interactive canvas, page picker and replay. Wait for the latest edits to save before preview, retain failed saves, and restore the original editing page, selection and camera on return.

- Add the playable Motion Playground built-in template with editable native animation and JavaScript examples, a touch layout and in-project guide. Respect live reduced-motion settings, support focus/touch hover feedback, and avoid accumulating animations on repeated interaction.

- Polish everyday Design Studio editing with marquee selection, snapping guides, keyboard nudging, rendered-coordinate alignment/distribution, selection scaling and auto-layout reordering. Add visual sizing, typography, effects, image crop, linked reusable styles and component overrides/reset; show import fidelity and pending-save recovery explicitly. Extend isolated acceptance with content-sized cards, FORMA rebranding and edited HTML ZIP replay.

- Fix directory browsing accidentally submitting Design Studio creation. Require explicit creation, show parent and target paths, validate folder names and guard repeated clicks for blank and FORMA projects.

- Add the built-in FORMA editorial studio template to new design projects with a preview, four editable artboards and 328 layers. Each creation gets independent document history, bundled artwork and overwrite protection.

- Improve Design Studio navigation with persistent pan/zoom, Select and Hand tools, fit-to-page/selection, collapsible layers, selection breadcrumbs and grouped inspector sections. Show canvas connection failures with retry. Preserve more HTML document context, mixed text and responsive resources during conversion; keep original source and isolated preview boundaries.

- Add permanent deletion and emptying to the design project recycle bin with confirmation, revision checks and resumable cleanup. Remove affected project recovery records while preserving unrelated history and shared libraries.

- Show a restart diagnostic when a newer project homepage meets an older backend. Disable management actions until workspace state loads, expose retry, and prevent delete from silently doing nothing.
- Add the existing English demo video to all three website homepages with native playback controls, localized screenshot posters and a direct video link.

- Add an optional browser developer launcher with an explicitly isolated state directory and Vite frontend. Opt-in `--loopback-ui` uses literal `localhost` for managed-browser compatibility while preserving authentication and separate HTML-project origins; project previews may still be affected. Normal desktop launches and supported installer platforms are unchanged.

- Build Windows x64 and Mac arm64 installers on GitHub when a matching version tag is pushed; prepare a manually published Release draft with verified SHA-256 checksums. Keep manual artifact-only builds and protect published releases from replacement. Certificate-free Mac builds use ad-hoc signing without notarization.

- Rename the settings sidebar entry and page title from AI integration to Skill.

- Add English, Chinese and Japanese About pages with the creator’s GitHub and X profiles, linked from website navigation and footers.

- Keep the latest available stable Windows and Mac website downloads independently, with matching versions, release notes and checksums. Allow `v*` tags in the Pages environment so Release events can deploy automatically.

- Expand Design Studio into a visual HTML game-screen workbench: project home and recycle bin, asset metadata/replacement, reusable components and embedded pages, versioned personal shared libraries, and standalone ZIP export. Keep legacy 1.1.0 projects and convert authored DOM/CSS into a separate copy, adapting recognized navigation, switches and context-dependent page states; original scripts remain in the copied source and other runtime behavior needs new scripts.

- Share durable transaction undo/redo across pages, source edits, assets and directly applied AI batches, including after restart. Add version checks, idempotent retries, pending-save recovery and external-change protection. Offer animation presets and per-element/page `mount(ctx)` scripts with editable parameters, isolated preview, tracked cleanup and console/error attribution. Canvas gestures update selected nodes per frame and commit once; real-project and pressure-test budgets remain explicit acceptance targets.

- Expand the combined HTTP MCP surface to 42 tools: 23 note tools, 14 Design Studio tools and five optional Feishu tools, retaining independent note and Feishu permissions. Refresh client tools after updating; managed designs use document, operation, history, asset, shared-library and export interfaces.

## 0.1.2 — 2026-10-16

- Replace the four Feishu document/Base adapters with installed lark-cli discovery, generic read/write execution and credential-scoped attachment transfer. Support XML block edits, preserve document revision prechecks, and add separate local/Tunnel high-risk permission with explicit per-operation confirmation. Refresh client tools after upgrading.

- Unify Dev and installed Tunnel startup: reuse the installed runtime when available, enforce one owner per shared state directory, and always release the owned process job on quit. Distinguish LeafLoom MCP authorization errors from invalid Feishu table references.

- Fix inconsistent MCP permissions across ChatGPT conversations: authenticate the owned Tunnel runtime independently of connector Authorization headers, preserving resource grants and immediate revocation.

- Add optional Feishu/Lark settings backed by an externally installed and authorized lark-cli, with account verification and a unified CLI MCP bridge. Separate local/Tunnel Feishu permissions from note access; preserve CLI credential ownership and require read-time revisions for document edits.
- Preserve CLI pagination and reject document revision mismatches before writing. The upstream revision parameter is not an atomic cross-client edit guard.

- Add Settings → General → App updates with current/latest versions, verified installer downloads, a progress bar and installer launch after a normal quit. macOS opens the DMG; source Dev checks versions only.

- Unify Dev and the installed app on the same user data directory, settings, models, AI/MCP credentials, desktop profile and backend port; retain separate development dependencies and safely reuse old Dev models when the shared model directory is absent.

- Display the actual model storage path and add Open folder in model settings and setup, including before the first download.

- Show persistent model preparation stages, download volume/speed, elapsed time, waiting hints and retry details in search settings and setup. Avoid duplicate preparation requests, premature ten-minute download timeouts and duplicate weight hashing.

- Add a responsive English, Chinese and Japanese product website on GitHub Pages, with real screenshots, direct latest-stable Windows/Mac downloads, release notes and checksum links. Website content and download links refresh on relevant main-branch changes and Release events.

- Strengthen ignore rules for private configuration, credentials and local state; anonymize personal paths and private commit emails in repository history while preserving public author names.

- Remove the old repository launchers; manage installed apps directly and use Dev for source development.

- Add `Dev.cmd` (Windows) and `Dev.command` / `Dev.sh` (Mac) for source desktop development with automatic frontend updates, a dedicated Python environment and the shared application settings.

- Expand HTTP MCP to 23 tools for full-folder note discovery, Markdown/TXT/HTML editing, properties, folders, link-aware moves, recoverable deletion, history, templates, daily notes and index synchronization.
- Add separate local/ChatGPT MCP credentials and write switches, defaulting to read-only; preserve legacy retrieval scope and the internal assistant's proposal workflow.
- Check workspace/file/operation versions, preserve BOM and line endings, and retain external edits during failed move rollback.

## 0.1.1 — 2026-10-15

- Add built-in Secure MCP Tunnel settings, encrypted saved credentials and connection lifecycle handling.
- Improve note editing and add multilingual starter examples.
- Publish the macOS Apple Silicon installer; unsigned and not notarized, matching 0.1.0.
- Run local HTML projects with a chosen resource root, SPA routes, isolated persistent origins, navigation and downloads; open existing HTTP/HTTPS websites or development servers.
- Migrate browser drafts and view state from legacy loopback addresses, preserving conflicting values with recovery backups; add scoped Safari compatibility setup for macOS 14/15.
- Edit Markdown directly on the formatted page with slash commands, block dragging, tables, links, equations, diagrams and pasted or dropped attachments.
- Share undo history between formatted and source editing, retain unchanged source and properties, and preserve drafts on save conflicts.

## 0.1.0

- Introduce LeafLoom, a shared book-and-connections logo, website icon and desktop assets.
- Add Chinese, English and Japanese user interfaces, shared desktop catalogs and saved language preferences.
- Add a fictional demo folder, explicit search-scope setup and a resumable beginner checklist.
- Keep existing configurations and technical identifiers compatible. Language changes do not rebuild the index.
- Extend keyword tokenization to Japanese kana.
- Add multilingual user guides, community files, public screenshots and an English promotional video.

The macOS menu must be rebuilt from the updated source; see the dedicated build workflow. Platform validation is recorded separately from release notes.
