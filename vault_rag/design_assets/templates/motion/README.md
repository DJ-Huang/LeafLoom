# Motion Playground

Original LeafLoom starter, distributed under the repository MIT license.

Three artboards contain 298 editable native layers: a desktop playground, a 390px narrow layout and a field guide. The cream, navy and lime artwork is made from editable shapes, text and CSS. No external assets, libraries, fonts or permissions are required.

## Two ways to make things move

### 01 / Editor controls

The examples use ordinary node `animation` data. Select the named layer and open **Animation** to change the preset, trigger, duration, delay, iterations or easing.

- **Editor · stagger 1/2/3**: three `slide` / `appear` animations, each 650ms, with 0/120/240ms delays.
- **Editor · hover scale**: `scale` / `hover`, 440ms, one iteration. Also available with focus and touch activation.
- **Editor · click bounce**: `bounce` / `click`, 580ms, one iteration. The native button also responds to Enter and Space.

Animations remain paused in editing mode. Switch to Preview to interact, or preview the selected sample. **Replay page** remounts the page to replay the entrance and reset the script examples.

### 02 / JavaScript

Select either named **Script** button, open the **Script** panel, and choose **Edit script and source**. The actual `export function mount(ctx)` implementation is readable in the source editor; its exposed numeric parameters are editable in the inspector.

- **Pointer tilt** maps pointer position to a perspective tilt. Tapping, Enter or Space toggles a fixed pose. `tiltDegrees` sets the maximum angle (default 12; supported range 0–18); `responseMs` sets the follow response (default 120; range 40–400ms).
- **Spring orbit** toggles a state and runs a finite damped spring. `stiffness` (110; range 30–240), `damping` (17; range 8–40) and `turnDegrees` (150; range 30–240) change its feel. The native button updates `aria-pressed` and its visible state caption.

Scripts query descendants of `ctx.el`, so duplicating a complete example keeps its references local. Changes to source, parameters and layers use ordinary project history. The field guide provides editing steps and an excerpt from the real orbit handler.

## Motion preferences and cleanup

- There are no repeating automatic animations, timers, network calls or external dependencies. Entrance animations run once; the other examples respond to input.
- Both scripts observe `prefers-reduced-motion`, including changes while Preview is open. Tilt remains still; the orbit snaps to its selected state. Preset motion is suppressed by the runtime when reduced motion is requested.
- `ctx.onFrame` runs only while a tilt or spring is settling, then its returned stop function is called. Each `mount(ctx)` returns cleanup that stops any remaining frames and restores its presentation. `ctx.on` listeners are owned and released by the runtime when Preview stops or the page changes.
- Use **The field guide** and **Back to the playground** to try a page transition. Each visit starts with a fresh, resting example.

## Make it your own

The page roots link **Motion / Cream, navy and lime** and **Motion / Editorial type** shared styles. Every card, label, shape and demo button is independently editable. The narrow artboard has its own native layers and scripts; container rules stack content at narrow widths. It is an editable variation, not a screenshot or an automatic content-linked clone of the desktop page.

Only this canonical document is packaged. Creation assigns a fresh project identity and installs the current runtime. No original history, exports, sessions or machine paths are copied.
