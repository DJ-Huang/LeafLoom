# Optional AI connections

[English](AI.md) · [中文](../zh-CN/AI.md) · [日本語](../ja/AI.md)

LeafLoom's browser, editor, graph and local retrieval do not require external AI. The optional assistant uses an already installed and signed-in Codex or Codely CLI. It does not ask you to enter API keys into LeafLoom.

## Browser assistant

Install your chosen CLI following its official instructions and sign in from a normal terminal. Open **AI chat**, choose the provider, and reconnect if necessary. Select text in a note, then choose **Add to AI chat**. Review the reference cards and the **Current note** checkbox before sending. The configured model service may receive your question, selected text, current note and retrieved evidence.

Chats are organized by topic and stored in the app's private configuration directory. **Stop** keeps received text. Refresh/restart reconnects to existing history without automatically resending a question. Keep the CLI's own native conversation records for restoration.

## Review edits before saving

Inspect the proposed difference. **Accept into draft** changes the editor, not the saved file. AI drafts and subsequent manual edits pause autosave until you choose **Save draft** or `Ctrl/⌘+S`. **Discard draft** restores the disk version after confirmation. Creating a proposed note requires confirmation and does not overwrite an existing file.

If the note, draft or saved version changed, regenerate or merge manually. LeafLoom preserves conflicting drafts rather than silently replacing the file.

## Connect another AI client through MCP

The local HTTP MCP endpoint is `http://127.0.0.1:18080/mcp`, or the port in your private config. Use a bearer token from the private `auth-token` file. Keep it out of commits, screenshots and shared messages.

- Codex: configure `url` and `http_headers.Authorization`.
- Cursor: configure `url` and `headers.Authorization`.
- Claude Code: use `type: http`, `url` and `headers.Authorization`.

The authorization value is `Bearer <LOCAL_TOKEN>`. Use placeholders in shared examples. **Settings → AI integration → Install skill** installs the bundled `wiki-search` instructions; it does not configure MCP for you.

The tools expose scoped knowledge search, rule search, chunks, full notes and index status. Search scope still controls what can be retrieved. For the complete tool contract, see the source in `vault_rag/web_server.py`.

## Troubleshooting

If a CLI is missing, verify it works in your terminal and restart the service so it sees the current PATH. Renew expired login through the CLI. If conversation restoration fails, keep the local history and resolve the underlying CLI/session problem; do not delete your notes to repair a chat.

![Fictional AI demonstration](../../assets/screenshots/en/06-ai.png)
