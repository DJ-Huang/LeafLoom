# Feishu / Lark through local lark-cli

LeafLoom wraps an externally configured [official lark-cli](https://github.com/larksuite/cli).
Install the CLI, configure the app and log in yourself using its official instructions.
LeafLoom does not install/update the CLI, initiate OAuth or copy its credentials.

## Connect

1. Open **Settings → AI connections → Feishu / Lark** and enable integration.
2. Leave **CLI executable** blank for detection, or enter the absolute native executable
   path. Windows npm installations are resolved to `@larksuite/cli/bin/lark-cli.exe`;
   `.cmd`, `.bat`, `.ps1` and JavaScript wrappers are not executed. The packaged app
   does not include lark-cli or require Node to invoke its native binary.
3. Optionally choose an existing CLI profile. Blank uses the CLI's current default.
   Save, then select **Verify connection**.
4. Review the account, CLI version, timestamp and result. The adapter runs
   `auth status --json --verify`, inspecting the **user** identity even if the CLI's
   default identity is bot. Validation establishes login, not access to every resource.
5. In **MCP access permissions**, enable Feishu reading/writing separately for local
   clients and Tunnel. Refresh the client's tools after upgrading the backend.

Configuration changes invalidate previous verification. CLI login/profile changes made
outside LeafLoom require re-verification; the displayed result is a timestamped snapshot.
All business operations explicitly use `--as=user` and the configured profile. Native
CLI help is checked for required commands and flags; the initial compatibility baseline
is 1.0.66. Missing interfaces produce an incompatible-version state.

## MCP contract

The existing `/mcp` endpoint exposes five additional tools:

| Tool | Actions and inputs |
| --- | --- |
| `feishu_status` | Cached account status; `verify=true` performs online verification. |
| `feishu_docs_read` | `search`: `query`, `limit` (1–20), `page_token`. `fetch`: `document` URL/token (Docx or Wiki); returns full detail including `document.revision_id`. |
| `feishu_docs_write` | `create`: `title`, Markdown `content`. `append` / `replace_text`: `document`, `content`, positive `expected_revision` from fetch; replacement also needs `old_text`. |
| `feishu_base_read` | `resolve`: `url`. `tables`: `base_token`. `fields` / `records`: also `table_id`. `get_record`: also `record_id`. Lists use `limit` / `offset`; record queries accept `filter`, `sort`, and projected `fields`. |
| `feishu_base_write` | `create_record` / `update_record`: `base_token`, `table_id`, `fields` map. Updates require an explicit `record_id`; creates must omit it. |

Read results retain CLI `data`, resource coordinates and pagination. Base lists add
`has_more` and `next_offset` when needed, using the CLI's `total` or pagination signal.
Tables allow 1–100 rows per page; fields/records allow 1–200. A partial page cannot
support whole-table counts or conclusions. Base filter/sort are structured CLI JSON,
not shell expressions. Resource names/IDs must come from actual results.

Document writes use Markdown and send content through stdin (maximum 512 KiB).
`replace_text` maps to CLI `str_replace`, including its ellipsis pattern semantics;
it is not a guaranteed literal replacement. Before editing, the adapter fetches current
revision metadata and rejects a mismatch, then forwards the read-time revision to the CLI.
Live testing found that the upstream update endpoint accepts stale revision values, so
this preflight check is not an atomic compare-and-swap against other cloud clients.
Read again after a conflict and avoid concurrent editing during an operation.

Base writes read every field-schema page before submitting only the supplied fields.
Computed, system, attachment and unknown field types are rejected. Duplicate name/ID
aliases and select values absent from the returned schema are rejected. A field map
is limited to 16 KiB for safe native command-line transport. Writes are serialized
within this LeafLoom instance; Base has no adapter-provided atomic revision guard.

Errors follow the existing MCP `ok=false`, `error_code`, `error`, `isError=true`
contract, with safe `missing_scopes` and `upstream_code` when available. Raw CLI
stderr and credentials are not returned. No automatic write retry occurs: a timeout,
output-limit failure or partial write may have changed the cloud resource. Read it
before deciding to retry. Each native command times out after 45 seconds and each
output stream is limited to 2 MiB. There is no `--yes`, raw-API or shell escape hatch.

## Permissions and storage

The authenticated browser API provides `GET /api/feishu` (settings/status),
`POST /api/feishu` (`enabled`, `binary`, `profile`) and `POST /api/feishu/verify`.
Permission updates use `POST /api/mcp-access` with `kind: local|tunnel`,
`resource: feishu`, `enabled`, `write`. Omitting `resource` retains the existing
workspace meaning. These management routes require the existing browser/API
authentication and write CSRF checks; MCP credentials cannot use them.

Feishu permissions default off for both channels and are independent of local notes.
A dedicated MCP credential may grant notes, Feishu or both. Disabling one resource
revokes that resource's permission; the credential remains usable for other granted
resources. Disabling all scopes or rotating the local credential revokes it entirely.
Tunnel permission changes rotate its in-memory credential and reconnect discovery/calls.

MCP authorization failures include `error_source: leafloom_mcp`, the connection identity and required resource permission. They occur before CLI access and do not mean Feishu needs reauthorization. CLI/API failures identify `error_source: feishu_cli`. Upstream `800010116` means the reference resolves to a document block, not a table: list Base tables and use a returned ID.

The runtime injects that credential as `X-LeafLoom-Tunnel-Authorization` for discovery and calls. Only a real loopback peer presenting the current secret can use it; an invalid proof is rejected without falling back to legacy access. Chat-specific `Authorization` headers cannot override this runtime identity, so conversations using the same Tunnel receive the same configured resource permissions.
Legacy/anonymous MCP clients and `/ai-mcp` receive no Feishu privileges.

The private state directory contains `feishu.json`: enabled state, executable override,
profile and allowlisted verification fields. CLI tokens, app secrets and raw auth output
are not copied. `mcp-access.json` stores independent per-channel permissions and the local
credential hash. Old access configurations default to no Feishu access. MCP callers
cannot change the executable/profile or call browser management APIs.

Cloud operations require the computer running LeafLoom to have network access. Results
are returned to the calling AI client; Feishu content is not automatically imported,
indexed or synchronized with local notes. This version provides no record/document
deletion, Base schema changes, attachment writes or permission administration.

## Validation

See [Windows Dev live acceptance](FEISHU_VALIDATION.md) for the account, shared
settings UI, document and Base read/write checks completed on 2026-10-16.

Run `python -m unittest discover -s tests -p test_feishu.py` and the workspace MCP
tests for adapter contracts and channel isolation. Fixtures never touch real documents.
For real acceptance, verify login first, then use a dedicated test document and Base.
Windows verification does not establish macOS packaging or live document/Base write
acceptance; record those separately.
