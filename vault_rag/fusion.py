from __future__ import annotations

from llama_index.core.schema import NodeWithScore


def reciprocal_rank_fusion(
    ranked_lists: list[list[NodeWithScore]],
    *,
    k: int = 60,
    top_n: int,
) -> list[NodeWithScore]:
    """RRF merge multiple ranked result lists by node_id."""
    scores: dict[str, float] = {}
    best: dict[str, NodeWithScore] = {}
    for results in ranked_lists:
        for rank, nws in enumerate(results, start=1):
            nid = nws.node.node_id
            scores[nid] = scores.get(nid, 0.0) + 1.0 / (k + rank)
            # Keep the NodeWithScore with highest fused score tie-breaker: first seen
            if nid not in best:
                best[nid] = nws
    ordered = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    out: list[NodeWithScore] = []
    for nid in ordered[:top_n]:
        base = best[nid]
        out.append(NodeWithScore(node=base.node, score=scores[nid]))
    return out
