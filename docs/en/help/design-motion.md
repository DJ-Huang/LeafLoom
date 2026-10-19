# Try animation and Motion Playground

## Your goal

Create interactions with editable animation and scripts.

## Before you start

Open a design project and wait for its saved state.

## Steps

Choose **Motion Playground** in **New design project**. The self-contained starter demonstrates two editable approaches: native **Animation** settings for staggered entrances, hover/focus feedback and click bounce; and **Script** modules for pointer tilt and click-driven state. Select the named example layer, adjust its Animation settings or open its readable `mount(ctx)` source and parameters, then use **Preview**. Editing mode pauses motion. The guide explains each example; a narrow artboard makes the touch layout easy to inspect.

There are no external dependencies or automatic endless effects. Preset motion honors the operating system’s reduced-motion preference, including changes during preview; hover examples also respond to keyboard focus and touch. Scripts provide click/touch alternatives and clean up through the runtime context and their returned cleanup function. Changes save with the project and run in the exported HTML ZIP. The picker illustration is static, not an animation recording.

## What to expect

Edits save with the project, and HTML ZIP exports retain interactions.

## If it does not work

Editing pauses scripts. Check preview, script logs and the system reduced-motion setting.

## Next steps

- [Switch between editing and live preview](design-preview.md)
- [Bind data, localize and publish designs](design-publish.md)
