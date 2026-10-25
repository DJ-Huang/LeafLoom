"""Attachment identity and visibility across destinations and folder-sync lag."""
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import httpx

import test_remote_attachments as fixtures
import test_attachment_initialization_ui as api_fixtures
from vault_rag.attachment_catalog import AttachmentCatalog
from vault_rag.attachment_index_jobs import AttachmentIndexJobs
from vault_rag.local_state import Files, LocalConfig
from vault_rag.remote_attachments import RemoteAttachments
from vault_rag.remote_webdav import RemoteStorageError


class ModeSwitchingTests(unittest.TestCase):
    setUp = fixtures.RemoteAttachmentTests.setUp
    tearDown = fixtures.RemoteAttachmentTests.tearDown
    manager_for_config = fixtures.RemoteAttachmentTests.manager_for_config
    put = fixtures.RemoteAttachmentTests.put

    def context(self):
        files=Files(self.config)
        catalog=AttachmentCatalog(files.attachments,self.manager)
        runtime=SimpleNamespace(files=files,config=self.config,remote_attachments=self.manager)
        return files,catalog,AttachmentIndexJobs(runtime)

    def destination(self, value):
        settings=self.manager._settings(str(self.root));settings['default_source']=value
        self.manager.save(str(self.root),settings)

    def remote_file(self, alias='old/image.png'):
        self.dav.files['Incoming/remote.png']=b'remote-original'
        self.manager.scan(str(self.root),fixtures.SOURCE)
        with self.manager.lock,self.manager._db(str(self.root)) as db:
            key=db.execute("SELECT id FROM assets WHERE path='Incoming/remote.png'").fetchone()[0]
            db.execute('INSERT OR IGNORE INTO aliases VALUES(?,?)',(alias,key))
        return key

    def test_local_only_needs_no_server_and_preserves_relative_note_links(self):
        self.manager.save(str(self.root),{'sources':[],'default_source':'local'})
        target=self.put('_attachments/image.png',b'local-original')
        note=self.put('notes/page.md',b'![image](../_attachments/image.png)')
        files,catalog,jobs=self.context()
        self.assertFalse(jobs.status()['usable'])
        with patch.object(self.manager,'_provider',side_effect=AssertionError('network')):
            jobs.start(str(self.root));jobs.thread.join(5)
            self.assertTrue(jobs.status()['local_index']['usable'])
            self.assertEqual(catalog.listing()['total'],1)
            self.assertEqual(catalog.resolve('../_attachments/image.png','notes/page.md'),['_attachments/image.png'])
            self.assertEqual(target.read_bytes(),b'local-original')
            self.assertEqual(note.read_bytes(),b'![image](../_attachments/image.png)')

    def test_switching_destination_retains_both_catalogs_and_offline_links(self):
        self.put('local/image.png',b'local-original');key=self.remote_file()
        files,catalog,jobs=self.context();files.attachments.refresh()
        cached=self.manager.materialize(str(self.root),asset_id=key)
        self.dav.offline=True
        for destination in ('local',fixtures.SOURCE,'local',fixtures.SOURCE):
            with self.subTest(destination=destination):
                self.destination(destination)
                self.assertTrue(jobs.status()['usable'])
                page=catalog.listing()
                self.assertEqual(page['total'],2)
                self.assertEqual({x['source'] for x in page['items']},{'local','remote'})
                self.assertEqual(catalog.listing(source='local')['total'],1)
                self.assertEqual(catalog.listing(source='remote')['total'],1)
                self.assertEqual(catalog.resolve('old/image.png'),['old/image.png'])
                self.assertEqual(catalog.resolve('local/image.png'),['local/image.png'])
                self.assertEqual(self.manager.materialize(str(self.root),asset_id=key),cached)
        self.assertEqual((self.root/'local/image.png').read_bytes(),b'local-original')

    def test_server_to_local_before_local_setup_keeps_server_catalog_available(self):
        self.put('unindexed.png',b'local');self.remote_file()
        files,catalog,jobs=self.context()
        with patch.object(Files,'walk',side_effect=AssertionError('implicit local scan')):
            for destination in (fixtures.SOURCE,'local'):
                self.destination(destination)
                status=jobs.status()
                self.assertTrue(status['usable']);self.assertFalse(status['local_index']['usable'])
                self.assertEqual(catalog.listing()['total'],1)
        self.assertFalse(files.state_path('attachments.sqlite').exists())
        jobs.start(str(self.root));jobs.thread.join(5)
        self.assertTrue(jobs.status()['local_index']['usable'])
        self.assertEqual(catalog.listing()['total'],2)
        self.assertEqual(self.manager.jobs(str(self.root)),[])

    def test_incompatible_local_index_does_not_block_server_or_get_overwritten(self):
        self.remote_file();files,catalog,jobs=self.context();path=files.state_path('attachments.sqlite')
        with sqlite3.connect(path) as db:db.execute('PRAGMA user_version=99')
        before=path.read_bytes()
        for destination in (fixtures.SOURCE,'local'):
            self.destination(destination)
            self.assertTrue(jobs.status()['usable'])
            self.assertEqual(jobs.status()['local_index']['state'],'unsupported')
            self.assertEqual(catalog.listing()['total'],1)
            with self.assertRaises(ValueError):jobs.start(str(self.root))
        self.assertEqual(path.read_bytes(),before)

    def test_existing_local_path_and_remote_alias_remain_distinct(self):
        self.put('image.png',b'new-local-file');remote_id=self.remote_file('image.png')
        files,catalog,jobs=self.context();files.attachments.refresh()
        for destination in ('local',fixtures.SOURCE):
            self.destination(destination)
            page=catalog.listing();self.assertEqual(page['total'],2)
            local=next(x for x in page['items'] if x['source']=='local')
            remote=next(x for x in page['items'] if x['source']=='remote')
            self.assertEqual(local['path'],'image.png');self.assertNotEqual(remote['path'],'image.png')
            self.assertEqual(catalog.resolve('image.png'),['image.png'])
            self.assertEqual(self.manager.stat(str(self.root),'image.png')['storage_id'],'local')
            self.assertEqual(self.manager.stat(str(self.root),asset_id=remote_id)['storage_id'],fixtures.SOURCE)

    def test_full_old_path_is_not_shadowed_by_local_basename_after_switch(self):
        self.put('unrelated/image.png',b'other-file');self.remote_file()
        files,catalog,jobs=self.context();files.attachments.refresh()
        for destination in ('local',fixtures.SOURCE):
            self.destination(destination)
            self.assertEqual(catalog.resolve('old/image.png'),['old/image.png'])
            self.assertEqual(catalog.resolve('image.png'),[])
            self.assertEqual(catalog.resolve('missing/image.png'),[])

    def test_queued_server_upload_keeps_original_destination_after_switch(self):
        queued=self.manager.queue_upload(str(self.root),fixtures.SOURCE,'_attachments/pending.png',b'pending-bytes')
        self.destination('local');self.manager.process_pending()
        completed=self.manager.job(str(self.root),queued['id'])
        self.assertEqual(completed['state'],'completed')
        self.assertEqual(completed['source_id'],fixtures.SOURCE)
        self.assertFalse((self.root/'_attachments/pending.png').exists())
        self.assertEqual(self.dav.files[completed['remote_path']],b'pending-bytes')

    def test_uncached_server_reference_does_not_fall_back_to_same_name_local_file(self):
        self.put('unrelated/image.png',b'wrong-file');self.remote_file()
        self.destination('local');self.dav.offline=True
        with self.assertRaises(RemoteStorageError):self.manager.materialize(str(self.root),'old/image.png')
        self.assertEqual((self.root/'unrelated/image.png').read_bytes(),b'wrong-file')

    def test_pure_local_peers_keep_independent_indexes_after_file_sync(self):
        self.manager.save(str(self.root),{'sources':[],'default_source':'local'})
        self.put('_attachments/image.png',b'local-original')
        note=self.put('notes/page.md',b'![image](../_attachments/image.png)')
        files,catalog,jobs=self.context();files.attachments.refresh()
        second=self.home/'synced-vault';shutil.copytree(self.root,second)
        config=LocalConfig(self.home/'peer-state');config.save({'root':str(second)})
        peer=Files(config);peer.attachments.refresh()
        self.assertNotEqual(files.state_path('attachments.sqlite'),peer.state_path('attachments.sqlite'))
        self.assertFalse(peer.state_path('attachments.sqlite').is_relative_to(second))
        self.assertEqual(peer.resolve('../_attachments/image.png','notes/page.md'),['_attachments/image.png'])
        new=self.put('_attachments/new.png',b'new');files.attachments.apply(['_attachments/new.png'])
        self.assertEqual(peer.attachments.listing()['total'],1)
        shutil.copyfile(new,second/'_attachments/new.png');peer.attachments.apply(['_attachments/new.png'])
        self.assertEqual(peer.attachments.listing()['total'],2)
        self.assertEqual((second/'notes/page.md').read_bytes(),note.read_bytes())

    def test_external_local_presence_change_invalidates_a_sorted_cursor(self):
        self.put('local.png',b'local');self.remote_file()
        files,catalog,jobs=self.context();files.attachments.refresh()
        cursor=catalog.listing(limit=1)['cursor'];self.assertTrue(cursor)
        (self.root/'local.png').unlink()
        from vault_rag.local_state import ConflictError
        with self.assertRaises(ConflictError):catalog.listing(limit=1,cursor=cursor)

    def test_peer_keeps_local_copy_until_folder_sync_delivers_deletion(self):
        original=self.put('_attachments/photo.png',b'original')
        old_id=self.manager.stat(str(self.root),'_attachments/photo.png')['asset_id']
        peer_root=self.home/'second-vault';shutil.copytree(self.root,peer_root)
        peer_config=LocalConfig(self.home/'second-state');peer_config.save({'root':str(peer_root)})
        with patch.object(RemoteAttachments,'_loop',return_value=None):peer=RemoteAttachments(peer_config)
        self.managers.append(peer);peer.transports[fixtures.SOURCE]=self.transport
        settings=self.manager._settings(str(self.root));peer.save(str(peer_root),{'sources':settings['sources'],'default_source':fixtures.SOURCE})
        peer.set_credentials(fixtures.SOURCE,'leafloom',fixtures.SECRET,revision='peer')
        with peer.lock,peer._db(str(peer_root)) as db:
            peer._upsert(db,'local',{'path':'_attachments/photo.png','size':8},asset_id=old_id)
            db.execute('INSERT INTO aliases VALUES(?,?)',('_attachments/photo.png',old_id))
        plan=self.manager.migration_plan(str(self.root),fixtures.SOURCE,['_attachments/photo.png'])
        self.assertEqual(self.manager.migrate(str(self.root),plan['id'])['state'],'completed')
        self.assertFalse(original.exists())
        self.assertTrue(peer.scan(str(peer_root),fixtures.SOURCE)['ok'])
        peer_file=peer_root/'_attachments/photo.png';self.assertEqual(peer_file.read_bytes(),b'original')
        self.assertEqual(peer.stat(str(peer_root),asset_id=old_id)['storage_id'],'local')
        peer_file.unlink()  # Simulate Resilio delivering the owner's deletion.
        self.assertEqual(peer.stat(str(peer_root),asset_id=old_id)['storage_id'],fixtures.SOURCE)
        self.assertEqual(peer.stat(str(peer_root),'_attachments/photo.png')['storage_id'],fixtures.SOURCE)


class ModeSwitchingApiTests(unittest.TestCase):
    def setUp(self):
        with patch.object(RemoteAttachments,'_loop',return_value=None):
            api_fixtures.AttachmentInitializationUIContracts.setUp(self)
    tearDown=api_fixtures.AttachmentInitializationUIContracts.tearDown

    def test_local_initialization_still_targets_local_index_with_server_default(self):
        remote=self.app.state.remote_attachments
        remote.save(str(self.root),{'sources':[{'id':fixtures.SOURCE,'type':'webdav','base_url':'https://files.example.invalid/',
            'upload_directory':'Incoming','enabled':True}],'default_source':fixtures.SOURCE})
        with patch.object(remote,'start_scan',side_effect=AssertionError('server scan')):
            response=self.client.post('/api/attachments/initialize',json={'root':str(self.root)},headers=self.headers)
            self.assertEqual(response.status_code,200,response.text)
            self.app.state.attachment_index_jobs.thread.join(5)
        status=self.client.get('/api/attachments/status').json()
        self.assertEqual(status['storage_mode'],'server');self.assertTrue(status['local_index']['usable'])
        page=self.client.get('/api/attachments').json()
        self.assertEqual(page['items'][0]['source'],'local')

    def test_upload_destination_switches_without_moving_or_overwriting_old_files(self):
        root=str(self.root);remote=self.app.state.remote_attachments
        remote.transports[fixtures.SOURCE]=httpx.MockTransport(fixtures.FakeDAV())
        remote.save(root,{'sources':[{'id':fixtures.SOURCE,'type':'webdav','base_url':'https://files.example.invalid/',
            'username':'leafloom','upload_directory':'Incoming','enabled':True}],'default_source':'local'})
        remote.set_credentials(fixtures.SOURCE,'leafloom',fixtures.SECRET)
        def destination(value):
            settings=self.client.get('/api/attachments/storage',params={'root':root}).json()
            allowed={'storage_id','name','base_url','remote_root','upload_directory','metadata_directory','username','enabled','connection_hint'}
            response=self.client.put('/api/attachments/storage',headers=self.headers,json={'root':root,
                'revision':settings['revision'],'storages':[{k:v for k,v in item.items() if k in allowed} for item in settings['storages']],
                'default_storage_id':value})
            self.assertEqual(response.status_code,200,response.text)
        def upload(data):
            response=self.client.post('/api/upload',params={'root':root,'name':'same.png','central':'true','unique':'true'},
                headers=self.headers,content=data)
            self.assertEqual(response.status_code,200,response.text)
            return response.json()
        local=upload(b'local-first')
        destination(fixtures.SOURCE);queued=upload(b'server-second')
        destination('local');remote.process_pending()
        self.assertEqual(remote.job(root,queued['id'])['state'],'completed')
        another=upload(b'local-third');self.assertNotEqual(local['path'],another['path'])
        self.assertEqual((self.root/local['path']).read_bytes(),b'local-first')
        self.assertEqual((self.root/another['path']).read_bytes(),b'local-third')
        self.assertFalse((self.root/queued['path']).exists())
        for path,data in [(local['path'],b'local-first'),(queued['path'],b'server-second'),(another['path'],b'local-third')]:
            opened=self.client.get('/api/media',params={'root':root,'path':path})
            self.assertEqual(opened.status_code,200,opened.text);self.assertEqual(opened.content,data)
