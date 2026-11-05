# Let AI modify the current design

## Your goal

Attach the selected project context and apply a reversible batch of AI edits.

## Before you start

Open a design project and wait for its saved state.

## Steps

In Design Studio, select elements and use **Send to AI** to attach their project, page, stable IDs and revision. Ask for layout, asset, component, animation or script changes. Only projects attached to the current turn can be changed by the built-in assistant. A design batch applies directly as one persistent undo step; version conflicts preserve the newer design. Script playback remains temporary. See [Design Studio](../../DESIGN_STUDIO.md) for script APIs and export.

For an external AI chat, right-click an element on the canvas or in the layer list and choose **Copy element location** (also available in the inspector for the current selection). Hold Shift to select several elements; right-clicking an already-selected element preserves the selection. Paste the context and describe your change. The compact JSON contains the canonical source file’s absolute `file` path, `page_id` (or `component_id`) and `node_id` for one element or `node_ids` for multiple elements. Only active variants or pending saves add `variant_id` or `has_pending_changes:true`. Wait for saves, then have AI read the latest design and use version-checked design operations to preserve undo history.

With the canvas or layers focused, press **⌘+C** on Mac or **Ctrl+C** on Windows to copy location information for non-image or multiple selections. A single selected image copies its source picture; use **Copy element location** explicitly for its location information. Text editing, input fields, source editors and ordinary text selections keep their normal copy behavior; preview mode is unchanged.

**Copy a source image.** Select one image in Design Studio, open the right-hand **Design** tab and use **Image source → Copy image**. The card shows the thumbnail, filename and vault-relative source path. It resolves the image currently used by bindings, variants and image-root component overrides. Copying preserves the source size and transparency, without canvas cropping, rounded corners or rotation. Locked images and read-only variant views can also be copied; saving is not required and project history is unchanged. With the canvas or layer list focused, **⌘C / Ctrl+C** copies a single selected image; other elements and multiple selections retain location copying, and **Copy element location** remains available in its menu. Text fields keep normal text copying. Paste the PNG into another application or note; a note uses its normal attachment-upload flow. SVG is rasterized and animated images use the first frame. Only project-local images are supported; import external sources first. Missing or unreadable originals report an error and allow retry, without substituting text or a link. Source and PNG data are limited to 32 MiB and decoded images to 64 megapixels. Restart the desktop app after updating native clipboard support.

## What to expect

MCP starts with paginated summaries instead of the entire project. Select a page or resource, then request `full=true` with its ID when exact source is needed. Follow `next_offset` with `expected_revision`; edits and imports return short receipts. Explicit `full=true` without selectors and `include_document=true` on mutations retain full-document access. After updating, restart the backend and refresh the client's tools. See the [MCP contract](../../MCP.md).

Design edits apply directly, with one durable undo step per batch.

## If it does not work

The desktop app uses the system clipboard; restart LeafLoom after updating to activate the new copy support.

Inspect the newer design when versions conflict instead of repeatedly resending stale edits.

## Next steps

- [Connect a local CLI and chat with AI](ai-chat.md)
- [Switch between editing and live preview](design-preview.md)
