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


class SMBDiscoveryTests(unittest.TestCase):
    setUp = smb.SMBTests.setUp

    def test_selected_subtree_uses_the_same_bounded_smb_traversal(self):
        (self.root / 'Other').mkdir()
        (self.root / 'Other/hidden.png').write_bytes(b'outside')
        items = self.source.scan(roots=['Incoming'])
        self.assertEqual([item['path'] for item in items], ['Incoming/test.bin'])
        self.assertEqual((self.root / 'Other/hidden.png').read_bytes(), b'outside')
