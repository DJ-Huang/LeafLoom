"""Synthetic-vault migration/recovery contracts. Never touch real user files."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from vault_rag.local_state import LocalConfig, ConflictError
from vault_rag.knowledge import Runtime
from vault_rag.attachment_migrations import AttachmentMigrations, file_hash


class AttachmentMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name).resolve()
        self.root=self.home/'vault';self.root.mkdir()
        self.config=LocalConfig(self.home/'state');self.config.save({'root':str(self.root)})
        self.runtime=Runtime(self.config);self.manager=AttachmentMigrations(self.runtime)

    def tearDown(self):
        self.manager.stop();self.runtime.stop();self.temp.cleanup()

    def put(self,path,data=b'fixture'):
        target=self.root/path;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(data if isinstance(data,bytes) else data.encode());return target

    def wait(self,key):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            state=self.manager.get(key)
            if state['state'] not in {'planning','running','rolling_back'}:return state
            time.sleep(.01)
        self.fail('migration did not finish')

    def plan(self,destination='_attachments'):
        result=self.manager.create(str(self.root),destination)
        return self.wait(result['id'])

    def execute(self,plan):
        self.manager.action(plan['id'],'execute',str(self.root),True)
        return self.wait(plan['id'])

    def manifest(self,key):
        return self.root/'.vault-rag/attachment-migrations'/key/'manifest.json'

    def test_preview_consolidates_references_and_rollback_preserves_all_bytes(self):
        self.put('left/image.png',b'image');self.put('right/image.png',b'other')
        original=b'\xef\xbb\xbf# Note\r\n![[left/image.png|alt]]\r\n![Photo](../right/image.png#view)\r\n'
        self.put('notes/a.md',original)
        plan=self.plan();self.assertEqual(plan['state'],'ready',plan)
        self.assertEqual(plan['summary']['files'],2);self.assertEqual(plan['summary']['notes'],1)
        self.assertEqual((self.root/'notes/a.md').read_bytes(),original)
        result=self.execute(plan);self.assertEqual(result['state'],'completed',result)
        self.assertFalse((self.root/'left/image.png').exists())
        self.assertEqual((self.root/'_attachments/left/image.png').read_bytes(),b'image')
        text=(self.root/'notes/a.md').read_bytes()
        self.assertIn(b'[[_attachments/left/image.png|alt]]',text)
        self.assertIn(b'../_attachments/right/image.png#view',text)
        self.assertTrue(text.startswith(b'\xef\xbb\xbf'));self.assertIn(b'\r\n',text)
        self.assertEqual(self.runtime.files.resolve('image.png'),['_attachments/left/image.png','_attachments/right/image.png'])
        self.manager.action(plan['id'],'rollback',str(self.root),True)
        rolled=self.wait(plan['id']);self.assertEqual(rolled['state'],'rolled_back',rolled)
        self.assertEqual((self.root/'notes/a.md').read_bytes(),original)
        self.assertEqual((self.root/'left/image.png').read_bytes(),b'image')
        self.assertFalse((self.root/'_attachments/left/image.png').exists())
        self.assertEqual(len(list((self.manifest(plan['id']).parent/'rolled-back-copies').iterdir())),2)

    def test_collision_never_overwrites_existing_target(self):
        self.put('a.png',b'new');self.put('_attachments/a.png',b'existing')
        self.put('a.md','![[a.png]]')
        plan=self.plan();self.assertEqual(plan['state'],'ready',plan)
        self.assertNotEqual(plan['moves'][0]['destination'],'_attachments/a.png')
        self.assertEqual(self.execute(plan)['state'],'completed')
        self.assertEqual((self.root/'_attachments/a.png').read_bytes(),b'existing')

    def test_html_project_and_shared_external_dependencies_are_excluded(self):
        self.put('site/index.html','<link rel="stylesheet" href="../shared/site.css"><img src="../shared/logo.png">')
        self.put('site/local.png');self.put('shared/site.css','body { background:url(bg.png) }')
        self.put('shared/logo.png');self.put('shared/bg.png');self.put('loose/photo.png')
        self.put('note.md','![[loose/photo.png]]')
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        plan=self.plan();self.assertEqual(plan['state'],'ready',plan)
        self.assertEqual([m['source'] for m in plan['moves']],['loose/photo.png'])
        self.assertEqual(plan['summary']['excluded'],3)
        self.assertEqual(self.execute(plan)['state'],'completed')
        for path,data in before.items():
            if path.relative_to(self.root).parts[0] in ('site','shared'):self.assertEqual(path.read_bytes(),data)

    def test_ambiguity_blocks_execution_without_modifications(self):
        self.put('one/a.png');self.put('two/a.png');self.put('note.md','![[a.png]]')
        plan=self.plan();self.assertEqual(plan['state'],'blocked')
        with self.assertRaises(ConflictError):self.manager.action(plan['id'],'execute',str(self.root),True)
        self.assertTrue((self.root/'one/a.png').exists())

    def test_note_drift_blocks_without_overwriting_edits(self):
        self.put('a.png');self.put('n.md','![[a.png]]');plan=self.plan()
        self.put('n.md','My new edit ![[a.png]]')
        result=self.execute(plan);self.assertEqual(result['state'],'conflict',result)
        self.assertEqual((self.root/'n.md').read_text(),'My new edit ![[a.png]]')
        self.assertTrue((self.root/'a.png').exists())

    def test_low_space_preserves_originals(self):
        self.put('a.png');self.put('n.md','![[a.png]]');plan=self.plan()
        with patch('vault_rag.attachment_migrations.shutil.disk_usage',return_value=type('Usage',(),{'free':0})()):
            result=self.execute(plan)
        self.assertEqual(result['state'],'rolled_back',result)
        self.assertTrue((self.root/'a.png').exists());self.assertIn('disk space',result['error'])

    def test_copy_failure_rolls_back_verified_copies(self):
        self.put('a.png');self.put('b.png');self.put('n.md','![[a.png]] ![[b.png]]');plan=self.plan()
        original=self.manager._copy;calls=[]
        def broken(files,job,move):
            calls.append(move['source'])
            if len(calls)==2:raise OSError('fixture interrupted copy')
            return original(files,job,move)
        with patch.object(self.manager,'_copy',side_effect=broken):result=self.execute(plan)
        self.assertEqual(result['state'],'rolled_back',result)
        self.assertTrue((self.root/'a.png').exists());self.assertFalse((self.root/'_attachments/a.png').exists())
        self.assertEqual((self.root/'n.md').read_text(),'![[a.png]] ![[b.png]]')

    def test_cancel_copy_rolls_back_and_reopening_reads_journal(self):
        self.put('a.png');self.put('b.png');plan=self.plan()
        original=self.manager._copy;entered=threading.Event();release=threading.Event()
        def slow(files,job,move):
            original(files,job,move);entered.set();release.wait(3)
        with patch.object(self.manager,'_copy',side_effect=slow):
            self.manager.action(plan['id'],'execute',str(self.root),True);self.assertTrue(entered.wait(2))
            self.manager.action(plan['id'],'cancel',str(self.root));release.set();result=self.wait(plan['id'])
        self.assertEqual(result['state'],'rolled_back',result)
        reopened=AttachmentMigrations(self.runtime)
        self.assertEqual(reopened.get(plan['id'])['state'],'rolled_back')
        self.assertTrue((self.root/'a.png').exists())

    def test_interrupted_copy_resume_and_same_content_external_target_refused(self):
        self.put('a.png');self.put('n.md','![[a.png]]');plan=self.plan()
        files=self.manager._files();job=self.manager._load(files,plan['id'])
        job['state']='running';job['phase']='copying';self.manager._save(files,job)
        self.manager._copy(files,job,job['moves'][0])
        reopened=AttachmentMigrations(self.runtime);self.manager=reopened
        self.assertEqual(reopened.get(plan['id'])['state'],'interrupted')
        reopened.action(plan['id'],'resume',str(self.root),True)
        self.assertEqual(self.wait(plan['id'])['state'],'completed')
        # Separate fixture plan: an unrelated same-content target is not ours.
        self.put('b.png');next_plan=self.plan('OtherAssets')
        move=next(m for m in next_plan['moves'] if m['source']=='b.png')
        self.put(move['destination'])
        result=self.execute(next_plan)
        self.assertEqual(result['state'],'conflict',result)
        self.assertTrue((self.root/move['destination']).exists());self.assertTrue((self.root/'b.png').exists())

    def test_rollback_refuses_postmigration_document_edits(self):
        self.put('a.png');self.put('n.md','![[a.png]]');plan=self.plan();self.execute(plan)
        self.put('n.md','My postmigration edit')
        self.manager.action(plan['id'],'rollback',str(self.root),True);result=self.wait(plan['id'])
        self.assertEqual(result['state'],'conflict');self.assertEqual((self.root/'n.md').read_text(),'My postmigration edit')
        self.assertTrue((self.root/'_attachments/a.png').exists())

    def test_in_app_mutations_are_rejected_during_execution_then_reenabled(self):
        self.put('a.png');self.put('n.md','![[a.png]]');plan=self.plan()
        original=self.manager._copy;entered=threading.Event();release=threading.Event()
        def slow(files,job,move):
            original(files,job,move);entered.set();release.wait(3)
        with patch.object(self.manager,'_copy',side_effect=slow):
            self.manager.action(plan['id'],'execute',str(self.root),True)
            self.assertTrue(entered.wait(2))
            value=self.runtime.files.read('n.md')
            with self.assertRaises(ConflictError):self.runtime.files.save('n.md','new edit',value['etag'])
            with self.assertRaises(ConflictError):self.runtime.files.create('new.md',text='![[a.png]]')
            with self.assertRaises(ConflictError):self.runtime.files.delete('a.png')
            release.set();self.assertEqual(self.wait(plan['id'])['state'],'completed')
        self.manager.threads[plan['id']].join(2)
        value=self.runtime.files.read('n.md')
        self.runtime.files.save('n.md','new accepted edit',value['etag'])
        self.assertEqual((self.root/'n.md').read_text(),'new accepted edit')

    def test_source_project_shared_config_reference_is_protected_or_blocks(self):
        self.put('code/package.json','{"icon":"../shared/icon.png"}')
        self.put('shared/icon.png');self.put('loose.png')
        plan=self.plan()
        self.assertEqual(plan['state'],'blocked',plan)
        self.assertTrue((self.root/'shared/icon.png').exists())

    def test_previously_irrelevant_config_drift_is_detected(self):
        self.put('a.png');self.put('settings.cfg','theme=blue');plan=self.plan()
        self.put('settings.cfg','icon=a.png')
        result=self.execute(plan)
        self.assertEqual(result['state'],'conflict',result)
        self.assertTrue((self.root/'a.png').exists())
        self.assertEqual((self.root/'settings.cfg').read_text(),'icon=a.png')

    @unittest.skipIf(os.name=='nt','POSIX permission contract')
    def test_private_file_mode_survives_copy_and_rollback(self):
        asset=self.put('a.png');asset.chmod(0o600);plan=self.plan()
        result=self.execute(plan);self.assertEqual(result['state'],'completed')
        self.assertEqual((self.root/'_attachments/a.png').stat().st_mode & 0o777,0o600)
        self.manager.action(plan['id'],'rollback',str(self.root),True)
        self.assertEqual(self.wait(plan['id'])['state'],'rolled_back')
        self.assertEqual(asset.stat().st_mode & 0o777,0o600)

    def test_external_source_change_during_retirement_preserves_new_bytes(self):
        self.put('a.png',b'old');plan=self.plan()
        from vault_rag.attachment_migrations import move_exclusive
        def race(source,destination):
            if source==self.root/'a.png':source.write_bytes(b'new external bytes')
            return move_exclusive(source,destination)
        with patch('vault_rag.attachment_migrations.move_exclusive',side_effect=race):result=self.execute(plan)
        self.assertEqual(result['state'],'conflict',result)
        self.assertEqual((self.root/'a.png').read_bytes(),b'new external bytes')



    @unittest.skipIf(os.name == 'nt', 'POSIX journal modes')
    def test_journal_private_and_nonprivate_resume_refused(self):
        self.put('a.png');note=self.put('n.md','![[a.png]]');note.chmod(0o600)
        plan=self.plan();directory=self.runtime.files.state_path('attachment-migrations',plan['id'])
        self.assertEqual(directory.stat().st_mode & 0o777,0o700)
        directory.chmod(0o755)
        with self.assertRaises(ValueError):self.manager.action(plan['id'],'execute',str(self.root),True)

    def test_final_index_failure_rolls_back_and_restores_index(self):
        self.put('a.png');self.put('n.md','![[a.png]]');plan=self.plan()
        refresh=self.runtime.files.attachments.refresh
        calls=[]
        def fail_once(*args,**kwargs):
            calls.append(1)
            if len(calls)==1:raise OSError('injected final index failure')
            return refresh(*args,**kwargs)
        with patch.object(self.runtime.files.attachments,'refresh',side_effect=fail_once):
            result=self.execute(plan)
        self.assertEqual(result['state'],'rolled_back',result)
        self.assertTrue((self.root/'a.png').exists())
        self.assertEqual((self.root/'n.md').read_text(),'![[a.png]]')
        self.assertEqual(self.runtime.files.attachments.listing()['items'][0]['path'],'a.png')
        self.assertEqual(len(calls),2)

    def test_unified_preview_failure_does_not_move_files(self):
        self.put('a.png');self.put('n.md','![[a.png]]')
        with patch.object(self.runtime.files.attachments,'refresh',side_effect=OSError('index unavailable')):
            result=self.plan()
        self.assertEqual(result['state'],'failed')
        self.assertTrue((self.root/'a.png').exists())
        self.assertFalse((self.root/'_attachments').exists())
