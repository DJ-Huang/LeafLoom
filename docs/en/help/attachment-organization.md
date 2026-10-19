# Organize attachments and recover a task

## Your goal

Review the proposed migration, consolidate attachments and retain recovery material.

## Before you start

Connect a local folder first. Practise in the demo vault if you prefer.

## Steps


**Organize attachments** opens the task workspace. Review the destination (vault-relative, default `_attachments`), movable file count, size, affected notes and retained resources; create a new plan when needed. Preparing a plan writes only index and recovery metadata. Actual changes require one explicit confirmation, without a separate acknowledgement checkbox. A blocked plan leaves the ready index usable for browsing and downloading. Expand the reasons, resolve them and prepare a fresh plan. Large path, reference, result and blocker lists show at most 200 entries, with totals where applicable.

HTML/source projects, loose script folders, native authoring projects and their related shared resources stay in place. Literal file references, directory prefixes and configuration references expand protection transitively. These files remain browsable and downloadable, but cannot be renamed, moved or recycled here. Dynamic code within retained projects does not by itself block independent attachments. Unreadable dependency sources, ambiguous links, unsupported references and destination conflicts can still block a plan. Binary engineering resources are not parsed as text.

Before execution, the service checks file versions, access boundaries, destination collisions and free space again. Changes after analysis require rechecking. Pause external editors and sync before applying; conflicting writes through LeafLoom are blocked during execution, while reading and downloading remain available. Move/rename rewrites only supported note links. Organization copies files, updates links, retires originals into recovery storage and rebuilds the index. A final-index failure triggers restoration. Results report each file as pending, completed, failed or restored so partial failures can be reviewed.

**Request stop** stops at a safe boundary and is not undo. Leaving the page or switching vaults stops client waiting, not the server task; return to **Tasks** to reconnect. After a service restart, inspect saved work before confirming resume. **Restore / undo task** requires confirmation and refuses to overwrite subsequent edits or new files. Recycled attachments can also be restored from the recycle area in Settings; their note links are left untouched.

Recovery material stays in `.vault-rag/attachment-migrations/<job-id>/`: `manifest.json` records the task, `originals/` holds original assets and `notes/` holds note backups. Recycling uses recoverable records under `.vault-rag/trash/`. Do not edit or remove recovery folders while they may be needed. This workspace has no permanent-delete action. Preserve recovery data and resolve reported conflicts before retrying. Only a completed organization task changes the default upload folder; rename and move do not.

## What to expect

Tasks report completed, failed or restored items. A successful migration updates the upload folder.

## If it does not work

Stopping does not undo a task. Retain the journal, originals and note backups while resolving conflicts.

## Next steps

- [Browse, preview and upload attachments](attachments.md)
- [Restore note history and recycled files](recovery.md)
- [Back up notes, comments and recovery data](backup.md)
