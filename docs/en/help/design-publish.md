# Bind data, localize and publish designs

## Your goal

Reuse copy and images, then publish selected pages and variants to PNG or PDF.

## Before you start

Open a design project and wait for its saved state.

## Steps

In Design Studio, open the inspector's **Data** tab. Bind a text, button or image
to a stable key, create a language or general variant, and edit its values. Images
share existing asset IDs. Source changes mark older translations for review;
variant layout overrides adjust text boxes and page dimensions without replacing
the source. These edits use normal save, undo and conflict recovery.

Open **Batch publish**, select pages and variants, check the explicit dimensions,
and run the output check. Export PNG images in a ZIP or one multi-page PDF. The
current-canvas check locates overflow and font/resource risks. Prefer editing the
content or box; bounded text fitting only runs when explicitly clicked and obeys
a minimum font size and reduction limit. Glyph/fallback detection is not a full
font audit. Failed export items can be retried from the same saved snapshot.
Desktop uses its built-in renderer; web/headless hosting needs the optional
publishing dependencies. Interactive preview and the original HTML ZIP export
remain available. See [publishing details](../../DESIGN_STUDIO.md#bound-content-variants-and-static-publishing).

Bindings and variants belong to their project. Shared-library component publication freezes source content and removes its project binding links; imported components can be bound to keys in the destination project.

### An editorial starter and a focused publishing workspace

Choose **ATELIER** when creating a project for a three-artboard lighting campaign with editable type, original sculptural artwork and complete English, Chinese and Japanese variants. Use **Data** to edit bound source copy or switch variants; retain the general-purpose blank, FORMA and Motion starters for other work.

The workbench separates editing tools from Export and Publish. Page reorder, duplicate and delete controls are grouped under **Page actions** in the page inspector. Batch publishing keeps its action bar visible while you choose pages, variants and format. Review the output summary, run the selected-output check, then publish. Completed items use compact expandable rows; failed items expand their diagnostics. Text fitting limits and shared check limitations remain available in disclosure sections. Static export checks do not replace visual review of fonts and layout. Use the canvas toolbar’s **Hide panels** control for more canvas space on a narrow window; **Show panels** restores the previous inspector and layer selection.

## What to expect

Get a static PNG ZIP or multi-page PDF; interactive projects can still export HTML ZIP.

## If it does not work

Review overflow, fonts and assets visually after preflight. Retry failed items from the same snapshot.

## Next steps

- [Switch between editing and live preview](design-preview.md)
- [Back up notes, comments and recovery data](backup.md)
