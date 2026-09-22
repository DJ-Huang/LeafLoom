from __future__ import annotations

import gc
import json
import logging
from pathlib import Path
from typing import Any

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
        return (
            "pcg/project-engineering",
            "pcg/index",
            "pcg/graph-contract",
            "pcg/assembly-bevel",
        )
    return ()


def _rule_path_prefixes(settings: Settings, domain: str | None) -> tuple[str, ...]:
    """Expose the dedicated PCG-AI rule root only to the PCG domain."""
    prefixes = [settings.vault_rules_folder]
    if (domain or "").strip().lower() == "pcg":
        prefixes.append(settings.pcg_rules_folder)
    return tuple(prefixes)



# Keep evidence scope, but omit empty/index-only metadata from routine searches.
_COMPACT_METADATA_KEYS = (
    "domain", "rule_id", "techStack", "affectedPlatforms",
    "verified_date", "verification_scope", "common_assumption",
)


def _search_response(rows: list[dict[str, Any]], *, compact: bool) -> str:
    if not compact:
        return json.dumps({"ok": True, "results": rows}, ensure_ascii=False, indent=2)

    results = []
    for row in rows:
        result = {
            key: row[key]
            for key in (
                "chunk_id", "file_path", "note_type", "trust",
                "excerpt", "excerpt_truncated",
            )
            if key in row
        }
        metadata = row.get("metadata", {})
        scope = {
            key: metadata[key] for key in _COMPACT_METADATA_KEYS
            if metadata.get(key) not in (None, "", [], {})
        }
        if scope:
            result["metadata"] = scope
        if row.get("match_reason") == "required_rule":
            result["match_reason"] = "required_rule"
        results.append(result)
    return json.dumps({"ok": True, "results": results}, ensure_ascii=False,
                      separators=(",", ":"))


def build_mcp() -> FastMCP:
    mcp = FastMCP("vault-rag")
    svc_holder: dict[str, VaultRagService | None] = {"svc": None}

    def svc() -> VaultRagService:
        current = svc_holder["svc"]
        if current is not None and current._index_changed_since_load():
            logger.info("Index changed; recreating VaultRagService…")
            current._release_resources()
            svc_holder["svc"] = None
            gc.collect()
        if svc_holder["svc"] is None:
            svc_holder["svc"] = _service()
        return svc_holder["svc"]

    @mcp.tool()
    def vault_search(
        query: str,
        top_k: int = 3,
        note_type: str | None = None,
        domain: str | None = None,
        compact: bool = True,
    ) -> str:
        """Hybrid search (BM25 + dense vectors) over the Obsidian vault index.

        Use for missing project history or platform/compatibility evidence, not
        every coding task. Excludes rules; prefers verified/limited notes.
        Defaults to 3 compact results, retaining excerpts and evidence scope.
        Fetch vault_get_chunk before relying on excerpt_truncated=true results.
        Set compact=false for all original fields; explicit top_k is respected.
        """
        try:
            settings = Settings()
            rows = svc().search(
                query,
                top_k=top_k,
                type_=note_type,
                domain=domain,
                path_exclude_prefixes=(
                    settings.vault_rules_folder,
                    settings.pcg_rules_folder,
                ),
            )
            return _search_response(rows, compact=compact)
        except Exception as e:
            logger.exception("vault_search failed")
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    def rule_search(
        query: str,
        top_k: int = 3,
        domain: str | None = None,
        compact: bool = True,
    ) -> str:
        """Hybrid search over routing rules with domain-bound roots.

        Use only for known relevant Vault rules missing from current context.
        Project hard constraints should be loaded directly from project files.
        Defaults to 3 compact results; compact=false returns all original fields.
        Fetch vault_get_chunk before relying on excerpt_truncated=true results.
        Rules/ is eligible; legacy PCG AI Rule/ is restricted to domain=pcg.
        Use vault_search for experience notes.
        """
        try:
            settings = Settings()
            rows = svc().search(
                query,
                top_k=top_k,
                type_="rule",
                domain=domain,
                path_prefix=_rule_path_prefixes(settings, domain),
                dedupe_by_rule=True,
                required_rule_ids=_required_rule_ids(query, domain),
            )
            return _search_response(rows, compact=compact)
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
