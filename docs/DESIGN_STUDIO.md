# Design Studio

Design Studio builds game screens as portable HTML projects. Start with a blank
page, import artwork, arrange elements, reuse a component or embedded page, add
animation or JavaScript, and export a ZIP. Human edits and AI edits share the
same versioned document and persistent undo history.

The project home groups designs by directory and provides search, favorites,
recents, rename, copy, move, archive, and a recoverable recycle bin. Project
management and shared-library changes have a workspace history. Page and element
edits use a separate project history.

## Everyday workflow

1. Open **Design Studio** and create a project in the connected folder. Choose a
   mobile, desktop or custom page size. Existing 1.1.0 projects keep the legacy
   viewer; **Convert a copy** creates a separate managed project.
2. Use **Pages** to create, rename, group, reorder or duplicate screens. Each page
   has its own size. Use **Insert** for text, containers, images, buttons, shapes,
   SVG or custom HTML. Game starters include a HUD, resource counter, progress
   bar, character card, gallery, dialog, tabs and loading/empty/error states.
3. Upload images, SVG, fonts and script resources through **Assets**, or paste
   image files. Set names, categories and tags, find use locations, replace a
   selected image or all references, and inspect dimensions and transparency.
   Deleting a referenced asset is rejected; undoing an import retains its bytes.
4. Select an element on the canvas or in **Layers**. Shift selects multiple
   elements. Drag free-positioned elements; eight handles resize regular
   elements. Use the inspector for position, size, rotation, opacity, crop/fit,
   text, stacking order, anchors and container layout. Row, column and grid
   layouts retain their layout rules; move their children through the structure
   controls rather than treating them as free-positioned elements.
5. Turn reusable content into a main component and insert instances. Edit the
   main component to update its project instances. Insert an embedded page for a
   reusable screen region; configure a button's target page for navigation.
   Cyclic page/component embedding is rejected.
6. Publish a component or asset to the personal **Shared library**. Importing
   copies its resources and keeps its source/version. Import a newer version
   explicitly to update it; other projects do not change automatically. Style
   and script library items are also available through MCP.
7. Add an animation preset or open **Scripts and source**. Scripts remain paused
   during editing. Preview a selected component or the whole page, then stop to
   reconstruct the design state. Code and parameter edits are undoable; playback
   state is temporary. Script logs identify the element and errors include a
   source line when available.
8. Send the selection to AI and describe the change. Managed design operations
   apply directly, one tool request per undo step. Wait for pending saves before
   exporting. Unzip the export and open `index.html`; keep its companion files.

`Ctrl/⌘+Z` undoes, `Ctrl/⌘+Shift+Z` or `Ctrl+Y` redoes, `Ctrl/⌘+D` duplicates,
and Delete removes selected elements. Focused source/text fields retain their
normal editing shortcuts. A new edit after undo starts a new history branch.

## Portable document and durable history

The editable source of truth is `Design/studio/project.json`, not generated
HTML. Its schema starts with:

```json
{
  "schemaVersion": 1,
  "id": "stable-project-id",
  "name": "Game screens",
  "pages": [{"id": "home", "name": "Home", "group": "", "width": 720, "height": 1560, "nodes": []}],
  "assets": {}, "components": {}, "styles": {}, "scripts": {}
}
```

Every node has `id`, `type`, `name`, `children`, `style` and `props`. Types are
`container`, `text`, `image`, `button`, `shape`, `svg`, `html`, `page`, `instance`
and the imported native `element`. `style` accepts `x`, `y`, `width`, `height`,
`rotate`, `scaleX`, `scaleY`, opacity and ordinary CSS properties. Sizes and
positions are pixels when numeric. `props` includes `text`, `assetId`, `fit`,
`objectPosition`, `lockAspectRatio`, `pageId`, `componentId`, `overrides`,
`navigateTo`, `html`, and `css` as applicable. A `styleId` merges a shared style
before local style overrides. Component overrides are keyed by the original
child node ID, with `style` and `props` patches.

Assets retain stable IDs, project-relative paths, content hashes and metadata.
Main components contain a `node` and increasing `version`. Script modules may
be inline on a node/page, or referenced through `script.moduleId` or
`props.scriptId` into `scripts`. Module records contain `id`, `path`, and
`source`. Style records can be a CSS-property object or `{ "style": {...} }`.

History is in `.vault-rag/design-studio/<project-id>/history.sqlite3`. It stores
paired JSON deltas, operation receipts, periodic document checkpoints and a
pending file-commit record. Undo/redo survives page switches, restart and
verified project moves. It does not silently stop after 50 edits: 50 is the
default history-list page size. Upload bytes remain in the project for redo.
Workspace metadata/history and versioned shared items are under the same
private `design-studio` directory.

Writes require the current project revision and a unique operation ID. Retrying
an identical operation ID returns its receipt; reusing it for different work is
rejected. External JSON changes and version conflicts stop overwrites. The UI
serializes its save queue, retains pending instructions and source drafts in
browser storage, and offers reload/reapply after a conflict. Review the pending
work before deliberately applying it on top of newer changes. Browser storage
belongs to that browser/profile and can be cleared separately from project
history. Project moves, copies, deletion and management undo/redo stop when their
affected browser save queue still needs attention. Source drafts follow project
moves; a destination conflict retains the original draft and reports it.

## HTTP and MCP interfaces

Browser APIs use the existing management session, connected-root checks and
write CSRF protection. They are under `/api/design`:

| Endpoint | Purpose |
| --- | --- |
| `GET /document` | Full document by default; `view=true&page_id=...` transfers the active page and embedded dependencies; `manifest=true` returns summaries |
| `POST /operations` | Apply `commands` with `directory`, `root`, `expected_revision`, `operation_id` and optional `label` |
| `POST /history` | `list`, `undo` or `redo`; undo/redo require the current revision and operation ID |
| `POST /assets` | Stream original file bytes; query identifies project, name, root, revision and operation ID |
| `GET/POST /workspace`, `POST /workspace/history` | Project metadata, physical moves/recycle, and workspace undo/redo |
| `POST /copy`, `/migrate`, `/migrate/finish` | Duplicate a project or capture a separate legacy conversion |
| `GET/POST /library` | List versions, publish or explicitly import/update a shared item |
| `POST /session`, `/export` | Create the isolated project session or a standalone export |

Read results return `document`, `revision`, `workspace_revision` and
`history: {can_undo, can_redo, undo_label, redo_label}`. A manifest/page read is a
partial view: fetch the full document before `document.replace`. A project
document is limited to 32 MiB and one imported asset to 128 MiB.

The same service backs public MCP `design_document`, `design_operations`,
`design_history`, `design_import_asset`, `design_library`,
`design_publish_library`, `design_import_library` and `design_export`. Full note
access governs project reads, and the connection's separate write grant governs
mutations. The legacy six `design_*` tools remain available. See [MCP](MCP.md).

Commands use `type` as their discriminator:

| Family | Types and arguments |
| --- | --- |
| Project | `project.update {patch}`; `document.replace {document}` retains project identity |
| Pages | `page.create {page,index?}`, `page.update {page_id,patch}`, `page.delete`, `page.duplicate {page_id,new_id?,name?,index?}`, `page.move {page_id,index}`, `page.reorder {page_ids}` |
| Elements | `node.create {page_id,parent_id?,node,index?}`, `node.update {page_id,node_id,patch}`, `node.replace {page_id,node_id,node}`, `node.delete`, `node.duplicate`, `node.move {page_id,node_id,parent_id?,target_page_id?,index?}`, `node.group {page_id,node_ids}`, `node.ungroup` |
| Components | `component.create {component}`, `component.from_node {page_id,node_id,component_id?,name?}`, `component.edit {component_id,commands}`, `component.update {component_id,patch}`, `component.delete {component_id}`, `component.detach {page_id,node_id}` |
| Assets | `asset.register {asset}`, `asset.update {asset_id,patch}`, `asset.delete {asset_id}`, `asset.replace {asset_id,replacement_id,page_id?,node_ids?}` |
| Shared styles | `style.create {style}`, `style.update {style_id,patch}`, `style.delete {style_id}` |
| Script modules | `script.create {script}`, `script.update {script_id,patch}`, `script.delete {script_id}` |

Commands without repeated arguments use their family's `page_id`/`node_id` as
applicable. An update patch merges properties; `null` removes a property. Stable
IDs and managed child arrays cannot be replaced through property patches. Use
structural commands for children. A batch is validated and committed atomically
as one undo step. Use `document.replace` only with a current full document;
an inactive page in a projected response is a summary, not an empty saved page.

`component.from_node` turns a selected subtree into a main component and an
instance atomically. Placement stays on the instance; behavior and appearance
belong to the master. `component.edit` applies nested element commands inside
the master's single-root tree, including nested `component.detach`, and advances
its version once. It rejects root deletion/duplication and moves outside that
tree. Canonical duplication, conversion and detach remap literal `ctx.find`
references while preserving comments and unrelated strings.

Design references carry `kind:"design"` and a rooted project document path.
The internal assistant keeps them separate from Markdown drafts. Its direct
`design_operations` writes are limited to projects explicitly attached to the
current turn; external MCP connections retain their separately granted workspace
permissions. Both CLI adapters expose the scoped design tools without granting
terminal or filesystem callbacks.

Example AI batch:

```json
{
  "directory": "Games/PetHome",
  "expected_revision": "<from design_document>",
  "workspace_revision": "<from design_document>",
  "operation_id": "<new unique ID>",
  "label": "Animate the pet and adjust its position",
  "commands": [{"type":"node.update","page_id":"home","node_id":"pet","patch":{"style":{"x":120,"y":340},"animation":{"preset":"breathe","trigger":"appear","duration":1800,"iterations":"Infinity"}}}]
}
```

The built-in assistant also exposes `design_document` and `design_operations`.
Managed design edits use direct reversible transactions; ordinary note edits
continue to use their existing proposal workflow. A stale revision applies no
part of a batch. Read again and merge with current content rather than blindly
retrying different work under the old operation ID.

## Scripts and animation API

Attach a JavaScript module to any element, component root or page:

```js
export function mount(ctx) {
  const pulse = () => ctx.animate(
    [{ scale: '1' }, { scale: '1.08' }, { scale: '1' }],
    { duration: ctx.props.duration, easing: 'ease-out' }
  );
  ctx.on('click', pulse);
  console.log('Ready', ctx.nodeId);
  return () => { /* release resources created outside ctx helpers */ };
}
```

Use `script.parameters` to define inspector controls, for example
`{"duration":{"type":"number","default":300,"label":"Duration"}}`, and
`script.props` for instance values. Runtime parameter defaults are merged before
instance values. The entry can be `export function mount`, a default exported
function, or a plain `function mount`.

| Context | Contract |
| --- | --- |
| `el`, `root`, `nodeId`, `pageId` | Animation/content element, page root and stable identity |
| `props`, `parameters`, `state` | Resolved parameter values, descriptors, and temporary per-instance state |
| `find(id)` | Find a content element within this page/component instance; returns `null` when absent |
| `on(type, fn, options?)` / `on(target,type,fn,options?)` | Subscribe and return an unsubscribe function |
| `onEvent(name,fn)`, `emit(name,detail)` | Communication within the running preview group |
| `animate(keyframes,options,element?)` | Start a Web Animation and return its animation object |
| `setTimeout`, `setInterval`, `onFrame` | Tracked timers/frame callbacks; `onFrame` returns an unsubscribe function |
| `assets.resolve(idOrPath)` | Resolve a registered asset ID or project-relative path |
| `navigate(pageId)`, `open(pageId)`, `close()` | Change the running page, open or close a page overlay |
| `console`, `signal` | Forwarded console and an AbortSignal cancelled on disposal |

Returned cleanup functions and resources created with `ctx` helpers are released
on stop, page change, script replacement or overlay close. Use `ctx.onFrame`
for the runtime's shared frame scheduler. Timers skip interval work while the
document is hidden; Web Animations pause and resume with visibility. Direct
browser timers, global listeners, third-party engines and async work created
outside these helpers require your cleanup or `ctx.signal`.

Presets are `fade`, `slide`, `scale`, `bounce`, `breathe`, `spin` and `pulse`.
Triggers are `appear`, `click` and `hover`; duration/delay are milliseconds,
iterations are numeric or `"Infinity"`, and easing is a CSS easing string.
Layout transforms and standard animation layers are separate. For native
imported elements, preset keyframes compose with the authored translate, scale,
rotation and opacity instead of replacing edited geometry. Custom scripts can intentionally modify the DOM;
stopping preview rebuilds it from the document.

Literal project-local ESM imports resolve relative to the module `path`,
defaulting to `Design/Scripts/<node-id>.js`. The exporter embeds local modules
of up to 2 MiB in `document.js`; Blob module rewriting permits these dependencies
to run from `file://`. Circular embedded dependencies are reported as errors.
Computed import specifiers, remote dependencies and external services remain
the script author's responsibility and may require HTTP/network access. Source
HTML runs in a sandboxed child iframe, never in the management document.

Shared-library publication follows literal `ctx.assets.resolve`, `ctx.navigate`,
`ctx.open` and local module imports without executing the source. Asset usage,
replacement and deletion guards also recognize literal asset calls, native image
paths and CSS/HTML/SVG resource references. For computed resource IDs, declare
their dependencies explicitly, for example
`props.dependencies: [{assetId:"pet"},{pageId:"details"},{moduleId:"helper"}]`.
These typed declarations travel with the component; static analysis cannot infer
arbitrary application logic.

## Isolation, import and performance boundaries

The canvas runs on the project's independent origin. Its message bridge pins
the management origin from `parentOrigin`, requires the exact session ID and
checks the sending window. Embedded pages/components namespace DOM IDs and
references; captured page CSS and literal keyframe names are scoped to the
instance, including stylesheet shorthand and inline animation names. Names
chosen dynamically through CSS variables or scripts require explicit scoping.
SVG image content uses
an image element, while imported authored SVG preserves native gradients,
paths and transforms. Custom HTML cannot access the management interface.

Legacy conversion copies the source directory first and captures authored
DOM/CSS for every declared artboard. Native hierarchy, classes, CSS layout,
text, image files, transparent artwork and SVG are retained instead of
flattening a page into a screenshot. Captured native elements start without
invented absolute geometry; later movement adds translation offsets. Original
scripts stay in the copied source. Declarative `data-target` navigation is
adapted, including the reference prototype's `data-source`/`settingsFrom` context
for the settings close/done destinations. Recognized
`button.toggle[role="switch"][aria-checked]` controls receive a tracked
`mount(ctx)` script preserving their `on` class and accessible checked state.
Capture records per-page adaptation counts and warnings for original source
scripts and omitted inline event attributes. Arbitrary original event listeners,
closures and runtime state are **not** replayed or automatically translated.
The reference's settings/help home, game and pause contexts are captured as
ordinary editable page states: the 31 source artboards gain four additional
pages for alternate backdrops and help content. The source page declares
`migration.contextVariants: [{context: {settingsFrom: "game"}, pageId: "..."}]`;
each extra page records its `migration.contextSource` with the source `pageId`
and matching context. Navigation chooses the declared matching page before
loading it; unmatched/default context uses the source page. These are validated
page references, not hidden uneditable snapshots or replayed renderer code.
Recreate other opaque behaviors with presets/scripts and
compare the copy to the original before relying on it. The focused
`python tests/studio_migration_interactions_browser.py` fixture checks capture,
switch behavior and contextual returns without recapturing the original project.

Drag gestures cache parent transforms once, update only selected DOM nodes per
animation frame and submit one transaction on release. Same-page geometry,
text and simple image changes preserve existing DOM; structure, stylesheet or
resource changes rebuild the page. Only the active page renders. Page projections
transfer current content plus recursive embedded dependencies; inactive pages
retain summaries and node counts. Revision-cached reference indexes preserve
asset-use information even for unloaded pages. Image thumbnails are generated
in a worker with two concurrent jobs and a bounded 256-entry cache; decoding
does not occupy the editor thread. The workbench itself loads on demand.

Validation is explicit and environment-specific:

- `python tests/studio_runtime_browser.py` runs the portable runtime's explicit
  Chromium contracts: rotated nested dragging and transaction boundaries,
  shortcuts, modules and console, cleanup, authored DOM/CSS, incremental undo,
  cyclic embeds, inline text commit/cancel, HTML sandboxing and origin/session checks.
  Targeted regressions also verify that native presets preserve geometry and
  embedded pages cannot share literal CSS keyframe names. Nine checks passed
  on the development Mac during implementation.
- The focused document, workspace, discovery, legacy-metadata and managed
  HTTP/MCP suites passed 65 tests, including recovery, CAS/idempotency, scoped AI
  writes, resource references, library dependencies and portable exports. The
  browser contracts alone do not certify those service surfaces.
- Real-project acceptance uses 31 artboards and 422 assets
  (approximately 86 MiB), and a separate 100-page/5,000-asset/2,000-node pressure
  sample. Targets are first editable page ≤3 seconds, cached-page switch P95
  ≤300 ms and drag-frame P95 ≤20 ms. These are acceptance targets, **not
  measurements established by the runtime contract tests**.

The isolated reference conversion completed all 31 source page records plus four
editable context states (35 total), 422 assets and 1,975 authored elements.
The unchanged source had a pre-existing `gameFrame is
not defined` error from an earlier metadata rewrite. Conversion restored that
pure literal declaration from the project's preserved source **only in the copy**.
Its metadata-only `test` page has no native renderer; it is retained as an empty
managed page with an explicit warning. Script errors and unexpectedly empty
supported pages fail capture instead of reporting successful conversion.

The converted homepage visually matched the repaired native copy (720×1560,
mean channel difference 0.040/255); the game page, including its SVG board and
perspective, measured 0.100/255. The three settings switches, context-aware return
navigation, conditional backgrounds and help content passed. Independent file-URL
HTML export loaded its images/fonts and retained switch/navigation behavior, and
a before/after source-tree digest confirmed no changes to the original. The
production workbench became editable in 1,258.27 ms on a cold load, with 455,783
decoded bytes in the initial page projection. Warm reference page-switch P95 was
54.93 ms, median 26.76 ms, including browser automation.
Eighteen full-workbench browser scenarios also passed, covering project entry,
editing, components, uploads and worker thumbnails, script cleanup, pending
transaction recovery, reopening history, projected navigation/overlays and export.
The separate blank-project workflow builds home, game, gallery and settings
screens through the UI, reuses a published HUD, embeds a gallery, configures
animation/scripts, closes the settings overlay, pages beyond 50 history entries
and exports. Run `node tests/studio_workbench_browser.cjs` after building the UI.
The focused `node tests/studio_component_scripts_browser.cjs` also passed four
real-UI checks for master extraction/editing, copied script references and undo/redo.
Evidence is written to `.cache/studio-qa/` by
`python tests/studio_migration_acceptance.py --source /path/to/project`; this
explicit harness needs a Python environment with Playwright and uses the
repository's locked Python environment for its disposable backend service.

The explicit `python tests/studio_runtime_pressure.py` renderer-only runs on
2026-10-16 used 100 page records, 5,000 asset metadata records and 2,000 active
shapes. It distinguishes idle display scheduling, browser-local pointer moves
fed on animation frames, and the original Playwright mouse-input/IPC loop.
`LEAFLOOM_BROWSER_EXECUTABLE` selects a browser; the normal fixture first uses
cached Playwright Chromium and falls back to installed Chrome.

| Measurement | Cached headless Chromium 151 | Installed headless Chrome 155 |
| --- | --- | --- |
| Mount after fonts ready | 35.1 ms | 34.4 ms |
| Warm page-switch P95, 12 samples | 32.3 ms | 32.5 ms |
| Idle animation-frame interval P95, 120 samples | 21.8 ms | 16.7 ms |
| Browser-local drag interval P95, 120 samples | 21.6 ms | 16.7 ms |
| Playwright-fed drag interval P95, 120 samples | 21.8 ms | 16.8 ms |
| Selected-node update JavaScript P95 | 0.1 ms | 0.1 ms |

The raw 20 ms drag interval target passes on installed Chrome 155, the browser
channel used for workbench acceptance. It **does not pass on cached Chromium
151**: that browser's idle baseline itself is above 20 ms. The JavaScript work
measurement excludes later rendering and is not substituted for frame intervals.
Chrome 155 reported zero layouts during the browser-local drag, 121 style
recalculations totalling 35.67 ms, and 8.74 ms of script execution. It uses cached
inverse-transform arithmetic, per-frame composited translation of selected nodes,
delegated hover state, and suspended unselected-node hit testing during capture.

These measurements exclude application startup, real-image transfer and decoding.
Twelve mounted-script preview/stop cycles returned tracked events, timers, frame
callbacks, animations, Blob URLs and preview groups to zero. Only the selected
regular element receives eight resize handles; the 2,000-element initial page
creates none. These are browser-specific synthetic runs, not a completed
real-project performance acceptance. Run the Chrome comparison with
`LEAFLOOM_BROWSER_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' python tests/studio_runtime_pressure.py`.

There is no multiplayer collaboration, multitrack animation timeline or promise
of complete Figma feature parity. The current editing model is intended to
grow without replacing portable HTML or bypassing project version checks.
