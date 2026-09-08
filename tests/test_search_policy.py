from __future__ import annotations

import unittest

from llama_index.core.schema import NodeWithScore, TextNode

from vault_rag.service import (
    _dedupe_candidates,
    _effective_domains,
    _effective_note_type,
    _ensure_required_rules,
    _metadata_match,
    _metadata_tokens,
    _passes_relevance_gate,
    _path_under_prefix,
)
from vault_rag.mcp_app import (
    _filter_rule_scope,
    _is_hmirp_query,
    _required_rule_ids,
    _rule_path_prefixes,
)
from vault_rag.settings import Settings
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

    def test_general_domain_excludes_inferred_specialized_notes(self) -> None:
        dcc = {"domain": "", "file_path": "DCC/Blender/guide.md"}
        unity = {"domain": "", "file_path": "Pitfalls/x.md", "techStack": "Unity, URP"}
        tmp = {"domain": "", "file_path": "Concepts/cpt-tmp-per-glyph-uv-mirror.md"}
        generic = {"domain": "", "file_path": "Concepts/generic-cli.md"}
        self.assertEqual(_effective_domains(dcc), {"dcc"})
        self.assertEqual(_effective_domains(unity), {"unity"})
        self.assertEqual(_effective_domains(tmp), {"unity"})
        self.assertFalse(_metadata_match(dcc, type_=None, domain="general"))
        self.assertFalse(_metadata_match(unity, type_=None, domain="general"))
        self.assertFalse(_metadata_match(tmp, type_=None, domain="general"))
        self.assertTrue(_metadata_match(generic, type_=None, domain="general"))

    def test_type_filter_uses_path_inference(self) -> None:
        self.assertTrue(
            _metadata_match({"type": "", "file_path": "Pitfalls/x.md"}, type_="pitfall", domain=None)
        )

    def test_multiple_path_prefixes_are_supported(self) -> None:
        prefixes = ("Rules", "PCG AI Rule")
        self.assertTrue(_path_under_prefix("Rules/core/a.md", prefixes))
        self.assertTrue(_path_under_prefix("PCG AI Rule/Graph Authoring/a.md", prefixes))
        self.assertFalse(_path_under_prefix("Pitfalls/a.md", prefixes))

    def test_pcg_rule_root_is_domain_bound(self) -> None:
        settings = Settings(_env_file=None)
        self.assertEqual(_rule_path_prefixes(settings, "unity"), (settings.vault_rules_folder,))
        self.assertEqual(_rule_path_prefixes(settings, "pcg"), (settings.vault_rules_folder,))


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

    def test_required_rule_cannot_escape_allowed_roots(self) -> None:
        outside = _candidate(
            "outside",
            0.1,
            file_path="Pitfalls/not-a-rule.md",
            rule_id="core/required",
        )
        pinned = _ensure_required_rules(
            [],
            all_nodes=[outside.node],
            required_rule_ids=("core/required",),
            path_prefix=("Rules", "PCG AI Rule"),
        )
        self.assertEqual(pinned, [])

    def test_generic_unity_write_does_not_include_hmirp_rules(self) -> None:
        self.assertFalse(_is_hmirp_query("implement Unity shader code"))
        self.assertEqual(_required_rule_ids("implement Unity shader code", "unity"), ())

    def test_hmirp_write_contract_includes_project_rules(self) -> None:
        self.assertTrue(_is_hmirp_query("implement HMIRP shader code"))
        self.assertTrue(_is_hmirp_query("fix Unity Runtime.Stable placement"))
        self.assertEqual(
            _required_rule_ids("implement HMIRP shader code", "unity"),
            ("core/role", "core/anti-ai-trace", "core/hmirp-rendering-agent"),
        )

    def test_non_hmirp_unity_search_filters_project_rules(self) -> None:
        rows = [
            {"metadata": {"rule_id": "core/hmirp-rendering-agent"}},
            {"metadata": {"rule_id": "core/generic-unity"}},
        ]
        self.assertEqual(
            _filter_rule_scope(rows, query="implement Unity shader", domain="unity"),
            [{"metadata": {"rule_id": "core/generic-unity"}}],
        )

    def test_pcg_contract_uses_project_local_kb(self) -> None:
        self.assertEqual(_required_rule_ids("author a vehicle graph", "pcg"), ())
        self.assertEqual(
            _filter_rule_scope(
                [{"metadata": {"rule_id": "pcg/project-engineering"}}],
                query="author a vehicle graph",
                domain="pcg",
            ),
            [],
        )

    def test_relevance_gate_uses_vector_similarity(self) -> None:
        candidate = _candidate("candidate", 0.03, file_path="Pitfalls/a.md")
        self.assertFalse(
            _passes_relevance_gate(
                candidate,
                vector_scores={"candidate": 0.39},
                min_vector_score=0.40,
            )
        )
        self.assertTrue(
            _passes_relevance_gate(
                candidate,
                vector_scores={"candidate": 0.41},
                min_vector_score=0.40,
            )
        )


if __name__ == "__main__":
    unittest.main()
