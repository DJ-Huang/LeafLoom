# Complete note access over MCP

The production Streamable HTTP endpoint remains `http://127.0.0.1:18080/mcp`
(port follows configuration). Existing clients retain the original five read-only
capabilities. The internal assistant's `/ai-mcp` still uses its own session and
proposal workflow.

## Enable access

In **Settings → AI connections → Full note access (MCP)**, enable local access and
copy the generated configuration into your client. This dedicated credential is
shown once; regenerating or disabling it revokes the previous credential. The
saved access file contains only its hash. For Codex, use the configuration's URL
and put its Authorization header in `http_headers`; Cursor/Claude use `headers`
(Claude also uses `type: http`). Shared examples must use placeholders.

Enable ChatGPT access separately. The existing desktop Tunnel automatically
reconnects with a private, runtime credential for discovery and tool calls; do
not paste that credential into ChatGPT. Refresh the client tool list after
updating LeafLoom. Both connections start with write access disabled. Their
separate write switches allow direct saves, with history and recoverable trash.
The MCP credentials cannot authenticate browser management APIs. Bad credentials
are rejected even from loopback; they never fall back to anonymous access.

Full workspace access includes Markdown, TXT and HTML/HTM throughout the connected
folder, including archives and unselected notes. Hidden/protected directories,
links/junctions and paths outside the folder remain inaccessible. HTML is source
text, not executed by the tools. RAG continues to use only selected, eligible
Markdown/TXT; neither full access nor saving a note expands that selection.

## Tools

| Workflow | Tools |
| --- | --- |
| Legacy retrieval | `vault_search`, `rule_search`, `vault_get_chunk`, `vault_get_note`, `vault_index_status` |
| Browse and read all notes | `vault_list_directory`, `vault_find_notes`, `vault_read_note`, `vault_query` |
| Create and edit | `vault_create_note`, `vault_update_note`, `vault_update_properties`, `vault_create_folder` |
| Organize and trash | `vault_move`, `vault_delete` |
| Preview and recover | `vault_list_records`, `vault_read_record`, `vault_restore` |
| Markdown relationships | `vault_links`, `vault_graph` |
| Templates and diary | `vault_list_templates`, `vault_daily_note` |
| Design Studio | `design_list_projects`, `design_get_project`, `design_create_project`, `design_upsert_screen`, `design_update_layers`, `design_check_project` |
| Synchronize | `vault_reindex` |

`vault_index_status` adds `workspace_revision`, supported formats and the caller's
`capabilities`. `vault_get_note` preserves its retrieval-scoped meaning; use
`vault_read_note` for full workspace access. Tool definitions are in
[`mcp_tools.py`](../vault_rag/mcp_tools.py); workflows use
[`note_operations.py`](../vault_rag/note_operations.py) and
[`design_studio.py`](../vault_rag/design_studio.py) with the same durable file
operations as the browser.

Design Studio tools inspect and mutate 1.1.0 design projects inside the connected
vault: `design_list_projects` and `design_get_project` inspect project manifests,
screens and layer transforms; `design_create_project` scaffolds a new `1.1.0`
project in any vault directory and registers its HTML project; `design_upsert_screen`
creates or updates screen HTML artboards and rebuilds the portal; `design_update_layers`
merges or replaces `Design/layer-transforms.json` and `Design/layer-transforms.js`
using `workspace_revision`; and `design_check_project` runs structural and
layer-review validation.

Lists and operation impact previews default to 50 results (maximum 200) and return `next_cursor`.
Record previews use `path_limit`/`path_cursor` for affected paths and `offset`/`limit` for text. Cursors are
bound to the query, workspace and result generation; `stale_cursor` means restart
pagination. Note/record text uses character offsets, defaults to 12,000 characters
(maximum 24,000) and returns `next_offset`. The existing 10 MiB text-file limit
still applies. Unreadable/oversize search sources are explicitly reported as
`content_unavailable`, with `incomplete: true`.

`vault_find_notes` searches path, title and source keywords, with optional folder,
AND-tag and format filters. It needs no model. `vault_query` uses the existing
safe Markdown TABLE/LIST grammar, including FROM/WHERE/GROUP BY/SORT/LIMIT; it
does not execute SQL or scripts. Graphs are local to a note, with only edges
whose endpoints appear on the returned page, capped at 200 with `links_truncated`
when necessary; use `vault_links` to paginate all incoming/outgoing edges.

## Editing contract

1. Read `workspace_revision` from status or a note. Every mutation requires it;
   switching folders or changing the workspace configuration invalidates it.
2. For existing notes, pass the read-time `revision` as `expected_revision`.
   `vault_update_note` supports `replace` (the complete source, including YAML),
   `append` (literal text), or `edit` with `[{"old_text":"before","new_text":"after"}]`.
   Every old string must match exactly once in the original source; edits must
   not overlap. A failed edit saves nothing. Re-read and merge after conflicts.
3. `vault_create_note` takes `text` OR a listed `template` in an existing folder;
   it never overwrites a name. `vault_update_properties` is Markdown-only;
   `null` removes a property. BOM, line endings, unknown YAML and comments are
   preserved by the shared save layer. A prior version is kept in history.
4. Moving or deleting first calls the tool with `dry_run: true` (the default).
   Inspect `affected_paths`, then call with the same arguments, `dry_run: false`
   and the returned `operation_token` within five minutes. Affected content or
   link changes invalidate the token. Folder operations include attachments and
   reject protected/hidden/link/special entries. No permanent-delete tool exists.
5. To restore, first use `vault_read_record`, then pass its `workspace_revision`,
   `record_revision` and `expected_revision` to `vault_restore`. Occupied trash
   destinations, changed backups and edits after a completed move block unsafe
   restoration. Incomplete move journals require inspecting their conflict paths
   and manual recovery; rollback never intentionally replaces newer external edits.

`vault_daily_note` uses an optional ISO date, defaulting to the computer's local
date; an existing daily note is returned unchanged. It uses the configured daily
folder and daily template. `vault_reindex` queues work and returns immediately.

The tools operate on disk content, not unsaved editor drafts. A saved result has
`saved: true` and a new `revision`; `index_pending` means vector synchronization
has not been certified for that change. The UI receives file events and keeps
conflicting drafts. First global metadata loading returns `metadata_pending`
with a retry interval instead of reporting an incomplete empty result. Semantic
retrieval reports its existing `degraded` reason when the model/index is missing.

New results include matching JSON text and `structuredContent`. Business errors
set `isError: true` and an `error_code`, including `permission_denied`,
`write_conflict`, `ambiguous_note`, `not_found`, `metadata_pending` and
`stale_cursor`. Read-only and modifying tools carry MCP annotations; enforcement
is always server-side.

## Local validation

The isolated HTTP workflow cases are in `tests/test_workspace_mcp.py`; Tunnel
credential injection and lifecycle cases are in `tests/test_tunnel.py`. These use
fictional notes, credentials and a local mock control plane. Real ChatGPT tool
discovery/write acceptance and native Windows validation must be reported
separately; passing the local tests does not certify either.

Observed on macOS Apple Silicon, 2026-10-16: all 39 focused Python cases in
`test_workspace_mcp`, `test_local_knowledge`, `test_tunnel` and `test_browsing`
passed, including the bundled Tunnel runtime against a local mock control plane.
Two focused authentication/move cases also passed after non-ASCII credential
handling was hardened. TypeScript checking, the frontend production build and
translation generation passed (874 entries, no missing translations).

Installed application check on the same date: the macOS frontend, application
wheel and Electron package were rebuilt, installed and launched. The running
HTTP endpoint discovered all 23 tools; legacy status returned the new workspace
revision and capability fields. With full access disabled, new read/create calls
returned structured `permission_denied` errors without touching notes, and an
invalid credential returned HTTP 401. The existing local Codex connection reached
the updated service, but its active-session tool inventory still contained five
tools. The installed ChatGPT LeafLoom plugin was refreshed and its status call
succeeded, but still returned the older status shape; no desktop Tunnel was
configured for this installation. Full-access ChatGPT discovery/write acceptance,
native Windows acceptance and comprehensive visual UI acceptance remain pending.

Subsequent authorized local acceptance on 2026-10-16 enabled full local read/write
access and updated the existing Codex connection with its dedicated credential.
Using that configuration against the installed HTTP service discovered 23 tools
and returned `connection: local` with both workspace permissions enabled. One
uniquely named temporary note completed create, exact-text edit, trash preview and
commit, record preview, restore and final read. After metadata preparation, a
post-delete read returned `not_found`; restored text matched the edited text
exactly. The restored temporary note was retained for inspection. The already
running Codex session continued using its previous credential and five-tool
inventory, so client reload is still required. ChatGPT Tunnel setup/acceptance
was excluded from further work at the user's request.
