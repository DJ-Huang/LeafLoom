"""
Write `_generated/cursor-mcp-vault-rag.fragment.json` for merging into Cursor global mcp.json.
Run from repository root `vault-rag/` with: `python scripts/write_mcp_fragment.py`
Replace the placeholder with the dedicated credential generated in Settings → AI connections.
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
    from vault_rag.local_state import LocalConfig
    port = LocalConfig().data.get('port', 18080)

    fragment = {
        "user-vault-rag": {
            "url": f"http://127.0.0.1:{port}/mcp",
            "headers": {"Authorization": "Bearer <MCP_TOKEN_FROM_SETTINGS>"},
        }
    }
    out = root / "_generated" / "cursor-mcp-vault-rag.fragment.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fragment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
