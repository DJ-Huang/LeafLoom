"""Portable product metadata on WebDAV; local SQLite is an offline projection.

Original packages and attachment aliases are never written here. Metadata uses
immutable events, explicit product IDs, parent revisions and verified readback.
"""
from __future__ import annotations

from contextlib import closing,contextmanager,ExitStack
from concurrent.futures import CancelledError,FIRST_COMPLETED,ThreadPoolExecutor,wait
import copy
import hashlib
import io
import json
import logging
import os
from pathlib import Path,PurePosixPath
import re
import sqlite3
import threading
import time
from urllib.parse import urlsplit,urlunsplit
import uuid
import warnings

from vault_rag.local_state import ConflictError,atomic_write
from vault_rag.platform_support import private_file_mode,is_link
from vault_rag.remote_webdav import RemoteStorageError,remote_path

logger=logging.getLogger(__name__)

SCHEMA='leafloom.asset-library.event.v1'
LIBRARY_SCHEMA='leafloom.asset-library.v1'
MAX_EVENT_BYTES=256*1024
MAX_COVER_BYTES=2*1024*1024
MAX_SYNC_BYTES=256*1024*1024
BACKGROUND_PULL_INTERVAL=30
METADATA_WORKERS=4
REVIEW={'unmatched','needs_review','confirmed','rejected'}
OFFICIAL_FIELDS={'product_id','url','title','publisher','summary_zh','description','categories','keywords',
                 'categories_zh','keywords_zh','compatibility','latest_version','fetched_at','cover_source_url','source_excerpt','summary_status'}


def _bytes(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def _sha(data):return hashlib.sha256(data).hexdigest()
def _pid(value):
    value=str(value or '').removeprefix('unity.assetstore:')
    if not re.fullmatch('[1-9][0-9]{0,17}',value):raise ValueError('Enter an official Asset Store product ID')
    return value
def _text(value,limit):
    if not isinstance(value,str) or len(value)>limit or '\x00' in value:raise ValueError('Invalid asset library text')
    return value
def _filename_version(name):
    match=re.search(r'(?i)(\d+(?:\.\d+){1,3}(?:[abfp]\d+)?)',name)
    return (match[1],'filename') if match else ('','unknown')
def _personal(value):
    if not isinstance(value,dict) or set(value)-{'tags','category','description'}:raise ValueError('Invalid personal metadata')
    result={'tags':value.get('tags',[]),'category':_text(value.get('category',''),200),'description':_text(value.get('description',''),10000)}
    if not isinstance(result['tags'],list) or len(result['tags'])>100:raise ValueError('Invalid asset library tags')
    result['tags']=list(dict.fromkeys(_text(tag,100) for tag in result['tags']))
    return result
def _url(value,product_id='',*,official=False):
    value=_text(value,4096)
    if not value:return ''
    try:
        url=urlsplit(value)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.fragment:raise ValueError()
        if official:
            if url.hostname.lower()!='assetstore.unity.com' or url.port not in {None,443}:raise ValueError()
            match=re.search(r'(?:-|/)([1-9][0-9]*)/?$',url.path)
            if not match or (product_id and match[1]!=product_id):raise ValueError()
    except ValueError:raise ValueError('Use the matching official Asset Store product URL') from None
    return urlunsplit((url.scheme,url.netloc,url.path,'',''))
def _official(value,product_id):
    if not isinstance(value,dict) or set(value)-OFFICIAL_FIELDS:raise ValueError('Invalid official product metadata')
    result=copy.deepcopy(value)
    if value.get('product_id') and _pid(value['product_id'])!=product_id:raise ValueError('Product IDs do not match')
    result['product_id']=product_id
    for key in ('title','publisher','latest_version','summary_status'):
        if key in result:result[key]=_text(result[key],500)
    for key in ('summary_zh','description'):
        if key in result:result[key]=_text(result[key],10000)
    if 'source_excerpt' in result:
        result['source_excerpt']=_text(result['source_excerpt'],1200)
        if len(result['source_excerpt'].split())>180:raise ValueError('Official excerpt is too long')
    for key in ('categories','keywords','categories_zh','keywords_zh'):
        if key in result:
            if not isinstance(result[key],list) or len(result[key])>100:raise ValueError('Invalid product categories or keywords')
            result[key]=list(dict.fromkeys(_text(item,200) for item in result[key]))
    if 'url' in result:result['url']=_url(result['url'],product_id,official=True)
    if 'cover_source_url' in result:result['cover_source_url']=_url(result['cover_source_url'])
    if 'compatibility' in result and (not isinstance(result['compatibility'],(dict,list,str)) or len(_bytes(result['compatibility']))>16384):
        raise ValueError('Invalid product compatibility information')
    if 'fetched_at' in result and result['fetched_at'] is not None and (type(result['fetched_at']) not in {int,float} or result['fetched_at']<0):raise ValueError('Invalid product fetch time')
    return result


class AssetLibrary:
    def __init__(self,remote):
        self.remote=remote;self.lock=threading.RLock();self.sync_lock=threading.Lock()
        self.wake=threading.Event();self.stopped=threading.Event();self.guards={}
        self.discovered={};self.last_pull={};self.on_changed=None;self.active_sync=None
        self.thread=threading.Thread(target=self._loop,daemon=True,name='asset-library-sync');self.thread.start()

    def _root(self,root):return self.remote._root(root)
    def _path(self,*parts):return self.remote._files().state_path('asset-library',*parts)

    @contextmanager
    def _db(self,root):
        self._root(root);path=self._path('library.sqlite');path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if is_link(path):raise ValueError('Asset library cannot be a link')
        for suffix in ('-wal','-shm','-journal'):self._path('library.sqlite'+suffix)
        db=sqlite3.connect(path,timeout=15);db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS files(file_uid TEXT PRIMARY KEY,path TEXT NOT NULL UNIQUE,name TEXT NOT NULL,
                    size INTEGER NOT NULL,mtime TEXT NOT NULL DEFAULT '',etag TEXT NOT NULL DEFAULT '',sha256 TEXT NOT NULL DEFAULT '',
                    asset_id TEXT NOT NULL DEFAULT '',storage_id TEXT NOT NULL DEFAULT '',availability TEXT NOT NULL DEFAULT 'unindexed',exported INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,kind TEXT NOT NULL,entity TEXT NOT NULL,parents TEXT NOT NULL,
                    payload TEXT NOT NULL,data BLOB NOT NULL,sha256 TEXT NOT NULL,synced INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS entities(id TEXT PRIMARY KEY,state TEXT NOT NULL,heads TEXT NOT NULL,revision TEXT NOT NULL,conflicts TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY,kind TEXT NOT NULL,path TEXT NOT NULL,data BLOB NOT NULL,sha256 TEXT NOT NULL,
                    context TEXT NOT NULL,dependencies TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'queued',error TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS receipts(owner TEXT NOT NULL,operation_id TEXT NOT NULL,fingerprint TEXT NOT NULL,target TEXT NOT NULL,
                    PRIMARY KEY(owner,operation_id));
            ''')
            if 'logical_path' not in {row[1] for row in db.execute('PRAGMA table_info(files)')}:
                db.execute("ALTER TABLE files ADD COLUMN logical_path TEXT NOT NULL DEFAULT ''")
            private_file_mode(path);yield db;self._root(root);db.commit()
        except Exception:db.rollback();raise
        finally:db.close()

    @contextmanager
    def _read_db(self,root):
        """Read one committed local projection without queuing behind a sync writer."""
        self._root(root);path=self._path('library.sqlite')
        # A new/older vault still needs its local schema once. Established
        # queries never run DDL or acquire the library's mutation lock.
        ready=False
        if path.is_file():
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=1)) as probe:
                ready='logical_path' in {row[1] for row in probe.execute('PRAGMA table_info(files)')}
        if not ready:
            with self.lock,self._db(root):pass
        for suffix in ('-wal','-shm','-journal'):self._path('library.sqlite'+suffix)
        db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=1);db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            yield db;self._root(root)
        finally:db.rollback();db.close()

    @staticmethod
    def _get(db,key,default=None):
        row=db.execute('SELECT value FROM state WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default
    @staticmethod
    def _set(db,key,value):db.execute('INSERT OR REPLACE INTO state VALUES(?,?)',(key,_bytes(value).decode()))

    def _set_sync(self,db,value):
        # A transient failure or queued retry must not erase the last success.
        previous=self._get(db,'sync',{})
        self._set(db,'sync',{**({key:previous[key] for key in ('last_synced_at',) if key in previous}),**value})

    def settings(self,root,*,db=None):
        self._root(root);path=self._path('settings.json')
        value=json.loads(path.read_text()) if path.exists() else {}
        sources=self.remote._settings(root)['sources'];default=self.remote._settings(root)['default_source']
        bound={}
        if not value.get('storage_id') and self._path('library.sqlite').exists():
            if db is not None:bound=self._get(db,'binding',{})
            else:
                with self._read_db(root) as connection:bound=self._get(connection,'binding',{})
        storage_id=value.get('storage_id') or bound.get('storage_id') or (default if default!='local' else next((s['id'] for s in sources if s.get('enabled',True)),''))
        directory=self.remote._source(storage_id,root)['metadata_directory'] if storage_id else 'Incoming/LeafLoomCatalog/v1'
        return {'storage_id':storage_id,'metadata_directory':directory,'revision':value.get('revision','')}

    def save_settings(self,root,payload,expected_revision=''):
        if not self.sync_lock.acquire(blocking=False):raise ConflictError('Wait for the current asset library synchronization')
        try:return self._save_settings(root,payload,expected_revision)
        finally:self.sync_lock.release()

    def _save_settings(self,root,payload,expected_revision=''):
        if not isinstance(payload,dict) or set(payload)-{'storage_id','metadata_directory','revision'}:raise ValueError('Invalid asset library setting')
        current=self.settings(root)
        if expected_revision and current['revision']!=expected_revision:raise ConflictError('Asset library settings changed')
        storage_id=payload.get('storage_id',current['storage_id']);source=self.remote._source(storage_id,root)
        directory=remote_path(payload.get('metadata_directory',source['metadata_directory']),allow_empty=False)
        with self.lock,self._db(root) as db:
            if self._get(db,'library_id') or db.execute('SELECT 1 FROM outbox LIMIT 1').fetchone():
                if (storage_id,directory)!=(current['storage_id'],current['metadata_directory']):raise ConflictError('An initialized library cannot silently switch its storage or directory')
        if source['metadata_directory']!=directory:
            settings=self.remote._settings(root)
            for item in settings['sources']:
                if item['id']==storage_id:item['metadata_directory']=directory
            self.remote.save(root,settings,settings['revision'])
        value={'storage_id':storage_id,'revision':uuid.uuid4().hex}
        atomic_write(self._path('settings.json'),_bytes(value));private_file_mode(self._path('settings.json'))
        return self.settings(root)

    def _binding(self,root,*,db=None):
        settings=self.settings(root,db=db)
        if not settings['storage_id']:raise ValueError('Select a remote asset library storage')
        source=self.remote._source(settings['storage_id'],root)
        if db is None:
            with self._read_db(root) as connection:bound=self._get(connection,'binding')
        else:bound=self._get(db,'binding')
        if bound and (bound['storage_id'],bound['metadata_directory'])!=(settings['storage_id'],settings['metadata_directory']):
            raise ConflictError('Asset library storage binding changed')
        return settings,source

    def _context(self,root,owner='local'):
        settings,source=self._binding(root);credentials=self.remote.credentials.get(source['id'])
        if not credentials:raise RemoteStorageError('credentials_required','auth_required')
        value={'root':str(root),'owner':owner,'workspace_revision':self.remote.config.data.get('revision',''),
               'source_id':source['id'],'source_revision':self.remote._source_revision(source),'credential_revision':credentials[2],
               'metadata_directory':settings['metadata_directory']}
        self._check(value);return value

    def _check(self,value,*,db=None):
        self._root(value['root'])
        if self.stopped.is_set() or self.remote.stopped.is_set():raise InterruptedError('Asset library stopped')
        if self.remote.config.data.get('revision','')!=value['workspace_revision']:raise PermissionError('Asset library workspace authorization changed')
        settings,source=self._binding(value['root'],db=db);credentials=self.remote.credentials.get(value['source_id'])
        if settings['storage_id']!=value['source_id'] or settings['metadata_directory']!=value['metadata_directory'] or self.remote._source_revision(source)!=value['source_revision']:
            raise PermissionError('Asset library source changed')
        if not credentials:raise RemoteStorageError('credentials_required','auth_required')
        if credentials[2]!=value['credential_revision'] or credentials[3] not in {'local',value['owner']}:raise PermissionError('Asset library credentials changed')
        if value['owner']!='local' and (not callable(self.remote.authorize_owner) or self.remote.authorize_owner(value['root'],value['owner'],value['workspace_revision']) is False):
            raise PermissionError('Asset library owner authorization expired')
        callback=self.guards.get((value['root'],value['owner'],value['workspace_revision']))
        if callback is not None and callback() is False:raise PermissionError('Asset library owner authorization expired')

    def _provider(self,context):
        return self.remote._provider(context['source_id'],context['root'],guard=lambda:self._check(context))

    def initialize(self,root,storage_id='',*,owner='local',guard=None):
        if storage_id:self.save_settings(root,{'storage_id':storage_id})
        if not self._path('settings.json').exists():self.save_settings(root,{'storage_id':self.settings(root)['storage_id']})
        context=self._context(root,owner)
        if guard is not None:
            self.guards[(str(root),owner,context['workspace_revision'])]=guard
            if guard() is False:raise PermissionError('Asset library owner authorization expired')
        with self.lock,self._db(root) as db:
            self._set(db,'requested',context);self._set_sync(db,{'state':'queued'})
        self._discover(root);self.wake.set()
        return {**self.status(root),'state':'queued'}

    def _bootstrap(self,root,provider,context):
        directory=context['metadata_directory'];path=directory+'/library.json'
        try:data=provider.read_bytes(path,max_bytes=16384)
        except RemoteStorageError as error:
            if error.code!='remote_not_found':raise
            provider.ensure_directory(directory)
            marker={'schema':LIBRARY_SCHEMA,'library_id':uuid.uuid4().hex,'locator_schema':'smb-root-relative-v1' if provider.source['type']=='smb' else 'webdav-root-relative-v1','remote_root':provider.source['remote_root']}
            data=_bytes(marker)
            try:provider.put_immutable(path,data,max_bytes=16384)
            except RemoteStorageError as conflict:
                if conflict.code!='immutable_object_conflict':raise
                data=provider.read_bytes(path,max_bytes=16384)
        try:marker=json.loads(data.decode('utf-8'))
        except (ValueError,UnicodeError):raise RemoteStorageError('invalid_asset_library_identity') from None
        if not isinstance(marker,dict) or marker.get('schema')!=LIBRARY_SCHEMA or not re.fullmatch('[0-9a-f]{32}',str(marker.get('library_id',''))):raise RemoteStorageError('invalid_asset_library_identity')
        if marker.get('remote_root')!=provider.source['remote_root']:raise ConflictError('Use the same logical server root for this asset library')
        self._check(context)
        with self.lock,self._db(root) as db:
            old=self._get(db,'library_id')
            if old and old!=marker['library_id']:raise ConflictError('The remote asset library identity changed')
            if not old:db.execute('DELETE FROM files')  # Provisional candidates had no curation or remote identity.
            self._set(db,'library_id',marker['library_id']);self._set(db,'binding',{'storage_id':context['source_id'],'metadata_directory':directory})
            if not self._path('settings.json').exists():
                atomic_write(self._path('settings.json'),_bytes({'storage_id':context['source_id'],'revision':uuid.uuid4().hex}));private_file_mode(self._path('settings.json'))
        return marker['library_id']

    def _discover(self,root,*,blocking=True):
        settings,source=self._binding(root)
        path=self.remote._files().state_path('remote-attachments','manifest.sqlite')
        if not path.is_file():return 0
        # The manifest is already a local, committed snapshot. Reading it must
        # not wait for the remote manager's transfer/scan mutation lock.
        try:
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=1)) as manifest:
                manifest.row_factory=sqlite3.Row
                manifest.execute('PRAGMA query_only=ON');manifest.execute('BEGIN')
                generation=manifest.execute('SELECT generation FROM catalog_state WHERE id=1').fetchone()[0]
                with self._read_db(root) as db:library_id=self._get(db,'library_id') or source['id']
                identity=path.stat()
                token=(source['id'],library_id,settings['metadata_directory'],self.remote.config.data.get('attachment_folder','_attachments'),
                       identity.st_dev,identity.st_ino,generation)
                previous=self.discovered.get(str(root))
                if previous and previous[0]==token:return previous[1]
                manifest_rows=[dict(row) for row in manifest.execute("SELECT a.*,p.logical_path FROM assets a LEFT JOIN (SELECT asset_id,MIN(path) AS logical_path FROM aliases GROUP BY asset_id) p ON p.asset_id=a.id WHERE source_id=? AND lower(a.path) LIKE '%.unitypackage'",(source['id'],))]
        except sqlite3.OperationalError as error:
            if not blocking and ('locked' in str(error).lower() or 'busy' in str(error).lower()):return 0
            raise
        rows=[row for row in manifest_rows if row['state']=='ready']
        known={row['path']:row['state'] for row in manifest_rows}
        if not self.lock.acquire(blocking=blocking):return 0
        try:
            previous=self.discovered.get(str(root))
            if previous and previous[0][:-1]==token[:-1] and previous[0][-1]>=generation:return previous[1]
            with self._db(root) as db:
                # The first remote bootstrap replaces provisional file IDs.
                # Never project a snapshot prepared against the old identity.
                if (self._get(db,'library_id') or source['id'])!=library_id:return 0
                for row in rows:
                    old=db.execute('SELECT * FROM files WHERE path=?',(row['path'],)).fetchone()
                    file_uid=old[0] if old else uuid.uuid5(uuid.UUID(library_id),'package:'+row['path']).hex
                    logical=row['logical_path'] or '/'.join((self.remote.config.data.get('attachment_folder','_attachments'),'_remote',source['id'],row['path']))
                    values=(row['path'],row['name'],row['size'],row['mtime'],row['etag'],row['sha256'],row['id'],source['id'],'ready',logical)
                    if old and tuple(old[key] for key in ('path','name','size','mtime','etag','sha256','asset_id','storage_id','availability','logical_path'))==values:continue
                    db.execute('''INSERT INTO files(file_uid,path,name,size,mtime,etag,sha256,asset_id,storage_id,availability,logical_path)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET name=excluded.name,size=excluded.size,
                        mtime=excluded.mtime,etag=excluded.etag,sha256=excluded.sha256,asset_id=excluded.asset_id,storage_id=excluded.storage_id,
                        availability='ready',logical_path=excluded.logical_path ''',(file_uid,*values))
                for item in db.execute('SELECT file_uid,path,availability FROM files').fetchall():
                    state=known.get(item['path'])
                    availability=state if state in {'missing','excluded'} else 'ready' if state=='ready' else 'unindexed' if item['availability'] in {'ready','unavailable'} else item['availability']
                    if item['availability']!=availability:db.execute('UPDATE files SET availability=? WHERE file_uid=?',(availability,item['file_uid']))
            self.discovered[str(root)]=(token,len(rows))
        finally:self.lock.release()
        return len(rows)

    @staticmethod
    def _default(entity):
        common={'personal':_personal({}),'review':{'status':'needs_review','reason':''}}
        if entity.startswith('file:'):return {**common,'file_uid':entity[5:],'product_id':'','version':'','version_source':'unknown','review':{'status':'unmatched','reason':''}}
        return {**common,'official':{'product_id':entity[8:],'url':'','title':'','publisher':'','summary_zh':'','categories':[],
                                   'keywords':[],'categories_zh':[],'keywords_zh':[],'compatibility':{},'latest_version':'','fetched_at':None,'cover_source_url':''}}

    def _project(self,db):
        grouped={}
        for row in db.execute("SELECT * FROM events WHERE kind='state'"):
            grouped.setdefault(row['entity'],{})[row['id']]={'parents':json.loads(row['parents']),'state':json.loads(row['payload'])}
        db.execute('DELETE FROM entities')
        for entity,events in grouped.items():
            referenced={parent for event in events.values() for parent in event['parents']};heads=sorted(set(events)-referenced)
            incomplete=any(parent not in events for parent in referenced)
            conflicts=[]
            if len(heads)==1 and not incomplete:state=events[heads[0]]['state']
            else:
                state=self._default(entity)
                def ancestors(key):
                    found=set();pending=[key]
                    while pending and len(found)<=20000:
                        current=pending.pop()
                        if current in found:continue
                        found.add(current);pending.extend(events.get(current,{}).get('parents',[]))
                    return found
                shared=set.intersection(*(ancestors(head) for head in heads)) if heads else set()
                bases=shared-{parent for key in shared for parent in events.get(key,{}).get('parents',[])}
                if len(bases)==1 and next(iter(bases)) in events:state=events[next(iter(bases))]['state']
                conflicts=[{'revision':head,'state':events[head]['state']} for head in heads[:100]]
                if incomplete or not heads:conflicts.append({'reason':'incomplete_or_cyclic_history'})
            revision=_sha(_bytes([entity,heads]))
            db.execute('INSERT INTO entities VALUES(?,?,?,?,?)',(entity,_bytes(state).decode(),_bytes(heads).decode(),revision,_bytes(conflicts).decode()))

    def _entity(self,db,entity):
        row=db.execute('SELECT * FROM entities WHERE id=?',(entity,)).fetchone()
        if row:return json.loads(row['state']),json.loads(row['heads']),row['revision'],json.loads(row['conflicts'])
        return self._default(entity),[],_sha(_bytes([entity,[]])),[]

    def _queue(self,db,root,kind,entity,payload,parents,context,dependencies=()):
        library_id=self._get(db,'library_id')
        if not library_id:raise ConflictError('Initialize the remote library before editing metadata')
        event_id=uuid.uuid4().hex
        event={'schema':SCHEMA,'library_id':library_id,'event_id':event_id,'kind':kind,'entity':entity,
               'parents':parents,'payload':payload,'created_at':time.time()}
        data=_bytes(event)
        if len(data)>MAX_EVENT_BYTES:raise ValueError('Asset library event is too large')
        if db.execute('SELECT COALESCE(SUM(length(data)),0) FROM outbox').fetchone()[0]+len(data)>10*1024**3:raise ValueError('Asset library outbox is full')
        path=context['metadata_directory']+'/events/'+event_id[:2]+'/'+event_id+'-'+_sha(data)+'.json'
        db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,0)',(event_id,kind,entity,_bytes(parents).decode(),_bytes(payload).decode(),data,_sha(data)))
        db.execute('INSERT INTO outbox(id,kind,path,data,sha256,context,dependencies) VALUES(?,?,?,?,?,?,?)',
                   (event_id,'event',path,data,_sha(data),_bytes(context).decode(),_bytes(list(dependencies)).decode()))
        return event_id

    def _seed(self,root,context):
        with self.lock,self._db(root) as db:
            rows=[dict(row) for row in db.execute('SELECT * FROM files WHERE exported=0')]
            for offset in range(0,len(rows),50):
                batch=rows[offset:offset+50]
                payload={'files':[{key:row[key] for key in ('file_uid','path','name','size','mtime','etag','sha256')} for row in batch]}
                self._queue(db,root,'file_batch','files',payload,[],context)
                db.executemany('UPDATE files SET exported=1 WHERE file_uid=?',[(row['file_uid'],) for row in batch])

    def _accept(self,db,event,data,synced):
        if len(data)>MAX_EVENT_BYTES or not isinstance(event,dict) or event.get('schema')!=SCHEMA or event.get('library_id')!=self._get(db,'library_id'):
            raise RemoteStorageError('invalid_asset_library_event')
        event_id=event.get('event_id','');kind=event.get('kind');entity=event.get('entity','');parents=event.get('parents',[]);payload=event.get('payload')
        if not re.fullmatch('[0-9a-f]{32}',event_id) or kind not in {'state','file_batch'} or not isinstance(parents,list) or len(parents)>100 or any(not re.fullmatch('[0-9a-f]{32}',str(parent)) for parent in parents):raise RemoteStorageError('invalid_asset_library_event')
        if kind=='state':
            if not re.fullmatch(r'(?:product:[1-9][0-9]{0,17}|file:[0-9a-f]{32})',entity) or not isinstance(payload,dict):raise RemoteStorageError('invalid_asset_library_event')
            self._validate_state(entity,payload)
        else:
            if entity!='files' or parents or not isinstance(payload,dict) or not isinstance(payload.get('files'),list) or len(payload['files'])>100:raise RemoteStorageError('invalid_asset_library_event')
            for item in payload['files']:
                if not isinstance(item,dict) or not re.fullmatch('[0-9a-f]{32}',str(item.get('file_uid',''))) or type(item.get('size')) is not int or item['size']<0:raise RemoteStorageError('invalid_asset_library_event')
                path=remote_path(item.get('path',''),allow_empty=False)
                if not path.lower().endswith('.unitypackage') or _text(item.get('name',''),4096)!=PurePosixPath(path).name:raise RemoteStorageError('invalid_asset_library_event')
                previous=db.execute('SELECT file_uid FROM files WHERE path=?',(path,)).fetchone()
                if previous and previous[0]!=item['file_uid']:raise RemoteStorageError('conflicting_asset_library_file_identity')
                db.execute('INSERT OR IGNORE INTO files(file_uid,path,name,size,mtime,etag,sha256,exported) VALUES(?,?,?,?,?,?,?,1)',
                           (item['file_uid'],path,item['name'],item['size'],_text(item.get('mtime',''),200),_text(item.get('etag',''),1000),_text(item.get('sha256',''),64)))
        previous=db.execute('SELECT sha256 FROM events WHERE id=?',(event_id,)).fetchone()
        if previous and previous[0]!=_sha(data):raise RemoteStorageError('immutable_asset_library_event_changed')
        db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET synced=MAX(events.synced,excluded.synced)',
                   (event_id,kind,entity,_bytes(parents).decode(),_bytes(payload).decode(),data,_sha(data),int(synced)))
        if synced:db.execute('DELETE FROM outbox WHERE id=?',(event_id,))

    def _validate_state(self,entity,state):
        allowed={'personal','review','official'} if entity.startswith('product:') else {'personal','review','file_uid','product_id','version','version_source','evidence'}
        if set(state)-allowed:raise ValueError('Invalid asset library state')
        _personal(state.get('personal',{}));review=state.get('review',{})
        if not isinstance(review,dict) or review.get('status') not in REVIEW:raise ValueError('Invalid asset review state')
        _text(review.get('reason',''),200)
        if set(review)-{'status','reason','proposed_product_id','proposed_url','evidence'}:raise ValueError('Invalid asset review data')
        proposed=_pid(review['proposed_product_id']) if review.get('proposed_product_id') else ''
        if review.get('proposed_url'):_url(review['proposed_url'],proposed,official=True)
        if len(_bytes(review.get('evidence',{})))>16384:raise ValueError('Invalid review evidence')
        if entity.startswith('product:'):
            official=copy.deepcopy(state.get('official',{}));cover=official.pop('cover',None)
            _official(official,entity[8:])
            if cover:
                if not isinstance(cover,dict) or not re.fullmatch('[0-9a-f]{64}',str(cover.get('sha256',''))) or type(cover.get('size')) is not int or not 0<cover['size']<=MAX_COVER_BYTES:
                    raise ValueError('Invalid product cover')
                remote_path(cover.get('path',''),allow_empty=False)
        else:
            if state.get('file_uid')!=entity[5:]:raise ValueError('Invalid file identity')
            if state.get('product_id'):_pid(state['product_id'])
            elif review.get('status')=='confirmed':raise ValueError('A filename candidate requires an explicit product association')
            _text(state.get('version',''),200);_text(state.get('version_source',''),200)
            if len(_bytes(state.get('evidence',{})))>16384:raise ValueError('Invalid product association evidence')

    def _pull(self,root,provider,context):
        directory=context['metadata_directory']+'/events'
        self._check(context)
        try:items=provider.scan(directory,max_files=20000,max_depth=2,prune_reserved=False,read_ignore=False)
        except RemoteStorageError as error:
            if error.code=='remote_not_found':self._check(context);return 0
            raise
        self._check(context)
        with self._read_db(root) as db:
            known={row['id']:row['sha256'] for row in db.execute('SELECT id,sha256 FROM events WHERE synced=1')}
        total=0;count=0
        for index,item in enumerate(items):
            # Known immutable identities need no per-event writer/schema setup.
            # Revalidate authorization in bounded batches, and before every
            # unknown-object read/write regardless of the batch position.
            if index%128==0:self._check(context)
            match=re.fullmatch(re.escape(directory)+r'/([0-9a-f]{2})/([0-9a-f]{32})-([0-9a-f]{64})\.json',item['path'])
            if not match or match[1]!=match[2][:2] or item['size']>MAX_EVENT_BYTES:raise RemoteStorageError('invalid_asset_library_event_path')
            if match[2] in known:
                if known[match[2]]!=match[3]:raise RemoteStorageError('immutable_asset_library_event_changed')
                continue
            self._check(context)
            data=provider.read_bytes(item['path'],max_bytes=MAX_EVENT_BYTES);total+=len(data)
            self._check(context)
            if _sha(data)!=match[3]:raise RemoteStorageError('asset_library_event_checksum_mismatch')
            if total>MAX_SYNC_BYTES:raise RemoteStorageError('asset_library_sync_limit')
            try:event=json.loads(data.decode('utf-8'))
            except (ValueError,UnicodeError):raise RemoteStorageError('invalid_asset_library_event') from None
            if not isinstance(event,dict) or event.get('event_id')!=match[2]:raise RemoteStorageError('invalid_asset_library_event')
            try:
                with self.lock,self._db(root) as db:
                    self._check(context,db=db);self._accept(db,event,data,True);self._check(context,db=db)
            except (ValueError,TypeError,KeyError,OverflowError):raise RemoteStorageError('invalid_asset_library_event') from None
            known[match[2]]=match[3]
            count+=1
        self._check(context)
        with self.lock,self._db(root) as db:
            # A large projection may spill SQLite's page cache and hold an
            # exclusive lock. Read our binding on this same transaction while
            # retaining live source/credential checks before commit.
            self._check(context,db=db);self._project(db);self._check(context,db=db)
        return count

    def _has_sendable(self,root):
        with self._read_db(root) as db:
            rows=[dict(row) for row in db.execute('SELECT id,state,dependencies FROM outbox')]
        pending={row['id'] for row in rows}
        return any(row['state']!='authorization_required' and not any(dependency in pending for dependency in json.loads(row['dependencies'])) for row in rows)

    @staticmethod
    def _same_outbox(current,row):
        return current is not None and all(current[key]==row[key] for key in ('kind','path','sha256','context','dependencies','state'))

    def _ack_outbox(self,root,row,actual):
        value=json.loads(row['context']);self._check(value)
        if actual!=row['sha256']:raise RemoteStorageError('asset_library_readback_mismatch')
        with self.lock,self._db(root) as db:
            current=db.execute('SELECT * FROM outbox WHERE id=?',(row['id'],)).fetchone()
            if not self._same_outbox(current,row):raise ConflictError('Asset library queued authorization changed')
            self._check(value,db=db)
            db.execute('DELETE FROM outbox WHERE id=?',(row['id'],));db.execute('UPDATE events SET synced=1 WHERE id=?',(row['id'],))
            self._check(value,db=db)

    def _outbox_failure(self,root,row,error):
        try:
            with self.lock,self._db(root) as db:
                current=db.execute('SELECT * FROM outbox WHERE id=?',(row['id'],)).fetchone()
                if not self._same_outbox(current,row):return
                if isinstance(error,PermissionError):
                    db.execute("UPDATE outbox SET state='authorization_required',error='owner_or_credentials_changed' WHERE id=?",(row['id'],))
                elif isinstance(error,RemoteStorageError):db.execute('UPDATE outbox SET error=? WHERE id=?',(error.code,row['id']))
        except (ConflictError,ValueError,sqlite3.Error):pass  # Never write into a replacement workspace.

    def _flush(self,root,queued):
        """Bounded metadata-only dispatch; persistent ACKs alone release dependencies."""
        local=threading.local();resources=[];resource_lock=threading.Lock();failed=threading.Event()
        completed=set();first_error=None;pending=list(queued);active={}
        def transfer(row):
            if failed.is_set():raise CancelledError()
            try:
                value=json.loads(row['context']);self._check(value)
                if not hasattr(local,'providers'):
                    local.providers={};local.stack=ExitStack()
                    with resource_lock:resources.append(local.stack)
                key=_sha(_bytes(value))
                if key not in local.providers:
                    provider=self._provider(copy.deepcopy(value));local.stack.enter_context(provider.session())
                    local.providers[key]=(provider,set())
                provider,directories=local.providers[key]
                actual=provider.put_immutable(row['path'],bytes(row['data']),
                    max_bytes=MAX_COVER_BYTES if row['kind']=='cover' else MAX_EVENT_BYTES,verified_directories=directories)
                self._check(value);return actual
            except BaseException:
                failed.set();raise
        try:
            with ThreadPoolExecutor(max_workers=METADATA_WORKERS,thread_name_prefix='asset-metadata') as executor:
                while pending or active:
                    if not failed.is_set() and len(active)<METADATA_WORKERS:
                        with self._read_db(root) as db:outstanding={row[0] for row in db.execute('SELECT id FROM outbox')}
                        for row in list(pending):
                            if failed.is_set() or len(active)>=METADATA_WORKERS:break
                            if row['id'] not in outstanding:
                                pending.remove(row);continue
                            if any(dependency in outstanding for dependency in json.loads(row['dependencies'])):continue
                            pending.remove(row);active[executor.submit(transfer,row)]=row
                    if not active:break
                    done,_=wait(active,return_when=FIRST_COMPLETED)
                    for future in done:
                        row=active.pop(future)
                        try:
                            actual=future.result();self._ack_outbox(root,row,actual);completed.add(row['id'])
                        except CancelledError:pass  # Not started; leave its durable queue entry intact.
                        except BaseException as error:
                            failed.set();first_error=first_error or error;self._outbox_failure(root,row,error)
                if first_error is not None:raise first_error
            return completed
        finally:
            for resource in resources:resource.close()

    def sync(self,root,storage_id='',*,owner='local',guard=None,resume=False,_saved_context=None,_background=False):
        self._root(root)
        if storage_id and storage_id!=self.settings(root)['storage_id']:raise ConflictError('Select the configured asset library storage')
        if not self.sync_lock.acquire(blocking=False):return {**self.status(root),'state':'syncing'}
        sessions=ExitStack();pulled=0
        try:
            context=copy.deepcopy(_saved_context) if _saved_context is not None else self._context(root,owner)
            self._check(context)
            if guard is not None:
                self.guards[(str(root),owner,context['workspace_revision'])]=guard
                if guard() is False:raise PermissionError('Asset library owner authorization expired')
            with self._read_db(root) as db:previous=self._get(db,'sync',{})
            self.active_sync={'context':context,'phase':'connecting','retrying':previous.get('state')=='unreachable','started_at':time.time()}
            provider=self._provider(context)
            sessions.enter_context(provider.session())
            library_id=self._bootstrap(root,provider,context)
            # A verified metadata response supersedes an old transport failure.
            # Persist queued (rather than a fake success or durable running flag)
            # so a crash leaves a truthful, retryable state for the next launch.
            with self.lock,self._db(root) as db:
                self._check(context,db=db);self._set_sync(db,{'state':'queued'})
            self.active_sync={**self.active_sync,'phase':'syncing'}
            fingerprint=_sha(_bytes([context,library_id]));previous=self.last_pull.get(str(root))
            same_checkpoint=previous is not None and previous[0]==fingerprint
            pull_due=not _background or not same_checkpoint or time.monotonic()-previous[1]>=BACKGROUND_PULL_INTERVAL
            # Resume a finite, already-authorized queue before repeating a slow
            # full directory walk. A failed transfer keeps the successful pull
            # checkpoint; first/new-context and explicit syncs still pull first.
            deferred_pull=pull_due and _background and same_checkpoint and self._has_sendable(root)
            if pull_due and not deferred_pull:
                pulled+=self._pull(root,provider,context)
                self.last_pull[str(root)]=(fingerprint,time.monotonic())
            self._discover(root);self._seed(root,context)
            if resume:
                with self.lock,self._db(root) as db:
                    for row in db.execute("SELECT id,context FROM outbox WHERE state='authorization_required'").fetchall():
                        previous=json.loads(row['context'])
                        if previous['owner']==owner and previous['metadata_directory']==context['metadata_directory'] and previous['source_id']==context['source_id']:
                            db.execute("UPDATE outbox SET context=?,state='queued',error='' WHERE id=?",(_bytes(context).decode(),row['id']))
                    requested=self._get(db,'requested')
                    if requested and requested['owner']==owner and requested['source_id']==context['source_id'] and requested['metadata_directory']==context['metadata_directory']:
                        self._set(db,'requested',context)
            with self.lock,self._db(root) as db:queued=[dict(row) for row in db.execute("SELECT * FROM outbox WHERE state!='authorization_required' ORDER BY CASE kind WHEN 'cover' THEN 0 ELSE 1 END,rowid")]
            completed=self._flush(root,queued)
            if deferred_pull:
                pulled+=self._pull(root,provider,context)
                self.last_pull[str(root)]=(fingerprint,time.monotonic())
                self._discover(root)
            with self.lock,self._db(root) as db:self._set_sync(db,{'state':'ready','last_synced_at':time.time()});self._project(db)
            if (pulled or completed) and callable(self.on_changed):
                try:self.on_changed(root)
                except Exception:logger.warning('Asset metadata notification unavailable')
            self.active_sync=None
            return {**self.status(root),'completed':len(completed)}
        except RemoteStorageError as error:
            with self.lock,self._db(root) as db:self._set_sync(db,{'state':error.state,'code':error.code,'reason':error.reason,'operation':error.operation,'checked_at':time.time()})
            self.active_sync=None
            return self.status(root)
        except PermissionError:
            with self.lock,self._db(root) as db:self._set_sync(db,{'state':'authorization_required','code':'owner_or_credentials_changed'})
            self.active_sync=None
            return self.status(root)
        finally:
            self.active_sync=None
            try:sessions.close()
            finally:self.sync_lock.release()

    def rebuild(self,root,*,owner='local',guard=None):
        return self.sync(root,owner=owner,guard=guard)

    def _items(self,root,include_unavailable=False):
        self._discover(root,blocking=False)
        with self._read_db(root) as db:
            files=[dict(row) for row in db.execute('SELECT * FROM files')]
            state={row['id']:(json.loads(row['state']),row['revision'],json.loads(row['conflicts'])) for row in db.execute('SELECT * FROM entities')}
            pending_rows=db.execute('SELECT kind,entity,payload FROM events WHERE synced=0').fetchall()
            pending={row['entity'] for row in pending_rows}
            pending_file_uids={file['file_uid'] for row in pending_rows if row['kind']=='file_batch'
                               for file in json.loads(row['payload'])['files']}
            initialized=bool(self._get(db,'library_id'))
        products={entity[8:] for entity in state if entity.startswith('product:')};grouped={};candidates=[]
        for file in files:
            entity='file:'+file['file_uid'];value,revision,conflicts=state.get(entity,(self._default(entity),_sha(_bytes([entity,[]])),[]))
            product_id=value.get('product_id','') if not conflicts else ''
            guessed,guess_source=_filename_version(file['name'])
            file={**file,'remote_path':file['path'],'path':file['logical_path'] or file['path'],
                  'version':value.get('version') or guessed,'version_source':value.get('version_source','unknown') if value.get('version') else guess_source}
            available=file['availability'] in {'ready','unindexed'}
            if product_id:products.add(product_id);grouped.setdefault(product_id,[]).append(file)
            elif available or include_unavailable:
                candidate_id='candidate:'+file['file_uid']
                candidates.append({'id':candidate_id,'kind':'candidate','candidate_id':candidate_id,'product_id':'','title':file['name'],
                                   'revision':revision,'official':self._default('product:1')['official']|{'product_id':''},
                                   'personal':value['personal'],'review':value['review'],'files':[file] if available else [],'conflicts':conflicts,
                                   'sync_state':'conflict' if conflicts else 'pending' if entity in pending or file['file_uid'] in pending_file_uids else 'synced' if initialized else 'local_only'})
        items=[]
        for product_id in products:
            entity='product:'+product_id;value,revision,conflicts=state.get(entity,(self._default(entity),_sha(_bytes([entity,[]])),[]))
            related=grouped.get(product_id,[])
            is_pending=entity in pending or any('file:'+file['file_uid'] in pending or file['file_uid'] in pending_file_uids for file in related)
            items.append({'id':'unity.assetstore:'+product_id,'kind':'product','candidate_id':'','product_id':product_id,
                          'title':value['official'].get('title') or 'Product '+product_id,'revision':revision,'official':value['official'],
                          'personal':value['personal'],'review':value['review'],'files':[file for file in related if file['availability'] in {'ready','unindexed'}],'conflicts':conflicts,
                          'sync_state':'conflict' if conflicts else 'pending' if is_pending else 'synced' if initialized else 'local_only'})
        return sorted(items+candidates,key=lambda item:(item['title'].casefold(),item['id']))

    def listing(self,root,query='',status='',limit=100,cursor=''):
        _text(query,500)
        if status and status not in REVIEW|{'conflict','pending','product','candidate'}:raise ValueError('Invalid asset library filter')
        if type(limit)is not int:raise ValueError('Invalid asset library page size')
        limit=max(1,min(limit,500));items=self._items(root)
        if query:
            needle=query.casefold();items=[item for item in items if needle in _bytes(item).decode().casefold()]
        if status:items=[item for item in items if status in {item['review']['status'],item['sync_state'],item['kind']}]
        related=[file for item in items for file in item['files']]
        summary={'products':sum(item['kind']=='product' for item in items),'candidates':sum(item['kind']=='candidate' for item in items),
                 'files':sum(file['availability']=='ready' for file in related),'bytes':sum(file['size'] for file in related if file['availability']=='ready'),
                 'metadata_known':sum(file['availability']=='unindexed' for file in related)}
        revision=_sha(_bytes([(item['id'],item['revision'],item['sync_state'],[(file['file_uid'],file['availability'],file['size']) for file in item['files']]) for item in items]))
        offset=0
        if cursor:
            match=re.fullmatch(r'([0-9a-f]{64}):(\d+)',cursor)
            if not match or match[1]!=revision:raise ConflictError('Asset library changed; restart from the first page')
            offset=int(match[2])
        return {'items':items[offset:offset+limit],'total':len(items),'next_cursor':revision+':'+str(offset+limit) if offset+limit<len(items) else '',
                'revision':revision,'query':query,'summary':summary}

    def detail(self,root,product_id):
        target=str(product_id)
        if target.isdecimal():target='unity.assetstore:'+_pid(target)
        for item in self._items(root,include_unavailable=True):
            if item['id']==target:return item
        raise FileNotFoundError('Asset library entry not found')

    def collection_identity(self,root,file_uid):
        """Read a collector checkpoint identity without file paths or credentials."""
        if not isinstance(file_uid,str) or not re.fullmatch('[0-9a-f]{32}',file_uid):raise ValueError('Invalid package identity')
        self._discover(root)
        with self._read_db(root) as db:
            file=db.execute('SELECT availability FROM files WHERE file_uid=?',(file_uid,)).fetchone()
            if file is None:return None
            value,_,_,conflicts=self._entity(db,'file:'+file_uid)
            product_id=value.get('product_id','');official={};product_conflicts=[]
            if product_id:
                product,_,_,product_conflicts=self._entity(db,'product:'+product_id)
                official={key:product['official'].get(key,'') for key in ('product_id','url','title','publisher')}
            evidence=value.get('evidence',{})
            if not isinstance(evidence,dict):evidence={}
            try:evidence_url=_url(evidence.get('url',''),product_id,official=True)
            except ValueError:evidence_url=''
            return {'file_uid':file_uid,'availability':file['availability'],'product_id':product_id,
                    'official':official,'conflict':bool(conflicts or product_conflicts),
                    'evidence':{'method':'official_title_publisher' if evidence.get('method')=='official_title_publisher' else '',
                                'url':evidence_url}}

    def update(self,root,operation,payload=None,*,owner='local',operation_id='',expected_revision=''):
        payload={} if payload is None else payload
        if not isinstance(payload,dict):raise ValueError('Invalid asset library update')
        if operation not in {'bind','official_url','official','personal','review','resolve'}:raise ValueError('Invalid asset library operation')
        self._discover(root);context=self._context(root,owner)
        fingerprint=_sha(_bytes([operation,payload,expected_revision]));operation_id=operation_id or uuid.uuid4().hex
        _text(operation_id,512)
        with self.lock,self._db(root) as db:
            if not self._get(db,'library_id'):raise ConflictError('Wait for asset library initialization')
            receipt=db.execute('SELECT * FROM receipts WHERE owner=? AND operation_id=?',(owner,operation_id)).fetchone()
            if receipt:
                if receipt['fingerprint']!=fingerprint:raise ConflictError('Operation ID was already used with different data')
                target=receipt['target']
            else:
                self._project(db)
                target=payload.get('id') or payload.get('candidate_id') or payload.get('product_id','')
                candidate_uid=target.removeprefix('candidate:') if str(target).startswith('candidate:') else ''
                file=None
                if payload.get('asset_id'):file=db.execute('SELECT * FROM files WHERE asset_id=?',(payload['asset_id'],)).fetchone()
                elif candidate_uid:file=db.execute('SELECT * FROM files WHERE file_uid=?',(candidate_uid,)).fetchone()
                if operation=='bind':
                    if not file:raise FileNotFoundError('Unity package candidate not found')
                    product_id=_pid(payload.get('product_id'));entity='file:'+file['file_uid'];value,heads,revision,conflicts=self._entity(db,entity)
                    if expected_revision and expected_revision!=revision:raise ConflictError('Asset library entry changed')
                    if conflicts:raise ConflictError('Resolve the conflicting file association first')
                    guessed,guess_source=_filename_version(file['name'])
                    version=payload.get('version',value.get('version') or guessed)
                    version_source=payload.get('version_source',('manual' if payload.get('version') else value.get('version_source','unknown') if value.get('version') else guess_source))
                    value.update(product_id=product_id,version=_text(version,200),version_source=_text(version_source,200))
                    value['evidence']=payload.get('evidence',{});value['review']={'status':'needs_review','reason':''}
                    self._validate_state(entity,value);self._queue(db,root,'state',entity,value,heads,context)
                    target='unity.assetstore:'+product_id
                    if operation=='bind':
                        db.execute('INSERT INTO receipts VALUES(?,?,?,?)',(owner,operation_id,fingerprint,target));self._project(db)
                        # No official fields are inferred from the filename.
                        result_target=target
                    else:result_target=None
                else:result_target=None
                if result_target is None:
                    if file and operation in {'personal','review','resolve','official_url'}:entity='file:'+file['file_uid'];target='candidate:'+file['file_uid']
                    else:product_id=_pid(payload.get('product_id') or str(target));entity='product:'+product_id;target='unity.assetstore:'+product_id
                    value,heads,revision,conflicts=self._entity(db,entity)
                    if expected_revision and expected_revision!=revision:raise ConflictError('Asset library entry changed')
                    if conflicts and operation!='resolve':raise ConflictError('Resolve the conflicting library revisions first')
                    if operation=='resolve':
                        chosen=payload.get('revision');row=db.execute('SELECT payload FROM events WHERE id=? AND entity=?',(chosen,entity)).fetchone()
                        if not row or chosen not in heads:raise ValueError('Select an existing conflicting revision')
                        value=json.loads(row[0])
                    elif operation=='personal':value['personal']=_personal({**value['personal'],**payload.get('personal',{})})
                    elif operation=='review':
                        status=payload.get('status')
                        if status not in REVIEW or (entity.startswith('file:') and not value.get('product_id') and status=='confirmed'):raise ValueError('A filename candidate cannot be confirmed without an official ID')
                        value['review']={'status':status,'reason':_text(payload.get('reason',''),200)}
                        for key in ('proposed_product_id','proposed_url','evidence'):
                            if key in payload:value['review'][key]=copy.deepcopy(payload[key])
                        if value['review'].get('proposed_product_id'):value['review']['proposed_product_id']=_pid(value['review']['proposed_product_id'])
                    elif operation=='official_url' and file:
                        proposed=_pid(payload.get('product_id'))
                        value['review']={'status':'needs_review','reason':'official_identity_requires_confirmation',
                                         'proposed_product_id':proposed,'proposed_url':_url(payload.get('url',''),proposed,official=True)}
                    else:
                        incoming={'product_id':product_id,'url':payload['url']} if operation=='official_url' else payload.get('official',{})
                        value['official'].update(_official(incoming,product_id))
                    self._validate_state(entity,value);self._queue(db,root,'state',entity,value,heads,context)
                    db.execute('INSERT INTO receipts VALUES(?,?,?,?)',(owner,operation_id,fingerprint,target));self._project(db)
        self.wake.set();return self.detail(root,target)

    def store_cover(self,root,product_id,local_path,source_url,expected_revision='',owner='local'):
        from PIL import Image,ImageOps
        product_id=_pid(product_id);context=self._context(root,owner);source=Path(local_path)
        if is_link(source) or not source.is_file() or source.stat().st_size>8*1024*1024:raise ValueError('Invalid product cover image')
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with os.fdopen(os.open(source,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)),'rb') as stream,Image.open(stream) as image:
                if image.width*image.height>32_000_000:raise ValueError('Product cover image is too large')
                image.seek(0);image=ImageOps.exif_transpose(image);image.thumbnail((512,512));image=image.convert('RGB')
                output=io.BytesIO();image.save(output,'WEBP',quality=85);data=output.getvalue()
        if len(data)>MAX_COVER_BYTES:raise ValueError('Product cover image is too large')
        digest=_sha(data);path=context['metadata_directory']+'/media/'+digest+'.webp'
        self._check(context)
        with self.lock,self._db(root) as db:
            self._project(db);entity='product:'+product_id;value,heads,revision,conflicts=self._entity(db,entity)
            if expected_revision and expected_revision!=revision:raise ConflictError('Product metadata changed')
            if conflicts:raise ConflictError('Resolve the conflicting product metadata first')
            dependency='cover:'+digest
            db.execute('INSERT OR IGNORE INTO outbox(id,kind,path,data,sha256,context,dependencies) VALUES(?,?,?,?,?,?,?)',
                       (dependency,'cover',path,data,digest,_bytes(context).decode(),'[]'))
            value['official']['cover']={'path':path,'sha256':digest,'size':len(data),'mime':'image/webp'}
            value['official']['cover_source_url']=_url(source_url)
            self._validate_state(entity,value);self._queue(db,root,'state',entity,value,heads,context,[dependency]);self._project(db)
        directory=self._path('covers');directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        atomic_write(directory/(digest+'.webp'),data);self.wake.set();return self.detail(root,product_id)

    def cover(self,root,product_id):
        item=self.detail(root,product_id);cover=item['official'].get('cover')
        if not cover:raise FileNotFoundError('Product cover is unavailable')
        settings,_=self._binding(root);expected=settings['metadata_directory']+'/media/'+cover['sha256']+'.webp'
        if cover['path']!=expected:raise ValueError('Product cover is outside the metadata namespace')
        path=self._path('covers',cover['sha256']+'.webp')
        if path.is_file() and not is_link(path) and _sha(path.read_bytes())==cover['sha256']:return path
        context=self._context(root);data=self._provider(context).read_bytes(expected,max_bytes=MAX_COVER_BYTES)
        if len(data)!=cover['size'] or _sha(data)!=cover['sha256']:raise RemoteStorageError('product_cover_checksum_mismatch')
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);atomic_write(path,data);return path

    def status(self,root):
        settings=self.settings(root)
        with self._read_db(root) as db:
            state=self._get(db,'sync',{'state':'uninitialized'});library_id=self._get(db,'library_id','')
            counts={row[0]:row[1] for row in db.execute('SELECT state,COUNT(*) FROM outbox GROUP BY state')}
            files=db.execute('SELECT COUNT(*) FROM files').fetchone()[0]
            conflicts=sum(bool(json.loads(row[0])) for row in db.execute('SELECT conflicts FROM entities'))
            pending_bytes=db.execute('SELECT COALESCE(SUM(length(data)),0) FROM outbox').fetchone()[0]
            active=self.active_sync
            if active and active['context']['root']==str(root):
                try:self._check(active['context'],db=db)
                except (ConflictError,PermissionError,RemoteStorageError,InterruptedError,ValueError):pass
                else:
                    state={**{key:state[key] for key in ('last_synced_at',) if key in state},
                           'state':'syncing','phase':active['phase'],'retrying':active['retrying'],'sync_started_at':active['started_at']}
        return {**settings,**state,'library_id':library_id,'initialized':bool(library_id),'pending':sum(counts.values()),'outbox':counts,
                'pending_bytes':pending_bytes,'files':files,'conflicts':conflicts}

    def _loop(self):
        while not self.stopped.is_set():
            self.wake.wait(30);self.wake.clear()
            if self.stopped.is_set():break
            try:
                root=self.remote._root()
                if not self._path('library.sqlite').is_file():continue
                with self.lock,self._db(root) as db:requested=self._get(db,'requested',None)
                if requested:
                    self._check(requested)
                    self.sync(root,owner=requested['owner'],_saved_context=requested,_background=True)
            except Exception as error:
                if isinstance(error,InterruptedError) and (self.stopped.is_set() or self.remote.stopped.is_set()):break
                position='_loop';trace=error.__traceback__
                while trace is not None:
                    if trace.tb_frame.f_code.co_filename==__file__:position=f'{trace.tb_frame.f_code.co_name}:{trace.tb_lineno}'
                    trace=trace.tb_next
                logger.warning('Asset library background failure type=%s location=%s',type(error).__name__,position)
                try:
                    if isinstance(error,RemoteStorageError):state,code=error.state,error.code
                    elif isinstance(error,PermissionError):state,code='authorization_required','owner_or_credentials_changed'
                    elif isinstance(error,ConflictError):state,code='conflict','library_binding_changed'
                    else:state,code='invalid_service','asset_library_operation_failed'
                    with self.lock,self._db(root) as db:self._set_sync(db,{'state':state,'code':code,'reason':getattr(error,'reason',''),'operation':getattr(error,'operation',''),'checked_at':time.time()})
                except Exception:pass

    def stop(self):
        self.stopped.set();self.wake.set();self.thread.join(timeout=2)
