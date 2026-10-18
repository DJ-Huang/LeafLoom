"""Source-level UI safety contracts; no real vault or browser is opened."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AttachmentMigrationUIContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'web/src/attachments.tsx').read_text()

    def test_execute_requires_ready_plan_acknowledgement_and_no_blockers(self):
        self.assertIn("job.state==='ready'", self.source)
        self.assertIn('disabled={busy||blocked||!acknowledged}', self.source)
        self.assertIn("onClick={()=>void act('execute')}", self.source)
        self.assertIn("action==='preview'?{root,destination:destination.trim()}", self.source)
        self.assertIn("action==='cancel'?{}:{confirm:true}", self.source)
        self.assertIn('setAcknowledged(false)', self.source)

    def test_unified_setup_uses_one_preview_and_refreshes_status(self):
        self.assertIn('<AttachmentMigration root={root} onChanged={migrationChanged}/>', self.source)
        self.assertIn('onChanged(value.state)', self.source)
        self.assertIn('setIndexRevision(value=>value+1)', self.source)
        self.assertIn('<button className="primary" disabled={busy||!!active||!destination.trim()}>', self.source)
        values = json.loads((ROOT / 'vault_rag/locales/en.json').read_text())
        self.assertEqual(values['migration.preview'], 'Initialize / upgrade and organize attachments')
        self.assertIn('one confirmation', values['migration.intro'])
        self.assertIn('recovery storage', values['migration.executeWarning'])

    def test_persisted_jobs_polling_and_root_scoping(self):
        self.assertIn("api<{jobs:Migration[]}>('attachments/migrations'", self.source)
        self.assertIn('item.root===root', self.source)
        self.assertIn('controller.abort()', self.source)
        self.assertIn('window.clearTimeout(timer)', self.source)
        self.assertIn('serial===sequence.current&&!controller.signal.aborted', self.source)
        self.assertIn("<Attachments root={config.root!}", (ROOT / 'web/src/main.tsx').read_text())

    def test_recovery_actions_require_separate_confirmation(self):
        self.assertIn("onClick={()=>setConfirmation('rollback')}", self.source)
        self.assertIn("onClick={()=>setConfirmation('resume')}", self.source)
        self.assertIn('onClick={()=>void act(confirmation)}', self.source)
        self.assertNotIn("act('delete')", self.source)
        self.assertIn('job.blockers!.map', self.source)
        self.assertIn('job.exclusions.map', self.source)

    def test_all_states_and_safety_labels_are_translated(self):
        states = ['planning', 'ready', 'blocked', 'running', 'completed', 'cancelled',
                  'failed', 'interrupted', 'rolling_back', 'rolled_back', 'conflict']
        labels = ['acknowledge', 'safety', 'executeWarning', 'recovery',
                  'confirm.rollback', 'confirm.resume', 'blockers', 'exclusions']
        for language in ['en', 'zh-CN', 'ja']:
            values = json.loads((ROOT / f'vault_rag/locales/{language}.json').read_text())
            for key in [f'migration.state.{state}' for state in states] + [f'migration.{label}' for label in labels]:
                with self.subTest(language=language, key=key):
                    self.assertTrue(values[key])

    def test_recovery_storage_documented_in_all_guides(self):
        for language in ['en', 'zh-CN', 'ja']:
            guide = (ROOT / f'docs/{language}/GUIDE.md').read_text()
            for value in ['.vault-rag/attachment-migrations/<job-id>/', 'manifest.json', 'originals/', 'notes/']:
                with self.subTest(language=language, value=value):
                    self.assertIn(value, guide)


if __name__ == '__main__':
    unittest.main()
