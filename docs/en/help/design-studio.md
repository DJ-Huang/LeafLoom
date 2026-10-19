# Create design projects and edit the canvas

## Your goal

Build game screens or web artboards with durable project history.

## Before you start

Connect a local folder first. Practise in the demo vault if you prefer.

## Steps

- The project home offers search, recent/favorite projects, rename, copy, move, archive and a recoverable recycle bin. Workspace undo/redo covers project management; project history covers design edits across pages and restarts.
- Use **Pages** to add, group, reorder or duplicate screens. Insert text, images, containers, buttons, shapes, SVG, custom HTML, embedded pages, or game starters such as a HUD, character card, gallery and dialog. Select layers, Shift-select several, then use the canvas and inspector for position, size, rotation, text, appearance and row/column/grid layout. Child pages and component instances retain separate identities.
- Upload or paste artwork in **Assets**. Inspect dimensions/transparency, set names/categories/tags, locate uses and replace one image or all references. Publish components and assets to the personal shared library; import a newer version explicitly. Dependencies are copied into the project for offline use. A referenced asset cannot be removed until its uses are replaced or deleted.
- The **Animation** inspector offers fade, slide, scale, bounce, breathe and spin. In **Scripts and source**, attach `mount(ctx)` JavaScript to an element or page and expose parameters as inspector controls. Scripts pause during editing. Preview a component or the whole screen, then stop to restore the design state; logs identify the affected element. Source changes and parameters share the same undo history.
- **Send to AI** includes stable element IDs and the current revision. Managed design edits apply directly and one AI batch is one undo step. `Ctrl/⌘+Z` undoes and `Ctrl/⌘+Shift+Z` redoes, including after closing and reopening. Save conflicts retain pending changes; inspect them before choosing reload/reapply. Export after pending saves finish, unzip the result and open `index.html` with its companion files.

- HTML conversion retains document-root context, native mixed text and responsive image candidates. Unreadable external stylesheets are omitted with a warning; original source remains intact. Viewport/rem units and media queries still use the renderer environment. Native text runs expose content editing; select their parent for layout and typography. Compare the converted page with its original before relying on it.

- Navigate the canvas with **Select** (`V`) and **Hand** (`H`), or hold Space while dragging. Use the zoom percentage, +/−, fit page (`Shift+1`) and fit selection (`Shift+2`); Ctrl/⌘+wheel zooms around the pointer. Camera position stays steady while editing. Expand/collapse containers in **Layers**, use the selected-layer breadcrumb to reach ancestors, and edit grouped **Layout**, **Appearance** and **Typography** properties. If the isolated canvas cannot connect, use its retry action; the management shell can still show saved layers and properties.
- **Convert a copy** preserves the original project and imports authored DOM/CSS, text and assets, adapting recognized navigation, settings switches and context-dependent page states. Original scripts remain in the copied source; other legacy event handlers and runtime state need new scripts. Review conversion notices and compare the copy with the original before replacing a workflow. See the [workflow and script API](../../DESIGN_STUDIO.md) for commands, import limits and performance acceptance targets.

To sync a design between computers, close LeafLoom on the sending computer, sync the entire project folder (including assets) and its `.vault-rag/design-studio` history, and wait for sync to finish before opening it on the receiving computer. Keep the same project path within the vault; the vault root may differ between Windows and Mac. Use the fixed version on both computers and edit on only one at a time. Opening does not rewrite history ownership, while duplicate project IDs in different folders and external content conflicts remain blocked. Use the project home’s **Copy** action for an independent copy.

The design project **Recycle bin** supports restore, **Delete project permanently** and **Empty project recycle bin**. Permanent actions list affected projects and require confirmation; their files, design histories and related management undo records are removed. Other projects and shared libraries are retained.

If project home reports that the service has not loaded project management, quit the app from the tray/menu bar and reopen it. Refreshing the page does not reload backend interfaces. Delete, move and related actions remain disabled until management loads; use **Retry** to reconnect.

## What to expect

Text, layers, assets and edits are saved in each independent project.

## If it does not work

Preserve pending edits after save failures. Compare converted copies with the original page.

## Next steps

- [Use templates, styles and components](design-templates.md)
- [Switch between editing and live preview](design-preview.md)
