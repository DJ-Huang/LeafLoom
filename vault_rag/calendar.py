"""Per-vault calendar and durable reminders. Markdown remains the daily-note source."""
from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vault_rag.local_state import ConflictError, relative, under
from vault_rag.note_operations import NoteError
from ruamel.yaml.error import YAMLError
from vault_rag.calendar_sync import CalendarSync, DIRECTORY

UTC = dt.timezone.utc
REPEATS = {'none', 'daily', 'weekly', 'monthly', 'weekdays'}


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('calendar.invalidDate')
    return dt.date.fromisoformat(value)


def clock(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{2}:\d{2}', value):
        raise ValueError('calendar.invalidTime')
    return dt.time.fromisoformat(value)


def instant(date, hour, zone):
    """Use first fold; round-trip nonexistent local times forward across the gap."""
    local = dt.datetime.combine(day(date), clock(hour), ZoneInfo(zone)).replace(fold=0)
    return local.astimezone(UTC)


def occurs(item, date):
    start, target = day(item['date']), day(date)
    if target < start or item.get('until') and date > item['until']: return False
    repeat = item['repeat']
    return (target == start if repeat == 'none' else
            repeat == 'daily' or repeat == 'weekdays' and target.weekday() < 5 or
            repeat == 'weekly' and target.weekday() == start.weekday() or
            repeat == 'monthly' and target.day == start.day)


class Calendar:
    def __init__(self, config, runtime, notes, databases):
        self.config, self.runtime, self.notes, self.databases = config, runtime, notes, databases
        self.files = runtime.files
        self.wake = threading.Event()
        self.stopped = threading.Event()
        self.thread = None
        self.sync = CalendarSync(self)

    @contextmanager
    def database(self, workspace_revision=None, root=None, *, publish_changes=True):
        if workspace_revision is not None:
            self.notes.check_workspace(workspace_revision)
            self.files.ensure_mutable()
        if root is not None and root != str(self.config.root):raise ConflictError('calendar.conflict')
        # All callers take config -> Files locks, also used by file move callbacks.
        path = self.files.state_path('calendar-local.sqlite3')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or path.exists() and not path.is_file(): raise ValueError('calendar.storageError')
        db = sqlite3.connect(path, timeout=8)
        db.row_factory = sqlite3.Row
        try:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > 1: raise ValueError('calendar.storageVersion')
            if version == 0:
                db.executescript('''
                CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, revision TEXT NOT NULL, data TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS exceptions(item_id TEXT NOT NULL, date TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(item_id,date));
                CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, signature TEXT NOT NULL, result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reminders(id TEXT PRIMARY KEY, date TEXT NOT NULL, item_id TEXT, data TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', seen INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                PRAGMA user_version=1;
                ''')
            self.sync.schema(db)
            with db:
                self.sync.prepare(db)
                if workspace_revision is not None:self.sync.require_ready(db)
                before=self.sync.snapshot(db)
                receipts={r[0] for r in db.execute('SELECT id FROM receipts')}
                yield db
                if publish_changes:self.sync.publish_diff(db,before,receipts)
        finally: db.close()

    def changed(self):
        self.wake.set()
        self.runtime.publish('calendar')

    def _settings(self, db):
        row = db.execute('SELECT * FROM settings WHERE id=1').fetchone()
        local = json.loads(row['data']) if row else {}
        shared = db.execute('SELECT data FROM sync_settings WHERE id=1').fetchone()
        head = db.execute("SELECT revision,conflicted FROM sync_heads WHERE entity='settings'").fetchone()
        return {'enabled':False,'summary':True,'summary_time':'09:00','initialized':bool(shared), **local,
                'timezone':'UTC','databases':[], **(json.loads(shared[0]) if shared else {}),
                'revision':str(row['revision'] if row else 0)+':'+(head['revision'] if head else '0'),
                'shared_conflict':bool(head and head['conflicted'])}

    def settings(self):
        with self.config.lock, self.files.lock, self.database() as db:
            return {**self._settings(db), 'workspace_revision':self.notes.workspace_revision, 'root':str(self.config.root)}

    def save_settings(self, body):
        if not isinstance(body,dict):raise ValueError('calendar.invalidCommand')
        with self.config.lock, self.files.lock:
            with self.database(body.get('workspace_revision','')) as db:
                old=self._settings(db)
                if body.get('revision')!=old['revision']:raise ConflictError('calendar.conflict')
                value={k:body.get(k,old[k]) for k in ('enabled','summary','summary_time','timezone','databases')}
                if not isinstance(value['enabled'],bool) or not isinstance(value['summary'],bool):raise ValueError('calendar.invalidSettings')
                clock(value['summary_time'])
                try:ZoneInfo(value['timezone'])
                except (ZoneInfoNotFoundError,TypeError,ValueError):raise ValueError('calendar.invalidTimezone') from None
                if not isinstance(value['databases'],list) or len(value['databases'])>50:raise ValueError('calendar.invalidSettings')
                value['databases']=list(dict.fromkeys(relative(p) for p in value['databases']))
                for path in value['databases']:
                    if not self.databases.config_read(path)['tasks']:raise ValueError('calendar.taskSetup')
                shared={k:value[k] for k in ('timezone','databases')}
                if old['shared_conflict'] and any(shared[k]!=old[k] for k in shared):raise ConflictError('calendar.syncConflict')
                if not old['shared_conflict']:db.execute('INSERT OR REPLACE INTO sync_settings VALUES(1,?)',(json.dumps(shared),))
                local={k:value[k] for k in ('enabled','summary','summary_time')};local['initialized']=True
                revision=int(old['revision'].split(':')[0])+1
                db.execute('INSERT OR REPLACE INTO settings VALUES(1,?,?)',(revision,json.dumps(local)))
                db.execute("UPDATE reminders SET state='cancelled' WHERE state='pending'")
                if not old['enabled'] and value['enabled']:
                    db.execute('INSERT OR REPLACE INTO state VALUES(?,?)',('last_tick',str(time.time())))
            result=self.settings()
        self.changed()
        return result

    def sync_status(self):
        with self.config.lock,self.files.lock,self.database() as db:
            return {**self.sync.status(db),'workspace_revision':self.notes.workspace_revision,'root':str(self.config.root)}

    def resolve_sync(self, body):
        if not isinstance(body,dict):raise ValueError('calendar.invalidCommand')
        with self.config.lock,self.files.lock,self.database(body.get('workspace_revision',''),publish_changes=False) as db:
            self.sync.resolve(db,body.get('entity'),body.get('revision'),body.get('selected'))
            db.execute("UPDATE reminders SET state='cancelled' WHERE state='pending'")
        self.changed()
        return {'ok':True}

    def daily(self, date):
        day(date)
        with self.config.lock:
            folder = self.config.data['daily_folder']
            path = '/'.join(p for p in (folder, date+'.md') if p)
            exists = self.config.path_for(path).is_file()
            return {'path': path, 'exists': exists, 'workspace_revision': self.notes.workspace_revision}

    def validate(self, raw):
        if not isinstance(raw, dict): raise ValueError('calendar.invalidItem')
        item = {k: raw.get(k, v) for k, v in dict(title='', description='', kind='todo', date='', start='', end='',
            repeat='none', until='', reminder=None, link=None, completed=False).items()}
        if not isinstance(item['title'], str) or not item['title'].strip() or len(item['title']) > 500: raise ValueError('calendar.titleRequired')
        item['title'] = item['title'].strip()
        if not isinstance(item['description'], str) or len(item['description']) > 20000: raise ValueError('calendar.invalidItem')
        day(item['date'])
        if item['kind'] not in ('todo','event') or item['repeat'] not in REPEATS or not isinstance(item['completed'], bool): raise ValueError('calendar.invalidItem')
        if item['until'] and day(item['until']) < day(item['date']): raise ValueError('calendar.invalidDate')
        if item['start']: clock(item['start'])
        if item['end']:
            clock(item['end'])
            if not item['start'] or item['end'] <= item['start']: raise ValueError('calendar.invalidTime')
        if item['reminder'] is not None:
            if type(item['reminder']) is not int or not 0 <= item['reminder'] <= 10080 or not item['start']: raise ValueError('calendar.invalidReminder')
        if item['link']:
            link = item['link']
            if not isinstance(link, dict): raise ValueError('calendar.invalidItem')
            config, note = self.task(link)
            item['link'] = {'database': config['path'], 'path': note['path'], 'id': str(note['metadata'].get('id') or '')}
        return item

    def task(self, link):
        config = self.databases.config_read(relative(link['database']))
        if not config['tasks']: raise ValueError('calendar.taskSetup')
        path = relative(link['path'])
        target = self.config.path_for(path)
        if link.get('id'):
            # Identity must still agree at the old path; never bind a replacement file.
            if not target.is_file() or str(self.files.read(path)['metadata'].get('id') or '') != link['id']:
                entries = self.notes.metadata().entries
                matches = [p for p,e in entries.items() if p.endswith('.md') and str(e['metadata'].get('id') or '') == link['id']]
                if len(matches) != 1: raise ValueError('calendar.brokenLink')
                path = matches[0]
        elif not target.is_file():raise FileNotFoundError('calendar.brokenLink')
        note = self.databases.read_record(config['path'], path)
        entry=self.runtime.catalog._entry(self.config.root,self.config.path_for(path),force=True)
        row = {'metadata': note['metadata'], 'title': entry['title'], 'file': entry['file']}
        if not self.databases.matches(config['config'].get('filters'), row): raise ValueError('calendar.brokenLink')
        return config, note

    def project(self, item):
        if not item.get('link'): return item
        try:
            config, note = self.task(item['link'])
            task = config['tasks']
            status = note['metadata'].get(task['statusField'].removeprefix('note.'))
            item['task'] = {'path': note['path'], 'title': note['metadata'].get('title') or note['metadata'].get('name') or note['path'],
                'completed': status in task['completedStatuses'], 'record_revision': note['revision'], 'config_revision': config['revision']}
            item['link'] = {**item['link'], 'path': note['path']}
            if item['kind'] == 'todo' and item['repeat'] == 'none': item['completed'] = item['task']['completed']
        except NoteError as error:
            if error.code=='metadata_pending':raise
            item['broken_link']=True
        except (ValueError, FileNotFoundError, YAMLError): item['broken_link'] = True
        return item

    def _items(self, db, start, end, *, deleted=False):
        result = []
        projections = {}
        def project(item):
            if not item.get('link'):return item
            key=json.dumps(item['link'],sort_keys=True)
            if key not in projections:projections[key]=self.project({**item,'repeat':'daily'})
            snapshot=projections[key]
            for field in ('task','broken_link','link'):
                if field in snapshot:item[field]=snapshot[field]
            if item['kind']=='todo' and item['repeat']=='none' and item.get('task'):item['completed']=item['task']['completed']
            return item
        exceptions = {(r['item_id'],r['date']):json.loads(r['data']) for r in db.execute('SELECT * FROM exceptions')}
        for row in db.execute('SELECT * FROM items WHERE deleted=?', (int(deleted),)):
            source = json.loads(row['data'])
            source['conflicted']=self.sync.item_conflicted(db,row['id'])
            if deleted:
                result.append({**source,'id':row['id'],'revision':row['revision']}); continue
            first, last = max(day(start), day(source['date'])), day(end)
            if source['until']: last = min(last, day(source['until']))
            if source['repeat'] == 'none': last = min(last, day(source['date']))
            for number in range(max(0,(last-first).days+1)):
                original = (first+dt.timedelta(days=number)).isoformat()
                if not occurs(source, original): continue
                change = exceptions.get((row['id'],original), {})
                if change.get('deleted'): continue
                item = {**source, **change, 'id':row['id'],'revision':row['revision'], 'occurrence':original}
                item['date'] = change.get('date', original)
                if start <= item['date'] <= end: result.append(project(item))
            # Moved exceptions may originate outside the visible date range.
            for (item_id, original), change in exceptions.items():
                if item_id != row['id'] or start <= original <= end or not change.get('date') or change.get('deleted'): continue
                if start <= change['date'] <= end and occurs(source, original):
                    result.append(project({**source, **change, 'id':row['id'],'revision':row['revision'],'occurrence':original}))
        return result

    def task_databases(self, cursor='', limit=100):
        with self.config.lock, self.files.lock:
            catalog=self.notes.metadata()
            with catalog.lock: candidates=[(p,e['title']) for p,e in sorted(catalog.entries.items()) if p.endswith('.base')]
            rows=[]
            for path,title in candidates:
                try:
                    if self.databases.config_read(path)['tasks']:rows.append({'path':path,'title':title})
                except (ValueError,FileNotFoundError,YAMLError):continue
            return self.notes.page(rows,limit,cursor,key='calendar-databases')

    def task_query(self, database, search='', cursor='', limit=100):
        with self.config.lock, self.files.lock:
            config=self.databases.config_read(database)
            if not config['tasks']:raise ValueError('calendar.taskSetup')
            rows,_=self.databases.query_rows(config,{},search)
            return self.notes.page(rows,limit,cursor,key=['calendar-tasks',database,search,config['revision']])

    def deadlines(self, settings, start, end):
        result, seen = [], set()
        for path in settings['databases']:
            try:
                config = self.databases.config_read(path)
                task = config['tasks']
                if not task: continue
                rows, _ = self.databases.query_rows(config, {})
                for row in rows:
                    date = str(row['metadata'].get(task['dueField'].removeprefix('note.')) or '')
                    if not start <= date <= end or row['path'] in seen: continue
                    try: day(date)
                    except ValueError: continue
                    seen.add(row['path'])
                    result.append({'id':'deadline:'+row['path'],'date':date,'title':row['title'],'kind':'deadline','start':'',
                        'completed':row['metadata'].get(task['statusField'].removeprefix('note.')) in task['completedStatuses'], 'path':row['path']})
            except NoteError as error:
                if error.code=='metadata_pending':raise
            except (ValueError, FileNotFoundError, YAMLError): continue
        return result

    def query(self, start, end, *, cursor='', limit=100, overdue=False, completed=True, deleted=False):
        a,b = day(start), day(end)
        if b < a or (b-a).days > 366: raise ValueError('calendar.range')
        with self.config.lock, self.files.lock, self.database() as db:
            settings = self._settings(db)
            # Overdue pagination covers all stored years; expansions are bounded per series below.
            if overdue:
                dates = [json.loads(r[0])['date'] for r in db.execute('SELECT data FROM items WHERE deleted=0')]
                start = min(dates+[start]); end = (a-dt.timedelta(days=1)).isoformat()
            rows = self._items(db, start, end, deleted=deleted)
            if not deleted and not overdue: rows += self.deadlines(settings,start,end)
            if overdue: rows = [r for r in rows if r['kind']=='todo' and not r['completed']]
            elif not completed: rows = [r for r in rows if not r['completed']]
            rows.sort(key=lambda r:(r['date'],r.get('start',''),r['title'],r['id']))
            page = self.notes.page(rows, limit, cursor, key=['calendar',start,end,overdue,completed,deleted])
            return {**page, 'root':str(self.config.root), 'settings':settings}

    def command(self, body):
        if not isinstance(body,dict): raise ValueError('calendar.invalidCommand')
        with self.config.lock, self.files.lock, self.database(body.get('workspace_revision','')) as db:
            self.notes.check_workspace(body.get('workspace_revision'))
            op = body.get('operation_id','')
            if not isinstance(op,str) or not re.fullmatch(r'[\w-]{1,128}',op): raise ValueError('calendar.operationRequired')
            cmd = body.get('command',{})
            if not isinstance(cmd,dict):raise ValueError('calendar.invalidCommand')
            signature = hashlib.sha256(json.dumps(cmd, sort_keys=True).encode()).hexdigest()
            previous = db.execute('SELECT * FROM receipts WHERE id=?',(op,)).fetchone()
            if previous:
                if previous['signature'] != signature: raise ConflictError('calendar.operationConflict')
                return json.loads(previous['result'])
            action = cmd.get('type'); result = {'ok':True}
            if action == 'create':
                item = self.validate(cmd.get('item'))
                item['completed'] = False
                identity = uuid.uuid4().hex
                db.execute('INSERT INTO items VALUES(?,?,?,0)',(identity,1,json.dumps(item)))
            else:
                identity = cmd.get('id')
                row = db.execute('SELECT * FROM items WHERE id=?',(identity,)).fetchone()
                if not row: raise FileNotFoundError('calendar.notFound')
                if self.sync.item_conflicted(db,identity):raise ConflictError('calendar.syncConflict')
                if cmd.get('revision') != row['revision']: raise ConflictError('calendar.conflict')
                source = json.loads(row['data']); item = dict(source)
                original = cmd.get('occurrence', source['date']); day(original)
                if action != 'restore' and (row['deleted'] or not occurs(source,original)): raise ValueError('calendar.notFound')
                exception = db.execute('SELECT data FROM exceptions WHERE item_id=? AND date=?',(identity,original)).fetchone()
                change = json.loads(exception[0]) if exception else {}
                scope = cmd.get('scope','one')
                if scope not in ('one','future'): raise ValueError('calendar.invalidItem')
                if action == 'restore':
                    if row['deleted']: db.execute('UPDATE items SET deleted=0 WHERE id=?',(identity,))
                    else:
                        if not change.get('deleted'): raise ValueError('calendar.notFound')
                        change.pop('deleted'); db.execute('INSERT OR REPLACE INTO exceptions VALUES(?,?,?)',(identity,original,json.dumps(change)))
                elif action == 'complete':
                    if source['kind'] != 'todo' or not isinstance(cmd.get('completed'),bool): raise ValueError('calendar.invalidItem')
                    if source['link'] and source['repeat']=='none':
                        config, note = self.task(source['link']); task = config['tasks']
                        if config['revision'] != cmd.get('config_revision'): raise ConflictError('calendar.conflict')
                        status = task['completedStatuses'][0] if cmd['completed'] else task['initialStatus']
                        key = task['statusField']
                        if note['metadata'].get(key.removeprefix('note.')) != status:
                            update = self.databases.command(config['path'], {'type':'record.update','path':note['path'],
                                'record_revision':cmd.get('record_revision'), 'values':{key:status}}, self.notes.workspace_revision, config['revision'])
                            result['note'] = update['note']
                    elif source['repeat']=='none': item['completed'] = cmd['completed']
                    else:
                        change['completed'] = cmd['completed']
                        db.execute('INSERT OR REPLACE INTO exceptions VALUES(?,?,?)',(identity,original,json.dumps(change)))
                elif action in ('edit','delete'):
                    updated = self.validate(cmd.get('item')) if action=='edit' else None
                    if source['repeat']=='none':
                        if action=='edit': item = updated
                        else: db.execute('UPDATE items SET deleted=1 WHERE id=?',(identity,))
                    elif scope=='one':
                        if action=='edit':
                            if updated['repeat'] != source['repeat']: raise ValueError('calendar.seriesScope')
                            change = {k:v for k,v in updated.items() if k not in ('repeat','until','completed') } | {'completed':change.get('completed',False)}
                        else: change['deleted'] = True
                        db.execute('INSERT OR REPLACE INTO exceptions VALUES(?,?,?)',(identity,original,json.dumps(change)))
                    else:
                        item['until'] = (day(original)-dt.timedelta(days=1)).isoformat()
                        # A separate soft-deleted tail allows restoration without losing earlier occurrences.
                        tail = {**source,'date':original} if action=='delete' else updated
                        successor = uuid.uuid4().hex
                        db.execute('INSERT INTO items VALUES(?,?,?,?)',(successor,1,json.dumps(tail),int(action=='delete')))
                        self.sync.join_series(db,identity,successor)
                        if action=='delete':
                            db.execute('UPDATE exceptions SET item_id=? WHERE item_id=? AND date>=?',(successor,identity,original))
                        else: db.execute('DELETE FROM exceptions WHERE item_id=? AND date>=?',(identity,original))
                        result['successor_id'] = successor
                else: raise ValueError('calendar.invalidCommand')
                db.execute('UPDATE items SET data=? WHERE id=?',(json.dumps(item),identity))
                if source['repeat']=='none' or action=='restore':
                    db.execute("UPDATE reminders SET state='cancelled' WHERE item_id=? AND state='pending'",(identity,))
                else:
                    compare = '>=' if scope=='future' and action in ('edit','delete') else '='
                    db.execute("UPDATE reminders SET state='cancelled' WHERE item_id=? AND state='pending' AND json_extract(data,'$.occurrence')"+compare+"?",(identity,original))
            result.update(id=identity, workspace_revision=self.notes.workspace_revision)
            db.execute('INSERT INTO receipts VALUES(?,?,?)',(op,signature,json.dumps(result)))
        self.changed()
        return result

    def trash(self, cursor='', limit=100):
        with self.config.lock, self.files.lock, self.database() as db:
            rows = self._items(db,'1970-01-01','9999-12-31',deleted=True)
            for row in db.execute('SELECT i.id,i.revision,i.data,e.date,e.data AS exception FROM items i JOIN exceptions e ON i.id=e.item_id WHERE i.deleted=0'):
                if json.loads(row['exception']).get('deleted'):
                    rows.append({**json.loads(row['data']),'id':row['id'],'revision':row['revision'],'date':row['date'],'occurrence':row['date']})
            return self.notes.page(rows,limit,cursor,key='calendar-trash')

    def moved(self, source, destination):
        if not self.files.state_path('calendar-local.sqlite3').exists() and not self.files.state_path('calendar.sqlite3').exists() and not self.config.path_for(DIRECTORY).exists():return
        with self.database() as db:
            def remap(value):
                link = value.get('link')
                if link:
                    for key in ('database','path'):
                        if under(link[key],source): link[key] = destination+link[key][len(source):]
                return value
            for row in db.execute('SELECT * FROM items').fetchall():
                if self.sync.item_conflicted(db,row['id']):continue
                value = remap(json.loads(row['data']))
                if json.dumps(value) != row['data']:
                    db.execute('UPDATE items SET data=? WHERE id=?',(json.dumps(value),row['id']))
            for row in db.execute('SELECT * FROM exceptions').fetchall():
                if self.sync.item_conflicted(db,row['item_id']):continue
                value = remap(json.loads(row['data']))
                db.execute('UPDATE exceptions SET data=? WHERE item_id=? AND date=?',(json.dumps(value),row['item_id'],row['date']))
            settings = self._settings(db)
            paths = [destination+p[len(source):] if under(p,source) else p for p in settings['databases']]
            if paths != settings['databases'] and not settings['shared_conflict']:
                db.execute('INSERT OR REPLACE INTO sync_settings VALUES(1,?)',(json.dumps({'timezone':settings['timezone'],'databases':paths}),))
        self.changed()

    def inbox(self, cursor='', limit=50):
        with self.config.lock, self.files.lock, self.database() as db:
            rows = [{**json.loads(r['data']), 'id':r['id'],'state':r['state'],'seen':bool(r['seen'])} for r in db.execute("SELECT * FROM reminders WHERE state!='cancelled' ORDER BY created DESC,id")]
            return {**self.notes.page(rows,limit,cursor,key='calendar-inbox'),'root':str(self.config.root)}

    @staticmethod
    def reminder_id(item, zone):
        fingerprint = hashlib.sha256(json.dumps([item['date'],item['start'],item['reminder'],zone]).encode()).hexdigest()[:12]
        return ':'.join([item['id'],item['occurrence'],fingerprint])

    def reconcile_pending(self, db, settings):
        # Recheck immediately before claiming, including changes just imported
        # from another device. Other occurrences retain their pending notices.
        dates = {}
        for row in db.execute("SELECT * FROM reminders WHERE state='pending' AND item_id IS NOT NULL").fetchall():
            if row['date'] not in dates: dates[row['date']] = self._items(db,row['date'],row['date'])
            notice = json.loads(row['data'])
            valid = any(i['id']==row['item_id'] and i['occurrence']==notice.get('occurrence')
                and not (i['completed'] or i.get('broken_link') or i.get('conflicted'))
                and i['reminder'] is not None and self.reminder_id(i,settings['timezone'])==row['id']
                and i['title']==notice['title'] for i in dates[row['date']])
            if not valid: db.execute("UPDATE reminders SET state='cancelled' WHERE id=?",(row['id'],))

    def delivery(self, body, *, claim=False):
        if not isinstance(body,dict): raise ValueError('calendar.invalidCommand')
        with self.config.lock, self.files.lock, self.database(body.get('workspace_revision',''),body.get('root','')) as db:
            if body.get('root') != str(self.config.root): raise ConflictError('calendar.conflict')
            if claim:
                settings = self._settings(db)
                self.reconcile_pending(db,settings)
                rows = list(db.execute("SELECT * FROM reminders WHERE state='pending' ORDER BY created LIMIT 100")) if settings['enabled'] and not settings['shared_conflict'] else []
                for row in rows: db.execute("UPDATE reminders SET state='claimed' WHERE id=?",(row['id'],))
                return {'root':str(self.config.root),'workspace_revision':self.notes.workspace_revision,'results':[
                    {**json.loads(r['data']),'id':r['id'],'late':json.loads(r['data']).get('late',False) or time.time()-r['created']>60} for r in rows]}
            state = body.get('state')
            if state == 'seen': db.execute('UPDATE reminders SET seen=1 WHERE id=?',(body.get('id'),))
            elif state in ('sent','failed'):
                db.execute("UPDATE reminders SET state=? WHERE id=? AND state='claimed'",(state,body.get('id')))
            else: raise ValueError('calendar.invalidCommand')
        self.changed()
        return {'ok':True}

    def tick(self, now=None):
        now = now or dt.datetime.now(UTC)
        with self.config.lock, self.files.lock:
            if not self.config.data.get('root'):return
            if not self.files.state_path('calendar-local.sqlite3').exists() and not self.files.state_path('calendar.sqlite3').exists() and not self.config.path_for(DIRECTORY).exists():return
            with self.database() as db:
                settings = self._settings(db)
                status=self.sync.meta(db,'status',{})
                if not settings['enabled'] or settings['shared_conflict'] or status.get('error') or status.get('pending'):return
                zone = settings['timezone']; today = now.astimezone(ZoneInfo(zone)).date()
                last = db.execute("SELECT value FROM state WHERE key='last_tick'").fetchone()
                previous = float(last[0]) if last else now.timestamp()-30
                if now.timestamp() < previous: previous = now.timestamp()-30
                # Historical notices stay in the inbox; catch-up scans at most the last 30 days.
                begin = max(dt.datetime.fromtimestamp(previous,UTC).astimezone(ZoneInfo(zone)).date(), today-dt.timedelta(days=30))
                items = self._items(db,begin.isoformat(),(today+dt.timedelta(days=7)).isoformat())
                added = False
                next_due = now.timestamp()+30
                for item in items:
                    if item['completed'] or item.get('broken_link') or item.get('conflicted') or item['reminder'] is None: continue
                    due = instant(item['date'],item['start'],zone)-dt.timedelta(minutes=item['reminder'])
                    if due.timestamp()>now.timestamp():next_due=min(next_due,due.timestamp())
                    if not previous < due.timestamp() <= now.timestamp(): continue
                    key = self.reminder_id(item,zone)
                    value = {'kind':'item','title':item['title'],'date':item['date'],'item_id':item['id'],'occurrence':item['occurrence'],'late':now.timestamp()-due.timestamp()>60}
                    added |= db.execute('INSERT OR IGNORE INTO reminders(id,date,item_id,data,created) VALUES(?,?,?,?,?)',
                        (key,item['date'],item['id'],json.dumps(value),now.timestamp())).rowcount > 0
                summary_due = instant(today.isoformat(),settings['summary_time'],zone)
                if settings['summary'] and summary_due.timestamp()>now.timestamp():next_due=min(next_due,summary_due.timestamp())
                if settings['summary'] and previous < summary_due.timestamp() <= now.timestamp():
                    current = [i for i in items if i['date']==today.isoformat() and not i['completed'] and not i.get('conflicted')]
                    deadlines = [i for i in self.deadlines(settings,today.isoformat(),today.isoformat()) if not i['completed']]
                    dates = [json.loads(r[0])['date'] for r in db.execute('SELECT data FROM items WHERE deleted=0')]
                    overdue = self._items(db,min(dates+[today.isoformat()]),(today-dt.timedelta(days=1)).isoformat())
                    count = sum(i['kind']=='todo' and not i['completed'] and not i.get('conflicted') for i in overdue)
                    if current or deadlines or count:
                        value = {'kind':'summary','date':today.isoformat(),'count':len(current)+len(deadlines),'overdue':count,'late':now.timestamp()-summary_due.timestamp()>60}
                        added |= db.execute('INSERT OR IGNORE INTO reminders(id,date,data,created) VALUES(?,?,?,?)',
                            ('summary:'+today.isoformat(),today.isoformat(),json.dumps(value),now.timestamp())).rowcount > 0
                self.reconcile_pending(db,settings)
                db.execute('INSERT OR REPLACE INTO state VALUES(?,?)',('last_tick',str(now.timestamp())))
            if added: self.runtime.publish('calendar')
            return max(.1,min(30,next_due-now.timestamp()))

    def start(self):
        if self.thread: return
        def run():
            while not self.stopped.is_set():
                self.wake.clear()
                delay=30
                try: delay=self.tick() or 30
                except NoteError as error:
                    if error.code=='metadata_pending':delay=1
                    else:logging.getLogger(__name__).exception('Calendar reminder check failed')
                except Exception: logging.getLogger(__name__).exception('Calendar reminder check failed')
                self.wake.wait(delay)
        self.thread = threading.Thread(target=run,name='calendar-reminders',daemon=True); self.thread.start()

    def stop(self):
        self.stopped.set(); self.wake.set()
        if self.thread: self.thread.join(timeout=5)
