# Browse, preview and upload attachments

## Your goal

Search attachments, preview media and download originals in a dedicated workspace.

## Before you start

> **Availability:** This attachment workspace and organization workflow are included in source `main` after [PR #18](https://github.com/DJ-Huang/LeafLoom/pull/18), but are **not included in the published v0.1.3 installers**. Follow these steps only in a build that includes PR #18; see the [v0.1.3 release notes](https://github.com/DJ-Huang/LeafLoom/releases/tag/v0.1.3).

Connect a local folder first. Practise in the demo vault if you prefer.

## Steps

AI clients can use the same attachment system through `vault_files` (read/download/status) and `vault_files_update` (upload/manage). Enable workspace access in **AI connections**, granting writes separately. Chat files upload in the background; local clients can transfer size/hash-verified byte chunks. Inspect completed results before retrying a failed batch. File reads require current versions, and move/trash operations retain previews and recovery records. See [MCP setup](mcp.md).

Open **Attachments** in the sidebar for a dedicated workspace (`?view=attachments`). The header shows the total file count, storage used and index status. Search file names and relative paths across the vault; filter by type, sort by name, modification time or size, and switch between thumbnails and a list. The default is thumbnails, most recently modified first. Each page contains up to 100 items. Selection applies only to the current page and clears when paging, searching, filtering or sorting.

Opening the page only checks status. On first use, choose **Set up & prepare** once: LeafLoom prepares or upgrades the metadata index, checks protected dependencies and builds an organization plan in the background. Browsing becomes available as soon as the index is ready, while analysis continues. Supported old indexes are backed up; unsupported versions are never overwritten. Unknown totals show activity and processed counts rather than a completion percentage. **Tasks** reconnects to saved work and shows dates, states and results. Index-only maintenance remains under advanced options.

Select a file to preview it beside the results. Images support zoom, dragging, fit and full-size viewing; PDF opens inline, and audio/video uses the built-in player. Switching files or leaving the page stops playback. On narrow screens, return from the preview to the list without losing filters or scroll position. Other formats show metadata and an original-file download; desktop also offers **Show in file manager**. HTML never executes in this page, and SVG is displayed as an image. Thumbnails are generated on demand with bounded decoding and cached locally; failed or unsupported thumbnails show format icons.

Use **Upload** or drop multiple files onto the page. Uploads use the configured central folder (default `_attachments`); duplicate names keep both files, without overwriting. Upload progress and retry are in **Tasks**. Notes (`.md`, `.txt`, `.base`) belong in the editor or file browser. Select files for a ZIP download, a batch move or recycling; rename is available for one file. ZIP download preparation is asynchronous and the download expires after one hour.

Rename and move first prepare a plan, including supported static Markdown inline/reference links and wiki links/embeds. Review the discovered referring notes, paths and blockers, then confirm once to apply. Recycling a referenced attachment also shows the discovered notes and requires confirmation; it does not delete or rewrite note links. Restore the attachment when those links are needed again. “Discovered references” describes the analysis results, not proof that all references have been found. Office conversion, content/OCR search, deduplication and bulk naming templates are outside this version.


## What to expect

Duplicate names keep both uploads. Unsupported previews still offer original downloads.

## If it does not work

Use initialization when the metadata index is not ready. HTML project resources remain protected.

## Next steps

- [Organize attachments and recover a task](attachment-organization.md)
- [Back up notes, comments and recovery data](backup.md)
