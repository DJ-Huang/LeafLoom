# Build on the target OS/architecture. Never copy a source-machine virtualenv.
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
datas = [(str(root / 'vault_rag/static'), 'vault_rag/static'),
         (str(root / 'vault_rag/locales'), 'vault_rag/locales'),
         (str(root / 'vault_rag/examples'), 'vault_rag/examples'),
         (str(root / 'assets/brand'), 'vault_rag/brand'),
         (str(root / 'wiki-search/SKILL.md'), 'vault_rag/skills/wiki-search'),
         (str(root / '_generated/desktop-build.json'), 'vault_rag')]
binaries = []
hiddenimports = ['uvicorn.logging', 'uvicorn.loops.asyncio', 'uvicorn.protocols.http.h11_impl',
                 'uvicorn.protocols.websockets.websockets_impl', 'uvicorn.lifespan.on']
if sys.platform == 'win32':
    # The CPU Torch/LanceDB wheels need app-local C++ runtime DLLs.
    for directory in (Path(sys.prefix), Path(sys.prefix) / 'Scripts'):
        for pattern in ('msvcp140*.dll', 'vcruntime140*.dll', 'concrt140*.dll'):
            binaries += [(str(file), '.') for file in directory.glob(pattern)]
for package in ('sentence_transformers', 'transformers', 'tokenizers', 'lancedb',
                'pyarrow', 'mcp', 'llama_index', 'bm25s', 'watchfiles'):
    extra_data, extra_bin, extra_import = collect_all(package)
    datas += extra_data
    binaries += extra_bin
    hiddenimports += extra_import
for name in ('sentence-transformers', 'transformers', 'torch', 'lancedb', 'mcp',
             'llama-index-core', 'llama-index-vector-stores-lancedb', 'llama-index-retrievers-bm25'):
    datas += copy_metadata(name, recursive=True)

a = Analysis([str(root / 'scripts/desktop_backend.py')], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=['tkinter', 'matplotlib', 'IPython', 'pytest', 'tensorboard', 'tensorflow'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='vault-rag-backend',
          console=True, debug=False, strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='vault-rag-backend')
