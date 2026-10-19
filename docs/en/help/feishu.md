# Connect Feishu and Lark

## Your goal

Use cloud documents and Base through an externally configured lark-cli.

## Before you start

Prepare the official lark-cli, an authorized account and a disposable test document.

## Steps

1. Install, configure and log in to [official lark-cli](https://github.com/larksuite/cli) separately. Its credentials stay with the CLI.
2. Open **Settings → AI connections → Feishu / Lark**, enable integration, optionally enter a native executable path and CLI profile, then save and select **Verify connection**. A blank path uses automatic detection.
3. In **MCP access permissions**, enable Feishu reading and, if wanted, writing separately for local AI clients and Tunnel. Copy the dedicated local connection configuration when first enabled; refresh the client's tools after a backend update.

4. Ask your AI client to inspect the installed CLI help and embedded Skill, then use the generic read/write tools for documents, Base and other business commands. Block edits support XML headings and rich structure. Document updates need the revision returned by reading. A verified account does not guarantee access to every resource.
5. High-risk commands and raw API calls require the separate local/Tunnel **high-risk** switch (off by default), plus explicit confirmation of each operation. Turning off read or write also turns off high-risk access.
6. Transfer attachments with temporary file IDs and chunked upload/download. Importing an existing connected file additionally needs note-read permission. After upgrading, refresh the client tool list: the four previous document/Base tools are replaced by CLI discovery, read/write execution and file transfer.

Tunnel conversations share the permissions configured for that Tunnel connection. LeafLoom authenticates its runtime separately from a conversation's connector bearer; changing chats does not require a permission refresh or reconnect. Disabling a resource still revokes access immediately.

Dev and the installed app use the same saved Tunnel configuration and application lifecycle: connect on startup when enabled, stop on Quit. Dev reuses the registered installation's runtime when available. One shared-directory owner is allowed; do not also run a standalone tunnel-client for the same connection. MCP authorization errors identify `leafloom_mcp`; they do not require Feishu reauthorization. For Base tables, use an ID returned by the table list, rather than an unverified URL query value.

Connection status distinguishes missing/incompatible CLI, missing configuration/login, expired login and network problems. Complete setup or reauthorization externally, then verify again. Cloud operations need network access and return requested content to the calling AI. They do not automatically import or index it in your local knowledge base. See [capabilities and limits](../../FEISHU.md).

## What to expect

Connection status and read/write permissions are separate. Cloud content does not automatically become local notes.

## If it does not work

Verified login does not prove resource access. Read the result before retrying a timeout or partial write.

## Next steps

- [Manage MCP permissions and credentials](permissions.md)
- [Troubleshoot AI, MCP, Tunnel and Feishu](connection-problems.md)
- [Understand local data and external access](privacy.md)
