# Contributing to LeafLoom

[English](CONTRIBUTING.md) · [中文](docs/zh-CN/COMMUNITY.md) · [日本語](docs/ja/COMMUNITY.md)

Thank you for helping people keep and use their own knowledge.

Open an issue with the problem, expected behavior, platform and reproducible steps. Use fictional notes and redact paths, usernames, tokens and AI conversations. For security issues, use GitHub private vulnerability reporting when available; do not publish credentials or private content in an issue.

For a change, keep the patch focused and preserve unrelated work. Technical identifiers (`vault-rag`, `VAULT_RAG_HOME`, `.vault-rag`) are compatibility interfaces, even though the product is named LeafLoom.

Use fictional paths and data in examples, logs and public media, and a public GitHub noreply address for repository commits. Keep local configuration, tokens, private keys and recovery backups out of Git. Before publishing, scan the worktree and complete history with [Gitleaks](https://github.com/gitleaks/gitleaks), using `--redact=100`; do not paste raw findings into issues or commit them. See [local access and privacy](docs/SECURITY.md).

UI text belongs in `vault_rag/locales/messages.tsv` (source, English, Japanese; named messages use key, Chinese, English, Japanese). Run `python scripts/compile_locales.py` after editing it. Keep placeholders consistent and update all three languages. The JSON catalogs are generated; do not maintain translations in build output.

Use Python 3.12 and the locked project environment. Build the frontend with `npm ci` and `npm run build` in `web/`. Run checks relevant to the change; productization regressions are in `tests/test_productization.py`. Validate UI changes against a fictional, isolated folder. State clearly which checks were run and which platforms were not tested.

For desktop development, install Node 22+ and uv, then double-click `Dev.cmd` on Windows or `Dev.command` on macOS 14+ Apple Silicon (or run `sh Dev.sh` in a Mac terminal / `node scripts/dev-desktop.cjs` on either platform). It synchronizes a dedicated Python 3.12 environment from `uv.lock`, installs missing frontend/desktop dependencies, and starts Vite plus the source desktop app. React/CSS edits update automatically without a frontend build or installer. Python/Electron edits require quitting from the tray and running it again. Development settings and its Python environment live in `.cache/desktop-dev/`; the backend defaults to port 18081 and Vite requires port 5173. Use fictional notes or the demo; opening a real folder still edits its real files. See [desktop development](docs/DESKTOP.md#source-development).

Editor source/history checks are `node tests/frontend_rich_markdown.cjs`, `node tests/frontend_browsing.cjs` and `node tests/test_ai_drafts.cjs`. The browser suite is `node tests/frontend_rich_editor.cjs` (also available through the previous `frontend_editor_ui.cjs` entry point). Install desktop development dependencies for Playwright Core and use an installed Edge/Chrome channel. Start `tests/editor_ui_server.py` with the built static directory; it creates a disposable vault and refuses the user's service port. Browser evidence is written to `.cache/rich-editor-qa/`.

For public media, see [media production](docs/MEDIA.md). Keep user data out of all screenshots. Contributions are distributed under the repository's MIT license; third-party material keeps its own license.

Browse the [documentation index](docs/README.md) for user guides, feature references and validation records.

## Repository layout

Keep the root limited to product entry points, dependency manifests and project documentation.

| Directory | Purpose |
| --- | --- |
| `vault_rag/` | Python application, translation catalogs and demo notes |
| `web/` | Frontend source and its npm lockfile |
| `scripts/` | Installation, platform integration and reproducible asset tools |
| `tests/` | Automated regression checks and isolated fixtures |
| `docs/` | User guides, architecture and validation instructions |
| `assets/` | Brand assets, public screenshots and reusable promotional media |
| `templates/`, `wiki-search/` | Ignore template and installable search skill |

`uv.lock` locks Python dependencies for both supported platforms; `web/package-lock.json` locks the frontend. Generated catalogs and public media are intentionally tracked so a checkout includes documentation and product resources.

Keep private `.env` files, indexes, `_generated/`, `.cache/`, virtual environments, `web/node_modules/` and built `vault_rag/static/` out of Git. Dev recreates development dependencies; release builds generate frontend output. Do not remove an active environment, configuration, model or index during routine source cleanup. Old environment backups can be removed after confirming the replacement works and no process uses them.

## Moving or copying a checkout

Place the repository in a writable local folder and launch Dev there. Do not copy a virtual environment from another machine or platform; let Dev prepare its dedicated environment. Installed applications are managed independently of the checkout.

Keep your note folder and private state separate from the source checkout. Never mirror a checkout over a folder containing unique notes or credentials. See [the user guide](docs/en/GUIDE.md).
