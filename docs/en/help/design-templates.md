# Use templates, styles and components

## Your goal

Start with FORMA, refine layout and reuse styles and components.

## Before you start

Connect a local folder first. Practise in the demo vault if you prefer.

## Steps

Folder clicks only select and expand a parent folder; they never create a project. Review the selected parent path and the complete new-project path, enter a single new folder name, and choose a template before clicking **Create and open Design Studio**. Enter in a name field, Cancel, and closing the dialog do not create files. While creation is pending, fields and repeated creation are disabled. Existing project folders are opened from the project list, not recreated.

Open **Design projects → New design project**, choose **FORMA · Editorial Studio**, then enter a project name and a new folder. The preview shows its editorial layout. Creating it opens an independent, editable project with four desktop/mobile artboards and 328 native layers. Text, layout, colors, interactions and original CSS artwork can be edited and saved normally. All artwork is bundled; no external asset download is needed. Existing folders are rejected rather than overwritten: choose a different folder name. Each creation has its own project ID and history, so edits never change the built-in starter or other copies.

### Everyday visual editing

Drag on empty canvas space to select a region; Shift adds to the selection. Arrow keys nudge selected free-positioned layers by 1 px, or 10 px with Shift. Dragging shows nearby alignment guides; use the alignment and equal-gap controls for a precise arrangement across nested containers. Multi-selection resize acts on the selected group. Layout children are reordered within their parent instead of receiving free-position offsets.

The inspector groups relevant properties by object. Mixed values are shown as mixed, and editing a shared field applies to the selection. Choose Fixed, Hug content or Fill parent separately for width and height. Row/column layouts expose wrap, alignment, gap, per-side padding and minimum/maximum sizes. Fill requires a layout parent with available space; use a fixed outer width and hugging height for a text-heavy card. Test long copy and narrow widths before exporting.

Typography includes weight, line height and letter spacing. Appearance exposes stroke, shadow and gradients; image controls offer cover/contain plus crop-position sliders. Save named color, typography and spacing styles, apply them to several layers and update the linked definition. Local overrides stay explicit; detach a style when a layer should keep its own appearance. FORMA includes named brand styles and recognizable content layers for rebranding.

Component instances expose editable content, color, image and state properties for their source layers. Overrides remain local while unchanged properties inherit the master; Reset removes an override so inheritance resumes. Review the separate retained, converted and unsupported import notes. Arbitrary JavaScript listeners and live runtime state are not reconstructed. Save errors retain pending operations; retry the original operation for connection failures, or deliberately reapply against the newest revision after inspecting a conflict. Export only once the saved indicator is confirmed.

## What to expect

Each creation is independent of built-in templates and other copies.

## If it does not work

Existing folders are not overwritten. Fill sizing requires available parent space.

## Next steps

- [Try animation and Motion Playground](design-motion.md)
- [Bind data, localize and publish designs](design-publish.md)
