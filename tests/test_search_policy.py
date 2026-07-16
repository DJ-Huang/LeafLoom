from __future__ import annotations

import unittest

from llama_index.core.schema import NodeWithScore, TextNode

from vault_rag.service import (
    _dedupe_candidates,
    _effective_note_type,
    _ensure_required_rules,
    _metadata_match,
    _metadata_tokens,
)
from vault_rag.mcp_app import _required_rule_ids
from vault_rag.verification_rank import rank_search_candidates


def _candidate(
    node_id: str,
    score: float,
    *,
    file_path: str,
    verified_status: str = "verified_true",
    rule_id: str = "",
) -> NodeWithScore:
    node = TextNode(
        id_=node_id,
        text=node_id,
        metadata={
            "file_path": file_path,
            "verified_status": verified_status,
            "rule_id": rule_id,
        },
    )
    return NodeWithScore(node=node, score=score)


class MetadataPolicyTests(unittest.TestCase):
    def test_metadata_tokens_support_csv_json_and_lists(self) -> None:
        self.assertEqual(_metadata_tokens("unity, comfyui"), {"unity", "comfyui"})
        self.assertEqual(_metadata_tokens('["Unity", "PCG"]'), {"unity", "pcg"})
        self.assertEqual(_metadata_tokens(["Unity", "PCG"]), {"unity", "pcg"})

    def test_note_type_falls_back_to_tag_then_path(self) -> None:
        self.assertEqual(
            _effective_note_type({"tags": '["type/quick-tip"]', "file_path": "Other/x.md"}),
            "tip",
        )
        self.assertEqual(_effective_note_type({"file_path": "Pitfalls/x.md"}), "pitfall")
        self.assertEqual(_effective_note_type({"file_path": "Rules/core/x.md"}), "rule")

    def test_domain_membership_and_unclassified_fallback(self) -> None:
        self.assertTrue(_metadata_match({"domain": "unity,comfyui"}, type_=None, domain="unity"))
        self.assertTrue(_metadata_match({"domain": ""}, type_=None, domain="unity"))
        self.assertFalse(_metadata_match({"domain": "pcg"}, type_=None, domain="unity"))

    def test_type_filter_uses_path_inference(self) -> None:
        self.assertTrue(
            _metadata_match({"type": "", "file_path": "Pitfalls/x.md"}, type_="pitfall", domain=None)
        )


class RankingPolicyTests(unittest.TestCase):
    def test_verification_pool_preserves_relevance_order(self) -> None:
        limited = _candidate("limited", 0.9, file_path="Pitfalls/a.md", verified_status="limited")
        verified = _candidate("verified", 0.7, file_path="Pitfalls/b.md")
        preferred, backfill = rank_search_candidates(
            [limited, verified],
            restricted_prefixes=("Tips/",),
        )
        self.assertEqual([x.node.node_id for x in preferred], ["limited", "verified"])
        self.assertEqual(backfill, [])

    def test_dedupe_keeps_first_chunk_per_file(self) -> None:
        rows = [
            _candidate("a1", 0.9, file_path="Pitfalls/a.md"),
            _candidate("a2", 0.8, file_path="Pitfalls/a.md"),
            _candidate("b1", 0.7, file_path="Pitfalls/b.md"),
        ]
        unique = _dedupe_candidates(rows, prefer_rule_id=False)
        self.assertEqual([x.node.node_id for x in unique], ["a1", "b1"])

    def test_rule_dedupe_uses_rule_id(self) -> None:
        rows = [
            _candidate("r1", 0.9, file_path="Rules/a.md", rule_id="core/a"),
            _candidate("r2", 0.8, file_path="Rules/a.md", rule_id="core/a"),
        ]
        unique = _dedupe_candidates(rows, prefer_rule_id=True)
        self.assertEqual([x.node.node_id for x in unique], ["r1"])

    def test_required_rule_is_pinned_from_full_node_store(self) -> None:
        semantic = _candidate("semantic", 0.9, file_path="Rules/a.md", rule_id="core/a")
        required = _candidate("required", 0.1, file_path="Rules/b.md", rule_id="core/b")
        pinned = _ensure_required_rules(
            [semantic],
            all_nodes=[semantic.node, required.node],
            required_rule_ids=("core/b",),
        )
        self.assertEqual([x.node.node_id for x in pinned], ["required", "semantic"])

    def test_unity_write_contract_includes_stable_rules(self) -> None:
        self.assertEqual(
            _required_rule_ids("implement Unity shader code", "unity"),
            ("core/role", "core/anti-ai-trace", "core/hmirp-rendering-agent"),
        )


if __name__ == "__main__":
    unittest.main()
