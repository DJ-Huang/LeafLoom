# Feishu live acceptance — 2026-10-16

## Environment and boundary

Windows source Dev, lark-cli 1.0.66, the production loopback HTTP MCP endpoint and
the externally configured user identity. The previously running installed app was
quit normally before launching Dev with its shared state directory. Dev remains
running. No installer build or macOS validation was performed.

The shared React settings were operated in the browser against the real Dev
backend: enable integration, save, verify, and observe the account/version/timestamp
success state. This verifies the shared web UI, not native desktop-only interactions.

Only a newly created acceptance document and a newly created Base containing two
synthetic records were modified. No existing business documents or tables were used.
The Base fixture itself was created with the external CLI because the MCP deliberately
does not expose Base/schema creation. All document and record operations below used
the running HTTP MCP rather than invoking adapter methods directly.

## Results

| Workflow | Result |
| --- | --- |
| Settings enable, save and online verification | Passed |
| HTTP discovery of five Feishu tools / 28 total tools | Passed |
| `feishu_status` online user verification | Passed |
| Disabled Feishu access and read-only write rejection | Passed |
| Document create, fetch, append and text replacement with readback | Passed |
| Document search finding the dedicated document | Passed |
| Stale document revision rejected without a write | Passed after the preflight fix below |
| Base URL resolution, tables and live field schema | Passed |
| Create two records and read by returned record IDs | Passed |
| Read two distinct pages using `next_offset` | Passed after the cell-matrix fix below |
| Update select/number fields while preserving an omitted title | Passed with readback |
| Server filter, sort and field projection | Passed |
| Restore temporary local Feishu permissions | Passed; existing note permissions and credential preserved |

The dedicated document and Base remain for inspection. Resource URLs, the private
run record and the settings screenshot are under `.cache/feishu-acceptance/` and
are intentionally excluded from version control. Integration stays enabled with
an account verification snapshot; local and Tunnel Feishu grants remain off.

## Findings fixed during acceptance

### Tunnel identity regression (2026-10-16, Windows Dev)

The bundled tunnel-client 0.0.16 lets per-request connector `Authorization`
override the configured static header. With the previous injection, absent, legacy
and stale chat bearer headers reproduced `tunnel`, `legacy` and invalid identities
respectively in a local control-plane fixture using the actual Windows executable.
The runtime now injects an independent `X-LeafLoom-Tunnel-Authorization` proof.
Repeating the same three requests with the fixed configuration returned `tunnel`
for each, without reconnecting between requests. HTTP MCP checks also cover revoked
proofs, resource revocation with note access retained, forged proofs, remote peers
and browser API isolation. The 10 Tunnel tests and 15 workspace MCP tests passed.

After loading the fix into Dev and waiting for Tunnel readiness, the current cloud
connector reported `connection: tunnel` and Feishu read access; consecutive paginated
record reads succeeded. This was a read-only check of an existing user-selected Base.
Independent manual acceptance in another ChatGPT conversation and macOS native
runtime validation were not performed in this run.

### Follow-up: competing legacy runtime and lifecycle

Subsequent live calls still alternated between authenticated and legacy identities.
Windows TCP ownership sampling found both an independently started `tunnel-client.exe`
and the application-owned `tunnel-client-runtime.exe` connecting to this backend.
Failed tool calls had no runtime proof; successful calls did. Stopping the old
standalone process left one runtime, after which status, tables, fields and records
all succeeded without changing Feishu authorization or reconnecting the managed client.
The earlier static-header fix was necessary protection against bearer collisions,
but was not the complete explanation for this machine's intermittent failures.

The URL's `table` value also reproduced upstream `800010116`: the CLI explicitly
reported a reference to a docx block instead of a table. A table-list ID succeeded.
The adapter now returns an invalid-request error for that case; MCP authorization
errors separately identify their LeafLoom source and connection.

Dev now reuses the registered installation's runtime when available. A shared
runtime lease prevents duplicate app-owned processes, quit cleanup closes the
owned job in all paths, and tests prove the lease can be acquired after quit.
Windows backend-crash testing also proved its runtime child terminates. The
focused suites passed 12 Tunnel cases, 5 desktop Tunnel cases, 15 adapter cases
and 15 workspace MCP cases (47 total).

Live Dev selected the registered installed runtime rather than the checkout copy.
Cloud account verification, field listing and paginated record reads succeeded.
Quitting the fixed Dev released both service/frontend ports and left zero
`tunnel-client.exe` / `tunnel-client-runtime.exe` processes, then reopening Dev
started the shared installed runtime again. The installed application itself was
not rebuilt in this run; the new desktop controller code will ship with its next build.

### Adapter behavior

1. Base v3 lists records as a cell matrix in `data.data`, accompanied by `fields`
   and `record_id_list`. Pagination now counts those rows while retaining the
   original response. A focused regression fixture covers this native shape.
2. The upstream document update endpoint accepted a stale `revision_id` during
   the dedicated-document test. LeafLoom now fetches current revision metadata
   before append/replacement and rejects a mismatch before issuing an update.
   The regression test proves no update command is submitted on a mismatch;
   the live check proves the document revision stays unchanged when rejected.
   This preflight is not atomic against another cloud client editing between
   verification and update. The earlier test marker was replaced within the
   dedicated document, and this limitation is documented in the tool contract.

The final focused adapter suite passed 14 tests. `git diff --check` passed.
Earlier HTTP fixture and Tunnel credential tests remain recorded in the task;
the earlier adapter acceptance did not repeat the entire suite or exercise remote
ChatGPT/Tunnel calls. The later Tunnel regression verification is recorded above.
Native desktop-only UI interactions, unsupported-account recovery and macOS
remain outside this acceptance.
