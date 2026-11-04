"""Adaptive synchronization on fictional offline servers; no user data or network."""
import time
import unittest
from unittest.mock import patch
from tests import test_attachment_auto_sync as auto
from tests import test_remote_attachments as remote
from tests import test_asset_library as metadata
from tests import test_attachment_groups as groups
from vault_rag.remote_webdav import WebDAVSource


class ScheduleTests(unittest.TestCase):
    setUp = auto.AutoSyncTests.setUp

    finish = auto.AutoSyncTests.finish

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


class MetadataTests(unittest.TestCase):
    setUp = metadata.AssetLibraryTests.setUp

    tearDown = metadata.AssetLibraryTests.tearDown

    create_client = metadata.AssetLibraryTests.create_client

    scan = metadata.AssetLibraryTests.scan

    initialize = metadata.AssetLibraryTests.initialize

    def test_idle_metadata_backs_off_persistently_but_edits_publish_without_pull(self):
        self.scan();self.initialize()
        for _ in range(6):
            # Make the last pull due without waiting or touching a real server.
            with self.library._db(self.root) as db:
                checkpoint=self.library._get(db,'pull_checkpoint',{})
                self.library._set(db,'pull_checkpoint',{**checkpoint,'pulled_at':time.time()-checkpoint.get('interval',1800)-1})
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
        with self.library._db(self.root) as db:self.assertEqual(self.library._get(db,'pull_checkpoint')['interval'],1800)

    def test_failed_metadata_pull_does_not_retry_every_worker_tick(self):
        self.scan();self.initialize();self.dav.offline=True
        self.assertEqual(self.library.sync(self.root)['state'],'unreachable')
        self.dav.calls.clear()
        self.library.sync(self.root,_background=True)
        self.assertEqual(self.dav.calls,[])


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
