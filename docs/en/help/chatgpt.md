# Connect ChatGPT through a Tunnel

## Your goal

Connect explicitly authorized local capabilities to ChatGPT.

## Before you start

Prepare an existing Tunnel ID and Runtime App Key with Tunnels Read + Use. Keep the key out of notes.

## Steps

1. In the desktop app, open **Settings → AI connections → ChatGPT connection**.
2. Enter the Tunnel ID and Runtime App Key, then choose **Save and connect**. Installers include the runtime.
3. When ready, add a custom MCP server in ChatGPT using Tunnel, the same ID and No authentication; enable it in the chat.
4. Separately grant note/Feishu read and any required write scopes in LeafLoom.
5. Make an actual tool call using fictional material and check returned capabilities and content.

## What to expect

The connection stays active in the tray; Quit stops it. Readiness alone does not prove a successful tool call.

## If it does not work

Use one managed runtime per shared configuration. Refresh client tools after permission changes. Disconnect disables automatic connection.

## Next steps

- [Manage MCP permissions and credentials](permissions.md)
- [Connect local MCP clients and Skills](mcp.md)
- [Troubleshoot AI, MCP, Tunnel and Feishu](connection-problems.md)
