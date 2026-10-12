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

    fragment = {
        "user-vault-rag": {
            "url": "http://127.0.0.1:18080/mcp",
            "headers": {"Authorization": "Bearer <LOCAL_TOKEN>"},
        }
    }
    out = root / "_generated" / "cursor-mcp-vault-rag.fragment.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fragment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
