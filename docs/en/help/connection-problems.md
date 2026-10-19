# Troubleshoot AI, MCP, Tunnel and Feishu

## Your goal

Identify the failing layer before changing accounts or permissions.

## Before you start

Record connection type, version, redacted errors and recent updates or credential rotation.

## Steps

1. AI Chat: verify the CLI runs and is signed in; restart after PATH changes.
2. Local MCP: check endpoint, dedicated credential and its read grant; refresh tools after updates.
3. Tunnel: check ID, Runtime App Key and channel state, with only one managed instance per configuration.
4. Feishu: check CLI authorization, then access to the actual document/table. `leafloom_mcp` indicates local authorization; `feishu_cli` indicates upstream errors.
5. After write timeouts, uncertain results or partial success, read the actual resource before retrying.

## What to expect

Client caching, local grants, channel readiness and Feishu resource errors can be handled separately.

## If it does not work

Keep configs/tokens private and avoid granting all writes for diagnostics. Verified account/channel status does not prove resource access.

## Next steps

- [Connect a local CLI and chat with AI](ai-chat.md)
- [Connect local MCP clients and Skills](mcp.md)
- [Connect ChatGPT through a Tunnel](chatgpt.md)
- [Connect Feishu and Lark](feishu.md)
