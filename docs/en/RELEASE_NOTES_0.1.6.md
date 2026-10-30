# LeafLoom 0.1.6 — Note databases and a consistent workspace

Release date: 2026-10-30 · Changes since v0.1.5

[English](RELEASE_NOTES_0.1.6.md) · [中文](../zh-CN/RELEASE_NOTES_0.1.6.md) · [日本語](../ja/RELEASE_NOTES_0.1.6.md)

## One collection, five database views

Organize Markdown notes in table, list, board, gallery and timeline views. Each record remains a note: bodies, attachments and properties reuse the existing editor and file history. Save per-view filters, sorting, grouping and layouts, and embed a stable database view inside another note. Creating a record prefills compatible equality filters from the current view.

Record context menus open a side peek or full page, rename, duplicate, copy a note link or move a note to recoverable trash. Details show a compact property layout with additional fields collapsed. Add properties at the bottom; use field menus to rename, reorder, remove definitions or edit select/multi-select labels and colors. Removing definitions or choices preserves existing note values and bodies.

## Plan tasks on the board

The task preset binds explicit status, priority and due-date fields. Move cards across columns, reorder them manually and undo moves with version protection. Configure columns, labels, colors and visible card properties. Deleting a group previews affected records and provides a destination and any required task-state replacement.

This release fixes repeated dragging, delayed create/move/delete feedback and metadata-preparation retries. Legacy task boards and calendars remain available.

## A shared workspace style

The sidebar, home, editor, database views, attachments, graph, Design Studio and dialogs share typography, spacing and focus states, including narrow-screen layouts. Design Studio adds page-list duplicate/delete actions and selected-page HTML exports. Its Publish to menu can publish selected pages to a new or associated Miaoda course app.

## More controlled attachment synchronization

Set attachment extension allowlists shared by local and server browsing and uploads. Limit server scan directories, pause/resume discovery and inspect concrete sync phases. Startup reuses saved state and check times; background checks run about every 30 minutes. Originals, existing links and pending metadata are preserved.

## Database tools for AI

Refresh MCP tool discovery after upgrading. Database tools expose typed commands, capabilities, record-body reads, field/view configuration, view ordering, group management and board moves/undo. Read-only grants, file boundaries, revisions and retry IDs continue to apply. Database browsing does not expand note retrieval scope.

## Upgrade and platform support

Back up the vault and retain its metadata and recovery files. Fully quit LeafLoom, install the matching package and reopen the same vault. Source users should update and use Restart LeafLoom.

Installers target Windows x64 and macOS 14+ Apple Silicon. Windows is unsigned; macOS uses ad-hoc signing without Apple notarization. Verify SHA256SUMS.txt and consult the linked native workflow reports. CI does not certify every device, server or physical display configuration.

[User guide](GUIDE.md) · [Full changelog](../../CHANGELOG.md)
