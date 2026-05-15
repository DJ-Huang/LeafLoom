from __future__ import annotations

import json
import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from vault_rag.service import VaultRagService
from vault_rag.settings import Settings

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _service() -> VaultRagService:
    return VaultRagService(PROJECT_ROOT, Settings())


def build_mcp() -> FastMCP:
    mcp = FastMCP("vault-rag")
    svc_holder: dict[str, VaultRagService | None] = {"svc": None}

    def svc() -> VaultRagService:
        if svc_holder["svc"] is None:
            svc_holder["svc"] = _service()
        return svc_holder["svc"]

    @mcp.tool()
    def vault_search(
        query: str,
        top_k: int = 10,
        note_type: str | None = None,
        domain: str | None = None,
    ) -> str:
        """Hybrid search (BM25 + dense vectors) over the Obsidian vault index.

        Results prefer notes with verified_status limited/verified_true. Notes marked
        unverified (and Tips/Features/BugFix without verification) are backfilled only
        when top_k cannot be met; backfill excerpts are prefixed as unverified hints.
        """
        try:
            rows = svc().search(
                query,
                top_k=top_k,
                type_=note_type,
                domain=domain,
            )
            return json.dumps({"ok": True, "results": rows}, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.exception("vault_search failed")
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    def vault_get_chunk(chunk_id: str) -> str:
        """Fetch full chunk text by chunk_id (from vault_search results)."""
        try:
            payload = svc().get_chunk(chunk_id)
            return json.dumps(payload, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.exception("vault_get_chunk failed")
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    def vault_index_status() -> str:
        """Return last index metadata (paths, counts, models)."""
        try:
            st = svc().status()
            return json.dumps(st, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.exception("vault_index_status failed")
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    return mcp


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    build_mcp().run()
