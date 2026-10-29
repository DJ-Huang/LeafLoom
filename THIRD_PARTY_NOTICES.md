# Third-party notices

LeafLoom's own source and original brand/media assets are licensed under [MIT](LICENSE). Dependencies and model weights retain their own licenses. LeafLoom does not relicense them.

Source installation prepares Python, Node, uv, Python packages and frontend dependencies. The desktop application bundles Electron, its Chromium/Node runtime, a private Python interpreter and locked Python dependencies. BGE-M3 is downloaded explicitly when needed. Retain all bundled license files, including `LICENSE.electron.txt`, `LICENSES.chromium.html`, Python notices and dependency LICENSE/NOTICE files. The repository does not contain model weights. For the model, consult the upstream [BGE-M3 model card](https://huggingface.co/BAAI/bge-m3) and the downloaded revision's license.

Major components include React, Vite, TypeScript, Tiptap, ProseMirror, CodeMirror, Lucide, markdown-it, DOMPurify, Mermaid, KaTeX, Cytoscape, D3, TanStack Virtual, FastAPI, Uvicorn, MCP SDK, LlamaIndex, LanceDB, PyTorch, sentence-transformers, watchfiles, pystray, Pillow, smbprotocol and pyspnego. See `web/package-lock.json`, `uv.lock`, and each installed distribution's LICENSE/NOTICE and package metadata for exact versions and terms.

The added editor libraries' [license texts](web/public/assets/editor-licenses.txt) are copied into the application assets at `/assets/editor-licenses.txt`.

The standalone FFmpeg CLI and Playwright tooling are used for media production and desktop acceptance, and are not bundled as LeafLoom application dependencies. Electron does include its own browser/media components, including `ffmpeg.dll` on Windows, covered by its bundled Chromium notices. The video soundtrack is an original synthesized composition; promotional screenshots contain only the repository's fictional demo. Font files are not redistributed by the media scripts.

Before distributing binaries, inventory the licenses of the actual resolved bundle, including transitive packages, native runtimes and model files. This document identifies components; it does not replace their upstream notices.

## OpenAI Secure MCP Tunnel runtime

Desktop installers bundle the official `tunnel-client-runtime` v0.0.16
([source and releases](https://github.com/openai/tunnel-client)), licensed under
Apache-2.0. The runtime's unmodified LICENSE, NOTICE and platform-specific
THIRD_PARTY_LICENSES.txt are included beside it in the application's
`resources/tunnel` directory. Archive and license-report SHA256 values are pinned
in `scripts/tunnel-runtime.json`.
