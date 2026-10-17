# Changelog

[English](CHANGELOG.md) · [中文](docs/zh-CN/CHANGELOG.md) · [日本語](docs/ja/CHANGELOG.md)

## Unreleased

- Add permanent deletion and emptying to the design project recycle bin with confirmation, revision checks and resumable cleanup. Remove affected project recovery records while preserving unrelated history and shared libraries.

- Show a restart diagnostic when a newer project homepage meets an older backend. Disable management actions until workspace state loads, expose retry, and prevent delete from silently doing nothing.

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
