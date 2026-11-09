"""Two independent devices exchange only immutable files, never their SQLite state."""
import datetime as dt
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vault_rag.calendar import Calendar, UTC
from vault_rag.calendar_sync import DIRECTORY
from vault_rag.databases import Databases
from vault_rag.knowledge import Runtime
from vault_rag.local_state import LocalConfig, ConflictError


class CalendarSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name).resolve();self.serial=0
        self.a=self.device('a');self.b=self.device('b')

    def device(self, name):
        root=self.home/name/'vault';root.mkdir(parents=True)
        config=LocalConfig(self.home/name/'state');config.save({'root':str(root),'include_roots':[]})
        runtime=Runtime(config);self.addCleanup(runtime.stop)
        database=Databases(config,runtime)
        return Calendar(config,runtime,database.notes,database)

    def command(self, cal, type, **kw):
        self.serial+=1
        return cal.command({'workspace_revision':cal.notes.workspace_revision,'operation_id':'operation-'+str(self.serial),'command':{'type':type,**kw}})

    def add(self, cal, **kw):
        return self.command(cal,'create',item={'title':'Task','date':'2026-11-06',**kw})['id']

    def rows(self, cal):return cal.query('2026-11-01','2026-11-30')['results']

    def exchange(self, source, target):
        folder=source.config.root/DIRECTORY/'changes'
        destination=target.config.root/DIRECTORY/'changes';destination.mkdir(parents=True,exist_ok=True)
        if folder.exists():
            for path in folder.glob('*.json'):
                if not (destination/path.name).exists():shutil.copy2(path,destination/path.name)

    def edit(self, cal, row, **kw):
        return self.command(cal,'edit',id=row['id'],revision=row['revision'],occurrence=row['occurrence'],item={**row,**kw})

    def test_independent_offline_edits_converge_and_local_preferences_stay_local(self):
        first=self.add(self.a,title='One');second=self.add(self.a,title='Two');self.exchange(self.a,self.b)
        a=self.rows(self.a);b=self.rows(self.b)
        self.edit(self.a,next(r for r in a if r['id']==first),title='Changed on A')
        self.edit(self.b,next(r for r in b if r['id']==second),title='Changed on B')
        self.exchange(self.a,self.b);self.exchange(self.b,self.a)
        self.assertEqual(self.rows(self.a),self.rows(self.b));self.assertEqual(self.a.sync_status()['conflicts'],[])
        settings=self.a.settings();self.a.save_settings({**settings,'enabled':True,'summary_time':'08:15','timezone':'Asia/Shanghai'})
        self.exchange(self.a,self.b)
        other=self.b.settings();self.assertFalse(other['enabled']);self.assertEqual(other['summary_time'],'09:00');self.assertEqual(other['timezone'],'Asia/Shanghai')
        self.assertNotEqual(self.a.sync_status()['device'],self.b.sync_status()['device'])
        raw=''.join(p.read_text() for p in (self.a.config.root/DIRECTORY/'changes').glob('*.json'))
        self.assertNotIn(str(self.a.config.root),raw);self.assertNotIn('summary_time',raw);self.assertNotIn('last_tick',raw)

    def test_same_item_conflict_explicit_resolution_and_late_branch(self):
        self.add(self.a);self.exchange(self.a,self.b);row_a=self.rows(self.a)[0];row_b=self.rows(self.b)[0]
        self.edit(self.a,row_a,title='A choice');self.edit(self.b,row_b,title='B choice')
        self.exchange(self.a,self.b);self.exchange(self.b,self.a)
        self.assertTrue(self.rows(self.a)[0]['conflicted']);self.assertEqual(self.rows(self.a),self.rows(self.b))
        conflict=self.a.sync_status()['conflicts'][0]
        with self.assertRaises(ConflictError):self.edit(self.a,self.rows(self.a)[0],title='Silent overwrite')
        chosen=next(v for v in conflict['versions'] if next(iter(v['value']['items'].values()))['data']['title']=='B choice')
        request={'workspace_revision':self.a.notes.workspace_revision,'entity':conflict['entity'],'revision':conflict['revision'],'selected':chosen['version']}
        self.a.resolve_sync(request);self.exchange(self.a,self.b)
        self.assertEqual(self.rows(self.a)[0]['title'],'B choice');self.assertFalse(self.rows(self.b)[0]['conflicted'])
        # A previously disconnected writer based on the old B head must not vanish.
        late=self.device('late')
        files=self.b.config.root/DIRECTORY/'changes';target=late.config.root/DIRECTORY/'changes';target.mkdir(parents=True)
        for p in files.glob('*.json'):
            e=json.loads(p.read_text())
            if all(len(c['parents'])<2 for c in e['changes']):shutil.copy2(p,target/p.name)
        conflict=late.sync_status()['conflicts'][0]
        late.resolve_sync({'workspace_revision':late.notes.workspace_revision,'entity':conflict['entity'],'revision':conflict['revision'],'selected':conflict['versions'][0]['version']})
        self.exchange(late,self.a)
        # Different concurrent resolutions are retained; equal resolutions coalesce.
        status=self.a.sync_status();self.assertGreater(status['records'],4)

    def test_repeat_split_is_one_conflict_unit_and_deletions_do_not_resurrect(self):
        self.add(self.a,repeat='daily',until='2026-11-09');self.exchange(self.a,self.b)
        before=self.rows(self.b)[0];split=self.rows(self.a)[2]
        self.command(self.a,'edit',id=split['id'],revision=split['revision'],occurrence=split['occurrence'],scope='future',item={**split,'title':'Future A'})
        self.edit(self.b,before,title='Whole B')
        self.exchange(self.a,self.b);self.exchange(self.b,self.a)
        conflicts=self.a.sync_status()['conflicts'];self.assertEqual(len(conflicts),1)
        chosen=next(v for v in conflicts[0]['versions'] if len(v['value']['items'])==1)
        self.a.resolve_sync({'workspace_revision':self.a.notes.workspace_revision,'entity':conflicts[0]['entity'],'revision':conflicts[0]['revision'],'selected':chosen['version']})
        self.assertEqual({r['title'] for r in self.rows(self.a)},{'Whole B','Task'})
        self.exchange(self.a,self.b)
        row=self.rows(self.a)[0];self.command(self.a,'delete',id=row['id'],revision=row['revision'],occurrence=row['occurrence'],scope='future')
        self.exchange(self.a,self.b);self.assertEqual(self.rows(self.b),[])
        self.exchange(self.b,self.a);self.assertEqual(self.rows(self.a),[])
        deleted=self.a.trash()['results'][0];self.command(self.a,'restore',id=deleted['id'],revision=deleted['revision'])
        self.exchange(self.a,self.b);self.assertEqual(len(self.rows(self.b)),4)

    def test_child_arrives_before_parent_and_removed_or_corrupt_files_block_writes(self):
        self.add(self.a);row=self.rows(self.a)[0];self.edit(self.a,row,title='New')
        paths=list((self.a.config.root/DIRECTORY/'changes').glob('*.json'))
        child=next(p for p in paths if json.loads(p.read_text())['changes'][0]['parents'])
        destination=self.b.config.root/DIRECTORY/'changes';destination.mkdir(parents=True)
        shutil.copy2(child,destination/child.name)
        self.assertEqual(self.rows(self.b),[]);self.assertEqual(self.b.sync_status()['pending'],1)
        with self.assertRaises(ConflictError):self.add(self.b)
        self.exchange(self.a,self.b);self.assertEqual(self.rows(self.b)[0]['title'],'New')
        (destination/child.name).unlink();self.assertEqual(self.rows(self.b)[0]['title'],'New')
        self.assertEqual(self.b.sync_status()['error'],'calendar.syncMissing')
        with self.assertRaises(ConflictError):self.add(self.b)
        self.exchange(self.a,self.b)
        (destination/child.name).write_text('{}')
        self.assertEqual(self.b.sync_status()['error'],'calendar.syncInvalid');self.assertEqual(self.rows(self.b)[0]['title'],'New')
        (destination/child.name).unlink();self.exchange(self.a,self.b);self.assertEqual(self.b.sync_status()['error'],'')

    def test_publication_survives_crash_before_sqlite_commit_and_retry_is_idempotent(self):
        original=self.a.sync.write
        def interrupted(event):original(event);raise RuntimeError('simulated interruption')
        body={'workspace_revision':self.a.notes.workspace_revision,'operation_id':'crash','command':{'type':'create','item':{'title':'Saved once','date':'2026-11-06'}}}
        with patch.object(self.a.sync,'write',side_effect=interrupted):
            with self.assertRaises(RuntimeError):self.a.command(body)
        rows=self.rows(self.a);self.assertEqual(len(rows),1)
        result=self.a.command(body);self.assertEqual(result['id'],rows[0]['id']);self.assertEqual(len(self.rows(self.a)),1)

    def legacy(self, cal):
        path=cal.files.state_path('calendar.sqlite3');path.parent.mkdir(parents=True)
        db=sqlite3.connect(path)
        db.executescript('''
        CREATE TABLE items(id TEXT PRIMARY KEY,revision INTEGER,data TEXT,deleted INTEGER);
        CREATE TABLE exceptions(item_id TEXT,date TEXT,data TEXT,PRIMARY KEY(item_id,date));
        CREATE TABLE settings(id INTEGER PRIMARY KEY,revision INTEGER,data TEXT);
        CREATE TABLE receipts(id TEXT PRIMARY KEY,signature TEXT,result TEXT);
        CREATE TABLE reminders(id TEXT PRIMARY KEY,date TEXT,item_id TEXT,data TEXT,state TEXT,seen INTEGER,created REAL);
        CREATE TABLE state(key TEXT PRIMARY KEY,value TEXT);
        PRAGMA user_version=1;
        ''')
        item=cal.validate({'title':'Legacy series','date':'2026-11-06','repeat':'daily','until':'2026-11-09'})
        identity='a'*32
        with db:
            db.execute('INSERT INTO items VALUES(?,?,?,0)',(identity,3,json.dumps(item)))
            db.execute('INSERT INTO exceptions VALUES(?,?,?)',(identity,'2026-11-07',json.dumps({'completed':True})))
            db.execute('INSERT INTO exceptions VALUES(?,?,?)',(identity,'2026-11-08',json.dumps({'deleted':True})))
            db.execute('INSERT INTO settings VALUES(1,2,?)',(json.dumps({'enabled':True,'summary':True,'summary_time':'08:30','timezone':'Asia/Shanghai','databases':[],'initialized':True}),))
            db.execute('INSERT INTO reminders VALUES(?,?,?,?,?,?,?)',('old-notice','2026-11-06',identity,json.dumps({'kind':'item','title':'Legacy series','date':'2026-11-06','item_id':identity}),'sent',1,123))
        db.close();return path

    def test_verified_migration_preserves_repeating_exceptions_trash_and_device_history(self):
        source=self.legacy(self.a);old=source.read_bytes()
        rows=self.rows(self.a);self.assertEqual(len(rows),3);self.assertTrue(rows[1]['completed']);self.assertEqual(len(self.a.trash()['results']),1)
        migration=self.a.sync_status()['migration'];backup=self.a.config.root/migration['backup']
        conn=sqlite3.connect(backup)
        try:self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],1);self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        finally:conn.close()
        conn=sqlite3.connect(source)
        try:self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],2)
        finally:conn.close()
        self.assertEqual(self.a.inbox()['results'][0]['state'],'sent');self.assertTrue(self.a.settings()['enabled'])
        self.exchange(self.a,self.b);self.assertEqual(self.rows(self.a),self.rows(self.b));self.assertFalse(self.b.settings()['enabled']);self.assertEqual(self.b.inbox()['results'],[])
        count=self.a.sync_status()['records'];self.a.sync_status();self.assertEqual(self.a.sync_status()['records'],count)
        self.assertTrue(old);self.assertTrue(backup.exists())

    def test_interrupted_migration_retries_without_duplicate_history(self):
        source=self.legacy(self.a);original=self.a.sync.write;calls=[]
        def interrupted(event):
            calls.append(event)
            if len(calls)==2:raise OSError('simulated full disk')
            return original(event)
        with patch.object(self.a.sync,'write',side_effect=interrupted):
            with self.assertRaises(OSError):self.rows(self.a)
        conn=sqlite3.connect(source)
        try:self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],1)
        finally:conn.close()
        self.assertEqual(len(self.rows(self.a)),3);self.assertEqual(self.a.sync_status()['records'],2)

    def test_each_device_can_deliver_same_reminder_once(self):
        self.add(self.a,start='10:00',reminder=10);self.exchange(self.a,self.b)
        for cal in (self.a,self.b):
            cal.save_settings({**cal.settings(),'enabled':True,'summary':False,'timezone':'Asia/Shanghai'})
            with cal.database() as db:db.execute('INSERT OR REPLACE INTO state VALUES(?,?)',('last_tick',str(dt.datetime(2026,11,6,1,0,tzinfo=UTC).timestamp())))
            cal.tick(dt.datetime(2026,11,6,1,51,tzinfo=UTC))
            owner={'root':str(cal.config.root),'workspace_revision':cal.notes.workspace_revision}
            self.assertEqual(len(cal.delivery(owner,claim=True)['results']),1)
            self.assertEqual(cal.delivery(owner,claim=True)['results'],[])
        self.exchange(self.a,self.b);self.exchange(self.b,self.a)
        self.assertEqual(len(self.a.inbox()['results']),1);self.assertEqual(len(self.b.inbox()['results']),1)

    def test_remote_reschedule_cancels_old_notice_without_cancelling_other_occurrences(self):
        self.add(self.a,start='10:00',reminder=10,repeat='daily',until='2026-11-07')
        self.a.save_settings({**self.a.settings(),'enabled':True,'summary':False,'timezone':'UTC'})
        self.exchange(self.a,self.b)
        with self.a.database() as db:
            db.execute('INSERT OR REPLACE INTO state VALUES(?,?)',('last_tick',str(dt.datetime(2026,11,6,9,0,tzinfo=UTC).timestamp())))
        self.a.tick(dt.datetime(2026,11,7,10,0,tzinfo=UTC))
        self.assertEqual(len(self.a.inbox()['results']),2)
        self.edit(self.b,self.rows(self.b)[0],start='11:00')
        self.exchange(self.b,self.a)
        owner={'root':str(self.a.config.root),'workspace_revision':self.a.notes.workspace_revision}
        notices=self.a.delivery(owner,claim=True)['results']
        self.assertEqual([r['date'] for r in notices],['2026-11-07'])

    def test_shared_settings_conflict_preserves_local_preferences_and_can_be_resolved(self):
        self.a.save_settings({**self.a.settings(),'timezone':'UTC'});self.exchange(self.a,self.b)
        a,b=self.a.settings(),self.b.settings()
        self.a.save_settings({**a,'timezone':'Asia/Shanghai','enabled':True})
        self.b.save_settings({**b,'timezone':'Asia/Tokyo'})
        self.exchange(self.a,self.b);self.exchange(self.b,self.a)
        self.assertTrue(self.a.settings()['shared_conflict']);self.assertTrue(self.a.settings()['enabled'])
        conflict=self.a.sync_status()['conflicts'][0]
        chosen=next(v for v in conflict['versions'] if v['value']['timezone']=='Asia/Tokyo')
        self.a.resolve_sync({'workspace_revision':self.a.notes.workspace_revision,'entity':'settings','revision':conflict['revision'],'selected':chosen['version']})
        self.exchange(self.a,self.b)
        self.assertFalse(self.b.settings()['shared_conflict']);self.assertEqual(self.a.settings()['timezone'],'Asia/Tokyo');self.assertFalse(self.b.settings()['enabled'])


if __name__=='__main__':unittest.main()
