from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from llama_index.core.schema import NodeWithScore, TextNode

from vault_rag.mcp_app import build_mcp
from vault_rag.service import VaultRagService
from vault_rag.settings import Settings
from vault_rag.verification_rank import UNVERIFIED_EXCERPT_PREFIX


def make_service(nodes: list[TextNode]) -> VaultRagService:
    service = VaultRagService(Path(__file__).parent, Settings(_env_file=None))
    service._loaded = True
    service._nodes_by_id = {node.node_id: node for node in nodes}
    candidates = [NodeWithScore(node=node, score=0.9) for node in nodes]
    service._vector_retriever = SimpleNamespace(retrieve=lambda query: candidates)
    service._bm25 = SimpleNamespace(retrieve=lambda query: candidates)
    service._index_changed_since_load = lambda: False
    return service


def note(index: int, *, text: str = "Project-specific evidence.", **metadata) -> TextNode:
    return TextNode(
        id_=str(index), text=text,
        metadata={
            "file_path": f"Pitfalls/note-{index}.md",
            "verified_status": "limited",
            "domain": "unity",
            "verified_date": "2026-09-22",
            "verification_scope": "source review; no device test",
            "affectedPlatforms": "GLES3",
            "techStack": "Tuanjie 2022.3",
            "common_assumption": "Only valid for the recorded version",
            "header_path": "/",
            "empty_field": "",
            **metadata,
        },
    )


class McpResponseTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, service, name, arguments):
        with patch("vault_rag.mcp_app._service", return_value=service):
            result = await build_mcp().call_tool(name, arguments)
        if isinstance(result, tuple):
            result = result[0]
        return json.loads(next(block.text for block in result if block.type == "text"))

    async def test_search_defaults_keep_three_results_and_scope_without_index_noise(self):
        service = make_service([note(index) for index in range(5)])
        result = await self.call(service, "vault_search", {"query": "history"})
        self.assertTrue(result["ok"])
        self.assertEqual([row["chunk_id"] for row in result["results"]], ["0", "1", "2"])
        row = result["results"][0]
        self.assertEqual(row["trust"], "limited")
        self.assertEqual(row["metadata"]["verification_scope"], "source review; no device test")
        self.assertEqual(row["metadata"]["affectedPlatforms"], "GLES3")
        self.assertEqual(row["metadata"]["techStack"], "Tuanjie 2022.3")
        self.assertIn("common_assumption", row["metadata"])
        self.assertNotIn("empty_field", row["metadata"])
        self.assertNotIn("header_path", row["metadata"])
        self.assertNotIn("score", row)
        self.assertFalse(row["excerpt_truncated"])

    async def test_full_mode_and_explicit_limit_preserve_original_service_fields(self):
        service = make_service([note(index) for index in range(5)])
        expected = service.search("history", top_k=5)
        result = await self.call(service, "vault_search", {
            "query": "history", "top_k": 5, "compact": False,
        })
        self.assertEqual(result, {"ok": True, "results": expected})
        self.assertIn("empty_field", result["results"][0]["metadata"])

    async def test_unverified_warning_survives_and_truncated_excerpt_resolves_to_full_text(self):
        original = "Device observation. " * 100
        service = make_service([note(1, text=original, verified_status="unverified")])
        result = await self.call(service, "vault_search", {"query": "history"})
        row = result["results"][0]
        self.assertEqual(row["trust"], "unverified")
        self.assertTrue(row["excerpt"].startswith(UNVERIFIED_EXCERPT_PREFIX))
        self.assertTrue(row["excerpt_truncated"])
        full = await self.call(service, "vault_get_chunk", {"chunk_id": row["chunk_id"]})
        self.assertEqual(full["text"], original)
        self.assertEqual(full["metadata"]["verified_status"], "unverified")

    async def test_literal_ellipsis_is_not_mistaken_for_truncation(self):
        service = make_service([note(1, text="A short observation…")])
        result = await self.call(service, "vault_search", {"query": "history"})
        self.assertFalse(result["results"][0]["excerpt_truncated"])

    async def test_rule_search_stays_separate_and_supports_full_mode(self):
        rule = note(2, file_path="Rules/dcc/example.md", rule_id="dcc/example", domain="dcc")
        service = make_service([note(1), rule])
        rule_result = await self.call(service, "rule_search", {"query": "example", "domain": "dcc"})
        self.assertEqual([row["chunk_id"] for row in rule_result["results"]], ["2"])
        self.assertEqual(rule_result["results"][0]["metadata"]["rule_id"], "dcc/example")
        full = await self.call(service, "rule_search", {"query": "example", "domain": "dcc", "compact": False})
        self.assertIn("score", full["results"][0])
        experience = await self.call(service, "vault_search", {"query": "example"})
        self.assertEqual([row["chunk_id"] for row in experience["results"]], ["1"])

    async def test_no_hit_and_error_keep_distinct_outcomes(self):
        service = make_service([])
        no_hit = await self.call(service, "vault_search", {"query": "missing"})
        self.assertEqual(no_hit, {"ok": True, "results": []})
        service._vector_retriever.retrieve = lambda query: (_ for _ in ()).throw(RuntimeError("offline"))
        with self.assertLogs("vault_rag.mcp_app", level="ERROR"):
            error = await self.call(service, "vault_search", {"query": "history"})
        self.assertEqual(error, {"ok": False, "error": "offline"})

    async def test_tool_schema_exposes_compact_defaults(self):
        tools = {tool.name: tool for tool in await build_mcp().list_tools()}
        for name in ("vault_search", "rule_search"):
            schema = tools[name].inputSchema["properties"]
            self.assertEqual(schema["top_k"]["default"], 3)
            self.assertTrue(schema["compact"]["default"])


if __name__ == "__main__":
    unittest.main()
