"""Immutable, content-addressed calendar changes; SQLite is a local projection.

Causality comes from parent hashes, never device clocks or file arrival order.
A recurring series and its split successors form one conflict/commit unit.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vault_rag.local_state import ConflictError, relative
from vault_rag.platform_support import move_exclusive

DIRECTORY = 'Calendar/LeafLoom'
HASH = re.compile(r'[0-9a-f]{64}')
IDENTITY = re.compile(r'[0-9a-f]{32}')
MAX_RECORD = 32 * 1024 * 1024


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def publish(path, content):
    """No replacement, including another writer's independently published file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != content: raise ValueError('calendar.syncInvalid')
        return
    temporary = path.with_name(uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        try: move_exclusive(temporary, path)
        except FileExistsError:
            if path.read_bytes() != content: raise ValueError('calendar.syncInvalid') from None
        if os.name != 'nt':
            descriptor = os.open(path.parent, os.O_RDONLY)
            try: os.fsync(descriptor)
            finally: os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value): raise ValueError('calendar.syncInvalid')
    dt.date.fromisoformat(value)


def validate_data(value, partial=False):
    if not isinstance(value, dict): raise ValueError('calendar.syncInvalid')
    fields = {'title','description','kind','date','start','end','repeat','until','reminder','link','completed'}
    if set(value) - (fields | ({'deleted'} if partial else set())) or not partial and fields-set(value): raise ValueError('calendar.syncInvalid')
    if 'title' in value and (not isinstance(value['title'], str) or not value['title'].strip() or len(value['title']) > 500): raise ValueError('calendar.syncInvalid')
    if 'description' in value and (not isinstance(value['description'], str) or len(value['description']) > 20000): raise ValueError('calendar.syncInvalid')
    for key in ('date','until'):
        if key in value and not isinstance(value[key],str): raise ValueError('calendar.syncInvalid')
        if key=='date' and key in value and not value[key]: raise ValueError('calendar.syncInvalid')
        if value.get(key): date(value[key])
    for key in ('start','end'):
        if key in value and not isinstance(value[key],str): raise ValueError('calendar.syncInvalid')
        if value.get(key):
            if not isinstance(value[key],str) or not re.fullmatch(r'\d{2}:\d{2}',value[key]): raise ValueError('calendar.syncInvalid')
            dt.time.fromisoformat(value[key])
    if 'kind' in value and value['kind'] not in ('todo','event'): raise ValueError('calendar.syncInvalid')
    if 'repeat' in value and value['repeat'] not in ('none','daily','weekly','monthly','weekdays'): raise ValueError('calendar.syncInvalid')
    for key in ('completed','deleted'):
        if key in value and type(value[key]) is not bool: raise ValueError('calendar.syncInvalid')
    reminder = value.get('reminder')
    if reminder is not None and (type(reminder) is not int or not 0 <= reminder <= 10080 or not value.get('start')): raise ValueError('calendar.syncInvalid')
    link = value.get('link')
    if link is not None:
        if not isinstance(link,dict) or not isinstance(link.get('database'),str) or not isinstance(link.get('path'),str): raise ValueError('calendar.syncInvalid')
        if relative(link['database']) != link['database'] or not link['database'].endswith('.base'): raise ValueError('calendar.syncInvalid')
        if relative(link['path']) != link['path'] or not link['path'].endswith('.md'): raise ValueError('calendar.syncInvalid')
        if not isinstance(link.get('id',''),str): raise ValueError('calendar.syncInvalid')


def validate_value(entity, value):
    if entity == 'settings':
        if not isinstance(value,dict) or set(value) != {'timezone','databases'}: raise ValueError('calendar.syncInvalid')
        try: ZoneInfo(value['timezone'])
        except (TypeError, ValueError, ZoneInfoNotFoundError): raise ValueError('calendar.syncInvalid') from None
        if not isinstance(value['databases'],list) or len(value['databases']) > 50: raise ValueError('calendar.syncInvalid')
        for path in value['databases']:
            if not isinstance(path,str) or relative(path) != path or not path.endswith('.base'): raise ValueError('calendar.syncInvalid')
        return
    if not entity.startswith('item:') or not IDENTITY.fullmatch(entity[5:]): raise ValueError('calendar.syncInvalid')
    if not isinstance(value,dict) or set(value) != {'items'} or not isinstance(value['items'],dict) or not value['items']: raise ValueError('calendar.syncInvalid')
    if entity[5:] not in value['items']: raise ValueError('calendar.syncInvalid')
    for identity, item in value['items'].items():
        if not isinstance(identity,str) or not IDENTITY.fullmatch(identity) or not isinstance(item,dict) or set(item) != {'data','deleted','exceptions'}: raise ValueError('calendar.syncInvalid')
        validate_data(item['data'])
        if type(item['deleted']) is not bool or not isinstance(item['exceptions'],dict): raise ValueError('calendar.syncInvalid')
        for occurrence, change in item['exceptions'].items():
            date(occurrence); validate_data(change,partial=True)


class CalendarSync:
    def __init__(self, calendar):
        self.calendar = calendar
        self.config, self.files = calendar.config, calendar.files
        self.cache = {}
        self.device = None

    def device_id(self):
        if self.device: return self.device
        path = self.config.directory / 'calendar-device.json'
        if not path.exists(): publish(path, encoded({'id':uuid.uuid4().hex}))
        if path.is_symlink(): raise ValueError('calendar.storageError')
        value = json.loads(path.read_bytes())
        if not IDENTITY.fullmatch(value.get('id','')): raise ValueError('calendar.storageError')
        self.device = value['id']
        return self.device

    @staticmethod
    def schema(db):
        db.executescript('''
        CREATE TABLE IF NOT EXISTS sync_events(id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sync_heads(entity TEXT PRIMARY KEY, heads TEXT NOT NULL, revision TEXT NOT NULL, conflicted INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sync_members(item_id TEXT PRIMARY KEY, entity TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sync_settings(id INTEGER PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sync_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')

    @staticmethod
    def meta(db, key, default=None):
        row = db.execute('SELECT value FROM sync_meta WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    @staticmethod
    def set_meta(db, key, value):
        db.execute('INSERT OR REPLACE INTO sync_meta VALUES(?,?)',(key,json.dumps(value)))

    def write(self, event):
        self.validate_event(event)
        raw = encoded(event)
        if len(raw) > MAX_RECORD: raise ValueError('calendar.syncTooLarge')
        identity = hashlib.sha256(raw).hexdigest()
        # Every component is checked again on publication; no symlinks or root escape.
        path = self.config.path_for(f'{DIRECTORY}/changes/{identity}.json',writable=True)
        publish(path,raw)
        self.calendar.runtime.files_changed(f'{DIRECTORY}/changes/{identity}.json')
        return identity

    @staticmethod
    def validate_event(event):
        if not isinstance(event,dict) or event.get('schema') != 1 or not isinstance(event.get('changes'),list) or not event['changes']: raise ValueError('calendar.syncInvalid')
        if set(event)-{'schema','device','created','changes','receipt'}: raise ValueError('calendar.syncInvalid')
        if not isinstance(event.get('device'),str) or not (event['device']=='migration' or IDENTITY.fullmatch(event['device'])): raise ValueError('calendar.syncInvalid')
        if type(event.get('created')) not in (float,int) or not math.isfinite(event['created']): raise ValueError('calendar.syncInvalid')
        entities=set()
        for change in event['changes']:
            if not isinstance(change,dict) or set(change) != {'entity','parents','value'}: raise ValueError('calendar.syncInvalid')
            entity=change['entity']
            if not isinstance(entity,str) or entity in entities: raise ValueError('calendar.syncInvalid')
            entities.add(entity)
            if not isinstance(change['parents'],list) or len(change['parents']) != len(set(change['parents'])) or any(not isinstance(p,str) or not HASH.fullmatch(p) for p in change['parents']): raise ValueError('calendar.syncInvalid')
            validate_value(entity,change['value'])
        receipt=event.get('receipt')
        if receipt is not None:
            if not isinstance(receipt,dict) or not isinstance(receipt.get('id'),str) or not re.fullmatch(r'[\w-]{1,128}',receipt['id']) or not isinstance(receipt.get('signature'),str) or not HASH.fullmatch(receipt['signature']): raise ValueError('calendar.syncInvalid')
            result=receipt.get('result')
            if not isinstance(result,dict) or set(result)-{'ok','id','successor_id'} or result.get('ok') is not True: raise ValueError('calendar.syncInvalid')
            if any(not isinstance(result[k],str) or not IDENTITY.fullmatch(result[k]) for k in ('id','successor_id') if k in result): raise ValueError('calendar.syncInvalid')

    @staticmethod
    def snapshot(db):
        values={}
        members=dict(db.execute('SELECT item_id,entity FROM sync_members'))
        exceptions={}
        for row in db.execute('SELECT * FROM exceptions'):
            exceptions.setdefault(row['item_id'],{})[row['date']]=json.loads(row['data'])
        for row in db.execute('SELECT * FROM items ORDER BY id'):
            entity=members.get(row['id'],'item:'+row['id'])
            values.setdefault(entity,{'items':{}})['items'][row['id']]={'data':json.loads(row['data']),'deleted':bool(row['deleted']),'exceptions':exceptions.get(row['id'],{})}
        row=db.execute('SELECT data FROM sync_settings WHERE id=1').fetchone()
        if row:values['settings']=json.loads(row[0])
        return values

    @staticmethod
    def join_series(db, source, successor):
        row=db.execute('SELECT entity FROM sync_members WHERE item_id=?',(source,)).fetchone()
        entity=row[0] if row else 'item:'+source
        db.execute('INSERT OR REPLACE INTO sync_members VALUES(?,?)',(successor,entity))

    @staticmethod
    def item_conflicted(db, identity):
        row=db.execute('SELECT h.conflicted FROM sync_heads h JOIN sync_members m ON h.entity=m.entity WHERE m.item_id=?',(identity,)).fetchone()
        return bool(row and row[0])

    def migrate(self, db):
        if self.meta(db,'migration') is not None:return
        legacy=self.files.state_path('calendar.sqlite3')
        if not legacy.exists():
            self.set_meta(db,'migration',{'state':'not_needed'});return
        source=sqlite3.connect(legacy,timeout=8);source.row_factory=sqlite3.Row
        try:
            source.execute('BEGIN IMMEDIATE')
            version=source.execute('PRAGMA user_version').fetchone()[0]
            if version not in (1,2):raise ValueError('calendar.storageVersion')
            tables={name:[dict(r) for r in source.execute('SELECT * FROM '+name)] for name in ('items','exceptions','settings','receipts','reminders','state')}
            signature=digest(tables)
            backup=self.files.state_path('calendar-backups',signature+'.sqlite3')
            if not backup.exists():
                backup.parent.mkdir(parents=True,exist_ok=True)
                temporary=backup.with_name(uuid.uuid4().hex+'.tmp')
                try:
                    reader=sqlite3.connect(legacy.as_uri()+'?mode=ro',uri=True)
                    target=sqlite3.connect(temporary)
                    try:reader.backup(target)
                    finally:target.close();reader.close()
                    with temporary.open('rb') as stream:os.fsync(stream.fileno())
                    move_exclusive(temporary,backup)
                finally:temporary.unlink(missing_ok=True)
            verified=sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True);verified.row_factory=sqlite3.Row
            try:
                if verified.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('calendar.migrationFailed')
                copy={name:[dict(r) for r in verified.execute('SELECT * FROM '+name)] for name in tables}
                if digest(copy)!=signature:raise ValueError('calendar.migrationFailed')
            finally:verified.close()
            exceptions={}
            for row in tables['exceptions']:exceptions.setdefault(row['item_id'],{})[row['date']]=json.loads(row['data'])
            records=[]
            for row in tables['items']:
                value={'items':{row['id']:{'data':json.loads(row['data']),'deleted':bool(row['deleted']),'exceptions':exceptions.get(row['id'],{})}}}
                records.append(('item:'+row['id'],value))
            if tables['settings']:
                old=json.loads(tables['settings'][0]['data'])
                records.append(('settings',{'timezone':old['timezone'],'databases':old['databases']}))
                db.execute('INSERT OR REPLACE INTO settings VALUES(1,?,?)',(tables['settings'][0]['revision'],json.dumps({k:old[k] for k in ('enabled','summary','summary_time','initialized') if k in old})))
            ids=[]
            for entity,value in records:
                event={'schema':1,'device':'migration','created':0,'changes':[{'entity':entity,'parents':[],'value':value}]}
                identity=self.write(event)
                raw=self.config.path_for(f'{DIRECTORY}/changes/{identity}.json').read_bytes()
                if json.loads(raw)!=event:raise ValueError('calendar.migrationFailed')
                ids.append(identity)
            # Preserve this device's delivery history; none of it enters shared records.
            for table in ('receipts','reminders','state'):
                for row in tables[table]:
                    columns=','.join(row);marks=','.join('?' for _ in row)
                    db.execute(f'INSERT OR REPLACE INTO {table} ({columns}) VALUES({marks})',tuple(row.values()))
            # Older builds reject >1, preventing writes to the obsolete source.
            # Its original schema/data remain intact in the verified backup.
            source.execute('PRAGMA user_version=2');source.commit()
            self.set_meta(db,'migration',{'state':'complete','backup':str(backup.relative_to(self.config.root)),'records':len(ids)})
        finally:
            source.close()

    def prepare(self, db):
        self.migrate(db)
        folder=self.config.path_for(DIRECTORY+'/changes')
        existing={r['id']:json.loads(r['data']) for r in db.execute('SELECT * FROM sync_events')}
        events=dict(existing);seen=set();invalid=[]
        if folder.exists():
            if not folder.is_dir():raise ValueError('calendar.syncInvalid')
            for path in sorted(folder.iterdir()):
                if path.name.endswith('.tmp'):continue
                if not path.name.endswith('.json'):continue
                identity=path.stem
                try:
                    self.config.path_for(f'{DIRECTORY}/changes/{path.name}')
                    if not HASH.fullmatch(identity) or not path.is_file():raise ValueError('calendar.syncInvalid')
                    stat=path.stat()
                    if stat.st_size > MAX_RECORD:raise ValueError('calendar.syncTooLarge')
                    key=str(path);stamp=(stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
                    cached=self.cache.get(key)
                    if cached and cached[0]==stamp:event=cached[1]
                    else:
                        raw=path.read_bytes()
                        if len(raw)>MAX_RECORD or hashlib.sha256(raw).hexdigest()!=identity:raise ValueError('calendar.syncInvalid')
                        event=json.loads(raw);self.validate_event(event)
                        self.cache[key]=(stamp,event)
                    seen.add(identity);events[identity]=event
                except (ValueError,TypeError,KeyError,OSError):invalid.append(path.name)
        missing=sorted(set(existing)-seen)
        if invalid or missing:
            self.set_meta(db,'status',{'error':'calendar.syncInvalid' if invalid else 'calendar.syncMissing','files':(invalid or missing)[:20],'pending':0})
            return
        applicable=set();pending=set(events)
        while pending:
            ready=[]
            for identity in sorted(pending):
                valid=True
                for change in events[identity]['changes']:
                    for parent in change['parents']:
                        if parent not in applicable:valid=False;break
                        if not any(c['entity']==change['entity'] for c in events[parent]['changes']):
                            self.set_meta(db,'status',{'error':'calendar.syncInvalid','files':[identity+'.json'],'pending':0});return
                    if not valid:break
                if valid:ready.append(identity)
            if not ready:break
            applicable.update(ready);pending.difference_update(ready)
        for identity in set(events)-set(existing):db.execute('INSERT INTO sync_events VALUES(?,?)',(identity,json.dumps(events[identity])))
        self.set_meta(db,'status',{'error':'','files':[],'pending':len(pending)})
        fingerprint=digest(sorted(applicable))
        if self.meta(db,'projection') != fingerprint:
            self.materialize(db,events,applicable)
            self.set_meta(db,'projection',fingerprint)
        # Receipts make a crash after immutable publication but before SQLite commit retryable.
        device=self.device_id()
        for identity in sorted(applicable):
            event=events[identity];receipt=event.get('receipt')
            if receipt and event['device']==device:
                previous=db.execute('SELECT signature FROM receipts WHERE id=?',(receipt['id'],)).fetchone()
                if previous and previous[0]!=receipt['signature']:raise ConflictError('calendar.operationConflict')
                result={**receipt['result'],'workspace_revision':self.calendar.notes.workspace_revision}
                db.execute('INSERT OR IGNORE INTO receipts VALUES(?,?,?)',(receipt['id'],receipt['signature'],json.dumps(result)))

    def materialize(self, db, events, applicable):
        previous = self.snapshot(db)
        versions={};referenced={}
        for identity in sorted(applicable):
            for change in events[identity]['changes']:
                entity=change['entity'];versions.setdefault(entity,{})[identity]=change['value']
                referenced.setdefault(entity,set()).update(change['parents'])
        db.execute('DELETE FROM items');db.execute('DELETE FROM exceptions');db.execute('DELETE FROM sync_members');db.execute('DELETE FROM sync_heads');db.execute('DELETE FROM sync_settings')
        ownership={}
        for entity, variants in sorted(versions.items()):
            heads=sorted(set(variants)-referenced[entity]);revision=digest(heads)
            conflict=len({digest(variants[h]) for h in heads})>1
            db.execute('INSERT INTO sync_heads VALUES(?,?,?,?)',(entity,json.dumps(heads),revision,int(conflict)))
            # Deterministic preview only. Conflicted items cannot be edited or scheduled.
            chosen=heads[0]
            if entity!='settings':
                chosen=next((h for h in heads if any(not i['deleted'] for i in variants[h]['items'].values())),chosen)
            value=variants[chosen]
            if entity=='settings':db.execute('INSERT INTO sync_settings VALUES(1,?)',(json.dumps(value),));continue
            for identity,item in value['items'].items():
                if identity in ownership:raise ValueError('calendar.syncInvalid')
                ownership[identity]=entity
                db.execute('INSERT INTO items VALUES(?,?,?,?)',(identity,revision,json.dumps(item['data']),int(item['deleted'])))
                db.execute('INSERT INTO sync_members VALUES(?,?)',(identity,entity))
                for occurrence,change in item['exceptions'].items():
                    db.execute('INSERT INTO exceptions VALUES(?,?,?)',(identity,occurrence,json.dumps(change)))
        if previous and previous != self.snapshot(db):
            db.execute("UPDATE reminders SET state='cancelled' WHERE state='pending' AND item_id IS NULL")

    def require_ready(self, db):
        status=self.meta(db,'status',{})
        if status.get('error') or status.get('pending'):raise ConflictError(status.get('error') or 'calendar.syncPending')

    def publish_diff(self, db, before, old_receipts):
        after=self.snapshot(db);changes=[]
        for entity,value in sorted(after.items()):
            if before.get(entity)==value:continue
            validate_value(entity,value)
            row=db.execute('SELECT * FROM sync_heads WHERE entity=?',(entity,)).fetchone()
            if row and row['conflicted']:raise ConflictError('calendar.syncConflict')
            changes.append({'entity':entity,'parents':json.loads(row['heads']) if row else [],'value':value})
        if set(before)-set(after):raise ValueError('calendar.syncMissing')
        if not changes:return
        self.require_ready(db)
        event={'schema':1,'device':self.device_id(),'created':time.time(),'changes':changes}
        new=[r for r in db.execute('SELECT * FROM receipts') if r['id'] not in old_receipts]
        if len(new)==1:
            result=json.loads(new[0]['result'])
            event['receipt']={'id':new[0]['id'],'signature':new[0]['signature'],'result':{k:v for k,v in result.items() if k in ('ok','id','successor_id')}}
        self.write(event)
        self.prepare(db)

    def status(self, db):
        conflicts=[]
        for row in db.execute('SELECT * FROM sync_heads WHERE conflicted=1 ORDER BY entity'):
            versions=[]
            for head in json.loads(row['heads']):
                event=json.loads(db.execute('SELECT data FROM sync_events WHERE id=?',(head,)).fetchone()[0])
                value=next(c['value'] for c in event['changes'] if c['entity']==row['entity'])
                versions.append({'version':head,'device':event['device'],'created':event['created'],'value':value})
            conflicts.append({'entity':row['entity'],'revision':row['revision'],'versions':versions})
        return {**self.meta(db,'status',{}),'directory':DIRECTORY,'records':db.execute('SELECT COUNT(*) FROM sync_events').fetchone()[0],
            'conflicts':conflicts,'migration':self.meta(db,'migration',{}),'device':self.device_id()}

    def resolve(self, db, entity, revision, selected):
        self.require_ready(db)
        row=db.execute('SELECT * FROM sync_heads WHERE entity=?',(entity,)).fetchone()
        if not row or not row['conflicted'] or row['revision']!=revision:raise ConflictError('calendar.conflict')
        heads=json.loads(row['heads'])
        if selected not in heads:raise ValueError('calendar.invalidCommand')
        event=json.loads(db.execute('SELECT data FROM sync_events WHERE id=?',(selected,)).fetchone()[0])
        value=next(c['value'] for c in event['changes'] if c['entity']==entity)
        self.write({'schema':1,'device':self.device_id(),'created':time.time(),'changes':[{'entity':entity,'parents':heads,'value':value}]})
        self.prepare(db)
