"""Offline directory-cache contracts: no user NAS, credentials or original reads."""
import json
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import unquote

import httpx

from tests import test_remote_attachments as fixtures
SOURCE,SECRET=fixtures.SOURCE,fixtures.SECRET
from vault_rag.local_state import ConflictError
from vault_rag.remote_webdav import RemoteStorageError, WebDAVSource
from vault_rag.attachment_scan_policy import SCAN_INTERVAL, MAX_DIRECTORY_INTERVAL


class IncrementalDiscoveryTests(unittest.TestCase):
    setUp=fixtures.RemoteAttachmentTests.setUp
    tearDown=fixtures.RemoteAttachmentTests.tearDown
    manager_for_config=fixtures.RemoteAttachmentTests.manager_for_config

    def run_scan(self,manager=None,**kwargs):
        manager=manager or self.manager
        # Simulate the health probe succeeding before a reconnect retry.
        manager._reset_connection(str(self.root),SOURCE)
        return manager.scan(str(self.root),SOURCE,_incremental=True,**kwargs)

    def listings(self):
        return [unquote(httpx.URL(url).path).strip('/') for method,url in self.dav.calls if method=='PROPFIND']

    def row(self,path):
        with self.manager._db(str(self.root)) as db:
            return dict(db.execute('SELECT * FROM assets WHERE source_id=? AND path=?',(SOURCE,path)).fetchone())

    def test_cached_pass_preserves_receipt_age_and_adaptive_interval(self):
        self.dav.files['Archive/file.bin']=b'file'
        self.assertTrue(self.run_scan()['ok'])
        def receipts():
            with self.manager._db(str(self.root)) as db:
                return ([tuple(row) for row in db.execute('SELECT * FROM discovery_directories ORDER BY path')],
                        [tuple(row) for row in db.execute('SELECT * FROM discovery_intervals ORDER BY path')])
        before=receipts();self.dav.calls.clear()
        self.assertTrue(self.run_scan()['ok'])
        self.assertEqual(self.listings(),[])
        self.assertEqual(receipts(),before)

    def test_interrupted_scan_resumes_completed_directories_after_restart(self):
        self.dav.files.update({'a/first.bin':b'first','a/b/last.bin':b'last'})
        original=WebDAVSource._propfind
        def interrupted(provider,path,*args,**kwargs):
            if path=='a/b':raise RemoteStorageError('connection_unavailable','unreachable')
            return original(provider,path,*args,**kwargs)
        with patch.object(WebDAVSource,'_propfind',interrupted):self.assertFalse(self.run_scan()['ok'])
        self.assertEqual(self.row('a/first.bin')['state'],'ready')
        self.dav.calls.clear()
        manager=self.manager_for_config();manager.set_credentials(SOURCE,'leafloom',SECRET,revision='stable-revision')
        self.assertTrue(self.run_scan(manager)['ok'])
        self.assertEqual(self.listings(),['a/b'])
        state=manager.connections[SOURCE]
        self.assertEqual((state['scan_mode'],state['cached_directories'],state['directories']),('resume',2,3))
        with manager._db(str(self.root)) as db:self.assertEqual(db.execute('SELECT complete FROM discovery_runs').fetchone()[0],1)

    def test_cache_reuses_without_network_or_catalog_churn_and_force_checks_now(self):
        self.dav.files['a/file.bin']=b'first'
        self.assertTrue(self.run_scan()['ok'])
        with self.manager._db(str(self.root)) as db:generation=db.execute('SELECT generation FROM catalog_state').fetchone()[0]
        self.dav.calls.clear();self.dav.files['a/new.bin']=b'new'
        self.assertTrue(self.run_scan()['ok']);self.assertEqual(self.listings(),[])
        with self.manager._db(str(self.root)) as db:self.assertEqual(db.execute('SELECT generation FROM catalog_state').fetchone()[0],generation)
        self.assertEqual(self.manager.connections[SOURCE]['scan_mode'],'incremental')
        self.assertTrue(self.run_scan(force_full=True)['ok'])
        self.assertEqual(set(self.listings()),{'','a'});self.assertEqual(self.row('a/new.bin')['state'],'ready')
        self.assertFalse(any(method=='GET' and url.endswith('.bin') for method,url in self.dav.calls))

    def test_expired_deep_directory_checked_even_when_parent_cache_is_fresh(self):
        self.dav.files['a/b/file.bin']=b'first';self.assertTrue(self.run_scan()['ok'])
        with self.manager._db(str(self.root)) as db:db.execute("UPDATE discovery_directories SET checked_at=0 WHERE path='a/b'")
        self.dav.files['a/b/new.bin']=b'new';self.dav.calls.clear()
        self.assertTrue(self.run_scan()['ok']);self.assertEqual(self.listings(),['a/b'])
        self.assertEqual(self.row('a/b/new.bin')['state'],'ready')

    def test_stable_archive_backs_off_but_upload_tree_remains_frequent(self):
        self.dav.files.update({'Archive/deep/file.bin':b'first','Incoming/file.bin':b'upload'})
        now=time.time()
        with patch('vault_rag.remote_discovery.time.time',return_value=now):self.assertTrue(self.run_scan()['ok'])
        self.dav.calls.clear()
        with patch('vault_rag.remote_discovery.time.time',return_value=now+SCAN_INTERVAL+1):self.assertTrue(self.run_scan()['ok'])
        self.assertEqual(set(self.listings()),{'','Archive','Archive/deep','Incoming'})
        self.dav.calls.clear()
        manager=self.manager_for_config();manager.set_credentials(SOURCE,'leafloom',SECRET,revision='stable-revision')
        with patch('vault_rag.remote_discovery.time.time',return_value=now+2*SCAN_INTERVAL+2):self.assertTrue(self.run_scan(manager)['ok'])
        self.assertEqual(set(self.listings()),{'','Incoming'})
        # Expired descendants must still be checked under unchanged/fresh parents.
        with manager._db(str(self.root)) as db:db.execute("UPDATE discovery_directories SET checked_at=0 WHERE path='Archive/deep'")
        self.dav.files['Archive/deep/new.bin']=b'new';self.dav.calls.clear()
        self.assertTrue(self.run_scan(manager)['ok']);self.assertEqual(self.listings(),['Archive/deep'])

    def test_archive_interval_is_bounded_and_changes_reset_it(self):
        self.dav.files['a/file.bin']=b'first';self.assertTrue(self.run_scan()['ok'])
        for _ in range(12):self.assertTrue(self.run_scan(force_full=True)['ok'])
        with self.manager._db(str(self.root)) as db:
            self.assertEqual(db.execute("SELECT check_interval FROM discovery_intervals WHERE path='a'").fetchone()[0],MAX_DIRECTORY_INTERVAL)
        self.dav.files['a/new.bin']=b'new';self.assertTrue(self.run_scan(force_full=True)['ok'])
        with self.manager._db(str(self.root)) as db:
            self.assertEqual(db.execute("SELECT check_interval FROM discovery_intervals WHERE path='a'").fetchone()[0],SCAN_INTERVAL)

    def test_upload_only_dirties_ancestors_and_keeps_catalog_current(self):
        self.dav.files.update({'Archive/keep.bin':b'keep','Incoming/old.bin':b'old'})
        self.assertTrue(self.run_scan()['ok'])
        job=self.manager.queue_upload(str(self.root),SOURCE,'new.bin',b'new')
        self.manager.process_pending()
        self.assertEqual(self.manager.job(str(self.root),job['id'])['state'],'completed')
        self.dav.calls.clear();self.assertTrue(self.run_scan()['ok'])
        self.assertTrue({'','Incoming'}<=set(self.listings()))
        self.assertFalse(any(path.startswith('Archive') for path in self.listings()))
        with self.manager._db(str(self.root)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM discovery_changes').fetchone()[0],0)

    def test_upload_racing_a_listing_keeps_dirty_marker(self):
        self.dav.files['Incoming/old.bin']=b'old';self.assertTrue(self.run_scan()['ok'])
        original=WebDAVSource._propfind
        def racing(provider,path,*args,**kwargs):
            entries=original(provider,path,*args,**kwargs)
            if path=='Incoming':
                with self.manager._db(str(self.root)) as db:
                    db.execute('INSERT OR REPLACE INTO discovery_changes VALUES(?,?,?)',(SOURCE,'Incoming',time.time()+1))
            return entries
        with patch.object(WebDAVSource,'_propfind',racing):self.assertTrue(self.run_scan(force_full=True)['ok'])
        self.dav.calls.clear();self.assertTrue(self.run_scan()['ok']);self.assertEqual(self.listings(),['Incoming'])

    def test_missing_cached_child_refreshes_parent_on_resume(self):
        self.dav.files['a/b/gone.bin']=b'gone';self.assertTrue(self.run_scan()['ok'])
        del self.dav.files['a/b/gone.bin']
        with self.manager._db(str(self.root)) as db:db.execute("UPDATE discovery_directories SET checked_at=0 WHERE path='a/b'")
        original=WebDAVSource._propfind
        def gone(provider,path,*args,**kwargs):
            if path=='a/b':raise RemoteStorageError('remote_not_found')
            return original(provider,path,*args,**kwargs)
        with patch.object(WebDAVSource,'_propfind',gone):self.assertFalse(self.run_scan()['ok'])
        self.dav.calls.clear();self.assertTrue(self.run_scan()['ok'])
        self.assertIn('a',self.listings());self.assertNotIn('a/b',self.listings())
        self.assertEqual(self.row('a/b/gone.bin')['state'],'missing')

    def test_legacy_directory_schema_remains_writable_without_discarding_receipts(self):
        import sqlite3
        from vault_rag.remote_discovery import DirectoryCheckpoints
        path=self.home/'legacy.sqlite'
        with sqlite3.connect(path) as db:
            db.executescript('''CREATE TABLE discovery_runs(source_id TEXT PRIMARY KEY,context TEXT,cycle TEXT,mode TEXT,complete INTEGER);
                CREATE TABLE discovery_directories(source_id TEXT,path TEXT,context TEXT,cycle TEXT,checked_at REAL,entries TEXT,rule BLOB,PRIMARY KEY(source_id,path));''')
            db.execute('INSERT INTO discovery_runs VALUES(?,?,?,?,?)',(SOURCE,'context','cycle','full',0))
            db.execute('INSERT INTO discovery_directories VALUES(?,?,?,?,?,?,?)',(SOURCE,'','context','cycle',0,json.dumps([{'path':'','is_dir':True,'size':0}]),None))
        cache=DirectoryCheckpoints(path,SOURCE,'context',lambda:None)
        try:
            self.assertTrue(cache.resumed);self.assertIsNotNone(cache.load(''))
            self.assertEqual(cache.receipt('')['check_interval'],SCAN_INTERVAL)
            # An older release can still write the original seven-column row.
            cache.db.execute('INSERT OR REPLACE INTO discovery_directories VALUES(?,?,?,?,?,?,?)',
                (SOURCE,'','context','cycle',1,json.dumps([{'path':'','is_dir':True,'size':0}]),None))
            cache.db.commit();self.assertIsNotNone(cache.load(''))
        finally:cache.close()

    def test_cache_never_rolls_back_newer_head_metadata_or_revives_missing(self):
        self.dav.files['a/file.bin']=b'first';self.assertTrue(self.run_scan()['ok'])
        with self.manager._db(str(self.root)) as db:
            db.execute("UPDATE assets SET size=100,etag='new-head' WHERE path='a/file.bin'")
        self.assertTrue(self.run_scan()['ok']);self.assertEqual(self.row('a/file.bin')['size'],100)
        self.assertEqual(self.row('a/file.bin')['etag'],'new-head')
        with self.manager._db(str(self.root)) as db:db.execute("UPDATE assets SET state='missing' WHERE path='a/file.bin'")
        self.assertTrue(self.run_scan()['ok']);self.assertEqual(self.row('a/file.bin')['state'],'missing')

    def test_changed_credentials_and_address_invalidate_previous_receipts(self):
        self.dav.files['a/file.bin']=b'first';self.assertTrue(self.run_scan()['ok']);self.dav.calls.clear()
        self.manager.set_credentials(SOURCE,'leafloom',SECRET,revision='replaced')
        self.assertTrue(self.run_scan()['ok']);self.assertEqual(set(self.listings()),{'','a'})
        values=self.manager._settings();values['sources'][0]['base_url']='https://fixture.invalid/'
        self.manager.save(str(self.root),values);self.dav.calls.clear()
        self.assertTrue(self.run_scan()['ok']);self.assertEqual(set(self.listings()),{'','a'})
        self.assertEqual(self.manager.connections[SOURCE]['cached_directories'],0)

    def test_change_during_listing_cannot_commit_old_configuration(self):
        self.dav.files['a/file.bin']=b'first';original=WebDAVSource._propfind
        def changed(provider,path,*args,**kwargs):
            entries=original(provider,path,*args,**kwargs)
            if path=='a':self.manager.set_credentials(SOURCE,'leafloom',SECRET,revision='replaced')
            return entries
        with patch.object(WebDAVSource,'_propfind',changed):
            with self.assertRaises(PermissionError):self.run_scan()
        with self.manager._db(str(self.root)) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM assets WHERE path='a/file.bin'").fetchone())
            self.assertIsNone(db.execute("SELECT 1 FROM discovery_directories WHERE path='a'").fetchone())
        self.dav.calls.clear();self.assertTrue(self.run_scan()['ok']);self.assertIn('',self.listings())

    def test_deleted_directory_removes_subtree_cache_only_after_verified_pass(self):
        self.dav.files.update({'a/kept.bin':b'keep','a/b/gone.bin':b'gone'})
        self.assertTrue(self.run_scan()['ok']);del self.dav.files['a/b/gone.bin']
        # Fail reconciliation after the new listing was saved: never mark missing.
        with patch.object(WebDAVSource,'verify_ignore',side_effect=RemoteStorageError('connection_unavailable','unreachable')):
            self.assertFalse(self.run_scan(force_full=True)['ok'])
        self.assertEqual(self.row('a/b/gone.bin')['state'],'ready')
        self.dav.calls.clear();result=self.run_scan();self.assertTrue(result['ok']);self.assertEqual(result['missing'],1)
        self.assertEqual(self.row('a/b/gone.bin')['state'],'missing');self.assertEqual(self.listings(),[])
        with self.manager._db(str(self.root)) as db:self.assertIsNone(db.execute("SELECT 1 FROM discovery_directories WHERE path='a/b'").fetchone())

    def test_ignore_rule_change_invalidates_subtree_and_recovers_on_resume(self):
        self.dav.files.update({'a/leafloom.ignore':b'# leafloom-ignore v1\n*.bin\n','a/file.bin':b'file'})
        self.assertTrue(self.run_scan()['ok']);self.assertEqual(self.row('a/file.bin')['state'],'excluded')
        self.dav.files['a/leafloom.ignore']=b'# leafloom-ignore v1\n'
        self.assertEqual(self.run_scan()['code'],'ignore_rules_changed')
        self.dav.calls.clear();self.assertTrue(self.run_scan()['ok'])
        self.assertEqual(self.listings(),['a']);self.assertEqual(self.row('a/file.bin')['state'],'ready')
        del self.dav.files['a/leafloom.ignore']
        self.assertEqual(self.run_scan()['code'],'ignore_rules_changed')
        self.assertTrue(self.run_scan()['ok'])

    def test_directory_workers_are_bounded_and_isolate_sessions(self):
        self.dav.files.update({f'{letter}/file.bin':b'file' for letter in 'abcd'})
        lock=threading.Lock();active=0;maximum=0;peers={};original=WebDAVSource._propfind
        def tracked(provider,path,*args,**kwargs):
            nonlocal active,maximum
            with lock:active+=1;maximum=max(maximum,active);peers.setdefault(threading.get_ident(),set()).add(id(provider))
            try:time.sleep(.02);return original(provider,path,*args,**kwargs)
            finally:
                with lock:active-=1
        with patch.object(WebDAVSource,'_propfind',tracked):self.assertTrue(self.run_scan()['ok'])
        self.assertEqual(maximum,2);self.assertEqual(len(peers),2);self.assertTrue(all(len(values)==1 for values in peers.values()))
        self.assertEqual(len(set.union(*peers.values())),2)

    def test_untrusted_cached_path_is_rejected_before_reuse(self):
        self.dav.files['a/file.bin']=b'file';self.assertTrue(self.run_scan()['ok'])
        with self.manager._db(str(self.root)) as db:
            value=json.loads(db.execute("SELECT entries FROM discovery_directories WHERE path='a'").fetchone()[0])
            value.append({'path':'../outside.bin','is_dir':False,'size':0})
            db.execute("UPDATE discovery_directories SET entries=? WHERE path='a'",(json.dumps(value),))
        self.dav.calls.clear();self.assertTrue(self.run_scan()['ok']);self.assertEqual(self.listings(),['a'])

    def test_unchanged_fresh_listing_does_not_invalidate_catalog_snapshot(self):
        self.dav.files['a/file.bin']=b'first';self.assertTrue(self.run_scan()['ok'])
        before=self.row('a/file.bin')
        self.assertTrue(self.run_scan(force_full=True)['ok']);after=self.row('a/file.bin')
        self.assertEqual((before['updated'],before['reconcile_revision']),(after['updated'],after['reconcile_revision']))

    def test_successful_sibling_is_checkpointed_when_other_worker_fails(self):
        self.dav.files.update({'a/done.bin':b'done','b/fail.bin':b'fail'})
        original=WebDAVSource._propfind;failed=threading.Event()
        def interrupted(provider,path,*args,**kwargs):
            if path=='b':
                failed.set();raise RemoteStorageError('connection_unavailable','unreachable')
            if path=='a':failed.wait(2);time.sleep(.03)
            return original(provider,path,*args,**kwargs)
        with patch.object(WebDAVSource,'_propfind',interrupted):self.assertFalse(self.run_scan()['ok'])
        self.assertEqual(self.row('a/done.bin')['state'],'ready')
        self.dav.calls.clear();self.assertTrue(self.run_scan()['ok']);self.assertEqual(self.listings(),['b'])
