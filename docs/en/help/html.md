# Open HTML projects and websites

## Your goal

Run local websites with their companion resources on isolated origins.

## Before you start

Connect a local folder first. Practise in the demo vault if you prefer.

## Steps

1. Open a local `.html` or `.htm` file from the directory. Confirm its **Project folder** and choose **Save and open**. Select a folder containing the entry and all companion resources; the website's `/` maps to this folder. An empty folder value uses the connected knowledge folder's root.
2. Use **Project settings** to change the folder or enable **SPA routing** for a client-side application. This opens the project entry for missing page routes; missing scripts, images and JSON still return errors.
3. Use back, forward, refresh, full screen or **Open in new tab** in the website toolbar. In the desktop app, the same website runs inside its window. Browser and desktop website storage are independent.
4. To open an existing website or development server, choose **Preview → Open website** and enter its HTTP/HTTPS URL. LeafLoom does not install dependencies or start a backend. A site may refuse embedding or require sign-in.
5. Open **Design Studio** from the sidebar or a folder's **New design project here** menu. New projects use a managed visual document; existing `1.1.0` projects keep their layer-review tools and can be converted into a separate editable copy. Choose mobile portrait `720×1560`, mobile landscape `1560×720`, desktop `1440×900` or custom page dimensions.

**Source** opens the HTML text. Ordinary edits autosave; if an unsaved draft remains, the website view previews it in a temporary origin without saving it. Companion resources still come from disk. HTML remains browsable independently of the selected search folders and is not indexed for knowledge search.

On macOS 14/15 Safari, use **Settings → General → Safari local website compatibility** if local websites do not open. macOS requests administrator authorization for this installation's resolver configuration. See [HTML project details](../../HTML_PROJECTS.md) for removal and platform limits.

When an older loopback address opens the new workspace address, local drafts and view state migrate automatically. Existing destination values win; a conflict banner offers a backup download. Original browser storage is retained. This migration does not synchronize browsers or the desktop app.

## What to expect

The website root maps to its selected project folder. HTML stays out of knowledge retrieval.

## If it does not work

Check the entry file and project folder. External sites may block embedding; start their backend separately.

## Next steps

- [Create design projects and edit the canvas](design-studio.md)
- [Understand local data and external access](privacy.md)
