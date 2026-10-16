# Changelog

[English](CHANGELOG.md) · [中文](docs/zh-CN/CHANGELOG.md) · [日本語](docs/ja/CHANGELOG.md)

## Unreleased — 2026-10-16

- Add a responsive English, Chinese and Japanese product website on GitHub Pages, with real screenshots, direct latest-stable Windows/Mac downloads, release notes and checksum links. Website content and download links refresh on relevant main-branch changes and Release events.

- Strengthen ignore rules for private configuration, credentials and local state; anonymize personal paths and private commit emails in repository history while preserving public author names.

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
