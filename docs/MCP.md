# Complete note access over MCP

## Annotation and comment MCP tools

When the connected vault permits local note access, `vault_list_annotations(path)` retrieves Markdown/TXT highlights and independent comment threads. Explicit note-write permission is required for `vault_add_annotation(path,workspace_revision,kind,content,anchor,etag,color)`, `vault_reply_annotation(path,annotation_id,content,workspace_revision,parent_id)`, and `vault_set_annotation_status(path,annotation_id,revision,workspace_revision,status)`. Page comments need no text anchor; inline comments require a current raw file etag and UTF-16 source quote/position/context. The note is never automatically edited, and annotation text is never automatically added to RAG. See [annotation design](ANNOTATIONS.md).

The production Streamable HTTP endpoint remains `http://127.0.0.1:18080/mcp`
(port follows configuration). Existing clients retain the original five read-only
capabilities. The internal assistant's `/ai-mcp` still uses its own session and
proposal workflow.

## Enable access

In **Settings → AI connections → MCP access permissions**, enable local note access and
copy the generated configuration into your client. This dedicated credential is
shown once; regenerating it or disabling all resource scopes revokes the previous credential. The
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

The owned Tunnel runtime sends its in-memory credential in `X-LeafLoom-Tunnel-Authorization`, independently of chat-specific `Authorization`. This prevents connector bearer headers from overriding the runtime credential and changing permissions between conversations. Both the HTTP boundary and each tool validate the proof against the current secret and actual loopback peer; invalid or revoked proofs are rejected without legacy fallback. Resource/write grants remain checked on every operation. This header does not authenticate browser APIs.

Full workspace access includes Markdown, TXT and HTML/HTM throughout the connected
folder, including archives and unselected notes. Hidden/protected directories,
links/junctions and paths outside the folder remain inaccessible. HTML is source
text, not executed by the tools. RAG continues to use only selected, eligible
Markdown/TXT; neither full access nor saving a note expands that selection.

Note writes acknowledge durable file/history changes with `saved:true` and the committed revision before catalog/attachment maintenance. Catalog updates use the existing runtime queue; they never run synchronously while note workflows hold configuration/file locks. Exact-path reads and revision-checked writes do not wait for catalog preparation. Global metadata queries can return `metadata_pending` until their background refresh finishes; retry the query, not an already successful mutation. `index_pending` remains the existing search-index eligibility/pending hint, not a persistence status.

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
| Managed design editing | `design_document`, `design_operations`, `design_history`, `design_import_asset` |
| Shared design library and export | `design_library`, `design_publish_library`, `design_import_library`, `design_export` |
| Synchronize | `vault_reindex` |
| General file reads and downloads | `vault_files` |
| General file uploads and management | `vault_files_update` |
| Feishu account | `feishu_status` |
| Feishu command discovery | `feishu_cli_inspect` |
| Feishu business commands | `feishu_cli_read`, `feishu_cli_write` |
| Feishu temporary files | `feishu_files` |

The surface includes note and Design Studio workflows, two general file tools,
and five optional Feishu tools. Configure the external CLI in **Settings → AI connections → Feishu / Lark**,
then grant Feishu reading/writing independently for local and Tunnel connections.
These scopes share each connection's dedicated credential; disabling note access does
not revoke separately granted Feishu access. Legacy clients gain no Feishu privileges.
See [Feishu setup and tool contract](FEISHU.md). Historical validation counts below
refer to the builds in which they were recorded.

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

New managed projects use `Design/studio/project.json`. `design_document` defaults
to a compact page manifest with stable IDs, resource counts, the project revision
and `workspace_revision`. It returns 20 entries per page (maximum 100), with
`total`, `offset` and `next_offset`. Summary rows share a 12,000-character budget;
follow `next_offset` even if fewer than `limit` entries arrive. No HTML, CSS,
script source, component trees or full resource tables are included by default.
`manifest=true` is an alias for this default and cannot be combined with selectors.

- Pass `page_id` to list flat node summaries, including `parent_id`, `child_count`
  and a short text preview. IDs remain exact; names and previews can be shortened.
- Set `section` to `assets`, `components`, `styles` or `scripts` to list resources.
- Set `full=true` with `page_id` to read only that complete page (`pages` array),
  or add `node_id` to read only that node/subtree (`nodes` array). Full `nodes`
  reads require `node_id` to avoid repeating nested subtrees.
- Set `full=true` with `section` and `item_id` to read exact resource source in
  that section's array. Full resource reads can also paginate the section.
- `full=true` without selectors explicitly returns the canonical `document`.
  Only this complete source is suitable for `document.replace`. Summary and
  selected-page responses are partial views, not replacement documents.

Carry the first response's `revision` as `expected_revision` when paging; a
changed design returns `write_conflict` instead of mixing different versions.
Exact source reads are intentionally unrestricted by the summary character
budget, so request only the page, node or resource needed for an edit.

`design_operations` requires the current `expected_revision`,
`workspace_revision` and a unique `operation_id`. Its `type`-discriminated batch
is one atomic undo step. It edits page/node structure, layout, text, asset
references, components, scripts and animation settings. Identical request retries
reuse their receipt; stale versions and conflicting operation IDs save nothing.
Design operations, undo/redo, asset imports and library imports now default to
short revision/history receipts. Asset imports also return the imported `asset`.
Use `include_document=true` to recover their previous full-document responses.
`design_get_project` also omits the managed document by default and accepts the
same opt-in. HTTP editor responses keep their existing contract. These defaults
apply to both public `/mcp` and the design tools available through `/ai-mcp`;
restart the updated backend and refresh the client's tool schema before use.

`design_history` pages persistent history or executes versioned undo/redo;
`design_import_asset` accepts exactly one source: `source_path` for a file relative
to the connected vault, `source_file_id` for an owned `feishu_files` / CLI download,
or the existing `data_base64`. Prefer file references for videos and other large
assets: the service copies and hashes the original locally instead of sending it
out through MCP and uploading it again. Paths are on the **service host**, must
remain inside the connected vault, and cannot traverse links or hidden/protected
directories. Temporary IDs require current Feishu read permission, the same
credential owner, a complete file and valid original-source access. Optional
`expected_sha256` pins the input bytes; changed files, stale revisions and source
mismatches save no asset. The 128 MiB asset limit remains; HTTP clients/proxies can
reject much smaller Base64 request bodies before this limit is checked.

The default `include_document:false` returns only the asset, revision, workspace revision
and undo state, without returning the complete project after every media import.
Set it to `true` only when the whole document is needed. For example, call
`design_import_asset` with:

```json
{
  "directory": "Projects/Training",
  "name": "sky.mp4",
  "source_path": "Projects/Training/SourceMedia/sky.mp4",
  "expected_revision": "<design_document revision>",
  "workspace_revision": "<current workspace_revision>",
  "operation_id": "import-sky-unique-id",
  "include_document": false
}
```

For a Feishu download, replace `source_path` with `source_file_id` returned by
`feishu_cli_read`; there is no need to call `feishu_files.get` to transfer the
bytes back to the caller. Import still registers one undoable operation, and
original bytes are retained when registration is undone. `design_library` lists published personal items;
`design_publish_library` publishes a versioned component/asset/style/script and
`design_import_library` explicitly imports or updates it with local dependency
copies. `design_export` creates an independent HTML ZIP. Optional `page_ids` limits the export to selected pages and their detected dependencies; omitted retains the full-project behavior. An optional `expected_revision` rejects stale exports. Script-generated references require manual review. Reading requires full
note access; modifying tools use the connection's separate note-write grant.
The legacy tools remain compatible, with managed-project adapters preserving
version checks and transaction history.

The built-in assistant's `/ai-mcp` exposes `design_document` and
`design_operations` too: managed design operations apply directly and remain
undoable. Existing note-edit proposals keep their workflow. Send stable selection
IDs and read revisions before each batch; on conflict, re-read and merge rather
than overwriting new content. See [Design Studio](DESIGN_STUDIO.md) for the full
document, command and `mount(ctx)` script API, export boundaries and validation.

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

## General file tools

Local MCP and the LeafLoom ChatGPT plugin discover the same two tools. Existing
workspace grants now cover notes, designs and attachments; Feishu grants remain
separate. Legacy retrieval credentials gain no file access. Refresh the client
tools after restarting the updated backend (rescan a plugin's tool snapshot if
the host requires it). Inspect `vault_index_status.capabilities` to verify the
actual connection grants.

Both tools take `workspace_revision` and a typed `request` object. Reads use
`vault_files`; writes use `vault_files_update`, which also requires a unique
`operation_id`. Unsupported actions/fields are rejected. Identical write retries
reuse a receipt; reusing an ID with different arguments is a conflict.

| Tool | `request.action` | Parameters and result |
| --- | --- | --- |
| `vault_files` | `list` | Optional `query`, `kind`, `sort`, `order`, `limit`, `cursor`, `source` (`all`, `local`, `remote`), `storage_id` (one server UUID or `local`), `tags`, `category`; searches paths and attachment metadata, not OCR or file bodies. Defaults: modified descending, 50 items, maximum 200. |
| `vault_files` | `stat` | Exactly one `path` or `asset_id`, optional `source_note`; returns file `revision`, storage identity, metadata, protection status, Markdown link and image embed when applicable. |
| `vault_files` | `read` | Exactly one `path`, `asset_id` or ZIP `job_id`, `expected_revision`, optional byte `offset`/`limit`; returns Base64 bytes, `next_offset`, `eof`. Default 64 KiB, maximum 256 KiB. |
| `vault_files` | `export` | `paths` (1–100); prepares a private ZIP task. |
| `vault_files` | `status` | Without `job_id`, pages tasks and returns index/limits. With an ID, reads that task. Operation `section=moves/references/blockers/exclusions/results` returns a complete paginated `page`. |
| `vault_files_update` | `upload` | `source=files/base64/begin/chunk/commit/abort`; see below. |
| `vault_files_update` | `move` | `paths`, `destination`; `destination_kind=folder` by default. Use `path` with one source to rename or move to an exact filename. Prepares a plan. |
| `vault_files_update` | `trash` | `paths` (1–100); prepares a recoverable recycle plan without removing note links. |
| `vault_files_update` | `organize` | Optional `destination` (default `_attachments`); prepares a consolidation plan. |
| `vault_files_update` | `metadata` | Exactly one `path` or `asset_id`, current metadata `expected_revision`, and `tags`, `category`, `description`; changes durable metadata without editing the original. |
| `vault_files_update` | `reindex` | Starts background attachment index initialization/refresh; optional remote `storage_id` scans that configured server's metadata. |
| `vault_files_update` | `job` | `job_id`, `command=execute/cancel/resume/undo`. Operations except cancel require current `expected_revision` and explicit `confirm=true`. Other job types support cancel. |

For example, after obtaining a current workspace revision:

```json
{"request":{"action":"list","query":"report","kind":"pdf"},"workspace_revision":"<current-workspace-revision>"}
```

Server attachment builds combine the local index with configured WebDAV sources.
`asset_id` and `storage_id` identify assets without exposing a server password or
session. Old LeafLoom paths and recorded local asset IDs continue to resolve after
an approved migration. Metadata lives independently of downloadable caches.
`list.summary.by_source.local` and `.remote` report original file counts and
bytes within the selected source scope; cache usage is separate in `status`.
After a successful complete server scan, absent snapshot entries are hidden only
when additional HEAD requests confirm 404/410. Interrupted, unauthorized or
incomplete scans preserve existing entries. Missing assets retain their identity,
tags and old paths; `stat` reports `state=missing`, while content reads return
`remote_asset_missing` rather than old cached bytes. A reappearing path keeps its
identity but invalidates the previous content generation. Server refresh returns
`scan_id`; `status.attachment_storage.sources[].connection.scan_state` is the
independent scan lifecycle, with `scan_scanned`, `scan_missing` and `scan_excluded` counts. A healthy
connection alone does not prove scan completion.
Remote discovery excludes Markdown, HTML and explicit source/script extensions by
default, while retaining text/data and design resources. A server directory may
contain a UTF-8 `leafloom.ignore` whose first line is `# leafloom-ignore v1`;
subsequent gitignore-style patterns and `!` rules override defaults and ancestors.
Directories are still visited so child rule files can override parent exclusions.
Only a complete, validated scan commits exclusion changes. Excluded entries do
not appear in `list` or its size/count summaries; `stat` reports `state=excluded`,
and old IDs/paths can still read their content and cache. Exclusion does not imply
missing, remove metadata, clear caches or change note/retrieval scopes. Invalid,
oversized, inaccessible or changing rule files fail the scan and preserve the old
exclusion state. Control files are never attachments.
`version_state=strong_etag` denotes a strong server validator; `weak_metadata`
means one is unavailable. SHA-256 can be unknown for the current version; a
historical migration receipt is not proof of its current contents. Uncached reads
check HEAD metadata, and a changed revision requires another `stat` before reading.
Omitted directory-listing ETags do not erase known validators for an unchanged
size and modification time. `status.attachment_storage` reports redacted source,
scan, cache and outbox state. Remote move, rename, trash and ZIP export are not
supported by this first adapter.

The disk cache defaults to 2 GiB per workspace and can be adjusted in Attachment
Storage settings. For the optional Zspace official desktop forwarding adapter,
keep both the official client and its attachment remote-access window open.
After restarting that client, reopen the window and update the configured address
if its local forwarding port changes; unattended bridge recovery is not guaranteed.

### Uploads

ChatGPT uploads use `request={"action":"upload","source":"files"}` and a
top-level `files` array. The tool advertises `_meta["openai/fileParams"]=["files"]`.
Every file object declares `download_url`, `file_id`, `mime_type`, `file_name`;
only `download_url` and `file_id` are required. Missing names use an opaque fallback
with a MIME-derived extension when available.
The host supplies the reference; no OpenAI API key is needed. Downloads stream
in the background, with public HTTPS checks, DNS pinning, bounded redirects,
size and timeout limits. Signed URLs are never saved in receipts or results.
Read `status` using the returned `upload:` job ID. A failed batch can contain
completed files: inspect `results` before uploading only the remaining files.

For a single file up to 2 MiB, a build containing this change also accepts
`request={"action":"upload","source":"base64","name":"concept.png","data_base64":"<original-file-base64>","sha256":"<sha256-of-original-bytes>","folder":"Comics/Project/assets"}`.
Supply the current `workspace_revision` and a unique `operation_id` at the top level.
The server validates the hash before publication; use host file inputs or chunks
for larger files or client request limits. Uploads return `markdown_link` and, for
images, `markdown_embed`. Use `stat.source_note` for a note-relative reference.

`vault_index_status.attachments.upload` advertises the upload tool, sources,
limits and client refresh guidance. File `status` also exposes `upload_sources`
and `limits.inline_bytes`. If the server lists both file tools but the client
only has Design Studio/Feishu tools, refresh/rescan the client plugin tool directory;
this is a stale client catalog, not a missing attachment API.

Local clients read files using their own host permissions, then send bytes:

1. `source=begin`, `name`, total `size`, `sha256`, optional `folder` returns `job_id`.
2. `source=chunk`, `job_id`, byte `offset`, `data_base64` appends up to 256 KiB.
   Exact repeated chunks are accepted; overlapping different bytes are rejected.
3. `source=commit`, `job_id` verifies size/hash and publishes; `source=abort`
   discards an unfinished upload. Use a distinct operation ID for each step and
   retain that ID when retrying the same step.

All upload sources use the configured attachment folder unless `folder` specifies a
safe relative directory. Same-name uploads get numbered copies and preserve
original bytes. Markdown/TXT/Base use their note workflows. Uploads never edit a
note automatically; insert a returned link with the existing note revision checks
only when requested. `stat.source_note` returns a note-relative reference.
`saved=true,index_pending=true` means the file exists but its index has not been
updated. Upload/stat/read work without initialized metadata; `list` reports
`initialization_required`, and `reindex` prepares the index without moving files.

An optional `storage_id` selects an enabled upload target; otherwise the configured
default applies. A server upload can return a `remote:` job with
`remote_saved=false`. Poll that job until remote storage and readback verification
complete; only then use its completed result and Markdown link as a saved upload.
After commit, its outbox bytes and receipt persist across restarts. Before commit,
the local byte-staging limits and interruption behavior below still apply. The
default durable outbox limit is 10 GiB per vault and is configurable. Standard
WebDAV retries incomplete uploads using a fresh unique object and a full retry;
PATCH-based continuation is not assumed.

Uploads are limited to 256 MiB/file, 1 GiB of active staged bytes/credential,
1024 retained transfers/credential and 24-hour expiry. Temporary bytes are
process-local; restart can interrupt an upload. Durable receipts report already
saved results without repeating publication. A revoked/rotated credential or
changed workspace invalidates staged access. IDs never authorize another
credential. ZIP jobs retain the existing one-hour expiry and disk-space checks;
read them through the tool, not a private localhost URL.

### File operation recovery

`move`, `trash` and `organize` return an `operation:` task while planning. Poll
`status` until ready, inspect blockers/references, and obtain its `revision`.
Submit `job command=execute` only after authorization for that preview. Changed
tasks or files require a new inspection. `resume` and `undo` also require a fresh
revision and confirmation; cancellation is a stop request, not an undo. Upload,
download and index IDs have their own prefixes and cannot be used as operation IDs.

These commands reuse the browser's resource protection, reference repair and
`.vault-rag/attachment-migrations/` journals. No permanent deletion is exposed.
Undo refuses occupied destinations and later edits. Background MCP workers
recheck grants and workspace versions at safe boundaries; automatic failure
recovery preserves originals even when the initiating grant was revoked.
An authenticated browser recovery action supplies its own authorization.
Successful consolidation changes the upload folder and workspace revision;
refresh `vault_index_status` before further calls.

The isolated contracts are in `tests/test_file_tools.py`, including HTTP discovery,
native file schemas, local/Tunnel scopes, binary integrity, retries, task recovery
and download-address restrictions. This does not certify a live host's tool
snapshot refresh or a real ChatGPT file-reference round trip.

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

The shared public MCP response encoder uses compact JSON in its worker thread,
keeping large explicit reads off the request event loop. Both existing JSON
representations and native image blocks are retained for client compatibility;
source data is never silently cut off by the response encoder. Completion logs
record elapsed milliseconds and response character counts without file contents.

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


### Windows Dev acceptance — 2026-10-16

Dev was restarted against the installed application's existing Windows data
folder on port 18080; the previous 18081 instance exited normally. No installer
or private backend payload was built or installed for this acceptance. The shared
configuration, browser/API token and saved Tunnel configuration were retained.
The user enabled full local and Tunnel read/write access, and the existing local
Codex connection was updated with a dedicated MCP credential.

The source registry, configured local HTTP connection, local client tool inventory
and refreshed ChatGPT LeafLoom plugin each contained the same 23 tool names
(14 read tools and 9 write tools). Fresh configured local calls reported
`connection: local`; plugin calls reported `connection: tunnel`, both with
workspace read/write enabled. Each connection independently completed creation,
exact-text editing, recoverable deletion, record preview, restoration and final
read of a uniquely named disposable note. Both test notes were finally moved to
recoverable Trash; no existing notes were edited.

The inherited local MCP connection in the already-running Codex session still
reported `connection: legacy` after the configuration file changed. It needs a
client reconnect/restart to use the new credential. This cached session is not
evidence that the new credential or shared access settings failed. The plugin
connection was refreshed and its full read/write workflow was verified in the
current session. macOS was not exercised in this Windows Dev acceptance.

Feishu now forwards installed lark-cli business commands through generic tools. Refresh
the tool list after upgrading; the old document/Base tools were removed. High-risk
commands and raw API calls need a separate per-connection permission and explicit
confirmation. File IDs are credential-scoped; connected-file imports also need note
read permission. See [Feishu](FEISHU.md) for the complete interface.

## Unity asset products and prepared downloads

The same two file tools expose the product catalog; refresh cached tool discovery after updating. These operations need the current `workspace_revision` from `vault_index_status` and the connection's workspace-read grant:

- `vault_files` with `request.action="products"` searches catalog metadata using `query`, review/sync `status`, `limit` and `cursor`.
- `request.action="product"` with `product_id` reads a product and all linked package versions/copies. A candidate ID is accepted for an unmatched package.
- `request.action="prepare_download"` with `asset_id` starts or reuses a backend streamed download of an existing NAS package. It does not fetch a missing purchase from a store account or modify Unity.
- `request.action="download_status"` with `job_id` reads a prepared-download task; omit the ID to list the caller's visible tasks. Queued, downloading and paused are not completed. Only a verified `ready` task returns an opaque, 24-hour download handle; never expose localhost URLs or internal disk paths to a remote client.

`vault_files_update` with `request.action="product_update"` requires workspace-write permission plus the existing unique `operation_id`. Its `operation` is `initialize`, `sync`, `rebuild`, `official`, `bind`, `personal`, `review`, `official_url`, `enrich`, `release_download` or `retry_download`. Supply relevant `product_id`, `asset_id`, `storage_id`, `job_id`, `url`, `expected_revision` and `payload` fields. Read detail before editing; an identical retry reuses its operation ID, while changed data uses a new one. Keep official fields and personal fields in their separate payload sections. A URL proposal that needs review is confirmed by binding the original candidate with its candidate revision, then reviewing the product with the newly returned product revision; do not substitute a product revision for a file-association revision.

The catalog is stored in the chosen NAS metadata directory (default `Incoming/LeafLoomCatalog/v1`), with a local query projection and versioned pending changes. Official updates preserve personal tags/notes; existing file metadata is separate. Filename hints are not confirmed product matches, and a product association is not proof of purchase entitlement. Explicit `enrich` reports actual obtained, review-needed and failed entries. A recorded URL does not prove a page was fetched; unavailable descriptions/covers remain empty and a pending Chinese summary stays marked as pending.

Complete package bytes are downloaded through the controlled local UI; MCP manages preparation and status, not Base64 transfer of the complete package. The existing `vault_files` action `read` with a download job ID remains limited to legacy ZIP export output.

Prepared downloads use a separate 20 GiB staging budget, independently of preview cache and upload outbox. Release removes the local prepared copy without deleting the NAS original. The catalog and download operations do not import into or modify a Unity project; import must be authorized separately in a known target project. They do not grant access to an Asset Store account or prove ownership.

### Batch script

[`scripts/collect_unity_catalog.py`](../scripts/collect_unity_catalog.py) starts or observes the same local collection task without browser automation. Start LeafLoom first and use its connected vault as `--root`. `--start --wait --interval 10 --report collection-report.json` starts/resumes and observes collection; `--status --report status-report.json` reads current progress. Omitting a mode also reads status. The backend persists collection progress, so stopping the script does not cancel a task. Official `succeeded` results do not imply Chinese summaries or translations are complete; inspect those fields separately.

Use `--apply-chinese chinese.json --report chinese-report.json` separately from `--wait`. Input is an array of partial official-field updates:

```json
[
  {
    "product_id": "123",
    "expected_revision": "current 64-character revision from product detail",
    "official": {
      "summary_zh": "A faithful Chinese summary of the recorded official facts.",
      "summary_status": "provided",
      "categories_zh": ["工具"],
      "keywords_zh": ["渲染"],
      "url": "https://assetstore.unity.com/packages/tools/example-123"
    }
  }
]
```

Only these five official fields are accepted, and at least one must be supplied. `url` is optional; if present, it must be an official HTTPS product URL for the same product ID without query or fragment. `expected_revision` is optional; use the actual revision from the facts being translated to reject changed input. The script validates the whole file, reads current detail and applies partial updates with a revision check. Identical fields are skipped; personal fields are never changed. Applying Chinese does not fetch a website.

The default API is `http://127.0.0.1:18080`; use `--api-url` only for a different configured local port. It accepts a bare HTTP(S) origin with a literal loopback IP, no path or trailing slash, credentials, query or fragment. Local requests disable proxies and redirects. The script reads the platform's private `VaultRag/auth-token` file into memory (or `--token-file`) and never includes it in reports or uses store-account cookies. Reports are atomically written with owner-only permissions. `--interval` is 1–60 seconds. Completion exits 0, paused/interrupted collection exits 2, errors exit 1, and Ctrl-C exits 130 without cancelling the backend task.


### User-defined attachment groups

`vault_files({action:"groups"})` returns saved groups and synchronization/conflict state. `list` accepts `group_id`, combined with existing source, type, category, tag and search filters. Source descriptions/keywords and personal metadata participate in attachment search; existing product commands remain compatible.

`vault_files_update` accepts `{action:"group_update", operation:"create"|"update"|"delete"|"members", payload:{...}}`, with the usual workspace revision, operation ID and write grant. Create uses `name`, optional `rules` and `position`. Update/delete/members require the group `id` and current `revision`; resolving existing conflicts additionally requires `resolve:true`. Members use up to 100 logical `paths` and `mode:"include"|"exclude"|"reset"`. Rules use arrays `sources`, `directories`, `formats`, `categories`, `tags`; populated conditions use AND, values use OR. Manual exclusions win over inclusions and rule matches. Deleting a group never deletes files.

`prepare_download` accepts any available remote attachment, not a store-specific package. `download_status` retains existing owner-scoped behavior. Ready staging is delivered through the local Downloads page, not MCP Base64 chunks; it does not assert that a user saved a copy to their chosen directory. Read-only clients can query groups and prepare authorized downloads but cannot change groups or membership.


## AI asset retrieval and persistent delivery

The existing file tools support `search_assets`, `asset_details`, native-image `asset_preview`, `deliver_asset`, `delivery_status` and `delivery_control`. Read existing assets first, inspect actual file versions and deliver selected originals to the configured directory. Completed jobs return an absolute path on the identified service host; the calling AI handles engine integration. Old temporary download handles still hide staging paths. See [configuration, action schemas and recovery](ASSET_WORKFLOWS.md).

AI asset search is now opt-in per attachment group. `groups` includes `search_enabled`, `search_scope_revision` and `search_scope_conflicts`; explicit `group_update` flag updates require the scope revision. Scope conflict resolution uses `resolve_search_scope=true` after review. Unselected groups are excluded from keyword and semantic search; no enabled groups returns `scope_not_configured`. Do not automatically bypass it with a full attachment listing. `group_id` only narrows the enabled union. See [group configuration and NAS synchronization](ASSET_WORKFLOWS.md#select-groups-before-searching).

### Presenter notes in managed designs

Local `design_document` reads optional page `presenterNotes` objects. Save them
with normal revision-checked `design_operations` commands:
`{type: "page.update", page_id, patch: {presenterNotes: {overview, cues}}}`.
`cues` maps stable step/case IDs to Markdown text. Use the read-time revision,
workspace revision and a unique operation ID; initialize only blank sections.
Notes participate in normal undo/redo and copies. Audience runtime documents,
project-origin `Design/studio/project.json`, HTML ZIPs and static-publish snapshots
omit notes. Presenter window control is a desktop-only main-frame interface,
not a general MCP or project-script debugging endpoint.

## Note databases

`vault_database(action="list"|"config"|"query"|"record"|"capabilities", path?, folder?, view_id?, search?, limit=100, cursor="", group_key?, anchor_path?, recent_paths?, record_path?, offset=0, text_limit=12000)` discovers local `.base` files, reads typed fields and stable view IDs, queries Markdown records, reads a database-scoped record body, or lists all database workflows. Results include workspace revision, configuration revision and per-record revisions. Limits are 1–200; stale cursors require restarting the query.

`vault_database_update(path, command, workspace_revision, expected_revision, operation_id?)` uses the same service as the UI. Workspace read/write permissions apply independently to local and Tunnel connections; legacy retrieval credentials gain no database access. `create`, `record.create` and `record.duplicate` require a unique operation ID; identical retries reuse that ID. Other commands require the read-time configuration revision.

The existing command JSON shape remains compatible. `tools/list` now publishes a discriminated command schema with required arguments for every database write, instead of an opaque object. Call `vault_database(action="capabilities")` for the complete operation map, supported views/fields, pagination limits and related file/body/attachment tools. `action="record"` requires `path` (the database) and exact `record_path`; it reads character pages using offset/text_limit (1–24000) and returns both record and configuration revisions. It cannot read a record outside that database folder.

Commands:

- Edit select/multi-select choices using `field.set.field.options` (stable values) and `optionMeta[value]` (`label`, `color`). Use `allowCustomOptions:false` for managed choices, so deleting every option still rejects new assignments; legacy unrestricted empty lists remain compatible. Copy unchanged metadata entries so historical labels, `labelKey` and unknown keys survive. Omitted `displayName` preserves the current name. Removing a value from `options` keeps original note values; record updates may retain their own historical selections but cannot add unknown values, and new records cannot receive removed choices. To replace task initial/completed states, include `field.set.task_setup` in that same write, using valid remaining/new options. Validation rejects incomplete mappings without partially saving the field or rewriting notes.
- Property actions reuse `field.set {key,field:{},displayName}` for a shared display-name change and `field.remove {key}` for shared definition removal. Both preserve original Markdown property values and bodies; removal clears field references in views and refuses built-in/read-only properties. Reorder primary detail properties with `view.update.patch.leafloom.detailFields`; reorder collapsed properties with `detailExtraOrder`. These configuration writes retain workspace/config revision checks and never modify the record body.
- Record detail layouts use `view.update.patch.leafloom.detailFields` (an ordered list of configured field keys); other properties stay expandable. `field.set` optionally accepts **both** `detail_view_id` and `detail_fields` to merge a field definition and append its key to that detail layout in one version-checked save. Invalid layout keys or stale revisions reject the entire change. Removing a field also removes its detail-layout reference and retains the original Markdown values.
- `view.move {view_id,before_view_id? or after_view_id?}` reorders a tab using stable IDs. Supply exactly one neighbor; self-targets and missing IDs are rejected. Keep read-time workspace/config revisions. Only the `views` array order changes; settings, records and fixed-view embeds are preserved. An unchanged position returns `changed:false` without saving. A repeated request with a stale revision is rejected; reload before another move.
- `create`: `{type:"create", folder?:"Projects"}`; path ends in `.base`. Omitted folder creates a sibling directory named after the database.
- `field.set`: `{type:"field.set",key:"status",displayName:"Status",field:{type:"select",options:["Open","Done"]}}`. Types: text, number, select, multiselect, date (YYYY-MM-DD), checkbox, url, attachment (list of `[[vault/path]]` references). `field.remove {key}` removes configuration, preserving note values. Keys are fixed; change displayName for renaming.
- `view.add {view:{name,type,order?,leafloom?}}`, `view.update {view_id,patch}`, `view.remove {view_id}`. Types: table, list, cards, leafloomTimeline, leafloomBoard. Standard sort/groupBy and namespaced coverField/cardSize/fit/startField/endField/conditions are supported. Conditions are ANDed and use field/operator/value; operators eq, neq, contains, empty, not_empty, gt, lt, gte, lte.
- `record.create {title,values,view_id?}` writes a distinct Markdown note. The selected view (first view if omitted) prefills unambiguous writable `leafloom.conditions` equalities, including record type. Precedence is task initial state, view equality values, board `group_key`, then explicit `values`. Search, expressions, ranges, conflicting equalities and read-only fields do not supply defaults; titles retain the caller's input. Retries reuse the original saved defaults even if the view changes. `record.update {path,record_revision,values}` updates configured properties with a note revision check. Titles use the built-in `title` field.
- `record.duplicate {path,record_revision,title?,view_id?,search?}` copies the full Markdown note into its current folder with a distinct file name, retaining the literal body, unknown properties and relative attachment references. An existing note `id` receives a fresh value. Original notes are unchanged; the result includes `visible` for the requested view. Read-time workspace/config/source revisions are required; reuse `operation_id` for retries.

Creation and duplication may opt into `return_record: true` inside the command. The persisted receipt then includes `record` (path/title/metadata/file/revision) and a catalog-version marker for immediate UI display; the default receipt remains compact. HTTP and MCP queries accept up to 20 `recent_paths` and return their `recent_records` from the complete filtered result, independent of pagination. Excluded/out-of-scope paths reveal no records. This reconciliation does not alter normal page order, cursor validation or retrieval scopes.
- `record.trash {path,record_revision?,dry_run:true}` returns a preview and operation_token; execute the same path with `dry_run:false,operation_token`. Supplying `record_revision` rejects a stale source before preview/execution. The original note goes to recoverable trash.

No operation selects notes for RAG. Read note content with existing note tools, and preserve unsaved drafts. Clients must refresh tool discovery after upgrading.

Ordinary saves/deletions wait for the active incremental file queue before metadata queries. Temporary `metadata_pending` responses include `retry_after_ms` (normally 25ms for an incremental batch; initial preparation can be longer). HTTP uses status 503 and `pending: true`; respect the hint and refresh read-time revisions after genuine conflicts. Configuration/query reuse is bound to content and workspace/catalog versions; it does not bypass permissions, source revisions or undo/trash safeguards.

### 数据库看板与任务预设

`vault_database` 与 HTTP `POST /api/bases/query` 对 `leafloomBoard` 首先返回 `groups`（key、value、count、configured、可选名称和颜色）、总数、config_revision 和 catalog_version。将某列返回的 `key` 原样作为 `group_key` 再查询该列；limit 默认 100、最大 200。cursor 仅用于相同列和快照；可选 anchor_path 在刷新后定位记录，并使用 previous_cursor 读取此前的窗口。其他四视图返回结构不变。浏览数据库不更改 RAG 范围。

`vault_database_update` 及 `/api/bases/commands` 新增以下用法，权限和工作区／配置版本保护沿用现有接口：

- `create {folder?, preset: "tasks"}` 创建五视图任务数据库，省略 preset 保留普通数据库行为。
- `view.add {view: {type: "leafloomBoard", name, groupBy?, leafloom?}, preset: "tasks"}` 复用或创建兼容任务字段；可用 task_setup 明确 statusField、priorityField、dueField、initialStatus、completedStatuses。view.update 也可显式携带 task_setup。普通看板按现有可编辑单选字段 groupBy.property 分列。
- `field.set` 的单选配置保留字符串 options，并可增加 `optionMeta: {原值: {label?, color?}}`；color 为 gray、blue、green、red、orange、yellow、purple、pink。修改标签不重写笔记值。
- `record.create` 可携带 view_id、group_key、search，自动填写视图明确的可写等值属性（例如记录类型）和所在列属性；优先级为任务初始状态、视图等值条件、列属性、显式 values。返回 visible 指明是否符合当前视图，显式覆盖后被其他筛选排除时仍保留提示。
- `record.move {view_id, path, record_revision, group_key, catalog_version, before_path? 或 after_path?, search?}` 保存分组与顺序。自动排序时允许跨列，禁止同列位置调整。相邻记录必须属于查询范围与目标列。
- `board.undo {move_id}` 撤销对应操作。只有当前文件仍符合操作后像时才执行，避免覆盖后续修改。
- `board.group.set {view_id, value, label?, color?}` 新增或编辑看板分组选项。value 为固定属性值；同值重复调用不会生成重复选项，修改 label/color 保留笔记原值及未指定的选项设置。列顺序、隐藏、折叠和空列通过 `view.update.patch.leafloom.board` 的 groupOrder、hiddenGroups、collapsedGroups、hideEmpty 配置；字段/列宽、卡片布局、筛选/排序/分组与任务映射也使用 view.update。
- `board.group.remove {view_id, group_key, dry_run: true}` 预览删除分组，返回 count、全部受影响记录的 `records: [{path, revision}]`、catalog_version 和 config_revision。范围遵循数据库目录和数据库级筛选，忽略当前视图筛选、搜索与分页。确认后携带原 records、catalog_version、`target_value: null`（未分类）或另一现有选项，使用预览的 config_revision 作为 expected_revision，并提供唯一 operation_id。事务共同移除共享字段选项、清理各看板列配置并迁移记录属性，保留笔记和正文；初始状态或唯一完成状态必须指定接替状态，不能删除“未分类”。

移动、分组删除与撤销需要唯一 operation_id；同一请求超时重试复用原 ID，改变请求使用新 ID。成功回执包含 undo_id、config_revision、record_revision；冲突应重新读取，不绕过版本校验。跨文件中断会恢复或安全回滚；外部修改导致的恢复冲突保留资料，需要先检查文件历史。只读 MCP 连接不能执行上述写入。

### Database lifecycle, bodies and attachments

All five views use the same public commands. Use `record.update.values` for title, typed properties, attachment references and both timeline dates in one save; use `record.move` for board columns/positions. Read bodies with `vault_database(action="record")`, then use `vault_update_note` for complete-source replace, unique-text edit or append, retaining YAML and read-time versions. Use `vault_files` / `vault_files_update` for media lookup, upload, previews and delivery; no duplicate attachment store is introduced. Stable embeds are ordinary Markdown `![[path.base#view=<id>]]`.

`vault_move` supports moving/renaming `.base` definitions and repairs supported Markdown references, including fixed-view embeds. `vault_delete` recycles only the `.base`, preserving the record directory. Both require an affected-file preview and confirmation token. `vault_list_records`, `vault_read_record` and `vault_restore` expose database history/trash/move recovery with existing version checks. These file-lifecycle operations do not enable arbitrary `.base` edits through the generic note-text writer.
