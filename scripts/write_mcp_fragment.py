"""
Write `_generated/cursor-mcp-vault-rag.fragment.json` for merging into Cursor global mcp.json.
Run from repository root `vault-rag/` with: `python scripts/write_mcp_fragment.py`
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    sys.path.insert(0, str(root))

    from vault_rag.settings import Settings  # noqa: E402

    settings = Settings()
    venv_py = root / ".venv" / "Scripts" / "python.exe"
    if not venv_py.is_file():
        venv_py = Path(sys.executable)

    fragment = {
        "vault-rag": {
            "command": str(venv_py),
            "args": [str(root / "mcp_server.py")],
            "cwd": str(root),
            "env": {
                "VAULT_ROOT": str(settings.vault_root.resolve()),
                "OLLAMA_BASE_URL": settings.ollama_base_url,
                "EMBEDDING_MODEL": settings.embedding_model,
            },
        }
    }
    out = root / "_generated" / "cursor-mcp-vault-rag.fragment.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fragment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
