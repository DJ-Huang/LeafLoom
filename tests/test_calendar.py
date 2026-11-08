"""Calendar regressions use disposable vaults and explicit clocks; no OS notifications."""
import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from vault_rag.calendar import Calendar, instant, occurs, UTC
from vault_rag.local_state import LocalConfig, ConflictError
from vault_rag.knowledge import Runtime
from vault_rag.databases import Databases


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = (Path(self.temp.name)/'vault').resolve(); self.root.mkdir()
        self.config = LocalConfig(Path(self.temp.name)/'state'); self.config.save({'root':str(self.root),'include_roots':[]})
        self.runtime = Runtime(self.config); self.addCleanup(self.runtime.stop)
        self.db = Databases(self.config,self.runtime)
        self.cal = Calendar(self.config,self.runtime,self.db.notes,self.db)
        self.runtime.files.calendar_moved = self.cal.moved
        self.ws = self.config.data['revision']; self.counter = 0

    def command(self, type, **values):
        self.counter += 1
        return self.cal.command({'workspace_revision':self.ws,'operation_id':'op-'+str(self.counter),'command':{'type':type,**values}})

    def add(self, **values):
        return self.command('create',item={'title':'Plan','date':'2026-11-06',**values})['id']

    def rows(self, start='2026-11-01',end='2026-12-01',**kw):
        return self.cal.query(start,end,**kw)['results']

    def edit(self, record, type, **values):
        return self.command(type,id=record['id'],revision=record['revision'],occurrence=record['occurrence'],**values)

    def task(self):
        self.db.command('Tasks.base',{'type':'create','preset':'tasks'},self.ws,operation_id='tasks')
        c = self.db.config_read('Tasks.base')
        result = self.db.command('Tasks.base',{'type':'record.create','title':'Original','values':{c['tasks']['dueField']:'2026-11-20'}},self.ws,c['revision'],'task')
        self.runtime.catalog.scan()
        return {'database':'Tasks.base','path':result['path']}

    def enable(self, now):
        s = self.cal.settings();self.cal.save_settings({**s,'enabled':True,'timezone':'Asia/Shanghai'})
        with self.cal.database() as db: db.execute('INSERT OR REPLACE INTO state VALUES(?,?)',('last_tick',str(now.timestamp())))

    def test_no_empty_notes_and_daily_preserves_existing_bytes(self):
        self.assertFalse(self.cal.daily('2026-11-06')['exists'])
        self.assertFalse((self.root/'Daily').exists())
        result = self.db.notes.daily(self.ws,'2026-11-06')
        path = self.root/result['path']; original = b'---\r\nvendor: unchanged\r\n---\r\n# Existing\r\n'
        path.write_bytes(original)
        self.assertFalse(self.db.notes.daily(self.ws,'2026-11-06')['created'])
        self.assertTrue(self.cal.daily('2026-11-06')['exists']); self.assertEqual(path.read_bytes(),original)

    def test_idempotence_conflict_delete_restore_and_vault_isolation(self):
        body={'workspace_revision':self.ws,'operation_id':'same','command':{'type':'create','item':{'title':'A','date':'2026-11-06'}}}
        result=self.cal.command(body);self.assertEqual(result,self.cal.command(body));self.assertEqual(len(self.rows()),1)
        with self.assertRaises(ConflictError): self.cal.command({**body,'command':{**body['command'],'item':{'title':'B','date':'2026-11-06'}}})
        item=self.rows()[0];self.edit(item,'delete');self.assertEqual(self.rows(),[])
        with self.assertRaises(ConflictError):self.edit(item,'edit',item=item)
        trash=self.cal.trash()['results'][0];self.command('restore',id=trash['id'],revision=trash['revision']);self.assertEqual(len(self.rows()),1)
        other=Path(self.temp.name)/'other';other.mkdir();self.config.save({'root':str(other),'include_roots':[]})
        with self.assertRaises(ConflictError):self.cal.command(body)
        self.assertFalse((other/'.vault-rag/calendar-local.sqlite3').exists())
        self.assertFalse((other/'Calendar/LeafLoom').exists())
        self.assertEqual(self.rows(),[])

    def test_recurrence_month_end_weekend_leap_and_exceptions(self):
        self.add(date='2024-01-31',repeat='monthly',until='2024-05-31')
        self.assertEqual([r['date'] for r in self.rows('2024-01-01','2024-06-01')],['2024-01-31','2024-03-31','2024-05-31'])
        self.assertTrue(occurs({'date':'2024-02-29','repeat':'monthly','until':''},'2024-03-29'))
        identity=self.add(repeat='weekdays',until='2026-11-10')
        items=[r for r in self.rows() if r['id']==identity];self.assertEqual([r['date'] for r in items],['2026-11-06','2026-11-09','2026-11-10'])
        self.edit(items[0],'complete',completed=True)
        items=[r for r in self.rows() if r['id']==identity];self.assertTrue(items[0]['completed']);self.assertFalse(items[1]['completed'])
        self.edit(items[1],'edit',item={**items[1],'date':'2026-12-10','until':''})
        self.assertEqual([r['date'] for r in self.rows('2026-12-01','2026-12-20') if r['id']==identity],['2026-12-10'])
        original=[r for r in self.rows() if r['id']==identity][0]
        self.edit(original,'delete',scope='one');trash=self.cal.trash()['results'][0]
        self.command('restore',id=trash['id'],revision=trash['revision'],occurrence=trash['occurrence'])
        self.assertTrue(any(r['date']=='2026-11-06' for r in self.rows()))

    def test_split_series_keeps_previous_completions_and_restores_tail(self):
        identity=self.add(repeat='daily',until='2026-11-10')
        items=self.rows();self.edit(items[0],'complete',completed=True)
        items=self.rows();self.edit(items[2],'delete',scope='future')
        self.assertEqual([r['date'] for r in self.rows()],['2026-11-06','2026-11-07']);self.assertTrue(self.rows()[0]['completed'])
        tail=self.cal.trash()['results'][0];self.command('restore',id=tail['id'],revision=tail['revision'])
        self.assertEqual(len(self.rows()),5)

    def test_single_task_sync_repeat_reference_and_deadlines(self):
        link=self.task();identity=self.add(link=link)
        item=self.rows()[0];self.assertFalse(item['completed'])
        self.edit(item,'complete',completed=True,record_revision=item['task']['record_revision'],config_revision=item['task']['config_revision'])
        self.assertTrue(self.rows()[0]['completed'])
        config=self.db.config_read('Tasks.base');note=self.runtime.files.read(link['path']);key=config['tasks']['statusField']
        self.db.command('Tasks.base',{'type':'record.update','path':link['path'],'record_revision':note['etag'],'values':{key:config['tasks']['initialStatus']}},self.ws,config['revision'])
        self.runtime.catalog.scan();self.assertFalse(self.rows()[0]['completed'])
        repeating=self.add(title='Follow up',repeat='daily',until='2026-11-07',link=link)
        item=next(i for i in self.rows() if i['id']==repeating);self.edit(item,'complete',completed=True)
        self.assertFalse(next(i for i in self.rows() if i['id']==identity)['completed'])
        s=self.cal.settings();self.cal.save_settings({**s,'databases':['Tasks.base']})
        deadlines=[i for i in self.rows() if i['kind']=='deadline'];self.assertEqual(deadlines[0]['date'],'2026-11-20')
        self.assertEqual(self.runtime.files.read(link['path'])['metadata'][config['tasks']['dueField']],'2026-11-20')

    def test_task_move_broken_link_and_draft_version(self):
        link=self.task();self.add(link=link);item=self.rows()[0]
        self.runtime.files.save(link['path'],self.runtime.files.read(link['path'])['text']+'External\n',item['task']['record_revision'])
        with self.assertRaises(ConflictError):self.edit(item,'complete',completed=True,record_revision=item['task']['record_revision'],config_revision=item['task']['config_revision'])
        self.runtime.files.move(link['path'],'Tasks/Moved.md');self.runtime.catalog.scan()
        self.assertEqual(self.rows()[0]['task']['path'],'Tasks/Moved.md')
        (self.root/'Tasks/Moved.md').unlink();self.runtime.catalog.scan();self.assertTrue(self.rows()[0]['broken_link'])

    def test_notification_dedupe_claim_failure_and_edit_cancellation(self):
        self.add(start='10:00',reminder=10)
        before=dt.datetime(2026,11,6,1,0,tzinfo=UTC);self.enable(before)
        now=dt.datetime(2026,11,6,1,51,tzinfo=UTC)
        self.cal.tick(now);self.cal.tick(now);inbox=self.cal.inbox()['results'];self.assertEqual(len(inbox),1)
        owner={'root':str(self.root),'workspace_revision':self.ws}
        claimed=self.cal.delivery(owner,claim=True);self.assertEqual(len(claimed['results']),1);self.assertEqual(self.cal.delivery(owner,claim=True)['results'],[])
        self.cal.delivery({**owner,'id':inbox[0]['id'],'state':'failed'});self.assertEqual(self.cal.inbox()['results'][0]['state'],'failed')
        item=self.rows()[0];self.edit(item,'edit',item={**item,'start':'11:00'})
        self.cal.tick(dt.datetime(2026,11,6,2,51,tzinfo=UTC));self.assertEqual(len(self.cal.inbox()['results']),2)
        item=self.rows()[0];self.edit(item,'delete');self.assertFalse(any(i['state']=='pending' for i in self.cal.inbox()['results']))

    def test_external_move_uses_unique_identity_and_metadata_pending_is_retryable(self):
        from unittest.mock import patch
        from vault_rag.note_operations import NoteError
        link=self.task();note=self.runtime.files.read(link['path'])
        self.runtime.files.properties(link['path'],{'id':'stable-task'},note['etag'])
        self.runtime.catalog.scan();self.add(link=link)
        moved=self.root/'Tasks/External.md';(self.root/link['path']).rename(moved);self.runtime.catalog.scan()
        self.assertEqual(self.rows()[0]['task']['path'],'Tasks/External.md')
        with patch.object(self.db.notes,'metadata',side_effect=NoteError('metadata_pending','pending')):
            with self.assertRaises(NoteError):self.rows()
        (self.root/'Tasks/Duplicate.md').write_bytes(moved.read_bytes());self.runtime.catalog.scan()
        self.assertTrue(self.rows()[0]['broken_link'])

    def test_completing_one_occurrence_does_not_cancel_other_pending_notices(self):
        self.add(start='10:00',reminder=10,repeat='daily',until='2026-11-07')
        self.enable(dt.datetime(2026,11,6,1,0,tzinfo=UTC))
        self.cal.tick(dt.datetime(2026,11,7,2,0,tzinfo=UTC))
        reminders=[r for r in self.cal.inbox()['results'] if r['kind']=='item']
        self.assertEqual(len(reminders),2)
        self.edit(self.rows()[0],'complete',completed=True)
        reminders=[r for r in self.cal.inbox()['results'] if r['kind']=='item']
        self.assertEqual(len(reminders),1);self.assertEqual(reminders[0]['date'],'2026-11-07')

    def test_unclaimed_notices_survive_midnight_and_restart(self):
        self.add(start='10:00',reminder=10)
        self.enable(dt.datetime(2026,11,6,1,0,tzinfo=UTC))
        self.cal.tick(dt.datetime(2026,11,6,1,51,tzinfo=UTC))
        self.cal.tick(dt.datetime(2026,11,7,1,0,tzinfo=UTC))
        self.cal.tick(dt.datetime(2026,11,8,1,0,tzinfo=UTC))
        other=Calendar(self.config,self.runtime,self.db.notes,self.db)
        notices=[r for r in other.inbox()['results'] if r['kind']=='item']
        self.assertEqual(len(notices),1);self.assertEqual(notices[0]['state'],'pending')

    def test_summary_catchup_and_timezones(self):
        self.add()
        self.enable(dt.datetime(2026,11,6,0,0,tzinfo=UTC));self.cal.tick(dt.datetime(2026,11,6,4,0,tzinfo=UTC))
        self.assertEqual(self.cal.inbox()['results'][0]['kind'],'summary');self.assertTrue(self.cal.inbox()['results'][0]['late'])
        self.assertEqual(instant('2026-03-08','02:30','America/New_York'),dt.datetime(2026,3,8,7,30,tzinfo=UTC))
        self.assertEqual(instant('2026-11-01','01:30','America/New_York'),dt.datetime(2026,11,1,5,30,tzinfo=UTC))


class CalendarApiTests(unittest.TestCase):
    setUp = CalendarTests.setUp

    def test_routes_keep_desktop_delivery_private_and_daily_compatible(self):
        from starlette.testclient import TestClient
        from vault_rag.web_server import create_app
        app=create_app(self.config,self.runtime,start_background=False)
        token=(self.config.directory/'auth-token').read_text().strip()
        with TestClient(app,base_url='http://127.0.0.1:18080') as client:
            self.assertEqual(client.get('/api/calendar/settings').status_code,401)
            headers={'Authorization':'Bearer '+token}
            session=client.get('/api/session',headers=headers).json()
            settings=client.get('/api/calendar/settings',headers=headers).json()
            response=client.get('/api/calendar/daily?date=2026-11-06',headers=headers)
            self.assertFalse(response.json()['exists'])
            response=client.post('/api/daily',headers=headers,json={'date':'2026-11-06','workspace_revision':self.ws})
            self.assertEqual(response.status_code,200);self.assertTrue(response.json()['created'])
            self.assertEqual(client.post('/api/daily',headers=headers).status_code,200)
            owner={'root':settings['root'],'workspace_revision':self.ws}
            client.cookies.set('vault_session',token)
            browser_headers={'X-Vault-CSRF':session['csrf']}
            self.assertEqual(client.get('/api/calendar/reminders/state',headers=browser_headers).status_code,403)
            self.assertEqual(client.get('/api/calendar/reminders/state',headers=headers).json()['config']['root'],settings['root'])
            self.assertEqual(client.post('/api/calendar/reminders/claim',headers=browser_headers,json=owner).status_code,403)
            self.assertEqual(client.post('/api/calendar/reminders/ack',headers=browser_headers,json={**owner,'state':'sent','id':'fake'}).status_code,403)
            self.assertEqual(client.post('/api/calendar/reminders/claim',headers=headers,json=owner).status_code,200)
            self.assertEqual(client.get('/api/calendar/query?start=2026-11-01&end=2026-11-30',headers=headers).status_code,200)
            self.runtime.catalog.scan()
            self.assertEqual(client.get('/api/calendar/databases',headers=headers).json()['results'],[])


if __name__=='__main__':unittest.main()
