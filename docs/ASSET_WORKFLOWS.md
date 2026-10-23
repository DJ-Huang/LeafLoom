# AI asset search, preview and delivery

LeafLoom finds existing connected local/NAS attachments and Unity product records, previews real images and saves a selected original to a stable directory. The calling AI handles project integration. This workflow does not inspect package contents, launch an engine, search external stores or generate metadata/images.

## Configure

Open **Downloads → Download settings → AI asset search and delivery**. Set the delivery directory (default: the system Downloads folder's `LeafLoomAssets`). Only the authenticated management interface may change this directory; MCP never accepts an output path. Files are saved under `<directory>/<delivery-id>/<original-name>` without replacement. Delivered files remain until you manage them yourself; download-cache cleanup does not remove them.

Enable semantic asset indexing here to use an already prepared BGE-M3 model. Indexing processes text metadata only and does not prepare/download a model or fetch original packages. Until ready, keyword search works. Disable/re-enable to stop/restart background indexing. **Rebuild semantic asset index** refreshes its published metadata generation and reuses unchanged text vectors; it does not modify note indexes. Wait for an active build to finish before rebuilding. The current directory/index settings and delivery/index status appear in the download workspace.

## Select groups before searching

All existing and new attachment groups default to **Use for AI asset search: off**. In **Attachments**, create/edit a group, choose its rules or manual members and enable this switch. Only the union of enabled, non-conflicting groups enters keyword search and semantic indexing; overlapping membership is deduplicated. No selection returns `scope_not_configured` with no all-library fallback and no model task. The Downloads settings show the selected groups, pending synchronization/conflicts and a link to group management.

The switch follows group metadata to NAS. Its independent immutable events live in `attachment-groups/search-scope/events/`, using the existing library identity and readback verification. Old group event payloads remain unchanged. `groups` adds `search_enabled`, `search_scope_revision` and `search_scope_conflicts`. `group_update` create/update may explicitly set `search_enabled`; updates must supply `search_scope_revision`. Omission preserves the value. Resolve a scope fork only after review using `resolve_search_scope=true` and the current revision, as well as the existing `resolve=true` if group membership/rules also conflict. A conflict excludes that group until resolved. Offline edits apply locally and remain pending until verified sync.

Search, details and previews obey the same scope; a query's `group_id` only narrows it. Product file lists include only participating versions/copies, including nested product details. Disabling/deleting a group invalidates old result IDs unless another enabled group still includes that asset. A new group with the same name does not inherit the old choice. Scope changes invalidate derived projections and cancel stale index publication; unchanged historical vectors may remain cached but cannot be recalled outside the selected scope. Previous unscoped generations are discarded on upgrade, without changing originals or note indexes.

Scope selects relevance, not file access: normal attachment browsing, references and original-file downloads retain their permissions and behavior. Older services ignore the additional event namespace and can still organize groups, but must be updated for their asset search to respect this selection.

## MCP workflow

These are actions of the existing `vault_files` and `vault_files_update` tools, not new top-level tools. Supply the current `workspace_revision` from `vault_index_status`. Writes additionally require note/workspace write access and a unique `operation_id`.

1. `vault_files` with `request={"action":"search_assets","query":"mossy damp ruins","mode":"hybrid","limit":5}` returns compact candidates. Optional filters: `source` (`all/local/remote`), `storage_id`, `group_id`, `formats` (extensions such as `png` or `unitypackage`) and `pipeline` (`builtin/urp/hdrp/unknown`). `limit` is 1–20. `mode=keyword` skips semantic retrieval.
2. `asset_details` with `result_id` returns recorded field provenance, product metadata and actual available file versions/copies. A product's latest official version does not establish which version the attached package contains. Read `files[].path` and `files[].revision` before delivery.
3. `asset_preview` with `result_id` and its `expected_revision` returns a native MCP image plus structured `preview_kind=product_cover/file_thumbnail`. A product cover is not a preview of an individual mesh or texture inside the package. Missing previews return `unsupported`; oversized/broken previews return an error.
4. `vault_files_update` with `request={"action":"deliver_asset","path":"Materials/stone.png","expected_revision":"<file revision>"}` starts an owner-scoped job. `operation_id` retries must use identical source, workspace and destination settings.
5. Poll `vault_files` with `request={"action":"delivery_status","job_id":"<returned ID>"}`. Only `state=completed` returns `local_path`, `verified`, size and SHA-256. `device.id/name/path_location=service_host` identifies the machine holding the file. A Tunnel connection does not establish where the calling AI executes.
6. `delivery_control` on the write tool takes `job_id`, the current task `expected_revision` and `command=retry/cancel`. Source/destination changes require a fresh delivery request. Cancelling a completed job does not delete its output.

Search result IDs only select current authorized records. Searches do not broaden note RAG selection, and a product association does not prove ownership or engine compatibility. Unlabelled images with opaque names cannot be reliably located by appearance in this version.

## Implementation and recovery

- `.vault-rag/asset-search/` holds a disposable metadata projection, a private vector cache and an atomically published generation manifest. Existing note generations are independent. Chinese/English token matching uses the existing tokenizer. Keyword and semantic top-50 lists use reciprocal-rank fusion with constant 60; exact filenames/titles come first.
- BGE-M3 is shared with note retrieval in the existing serial `rag_process`. Small asset batches yield between requests, and foreground queries precede queued background batches. A 3-second semantic deadline returns keyword results with a degradation reason; no second model is loaded. Stale/deleted records are excluded using current metadata and text fingerprints.
- `.vault-rag/asset-deliveries/` stores credential-generation-scoped jobs and directory settings. Remote acquisition reuses original download staging and leases, then streams a separate output copy; local originals are copied directly. SHA-256 readback, exclusive publication, source revisions, directory/link checks and a 5 GiB destination-volume reserve protect publication. Only one output copy runs at a time.
- Interrupted pending deliveries are revalidated when the creating client polls status after restart. Failed/paused deliveries require explicit retry; revoked credentials and changed source/directory settings do not silently resume. Partial files never produce a completed path. An already journaled publication can be recovered after interruption.
- Original download endpoints and expiring handles retain their existing behavior; they never expose private staging paths. Delivery paths refer to persistent output copies, not these handles. If you move/delete/change an output, its status becomes `unavailable`.
- Delivery files are not automatically deleted or synchronized between machines. Use the calling AI's file tools on the identified service host to integrate them into a project.

## Focused validation

Run `python -m unittest tests.test_asset_workflows tests.test_asset_workflows_remote` in the locked development environment. Fixtures use temporary local folders and a simulated NAS. Run `npm run build` in `web/` and `node tests/frontend_asset_workflows.cjs` for the isolated settings/delivery view. No real asset library or engine is required.
