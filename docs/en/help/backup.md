# Back up notes, comments and recovery data

## Your goal

Protect original files and user records that cannot be rebuilt from an index.

## Before you start

Save notes and AI drafts, pause external edits/sync, then quit normally.

## Steps

1. Back up the complete vault, including hidden `.vault-rag/`, attachments, HTML and design projects.
2. `.vault-rag/annotations.sqlite` stores comments/highlights. History, trash and attachment-migration originals are recovery data, not disposable caches.
3. Private settings, models, credentials and AI history live in Windows `%LOCALAPPDATA%\VaultRag` or Mac `~/Library/Application Support/VaultRag`, unless customized.
4. Export any unique unsaved browser/desktop drafts separately and check backup readability.
5. Restore to a new local folder for inspection before replacing existing material.

If you use attachment servers, also back up the original files in every server root used by the vault, including originals outside the current upload folder, and each configured server metadata directory. Keep the storage ID, relative paths and metadata directory mapping so existing note links can still resolve. A migrated original may exist only on the server; thumbnails, local caches and the catalog are not substitutes.

Check a restore in a separate vault and, for server attachments, against a separate restored server copy with empty client caches. Open a local original and a server-only original from their existing note links and compare their SHA-256 checksums with the originals. If you use attachment groups or covers, check that they also appear. A visible thumbnail alone does not verify the original.

## What to expect

A complete backup protects both the originals and user records. Local indexes and trash are not an off-device backup.

## If it does not work

OS-encrypted credentials may need reauthorization on another computer. Keep credential-containing backups private.

## Next steps

- [Restore note history and recycled files](recovery.md)
- [Organize attachments and recover a task](attachment-organization.md)
- [Understand local data and external access](privacy.md)
