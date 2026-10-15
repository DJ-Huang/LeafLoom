# Agent Working Agreements

## Core Architecture

- `vault_rag/`: local Python service providing file APIs, HTTP MCP, cataloging and retrieval; model and vector tasks run in the separate `rag_process` process.
- `web/`: shared React frontend; Markdown content uses Tiptap/ProseMirror, while source editing uses CodeMirror, with shared document state and undo history.
- `desktop/`: Electron loads the same frontend and handles only windows, the tray and system integration. HTML projects run on separate origins, isolated from the management interface.
- Notes live in user directories; indexes, history and trash live in their `.vault-rag/` directory. Browsing and retrieval scopes are independent; retrieval uses only explicitly selected content.

## Changes and Delivery

- Follow current source code and local instructions, keep changes focused and preserve unrelated changes; protect original user files, drafts, version checks and access boundaries.
- **Update documentation when completing a feature**: update the usage guides in all three languages for operational changes and the changelogs in all three languages for user-visible changes; update the relevant documentation for entry point, architecture or configuration changes, and adjust the homepages in all three languages when needed.
- The documentation entry point is `docs/README.md`, and the guides are `docs/{en,zh-CN,ja}/GUIDE.md`; add new documents to the index. See `docs/ARCHITECTURE.md` for architecture details and `CONTRIBUTING.md` for development conventions.
- Maintain UI text in `vault_rag/locales/messages.tsv` and generate language files with `scripts/compile_locales.py`; do not maintain build artifacts as source.
- Run the minimum necessary checks for the changes; for documentation-only changes, checking links and diffs is sufficient. Report what changed and what was verified, and never claim that unperformed checks passed.
