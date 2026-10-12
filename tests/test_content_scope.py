from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vault_rag.loader import iter_markdown_documents
from vault_rag.vault_audit import audit_vault
from vault_rag.settings import Settings
from vault_rag.service import VaultRagService, _effective_domains, _effective_note_type
from vault_rag.mcp_app import _rule_path_prefixes
from vault_rag.verification_rank import is_backfill_only


class ContentScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = Settings(_env_file=None, vault_root=self.root)

    def write(self, path, text="---\nverified_status: limited\n---\nEvidence"):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def test_only_content_subtree_without_ragignore(self):
        self.write("RAG/Notes/inside.md")
        self.write("Elsewhere/outside.md")
        self.write("RAG-other/lookalike.md")
        self.write("root.md")
        self.write("RAG/README.md")
        self.write("RAG/Navigation/index.md")
        self.write("RAG/Notes/Attachments/ignored.md")
        self.write("RAG/Notes/opt-out.md", "---\nrag_index: false\n---\nNo")
        for load_ragignore in (True, False):
            self.settings.load_ragignore_file = load_ragignore
            docs = iter_markdown_documents(self.settings)
            self.assertEqual([d.metadata["file_path"] for d in docs], ["RAG/Notes/inside.md"])
            self.assertEqual(audit_vault(self.settings, self.root)["estimated_indexed_md"], 1)

    def test_scope_cannot_be_bypassed_by_negated_ignore_rule(self):
        self.write("RAG/Notes/inside.md")
        self.write("RAG/Navigation/index.md")
        self.write("Elsewhere/outside.md")
        self.write(".ragignore", "!**/*.md\n")
        self.assertEqual(len(iter_markdown_documents(self.settings)), 1)

    def test_missing_folder_and_invalid_configuration_never_fall_back(self):
        self.write("Elsewhere/outside.md")
        with self.assertRaises(FileNotFoundError):
            iter_markdown_documents(self.settings)
        for folder in ("", ".", "..", "../outside", "/tmp/outside", "C:\\outside"):
            with self.subTest(folder=folder), self.assertRaises(ValueError):
                Settings(_env_file=None, vault_content_folder=folder)

    def test_symlinks_do_not_import_outside_content(self):
        inside = self.write("RAG/Notes/inside.md")
        outside = self.write("Elsewhere/outside.md")
        (inside.parent / "external.md").symlink_to(outside)
        (inside.parent / "external-folder").symlink_to(outside.parent, target_is_directory=True)
        self.assertEqual([d.metadata["file_path"] for d in iter_markdown_documents(self.settings)],
                         ["RAG/Notes/inside.md"])
        alternate = Settings(_env_file=None, vault_root=self.root, vault_content_folder="Alias")
        (self.root / "Alias").symlink_to(self.root / "RAG", target_is_directory=True)
        with self.assertRaises(ValueError):
            alternate.resolved_content_root()

    def test_legacy_or_mismatched_index_refuses_search_and_chunk_lookup(self):
        self.write("RAG/Notes/inside.md")
        status = self.write(".vault-rag/status.json", json.dumps({"vault_root": str(self.root)}))
        svc = VaultRagService(self.root, self.settings)
        self.assertFalse(svc.status()["scope_matches_settings"])
        for action in (lambda: svc.search("query"), lambda: svc.get_chunk("legacy")):
            with self.assertRaisesRegex(RuntimeError, "reindex"):
                action()
        status.write_text(json.dumps({"vault_root": str(self.root), "vault_content_folder": "RAG",
                                    "vault_content_root": str(self.root / "Other"), "content_scope_version": 1}))
        self.assertFalse(svc.status()["scope_matches_settings"])

    def test_flat_types_domains_and_rules_scope(self):
        self.assertEqual(_effective_note_type({"file_path": "RAG/Notes/x.md", "tags": ["type/pitfall"]}), "pitfall")
        self.assertEqual(_effective_domains({"file_path": "RAG/Notes/x.md", "domain": "dcc"}), {"dcc"})
        self.assertEqual(_rule_path_prefixes(self.settings, "dcc"), ("RAG/Rules",))
        self.assertTrue(is_backfill_only({"file_path": "RAG/Notes/x.md"}, restricted_prefixes=()))
        self.assertFalse(is_backfill_only({"verified_status": "limited"}, restricted_prefixes=()))


if __name__ == "__main__":
    unittest.main()
