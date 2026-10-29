# File operations and recovery records

## Your goal

Rename, move or recycle supported attachments with reference checks, and keep recovery records from earlier versions.

## Before you start

Back up the vault before structural changes. In [0.1.5](../RELEASE_NOTES_0.1.5.md), migration and organization entry points are hidden; server settings only manage connections. A destination change does not migrate existing originals. See [attachment browsing](attachments.md).

## Steps

1. Select supported files in Attachments and choose rename, move or recycle. Review the proposed destination, discovered note references, file versions and protected resources before confirming.
2. Project resources and unsupported server operations remain unavailable; do not force them through another attachment action. Incomplete dependency discovery does not prove that a file has no references.
3. Keep previous `.vault-rag/attachment-migrations/<job-id>/` records, retained originals/note backups and `.vault-rag/trash/` while recovery may still be needed. The hidden UI does not delete these records or automatically restart a migration.
4. Preserve device-private application state, including unsent uploads, server reference mappings and metadata. Do not copy live SQLite databases between devices or delete the whole state folder as a cache. Contact the project with the task ID and sanitized diagnostic when a legacy task needs manual recovery.

## What to expect

Only a confirmed, supported operation changes a file. Available actions recheck revisions and boundaries. Changing the server used for new attachments leaves old originals and metadata bindings in place.

## If it does not work

Stop when a preview reports changed versions, ambiguous references, protected resources or an unavailable server capability. Keep recovery materials and retry only after resolving the cause. Download-cache cleanup is not a backup and does not remove NAS originals.

## Next steps

- [Browse and download attachments](attachments.md)
- [Back up the vault and recovery files](backup.md)
