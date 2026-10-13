# Third-party notices

LeafLoom's own source and original brand/media assets are licensed under [MIT](LICENSE). Dependencies and model weights retain their own licenses. LeafLoom does not relicense them.

The installer downloads Python, Node, uv, Python packages, frontend dependencies and the BGE-M3 model. Retain their license files when distributing a packaged installation. The repository does not contain model weights. For the model, consult the upstream [BGE-M3 model card](https://huggingface.co/BAAI/bge-m3) and the downloaded revision's license.

Major components include React, Vite, TypeScript, CodeMirror, Lucide, markdown-it, DOMPurify, Mermaid, KaTeX, Cytoscape, D3, TanStack Virtual, FastAPI, Uvicorn, MCP SDK, LlamaIndex, LanceDB, PyTorch, sentence-transformers, watchfiles, pystray and Pillow. See `web/package-lock.json`, `uv.lock`, and each installed distribution's LICENSE/NOTICE and package metadata for exact versions and terms.

FFmpeg and Playwright are media-production tools, not application runtime dependencies. They are not bundled into LeafLoom. The video soundtrack is an original synthesized composition; screenshots contain only the repository's fictional demo. Font files are not redistributed by the media scripts.

Before distributing binaries, inventory the licenses of the actual resolved bundle, including transitive packages, native runtimes and model files. This document identifies components; it does not replace their upstream notices.
