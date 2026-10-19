# Manage MCP permissions and credentials

## Your goal

Control exactly which resources each connection can read or write.

## Before you start

Distinguish local AI from the ChatGPT Tunnel. Writing starts disabled for both.

## Steps

1. Select the connection in **Settings → AI connections → MCP access permissions**.
2. Enable note or Feishu reading as needed, and writing separately. Full note access includes notes outside RAG selection.
3. Copy the dedicated local configuration when first shown and keep it private in the intended client.
4. Feishu high-risk operations need their own switch and explicit confirmation for each operation.
5. Update clients after rotating credentials. Disabling every resource or regenerating credentials revokes the old credential.

## What to expect

Disabling one resource blocks it immediately while other granted resources can remain available. Legacy clients do not gain full access automatically.

## If it does not work

For authentication errors, verify the client and credential. Do not enable all writes as a diagnostic shortcut. MCP credentials do not log in to the web UI or Feishu.

## Next steps

- [Understand local data and external access](privacy.md)
- [Connect local MCP clients and Skills](mcp.md)
- [Connect ChatGPT through a Tunnel](chatgpt.md)
