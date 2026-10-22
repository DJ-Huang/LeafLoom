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

New managed projects use `Design/studio/project.json`. `design_document` returns
stable page/element IDs, components, assets, styles, scripts, the project revision
and `workspace_revision`; `manifest=true` reads page summaries and `page_id`
reads one page. `design_operations` requires the current `expected_revision`,
`workspace_revision` and a unique `operation_id`. Its `type`-discriminated batch
is one atomic undo step. It edits page/node structure, layout, text, asset
references, components, scripts and animation settings. Identical request retries
reuse their receipt; stale versions and conflicting operation IDs save nothing.

`design_history` pages persistent history or executes versioned undo/redo;
`design_import_asset` accepts original bytes as base64 and retains those bytes
when registration is undone. `design_library` lists published personal items;
`design_publish_library` publishes a versioned component/asset/style/script and
`design_import_library` explicitly imports or updates it with local dependency
copies. `design_export` creates an independent HTML ZIP. Reading requires full
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
