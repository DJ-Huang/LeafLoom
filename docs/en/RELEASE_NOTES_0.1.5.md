# LeafLoom 0.1.5 — Attachments, asset workflows and presentations

Release date: 2026-10-29 · Changes since v0.1.4

[English](RELEASE_NOTES_0.1.5.md) · [中文](../zh-CN/RELEASE_NOTES_0.1.5.md) · [日本語](../ja/RELEASE_NOTES_0.1.5.md)

## Browse local and server attachments together

Connect generic WebDAV or SMB2/3 servers with an address, account and password in **Settings → Attachment servers**. Changing the new-upload destination keeps existing files and metadata-library bindings in place. Notes remain in your local vault; server originals are read or downloaded on demand.

The attachment manager now puts files first: a compact toolbar, an on-demand overview, a collapsible information panel and cover previews for formats without a built-in viewer. Create manual or rule-based groups using source, directory, format, category and tags. Group changes update the heading, list and counts together; failed reads no longer leave the previous group's contents under a new tab. **Downloads** has its own page, and file creation/import moves to directory actions.

## Automatic synchronization that can resume

Discovery runs after connection recovery and checks again five minutes after a completed pass. Completed directories are checkpointed locally so interrupted scans can resume after a disconnect or restart. Later checks reuse ten-minute directory caches and revalidate expired descendants independently. **Sync status** shows progress, reused directories and current reconnecting/syncing states; temporary connection details are collapsed and authentication failures still require updated credentials.

Servers without a change feed still need periodic directory queries. The first pass after upgrading builds checkpoints; this is not an instant change stream. Incomplete scans preserve existing records. Migration and organization entry points are hidden; existing records and recovery material are retained.

## Give AI an explicit asset scope

Enable **Use for AI asset search** on selected attachment groups. AI can search metadata, inspect existing previews and deliver verified originals to a configured local directory. Optional local semantic ranking is separate from note retrieval. No selected groups means no asset-search results; this does not authorize automatic Unity imports or prove purchase rights.

Existing Unity packages can retain official product information, multiple versions, personal tags and real covers. Optional collection verifies official product identities, preserves personal edits and supports resumable batch collection. Groups, references and metadata use verified server records with explicit conflict handling; live SQLite databases stay on the device.

## Present and work with Design Studio

Full-screen preview fits the artboard without restarting interactions. Desktop presenter mode adds a separate audience display, a live controller preview, private speaker notes, step navigation, blackout and reconnection. Notes remain in project history and are excluded from audience/export output.

Design MCP reads now offer paginated summaries and targeted page/node/resource source reads, with compact mutation receipts. Server-side design asset imports avoid unnecessary byte round trips. Note saves acknowledge committed content before background metadata work, fixing a save-response deadlock.

## Upgrade and compatibility

1. Back up the vault and keep the existing app-owned metadata, pending-upload queue and recovery files. Fully quit LeafLoom before replacing the app.
2. Install the package for your platform, reopen the same vault and allow credentials and directory checkpoints to initialize. Existing server IDs, roots, upload folders and metadata bindings are retained.
3. Refresh the tool list in MCP clients after updating. Source checkouts should update their code and use **Restart LeafLoom**; Dev and installed builds share the same profile.

Windows x64 and macOS 14+ Apple Silicon are the supported installer targets. Windows packages are unsigned; macOS uses ad-hoc signing without Apple notarization. Check `SHA256SUMS.txt` and the linked native build reports. CI does not certify every NAS, VPN or physical display setup; Windows presenter hardware coverage remains separate.

[Attachment guide](help/attachments.md) · [User guide](GUIDE.md) · [Full changelog](../../CHANGELOG.md)
