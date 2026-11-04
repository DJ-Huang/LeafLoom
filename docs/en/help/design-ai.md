# Let AI modify the current design

## Your goal

Attach the selected project context and apply a reversible batch of AI edits.

## Before you start

Open a design project and wait for its saved state.

## Steps

In Design Studio, select elements and use **Send to AI** to attach their project, page, stable IDs and revision. Ask for layout, asset, component, animation or script changes. Only projects attached to the current turn can be changed by the built-in assistant. A design batch applies directly as one persistent undo step; version conflicts preserve the newer design. Script playback remains temporary. See [Design Studio](../../DESIGN_STUDIO.md) for script APIs and export.

For an external AI chat, right-click an element on the canvas or in the layer list and choose **Copy element location** (also available in the inspector for the current selection). Hold Shift to select several elements; right-clicking an already-selected element preserves the selection. Paste the context and describe your change. The compact JSON contains the canonical source file’s absolute `file` path, `page_id` (or `component_id`) and `node_id` for one element or `node_ids` for multiple elements. Only active variants or pending saves add `variant_id` or `has_pending_changes:true`. Wait for saves, then have AI read the latest design and use version-checked design operations to preserve undo history.

With the canvas or layers focused, press **⌘+C** on Mac or **Ctrl+C** on Windows to copy the current element selection, including multiple elements. Text editing, input fields, source editors and ordinary text selections keep their normal copy behavior; preview mode is unchanged.

## What to expect

MCP starts with paginated summaries instead of the entire project. Select a page or resource, then request `full=true` with its ID when exact source is needed. Follow `next_offset` with `expected_revision`; edits and imports return short receipts. Explicit `full=true` without selectors and `include_document=true` on mutations retain full-document access. After updating, restart the backend and refresh the client's tools. See the [MCP contract](../../MCP.md).

Design edits apply directly, with one durable undo step per batch.

## If it does not work

The desktop app uses the system clipboard; restart LeafLoom after updating to activate the new copy support.

Inspect the newer design when versions conflict instead of repeatedly resending stale edits.

## Next steps

- [Connect a local CLI and chat with AI](ai-chat.md)
- [Switch between editing and live preview](design-preview.md)
