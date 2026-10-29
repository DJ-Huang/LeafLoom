# Browse, preview and upload attachments

## Your goal

Find local and server files in one attachment manager, organize groups and download originals when needed.

## Before you start

The simplified servers, automatic resumable discovery and dedicated Downloads page are available in [LeafLoom 0.1.5](../RELEASE_NOTES_0.1.5.md). Back up the vault and retain existing app data before upgrading. Local-only browsing does not require a server.

For remote files, open **Settings → Attachment servers**, add an address, account and password, then **Save and connect**. HTTP(S) addresses use WebDAV; `smb://host/share/subfolder` and Windows shared paths use SMB2/3. No brand selection or system mount is required. Use HTTPS for public WebDAV; existing numeric private/VPN HTTP connections remain supported. Official-client bridges still need their client and configured port to stay available.

## Steps

1. Open **Attachments**. Use the source selector for all, local, remote or an individual server. Prepare the local catalog when needed; this indexes filenames without moving files. Changing the default upload server affects future uploads only.
2. Search names/paths, filter by type, sort and choose a grid or list. Create manual groups or rules using source, directory, format, category and tags. A group change updates its heading and clears the old list while loading; Retry stays in the selected group after a failed read.
3. Open **Attachment information** to inspect a selected file. The panel starts collapsed and remembers its preference. Images, PDF, audio and video retain their viewers. Unsupported formats use an existing cover without downloading the original; a missing cover offers the file icon and download action.
4. Upload files here or drag them into the manager. Existing same-name originals are retained. Notes and new folders/imports use the file directory actions. Server cards can be edited, disabled or selected as the new-upload destination without moving existing attachments.
5. Open **Sync status** for discovered files, scanned/pending directories, reused-directory counts and retry details. Scanning resumes from device-local checkpoints after disconnection or restart; automatic sources run serially, with at most two directory readers per server. After a completed pass, the next check is five minutes later. Directory caches last ten minutes; expired children are checked independently. **Check all directories** bypasses the cache without downloading originals.
6. Use **Downloads** to monitor original-file preparation and ZIP tasks. A verified remote file can be saved to the device; the staging limit is configured in Download settings. Releasing staged files removes local temporary copies, not server originals. Rename, move and recycle retain reference/version checks; server capabilities can differ.

### Metadata, AI scope and server rules

Categories, tags, personal notes, source metadata and real covers enrich the same file list. The former fixed product view is replaced by groups; compatible product tools and optional Unity collection remain available. Groups and metadata synchronize through verified server records with explicit conflict handling. Live SQLite catalogs, pending uploads and caches stay in the device's application data; do not synchronize or delete them as disposable caches.

Enable **Use for AI asset search** only on the groups that AI should search. No selected groups returns no asset results. AI can inspect metadata/previews and request verified delivery to a configured local directory; it does not automatically import into Unity or verify purchase rights. See the [complete guide](../GUIDE.md#attachment-manager).

A visible `leafloom.ignore` at the server root or a subdirectory may exclude files using Gitignore-style patterns. Its first line must be exactly `# leafloom-ignore v1`; a child rule or `!` can reinclude files. Rules are read without requiring NAS write permission. A completed successful scan applies exclusions while retaining original files, IDs and existing references.

## What to expect

Background discovery preserves browsing filters, selection, scroll and metadata drafts. An expired pagination snapshot offers **List updated — show latest** instead of silently moving to page one. Originals remain local or on their existing server. The overview reports originals separately from preview caches; unprepared local totals are unknown rather than zero.

## If it does not work

Temporary network failures retry automatically, with the previous issue collapsed. Reconnecting and active metadata synchronization replace stale errors; authentication failures need updated credentials. Failed scans retain existing records. The first upgraded scan must establish checkpoints. Without a server change feed, periodic directory queries remain necessary. Cached originals can be opened offline; uncached or partial files need a connection.

Keep the existing server ID, logical root and metadata binding when recovering references on another device. Changing the default upload destination does not relocate originals or a bound metadata library. Preserve legacy migration records and recovery material; migration/organization entry points are not offered in this version.

## Next steps

- [File operations and recovery records](attachment-organization.md)
- [Back up notes and recovery material](backup.md)
- [Configure MCP access](mcp.md)
