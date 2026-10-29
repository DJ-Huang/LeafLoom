"""Device isolation and server references with two independent synthetic clients."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import test_remote_attachments as fixtures
from vault_rag.attachment_catalog import AttachmentCatalog
from vault_rag.attachment_index_jobs import AttachmentIndexJobs
from vault_rag.attachment_server_references import publish, pull, sync
from vault_rag.local_state import ConflictError, Files, LocalConfig
from vault_rag.remote_attachments import RemoteAttachments
from types import SimpleNamespace


class DeviceStateTests(unittest.TestCase):
    def test_snapshot_is_private_consistent_and_does_not_follow_later_sync(self):
        with tempfile.TemporaryDirectory() as home:
            home = Path(home).resolve(); root = home / 'notes'; root.mkdir()
            legacy = root / '.vault-rag'; legacy.mkdir()
            old = legacy / 'attachments.sqlite'
            with sqlite3.connect(old) as db:
                db.execute('CREATE TABLE example(value TEXT)'); db.execute("INSERT INTO example VALUES('original')")
            first = LocalConfig(home / 'first'); first.save({'root': str(root)})
            files = Files(first); path = files.state_path('attachments.sqlite')
            self.assertTrue(path.is_relative_to(first.directory))
            with sqlite3.connect(old) as db: db.execute("UPDATE example SET value='synced elsewhere'")
            with sqlite3.connect(path) as db: self.assertEqual(db.execute('SELECT value FROM example').fetchone()[0], 'original')
            second = LocalConfig(home / 'second'); second.save({'root': str(root)})
            self.assertNotEqual(Files(second).state_path('attachments.sqlite'), path)
            self.assertTrue(old.exists())
            self.assertTrue(files.state_path('remote-attachments', 'release', 'claim').is_relative_to(root))
            self.assertTrue(files.state_path('attachment-migrations', 'job').is_relative_to(root))

    def test_legacy_symlink_is_not_imported(self):
        with tempfile.TemporaryDirectory() as home:
            home = Path(home).resolve(); root = home / 'notes'; root.mkdir()
            legacy = root / '.vault-rag'; legacy.mkdir(); outside = home / 'private'; outside.write_bytes(b'private')
            (legacy / 'attachments.sqlite').symlink_to(outside)
            config = LocalConfig(home / 'state'); config.save({'root': str(root)})
            with self.assertRaises(ValueError): Files(config).state_path('attachments.sqlite')
            self.assertEqual(outside.read_bytes(), b'private')

    def test_foreign_root_reuses_server_profile_without_adopting_jobs(self):
        with tempfile.TemporaryDirectory() as home:
            home=Path(home).resolve();root=home/'synced-notes';root.mkdir()
            legacy=root/'.vault-rag/remote-attachments';legacy.mkdir(parents=True)
            (legacy/'settings.json').write_text(json.dumps({'root':'C:\\Users\\fixture\\notes','revision':'old',
                'sources':[],'default_source':'local'}))
            with sqlite3.connect(legacy/'manifest.sqlite') as db:
                db.execute('CREATE TABLE jobs(payload TEXT)');db.execute("INSERT INTO jobs VALUES('foreign job')")
            config=LocalConfig(home/'state');config.save({'root':str(root)})
            files=Files(config);settings=files.state_path('remote-attachments','settings.json')
            self.assertEqual(json.loads(settings.read_text())['root'],str(root))
            self.assertFalse(files.state_path('remote-attachments','manifest.sqlite').exists())
            self.assertTrue((legacy/'manifest.sqlite').exists())

    def test_upgrade_preserves_unsent_bytes_and_downloads_but_discards_only_cache(self):
        with tempfile.TemporaryDirectory() as home:
            home=Path(home).resolve();root=home/'notes';root.mkdir();legacy=root/'.vault-rag'
            remote=legacy/'remote-attachments';remote.mkdir(parents=True)
            (remote/'settings.json').write_text(json.dumps({'root':str(root)}))
            for name in ('outbox','cache','release'):
                (remote/name).mkdir();(remote/name/'content').write_bytes(name.encode())
            with sqlite3.connect(remote/'manifest.sqlite') as db:
                db.execute('CREATE TABLE cache(file TEXT)');db.execute("INSERT INTO cache VALUES('content')")
                db.execute('CREATE TABLE jobs(payload TEXT)');db.execute("INSERT INTO jobs VALUES('unsent')")
            downloads=legacy/'asset-downloads';downloads.mkdir();(downloads/'verified.bin').write_bytes(b'verified')
            config=LocalConfig(home/'state');config.save({'root':str(root)})
            files=Files(config)
            self.assertEqual(files.state_path('remote-attachments','outbox','content').read_bytes(),b'outbox')
            self.assertFalse(files.state_path('remote-attachments','cache').exists())
            self.assertEqual(files.state_path('remote-attachments','release','content').read_bytes(),b'release')
            self.assertEqual(files.state_path('asset-downloads','verified.bin').read_bytes(),b'verified')
            with sqlite3.connect(files.state_path('remote-attachments','manifest.sqlite')) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM cache').fetchone()[0],0)
                self.assertEqual(db.execute('SELECT payload FROM jobs').fetchone()[0],'unsent')
            self.assertEqual((remote/'cache/content').read_bytes(),b'cache')


class ServerReferenceTests(unittest.TestCase):
    setUp = fixtures.RemoteAttachmentTests.setUp
    tearDown = fixtures.RemoteAttachmentTests.tearDown
    manager_for_config = fixtures.RemoteAttachmentTests.manager_for_config

    def peer(self):
        root = self.home / 'other-notes'; root.mkdir()
        config = LocalConfig(self.home / 'other-state'); config.save({'root': str(root)})
        with patch.object(RemoteAttachments, '_loop', return_value=None):
            peer = RemoteAttachments(config)
        self.managers.append(peer)
        settings = self.manager._settings(str(self.root)); source = dict(settings['sources'][0]); source['id'] = 'b' * 32
        peer.save(str(root), {'sources': [source], 'default_source': source['id']})
        peer.transports[source['id']] = self.transport
        peer.set_credentials(source['id'], 'leafloom', fixtures.SECRET, revision='peer')
        return peer, str(root), source['id']

    def seed(self, alias='old/image.png', path='Incoming/object.png'):
        self.dav.files[path] = b'image'; self.manager.scan(str(self.root), fixtures.SOURCE)
        with self.manager.lock, self.manager._db(str(self.root)) as db:
            key = db.execute('SELECT id FROM assets WHERE path=?', (path,)).fetchone()[0]
            db.execute('INSERT INTO aliases VALUES(?,?)', (alias, key))
        return key

    def test_peer_restores_legacy_canonical_paths_and_ids_without_originals(self):
        key = self.seed(); provider = self.manager._provider(fixtures.SOURCE, str(self.root))
        publish(self.manager, str(self.root), fixtures.SOURCE, key, provider)
        peer, root, source = self.peer()
        self.assertTrue(peer.scan(root, source)['ok'])
        self.assertEqual(peer.stat(root, 'old/image.png')['remote_path'], 'Incoming/object.png')
        self.assertEqual(peer.stat(root, '_attachments/_remote/' + fixtures.SOURCE + '/Incoming/object.png')['remote_path'], 'Incoming/object.png')
        self.assertEqual(peer.stat(root, asset_id=key)['storage_id'], source)
        self.assertFalse((Path(root) / 'old/image.png').exists())
        self.assertFalse(any(peer._state('cache').glob('*')))

    def test_ambiguous_server_alias_does_not_replace_previous_mapping(self):
        first = self.seed(); second = self.seed(alias='other/image.png', path='Incoming/second.png')
        provider = self.manager._provider(fixtures.SOURCE, str(self.root))
        publish(self.manager, str(self.root), fixtures.SOURCE, first, provider)
        with self.manager.lock, self.manager._db(str(self.root)) as db:
            db.execute('DELETE FROM aliases WHERE path=?', ('old/image.png',))
            db.execute('INSERT INTO aliases VALUES(?,?)', ('old/image.png', second))
        publish(self.manager, str(self.root), fixtures.SOURCE, second, provider)
        peer, root, source = self.peer()
        with self.assertRaises(ConflictError): peer.scan(root, source)
        with peer.lock, peer._db(root) as db:
            self.assertIsNone(db.execute('SELECT 1 FROM aliases WHERE path=?', ('old/image.png',)).fetchone())

    def test_reference_write_failure_retains_upload_queue_and_local_migration_source(self):
        source = self.root / 'original.png'; source.write_bytes(b'original')
        plan = self.manager.migration_plan(str(self.root), fixtures.SOURCE, ['original.png'])
        with patch('vault_rag.attachment_server_references.publish', side_effect=RuntimeError('fixture')):
            result = self.manager.migrate(str(self.root), plan['id'])
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(source.read_bytes(), b'original')
        queued = self.manager.queue_upload(str(self.root), fixtures.SOURCE, 'queued.png', source)
        with patch('vault_rag.attachment_server_references.publish', side_effect=RuntimeError('fixture')):
            self.manager.process_pending()
        self.assertNotEqual(self.manager.job(str(self.root), queued['id'])['state'], 'completed')
        self.assertTrue(self.manager._state('outbox', queued['id'] + '.blob').is_file())

    def test_server_catalog_is_usable_without_local_scan_or_organization(self):
        self.seed(); files = Files(self.config); catalog = AttachmentCatalog(files.attachments, self.manager)
        runtime = SimpleNamespace(files=files, config=self.config, remote_attachments=self.manager)
        with patch.object(Files, 'walk', side_effect=AssertionError('local discovery')):
            self.assertTrue(AttachmentIndexJobs(runtime).status()['usable'])
            self.assertEqual(catalog.listing()['total'], 1)
            self.assertEqual(catalog.resolve('old/image.png'), ['old/image.png'])
        self.assertFalse(files.state_path('attachment-index-job.json').exists())

    def test_explicit_backfill_is_idempotent_and_missing_full_paths_do_not_guess(self):
        self.seed()
        self.assertEqual(sync(self.manager, str(self.root), fixtures.SOURCE)['published'], 1)
        before = set(self.dav.files)
        sync(self.manager, str(self.root), fixtures.SOURCE)
        self.assertEqual(set(self.dav.files), before)
        with self.assertRaises(FileNotFoundError): self.manager.stat(str(self.root), 'wrong/object.png')

    def test_verified_reference_records_are_reused_without_reading_originals(self):
        key=self.seed();provider=self.manager._provider(fixtures.SOURCE,str(self.root))
        publish(self.manager,str(self.root),fixtures.SOURCE,key,provider)
        pull(self.manager,str(self.root),fixtures.SOURCE,provider)
        self.dav.calls.clear()
        pull(self.manager,str(self.root),fixtures.SOURCE,provider)
        self.assertFalse(any(method=='GET' for method,_ in self.dav.calls))
