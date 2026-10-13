# Browsing performance

LeafLoom separates file browsing from model inference. Directory and link metadata are cached, and non-note assets do not enter text/vector indexing. External changes use file watching, periodic reconciliation and a polling fallback.

Large lists are virtualized; the editor, graph, formulas and diagrams load on demand. Long Markdown is parsed in a worker and rendered incrementally. Recent document caching is bounded, preserves drafts, and is scoped to the connected folder. Media is loaded as needed; inactive playback pauses.

## Validate a change

Use fictional, isolated folders and ports. Check initial rendering, repeated navigation, long documents, large file lists and foreground responsiveness while indexing. Record platform, browser, dataset size, cold/warm state and measurement method. A timing measured on one device is not a universal promise.

Relevant checks are `tests/test_browsing.py`, `tests/frontend_browsing.cjs` and the UI fixtures. Use `VAULT_WEB_OUTPUT` for a separate build if an existing service serves current assets. Application updates need installation and service restart; browser reload alone is insufficient.

See [the user guide](en/GUIDE.md) and [current productization validation](PRODUCTIZATION_VALIDATION.md).
