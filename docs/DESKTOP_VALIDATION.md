# Desktop validation — 2026-10-14

Latest startup/reading architecture and actual BGE-M3 measurements are recorded
in [READING_PERFORMANCE.md](READING_PERFORMANCE.md). The old idle-memory numbers
below describe the earlier architecture and have not been remeasured.

Implemented the shared desktop application, private backend packaging, migration
rollback, manual-update installer configuration and native two-platform CI build.

## Verified on Windows 11 x64

- Built the React/TypeScript interface and a wheel containing static assets,
  locales and examples without duplicate archive entries.
- Built a standalone Python 3.12.13 payload with dependencies installed from
  `uv.lock`, separate from `.venv`. This local build used the existing standalone
  Python core; the receipt records `verified-standalone-prefix`. Default release
  builds download/check the pinned Python archive.
- Electron 44.7.2 was downloaded from a reachable mirror and its archive SHA256
  matched the checksum in the official Electron npm package.
- Produced a Windows current-user NSIS installer. It is **unsigned**.
  Final size: 482,933,932 bytes (482.9 MB / 460.6 MiB).
  SHA256: `627abc0c97c4bdd06e79f3f8764eacc0d810fb0e11b35a48927d12fc64e380d2`.
- 62 targeted tests passed: desktop boundary/lifecycle (6), migration (7), source
  installer (23), model integrity/preparation (6), Windows compatibility (20).
- Private-backend acceptance passed both at the staging path and after relocation
  into the unpacked app: offline file read/write, keyword retrieval without a
  model, unauthorized API rejection, authenticated HTTP MCP, explicit shutdown,
  parent-pipe EOF cleanup and released listening port.
- Actual packaged Electron window acceptance passed 10 checks with no renderer
  exceptions: private runtime/no model, editor saves the original file, note and
  graph rendering, directory bridge, login-option roundtrip, preview isolation,
  single instance, close retains service, cancelled unsaved quit and full quit.
- GUI acceptance ran with developer runtimes removed from PATH. It used isolated
  state/vault directories, and redirected the desktop registration pointer.
  Native directory-dialog responses and OS login APIs were mocked to avoid
  changing the user's real desktop/login state. Window/editor/graph rendering,
  the backend, file writes, IPC, single-instance and quit paths were real.

Runtime test results and screenshots: `.cache/desktop-acceptance/`.

## Personal Windows installation and migration

- Installed for the current user at `%LOCALAPPDATA%/Programs/LeafLoom`, using
  the existing state at `%LOCALAPPDATA%/VaultRag` and vault `D:/DJKnowledge`.
- A real `schtasks /Query /XML` pipe declared UTF-16 but emitted UTF-8. The first
  launch safely rolled back before disabling either legacy agent. Normalizing
  the declaration fixed this compatibility issue; all 8 migration tests passed,
  including a regression checking the exported backup is parseable for restore.
- The corrected app committed migration of both running legacy tasks. Their XML
  backups are in `legacy-backups/7932e231305e49a5ad2d73c2f6c34b07/`; both tasks
  are disabled. The actual Windows login API confirms the original enabled
  login-start preference is preserved.
- Actual installed-window checks passed: authenticated interface loaded, close
  hides the window while HTTP MCP remains available, window can reopen, and Quit
  stops the application/backend and releases port 18080.
- MCP initialize, tool discovery and `vault_index_status` succeeded using the
  unchanged private token and each existing Codex, Cursor and Codely HTTP config.
- Byte hashes of 12 existing state/client files and 2,530 Markdown files remained
  identical. Config/client recovery copies and the checksum manifest are stored
  privately in `desktop-install-backups/20261014-175506/`.
- Results: `.cache/live-desktop-result.json`. No private tokens or note contents
  are included in that report. No note edits or model downloads were requested.
- Covered the corrected installer over the first installation, then launched via
  the original source launcher. The running server uses the installed private
  Python, with the original port and token. All MCP clients passed again and all
  original notes remain unchanged. Codex independently changed its reasoning and
  service-tier preferences during installation; its MCP block stayed identical,
  and those unrelated settings were retained. The app was left running.
- Updated sync-progress display in the installed app: warmup shows an animated
  indeterminate bar and a wait message; indexing shows the current phase's
  percentage and completed/total counts. TypeScript/Vite build passed. Actual
  installed-window checks used UI-only status fixtures to verify warmup and
  `65% · 26 / 40`, with cropped screenshots in `.cache/progress-*.png`; these
  checks did not request reindexing or download a model. The app was restarted
  with real status afterward; existing MCP configurations and note checks passed.

An idle welcome-window snapshot without the retrieval model measured 995 MiB
of summed private committed memory and 569 MiB of summed process working sets,
including the Python backend. Working sets count shared pages in multiple
processes, so this is not unique physical memory. It is one startup snapshot,
not a peak or a large-vault/model benchmark. Raw counters: `memory.json` beside
the window acceptance report. Installed/runtime dependencies remain a substantial
part of the footprint even when model weights have not been downloaded.

## Still requires target-machine acceptance

- No Mac `.dmg` was built or run on this Windows host. The workflow builds it on
  Apple Silicon macOS and includes nested Python-library signing, notarization,
  relocated-backend checks and actual-window acceptance. That workflow has not
  been dispatched from this local, uncommitted checkout.
- Signing certificates/notarization credentials were not supplied. Signed
  Gatekeeper/SmartScreen acceptance remains pending.
- Uninstall, real OS folder dialogs/login restart and real model download/retry need
  target-machine testing before public release. Migration rollback and model
  integrity/preparation logic have targeted automated coverage.
- No commit, push or public release was performed.
