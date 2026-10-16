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
All business operations explicitly use `--as=user` and the configured profile.
Discovery is read from the installed binary; the validated baseline is 1.0.66.
LeafLoom neither upgrades the CLI nor copies its credential store.

## Unified MCP contract

Refresh the client's tool list after restarting the upgraded backend. The old
`feishu_docs_read/write` and `feishu_base_read/write` tools have been removed.
There are still five Feishu tools; command capabilities now come from lark-cli.

| Tool | Inputs and behavior |
| --- | --- |
| `feishu_status` | `verify=false`; reports account snapshot, current CLI version, bridge availability and live connection capabilities. |
| `feishu_cli_inspect` | `action`: `help`, `schema`, `skills_list`, `skills_read`. Help takes a command-path `argv` array (empty for root); schema takes a dotted `path`; skills take `skill[/reference]` in `path`. Returns native JSON or text. |
| `feishu_cli_read` | `argv` string array without executable name; optional `stdin` and `input_files` mapping relative paths to temporary file IDs. Service-side CLI metadata must classify the command as read-only. |
| `feishu_cli_write` | Same inputs, plus `confirm=false` and optional `expected_revision`. Requires write permission. High-risk commands and **all raw API calls**, including GET, also require the high-risk permission and explicit per-operation confirmation. |
| `feishu_files` | `action`: `put`, `get`, `stat`, `remove`, `import_workspace`. Operates on credential-scoped temporary file IDs, never arbitrary computer paths. |

First inspect the command's current help and read its embedded Skill/reference.
For example, inspect `help` with `argv: ["docs", "+update"]`, then read
`skills_read` with `path: "lark-doc/references/lark-doc-update.md"` and the
referenced XML guidance. Newly discovered business commands require no new
LeafLoom tool or business-specific parameter mapping.

An actual block replacement, after fetching the document and target block:

```json
{
  "argv": ["docs", "+update", "--doc=DOCUMENT", "--command=block_replace", "--block-id=BLOCK", "--content=-"],
  "stdin": "<h4>2026/10/16</h4>",
  "expected_revision": 12
}
```

Send this to `feishu_cli_write`. XML is the CLI default; explicitly pass
`--doc-format=markdown` when wanted. LeafLoom does not convert or reformat content.
The supplied positive document revision is checked immediately before updating
and passed to the CLI. Raw API edits under `/open-apis/docx/v*/documents/ID` use
the same preflight check. This is not atomic compare-and-swap across cloud clients.

The bridge forwards the CLI's full result in `data`, preserving object/array/scalar
shapes and pagination. It adds `ok`, `exit_code`, `risk` and `files`; help/Skill text
uses `text`. Do not treat one page as a whole collection. There is no Base schema
prevalidation, synthetic next offset, or automatic pagination. Incomplete writes
retain their upstream details and return `ok=false`, `error_code=partial_write`.

## Command policy

Typed command risk comes from the installed CLI schema; shortcut risk comes from
its help. Discovery is cached against native executable path, timestamp, size and
profile, and invalidated when those change. Missing risk information is rejected.
Management/auth/config/update, local servers/watchers, clipboard access and arbitrary
program execution are unavailable. No shell is used. Output/filter, identity,
profile, revision and CLI confirmation flags are managed by the bridge; pass
`confirm=true` only after the user authorizes that specific high-risk action.
The bridge supplies `--yes` only when confirmed and the command supports it.

Raw `api` accepts only a canonical `/open-apis/` path, without a host/query/fragment,
encoded path escapes or credential endpoints. Use typed commands or shortcuts first.
All raw calls conservatively need high-risk authorization, since raw API metadata
cannot classify individual endpoints. This does not bypass upstream permissions.

Each command has a 45-second timeout, or 300 seconds when file arguments are used.
Each output stream is limited to 2 MiB; stdin text is limited to 512 KiB.
No write is retried automatically. After a timeout, partial result or output-limit
error, read the resource before deciding whether to retry.
Errors retain upstream type, hint and safe scope details in `data`; credentials,
local internal paths and update notices are filtered. Unstructured errors are withheld.
`error_source=leafloom_mcp` identifies local authorization failures;
`error_source=feishu_cli` identifies upstream failures. The existing special guidance
for upstream `800010116` (document block used as Base table ID) remains.

## Files

`put` accepts a plain `name` on the first chunk; subsequent chunks supply `file_id`.
Each call supplies `data_base64` and a sequential byte `offset` (initially zero).
Finish with `complete=true`, total byte `size` and hexadecimal `sha256`; a failed
integrity check discards the upload. Completed files are immutable. `get` returns
up to 256 KiB plus `next_offset` and `eof`; `stat` returns metadata; `remove` deletes
only the staged file. Use IDs returned by actual results.

Limits: 256 KiB decoded per chunk, 256 MiB per file, 1 GiB staged data and 1024 files
per credential, 24-hour expiry. Expired files are removed on the next file/command
operation; all IDs are lost on backend restart. Credential rotation makes old IDs
unavailable. Files are private and separate from vault content, indexes and history.

To upload an attachment, put its bytes, then call the CLI with e.g.
`argv: ["docs", "+media-insert", "--doc=DOCUMENT", "--file=in/report.txt", "--type=file"]`
and `input_files: {"in/report.txt": "FILE_ID"}`. Each command runs in its own working
directory; inputs are copied there. Downloads may use `--output=out/report.txt`.
Generated files are registered and returned in `files` with a relative `path` and
file ID, including files from an upstream partial result. Retrieve their bytes with
`feishu_files.get`. Binary bytes do not enter the CLI's stdout JSON.

Absolute paths, traversal, symbolic links and Windows junctions are rejected.
The native CLI's own file guards also restrict relative paths to its working directory.
Temporary file actions require Feishu read permission, even though their MCP
annotation conservatively marks them as modifying temporary storage. They do not
require cloud write permission.

`import_workspace` takes a connected-directory-relative `path`. It additionally
requires the connection's **note read permission** and uses the existing protected
path checks. Subsequent reads/use of that file, and files generated from it, recheck
note permission and the original connected root/path. Feishu-only access cannot read
local notes or arbitrary local files. Local clients and Tunnel cannot share IDs.

## Permissions and migration

In Settings, configure Feishu read, write and **high-risk** permission separately
for local and Tunnel clients. High-risk defaults off, requires read+write, and clears
when either is disabled. Enabling it permits execution; each high-risk request still
requires specific user authorization and `confirm=true`. Never silently confirm.

The settings API remains `GET/POST /api/feishu` and `POST /api/feishu/verify`.
`POST /api/mcp-access` adds optional `high_risk` for `resource: "feishu"`; omitted
values preserve that setting unless read/write is disabled. GET responses include
`feishu_high_risk`; MCP capabilities include `high_risk_feishu`. Existing settings,
profiles and credentials remain valid; migration does not enable high-risk operations.
Settings routes retain browser/API authentication and CSRF protection.

The existing per-resource local credential and private Tunnel runtime authentication
remain unchanged. A chat's connector bearer cannot override runtime identity.
Legacy/anonymous clients and `/ai-mcp` receive no Feishu access. MCP cannot change
settings, initiate login, obtain CLI credentials or update the CLI. A verified login
is not proof of access to a particular resource. Cloud content is never automatically
imported, indexed or synchronized into local notes.

## Validation

See [Windows acceptance records](FEISHU_VALIDATION.md). Run the focused Feishu,
workspace MCP and Tunnel tests against fictional data. Live acceptance must use a
new synthetic document and attachment; never use existing work records. Report native
CLI, HTTP MCP, UI, remote client and macOS validation separately.
