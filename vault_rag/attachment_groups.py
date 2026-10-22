"""User-defined attachment groups. Immutable, checksummed events; no original bytes.

Local SQLite is authoritative offline. WebDAV is an append-only replica in its
own directory; divergent heads are retained and require explicit resolution.
"""
from __future__ import annotations
from contextlib import contextmanager, closing
import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import PurePosixPath

from vault_rag.platform_support import private_file_mode
from vault_rag.local_state import ConflictError
from vault_rag.remote_webdav import RemoteStorageError, remote_path


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


class AttachmentGroups:
    def __init__(self, remote, library):
        self.remote, self.library = remote, library
        self.lock = threading.RLock()
        self.wake, self.stopped = threading.Event(), threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True, name='attachment-groups')
        self.thread.start()

    @contextmanager
    def _db(self, root):
        self.remote._root(root)
        path = self.remote._files().state_path('attachment-groups', 'groups.sqlite')
        path.parent.mkdir(parents=True, exist_ok=True,mode=0o700)
        for suffix in ('', '-wal', '-shm', '-journal'):
            if path.with_name(path.name + suffix).is_symlink():
                raise ValueError('Group database cannot be a link')
        with closing(sqlite3.connect(path, timeout=10)) as db,db:
            private_file_mode(path)
            db.row_factory = sqlite3.Row
            db.executescript('''CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, entity TEXT NOT NULL,
                parents TEXT NOT NULL,payload TEXT NOT NULL,data BLOB NOT NULL,synced INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT NOT NULL);''')
            db.execute('INSERT OR IGNORE INTO state VALUES(?,?)', ('device', uuid.uuid4().hex))
            yield db

    @staticmethod
    def _groups(db):
        events = [dict(row) for row in db.execute('SELECT * FROM events')]
        by_id = {row['id']: row for row in events}
        entities = {}
        for event in events:
            entities.setdefault(event['entity'], []).append(event)
        groups = []
        for key, rows in entities.items():
            parents = {p for row in rows for p in json.loads(row['parents'])}
            heads = sorted(row['id'] for row in rows if row['id'] not in parents)
            complete = all(p in by_id and by_id[p]['entity'] == key for row in rows for p in json.loads(row['parents']))
            if not heads:
                continue
            value = json.loads(by_id[heads[0]]['payload'])
            # A delete concurrent with an edit remains visible for resolution.
            if value['deleted'] and len(heads) == 1 and complete:
                continue
            groups.append({**value, 'id': key, 'revision': digest([heads,complete]),
                'conflicts': [{'head': h, 'value': json.loads(by_id[h]['payload'])} for h in heads] if len(heads) > 1 or not complete else [],
                'heads': heads})
        return sorted(groups, key=lambda g: (g['position'], g['name'].casefold(), g['id']))

    def listing(self, root):
        self.reconcile_members(root)
        with self.lock, self._db(root) as db:
            groups = self._groups(db)
            pending = db.execute('SELECT COUNT(*) FROM events WHERE synced=0').fetchone()[0]
            status = db.execute("SELECT value FROM state WHERE key='sync'").fetchone()
        self.wake.set()
        configured=bool(self.library.settings(root)['storage_id'])
        return {'groups': [{k: v for k, v in g.items() if k != 'heads'} for g in groups],
                'sync': json.loads(status[0]) if status and configured else {'state': 'local_only'}, 'pending': pending if configured else 0}

    @staticmethod
    def _validate(value):
        if not isinstance(value, dict) or set(value) != {'name', 'position', 'rules', 'included', 'excluded', 'deleted'}:
            raise ValueError('Invalid group definition')
        if not isinstance(value['name'], str) or not 1 <= len(value['name'].strip()) <= 100:
            raise ValueError('Enter a group name')
        if type(value['position']) not in (int, float) or not -1000000 <= value['position'] <= 1000000 or type(value['deleted']) is not bool:
            raise ValueError('Invalid group position')
        rules = value['rules']
        if not isinstance(rules, dict) or set(rules) - {'sources', 'directories', 'formats', 'categories', 'tags'}:
            raise ValueError('Invalid group rules')
        for key, entries in rules.items():
            if not isinstance(entries, list) or len(entries) > 100 or any(not isinstance(v, str) or not v or len(v) > 1000 for v in entries):
                raise ValueError('Invalid group rule values')
            if key == 'directories':
                for directory in entries:
                    remote_path(directory, allow_empty=False)
        for field in ('included', 'excluded'):
            if not isinstance(value[field], list) or len(value[field]) > 10000:
                raise ValueError('Too many group members')
            for member in value[field]:
                if not isinstance(member, dict) or set(member) != {'uid', 'scope', 'path', 'asset_id'} or any(not isinstance(v, str) or len(v) > 8192 for v in member.values()):
                    raise ValueError('Invalid group member')
                if not re.fullmatch('[0-9a-f]{32}', member['uid']):
                    raise ValueError('Invalid attachment identity')
                remote_path(member['path'], allow_empty=False)
        if len(encoded(value)) > 2 * 1024**2:
            raise ValueError('Group definition is too large')

    def identity(self, root, item, device):
        storage = item.get('storage_id', item.get('source_id', 'local'))
        asset_id = item.get('asset_id', item.get('id', ''))
        if storage == 'local':
            scope, path = 'local:' + device, item['path']
            locator = asset_id or path
        else:
            settings = self.library.settings(root)
            scope = 'primary' if storage == settings['storage_id'] else 'storage:' + storage
            source = self.remote._source(storage, root)
            path = item.get('remote_path') or item['path']
            locator = source['remote_root'] + '/' + path
        key = uuid.uuid5(uuid.NAMESPACE_URL, 'leafloom-attachment:' + scope + ':' + locator).hex
        return {'uid': key, 'scope': scope, 'path': path, 'asset_id': asset_id}

    def snapshot(self, root):
        with self.lock, self._db(root) as db:
            return self._groups(db), db.execute("SELECT value FROM state WHERE key='device'").fetchone()[0]

    def update(self, root, operation, payload):
        if operation not in {'create', 'update', 'delete', 'members'} or not isinstance(payload, dict):
            raise ValueError('Invalid group operation')
        if 'resolve' in payload and type(payload['resolve']) is not bool:raise ValueError('Explicit conflict resolution must be boolean')
        members = []
        if operation == 'members':
            if payload.get('mode') not in {'include', 'exclude', 'reset'}:
                raise ValueError('Invalid membership mode')
            paths = payload.get('paths', [])
            if not isinstance(paths, list) or not 1 <= len(paths) <= 100:
                raise ValueError('Select between 1 and 100 attachments')
            _, device = self.snapshot(root)
            for path in paths:
                if not isinstance(path, str): raise ValueError('Invalid attachment path')
                item = self.remote.stat(root, path=path)
                # The logical public path and server path are intentionally distinct.
                members.append(self.identity(root, item, device))
        with self.lock, self._db(root) as db:
            groups = self._groups(db)
            key = uuid.uuid4().hex if operation == 'create' else payload.get('id', '')
            current = next((g for g in groups if g['id'] == key), None)
            if operation != 'create':
                if not current: raise FileNotFoundError('Attachment group not found')
                if payload.get('revision') != current['revision']: raise ConflictError('Attachment group changed; reload before saving')
                if current['conflicts'] and not payload.get('resolve'): raise ConflictError('Resolve group conflicts explicitly before editing')
            value = {k: current[k] for k in ('name', 'position', 'rules', 'included', 'excluded', 'deleted')} if current else {
                'name': '', 'position': max((g['position'] for g in groups),default=-1)+1, 'rules': {}, 'included': [], 'excluded': [], 'deleted': False}
            if operation in {'create', 'update'}:
                for field in ('name', 'position', 'rules'):
                    if field in payload: value[field] = payload[field]
            elif operation == 'delete': value['deleted'] = True
            else:
                keys = {m['uid'] for m in members}
                for field in ('included', 'excluded'):
                    value[field] = [m for m in value[field] if m['uid'] not in keys]
                if payload['mode'] != 'reset': value['included' if payload['mode'] == 'include' else 'excluded'].extend(members)
            if operation in {'create','update'} and isinstance(value.get('rules'),dict) and isinstance(value['rules'].get('sources'),list):
                primary=self.library.settings(root)['storage_id']
                value['rules']={**value['rules'],'sources':['primary' if source==primary else source for source in value['rules']['sources']]}
            self._validate(value)
            event_id = uuid.uuid4().hex
            event = {'schema': 1, 'id': event_id, 'entity': key, 'parents': current['heads'] if current else [], 'payload': value}
            self._accept(db, event, encoded(event), False)
        self.wake.set()
        return self.listing(root)

    def _accept(self, db, event, data, synced):
        if set(event) != {'schema', 'id', 'entity', 'parents', 'payload'} or event['schema'] != 1:
            raise ValueError('Invalid group event')
        if any(not isinstance(event[k], str) or not re.fullmatch('[0-9a-f]{32}', event[k]) for k in ('id', 'entity')):
            raise ValueError('Invalid group event identity')
        parents = event['parents']
        if not isinstance(parents, list) or len(parents) > 100 or event['id'] in parents or any(not isinstance(p, str) or not re.fullmatch('[0-9a-f]{32}', p) for p in parents):
            raise ValueError('Invalid group event parents')
        self._validate(event['payload'])
        pending=list(parents);seen=set()
        while pending:
            parent=pending.pop()
            if parent==event['id']:raise ValueError('Cyclic group history')
            if parent in seen:continue
            seen.add(parent)
            previous=db.execute('SELECT entity,parents FROM events WHERE id=?',(parent,)).fetchone()
            if previous:
                if previous['entity']!=event['entity']:raise ValueError('Group parent belongs to another group')
                pending.extend(json.loads(previous['parents']))
        old = db.execute('SELECT data FROM events WHERE id=?', (event['id'],)).fetchone()
        if old and bytes(old[0]) != data: raise ConflictError('Immutable group event changed')
        db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?)', (event['id'], event['entity'], json.dumps(parents), encoded(event['payload']).decode(), data, int(synced)))

    def reconcile_members(self, root):
        """Follow only explicit manifest identities, never basename guesses.

        Resolve outside the group lock to retain catalog -> manifest -> group
        lock order. A concurrent user edit wins the local CAS and is retried.
        """
        groups,device=self.snapshot(root)
        for group in groups:
            if group['conflicts']:continue
            value={k:group[k] for k in ('name','position','rules','included','excluded','deleted')}
            changed=False
            for field in ('included','excluded'):
                members=[]
                for member in value[field]:
                    current=member
                    if member['scope']=='local:'+device:
                        try:
                            with self.remote.lock,self.remote._db(root) as manifest:
                                row=self.remote._resolve(manifest,asset_id=member['asset_id'])
                            item=self.remote._public_asset(row)
                            current=self.identity(root,item,device)
                        except (FileNotFoundError,ValueError):pass
                    changed=changed or current!=member
                    members.append(current)
                value[field]=members
            if not changed:continue
            with self.lock,self._db(root) as db:
                latest=next((g for g in self._groups(db) if g['id']==group['id']),None)
                if not latest or latest['revision']!=group['revision']:continue
                event={'schema':1,'id':uuid.uuid4().hex,'entity':group['id'],'parents':latest['heads'],'payload':value}
                self._accept(db,event,encoded(event),False)

    def sync(self, root):
        settings = self.library.settings(root)
        if not settings['storage_id']: return
        self.reconcile_members(root)
        context = self.library._context(root)
        binding={key:context[key] for key in ('source_id','metadata_directory')}
        with self.lock,self._db(root) as db:
            old=db.execute("SELECT value FROM state WHERE key='binding'").fetchone()
            if old and json.loads(old[0])!=binding:raise ConflictError('Group metadata storage changed; explicit relocation is required')
            db.execute('INSERT OR IGNORE INTO state VALUES(?,?)',('binding',json.dumps(binding)))
        directory = context['metadata_directory'] + '/attachment-groups/events'
        provider = self.library._provider(context)
        with provider.session():
            marker_path=context['metadata_directory']+'/attachment-groups/library.json'
            with self.lock,self._db(root) as db:
                saved=db.execute("SELECT value FROM state WHERE key='remote_identity'").fetchone()
            try:marker_bytes=provider.read_bytes(marker_path,max_bytes=16384)
            except RemoteStorageError as error:
                if error.code!='remote_not_found':raise
                if saved:raise ConflictError('Remote group library identity is missing')
                marker_bytes=encoded({'schema':1,'library_id':uuid.uuid4().hex,'remote_root':provider.source['remote_root']})
                try:provider.put_immutable(marker_path,marker_bytes,max_bytes=16384,verified_directories=set())
                except RemoteStorageError as conflict:
                    if conflict.code!='immutable_object_conflict':raise
                    marker_bytes=provider.read_bytes(marker_path,max_bytes=16384)
            marker=json.loads(marker_bytes)
            if not isinstance(marker,dict) or marker.get('schema')!=1 or not re.fullmatch('[0-9a-f]{32}',str(marker.get('library_id',''))) or marker.get('remote_root')!=provider.source['remote_root']:
                raise ConflictError('Invalid remote group library identity')
            if saved and saved[0]!=marker['library_id']:raise ConflictError('Remote group library identity changed')
            with self.lock,self._db(root) as db:
                self.library._check(context)
                db.execute('INSERT OR IGNORE INTO state VALUES(?,?)',('remote_identity',marker['library_id']))
            try: entries = provider.scan(directory, max_files=20000, max_depth=1, prune_reserved=False, read_ignore=False)
            except RemoteStorageError as error:
                if error.code != 'remote_not_found': raise
                entries = []
            with self.lock, self._db(root) as db:
                known = {row['id']: hashlib.sha256(row['data']).hexdigest() for row in db.execute('SELECT id,data FROM events')}
            pulled=0
            for item in entries:
                match = re.fullmatch(re.escape(directory) + r'/([0-9a-f]{32})-([0-9a-f]{64})\.json', item['path'])
                if not match or item['size'] > 2 * 1024**2: raise ValueError('Invalid remote group event')
                if match[1] in known:
                    if known[match[1]] != match[2]: raise ConflictError('Immutable group event changed')
                    continue
                self.library._check(context)
                if pulled+item['size']>64*1024**2:raise RemoteStorageError('group_sync_batch_limit')
                data = provider.read_bytes(item['path'], max_bytes=2 * 1024**2)
                pulled+=len(data)
                if hashlib.sha256(data).hexdigest() != match[2]: raise ValueError('Group checksum mismatch')
                event = json.loads(data)
                if event.get('id') != match[1]: raise ValueError('Group event identity mismatch')
                with self.lock, self._db(root) as db:
                    self.library._check(context)
                    self._accept(db, event, data, True)
            with self.lock, self._db(root) as db:
                queued = [dict(row) for row in db.execute('SELECT id,data FROM events WHERE synced=0')]
            directories=set()
            for row in queued:
                self.library._check(context)
                data = bytes(row['data'])
                provider.put_immutable(directory + '/' + row['id'] + '-' + hashlib.sha256(data).hexdigest() + '.json', data, max_bytes=2 * 1024**2,verified_directories=directories)
                self.library._check(context)
                with self.lock, self._db(root) as db: db.execute('UPDATE events SET synced=1 WHERE id=?', (row['id'],))
        with self.lock, self._db(root) as db:
            db.execute('INSERT OR REPLACE INTO state VALUES(?,?)', ('sync', json.dumps({'state': 'synced', 'at': time.time()})))

    def _loop(self):
        while not self.stopped.is_set():
            self.wake.wait(30); self.wake.clear()
            if self.stopped.is_set(): break
            root = str(self.remote.config.root)
            try:
                # Do not initialize a database for untouched vaults merely by starting LeafLoom.
                if self.remote._files().state_path('attachment-groups', 'groups.sqlite').exists(): self.sync(root)
            except Exception as error:
                try:
                    with self.lock, self._db(root) as db:
                        db.execute('INSERT OR REPLACE INTO state VALUES(?,?)', ('sync', json.dumps({'state':'conflict' if isinstance(error,ConflictError) else 'waiting_for_connection'})))
                except Exception: pass

    def stop(self):
        self.stopped.set(); self.wake.set(); self.thread.join(timeout=2)


def matches(group, item, identity):
    key = identity['uid']
    if any(m['uid'] == key for m in group['excluded']): return False
    if any(m['uid'] == key for m in group['included']): return True
    rules = {k: v for k, v in group['rules'].items() if v}
    if not rules: return False
    path = item.get('remote_path') or item['path']
    checks = {
        'sources': lambda values: item['storage_id'] in values or item['source'] in values or ('primary' in values and identity['scope'] == 'primary'),
        'directories': lambda values: any(path == v.rstrip('/') or path.startswith(v.rstrip('/') + '/') for v in values),
        'formats': lambda values: PurePosixPath(item['name']).suffix.lower().lstrip('.') in [v.lower().lstrip('.') for v in values],
        'categories': lambda values: item.get('category', '') in values,
        'tags': lambda values: bool(set(values) & set(item.get('tags', []))),
    }
    return all(checks[k](values) for k, values in rules.items())
