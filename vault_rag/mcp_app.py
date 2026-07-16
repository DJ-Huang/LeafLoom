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


def _required_rule_ids(query: str, domain: str | None) -> tuple[str, ...]:
    """Translate the stable gate contract into deterministic rule inclusions."""
    domain_key = (domain or "").strip().lower()
    query_key = query.lower()
    is_review = any(token in query_key for token in ("review", "审查"))
    is_debug = any(token in query_key for token in ("debug", "调试", "排错"))
    is_architecture = any(
        token in query_key
        for token in ("architecture", "module", "documentation", "架构", "模块", "文档")
    )
    is_write = any(
        token in query_key
        for token in (
            "write",
            "implement",
            "fix",
            "refactor",
            "code",
            "写",
            "改",
            "实现",
            "修复",
            "重构",
            "编码",
        )
    )

    if domain_key == "unity":
        rule_ids = ["core/role", "core/anti-ai-trace"]
        if is_review:
            rule_ids.extend(("reviews/hmirp-review-rules", "agents/shader-expert"))
        elif is_debug:
            rule_ids.append("agents/test-engineer")
        elif is_architecture:
            rule_ids.append("agents/ta-render-expert")
        elif is_write:
            rule_ids.append("core/hmirp-rendering-agent")
        return tuple(rule_ids)

    if domain_key == "comfyui":
        rule_ids = ["core/comfyui", "core/anti-ai-trace"]
        if is_review:
            rule_ids.extend(("reviews/comfyui-review-rules", "agents/comfyui-expert"))
        return tuple(rule_ids)

    if domain_key == "pcg":
        return ("pcg/index", "pcg/assembly-bevel")
    return ()


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

        Excludes vault Rules/ (use rule_search for routing rules). Results prefer notes
        with verified_status limited/verified_true. Notes marked unverified (and
        Tips/Features/BugFix without verification) are backfilled only when top_k
        cannot be met; backfill excerpts are prefixed as unverified hints.
        """
        try:
            settings = Settings()
            rows = svc().search(
                query,
                top_k=top_k,
                type_=note_type,
                domain=domain,
                path_exclude_prefixes=(settings.vault_rules_folder,),
            )
            return json.dumps({"ok": True, "results": rows}, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.exception("vault_search failed")
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    def rule_search(
        query: str,
        top_k: int = 10,
        domain: str | None = None,
    ) -> str:
        """Hybrid search scoped to vault Rules/ only (Codely routing rules).

        Does not search Pitfall/Tip/Concept/BugFix outside Rules/. Use vault_search for experience notes.
        """
        try:
            settings = Settings()
            rows = svc().search(
                query,
                top_k=top_k,
                type_="rule",
                domain=domain,
                path_prefix=settings.vault_rules_folder,
                dedupe_by_rule=True,
                required_rule_ids=_required_rule_ids(query, domain),
            )
            return json.dumps({"ok": True, "results": rows}, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.exception("rule_search failed")
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
