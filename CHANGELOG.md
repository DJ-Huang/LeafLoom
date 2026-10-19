# Changelog

[English](CHANGELOG.md) · [中文](docs/zh-CN/CHANGELOG.md) · [日本語](docs/ja/CHANGELOG.md)

## Unreleased

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
