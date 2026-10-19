# Connect local MCP clients and Skills

## Your goal

Allow other AI clients to read or edit notes with explicit permissions.

## Before you start

Connect a local folder first. Practise in the demo vault if you prefer.

## Steps

The existing workspace read/write switches include attachments. After restarting an updated backend, refresh both local clients and the LeafLoom ChatGPT plugin tools. `vault_files` provides search, metadata, original-byte reads, ZIP downloads and task status; `vault_files_update` provides chat/local uploads, move/rename, trash, organization, index maintenance and task control. Inspect a plan before confirming it with the current task revision. Uploads preserve duplicate names and return links without editing notes automatically. See the [file tool contract](../../MCP.md#general-file-tools).

Open **Settings → AI connections → MCP access permissions**. Enable local AI reading and copy the generated connection configuration. Its dedicated credential is shown once. Use `http_headers.Authorization` in Codex, `headers.Authorization` in Cursor, and `type: http` plus `headers.Authorization` in Claude Code. Regenerating the credential or disabling all its resource scopes revokes it; keep configurations private.

Enable **Allow local AI to modify notes** separately for direct saves. For ChatGPT, use the existing Tunnel connection and its separate **read all notes** and **modify notes** switches. Permission changes automatically reconnect the Tunnel; refresh the tool list in your client. Writing is off by default for both connections.

Full access covers all connected Markdown, TXT and HTML/HTM notes, including archives and notes outside RAG. It supports finding, reading, creating, precise edits, properties, moves, recoverable deletion, history, links, templates and daily notes. RAG still uses only selected eligible Markdown/TXT. HTML is read and edited as source. Existing unauthenticated loopback and legacy bearer connections retain the original five read-only capabilities; the old `auth-token` does not unlock full access.

Every mutation checks the workspace revision; existing notes also require their read-time version. Moves and deletes first return an impact preview; history and Trash can be previewed and restored. MCP reads saved files, preserves conflicting editor drafts and reports pending indexing separately from successful saves. The browser assistant keeps its proposal workflow for notes. Managed designs use `design_document`, `design_operations` and the design history, asset, library and export tools with the connection's read/write permissions.

**Settings → Skill → Install skill** installs `wiki-search` instructions and does not configure MCP. See the [complete tool contract](../../MCP.md).

## What to expect

Full workspace access is independent of RAG scope; installing a Skill does not configure MCP.

## If it does not work

Reload clients after updates or credential rotation and inspect the actual capabilities returned by status.

## Next steps

- [Manage MCP permissions and credentials](permissions.md)
- [Connect ChatGPT through a Tunnel](chatgpt.md)
- [Connect Feishu and Lark](feishu.md)
