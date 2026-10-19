# Understand local data and external access

## Your goal

Know when content stays local and when it reaches another service.

## Before you start

Distinguish local browsing, selected retrieval, AI references and full MCP permissions.

## Steps

1. Reading, graphs and retrieval run locally; initial model downloads need the network.
2. Review selections, the current-note switch and retrieval references before sending an AI question. Your provider may receive them.
3. MCP results reach the calling client. Full read permission covers notes outside RAG.
4. Feishu operations access cloud resources without automatically syncing them to local notes.
5. Keep credentials/backups private and do not expose the local port as a public multi-user service.

## What to expect

Local/Tunnel, note/Feishu and write scopes are separate. The public help center is static and cannot read your vault.

## If it does not work

Review untrusted HTML and scripts even on isolated origins. Access boundaries do not replace OS account protection and backups. See [technical boundaries](../../SECURITY.md).

## Next steps

- [Manage MCP permissions and credentials](permissions.md)
- [Back up notes, comments and recovery data](backup.md)
- [Connect a local CLI and chat with AI](ai-chat.md)
