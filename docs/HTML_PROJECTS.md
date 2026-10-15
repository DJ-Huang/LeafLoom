# HTML websites in the shared workspace

LeafLoom has one React application served by the local Python service. The
Electron window loads that website; it does not maintain a second business UI.
The App keeps a small native adapter for windows, tray, startup and system dialogs.

## Opening a project

Open an HTML file and confirm its project folder once. Paths are relative to the
connected knowledge folder; an empty project folder means its root. Select a
parent folder when the website needs resources outside the entry file's folder.
The website's `/` maps directly to the selected project folder. Directory browsing
is disabled. `index.html` is the default directory entry. Optional SPA routing
falls back to the recorded entry only for extensionless HTML navigations, never
for missing JS, images or JSON requests.

Use **Web → Open website** for an existing HTTP/HTTPS site or development server.
LeafLoom does not install dependencies or start website backends. External sites
retain their CSP, login and browser restrictions. An iframe load event alone does
not prove that an external site's content was displayed. No automatic external
browser fallback is performed.

## Origins, files and sessions

The existing loopback listener dispatches exact registered Host names before any
workspace route:

- `app.<installation-id>.localhost:<port>` serves the workspace.
- `p-<project-id>.<installation-id>.localhost:<port>` serves a saved project.
- `d-<session-id>.<installation-id>.localhost:<port>` serves an unsaved entry snapshot.

These are different-origin websites in one installation namespace. Chromium and
Firefox classify the sibling hosts as same-site; Cocoa WebKit classifies them
as cross-site. The workspace's HttpOnly cookie
is host-only. Project cookies authorize only active, read-only project sessions.
Cocoa WebKit classifies these `.localhost` siblings as cross-site. When its
embedded cookie policy blocks the project cookie, an unguessable session
capability authorizes the viewer document and browser-controlled same-origin
request metadata authorizes its resources. Cross-site resource requests without
a valid project cookie remain denied. The standalone-tab link uses that private
viewer capability; an explicit first-party visit can establish the normal cookie.
Both paths still require an active session and enforce its vault revision and
project-root boundary. Management authentication never uses this fallback.
Unknown hosts cannot reach the management router. Project responses do not grant
CORS access to the workspace; workspace Origin and CSRF checks remain in force.
The native bridge exists only in the main workspace window. Website popup windows
have an empty preload.

The service returns original file bytes without script injection, URL rewriting,
opaque-origin sandboxing or charset replacement. A same-origin viewer shell
reports navigation to the shared UI and handles refresh/back/forward. It carries
no file-write or desktop authority. Local subresources use same-origin CORP;
frame ancestors are restricted to the project itself and the workspace.

Saved project origins survive service restarts. Browser and App storage remain
independent; this feature does not synchronize cookies or page data between them.
Draft origins are temporary, separate from saved caches/storage/Service Workers,
and override only the current entry. Companion resources remain live disk files.
Creating a preview never saves a draft. Existing editing/autosave rules continue.

Resources must remain inside the selected project. Private knowledge directories
and symbolic links/junctions are rejected. Project files are independent of the
indexing inclusion/exclusion policy. Responses support MIME types, HEAD, ETags
and Range requests; access is checked before conditional caching.

## Management interfaces and migration

Authenticated workspace interfaces:

- `GET /api/html-projects?root=...&path=...`: projects, most specific containing
  project, and suggested folder.
- `POST /api/html-projects`: `{root,directory,entry,spa?,id?}` registers or updates
  a project. Root, directory and entry use existing connected-folder conventions.
- `POST /api/html-sessions`: `{root,path,project_id,draft?}` creates a local session;
  `{root,url}` validates an external website without fetching it on the server.
  Returns `{id,url,mode,origin?,entry?}`. External URLs have no local session ID.
- `DELETE /api/html-sessions/{id}` releases a session.

The original `127.0.0.1:<port>` and `localhost:<port>` browser entrances migrate
owned local/session storage and open the canonical UI. MCP and bearer clients
continue using their original addresses. Migration uses a bounded, five-minute,
one-use local handoff and imports at the new top-level origin, avoiding browser
storage partitioning. Original storage is never removed. Existing destination
values win; a recovery backup and conflict download are available. A completed
receipt prevents repeated import of unchanged old drafts, including after restart.
Changed legacy storage is eligible for migration again.

The legacy `/api/html-preview` endpoint remains isolated for older clients; new
UI sessions never remove restrictions from those old same-origin URLs.

## macOS 14/15 Safari compatibility

Older Apple networking frameworks do not resolve wildcard `.localhost` names.
The macOS source installer requests administrator authorization to add
`/etc/resolver/<installation-id>.localhost`. It routes only this installation's
namespace to `127.0.0.1`, using UDP on the configured HTTP port. The existing
service process answers A queries with `127.0.0.1`, AAAA queries with no data, and
refuses other domains. No upstream DNS or additional service process is used.
The HTTP listener remains IPv4 loopback only.

For packaged installations, the shared **Settings → General → Safari local
website compatibility** control performs the same installation step. An older
Safari opening the original `127.0.0.1` entrance can request setup directly,
before migration. This requires a one-use, origin-checked page capability and the
macOS administrator dialog. Configuration never changes default DNS, `/etc/hosts`,
TLS trust, or third-party resolver files. If authorization is canceled, originals
and drafts remain available and the entrance offers retry.

Remove the configuration in the same Settings panel, or with
`vault-rag local-resolver remove` before deleting the installation's state.
`vault-rag local-resolver install` repairs a changed service port and
`vault-rag local-resolver status` reports installation state. Service stop/start
keeps this small resolver configuration; only the running app answers its private
namespace. Removal does not affect Chrome/Edge/Firefox or Electron's native
localhost resolution. macOS 26+ needs no system resolver change by default.

## Targeted validation

```sh
PYTHONPATH=tests .venv/bin/python -m unittest test_html_projects
node --test desktop/tests/desktop.test.cjs
npm run build --prefix web
HTML_TEST_BROWSER=chrome node tests/html_projects_browser.cjs
```

The browser harness accepts `chrome`, `msedge`, `chromium`, `firefox` or `webkit`
when the corresponding runtime is installed. WebKit coverage does not constitute
an actual Safari application test. Set `HTML_TEST_ELECTRON` to a source or newly
packaged Electron executable for native shared-UI/download checks. All profile,
fixture, migration and download writes stay in temporary directories; native
login settings are not changed. On macOS 14/15, explicitly set
`HTML_TEST_RESOLVER=admin` for the system authorization dialog or `sudo` on a
managed CI runner. This temporarily adds the fixture's unique scoped resolver,
checks the OS lookup, and removes it in `finally`. Other browser tests never
install resolver settings. The macOS 15 WebKit CI job exercises that path.

For a real, read-only design sample, set `HTML_TEST_VAULT`,
`HTML_TEST_DIRECTORY` and `HTML_TEST_ENTRY`. This mode performs no catalog scan
and uses a minimal host page without the workspace's background queries.

### Local evidence (2026-10-15)

On macOS 15.7.8, the focused HTTP/origin/migration/resolver tests, MCP security
regressions, installer checks, desktop policy checks and frontend build passed.
Chrome, Edge and Firefox completed the shared-UI browser harness. The actual
Electron thin-shell entry completed the disposable website and download checks.
The real “萌宠安家” design completed board/layer loading, selection, state changes,
prototype navigation and PNG downloads in Chrome and a read-only Electron host.
The original project files were unchanged. A subsequent update packaged and
replaced the existing local App with a recoverable App/profile backup. The real
installed App passed board/layer loading, canvas-to-property selection, state
changes, prototype settings navigation and PNG download checks, then reopened
normally with the original knowledge folder.

macOS administrator authorization subsequently completed and the scoped resolver
was installed. OS name resolution and the running App's UDP resolver both passed.
This exposed Cocoa WebKit's cross-site cookie restriction; the private-viewer
capability and same-origin resource path fixed it. The full macOS WebKit harness
passed migration/conflict preservation, modules/fetch/Worker/WASM/IndexedDB/local
storage/Service Workers, nested frames, downloads, stable origins, standalone tabs
and drafts. Chrome and Electron passed the same regression checks. The final App
and DMG were rebuilt and installed with this fix; DMG checksums were verified.
Native Safari's UI acceptance subsequently passed after Mac unlock: the actual
workspace displayed the board and layer tree, canvas selection updated the
selected layer and its properties, teaching-state switching worked, the PNG
appeared completed in Safari's download list, and prototype navigation opened
the settings modal. Windows and macOS 14 checks were not executed locally. The
CI matrix is configured but has not been run as part of this local change.

`HTML_TEST_DNS_ID` can explicitly reuse an already configured installation's DNS
namespace for a temporary test service on a separate port. It neither reads that
installation's state nor installs/removes its resolver. Test browser profiles,
service state and project files remain isolated.

The underlying Apple resolver limitation is tracked in
[WebKit issue 160504](https://bugs.webkit.org/show_bug.cgi?id=160504).
