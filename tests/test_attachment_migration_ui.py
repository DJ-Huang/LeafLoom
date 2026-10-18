"""Bounded public task data and localized workspace presentation."""
import json
from pathlib import Path
import unittest
from vault_rag.attachment_migrations import AttachmentMigrations
ROOT=Path(__file__).resolve().parents[1]

class AttachmentMigrationUIContracts(unittest.TestCase):
    def test_public_task_data_is_bounded_and_does_not_expose_backup_details(self):
        job={'id':'a'*32,'root':'/fixture','state':'planning','phase':'planning','stage':'references',
             'documents':{'note.md':'private hash'},'moves':[{'source':f'{i}.png','destination':f'_attachments/{i}.png','size':1,'sha256':'private hash','backup':str(i)} for i in range(250)],
             'references':[f'{i}.md' for i in range(250)],'results':[{'path':f'{i}.png','state':'pending'} for i in range(250)],
             'blockers':[{'path':f'{i}.md','reason':'review'} for i in range(250)],'exclusions':[]}
        value=AttachmentMigrations._public(job)
        self.assertEqual(value['phase'],'planning');self.assertEqual(value['stage'],'references')
        for key in ['moves','references','results','blockers']:self.assertEqual(len(value[key]),200)
        self.assertEqual(value['results_total'],250);self.assertTrue(value['preview_limited'])
        self.assertNotIn('documents',value);self.assertNotIn('sha256',value['moves'][0]);self.assertNotIn('backup',value['moves'][0])
    def test_legacy_task_without_stage_is_still_readable(self):
        value=AttachmentMigrations._public({'id':'b'*32,'root':'/fixture','state':'ready','phase':'planned'})
        self.assertEqual(value['state'],'ready');self.assertNotIn('stage',value)
    def test_states_and_file_operations_are_translated(self):
        for language in ['en','zh-CN','ja']:
            values=json.loads((ROOT/f'vault_rag/locales/{language}.json').read_text())
            for state in ['planning','ready','blocked','running','completed','failed','interrupted','cancelled','rolling_back','rolled_back','conflict']:
                self.assertTrue(values['aw.state.'+state])
            for operation in ['organize','rename','move','trash']:self.assertTrue(values['aw.operation.'+operation])
            for key in ['aw.recycleLinks','aw.references','aw.protected','aw.limit','aw.fileResults']:self.assertTrue(values[key])
    def test_recovery_is_documented_in_all_guides(self):
        for language in ['en','zh-CN','ja']:
            guide=(ROOT/f'docs/{language}/GUIDE.md').read_text()
            for text in ['.vault-rag/attachment-migrations/<job-id>/','manifest.json','originals/','notes/']:self.assertIn(text,guide)

if __name__=='__main__':unittest.main()
