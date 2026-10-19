# Frequently asked questions and support

## Your goal

Find answers about offline use, models, data locations and installation.

## Before you start

Connect a local folder first. Practise in the demo vault if you prefer.

## Steps

**Why are there no search results?** Check the selected folders, file extensions and exclusions. Check indexing in Settings. If the semantic model/index is not ready, the app reports a keyword/Wiki fallback. Do not treat that as completed semantic indexing.

**Do I need to download a model before starting?** No. The desktop package includes its private runtime; reading, editing, graphs and keyword search work without BGE-M3. Download the model from search settings only when you want semantic retrieval. Source installations prepare their dependencies separately.

Model preparation shows the current connection, download and verification stages in Settings → Search & index and in setup. Downloaded file counts, received bytes, speed and elapsed time update in place. After 30 seconds without progress, a waiting hint appears; failures retain details and a retry button. Close Settings to keep reading while preparation continues; quitting the app interrupts it. Retrying reuses available downloads. Once the files are ready, indexing has its own progress.

The model section also shows the actual storage path. Select **Open folder** to view it in your system file manager; if it does not exist yet, an empty folder is created without downloading the model.

**Where is my data?** Notes remain in the connected folder. Indexes, history and Trash are in its `.vault-rag/`. Private configuration, models, tokens and AI history are in `%LOCALAPPDATA%\VaultRag` on Windows or `~/Library/Application Support/VaultRag` on macOS. `VAULT_RAG_HOME` can override the private location.

**Does it work offline?** The installed desktop app supports local reading, editing, graphs and keyword search offline. Semantic retrieval also needs the local model prepared first. External AI depends on the chosen provider's network requirements.

**The page is blank or changes do not appear.** Complete the frontend build/install, restart the service, then reload the page. Check the service logs and port conflicts. Restarting a browser alone does not load new server code.

**Can I use a network folder?** The desktop app expects a local folder. UNC shares and symbolic-link/junction access are rejected to keep file operations inside the connected folder.

**How do I uninstall?** Quit LeafLoom, then uninstall it through Windows Settings or remove it from Applications on Mac. Notes, configuration, indexes and models are retained. For a legacy source-installed service, use `vault-rag service uninstall` from that environment. Remove retained data separately only when you no longer need it.

## What to expect

Follow a symptom to its dedicated article, then collect redacted information if support is needed.

## If it does not work

Include version, OS, reproduction steps and redacted errors. Keep notes, tokens and full configuration private.

## Next steps

- [Fix blocked installation or startup](installation-problems.md)
- [Fix missing search results or a pending index](search-problems.md)
- [Troubleshoot AI, MCP, Tunnel and Feishu](connection-problems.md)
