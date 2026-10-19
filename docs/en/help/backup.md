# Back up notes, comments and recovery data

## Your goal

Protect original files and user records that cannot be rebuilt from an index.

## Before you start

Save notes and AI drafts, pause external edits/sync, then quit normally.

## Steps

1. Back up the complete vault, including hidden `.vault-rag/`, attachments, HTML and design projects.
2. Versions with the upcoming [annotation feature](annotations.md) also store comments/highlights in `.vault-rag/annotations.sqlite`. History, trash and attachment-migration originals are recovery data, not disposable caches.
3. Private settings, models, credentials and AI history live in Windows `%LOCALAPPDATA%\VaultRag` or Mac `~/Library/Application Support/VaultRag`, unless customized.
4. Export any unique unsaved browser/desktop drafts separately and check backup readability.
5. Restore to a new local folder for inspection before replacing existing material.

## What to expect

Your backup includes originals and user records. Local indexes and trash are not an off-device backup.

## If it does not work

OS-encrypted credentials may need reauthorization on another computer. Keep credential-containing backups private.

## Next steps

- [Restore note history and recycled files](recovery.md)
- [Organize attachments and recover a task](attachment-organization.md)
- [Understand local data and external access](privacy.md)
