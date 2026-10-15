# Startup and reading validation — Windows 11 x64, 2026-10-14

Implemented the lightweight file service, recoverable catalog cache, lazy global
metadata, idle scoped RAG updates and private model/index process. BGE-M3 and
the existing vector/index generation formats are retained.

## Measured on the installed app and existing vault

Vault: `D:/DJKnowledge`; state: `%LOCALAPPDATA%/VaultRag`; HTTP MCP port: 18080.
Two fresh app/backend processes, with the retrieval model unloaded at startup:

| Measurement | First launch | Second launch |
| --- | ---: | ---: |
| Launch to interface | 3,574 ms | 3,457 ms |
| Click README to rendered heading | 113 ms | 120 ms |
| File API | 5 ms | 6 ms |

During real BGE-M3 loading in the separate worker, the file API took 5 ms and
status took 1 ms. First semantic search took 21,432 ms, including 16.68 seconds
reported for model loading; the repeated search took 960 ms. Both returned
results, with no vector degradation, and the worker's model load count was one.
These are local observations, not a broad performance distribution or a Mac
benchmark. First keyword search, including source/cache reconciliation, took
2,338 ms and did not load the model.

Each no-change startup retained no model worker after its idle verification.
Close hid the window while the service stayed available; Quit released port
18080 and stopped the model worker. Raw report: `.cache/reading-live-result.json`.

## Relevant checks

- 11 runtime contracts: no heavy imports in the file service, cache restart and
  legacy backup/migration, idle timing and bounded polling, demand-only metadata,
  policy-change rejection, blocked/crashed-worker isolation, protocol/EOF cleanup,
  owner-crash cleanup and native import with an open control pipe.
- 5 browsing contracts and 12 local knowledge contracts, including only missing
  vectors being encoded when one RAG note changes.
- 17 shared metadata/search-policy contracts passed after separating the light
  metadata helpers from the legacy heavy retrieval adapter.
- Relocated private-backend checks in disposable vaults: offline editing, keyword
  retrieval without a model, authenticated MCP, explicit shutdown and parent EOF.
- 10 packaged-window checks: editor save, graph, preview isolation, single
  instance, close retains service, unsaved-quit cancellation and complete quit.
  Native folder-dialog/login toggles used fixtures, preserving real login state.

## Important implementation details

The old SQLite catalog was write-only; schema version 2 restores the namespace
without hydrating all note bodies. Old caches are backed up before migration.
Folder enumeration and file IO operate outside the shared configuration lock.
Periodic full-vault traversal and automatic model warmup have been removed.

The Windows control channels now poll anonymous pipes using `PeekNamedPipe` and
`ReadFile`, rather than blocking CRT stdin/stdout reads while native DLLs load.
The real model import previously stalled; the new path completed successfully.
Vector replies carry IDs/distances only, keeping vectors and dependencies out of
the HTTP process. A Windows kill-on-close job contains the owned worker. POSIX
workers exit on control EOF; native Mac acceptance remains pending.

Public file/MCP interfaces remain compatible. Status additionally reports
`browse_ready`, `metadata` and `rag`; the authenticated `/api/activity` endpoint
reports user input. Demand-only metadata endpoints can return 503 with
`pending: true`; the shared UI retries these requests with cancellation support.

Before updating the installed application, its prior package was retained in
`%LOCALAPPDATA%/VaultRag/desktop-resource-backups/20261014-191746/`. Models,
knowledge files, configuration and client credentials were not moved or reset.

Final normal launch used the original source Start entry and was left running.
After idle verification, status was already synced, model loaded/count were
`false/0`, and the RAG worker PID remained null. The original index generation
`2769e5df3ff8478791a7a246b3d82f10` was unchanged. All 2,530 original Markdown
checksums matched, original state/credential files matched, and MCP initialize,
tool discovery and index-status calls succeeded through the existing Codex,
Cursor and both Codely HTTP configurations. Concurrent unrelated Codex reasoning
and service-tier preference changes were retained; its MCP block was unchanged.
