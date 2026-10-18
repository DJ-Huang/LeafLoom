"""Source-level contracts for explicit metadata setup, no browser required."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class AttachmentInitializationUIContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'web/src/attachments.tsx').read_text()

    def test_status_first_and_listing_gated(self):
        self.assertIn("'attachments/status?'+new URLSearchParams({root})", self.source)
        self.assertIn('force:true', self.source)
        self.assertIn('{indexReady&&<>', self.source)
        self.assertIn('if(usable)void load(', self.source)
        self.assertNotIn("useEffect(()=>{void load(", self.source)
        self.assertNotIn("api('attachments/refresh'", self.source)

    def test_explicit_setup_and_supported_upgrade(self):
        self.assertIn("action:'initialize'|'rebuild'|'index-cancel'", self.source)
        self.assertIn("api('attachments/'+action,{root},'POST'", self.source)
        self.assertIn("status?.state==='unsupported'?null", self.source)
        self.assertIn("status.state==='needs_upgrade'?'initialize'", self.source)
        self.assertIn("onClick={()=>void act('index-cancel')}", self.source)

    def test_index_only_actions_are_collapsed_advanced(self):
        self.assertIn('<details className="attachment-advanced"><summary>', self.source)
        self.assertNotIn('<details open className="attachment-advanced">', self.source)
        self.assertNotIn('status&&<button className="primary"', self.source)
        self.assertIn('revision={indexRevision}', self.source)
        self.assertIn('},[refresh,revision]);', self.source)

    def test_polling_and_root_change_abort(self):
        self.assertIn('<AttachmentBrowser key={props.root}', self.source)
        self.assertIn("if(result.state==='building')timer.current=window.setTimeout", self.source)
        self.assertIn('sequence.current++;controller.abort();window.clearTimeout(timer.current)', self.source)
        self.assertIn('serial!==sequence.current||controller.signal.aborted', self.source)

    def test_localized_states_and_unified_setup(self):
        for language in ['en', 'zh-CN', 'ja']:
            values = json.loads((ROOT / f'vault_rag/locales/{language}.json').read_text())
            for key in ['initialize', 'upgrade', 'initializeSafety', 'retryInitialize', 'cancelBuild', 'advanced']:
                self.assertTrue(values['attachments.' + key])
            for state in ['uninitialized', 'ready', 'needs_upgrade', 'unsupported', 'building', 'failed', 'cancelled', 'interrupted']:
                self.assertTrue(values['attachments.indexState.' + state])
            self.assertTrue(values['migration.acknowledge'])

if __name__ == '__main__':
    unittest.main()
