"""Bounded scheduling and request/write counts on fictional offline servers."""
import sqlite3
import time
import unittest

import httpx
from unittest.mock import patch
from urllib.parse import unquote

from tests import test_attachment_auto_sync as auto
from tests import test_remote_attachments as remote
from tests import test_asset_library as metadata
from tests import test_remote_smb as smb
from tests import test_attachment_groups as groups
from vault_rag.attachment_scan_policy import SCAN_INTERVAL, STARTUP_GRACE, normalize_scan_roots
from vault_rag.attachment_catalog import AttachmentCatalog
from vault_rag.attachment_storage_routes import public_settings, save_settings
from vault_rag.local_state import Files
from vault_rag.remote_discovery import DirectoryCheckpoints
from vault_rag.remote_webdav import WebDAVSource


class ScheduleTests(unittest.TestCase):
    setUp = auto.AutoSyncTests.setUp
    finish = auto.AutoSyncTests.finish

    def test_launch_defers_and_recent_success_survives_restart(self):
        self.remote.auto_scans.clear()
        now = time.time()
        with patch.object(self.remote, 'start_scan') as start:
            self.remote.poll_scans()
            start.assert_not_called()
            due = self.remote.auto_scans[(str(self.root), remote.SOURCE)]['next_scan_at']
            self.assertGreaterEqual(due, now + STARTUP_GRACE)
        self.remote.auto_scans[(str(self.root), remote.SOURCE)]['next_scan_at'] = 0
        self.remote.poll_scans(); self.finish(); self.remote.poll_scans()
        last = public_settings(self.remote, str(self.root))['storages'][0]['connection']['last_success_at']
        self.remote.auto_scans.clear(); self.remote.scan_statuses.clear()
        with patch.object(self.remote, 'start_scan') as start:
            self.remote.poll_scans(); start.assert_not_called()
        due = self.remote.auto_scans[(str(self.root), remote.SOURCE)]['next_scan_at']
        self.assertEqual(due, last + SCAN_INTERVAL)

    def test_pause_persists_and_does_not_revoke_upload_authorization(self):
        before = self.remote._source_revision(self.remote._source(remote.SOURCE))
        self.remote.pause_scan(str(self.root), remote.SOURCE, True)
        self.remote.auto_scans.clear()
        with patch.object(self.remote, 'start_scan') as start:
            self.remote.poll_scans(); start.assert_not_called()
        self.assertTrue(self.remote._settings()['sources'][0]['scan_paused'])
        self.assertEqual(before, self.remote._source_revision(self.remote._source(remote.SOURCE)))
        job = self.remote.queue_upload(str(self.root), remote.SOURCE, 'pending.png', b'body')
        self.remote.process_pending()
        self.assertEqual(self.remote.job(str(self.root), job['id'])['state'], 'completed')
        with patch.object(self.remote, 'start_scan') as start:
            self.remote.pause_scan(str(self.root), remote.SOURCE, False)
            start.assert_called_once()

    def test_failed_scans_back_off_across_restart_and_reconnection(self):
        with patch.object(self.remote,'_scan',return_value={'ok':False,'state':'invalid_service'}):
            for attempt in range(1,9):
                self.remote.scan(str(self.root),remote.SOURCE,_incremental=True)
                with self.remote._db(str(self.root)) as db:retry=db.execute('SELECT * FROM scan_retries').fetchone()
                finished=self.remote.scan_statuses[(str(self.root),remote.SOURCE)]['scan_finished_at']
                self.assertEqual(retry['failures'],attempt)
                self.assertAlmostEqual(retry['next_retry_at']-finished,min(3600,60*2**min(attempt-1,6)))
        self.remote.auto_scans.clear()
        with patch.object(self.remote,'start_scan') as start:
            self.remote.poll_scans();start.assert_not_called()
            state=self.remote.auto_scans[(str(self.root),remote.SOURCE)]
            self.assertGreaterEqual(state['next_scan_at'],retry['next_retry_at'])
            state['connection_state']='unreachable'
            self.remote.poll_scans();start.assert_not_called()
        self.remote.scan(str(self.root),remote.SOURCE,_incremental=True)
        with self.remote._db(str(self.root)) as db:self.assertIsNone(db.execute('SELECT * FROM scan_retries').fetchone())



class DiscoveryTests(unittest.TestCase):
    setUp = remote.RemoteAttachmentTests.setUp
    tearDown = remote.RemoteAttachmentTests.tearDown
    manager_for_config = remote.RemoteAttachmentTests.manager_for_config

    def scan(self, **values):
        return self.manager.scan(str(self.root), remote.SOURCE, _incremental=True, **values)

    def test_scope_skips_unrelated_trees_preserves_records_and_inherits_ignore(self):
        self.dav.files.update({'Art/Packages/keep.png': b'keep', 'Code/app.js': b'code', 'Other/old.png': b'old'})
        self.assertTrue(self.scan()['ok'])
        old = self.manager.stat(str(self.root), '_attachments/_remote/' + remote.SOURCE + '/Other/old.png')
        settings = self.manager._settings(); settings['sources'][0]['scan_roots'] = ['Art/Packages']
        self.manager.save(str(self.root), settings)
        self.dav.files['Art/leafloom.ignore'] = b'# leafloom-ignore v1\n*.png\n'
        self.dav.calls.clear()
        self.assertTrue(self.scan(force_full=True)['ok'])
        listings = [unquote(httpx.URL(url).path).strip('/') for method, url in self.dav.calls if method == 'PROPFIND']
        self.assertEqual(listings, ['Art/Packages'])
        self.assertEqual(self.manager.stat(str(self.root), asset_id=old['asset_id'])['state'], 'ready')
        files = Files(self.config); catalog = AttachmentCatalog(files.attachments, self.manager)
        self.assertEqual(catalog.listing()['total'], 0)
        self.assertTrue(catalog.resolve('_attachments/_remote/' + remote.SOURCE + '/Other/old.png'))
        # An older settings client cannot accidentally remove the scope/pause preferences.
        current = public_settings(self.manager, str(self.root))
        sources = [{key: value for key, value in s.items() if key not in {'scan_roots','scan_paused','password_saved','connection'}} for s in current['storages']]
        saved = save_settings(self.manager, {'root': str(self.root), 'revision': current['revision'], 'storages': sources})
        self.assertEqual(saved['storages'][0]['scan_roots'], ['Art/Packages'])

    def test_cached_walk_does_not_rewrite_receipts_or_open_writer_per_directory(self):
        self.dav.files.update({f'a/{i}/image.png': b'image' for i in range(24)})
        self.assertTrue(self.scan()['ok'])
        with self.manager._db(str(self.root)) as db:
            receipts = db.execute('SELECT path,cycle,checked_at,entries FROM discovery_directories ORDER BY path').fetchall()
            before = [tuple(r) for r in receipts]
        self.dav.calls.clear()
        with patch.object(DirectoryCheckpoints, 'save', wraps=DirectoryCheckpoints.save) as save, patch.object(self.manager, '_db', wraps=self.manager._db) as writer:
            self.assertTrue(self.scan()['ok'])
            save.assert_not_called()
            self.assertLess(writer.call_count, 15)
        self.assertFalse(any(method == 'PROPFIND' for method, _ in self.dav.calls))
        with self.manager._db(str(self.root)) as db:
            after = [tuple(r) for r in db.execute('SELECT path,cycle,checked_at,entries FROM discovery_directories ORDER BY path')]
        self.assertEqual(before, after)

    def test_pause_interrupts_before_publishing_and_keeps_resume_receipts(self):
        self.dav.files['a/deep/file.png'] = b'file'
        original = WebDAVSource._propfind
        def pause(provider, path, **values):
            if path == 'a': self.manager.pause_scan(str(self.root), remote.SOURCE, True)
            return original(provider, path, **values)
        with patch.object(WebDAVSource, '_propfind', pause), self.assertRaises(InterruptedError):
            self.scan()
        with self.manager._db(str(self.root)) as db:
            self.assertIsNotNone(db.execute("SELECT 1 FROM discovery_directories WHERE path=''").fetchone())
        self.assertTrue(self.manager._settings()['sources'][0]['scan_paused'])

    def test_root_validation_and_schema_reuse_keep_future_version_guard(self):
        self.assertEqual(normalize_scan_roots(['Art', 'Art/Nested', 'Art', 'Other', '']), ['Art', 'Other'])
        for roots in [['../escape'], ['/absolute'], ['.hidden'], ['a\\b']]:
            with self.subTest(roots=roots), self.assertRaises(ValueError): normalize_scan_roots(roots)
        statements = []; connect = sqlite3.connect
        def traced(*args, **kwargs):
            db = connect(*args, **kwargs); db.set_trace_callback(statements.append); return db
        with patch('vault_rag.remote_attachments.sqlite3.connect', traced):
            with self.manager._db(str(self.root)): pass
        self.assertFalse(any('CREATE ' in s.upper() for s in statements))
        with self.manager._db(str(self.root)) as db: db.execute('PRAGMA user_version=99')
        with self.assertRaises(ValueError):
            with self.manager._db(str(self.root)): pass


class MetadataTests(unittest.TestCase):
    setUp = metadata.AssetLibraryTests.setUp
    tearDown = metadata.AssetLibraryTests.tearDown
    create_client = metadata.AssetLibraryTests.create_client
    scan = metadata.AssetLibraryTests.scan
    initialize = metadata.AssetLibraryTests.initialize

    def test_fresh_restart_avoids_network_but_pending_changes_still_publish(self):
        self.dav.files['Packages/Tool.unitypackage'] = b'package'
        self.scan(); self.initialize()
        self.library.last_pull.clear(); self.library.discovered.clear(); self.dav.calls.clear()
        with patch.object(self.library, '_provider', side_effect=AssertionError('unnecessary network')):
            self.assertEqual(self.library.sync(self.root, _background=True)['state'], 'ready')
        self.assertEqual(self.dav.calls, [])
        self.library.update(self.root, 'official', {'product_id': '123', 'official': {'title': 'Queued edit'}})
        self.dav.calls.clear()
        with patch.object(self.library, '_pull', wraps=self.library._pull) as pull:
            self.assertEqual(self.library.sync(self.root, _background=True)['pending'], 0)
            pull.assert_not_called()
        self.assertTrue(any(method == 'PUT' for method, _ in self.dav.calls))

    def test_unchanged_projection_does_not_delete_or_reinsert_entities(self):
        self.scan(); self.initialize()
        with self.library._db(self.root) as db:
            trace = []; db.set_trace_callback(trace.append); self.library._project(db)
        self.assertFalse(any(s.startswith('DELETE FROM entities') or s.startswith('INSERT INTO entities') for s in trace))

    def test_idle_metadata_backs_off_persistently_but_edits_publish_without_pull(self):
        self.scan();self.initialize()
        for _ in range(6):
            # Make the last pull due without waiting or touching a real server.
            with self.library._db(self.root) as db:
                checkpoint=self.library._get(db,'pull_checkpoint',{})
                self.library._set(db,'pull_checkpoint',{**checkpoint,'pulled_at':time.time()-checkpoint.get('interval',SCAN_INTERVAL)-1})
            self.library.last_pull.clear()
            self.assertEqual(self.library.sync(self.root,_background=True)['state'],'ready')
        with self.library._db(self.root) as db:self.assertEqual(self.library._get(db,'pull_checkpoint')['interval'],6*3600)
        self.library.last_pull.clear()
        with patch.object(self.library,'_provider',side_effect=AssertionError('idle network access')):
            self.assertEqual(self.library.sync(self.root,_background=True)['state'],'ready')
        self.library.update(self.root,'official',{'product_id':'123','official':{'title':'Fresh edit'}})
        self.dav.calls.clear()
        with patch.object(self.library,'_pull',side_effect=AssertionError('queued edit must not rescan')):
            self.assertEqual(self.library.sync(self.root,_background=True)['pending'],0)
        self.assertTrue(any(method=='PUT' for method,_ in self.dav.calls))
        with self.library._db(self.root) as db:self.assertEqual(self.library._get(db,'pull_checkpoint')['interval'],SCAN_INTERVAL)


    def test_failed_metadata_pull_does_not_retry_every_worker_tick(self):
        self.scan();self.initialize();self.dav.offline=True
        self.assertEqual(self.library.sync(self.root)['state'],'unreachable')
        self.dav.calls.clear()
        self.library.sync(self.root,_background=True)
        self.assertEqual(self.dav.calls,[])



class SMBDiscoveryTests(unittest.TestCase):
    setUp = smb.SMBTests.setUp

    def test_selected_subtree_uses_the_same_bounded_smb_traversal(self):
        (self.root / 'Other').mkdir()
        (self.root / 'Other/hidden.png').write_bytes(b'outside')
        items = self.source.scan(roots=['Incoming'])
        self.assertEqual([item['path'] for item in items], ['Incoming/test.bin'])
        self.assertEqual((self.root / 'Other/hidden.png').read_bytes(), b'outside')


class GroupScheduleTests(unittest.TestCase):
    setUp=groups.AttachmentGroupTests.setUp

    tearDown=groups.AttachmentGroupTests.tearDown

    create_client=groups.AttachmentGroupTests.create_client

    scan=groups.AttachmentGroupTests.scan

    initialize=groups.AttachmentGroupTests.initialize

    manager=groups.AttachmentGroupTests.manager

    def test_background_group_checks_are_throttled_across_restart_but_edits_send(self):
        self.scan();self.initialize();manager=self.manager();manager.sync(self.root)
        manager=self.manager();self.dav.calls.clear()
        manager.sync(self.root,_background=True);self.assertEqual(self.dav.calls,[])
        manager.update(self.root,'create',{'name':'New group'})
        self.dav.calls.clear()
        with patch.object(WebDAVSource,'scan',side_effect=AssertionError('queued edit must not scan event trees')):
            manager.sync(self.root,_background=True)
        self.assertTrue(any(method=='PUT' for method,_ in self.dav.calls))

    def test_idle_groups_back_off_and_manual_sync_still_reads(self):
        self.scan();self.initialize();manager=self.manager();manager.sync(self.root)
        for _ in range(6):
            with manager._db(self.root) as db:
                import json
                checkpoint=json.loads(db.execute("SELECT value FROM state WHERE key='pull_checkpoint'").fetchone()[0])
                checkpoint['at']=time.time()-checkpoint['interval']-1
                db.execute("UPDATE state SET value=? WHERE key='pull_checkpoint'",(json.dumps(checkpoint),))
            manager.sync(self.root,_background=True)
        with manager._db(self.root) as db:
            self.assertEqual(json.loads(db.execute("SELECT value FROM state WHERE key='pull_checkpoint'").fetchone()[0])['interval'],6*3600)
        self.dav.calls.clear();manager.sync(self.root)
        self.assertTrue(any(method=='PROPFIND' for method,_ in self.dav.calls))

    def test_failed_group_sync_waits_before_retrying(self):
        self.scan();self.initialize();manager=self.manager();manager.sync(self.root)
        self.dav.offline=True
        with self.assertRaises(Exception):manager.sync(self.root)
        self.dav.calls.clear();manager.sync(self.root,_background=True)
        self.assertEqual(self.dav.calls,[])
