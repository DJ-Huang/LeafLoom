import json
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import patch
import test_attachment_index
from vault_rag.attachment_index_jobs import AttachmentIndexJobs


class IndexJobTests(test_attachment_index.unittest.TestCase):
    setUp = test_attachment_index.AttachmentIndexTests.setUp
    tearDown = test_attachment_index.AttachmentIndexTests.tearDown
    put = test_attachment_index.AttachmentIndexTests.put
    def manager(self):
        return AttachmentIndexJobs(SimpleNamespace(files=self.files, config=self.config))

    def test_status_does_not_create_or_walk(self):
        jobs=self.manager()
        with patch.object(type(self.files),'walk',side_effect=AssertionError('scan')):
            self.assertEqual(jobs.status()['state'],'uninitialized')
        self.assertFalse(self.files.state_path('attachments.sqlite').exists())

    def test_background_initialize_and_restart(self):
        self.put('media/a.png')
        jobs=self.manager();jobs.start(str(self.root));jobs.thread.join(5)
        status=jobs.status();self.assertEqual(status['state'],'ready');self.assertEqual(status['files'],1)
        self.assertTrue(self.manager().status()['usable'])

    def test_cancel_preserves_previous_generation(self):
        self.put('a.png');self.index.refresh();self.put('b.png')
        cancel=threading.Event();cancel.set()
        with self.assertRaises(InterruptedError):self.index.refresh(cancel=cancel)
        self.assertEqual(self.index.listing()['total'],1)

    def test_interrupted_job_reported_after_restart(self):
        path=self.files.state_path('attachment-index-job.json');path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(dict(id='old',root=str(self.root),state='building',done=10)))
        self.assertEqual(self.manager().status()['state'],'interrupted')

    def test_legacy_schema_backed_up_before_upgrade(self):
        self.put('a.png');self.index.refresh();path=self.files.state_path('attachments.sqlite')
        with sqlite3.connect(path) as db:db.execute('PRAGMA user_version=0')
        self.assertEqual(self.manager().status()['state'],'needs_upgrade')
        self.index.refresh()
        backups=list(path.parent.glob('attachments-before-v1-*.sqlite'));self.assertEqual(len(backups),1)
        with sqlite3.connect(backups[0]) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM assets').fetchone()[0],1)

    def test_future_schema_preserved(self):
        self.index.refresh();path=self.files.state_path('attachments.sqlite')
        with sqlite3.connect(path) as db:db.execute('PRAGMA user_version=99')
        before=path.read_bytes();jobs=self.manager()
        self.assertEqual(jobs.status()['state'],'unsupported')
        with self.assertRaises(ValueError):jobs.start(str(self.root))
        self.assertEqual(before,path.read_bytes())

    def test_unknown_legacy_preserved(self):
        path=self.files.state_path('attachments.sqlite');path.parent.mkdir(exist_ok=True)
        with sqlite3.connect(path) as db:db.execute('CREATE TABLE unknown(secret TEXT)')
        before=path.read_bytes()
        with self.assertRaises(ValueError):self.index.refresh()
        self.assertEqual(before,path.read_bytes())

    def test_upgrade_ddl_failure_keeps_original_schema(self):
        self.put('a.png');self.index.refresh();path=self.files.state_path('attachments.sqlite')
        with sqlite3.connect(path) as db:db.execute('PRAGMA user_version=0')
        connect=sqlite3.connect
        class FailingConnection(sqlite3.Connection):
            def execute(self, sql, *args):
                if sql.startswith('CREATE INDEX'):raise sqlite3.OperationalError('injected upgrade failure')
                return super().execute(sql,*args)
        def failing(*args,**kwargs):
            if str(args[0])==str(path):kwargs['factory']=FailingConnection
            return connect(*args,**kwargs)
        with patch('vault_rag.attachment_index.sqlite3.connect',side_effect=failing):
            with self.assertRaises(sqlite3.OperationalError):self.index.refresh()
        with connect(path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM assets').fetchone()[0],1)
        self.assertEqual(len(list(path.parent.glob('attachments-before-v1-*.sqlite'))),1)

    def test_background_cancel_is_durable_and_non_destructive(self):
        self.put('a.png');self.index.refresh();self.put('b.png')
        entered=threading.Event();release=threading.Event();walk=type(self.files).walk
        def paused(files,*args,**kwargs):
            entered.set();release.wait(3);yield from walk(files,*args,**kwargs)
        jobs=self.manager()
        with patch.object(type(self.files),'walk',paused):
            jobs.start(str(self.root));self.assertTrue(entered.wait(2))
            self.assertEqual(jobs.status()['state'],'building')
            jobs.cancel_job(str(self.root));release.set();jobs.thread.join(5)
        self.assertEqual(jobs.status()['state'],'cancelled')
        self.assertTrue(jobs.status()['usable'])
        self.assertEqual(self.index.listing()['total'],1)
        self.assertEqual(self.manager().status()['state'],'cancelled')

    def test_unified_rebuild_supersedes_old_maintenance_failure(self):
        import time
        jobs=self.manager();files=self.files
        jobs._save(files,dict(id='old',root=str(self.root),state='failed',error='old failure',started_at=time.time()-10))
        self.index.refresh()
        status=jobs.status()
        self.assertEqual(status['state'],'ready')
        self.assertNotIn('error',status)
