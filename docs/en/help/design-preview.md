# Switch between editing and live preview

## Your goal

Try artboard interactions after saving, then return to your editing position.

## Before you start

Open a design project and wait for its saved state.

## Steps

Choose **Preview** at the top of the workbench to play the current page’s animation, scripts and navigation without exporting a ZIP. The workbench commits active text input and waits for pending saves first. If saving fails, your changes remain queued and editing stays open with retry guidance, rather than showing stale content. Preview hides layers, properties, selection outlines and handles. Use **Preview page** to switch existing artboards, including desktop/mobile layouts included in a template, and **Replay** to restart the current page. **Edit** or **Back to editing** restores the page, selected layers and canvas position from before preview.

In **Preview**, choose **Present full screen** to hide the application chrome and fit the entire artboard to the screen without stretching. The current interaction continues without restarting. Move the pointer to the bottom to show page controls and **Exit full screen**, or press **Esc** to return to ordinary preview. You can then return to editing as usual. If native full screen is unavailable, presentation still fills the application window.

## What to expect

Returning to editing restores the previous page, selection and canvas position.

## If it does not work

Retry a failed save before previewing; preview will not silently use stale content.

## Next steps

- [Bind data, localize and publish designs](design-publish.md)
- [Let AI modify the current design](design-ai.md)

## Present with a second display

In the desktop app, open **Preview → Presenter mode**. Select the audience display, use **Identify displays** if needed, then start. A single display offers a separate rehearsal window. Projects with page groups start with the current group; choose **Present all pages** to include the rest. **Swap displays** exchanges the audience and controller during playback.

The presenter console contains a resizable live operation preview and private speaker notes. Click, drag A/B sliders, scroll, select cases and control videos in the preview: only the audience window plays the media and produces sound. **Next step**, Space and Right advance registered talking points, then the next page; Left reverses. An expanded demo closes before advancing. Page buttons and the directory jump directly. Projects without a presenter adapter navigate by page.

Notes contain an overview and sections keyed to stable step/case IDs. Read or edit them, adjust text size, and follow the current point. Scrolling or editing suspends following; **Resume following** restores it. Parameter changes update the status without scrolling. Notes autosave with project revision checks and undo history; a failed save retains the local draft. Saving notes never reloads the audience's frozen presentation snapshot.

**Blackout** pauses and mutes media. **Restore picture** keeps it paused until **Resume playback**. A disconnected display or controller pauses and hides audience output; reconnect a selected display before continuing. **End presentation** closes the audience window and returns to the previous editor page, selection and camera. Notes stay in project copies and history, and are excluded from audience documents, HTML ZIPs and static publishing. macOS is the first acceptance target; Windows hardware verification remains separate.
