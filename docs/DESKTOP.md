# LeafLoom desktop application

The desktop application uses the existing local workspace in its own Electron
window. It includes a private Python interpreter and locked dependencies. End
users do not need a browser, Python, Node, uv, a cloned repository or Ollama.

## Install and use

### ChatGPT connection

Open **Settings → AI connections → ChatGPT connection** in the desktop app. Enter your existing
Tunnel ID and OpenAI Tunnel runtime App Key (Tunnels Read + Use), then choose
**Save and connect**. Windows x64 and Apple Silicon packages include the verified
official runtime; no separate download, YAML file or terminal is needed.

The system encrypts the saved key. Leaving the key input empty preserves it;
Clear settings removes it. Enabled connections resume at startup, remain active
when the window closes to the tray, and stop on Quit. Disconnect also disables
automatic connection. A Tunnel failure does not prevent local file use.

When the channel is ready, add a custom MCP server in ChatGPT, choose **Tunnel**,
use the same Tunnel ID, select **No authentication**, install it, and select it
in a conversation. Tunnel/workspace associations and account permissions still
apply. Stop an existing manually started client yourself to avoid duplicate
runtimes. Channel readiness is not proof of a successful ChatGPT tool call.
Tool responses contain local knowledge and are sent to ChatGPT when invoked.

The original five read-only `/mcp` capabilities allow actual loopback peers without a token. Full note access is enabled separately in **Settings → AI connections**; local and ChatGPT connections have independent write switches, off by default. The backend injects a private MCP-only credential into both Tunnel discovery and calls, reconnects after permission changes and revokes it when the runtime disconnects. Browser APIs and `/ai-mcp` keep their existing authentication; legacy bearer clients retain their original scope. See [MCP access](MCP.md).

Build machines prepare the runtime with `python scripts/build_tunnel.py` before
packaging (or `--platform all` to verify both payloads). Version and SHA256 values
are pinned in `scripts/tunnel-runtime.json`. The Mac runtime is included in nested
signing and application notarization; test Gatekeeper on a native Mac release.

### Local workspace

- Windows 10/11 x64: run the `LeafLoom-*-windows-x64-setup.exe` installer for your
  user account, then open LeafLoom from Start or the desktop shortcut.
- macOS 14+ Apple Silicon: open the `LeafLoom-*-macos-arm64.dmg`, drag LeafLoom to
  Applications, and launch the installed application. Intel Mac is not supported.
- Close hides the window to the tray/menu bar. Indexing and HTTP MCP remain
  available. Quit stops the application and its local service. Pending automatic
  note saves are flushed; unsaved/manual AI drafts prompt before quitting.
- Reading, editing, graphs and keyword search work without the retrieval model.
  Download BGE-M3 explicitly from the search settings when needed; existing models
  are reused. A failed download does not prevent opening your files.
- Startup restores catalog/index caches without loading the model. Ordinary
  folders and files load on demand; hidden restored tabs do not read their files.
  Full graph, backlinks and property-query metadata are prepared when requested.
- Only selected RAG text participates in background updates, after five seconds
  without foreground requests or user input. Unchanged index generations,
  chunks and vectors are reused. Model and vector work run in a private serial
  process; the first semantic search can wait for model loading while reading
  and editing remain available. Quit also stops this owned process.
- Open **Settings → General → App updates** to check the current/latest stable
  versions. **Download and install** shows percentage and received/total bytes,
  verifies SHA-256 and quits through the normal draft-protection flow before
  opening the Windows installer or Mac DMG. Complete the wizard (Mac: drag to
  Applications), then reopen. Canceling quit leaves **Continue installation**.
  Failed checks/downloads can be retried; Dev only checks versions.
  App upgrade/uninstall keeps note folders, settings, indexes and model files.
- Login startup is off for new users. Desktop settings and the tray can change it.
  Migration preserves an existing installation's login preference.

Manage the installed app through its own shortcuts, tray/menu-bar menu and installer. The old repository launchers have been removed; source development uses Dev.

## Update implementation

`desktop/updater.cjs` queries the public GitHub latest stable release on explicit
request. It selects only the exact platform/architecture asset from this
repository and requires its GitHub SHA-256 digest (or the exact filename in
`SHA256SUMS.txt`). Downloads stream into a private temporary directory beneath
`<state-home>/desktop-updates/`; size/hash mismatches delete the partial download.
A second hash check precedes installation. Main-process IPC uses the existing
trusted workspace/main-frame checks; renderers cannot supply download URLs or
installer paths. Settings polls status, so reopening it restores active progress.
Development mode never installs release binaries. Windows starts the NSIS wizard;
macOS opens the DMG for the normal Applications replacement workflow. Neither
platform silently overwrites a running application. Network access to GitHub is
required; interrupted application exits require downloading again. Verified
installers remain in the state directory until removed by the user.

## Source development

Install Node 22+ (with npm) and uv, then double-click **Dev.cmd** on Windows or **Dev.command** on macOS 14+ Apple Silicon, at the repository root. On Mac, you can also run `sh Dev.sh` in Terminal; the Mac entry points include standard Homebrew and uv user locations in PATH. If a downloaded/copied checkout loses execute permissions, run `chmod +x Dev.command Dev.sh` once before double-clicking. Alternatively, run `node scripts/dev-desktop.cjs` on either supported platform. No installer build is required. The first launch needs network access to install the locked Python dependencies and missing npm dependencies; subsequent launches reuse them. After npm lockfile changes, run `npm ci --prefix web` / `npm ci --prefix desktop` for the affected directory.

Use **Dev** for source desktop work with hot updates. Stop Dev through its own tray/menu-bar **Quit** or Ctrl+C in its terminal. Installed applications manage their own startup, shutdown and updates.

Dev and the installed app share the saved Tunnel settings and the same app-owned startup/quit lifecycle. Dev selects the registered installation's bundled runtime when it exists; a source-only checkout falls back to its verified payload. A shared-directory OS lease prevents a second managed runtime, and quitting waits for the owned process to stop and releases the lease. Windows kill-on-close jobs also terminate the runtime if its backend crashes. An independently started legacy CLI is not adopted as an authenticated runtime; stop that old client instead of running both.

The launcher synchronizes Python 3.12 into `.cache/desktop-dev/.venv`, verifies that Python imports this checkout, starts Vite on `127.0.0.1:5173`, then starts Electron from `desktop/`. Dev and the installed app use the same data-directory resolver: `%LOCALAPPDATA%/VaultRag` on Windows or `~/Library/Application Support/VaultRag` on Mac, including a remembered custom installed location or explicit `--home` / `VAULT_RAG_HOME`. Settings, models, AI/MCP credentials, desktop profile/drafts and the configured backend port are shared; a new configuration defaults to **18080**. Only dependencies and Vite remain development-specific. Quit the running app from the tray before switching modes; the shared single-instance lock prevents a second service. For isolated testing, explicitly set a disposable `VAULT_RAG_HOME`. Normal Dev uses your actual app data.

React, TypeScript and CSS edits update through Vite HMR; some edits trigger a page reload. Save pending work before changes that require reloads. Python and Electron main/preload changes require **Quit** from the tray/menu bar, then relaunch. Closing the window leaves it running in the tray. Quit also stops the owned backend and Vite; Ctrl+C requests the same normal quit. If an unsaved-draft prompt appears, resolve it in the desktop window. Do not force-close the terminal while work is pending. A busy Vite/backend port is reported instead of attaching to another service. If another desktop instance is already running, the existing window is activated; quit it before starting a different mode.

The workspace retains its `app.<installation-id>.localhost` origin. Only an unpackaged Electron run forwards `LEAFLOOM_DEV_SERVER` to its private sidecar. In this explicit mode, the backend fetches Vite's index and module assets without forwarding cookies or tokens; API authentication, CSRF checks and HTML-project routing remain in the backend. Development CSP permits the React preamble and the loopback HMR WebSocket. Packaged runs strip the development variable, and the regular web service never enables it implicitly.

## Build on the target OS

Build Windows on Windows x64, and Mac on Apple Silicon macOS. Build machines need
Node 22+, Python 3.12+, the uv version pinned in `scripts/runtimes.json`, and native
platform signing tools for signed releases. Use `--uv PATH` if the default uv is
another version.

After a successful full build, `--refresh-app` can update only the application
wheel while retaining the native runtime. It rejects a changed platform, Python
version or dependency lock; those changes require a full rebuild.

```sh
npm ci --prefix desktop
npm ci --prefix web
npm run build --prefix web
python -X utf8 scripts/build_desktop_backend.py
python -X utf8 scripts/build_tunnel.py
npm run dist --prefix desktop
```

The backend builder verifies the pinned standalone Python archive and installs
dependency versions/hashes exported from `uv.lock` into its own prefix. It never
copies `.venv`. An optional `--runtime-source PATH` accepts a matching standalone
Python prefix for offline/local builds; it rejects venvs and strips previous
site-packages before installing locked dependencies. Its build receipt records
this alternate provenance. Release CI uses the checksum-locked archive path.

Output is under `dist/desktop/`. Generated runtimes and package outputs are ignored
by Git. The UI/backend/package version must match. `desktop/package-lock.json`
locks the desktop tooling separately from the existing web project.

For a development window, build the private backend, set `LEAFLOOM_PYTHON` to
`desktop/resources/backend/python/python.exe` (Windows) or `bin/python3` (Mac),
and run `npm start --prefix desktop`. Use a disposable `VAULT_RAG_HOME` for tests.

## Signing and release

### Automatic release drafts

The `LeafLoom desktop packages` GitHub Actions workflow builds Windows x64 on
`windows-2025` and macOS arm64 on `macos-15`. No local build machine is required.
The Mac job checks that it is actually running on Apple Silicon.
Its packaging step raises the disposable runner's open-file limit for the signing
tool's parallel scan of the embedded Python/Torch tree; local Mac builds with an
`EMFILE` error need a sufficient open-file limit as well.

1. Update the application version in `pyproject.toml`, `vault_rag/__init__.py`,
   both `web/package.json` and `desktop/package.json`, the root application entries
   in both npm lockfiles, and the `vault-rag` package in `uv.lock`. Update the three
   changelogs. Commit the matching versions; CI checks them but never rewrites them.
2. Push that commit, then create and push its stable `vX.Y.Z` tag. For example,
   after preparing version 0.1.3: `git tag v0.1.3`, then
   `git push public v0.1.3`. Use your actual remote name. Do not reuse an existing tag.
3. In **Actions → LeafLoom desktop packages**, inspect both native builds and their
   checks. Each build installs locked dependencies and prepares a full private
   Python backend plus the verified Tunnel runtime. Either platform failing blocks
   the draft upload job; logs and available acceptance reports remain in Actions.
4. When both succeed, open the workflow summary's Release draft link. It contains
   `LeafLoom-X.Y.Z-windows-x64-setup.exe`, `LeafLoom-X.Y.Z-macos-arm64.dmg`,
   `SHA256SUMS.txt`, signing status, build links and generated release notes.
   Uploaded file sizes and SHA-256 values are verified against the local outputs.
5. Review the notes and installers, then click **Publish release** yourself.
   Drafts are not offered by the app updater or the public website. Manual
   publication triggers the existing website workflow.

Build jobs have read-only repository access. Only the final draft job receives
`contents: write`, using GitHub's built-in token; no personal access token is needed.
Tag runs are serialized. Rerunning a failed job/workflow can replace the same
draft's generated attachments while preserving edited notes. An upload failure
may leave a partial draft: inspect it, rerun the failed job and publish only after
verification succeeds. Already public Releases are rejected before replacement.
For a source fix, commit a new version and tag instead of moving the old tag.
There is no automatic public release or automatic version bump.

### Manual builds and certificates

For a build without a Release, use **Actions → LeafLoom desktop packages → Run
workflow**, select the branch and leave `signed` unchecked. Download installers
from the `leafloom-Windows-unsigned-test` and `leafloom-macOS-unsigned-test`
artifacts after success. This entry point never creates or uploads a Release,
even when a tag is selected. Test a new workflow branch here before its first
release tag. The workflow must first be present on the default branch for the
manual entry point to be available.

Tag builds currently require no certificates: Windows is unsigned; Mac uses
ad-hoc signing (`identity: "-"`), with Hardened Runtime and notarization disabled.
The workflow selects this explicitly with `LEAFLOOM_UNSIGNED=1`; use the same
environment variable for matching local builds. SmartScreen/Gatekeeper may warn
or block installation. CI window acceptance does not prove a downloaded DMG will
pass Gatekeeper on another Mac. Test the downloaded installers on target machines
before manual publication; the draft explicitly records the signing limitation.

For certificate-backed manual builds, enable `signed` and configure repository
secrets below. This retains the existing signing and notarization checks; tag
drafts remain without trusted signing until that release policy is changed.

- Windows: `WINDOWS_CSC_LINK`, `WINDOWS_CSC_KEY_PASSWORD`. Mac:
  `MAC_CSC_LINK`, `MAC_CSC_KEY_PASSWORD`. Local builds use electron-builder's
  `CSC_LINK` and `CSC_KEY_PASSWORD` environment variables.
- Mac notarization: `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`.
  All executables and native libraries in the bundled Python runtime must be signed
  as nested code before notarization; validate the resulting app with Gatekeeper.

No signing credentials are checked into the repository. A signed build fails rather
than treating a missing certificate as a signed release. App Store submission and
unattended background installation are outside this version; updates are initiated
explicitly from Settings.

## Data and migration

State stays under `%LOCALAPPDATA%/VaultRag` on Windows or
`~/Library/Application Support/VaultRag` on Mac, honoring `VAULT_RAG_HOME`.
Electron's profile/drafts use a separate `desktop-ui` subdirectory.
The successful state location is remembered in the default state's
`desktop-current-home.json`, so Finder/login launches retain custom state paths;
an explicit `--home` or `VAULT_RAG_HOME` still takes precedence. Tests redirect
this small registration file with `LEAFLOOM_REGISTRATION_HOME`.
Old `.cache/desktop-dev/` settings are retained for recovery and do not override the installed app's configuration. When the shared data directory has no `models/` directory, Dev copies the old model directory through a staging directory, retaining the source and excluding download caches. Existing model directories are never merged or overwritten.
Original note folders and `.vault-rag` indexes stay in place. Existing browser-profile drafts
cannot be imported automatically: save browser edits before moving to desktop.

Migration exports only the current user's known legacy service/tray agents into
`legacy-backups`, persists a rollback receipt before disabling them, and preserves
the configuration/auth-token. The desktop commits the transition after the UI and
authenticated backend are ready. Startup failure restores those agents. Logs live
in `logs/desktop.log` and `logs/desktop-backend.log`; the error window provides
Retry and Open logs. Stale pending migrations are recovered on the next launch.

## Acceptance

```sh
npm test --prefix desktop
uv run --no-sync python -X utf8 -m unittest discover -s tests -p test_desktop.py
uv run --no-sync python -X utf8 scripts/desktop_smoke.py --python PRIVATE_PYTHON
```

`desktop/scripts/acceptance.cjs` launches an actual Electron window in an isolated
test vault, with developer runtimes removed from PATH. Set
`LEAFLOOM_DESKTOP_EXECUTABLE` to the unpacked application's executable, then run
it with Node. It checks desktop isolation, directory bridging, note/graph rendering,
single-instance behavior, close-to-tray and quit cleanup, and saves screenshots
plus a report under `.cache/desktop-acceptance`.

Actual OS installation, signed Gatekeeper/SmartScreen behavior, login restart,
model download/retry/inference, existing-install migration, upgrade and uninstall
need target-machine acceptance before public release. Windows checks do not prove
Mac UI, login, signing or MPS behavior.

## Shared HTML websites

The desktop window and browser use the same front-end build and project website
container. The canonical UI uses a stable local `.localhost` hostname; the original
loopback entrance preserves owned drafts and reading state before opening it.
MCP addresses, service ownership and quit/tray behavior are unchanged.
See [HTML project setup, origins and validation](HTML_PROJECTS.md).
