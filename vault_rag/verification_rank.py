from __future__ import annotations

from typing import Any

from llama_index.core.schema import NodeWithScore

# Higher tier = preferred in vault_search before backfill pool.
TIER_VERIFIED_TRUE = 3
TIER_LIMITED = 2
TIER_UNKNOWN = 1
TIER_UNVERIFIED = 0

UNVERIFIED_EXCERPT_PREFIX = "[未验证·仅作线索，勿当规范] "


def verification_tier(meta: dict[str, Any]) -> int:
    vs = str(meta.get("verified_status", "")).strip().lower()
    if vs == "verified_true":
        return TIER_VERIFIED_TRUE
    if vs == "limited":
        return TIER_LIMITED
    if vs == "unverified":
        return TIER_UNVERIFIED
    return TIER_UNKNOWN


def trust_label(tier: int) -> str:
    if tier == TIER_VERIFIED_TRUE:
        return "verified_true"
    if tier == TIER_LIMITED:
        return "limited"
    if tier == TIER_UNVERIFIED:
        return "unverified"
    return "unknown"


def is_backfill_only(
    meta: dict[str, Any],
    *,
    restricted_prefixes: tuple[str, ...],
) -> bool:
    """
    True → only used when preferred pool cannot fill top_k.

    - explicit unverified: always backfill
    - unknown status under Tips/Features/BugFix: backfill (no implicit trust)
    """
    tier = verification_tier(meta)
    if tier == TIER_UNVERIFIED:
        return True
    fp = str(meta.get("file_path", ""))
    if tier == TIER_UNKNOWN and any(fp.startswith(p) for p in restricted_prefixes):
        return True
    return False


def rank_search_candidates(
    merged: list[NodeWithScore],
    *,
    restricted_prefixes: tuple[str, ...],
) -> tuple[list[NodeWithScore], list[NodeWithScore]]:
    """Split RRF-ordered hits into preferred vs backfill pools (each keeps RRF order within pool)."""
    preferred: list[NodeWithScore] = []
    backfill: list[NodeWithScore] = []
    for nws in merged:
        meta = dict(nws.node.metadata or {})
        if is_backfill_only(meta, restricted_prefixes=restricted_prefixes):
            backfill.append(nws)
        else:
            preferred.append(nws)

    # Higher verification tier first, then fused score.
    def sort_key(nws: NodeWithScore) -> tuple[int, float]:
        meta = dict(nws.node.metadata or {})
        return (verification_tier(meta), float(nws.score or 0.0))

    preferred.sort(key=sort_key, reverse=True)
    backfill.sort(key=sort_key, reverse=True)
    return preferred, backfill


def select_for_top_k(
    preferred: list[NodeWithScore],
    backfill: list[NodeWithScore],
    top_k: int,
) -> list[tuple[NodeWithScore, str]]:
    """Return (node, ranking) with ranking 'preferred' | 'backfill'."""
    out: list[tuple[NodeWithScore, str]] = []
    for nws in preferred:
        if len(out) >= top_k:
            break
        out.append((nws, "preferred"))
    if len(out) < top_k:
        for nws in backfill:
            if len(out) >= top_k:
                break
            out.append((nws, "backfill"))
    return out
