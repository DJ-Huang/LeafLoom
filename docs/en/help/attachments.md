# Browse, preview and upload attachments

## Your goal

Search attachments, preview media and download originals in a dedicated workspace.

## Before you start

> **Availability:** This attachment workspace and organization workflow are included in the [v0.1.4 installers](https://github.com/DJ-Huang/LeafLoom/releases/tag/v0.1.4). They are not included in v0.1.3. If you use an older version, back up your vault and update before following these steps.

Connect a local folder first. Practise in the demo vault if you prefer.

## Server attachments, local cache and migration

This feature requires a build containing server attachment support; the original v0.1.4 installers do not include it.

Open **Settings → Files & import → Attachment storage** to add a generic WebDAV server. Each profile has a name, service URL, server root, upload subdirectory and separate username. Do not include a password in the URL. **Save attachment settings**, then **Test connection** and **Scan server attachments**; opening Settings does not scan the NAS automatically. Background scanning saves directory metadata in batches without reading attachment contents; discovered records remain after interruptions or failures. The new-attachment destination affects future uploads only, and the local workspace remains available. Server permissions control writable directories; read-only assets cannot be renamed, moved or recycled in LeafLoom.

After deleting, moving or adding originals on the NAS, choose **Refresh server directory** in Attachments. A specific-server source refreshes only that server. For all/server sources, choose one server when several are configured; a single enabled server can refresh directly. It does not refresh every server automatically. This synchronizes directory metadata without reading attachment contents, and reports progress and results. Only a complete successful scan hides missing files from the list and size totals. Asset IDs, tags and old-reference records remain; opening an old reference reports a missing original. Interrupted or failed scans retain existing records. **Refresh indexed list** only reloads the local index and does not discover NAS deletions.

The server root and each subdirectory may contain a visible `leafloom.ignore`. It supports Gitignore-style paths, globs, `#` comments and `!` reinclusion; child-directory rules can override ancestor rules. Scanning always visits subdirectories to read their rules rather than applying Git's excluded-parent directory pruning, so child rules can reinclude files excluded by an ancestor. The defaults exclude `.md`, `.markdown`, `.base`, `.html`, `.htm` and script/source-code files; `!` can also override these defaults. `.txt`, `.json`, binary and design resources remain included. Edit rules through the NAS file manager: LeafLoom reads them without requiring Dufs write permission. Refresh the server directory after changes. Only a complete successful scan hides excluded entries from attachment lists, metadata searches and size totals. Exclusion does not delete NAS originals or mark them missing: existing asset IDs, tags, old references and cache remain, and old IDs/references can still read the original. Rule read/parse failures do not partially hide existing records under the new rules; correct them and refresh again.

Save the file as UTF-8 (an optional BOM and CRLF are accepted). Its first line must be exactly `# leafloom-ignore v1`, with no blank line before it; an absent or invalid header stops the refresh instead of treating an authentication/error page as rules. Each file is limited to 64 KiB, 2,048 lines and 2,048 characters per line. Copy this template to the root or a subdirectory and adapt its rules:

```text
# leafloom-ignore v1
# Exclude temporary files under this directory
*.tmp
# Reinclude this Markdown file as an attachment
!reference.md
```

The desktop app stores passwords with system encryption and restores them to backend memory in the background; workspace configuration contains no passwords. Where supported, system encryption uses asynchronous APIs so the workspace opens without waiting for key-store recovery. If the system key store is temporarily locked or the local service has not received credentials, recovery retries are limited to delays of 1, 3, 10 and 30 seconds. Unlocking, waking the computer or choosing **Settings → Files & import → Attachment storage → Attachment credential recovery → Retry credential recovery** starts a fresh retry cycle. This section reports key-store, credential-file and local-sync status. **Synced to the local service** means credentials reached backend memory; check the server connection separately. A damaged credential file is retained rather than replaced with empty credentials. In the browser version, passwords live only in the current backend process's memory and must be entered again after its restart.

NAS network failures and 502/503/504 responses use retry backoff of about 2, 4, 8, 16, 32 and 60 seconds, capped at 60 seconds, while retaining directory records and pending uploads. Healthy connections probe only their configured URL about every 60 seconds, without recursively scanning the NAS or reading attachment contents. A 401/403 response pauses automatic attempts with that credential version until an explicit **Test connection**, task resume or credential update. Changing a password does not reauthorize old tasks: if the owner or credential revision changed, explicitly resume the task so its owner/revision checks can run again.

An official-client bridge uses the verified local forwarded URL you provide. Keep the official client and its attachment window open. After closing that window or restarting the client, reopen the attachment window manually; LeafLoom cannot rebuild the official session or discover a new port. Recovery at the same URL can be detected automatically; update the URL manually if the port changes. Complete any verification in the official client, then resume according to the task state.

The server holds originals; local files are fetched into an on-demand cache. Details show the original location and whether caching is absent, partial or complete. Edit tags, categories and descriptions for browsing and AI/MCP queries. The downloaded cache defaults to 2 GiB and can be resized or cleared in Settings. Complete cached files can be reused; uncached or partial files still require a server connection. Pending uploads have a separate space limit, defaulting to 10 GiB, and survive cache cleanup. Connection or authentication failures retain waiting tasks and pending files. Received and waiting for sync does not mean saved on the server; completion requires server storage and verification. Authentication pages or error HTML must not become attachment cache entries. AI/MCP shares these storage profiles, metadata and backend tasks under the existing separate workspace read/write grants, without receiving server passwords.

To move existing files, choose a server and **Preview local attachment migration**. By default this analyzes only the current local attachment directory, excluding project dependencies. Review counts, sizes, files and exclusions, then **Confirm and execute migration**. Each original is released locally only after upload, streaming readback SHA-256 verification, a durable old-path mapping and a fresh source-version check. This creates no permanent local originals archive. Existing note references keep resolving inside LeafLoom; compatibility with other Markdown editors is not promised. Interruptions retain pending files and progress. Configuring a server does not move existing originals without an explicit migration.

Server migration differs from the recoverable local organization workflow below. Existing history, recycle records and older organization archives are not deleted automatically and may still use disk space. Back up server originals independently; cache is not a backup. Remote attachments do not offer **Show in file manager**.

### Asset products and Unity packages

Switch from **Attachment files** to **Asset products** in Attachments. In **Settings → Files & import → Attachment storage → Asset catalog and download staging**, choose the catalog server and its metadata directory (default `Incoming/LeafLoomCatalog/v1`). Then choose **Discover existing packages**. Discovery catalogs existing `.unitypackage` entries without downloading or unpacking the originals. Opening the view does not start official-site collection. The product catalog is shared for this vault; the server selector chooses its storage location rather than filtering package files. An initialized catalog cannot silently change server or directory.

One product can link several versions or copies. Unmatched files remain visible as candidates. Filename hints never become confirmed matches automatically; unverified versions show **Unknown** or their filename source. Paste an official Asset Store URL, check the product and publisher, then confirm or reject the association. A product association is not proof of purchase entitlement. **Fetch official information** is explicit; progress distinguishes obtained, review-needed and failed entries. Unavailable official descriptions or covers stay empty, with no substitute artwork. A recorded link does not mean collection succeeded; a pending Chinese summary remains labeled as pending.

Official information and **My organization** are separate. Official refresh preserves personal product tags, category and notes; existing per-file metadata also remains separate. Catalog metadata and covers are saved in the chosen NAS directory, with a local query projection for browsing and search. Pending sync and conflicts remain visible; a stale revision does not overwrite newer edits.

Choose **Prepare download** for a specific package. The backend streams it into separate local staging, verifies it and exposes a controlled download only in **Verified, ready to download** state. This staging defaults to **20 GiB**, independently of preview cache and upload queues. Tasks survive page changes; paused tasks can retry, and **Release staging** removes the local prepared copy without deleting the NAS original. Download handles expire after 24 hours; prepare again when needed. Preparing or downloading does not modify a Unity project. Confirm any import separately in the intended Unity project.

AI/MCP uses the same catalog and tasks: `vault_files` actions `products`, `product`, `prepare_download` and `download_status`; catalog edits and release/retry use `vault_files_update` action `product_update` under the connection's write grant. Read current revisions and keep identical operation IDs for identical retries. Complete packages are downloaded through the controlled local UI, not moved as Base64 through MCP. The existing `read` with a download job ID still applies only to legacy ZIP export jobs. No automatic Unity import or account ownership verification is provided.

## Steps

The single-request Base64 path requires a build containing this change.

Use `vault_files_update` with `request.action="upload"` for knowledge-base attachments. ChatGPT should prefer `source="files"` with the host-provided top-level `files` array. Local clients can send one file up to 2 MiB with `source="base64"`, `name`, `data_base64`, and the original bytes' `sha256`; use begin/chunk/commit for larger files. Omit `folder` for the configured attachment directory, or specify a vault-relative directory such as `Comics/Project/assets`.

Read `workspace_revision` from `vault_index_status` and use a unique `operation_id`; keep the ID unchanged when retrying identical arguments. Upload results include the saved path, size, SHA-256, revision and `markdown_link`; images also return `markdown_embed`. Use `vault_files` stat with `source_note` to obtain a note-relative reference, then edit the note with its current revision. Existing files remain intact.

If only Design Studio import or Feishu temporary transfers appear, check the server's `tools/list`: it must include `vault_files` and `vault_files_update`. Restart an updated backend and refresh/rescan the client's plugin tool directory. Restarting LeafLoom alone does not refresh a cached client directory. Check workspace-write permission separately; these uploads do not require Feishu authorization. See [MCP file tools](mcp.md).

AI clients can use the same attachment system through `vault_files` (read/download/status) and `vault_files_update` (upload/manage). Enable workspace access in **AI connections**, granting writes separately. Chat files upload in the background; local clients can transfer size/hash-verified byte chunks. Inspect completed results before retrying a failed batch. File reads require current versions, and move/trash operations retain previews and recovery records. See [MCP setup](mcp.md).

Open **Attachments** in the sidebar for a dedicated workspace (`?view=attachments`). Use **Attachment source** to select all sources, local attachments, server attachments or a specific server; pagination, totals, size and type counts follow that selection. All sources shows local and server original sizes separately; a single source shows only its originals, excluding local cache. The header shows the total file count, storage used and index status. Search file names and relative paths across the vault; filter by type, sort by name, modification time or size, and switch between thumbnails and a list. The default is thumbnails, most recently modified first. Each page contains up to 100 items. Selection applies only to the current page and clears when paging, searching, filtering or sorting.

Opening the page only checks status. On first use, choose **Set up & prepare** once: LeafLoom prepares or upgrades the metadata index, checks protected dependencies and builds an organization plan in the background. Browsing becomes available as soon as the index is ready, while analysis continues. Supported old indexes are backed up; unsupported versions are never overwritten. Unknown totals show activity and processed counts rather than a completion percentage. **Tasks** reconnects to saved work and shows dates, states and results. Index-only maintenance remains under advanced options.

Select a file to preview it beside the results. Images support zoom, dragging, fit and full-size viewing; PDF opens inline, and audio/video uses the built-in player. Switching files or leaving the page stops playback. On narrow screens, return from the preview to the list without losing filters or scroll position. Other formats show metadata and an original-file download; desktop also offers **Show in file manager** for local attachments. HTML never executes in this page, and SVG is displayed as an image. Thumbnails are generated on demand with bounded decoding and cached locally; failed or unsupported thumbnails show format icons.

Use **Upload** or drop multiple files onto the page. Uploads use the configured local central folder (default `_attachments`) or the selected server upload directory; duplicate names keep both files, without overwriting. Upload progress and retry are in **Tasks**. Notes (`.md`, `.txt`, `.base`) belong in the editor or file browser. Select files for a ZIP download, a batch move or recycling; rename is available for one file. ZIP download preparation is asynchronous and the download expires after one hour.

Rename and move first prepare a plan, including supported static Markdown inline/reference links and wiki links/embeds. Review the discovered referring notes, paths and blockers, then confirm once to apply. Recycling a referenced attachment also shows the discovered notes and requires confirmation; it does not delete or rewrite note links. Restore the attachment when those links are needed again. “Discovered references” describes the analysis results, not proof that all references have been found. Office conversion, content/OCR search, deduplication and bulk naming templates are outside this version.


## What to expect

Duplicate names keep both uploads. Unsupported previews still offer original downloads.

## If it does not work

Use initialization when the metadata index is not ready. HTML project resources remain protected.

## Next steps

- [Organize attachments and recover a task](attachment-organization.md)
- [Back up notes, comments and recovery data](backup.md)
