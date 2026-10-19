# Let AI modify the current design

## Your goal

Attach the selected project context and apply a reversible batch of AI edits.

## Before you start

Open a design project and wait for its saved state.

## Steps

In Design Studio, select elements and use **Send to AI** to attach their project, page, stable IDs and revision. Ask for layout, asset, component, animation or script changes. Only projects attached to the current turn can be changed by the built-in assistant. A design batch applies directly as one persistent undo step; version conflicts preserve the newer design. Script playback remains temporary. See [Design Studio](../../DESIGN_STUDIO.md) for script APIs and export.

## What to expect

Design edits apply directly, with one durable undo step per batch.

## If it does not work

Inspect the newer design when versions conflict instead of repeatedly resending stale edits.

## Next steps

- [Connect a local CLI and chat with AI](ai-chat.md)
- [Switch between editing and live preview](design-preview.md)
