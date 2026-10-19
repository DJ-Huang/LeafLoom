# Highlight text and discuss notes (upcoming)

## Your goal

Mark passages and discuss a selection or the entire note.

## Before you start

> This feature is pending in [PR #22](https://github.com/DJ-Huang/LeafLoom/pull/22) and has not merged into main. Use the workflow below only after it is included in your installed version.

Connect a local folder first. Practise in the demo vault if you prefer.

## Steps

In a Markdown document, select text to reveal five **highlight** colors and **Add comment** in the floating formatting bar. Choose a color to mark a passage. To restore plain text, select highlighted text and choose **Clear highlight** (the slashed circle before the colors), also available in the context menu. Only the selected highlight is removed; outside portions and comments remain. One clear action is one undo/redo step. Click comment (or press `Ctrl/⌘+Shift+M`) to begin a thread. Use the toolbar's **Comments** button to see the right panel, add a **Page comment** without selecting text, reply to threads, edit your messages, resolve/reopen, filter or delete.

Click a quoted snippet to jump to the original passage. Comments try to follow moved text using the quote and its context; deleted or ambiguous quotes are flagged **Text no longer found**, so you can select a new range and **Relink to selected text**. The same decorations appear in Markdown source mode without modifying Markdown syntax. Highlights and comments share the page/source undo history: use the toolbar buttons or `Ctrl/⌘+Z` to undo and `Ctrl/⌘+Shift+Z` (or `Ctrl+Y`) to redo. Creation, deletion (including replies), message edits, resolve/reopen and relinking can be reversed in order with text edits during the current session. Comment input fields keep their own text undo. If another window or MCP changed a thread, undo/redo stops without overwriting it. Normal unsaved edits must save first; AI manual drafts must be saved explicitly.

Highlights and comments are **user data**, not a disposable index: back up `.vault-rag/annotations.sqlite` alongside your notes. When moved or restored through LeafLoom, note comments retain their identity. The first iteration supports annotated Markdown (the API also supports plain TXT); HTML projects and Design Studio are not yet covered. See [annotation architecture](https://github.com/DJ-Huang/LeafLoom/blob/cee43cd8114845f85360401cb9b57ad2fc412030/docs/ANNOTATIONS.md).

## What to expect

Annotations stay in the vault without rewriting Markdown source.

## If it does not work

Relink an outdated quote to a new selection. Include annotations.sqlite in backups.

## Next steps

- [Restore note history and recycled files](recovery.md)
- [Back up notes, comments and recovery data](backup.md)
