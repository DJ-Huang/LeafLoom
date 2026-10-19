# Markdown highlights and threaded comments · 标注与评论

LeafLoom supports per-vault, local-first text highlights and threaded comments without inserting hidden markup or Notion-specific syntax into Markdown files.

## Usage

1. Open a Markdown note in rich editing mode. Select text and click one of the five colored highlight dots in the floating formatting bar. To comment on the selection instead, choose the speech-bubble icon or press **Ctrl/⌘ + Shift + M**.
2. Use the **Comments / 评论** button in the note toolbar to open the right panel. Choose **Page comment** to comment without selecting text. Threads support replies, editing your message, resolving/reopening, filtering by status, and deletion.
3. Click highlighted text or an excerpt in the comments panel to jump back to its source. If the quote was deleted or its position became ambiguous, the comment shows **Text no longer found / 定位已失效**. Select new source text, then choose **Relink to selected text / 关联到当前选区**.
4. Annotations are visible as colored ranges in both the rich editor and Markdown source mode. They never modify Markdown syntax. Annotation operations share the rich/source document history for the current session. Use toolbar Undo/Redo, **Ctrl/⌘+Z**, **Ctrl/⌘+Shift+Z** or **Ctrl+Y**; creation, replies, message edits, resolution, relinking and deletion are reversible in order with text edits. Textareas retain native text undo.
5. The app autosaves ordinary dirty notes before anchored annotations. Manual AI drafts are not automatically committed; save them explicitly first. If saving fails, no anchored annotation is created.

## Data and migration

Annotations are durable user content saved in **`<vault>/.vault-rag/annotations.sqlite`**, alongside separate version histories. **Back up this database** together with the vault's Markdown notes; it is *not* a disposable search index. Annotations and replies contain text, author names, color, timestamps and a file identity. Note moves/renames, directory moves, trash/restores and MCP note operations keep identities aligned when completed through LeafLoom. A new note at a path whose previous note is in the trash gets a new identity.

Only `.md` and `.txt` notes are supported by the storage API in this first iteration; rich-editor annotation controls are available in `.md`. HTML projects and Design Studio are not yet annotation targets. The local AI/MCP interface exposes explicit permission-gated annotation list, create, reply and resolve operations; annotation text is **not** automatically included in RAG or search results.

### Source anchor contract

Each anchored annotation stores `from`, `to` (UTF-16 source positions), selected `exact` text, neighboring `prefix` and `suffix` strings and the raw file `etag`. In-session ranges render as ProseMirror and CodeMirror decorations. On reload after external text changes, a deterministic quote/context resolver tries to find the best match. An ambiguous or deleted quote is detached rather than attached to potentially unrelated text.

Concurrent annotation writes use incrementing revisions; a stale edit returns a conflict. The note's original source version is checked when initially creating or relocating an anchor. The per-vault database refuses unknown future schema versions. Opening notes with no comments is read-only and does not create an empty database. Schema 2 adds server-owned before/after snapshots in `annotation_history` (up to 200 operations per document). Each write returns a history ID; `POST /api/annotations/history` replays it under the existing root/path checks and a full-thread comparison. Deleted threads restore their original IDs, authors, creation times, anchors and replies; replay increases revisions and rebases only matching adjacent history states. Concurrent changes cause a conflict and leave the history step in place. The frontend reserves annotation steps before asynchronous writes and retains history across rich/source and tab switches; reload clears the frontend session history.

## API and tests

Browser endpoints: `GET/POST /api/annotations`, `PATCH/DELETE /api/annotations/{id}`, `POST /api/annotations/{id}/messages`, and `PATCH /api/annotations/{id}/messages/{message_id}`. All requests remain protected by the existing browser authentication and write-CSRF middleware. The `root` and `path` parameters must resolve to the currently connected local vault and a regular note. MCP tools: `vault_list_annotations`, `vault_add_annotation`, `vault_reply_annotation`, `vault_set_annotation_status`; note-write permissions and workspace revisions are required for changes.

Regression checks:

```sh
uv run --no-project --python .cache/desktop-dev/.venv/bin/python --with pytest python -m pytest -q tests/test_annotations.py tests/test_annotation_mcp.py
node tests/frontend_rich_markdown.cjs
node tests/frontend_annotation_anchors.cjs
node tests/frontend_annotation_history.cjs
# After building frontend, run tests/editor_ui_server.py against a disposable vault (not 18080):
node tests/frontend_annotations.cjs
```

The isolated browser tests cover highlighting, page/inline comments, replies, status, source decoration, quote reattachment/detachment and Markdown byte preservation. No Windows native testing is claimed.
