# Contributing to LeafLoom

[English](CONTRIBUTING.md) · [中文](docs/zh-CN/COMMUNITY.md) · [日本語](docs/ja/COMMUNITY.md)

Thank you for helping people keep and use their own knowledge.

Open an issue with the problem, expected behavior, platform and reproducible steps. Use fictional notes and redact paths, usernames, tokens and AI conversations. For security issues, use GitHub private vulnerability reporting when available; do not publish credentials or private content in an issue.

For a change, keep the patch focused and preserve unrelated work. Technical identifiers (`vault-rag`, `VAULT_RAG_HOME`, `.vault-rag`) are compatibility interfaces, even though the product is named LeafLoom.

UI text belongs in `vault_rag/locales/messages.tsv` (source, English, Japanese). Run `python scripts/compile_locales.py` after editing it. Keep placeholders consistent and update all three languages. The JSON catalogs are generated; do not maintain translations in build output.

Use Python 3.12 and the locked project environment. Build the frontend with `npm ci` and `npm run build` in `web/`. Run checks relevant to the change; productization regressions are in `tests/test_productization.py`. Validate UI changes against a fictional, isolated folder. State clearly which checks were run and which platforms were not tested.

For public media, see [media production](docs/MEDIA.md). Keep user data out of all screenshots. Contributions are distributed under the repository's MIT license; third-party material keeps its own license.
