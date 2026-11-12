"""Durable attachment identities, WebDAV storage, disposable cache and outbox.

The manifest is user data, separate from rebuildable attachment indexes. Remote
files are never imported into note/RAG scopes. Credentials live only in memory.
All methods are synchronous so HTTP handlers can use asyncio.to_thread.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import email.utils
import hashlib
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat as statlib
import threading
import time
import uuid

from vault_rag.local_state import ConflictError, Files, atomic_write, relative, under
from vault_rag.platform_support import is_link, path_key, private_file_mode, move_exclusive
from vault_rag.remote_webdav import RemoteStorageError, WebDAVSource, remote_path, validate_source
from vault_rag.attachment_scan_policy import SCAN_INTERVAL, STARTUP_GRACE, retry_interval, in_scan_scope, register_scan_scope
from vault_rag.remote_ignore import RemoteIgnore
from vault_rag.attachment_policy import AttachmentTypeError, DEFAULT_EXTENSIONS, allows, extensions_for, normalize_extensions, register_policy, require_allowed


CACHE_DEFAULT = 2 * 1024**3
OUTBOX_DEFAULT = 10 * 1024**3
_PENDING = {'queued','waiting_for_connection','waiting_for_auth','waiting_for_authorization','uploading','verifying'}
_JSON_SETTINGS = {'revision','root','sources','default_source','cache_max_bytes','outbox_max_bytes','allowed_extensions'}


def _json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def _version(info):
    return [info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns]


def _mtime_ns(value):
    value=str(value or '')
    try:return int(value) if value.isdecimal() else int(email.utils.parsedate_to_datetime(value).timestamp()*1_000_000_000)
    except (ValueError,TypeError,OverflowError):return 0


def _remote_version(value):
    return (int(value['size']),value.get('etag',''),_mtime_ns(value.get('mtime','')))


def _hash_file(path):
    descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
    with os.fdopen(descriptor,'rb') as stream:
        before=os.fstat(stream.fileno())
        if not statlib.S_ISREG(before.st_mode):raise ValueError('Attachment must be a regular file')
        digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if _version(os.fstat(stream.fileno()))!=_version(before):raise ConflictError('Attachment changed while reading')
    return digest,_version(before)


class RemoteAttachments:
    def __init__(self,config,runtime=None):
        self.config=config;self.runtime=runtime
        self.lock=threading.RLock();self.worker_lock=threading.Lock()
        self.credentials={};self.guards={};self.connections={};self.transports={}
        self.recovery_states={}
        self.poll_cursor=0
        self.cancelled=set()
        self.cache_ttl=60
        self.cache_checks={}
        self.cache_lock=threading.RLock()
        self.cache_checked={}
        self.cache_readers={}
        self.cache_deletions={}
        self.scan_threads={}
        self.scan_locks={}
        self.scan_statuses={}
        self.scan_publish_at={}
        self.auto_scans={}
        self.on_scan_completed=None;self.on_connection_ready=None
        self.asset_locks={}
        self.redirect_backfilled=set();self.schema_ready={}
        # Assigned by the router. A nonlocal owner must still be authorized now,
        # including after restart; neither a persisted owner nor a token is enough.
        self.authorize_owner=None
        self.stopped=threading.Event();self.wake=threading.Event()
        self.thread=threading.Thread(target=self._loop,daemon=True,name='remote-attachment-outbox')
        self.thread.start()

    def _root(self,root=None):
        current=str(self.config.root)
        if root is not None and str(root)!=current:raise ConflictError('Connected attachment folder changed')
        return current

    def _files(self):
        # LocalConfig.save atomically replaces data. Taking its immutable
        # snapshot without config.lock avoids a lock inversion with MCP callers
        # that already hold config.lock before entering this manager.
        config=copy.copy(self.config);config.data=copy.deepcopy(self.config.data)
        return Files(config)

    def _settings(self,root=None):
        root=self._root(root);path=self._state('settings.json')
        if path.exists():
            value=json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(value,dict) or set(value)-_JSON_SETTINGS or value.get('root')!=root:
                raise ValueError('Attachment storage settings belong to another folder')
        else:
            value=self.config.data.get('remote_attachments',{})
            if value.get('root')!=root:value={}
        return {'root':root,'revision':value.get('revision',''), 'sources':copy.deepcopy(value.get('sources',[])),
                'default_source':value.get('default_source','local'),
                'allowed_extensions':normalize_extensions(value.get('allowed_extensions',list(DEFAULT_EXTENSIONS))),
                'cache_max_bytes':value.get('cache_max_bytes',CACHE_DEFAULT),
                'outbox_max_bytes':value.get('outbox_max_bytes',OUTBOX_DEFAULT)}

    def _state(self,*parts):
        return self._files().state_path('remote-attachments',*parts)

    def manifest_path(self,root=None):
        """Durable catalog database, suitable for a read-only SQLite ATTACH."""
        self._root(root)
        with self.lock,self._db(root):pass
        return self._state('manifest.sqlite')

    @contextmanager
    def _db(self,root=None):
        expected=self._root(root);files=self._files()
        if str(files.config.root)!=expected:raise ConflictError('Connected attachment folder changed')
        directory=files.state_path('remote-attachments');directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        path=files.state_path('remote-attachments','manifest.sqlite')
        for suffix in ('-wal','-shm','-journal'):files.state_path('remote-attachments','manifest.sqlite'+suffix)
        connection=sqlite3.connect(path,timeout=15)
        connection.row_factory=sqlite3.Row
        try:
            connection.execute('PRAGMA foreign_keys=ON');connection.execute('PRAGMA synchronous=FULL')
            version=connection.execute('PRAGMA user_version').fetchone()[0]
            if version>1:raise ValueError('Attachment manifest belongs to a newer version')
            identity=(path.stat().st_dev,path.stat().st_ino)
            prepare=self.schema_ready.get(str(path))!=identity or version!=1
            if prepare:
                connection.executescript('''
                    CREATE TABLE IF NOT EXISTS sync_checkpoints(source_id TEXT PRIMARY KEY, source_revision TEXT NOT NULL, last_success REAL NOT NULL);
                    CREATE TABLE IF NOT EXISTS discovery_changes(source_id TEXT NOT NULL,path TEXT NOT NULL,changed_at REAL NOT NULL,PRIMARY KEY(source_id,path));
                    CREATE TABLE IF NOT EXISTS scan_retries(source_id TEXT PRIMARY KEY,context TEXT NOT NULL,failures INTEGER NOT NULL,next_retry_at REAL NOT NULL);
                    CREATE TABLE IF NOT EXISTS assets(
                        id TEXT PRIMARY KEY,source_id TEXT NOT NULL,path TEXT NOT NULL,name TEXT NOT NULL,
                        size INTEGER NOT NULL,mtime TEXT NOT NULL DEFAULT '',etag TEXT NOT NULL DEFAULT '',
                        mime TEXT NOT NULL,sha256 TEXT NOT NULL DEFAULT '',state TEXT NOT NULL DEFAULT 'ready',
                        description TEXT NOT NULL DEFAULT '',tags TEXT NOT NULL DEFAULT '[]',category TEXT NOT NULL DEFAULT '',
                        metadata_revision TEXT NOT NULL,updated REAL NOT NULL,UNIQUE(source_id,path));
                    CREATE TABLE IF NOT EXISTS aliases(path TEXT PRIMARY KEY,asset_id TEXT NOT NULL REFERENCES assets(id));
                    CREATE TABLE IF NOT EXISTS reference_ids(old_id TEXT PRIMARY KEY,asset_id TEXT NOT NULL REFERENCES assets(id));
                    CREATE TABLE IF NOT EXISTS reference_records(digest TEXT PRIMARY KEY,data BLOB NOT NULL);
                    CREATE TABLE IF NOT EXISTS asset_redirects(old_id TEXT PRIMARY KEY REFERENCES assets(id),
                        new_id TEXT NOT NULL REFERENCES assets(id),source_path TEXT NOT NULL,job_id TEXT NOT NULL,
                        active INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,CHECK(old_id!=new_id));
                    CREATE TABLE IF NOT EXISTS cache(asset_id TEXT PRIMARY KEY REFERENCES assets(id),file TEXT NOT NULL,
                        size INTEGER NOT NULL,sha256 TEXT NOT NULL,etag TEXT NOT NULL,mtime TEXT NOT NULL,accessed REAL NOT NULL);
                    CREATE TABLE IF NOT EXISTS ranges(asset_id TEXT NOT NULL REFERENCES assets(id),start INTEGER NOT NULL,end INTEGER NOT NULL,
                        file TEXT NOT NULL,size INTEGER NOT NULL,object_size INTEGER NOT NULL,sha256 TEXT NOT NULL,etag TEXT NOT NULL,mtime TEXT NOT NULL,
                        accessed REAL NOT NULL,verified REAL NOT NULL,identity TEXT NOT NULL,PRIMARY KEY(asset_id,start,end));
                    CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,state TEXT NOT NULL,payload TEXT NOT NULL,
                        created REAL NOT NULL,updated REAL NOT NULL);
                    CREATE TABLE IF NOT EXISTS upload_receipts(owner TEXT NOT NULL,operation_key TEXT NOT NULL,
                        fingerprint TEXT NOT NULL,job_id TEXT NOT NULL REFERENCES jobs(id),PRIMARY KEY(owner,operation_key));
                    CREATE TABLE IF NOT EXISTS connection_recovery(source_id TEXT PRIMARY KEY,source_revision TEXT NOT NULL,
                        credential_revision TEXT NOT NULL,payload TEXT NOT NULL);
                    CREATE INDEX IF NOT EXISTS remote_assets_name ON assets(name);
                    CREATE INDEX IF NOT EXISTS remote_jobs_state ON jobs(state);
                    CREATE TABLE IF NOT EXISTS catalog_state(id INTEGER PRIMARY KEY CHECK(id=1),generation INTEGER NOT NULL);
                    INSERT OR IGNORE INTO catalog_state VALUES(1,0);
                    PRAGMA user_version=1;
                ''')
                columns={r[1] for r in connection.execute('PRAGMA table_info(assets)')}
                if 'mtime_ns' not in columns:connection.execute('ALTER TABLE assets ADD COLUMN mtime_ns INTEGER NOT NULL DEFAULT 0')
                if 'reconcile_revision' not in columns:connection.execute('ALTER TABLE assets ADD COLUMN reconcile_revision INTEGER NOT NULL DEFAULT 0')
                if 'content_generation' not in columns:connection.execute('ALTER TABLE assets ADD COLUMN content_generation INTEGER NOT NULL DEFAULT 0')
                connection.execute('''CREATE TRIGGER IF NOT EXISTS remote_asset_reconcile_revision AFTER UPDATE ON assets
                    WHEN NEW.reconcile_revision=OLD.reconcile_revision BEGIN
                    UPDATE assets SET reconcile_revision=reconcile_revision+1 WHERE id=NEW.id; END''')
                cache_columns={r[1] for r in connection.execute('PRAGMA table_info(cache)')}
                if 'verified' not in cache_columns:connection.execute('ALTER TABLE cache ADD COLUMN verified REAL NOT NULL DEFAULT 0')
                if 'identity' not in cache_columns:connection.execute("ALTER TABLE cache ADD COLUMN identity TEXT NOT NULL DEFAULT ''")
                for table in ('assets','aliases','cache','ranges','asset_redirects','reference_ids'):
                    for action in ('INSERT','UPDATE','DELETE'):
                        connection.execute(f'CREATE TRIGGER IF NOT EXISTS catalog_{table}_{action.lower()} AFTER {action} ON {table} BEGIN UPDATE catalog_state SET generation=generation+1 WHERE id=1; END')
            private_file_mode(path)
            backfill=expected not in self.redirect_backfilled
            if backfill:self._backfill_redirects(connection,expected)
            yield connection
            self._root(expected)
            connection.commit()
            if prepare:self.schema_ready[str(path)]=identity
            if backfill:self.redirect_backfilled.add(expected)
        except Exception:
            connection.rollback();raise
        finally:connection.close()

    def _record_redirect(self,db,old_id,new_id,path,job_id,*,active=False):
        if old_id==new_id:return
        previous=db.execute('SELECT new_id FROM asset_redirects WHERE old_id=?',(old_id,)).fetchone()
        if previous and previous[0]!=new_id:raise ConflictError('Attachment identity already has a different migration target')
        current=new_id;seen={old_id}
        for _ in range(32):
            if current in seen:raise ConflictError('Attachment identity redirect cycle')
            seen.add(current);next_row=db.execute('SELECT new_id FROM asset_redirects WHERE old_id=?',(current,)).fetchone()
            if not next_row:break
            current=next_row[0]
        else:raise ConflictError('Attachment identity redirect chain is too long')
        db.execute('INSERT INTO asset_redirects VALUES(?,?,?,?,?,?) ON CONFLICT(old_id) DO UPDATE SET active=MAX(asset_redirects.active,excluded.active)',
                   (old_id,new_id,path,job_id,int(active),time.time()))
        if active:self._activate_redirects(db,new_id)

    @staticmethod
    def _activate_redirects(db,target_id):
        for row in db.execute('SELECT old_id FROM asset_redirects WHERE new_id=?',(target_id,)).fetchall():
            # A hidden local tombstone preserves the old ID without consuming
            # the original path or appearing in either catalog source branch.
            db.execute("UPDATE assets SET path=?,state='redirected',updated=? WHERE id=? AND source_id='local'",
                       ('.retired-assets/'+row[0],time.time(),row[0]))
        db.execute('UPDATE asset_redirects SET active=1 WHERE new_id=?',(target_id,))

    def _backfill_redirects(self,db,root):
        evidence={};changed=0;skipped=0
        for row in db.execute("SELECT payload FROM jobs WHERE kind='migration'").fetchall():
            job=json.loads(row[0])
            if job.get('root')!=str(root):continue
            for item in job.get('items',[]):
                if item.get('state')!='released':continue
                target=db.execute('SELECT * FROM assets WHERE id=?',(item.get('asset_id',''),)).fetchone()
                if (not target or target['source_id']!=job.get('source_id') or target['path']!=item.get('remote_path') or
                        target['sha256']!=item.get('sha256') or target['size']!=item.get('size') or target['state']!='ready'):continue
                evidence.setdefault(item.get('path',''),[]).append((job,item,target))
        for path,entries in evidence.items():
            old=db.execute("SELECT * FROM assets WHERE source_id='local' AND path=? AND state!='redirected'",(path,)).fetchone()
            if not old or db.execute('SELECT 1 FROM asset_redirects WHERE old_id=?',(old['id'],)).fetchone():continue
            if len({entry[2]['id'] for entry in entries})!=1:skipped+=1;continue
            job,item,target=entries[0];version=item.get('source_version',[])
            alias=db.execute('SELECT asset_id FROM aliases WHERE path=?',(path,)).fetchone()
            try:exists=self.config.path_for(path).exists()
            except (ValueError,OSError):exists=True
            if (exists or not alias or alias[0]!=target['id'] or len(version)!=4 or
                    old['size']!=version[2] or old['mtime']!=str(version[3])):
                skipped+=1;continue
            self._record_redirect(db,old['id'],target['id'],path,job['id'],active=True);changed+=1
        return {'redirected':changed,'skipped':skipped}

    def backfill_asset_redirects(self,root):
        """Repair only unambiguous released journals; never read remote bytes."""
        self._root(root)
        with self.lock,self._db(root) as db:return self._backfill_redirects(db,root)

    def _source(self,source_id,root=None):
        if source_id=='local':return {'id':'local','type':'local','name':'Local','enabled':True}
        for source in self._settings(root)['sources']:
            if source['id']==source_id and source.get('enabled',True):return validate_source(source)
        raise ValueError('Attachment source is unavailable')

    @staticmethod
    def _source_revision(source):
        # Metadata namespace is guarded separately by AssetLibrary. Adding its
        # default must not invalidate existing attachment transfer journals.
        return hashlib.sha256(_json({k:v for k,v in source.items() if k not in {'metadata_directory','scan_roots','scan_paused','membership_mode'}}).encode()).hexdigest()

    def save(self,root,payload,revision=None):
        self._root(root)
        if not isinstance(payload,dict) or set(payload)-_JSON_SETTINGS:raise ValueError('Unsupported attachment storage setting')
        sources=payload.get('sources',[])
        if not isinstance(sources,list) or len(sources)>32:raise ValueError('Too many attachment sources')
        sources=[validate_source(source) for source in sources]
        if len({s['id'] for s in sources})!=len(sources):raise ValueError('Duplicate attachment source ID')
        expected=revision if revision is not None else payload.get('revision')
        with self.config.lock,self.lock:
            values=self._settings(root)
            if expected is not None and expected!=values['revision']:raise ConflictError('Attachment storage settings changed')
            removed={s['id'] for s in values['sources']}-{s['id'] for s in sources}
            with self._db(root) as db:
                for source_id in removed:
                    if db.execute('SELECT 1 FROM assets WHERE source_id=? LIMIT 1',(source_id,)).fetchone():
                        raise ConflictError('Disable a source while its attachment catalog is retained')
                    if any(json.loads(r[0]).get('source_id')==source_id for r in db.execute('SELECT payload FROM jobs')):
                        raise ConflictError('Disable a source while its transfer records are retained')
            values.update({key:value for key,value in payload.items() if key not in {'root','revision','sources'}})
            values.update(sources=sources,root=str(root),revision=uuid.uuid4().hex)
            if values['default_source'] not in {'local',*(s['id'] for s in sources if s.get('enabled',True))}:
                raise ValueError('Select an enabled default attachment source')
            for key in ('cache_max_bytes','outbox_max_bytes'):
                if type(values[key])is not int or values[key]<0:raise ValueError('Invalid attachment storage size limit')
            values['allowed_extensions']=normalize_extensions(values['allowed_extensions'])
            destination=self._state('settings.json')
            atomic_write(destination,_json(values).encode());private_file_mode(destination)
        self.wake.set();return self.status(root)

    def set_credentials(self,source_id,username,password,owner='local',revision=''):
        if not isinstance(username,str) or not isinstance(password,str) or ':' in username or any(ord(c)<32 for c in username):
            raise ValueError('Invalid attachment credentials')
        if not password or '\x00' in password or len(password.encode())>4096:raise ValueError('Enter the attachment source password')
        if not isinstance(owner,str) or not owner:raise ValueError('Invalid attachment owner')
        if revision and not re.fullmatch('[A-Za-z0-9_-]{1,128}',revision):raise ValueError('Invalid credential revision')
        with self.lock:
            self.credentials[source_id]=(username,password,revision or uuid.uuid4().hex,owner)
            self.connections.pop(source_id,None)
        self.wake.set();return self.credentials[source_id][2]

    def replace_credentials(self,entries):
        if not isinstance(entries,list):raise ValueError('Invalid attachment credentials')
        validated={}
        for entry in entries:
            if not isinstance(entry,dict):raise ValueError('Invalid attachment credentials')
            source_id=entry.get('source_id',entry.get('id',''))
            username=entry.get('username','');password=entry.get('password','');revision=entry.get('revision',entry.get('credential_revision',''))
            if not re.fullmatch('[A-Za-z0-9_-]{1,64}',source_id):raise ValueError('Invalid attachment source ID')
            if not isinstance(username,str) or ':' in username or any(ord(c)<32 for c in username) or not isinstance(password,str) or not password or '\x00' in password or len(password.encode())>4096:
                raise ValueError('Invalid attachment credentials')
            if not revision or not re.fullmatch('[A-Za-z0-9_-]{1,128}',revision):raise ValueError('Credential revision is required')
            validated[source_id]=(username,password,revision,entry.get('owner','local'))
        with self.lock:
            for key in set(self.credentials)|set(validated):
                if self.credentials.get(key)!=validated.get(key):self.connections.pop(key,None)
            self.credentials=validated
        self.wake.set()

    def _connection_context(self,root,source_id):
        source=self._source(source_id,root);credentials=self.credentials.get(source_id)
        return (str(root),source_id,self._source_revision(source),credentials[2] if credentials else '')

    def _connection_state(self,root,source_id):
        """Only revision identifiers and sanitized health state are durable."""
        context=self._connection_context(root,source_id);key=context[:2]
        with self.lock:
            cached=self.recovery_states.get(key)
            if cached is not None and cached[0]==context:return dict(cached[1])
            with self._db(root) as db:
                row=db.execute('SELECT * FROM connection_recovery WHERE source_id=?',(source_id,)).fetchone()
            value=(json.loads(row['payload']) if row and (row['source_revision'],row['credential_revision'])==context[2:]
                   else {'state':'unchecked','retry_attempts':0,'checked_at':0,'next_retry_at':0,'retry_paused':False})
            if row is None:
                # Older manifests already journaled rejected credentials on
                # jobs. Preserve that pause when upgrading/restarting too.
                with self._db(root) as db:
                    rejected=[json.loads(item[0]) for item in db.execute("SELECT payload FROM jobs WHERE state='waiting_for_auth'")]
                if any(job.get('source_id')==source_id and job.get('source_revision')==context[2] and
                       job.get('credential_revision')==context[3] and job.get('error')=='authentication_required' for job in rejected):
                    value={'state':'auth_required','code':'authentication_required','retry_attempts':1,
                           'checked_at':0,'next_retry_at':None,'retry_paused':True}
            self.recovery_states[key]=(context,value)
            if self.connections.get(source_id,{}).get('state')!='scanning':self.connections[source_id]=dict(value)
            return dict(value)

    def _record_connection(self,context,value):
        root,source_id,source_revision,credential_revision=context
        try:
            with self.lock:
                # A late reply from an old source/password must not pause or
                # mark healthy the replacement configuration.
                if self._connection_context(root,source_id)!=context:return
                self.recovery_states[context[:2]]=(context,dict(value))
                previous=self.connections.get(source_id,{})
                self.connections[source_id]=dict(value)
                if previous.get('state')=='scanning' and value['state']=='ready' and 'pending_directories' not in value:
                    self.connections[source_id].update({name:previous[name] for name in ('state','scanned','directories','pending_directories') if name in previous})
                with self._db(root) as db:
                    db.execute('INSERT OR REPLACE INTO connection_recovery VALUES(?,?,?,?)',
                               (source_id,source_revision,credential_revision,_json(value)))
        except (ConflictError,ValueError,OSError,sqlite3.Error):return  # Keep the in-memory pause if persistence is unavailable.

    def _connection_failed(self,root,source_id,error,*,context=None):
        if error.state not in {'auth_required','unreachable'}:return
        try:
            context=context or self._connection_context(root,source_id)
            if self._connection_context(root,source_id)!=context:return
        except (ConflictError,ValueError):return
        previous=self._connection_state(root,source_id)
        attempts=previous.get('retry_attempts',0)+1
        paused=error.code=='authentication_required'
        value={'state':error.state,'code':error.code,'retry_attempts':attempts,'checked_at':time.time(),
               'next_retry_at':None if error.state=='auth_required' else time.time()+min(60,2**min(attempts,6)),
               'retry_paused':paused,'reason':error.reason,'operation':error.operation}
        self._record_connection(context,value)

    def _connection_ready(self,root,source_id,*,context=None,**extra):
        try:
            context=context or self._connection_context(root,source_id)
            if self._connection_context(root,source_id)!=context:return
            previous=self._connection_state(root,source_id)
            if previous.get('retry_paused'):return
        except (ConflictError,ValueError,OSError,sqlite3.Error):return
        self._record_connection(context,{'state':'ready','retry_attempts':0,'checked_at':time.time(),
                                        'next_retry_at':time.time()+60,'retry_paused':False,**extra})
        if previous.get('state')!='ready' and callable(self.on_connection_ready):
            try:
                if self._connection_context(root,source_id)==context and self._connection_state(root,source_id)['state']=='ready':
                    self.on_connection_ready(root,source_id)
            except Exception:pass  # A notification cannot fail a verified connection.

    def _reset_connection(self,root,source_id):
        context=self._connection_context(root,source_id)
        self._record_connection(context,{'state':'unchecked','retry_attempts':0,'checked_at':0,
                                        'next_retry_at':0,'retry_paused':False})

    def _check_connection(self,root,source_id):
        value=self._connection_state(root,source_id)
        if value.get('retry_paused'):raise RemoteStorageError('authentication_required','auth_required')
        if value['state']=='unreachable' and value.get('next_retry_at',0)>time.time():
            raise RemoteStorageError(value.get('code','connection_unavailable'),'unreachable',reason=value.get('reason',''),operation=value.get('operation',''))

    def _provider(self,source_id,root=None,guard=None):
        root=self._root(root)
        with self.lock:
            source=self._source(source_id,root);credentials=self.credentials.get(source_id)
            if not credentials:raise RemoteStorageError('credentials_required','auth_required')
            self._check_connection(root,source_id)
            context=(root,source_id,self._source_revision(source),credentials[2])
        def check():
            self._root(root)
            if self.stopped.is_set():raise InterruptedError('Attachment storage stopped')
            if self._connection_context(root,source_id)!=context:raise PermissionError('Attachment source authorization changed')
            if guard is not None:guard()
        from vault_rag.remote_smb import SMBSource
        factory=SMBSource if source.get('type')=='smb' else WebDAVSource
        provider=factory(source,(source['username'],credentials[1]),transport=self.transports.get(source_id),guard=check,
                              on_error=lambda error:self._connection_failed(root,source_id,error,context=context))
        provider.connection_context=context
        return provider

    def poll_connections(self):
        """Probe configured origins only. Auth rejection requires explicit action."""
        root=self._root();sources=self._settings(root)['sources']
        start=self.poll_cursor%len(sources) if sources else 0
        for offset in range(len(sources)):
            index=(start+offset)%len(sources);source=sources[index]
            if self.stopped.is_set():break
            source_id=source['id']
            if not source.get('enabled',True) or source_id not in self.credentials:continue
            if self.connections.get(source_id,{}).get('state')=='scanning':continue
            owner=self.credentials[source_id][3]
            if owner!='local' and (not callable(self.authorize_owner) or self.authorize_owner(root,owner,self.config.data.get('revision','')) is False):continue
            state=self._connection_state(root,source_id)
            if state.get('retry_paused') or (state.get('next_retry_at') or 0)>time.time():continue
            self.poll_cursor=index+1
            def check():
                self._root(root)
                if self.stopped.is_set():raise InterruptedError('Attachment storage stopped')
            try:
                provider=self._provider(source_id,root,guard=check);result=provider.test()
            except RemoteStorageError as error:
                if error.state not in {'auth_required','unreachable'}:
                    context=provider.connection_context
                    self._record_connection(context,{'state':error.state,'code':error.code,'retry_attempts':state.get('retry_attempts',0)+1,
                                                    'checked_at':time.time(),'next_retry_at':time.time()+60,'retry_paused':False})
            else:self._connection_ready(root,source_id,context=provider.connection_context,**{key:value for key,value in result.items() if key!='state'})
            break  # One bounded probe per worker pass; other sources rotate fairly.

    def poll_scans(self):
        """One automatic catalog pull or directory walk at a time; never hold up byte transfers."""
        root=self._root()
        with self.lock:
            if any(thread.is_alive() for thread in self.scan_threads.values()):return
        now=time.time()
        for source in self._settings(root)['sources']:
            source_id=source['id'];credentials=self.credentials.get(source_id)
            mode=validate_source(source).get('membership_mode','discover')
            # app_only never runs discovery walks; catalog pull still refreshes membership.
            if not source.get('enabled',True) or not credentials or credentials[3]!='local':continue
            if mode=='discover' and source.get('scan_paused',False):continue
            context=self._connection_context(root,source_id)
            key=(root,source_id);previous=self.auto_scans.get(key,{})
            if previous.get('context')!=context:
                with self._db(root) as db:
                    checkpoint=db.execute('SELECT last_success FROM sync_checkpoints WHERE source_id=? AND source_revision=?',(source_id,context[2])).fetchone()
                    retry=db.execute('SELECT * FROM scan_retries WHERE source_id=? AND context=?',(source_id,_json(context))).fetchone()
                last=checkpoint[0] if checkpoint else None
                previous={'context':context,'next_scan_at':max(now+STARTUP_GRACE,(last or 0)+SCAN_INTERVAL,retry['next_retry_at'] if retry else 0),
                          'retry_at':retry['next_retry_at'] if retry else 0,'last_success_at':last};self.auto_scans[key]=previous
            connection=self._connection_state(root,source_id)
            was=previous.get('connection_state');previous['connection_state']=connection['state']
            if connection.get('retry_paused') or connection['state']!='ready':continue
            if was and was!='ready':previous['next_scan_at']=previous.get('retry_at',0)
            lifecycle=self.scan_statuses.get(key,{})
            finished=lifecycle.get('scan_finished_at')
            if finished and lifecycle.get('source_revision')==context[2] and finished!=previous.get('observed'):
                with self._db(root) as db:retry=db.execute('SELECT next_retry_at FROM scan_retries WHERE source_id=? AND context=?',(source_id,_json(context))).fetchone()
                retry_at=retry[0] if retry else 0
                previous.update(observed=finished,retry_at=retry_at,next_scan_at=max(retry_at,finished+(SCAN_INTERVAL if lifecycle['scan_state']=='completed' else 60)))
                if lifecycle['scan_state']=='completed':
                    previous['last_success_at']=finished
                    callback=self.on_scan_completed
                    if callable(callback):callback(root,source_id)
            if previous.get('next_scan_at',0)>now:continue
            if mode=='app_only':self.start_catalog_sync(root,source_id)
            else:self.start_scan(root,source_id)
            return

    def status(self,root=None):
        root=self._root(root);result=self._settings(root)
        for source in result['sources']:
            validated=validate_source(source)
            source['metadata_directory']=validated['metadata_directory']
            mode=validated.get('membership_mode','discover')
            source['membership_mode']=mode
            source_revision=self._source_revision(validated)
            source['password_saved']=source['id'] in self.credentials
            if source['password_saved'] and source.get('enabled',True):self._connection_state(root,source['id'])
            source['connection']=(self.connections.get(source['id'],{'state':'unchecked'}) if source['password_saved'] else
                                  {'state':'unconfigured','retry_attempts':0,'next_retry_at':None,'retry_paused':False})
            source['connection']=dict(source['connection'])
            schedule=self.auto_scans.get((root,source['id']),{})
            if not schedule:
                with self._db(root) as db:checkpoint=db.execute('SELECT last_success FROM sync_checkpoints WHERE source_id=? AND source_revision=?',(source['id'],source_revision)).fetchone()
                schedule={'last_success_at':checkpoint[0] if checkpoint else None}
            source['connection'].update(auto_sync=mode=='app_only' or not source.get('scan_paused',False),
                                        scan_paused=source.get('scan_paused',False),membership_mode=mode,
                                        last_success_at=schedule.get('last_success_at'),next_scan_at=schedule.get('next_scan_at'))
            lifecycle=self.scan_statuses.get((str(root),source['id']),{})
            if lifecycle.get('source_revision')==source_revision:
                source['connection'].update({key:value for key,value in lifecycle.items() if key!='source_revision'})
            else:source['connection']['scan_state']='unknown'
            if source.get('connection_hint')=='official-client':
                source['connection_notice']='Keep the official attachment window open; reopen it and update the loopback address after the client restarts.'
        with self.lock,self._db(root) as db:
            cached=db.execute('SELECT COALESCE(SUM(size),0),COUNT(*) FROM cache').fetchone()
            ranges=db.execute('SELECT COALESCE(SUM(size),0),COUNT(*) FROM ranges').fetchone()
            jobs=db.execute("SELECT state,COUNT(*) FROM jobs GROUP BY state").fetchall()
            outbox=self._outbox_usage()
        result.update(cache={'used_bytes':cached[0]+ranges[0],'files':cached[1]+ranges[1],'max_bytes':result['cache_max_bytes']},
                      outbox={'used_bytes':outbox,'max_bytes':result['outbox_max_bytes']},jobs={r[0]:r[1] for r in jobs})
        return result

    def test(self,root,source_id):
        self._root(root)
        self._reset_connection(root,source_id)
        started=time.perf_counter()
        try:
            provider=self._provider(source_id,root);result=provider.test()
        except RemoteStorageError as error:result={'state':error.state,'code':error.code,'read_verified':False,'upload_verified':False}
        else:self._connection_ready(root,source_id,context=provider.connection_context,**{key:value for key,value in result.items() if key!='state'})
        result['latency_ms']=max(0,int((time.perf_counter()-started)*1000))
        # Rough guidance for Tailscale/DERP vs LAN; not a hard protocol probe.
        result['latency_hint']=('high' if result['latency_ms']>=800 else
                                'elevated' if result['latency_ms']>=250 else 'ok')
        result['checked_at']=time.time()
        self.connections[source_id]={**self.connections.get(source_id,{}),**result}
        return result

    def _upsert(self,db,source_id,item,*,asset_id=None,sha256='',state='ready'):
        path=remote_path(item['path'],allow_empty=False)
        old=db.execute('SELECT * FROM assets WHERE source_id=? AND path=?',(source_id,path)).fetchone()
        key=old['id'] if old else asset_id or uuid.uuid4().hex
        modified=str(item.get('mtime',''))
        if old and not modified and item.get('metadata_origin')!='head':modified=old['mtime']
        mtime_ns=_mtime_ns(modified)
        same_size_time=old is not None and old['size']==int(item['size']) and _mtime_ns(old['mtime'])==mtime_ns
        etag=item.get('etag','')
        # Missing PROPFIND properties describe an unknown validator, not an
        # observed change. An explicit HEAD without ETag is authoritative.
        if not etag and same_size_time and old['state']!='missing' and item.get('metadata_origin')!='head':etag=old['etag']
        checked_sha=sha256 or (old['sha256'] if same_size_time and old['state']!='missing' and old['etag']==etag else '')
        mime=item.get('mime') or mimetypes.guess_type(path)[0] or 'application/octet-stream'
        if old and (old['name'],old['size'],old['mtime'],old['etag'],old['mime'],old['sha256'],old['state'],old['mtime_ns'])==(
                PurePosixPath(path).name,int(item['size']),modified,etag,mime,checked_sha,state,mtime_ns):return key
        db.execute('''INSERT INTO assets(id,source_id,path,name,size,mtime,etag,mime,sha256,state,metadata_revision,updated)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_id,path) DO UPDATE SET
            name=excluded.name,size=excluded.size,mtime=excluded.mtime,etag=excluded.etag,mime=excluded.mime,
            sha256=excluded.sha256,
            state=excluded.state,updated=excluded.updated''',
            (key,source_id,path,PurePosixPath(path).name,int(item['size']),modified,etag,
             mime,checked_sha,state,uuid.uuid4().hex,time.time()))
        db.execute('UPDATE assets SET mtime_ns=? WHERE id=?',(mtime_ns,key))
        return key

    def scan(self,root,source_id,*,guard=None,_scan_id='',_incremental=False,force_full=False):
        self._root(root)
        source_revision=self._source_revision(self._source(source_id,root))
        context=self._connection_context(root,source_id) if source_id!='local' else None
        key=(str(root),source_id)
        with self.lock:
            scan_lock=self.scan_locks.setdefault(key,threading.Lock())
            reserved=self.scan_threads.get(key)
            if ((reserved is not None and reserved.is_alive() and reserved is not threading.current_thread()) or
                    not scan_lock.acquire(blocking=False)):
                return {'ok':False,'state':'scanning','code':'scan_already_running','scanned':0,'metadata_preserved':True,
                        'scan_id':self.scan_statuses.get(key,{}).get('scan_id','')}
            lifecycle={'scan_id':_scan_id or uuid.uuid4().hex,'scan_state':'scanning','scan_started_at':time.time(),
                       'scan_finished_at':None,'scan_scanned':0,'scan_missing':0,'scan_excluded':0,'source_revision':source_revision}
            self.scan_statuses[key]=lifecycle
        try:
            result=self._scan(root,source_id,guard=guard,incremental=_incremental or force_full,force_full=force_full)
            lifecycle.update(scan_state='completed' if result.get('ok') else 'cancelled' if result.get('state')=='cancelled' else 'failed',
                             scan_finished_at=time.time(),scan_scanned=result.get('scanned',0),scan_missing=result.get('missing',0),scan_excluded=result.get('excluded',0))
            if result.get('ok') and source_id!='local':
                with self.lock,self._db(root) as db:
                    db.execute('INSERT OR REPLACE INTO sync_checkpoints VALUES(?,?,?)',(source_id,source_revision,lifecycle['scan_finished_at']))
            self._scan_retry(root,source_id,lifecycle,context)
            return {**result,'scan_id':lifecycle['scan_id']}
        except Exception as error:
            lifecycle.update(scan_state='cancelled' if isinstance(error,(InterruptedError,ConflictError,PermissionError)) else 'failed',scan_finished_at=time.time())
            self._scan_retry(root,source_id,lifecycle,context)
            raise
        finally:scan_lock.release()

    def _scan_retry(self,root,source_id,lifecycle,context):
        if source_id=='local' or lifecycle['scan_state']=='cancelled':return
        if self._connection_context(root,source_id)!=context:return
        with self.lock,self._db(root) as db:
            if lifecycle['scan_state']=='completed':db.execute('DELETE FROM scan_retries WHERE source_id=?',(source_id,))
            else:
                row=db.execute('SELECT failures FROM scan_retries WHERE source_id=? AND context=?',(source_id,_json(context))).fetchone()
                failures=(row[0] if row else 0)+1
                db.execute('INSERT OR REPLACE INTO scan_retries VALUES(?,?,?,?)',
                           (source_id,_json(context),failures,lifecycle['scan_finished_at']+retry_interval(failures)))

    @staticmethod
    def _reserved_paths(db,source_id):
        reserved=set()
        for record in db.execute('SELECT payload FROM jobs'):
            job=json.loads(record[0])
            if job.get('source_id')!=source_id:continue
            reserved.update(job.get('remote_orphans',[]))
            if job.get('kind')=='upload' and job.get('state')!='completed' and job.get('remote_path'):reserved.add(job['remote_path'])
            for entry in job.get('items',[]):
                reserved.update(entry.get('remote_orphans',[]))
                if entry.get('state')!='released' and entry.get('remote_path'):reserved.add(entry['remote_path'])
        return reserved

    @staticmethod
    def _require_available(row):
        if row['source_id']!='local' and row['state']=='missing':raise RemoteStorageError('remote_asset_missing','missing')

    @classmethod
    def _require_current(cls,current,expected):
        cls._require_available(current)
        if current.get('content_generation',0)!=expected.get('content_generation',0):
            raise ConflictError('Attachment availability changed while reading')

    def _scan(self,root,source_id,*,guard=None,incremental=False,force_full=False):
        self._root(root)
        source_revision=self._source_revision(self._source(source_id,root))
        scan_source=self._source(source_id,root)
        scan_roots=scan_source.get('scan_roots',[''])
        metadata_directory=scan_source.get('metadata_directory','')
        pause_state=scan_source.get('scan_paused',False)
        credentials=self.credentials.get(source_id)
        credential_revision=credentials[2] if credentials else ''
        def connection_is_current():
            try:return self._root(root)==root and self._source_revision(self._source(source_id,root))==source_revision and (self.credentials.get(source_id) or ('','',''))[2]==credential_revision
            except (ValueError,ConflictError):return False
        seen=set();snapshot={};missing=0;excluded=0;deferred={}
        extensions=extensions_for(self._files())
        ignore=RemoteIgnore((self._source(source_id,root).get('metadata_directory',''),) if source_id!='local' else (), allowed_extensions=extensions)
        cached_states={}
        if source_id!='local':
            with self.lock,self._db(root) as db:
                cached_states={row['path']:(row['state'],bool(row['has_alias'])) for row in db.execute("SELECT path,state,EXISTS(SELECT 1 FROM aliases x WHERE x.asset_id=assets.id) AS has_alias FROM assets WHERE source_id=? AND state IN ('ready','excluded')",(source_id,))}
                snapshot={row['id']:(row['path'],row['reconcile_revision'],row['state']) for row in db.execute("SELECT id,path,reconcile_revision,state FROM assets WHERE source_id=? AND state IN ('ready','excluded')",(source_id,)) if in_scan_scope(row['path'],scan_roots)}
        progress={'scanned':0,'directories':0,'pending_directories':1}
        def check():
            try:
                self._root(root)
                current_source=self._source(source_id,root)
                if current_source.get('scan_paused',False)!=pause_state:raise InterruptedError('Attachment directory scan paused')
                if current_source.get('scan_roots',[''])!=scan_roots:raise ConflictError('Attachment scan directories changed')
                if extensions_for(self._files())!=extensions:raise ConflictError('Attachment file types changed')
                if self.stopped.is_set():raise InterruptedError('Attachment scan stopped')
                if self._source_revision(self._source(source_id,root))!=source_revision:
                    raise ConflictError('Attachment scan source settings changed')
                if source_id!='local' and self._source(source_id,root).get('metadata_directory','')!=metadata_directory:
                    raise ConflictError('Attachment metadata namespace changed')
                current=self.credentials.get(source_id)
                if source_id!='local' and (current[2] if current else '')!=credential_revision:
                    raise PermissionError('Attachment scan credentials changed')
                if guard is not None:guard()
            except Exception:
                if connection_is_current():self.connections[source_id]={'state':'cancelled','code':'scan_interrupted',**progress,'checked_at':time.time()}
                raise
        def save_item(db,item,state='ready'):
            # Cached listings establish membership, never roll HEAD/PUT metadata
            # back to an older directory observation. Exclusion can still change.
            current=db.execute('SELECT * FROM assets WHERE source_id=? AND path=?',(source_id,item['path'])).fetchone() if item.get('_directory_cached') else None
            if current:
                key=current['id']
                if current['state'] in {'ready','excluded'} and current['state']!=state:
                    db.execute('UPDATE assets SET state=?,updated=? WHERE id=?',(state,time.time(),key))
            else:key=self._upsert(db,source_id,item,state=state)
            if not db.execute('SELECT 1 FROM aliases WHERE asset_id=?',(key,)).fetchone():
                logical=item['path'] if source_id=='local' else '/'.join((self.config.data.get('attachment_folder','_attachments'),'_remote',source_id,item['path']))
                existing=db.execute('SELECT asset_id FROM aliases WHERE path=?',(logical,)).fetchone()
                if existing and existing[0]!=key:raise ConflictError('Remote attachment logical path conflicts')
                db.execute('INSERT OR IGNORE INTO aliases VALUES(?,?)',(logical,key))
        def commit_batch(items,counts=None):
            check()
            seen.update(item['path'] for item in items)
            items=[item for item in items if not (item.get('_directory_cached') and cached_states.get(item['path'])==('excluded' if item.get('excluded') else 'ready',True))]
            if items:
                with self.lock,self._db(root) as db:
                    # A PUT can already be visible on WebDAV before its independent
                    # readback succeeds. Jobs reserve those keys before uploading;
                    # discovery must not publish their partial bytes as new assets.
                    reserved=self._reserved_paths(db,source_id) if source_id!='local' else set()
                    for item in items:
                        seen.add(item['path'])
                        if item['path'] in reserved:continue
                        existing=db.execute('SELECT state FROM assets WHERE source_id=? AND path=?',(source_id,item['path'])).fetchone()
                        if existing and existing['state'] in {'pending','migration_pending'}:continue
                        if source_id!='local' and (item.get('excluded') or (existing and existing['state']=='excluded')):
                            if existing or not item.get('ignore_control'):deferred[item['path']]=item
                            continue
                        save_item(db,item)
                    check()
            if counts is not None:progress.update(counts)
            self.scan_statuses[(str(root),source_id)]['scan_scanned']=progress['scanned']
            self.scan_statuses[(str(root),source_id)]['scan_excluded']=progress.get('excluded',0)
            # Progress stays on connections/scan_statuses for status polling.
            # Do not publish('files') per batch — that re-lists the attachment
            # grid under remote.lock while discovery is still writing.
            self.connections[source_id]={'state':'scanning',**progress,'checked_at':time.time()}
        if source_id=='local':
            files=self._files();items=[]
            for path in files.walk(strict=True):
                check()
                rel=path.relative_to(files.config.root).as_posix()
                if not allows(rel,extensions):continue
                info=path.stat();items.append({'path':rel,'size':info.st_size,'mtime':str(info.st_mtime_ns)})
            commit_batch(items,{'scanned':len(items),'directories':0,'pending_directories':0})
        else:
            self.connections[source_id]={'state':'scanning',**progress,'checked_at':time.time()}
            checkpoint=None
            try:
                provider=self._provider(source_id,root,guard=check)
                if incremental:
                    from vault_rag.remote_discovery import DirectoryCheckpoints,discovery_context
                    checkpoint=DirectoryCheckpoints(self.manifest_path(root),source_id,
                        discovery_context(root,source_revision,credential_revision,metadata_directory),check,force_full=force_full,
                        upload_directory=self._source(source_id,root).get('upload_directory','Incoming'))
                items=provider.scan(on_batch=commit_batch,ignore=ignore,roots=scan_roots,**({'checkpoint':checkpoint} if checkpoint else {}))
                ignored_paths={item['path'] for item in items if item.get('excluded')}
                ignored_paths.update(path for path,revision,state in snapshot.values() if ignore.excluded(path))
                excluded=len(ignored_paths)
                # Some servers silently omit ACL-hidden children from a valid
                # listing. Absence alone is insufficient: confirm only the
                # unseen snapshot candidates, without holding the catalog lock.
                with self.lock,self._db(root) as db:
                    check();reserved=self._reserved_paths(db,source_id)
                    candidates=[(asset_id,path,revision) for asset_id,(path,revision,state) in snapshot.items()
                                if path not in seen and path not in ignored_paths and path not in reserved and db.execute(
                                    "SELECT 1 FROM assets WHERE id=? AND state IN ('ready','excluded') AND path=? AND reconcile_revision=?",
                                    (asset_id,path,revision)).fetchone()]
                confirmed=set();head_present={}
                for index,(asset_id,path,revision) in enumerate(candidates):
                    check()
                    self.connections[source_id]={'state':'scanning',**progress,'phase':'confirming','pending_missing':len(candidates)-index,'checked_at':time.time()}
                    try:head_present[asset_id]=provider.stat(path)
                    except RemoteStorageError as error:
                        if error.code!='remote_not_found':raise
                        confirmed.add(asset_id)
                self.connections[source_id]={**self.connections[source_id],'phase':'verifying_rules'}
                provider.verify_ignore()
                from vault_rag.attachment_server_references import pull
                self.connections[source_id]={**self.connections[source_id],'phase':'syncing_references'}
                pull(self,root,source_id,provider)
                # Only a complete view can prove absence. Check the same
                # source/credential view again while committing the decision.
                stale_files=[]
                with self.lock,self._db(root) as db:
                    check();reserved=self._reserved_paths(db,source_id)
                    for path,item in deferred.items():
                        if path in reserved:continue
                        current=db.execute('SELECT state FROM assets WHERE source_id=? AND path=?',(source_id,path)).fetchone()
                        if current and current['state'] in {'pending','migration_pending'}:continue
                        save_item(db,item,'excluded' if item.get('excluded') else 'ready')
                    for asset_id,(path,revision,state) in snapshot.items():
                        if path in reserved:continue
                        if path in ignored_paths:
                            if state=='excluded':continue
                            db.execute("UPDATE assets SET state='excluded',updated=? WHERE id=? AND state='ready' AND reconcile_revision=?",
                                       (time.time(),asset_id,revision))
                            continue
                        if state=='excluded' and asset_id in head_present and db.execute(
                                "SELECT 1 FROM assets WHERE id=? AND state='excluded' AND reconcile_revision=?",(asset_id,revision)).fetchone():
                            save_item(db,head_present[asset_id]);continue
                        if asset_id not in confirmed or path in seen or path in reserved:continue
                        changed=db.execute("UPDATE assets SET state='missing',sha256='',etag='',content_generation=content_generation+1,updated=? WHERE id=? AND source_id=? AND path=? AND state IN ('ready','excluded') AND reconcile_revision=?",
                                           (time.time(),asset_id,source_id,path,revision)).rowcount
                        if not changed:continue
                        missing+=1
                        stale_files.extend((asset_id,self._cache_file_path(root,row[0])) for row in db.execute('SELECT file FROM cache WHERE asset_id=? UNION ALL SELECT file FROM ranges WHERE asset_id=?',(asset_id,asset_id)))
                        db.execute('DELETE FROM cache WHERE asset_id=?',(asset_id,));db.execute('DELETE FROM ranges WHERE asset_id=?',(asset_id,))
                    check()
                if checkpoint is not None:checkpoint.complete()
                for asset_id,cache_path in stale_files:
                    try:self._remove_cached_file(root,asset_id,cache_path)
                    except OSError:pass  # Detached cache is disposable; never touch source/outbox.
            except RemoteStorageError as error:
                if connection_is_current():self.connections[source_id]={**self.connections.get(source_id,{}),'state':error.state,'code':error.code,**progress,'checked_at':time.time()}
                self._publish_scan(root,source_id,force=True)
                return {'ok':False,'state':error.state,'code':error.code,'scanned':progress['scanned'],'metadata_preserved':True}
            except Exception as error:
                state='cancelled' if isinstance(error,(InterruptedError,ConflictError,PermissionError)) else 'invalid_service'
                if connection_is_current():self.connections[source_id]={'state':state,'code':'scan_interrupted' if state=='cancelled' else 'scan_failed',**progress,'checked_at':time.time()}
                self._publish_scan(root,source_id,force=True)
                raise
            finally:
                if checkpoint is not None:checkpoint.close()
        # Discovery rules never change note/RAG scopes or revoke old references.
        if source_id=='local':self.connections[source_id]={'state':'ready',**progress,'checked_at':time.time()}
        else:self._connection_ready(root,source_id,context=provider.connection_context,**progress)
        self._publish_scan(root,source_id,force=True)
        return {'ok':True,'state':'ready','scanned':len(items),'missing':missing,'excluded':excluded,'metadata_preserved':True}

    def _publish_scan(self,root,source_id,*,force=False):
        if self.runtime is None or str(self.config.data.get('root'))!=str(root):return
        now=time.monotonic();key=(str(root),source_id)
        if not force and now-self.scan_publish_at.get(key,0)<1:return
        self.scan_publish_at[key]=now
        try:self.runtime.publish('files',[])
        except Exception:pass  # UI notification failure never rolls back metadata.

    def pause_scan(self,root,source_id,paused):
        if type(paused)is not bool:raise ValueError('Invalid automatic scan setting')
        with self.config.lock,self.lock:
            settings=self._settings(root)
            source=next((s for s in settings['sources'] if s['id']==source_id),None)
            if source is None:raise ValueError('Attachment source is unavailable')
            source['scan_paused']=paused
            self.save(root,settings,settings['revision'])
            if not paused:self.auto_scans.pop((str(root),source_id),None)
        if not paused:self.start_scan(root,source_id)
        self.wake.set()
        return {'ok':True,'paused':paused}

    def start_catalog_sync(self,root,source_id,*,guard=None,publish_local=True):
        """Pull (and optionally publish) the server membership catalog without directory discovery."""
        self._root(root)
        if self.stopped.is_set():raise InterruptedError('Attachment storage stopped')
        key=(str(root),source_id)
        with self.lock:
            previous=self.scan_threads.get(key)
            if (previous is not None and previous.is_alive()) or (key in self.scan_locks and self.scan_locks[key].locked()):
                return {'ok':True,'state':'scanning','storage_id':source_id,'scan_id':self.scan_statuses.get(key,{}).get('scan_id',''),
                        'membership_mode':'app_only'}
            scan_id=uuid.uuid4().hex
            self.scan_statuses[key]={'scan_id':scan_id,'scan_state':'scanning','scan_started_at':time.time(),'scan_finished_at':None,
                                     'scan_scanned':0,'scan_missing':0,'scan_excluded':0,'phase':'catalog',
                                     'source_revision':self._source_revision(self._source(source_id,root))}
            def run():
                lifecycle=self.scan_statuses[key]
                try:
                    from vault_rag.attachment_server_catalog import sync_catalog
                    result=sync_catalog(self,root,source_id,guard=guard,publish_local=publish_local)
                    lifecycle.update(scan_state='completed',scan_finished_at=time.time(),scan_scanned=result.get('members',0))
                    with self.lock,self._db(root) as db:
                        db.execute('INSERT OR REPLACE INTO sync_checkpoints VALUES(?,?,?)',
                                   (source_id,lifecycle['source_revision'],lifecycle['scan_finished_at']))
                    self.connections[source_id]={'state':'ready','checked_at':time.time(),'scanned':result.get('members',0),
                                                'directories':0,'pending_directories':0,'phase':'catalog'}
                    callback=self.on_scan_completed
                    if callable(callback):callback(root,source_id)
                    try:self.runtime.publish('files',[])
                    except Exception:pass
                    return {**result,'ok':True,'state':'ready','scan_id':scan_id}
                except Exception as error:
                    lifecycle.update(scan_state='failed' if not isinstance(error,(InterruptedError,ConflictError,PermissionError)) else 'cancelled',
                                     scan_finished_at=time.time())
                    code=getattr(error,'code','catalog_sync_failed')
                    if isinstance(error,RemoteStorageError) and error.state in {'unreachable','auth_required'}:
                        self._connection_failed(root,source_id,error)
                    self.connections[source_id]={'state':'ready' if self.connections.get(source_id,{}).get('state')=='ready' else 'unreachable',
                                                'code':code,'checked_at':time.time(),'phase':'catalog'}
                    raise
                finally:
                    with self.lock:self.scan_threads.pop(key,None)
            thread=threading.Thread(target=run,name=f'attachment-catalog-{source_id[:8]}',daemon=True)
            self.scan_threads[key]=thread;thread.start()
        self.wake.set()
        return {'ok':True,'state':'scanning','storage_id':source_id,'scan_id':scan_id,'membership_mode':'app_only'}

    def start_catalog_import(self,root,source_id,*,guard=None):
        """One-time filesystem import into the server catalog; then app_only membership."""
        self._root(root)
        if self.stopped.is_set():raise InterruptedError('Attachment storage stopped')
        key=(str(root),source_id)
        deadline=time.time()+45
        while True:
            with self.lock:
                previous=self.scan_threads.get(key)
                locked=key in self.scan_locks and self.scan_locks[key].locked()
                phase=self.scan_statuses.get(key,{}).get('phase')
                if previous is not None and previous.is_alive() and phase=='import':
                    return {'ok':True,'state':'scanning','storage_id':source_id,
                            'scan_id':self.scan_statuses.get(key,{}).get('scan_id',''),'phase':'import'}
                if (previous is None or not previous.is_alive()) and not locked:
                    scan_id=uuid.uuid4().hex
                    self.scan_statuses[key]={'scan_id':scan_id,'scan_state':'scanning','scan_started_at':time.time(),'scan_finished_at':None,
                                             'scan_scanned':0,'scan_missing':0,'scan_excluded':0,'phase':'import',
                                             'source_revision':self._source_revision(self._source(source_id,root))}
                    # Visible immediately even while directory checks remain paused.
                    self.connections[source_id]={'state':'scanning','phase':'import','scanned':0,'scan_scanned':0,
                                                 'directories':0,'pending_directories':1,'checked_at':time.time()}
                    def run():
                        lifecycle=self.scan_statuses[key]
                        try:
                            from vault_rag.attachment_server_catalog import import_filesystem
                            def progress(info):
                                imported=info.get('imported',0)
                                scanned=info.get('scanned',imported)
                                lifecycle['scan_scanned']=max(imported,scanned)
                                self.connections[source_id]={'state':'scanning','phase':'import','scanned':imported,
                                                             'scan_scanned':scanned,'directories':info.get('directories',0),
                                                             'pending_directories':info.get('pending_directories',0),
                                                             'checked_at':time.time()}
                            result=import_filesystem(self,root,source_id,guard=guard,force_app_only=True,progress=progress)
                            lifecycle.update(scan_state='completed',scan_finished_at=time.time(),scan_scanned=result.get('imported',0))
                            with self.lock,self._db(root) as db:
                                db.execute('INSERT OR REPLACE INTO sync_checkpoints VALUES(?,?,?)',
                                           (source_id,lifecycle['source_revision'],lifecycle['scan_finished_at']))
                            self.connections[source_id]={'state':'ready','checked_at':time.time(),'scanned':result.get('imported',0),
                                                        'phase':'import','membership_mode':'app_only',
                                                        'directories':0,'pending_directories':0}
                            callback=self.on_scan_completed
                            if callable(callback):callback(root,source_id)
                            try:self.runtime.publish('files',[])
                            except Exception:pass
                            return {**result,'ok':True,'state':'ready','scan_id':scan_id}
                        except Exception as error:
                            lifecycle.update(scan_state='failed' if not isinstance(error,(InterruptedError,ConflictError,PermissionError)) else 'cancelled',
                                             scan_finished_at=time.time())
                            if isinstance(error,RemoteStorageError) and error.state in {'unreachable','auth_required'}:
                                self._connection_failed(root,source_id,error)
                            else:
                                self.connections[source_id]={**self.connections.get(source_id,{}),
                                                             'state':'unreachable' if isinstance(error,RemoteStorageError) else 'ready',
                                                             'code':getattr(error,'code','catalog_import_failed'),
                                                             'phase':'import','checked_at':time.time()}
                            raise
                        finally:
                            with self.lock:self.scan_threads.pop(key,None)
                    thread=threading.Thread(target=run,name=f'attachment-import-{source_id[:8]}',daemon=True)
                    self.scan_threads[key]=thread;thread.start()
                    self.wake.set()
                    return {'ok':True,'state':'scanning','storage_id':source_id,'scan_id':scan_id,'phase':'import'}
            if time.time()>=deadline:
                raise ConflictError('Directory check is still stopping; try importing again in a moment')
            time.sleep(0.2)

    def start_scan(self,root,source_id,*,guard=None,force_full=False):
        """Run a bounded metadata scan in the background; one per source/root."""
        if type(force_full)is not bool:raise ValueError('Invalid attachment scan mode')
        self._root(root)
        source=self._source(source_id,root)
        if source.get('membership_mode','discover')=='app_only' and not force_full:
            return self.start_catalog_sync(root,source_id,guard=guard)
        if source.get('scan_paused',False):raise ValueError('Resume automatic directory checks before scanning')
        if self.stopped.is_set():raise InterruptedError('Attachment storage stopped')
        key=(str(root),source_id)
        with self.lock:
            previous=self.scan_threads.get(key)
            if (previous is not None and previous.is_alive()) or (key in self.scan_locks and self.scan_locks[key].locked()):
                return {'ok':True,'state':'scanning','storage_id':source_id,'scan_id':self.scan_statuses.get(key,{}).get('scan_id','')}
            scan_id=uuid.uuid4().hex
            context=self._connection_context(root,source_id)
            self.scan_statuses[key]={'scan_id':scan_id,'scan_state':'scanning','scan_started_at':time.time(),'scan_finished_at':None,
                                     'scan_scanned':0,'scan_missing':0,'scan_excluded':0,'source_revision':self._source_revision(self._source(source_id,root))}
            self.connections[source_id]={'state':'scanning','scanned':0,'directories':0,'pending_directories':1,'checked_at':time.time()}
            def run():
                try:self.scan(root,source_id,guard=guard,_scan_id=scan_id,_incremental=True,force_full=force_full)
                except Exception as error:
                    try:
                        if self._connection_context(root,source_id)!=context:return
                    except (ValueError,ConflictError):return
                    previous=self.connections.get(source_id,{})
                    progress={name:previous.get(name,0) for name in ('scanned','directories','pending_directories')}
                    if isinstance(error,RemoteStorageError):state,code=error.state,error.code
                    elif isinstance(error,(InterruptedError,ConflictError,PermissionError)):state,code='cancelled','scan_interrupted'
                    else:state,code='invalid_service','scan_failed'
                    self.connections[source_id]={'state':state,'code':code,**progress,'checked_at':time.time()}
                    if previous.get('state')=='scanning':self._publish_scan(root,source_id,force=True)
                finally:
                    with self.lock:
                        if self.scan_threads.get(key) is threading.current_thread():self.scan_threads.pop(key,None)
            thread=threading.Thread(target=run,daemon=True,name='remote-attachment-scan-'+source_id[:8])
            self.scan_threads[key]=thread;thread.start()
        return {'ok':True,'state':'scanning','storage_id':source_id,'scan_id':scan_id}

    def _public_asset(self,row,cached=False,logical_path=''):
        value=dict(row);value['asset_id']=value.pop('id');value['storage_id']=value['source_id']
        if value['source_id']!='local':
            value['remote_path']=value['path']
            value['path']=logical_path or value.pop('logical_path','') or '/'.join((self.config.data.get('attachment_folder','_attachments'),'_remote',value['source_id'],value['path']))
            value['name']=PurePosixPath(value['path']).name
        value['tags']=json.loads(value.get('tags','[]'));value['source']='local' if value['source_id']=='local' else 'remote'
        value['cache_state']='complete' if cached else 'none'
        value['version_state']='strong_etag' if value.get('etag') and not value['etag'].lower().startswith('w/') else 'weak_metadata'
        value['capabilities']={'rename':value['source_id']=='local','move':value['source_id']=='local','trash':value['source_id']=='local'}
        return value

    def _observe_remote_version(self,root,row,metadata):
        """Bind subsequent bytes to actual HEAD metadata, never an old scan row."""
        self._root(root)
        with self.lock,self._db(root) as db:
            current=self._resolve(db,asset_id=row['id'])
            self._require_current(current,row)
            if _remote_version(metadata)==_remote_version(row):return
            if _remote_version(current)!=_remote_version(row):raise ConflictError('Attachment metadata changed while checking its version')
            self._upsert(db,row['source_id'],metadata,state=row['state'])
            row.update(dict(db.execute('SELECT * FROM assets WHERE id=?',(row['id'],)).fetchone()))

    def _refresh_remote_version(self,root,row):
        provider=self._provider(row['source_id'],root)
        source_revision=self._source_revision(provider.source)
        metadata=provider.stat(row['path'])
        self._root(root)
        if self._source_revision(self._source(row['source_id'],root))!=source_revision:
            raise ConflictError('Attachment source settings changed while checking its version')
        self._observe_remote_version(root,row,metadata)

    def list(self,root,query='',source_id='',limit=100,after=''):
        self._root(root)
        if len(query)>500 or len(after)>4096:raise ValueError('Attachment query is too long')
        limit=max(1,min(int(limit),500));where=['a.path>?','attachment_allowed(a.path)=1','attachment_scan_scope(a.source_id,a.path)=1',"a.state NOT IN ('redirected','missing','excluded')"];params=[after]
        if source_id:where.append('a.source_id=?');params.append(source_id)
        if query:
            where.append('(a.path LIKE ? ESCAPE "\\" OR a.description LIKE ? ESCAPE "\\" OR a.tags LIKE ? ESCAPE "\\" OR a.category LIKE ? ESCAPE "\\")')
            pattern='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%';params.extend([pattern]*4)
        with self.lock,self._db(root) as db:
            register_policy(db,extensions_for(self._files()))
            register_scan_scope(db,self._settings(root)['sources'])
            total=db.execute('SELECT COUNT(*) FROM assets a WHERE '+' AND '.join(where),params).fetchone()[0]
            rows=db.execute('SELECT a.*,(SELECT MIN(path) FROM aliases WHERE asset_id=a.id) AS logical_path,c.asset_id AS cached FROM assets a LEFT JOIN cache c ON a.id=c.asset_id WHERE '+' AND '.join(where)+' ORDER BY a.path,a.source_id LIMIT ?',(*params,limit+1)).fetchall()
        return {'items':[self._public_asset({k:r[k] for k in r.keys() if k!='cached'},bool(r['cached'])) for r in rows[:limit]],
                'total':total,'after':rows[limit-1]['path'] if len(rows)>limit else '',
                'next_cursor':rows[limit-1]['path'] if len(rows)>limit else '',
                'next':rows[limit-1]['path'] if len(rows)>limit else '', 'has_more':len(rows)>limit}

    def _resolve(self,db,path='',asset_id='',source_id=''):
        if asset_id:
            if not re.fullmatch('[0-9a-f]{32}',asset_id):raise ValueError('Invalid attachment asset ID')
            shared=db.execute('SELECT asset_id FROM reference_ids WHERE old_id=?',(asset_id,)).fetchone()
            if shared:asset_id=shared[0]
            seen=set()
            for _ in range(32):
                if asset_id in seen:raise ConflictError('Attachment identity redirect cycle')
                seen.add(asset_id)
                redirect=db.execute('SELECT * FROM asset_redirects WHERE old_id=?',(asset_id,)).fetchone()
                if not redirect:break
                if not redirect['active'] and self.config.path_for(redirect['source_path']).is_file():break
                asset_id=redirect['new_id']
            else:raise ConflictError('Attachment identity redirect chain is too long')
            rows=db.execute('SELECT * FROM assets WHERE id=?',(asset_id,)).fetchall()
        else:
            path=remote_path(path,allow_empty=False)
            alias=db.execute('SELECT al.asset_id FROM aliases al JOIN assets a ON a.id=al.asset_id WHERE al.path=?'+(' AND a.source_id=?' if source_id else ''),
                             (path,source_id) if source_id else (path,)).fetchone()
            if alias:
                rows=db.execute('SELECT * FROM assets WHERE id=?',(alias[0],)).fetchall()
                # During migration, an active local row still owns an edited file.
                # After release the same path is vault-path cache for the remote asset.
                if not source_id and rows and rows[0]['source_id']!='local' and self.config.path_for(path).is_file():
                    local_rows=db.execute("SELECT * FROM assets WHERE source_id='local' AND path=? AND state!='redirected'",(path,)).fetchall()
                    if local_rows:rows=local_rows
            elif source_id:rows=db.execute('SELECT * FROM assets WHERE source_id=? AND path=?',(source_id,path)).fetchall()
            else:rows=db.execute('SELECT * FROM assets WHERE path=?',(path,)).fetchall()
            if not rows:
                prefix=self.config.data.get('attachment_folder','_attachments')+'/_remote/'
                if path.startswith(prefix):
                    storage,separator,physical=path[len(prefix):].partition('/')
                    if separator and (not source_id or source_id==storage):
                        rows=db.execute('SELECT * FROM assets WHERE source_id=? AND path=?',(storage,physical)).fetchall()
            if not rows and not source_id and '/' not in path:
                rows=db.execute("SELECT * FROM assets WHERE name=? AND state!='redirected'",(PurePosixPath(path).name,)).fetchall()
        if len(rows)>1:raise ConflictError('Attachment path is ambiguous; specify a storage source or asset ID')
        if not rows:raise FileNotFoundError('Attachment metadata is unavailable')
        if source_id and rows[0]['source_id']!=source_id:raise ValueError('Attachment source mismatch')
        result=dict(rows[0])
        if result['source_id']!='local':
            result['logical_path']=db.execute('SELECT MIN(path) FROM aliases WHERE asset_id=?',(result['id'],)).fetchone()[0] or ''
        return result

    def stat(self,root,path='',*,asset_id='',source_id=''):
        self._root(root)
        with self.lock,self._db(root) as db:
            if not asset_id and not source_id and path and self.config.path_for(relative(path)).is_file():
                logical=relative(path)
                has_remote=db.execute(
                    "SELECT 1 FROM aliases al JOIN assets a ON a.id=al.asset_id WHERE al.path=? AND a.source_id!='local' "
                    "AND (a.state='pending' OR EXISTS (SELECT 1 FROM cache c WHERE c.asset_id=a.id AND c.file='vault:'||al.path))",
                    (logical,)).fetchone()
                has_local=db.execute(
                    "SELECT 1 FROM assets WHERE source_id='local' AND path=? AND state!='redirected'",
                    (logical,)).fetchone()
                if has_local or not has_remote:source_id='local'
            try:row=self._resolve(db,path,asset_id,source_id)
            except FileNotFoundError:
                if asset_id:raise
                if source_id not in {'','local'}:raise
                local=self.config.path_for(relative(path));info=local.stat()
                if not local.is_file() or local.suffix.lower() in {'.md','.markdown','.txt','.base'}:raise ValueError('Select an attachment file')
                key=self._upsert(db,'local',{'path':relative(path),'size':info.st_size,'mtime':str(info.st_mtime_ns)})
                db.execute('INSERT OR IGNORE INTO aliases VALUES(?,?)',(relative(path),key))
                row=self._resolve(db,asset_id=key)
            if row['source_id']=='local':
                local=self.config.path_for(row['path']);info=local.stat()
                if not local.is_file():raise ValueError('Select an attachment file')
                if (info.st_size,str(info.st_mtime_ns))!=(row['size'],row['mtime']):
                    self._upsert(db,'local',{'path':row['path'],'size':info.st_size,'mtime':str(info.st_mtime_ns)})
                    row=self._resolve(db,asset_id=row['id'])
            cache=db.execute('SELECT verified FROM cache WHERE asset_id=?',(row['id'],)).fetchone()
            partial=db.execute('SELECT MAX(verified) AS verified FROM ranges WHERE asset_id=?',(row['id'],)).fetchone()
            alias=db.execute('SELECT MIN(path) FROM aliases WHERE asset_id=?',(row['id'],)).fetchone()[0]
        result=self._public_asset(row,bool(cache),alias or '')
        if cache:result.update(last_verified=cache['verified'],offline=self.connections.get(row['source_id'],{}).get('state') in {'unreachable','auth_required'})
        elif partial['verified'] is not None:result.update(cache_state='partial',last_verified=partial['verified'])
        return result

    def update_metadata(self,root,path,patch,revision=None,*,asset_id='',source_id=''):
        if not isinstance(patch,dict) or set(patch)-{'description','tags','category'}:raise ValueError('Unsupported attachment metadata')
        if not isinstance(patch.get('description',''),str) or len(patch.get('description',''))>10000:raise ValueError('Attachment description is too long')
        if not isinstance(patch.get('category',''),str) or len(patch.get('category',''))>200:raise ValueError('Attachment category is too long')
        tags=patch.get('tags',[])
        if not isinstance(tags,list) or len(tags)>100 or any(not isinstance(t,str) or len(t)>100 for t in tags):raise ValueError('Invalid attachment tags')
        self.stat(root,path,asset_id=asset_id,source_id=source_id)
        with self.lock,self._db(root) as db:
            row=self._resolve(db,path,asset_id,source_id)
            if revision is not None and revision!=row['metadata_revision']:raise ConflictError('Attachment metadata changed')
            for key in ('description','tags','category'):
                if key in patch:row[key]=_json(list(dict.fromkeys(tags))) if key=='tags' else patch[key]
            db.execute('UPDATE assets SET description=?,tags=?,category=?,metadata_revision=?,updated=? WHERE id=?',
                       (row['description'],row['tags'],row['category'],uuid.uuid4().hex,time.time(),row['id']))
        return self.stat(root,asset_id=row['id'])

    @staticmethod
    def _vault_cache_key(path):
        return 'vault:'+relative(path)

    def _is_vault_cache(self,file_field):
        return isinstance(file_field,str) and file_field.startswith('vault:')

    def _cache_file_path(self,root,file_field):
        if self._is_vault_cache(file_field):
            return self.config.path_for(file_field[6:])
        return self._state('cache',file_field)

    def _attachment_folder(self):
        return self.config.data.get('attachment_folder','_attachments')

    def _vault_alias_for(self,db,row):
        folder=self._attachment_folder()
        for alias in db.execute('SELECT path FROM aliases WHERE asset_id=? ORDER BY path',(row['id'],)).fetchall():
            if under(alias[0],folder):return alias[0]
        return ''

    def _register_vault_cache(self,db,row,path,*,sha256='',verified=None,alias=''):
        info=path.stat();digest=sha256 or row['sha256'] or _hash_file(path)[0]
        key=self._vault_cache_key(alias or self._vault_alias_for(db,row) or relative(path))
        now=time.time();stamp=now if verified is None else verified
        db.execute('INSERT OR REPLACE INTO cache(asset_id,file,size,sha256,etag,mtime,accessed,verified,identity) VALUES(?,?,?,?,?,?,?,?,?)',
                   (row['id'],key,info.st_size,digest,row['etag'],row['mtime'],now,stamp,_json(_version(info))))
        return key

    def _drop_cache_row(self,db,root,asset_id):
        item=db.execute('SELECT file FROM cache WHERE asset_id=?',(asset_id,)).fetchone()
        if not item:return
        self._remove_cached_file(root,asset_id,self._cache_file_path(root,item[0]))
        db.execute('DELETE FROM cache WHERE asset_id=?',(asset_id,))

    def acquire_cache_read(self,root,asset_id):
        """Keep preview bytes alive until the response (or thumbnail) closes."""
        key=(str(root),asset_id)
        with self.lock:
            self._root(root)
            with self.cache_lock:self.cache_readers[key]=self.cache_readers.get(key,0)+1
        released=False
        def release():
            nonlocal released
            with self.cache_lock:
                if released:return
                released=True
                remaining=self.cache_readers[key]-1
                if remaining:self.cache_readers[key]=remaining
                else:
                    del self.cache_readers[key]
                    for path,identity in self.cache_deletions.pop(key,{}).items():
                        try:
                            if not is_link(path) and _version(path.stat())==identity:path.unlink(missing_ok=True)
                        except OSError:pass
                self.wake.set()
        return release

    def _remove_cached_file(self,root,asset_id,path):
        with self.cache_lock:
            key=(str(root),asset_id)
            if self.cache_readers.get(key):
                try:self.cache_deletions.setdefault(key,{})[path]=_version(path.stat())
                except FileNotFoundError:pass
            else:path.unlink(missing_ok=True)

    def queue_preview_check(self,root,asset_id,verified=0):
        with self.lock,self._db(root) as db:
            row=self._resolve(db,asset_id=asset_id)
        self._queue_cache_check(root,row,verified)

    def _queue_cache_check(self,root,row,verified):
        if row['state']!='ready' or time.time()-verified<self.cache_ttl:return
        try:
            with self.lock:
                if self.stopped.is_set():return
                source=self._source(row['source_id'],root)
                if not source.get('enabled',True):return
                context=self._connection_context(root,row['source_id'])
                if not context[3]:return
                state=self._connection_state(root,row['source_id'])
                if state.get('retry_paused') or (state.get('state')=='unreachable' and (state.get('next_retry_at') or 0)>time.time()):return
                key=(str(root),row['id'])
                settings_revision=self._settings(root)['revision']
                revision=self.config.data.get('revision')
                self.cache_checks={pending:task for pending,task in self.cache_checks.items()
                                   if pending[0]==str(root) and task['revision']==revision}
                signature=(context,revision,settings_revision,_remote_version(row),row.get('content_generation',0))
                checked=self.cache_checked.get(key)
                if checked and checked[0]==signature and time.time()-checked[1]<self.cache_ttl:return
                if key not in self.cache_checks and len(self.cache_checks)<128:
                    self.cache_checks[key]={'context':context,'revision':revision,'settings_revision':settings_revision,'row':dict(row)}
                    self.wake.set()
        except (ConflictError,ValueError,OSError,sqlite3.Error):return

    def process_cache_checks(self):
        """Revalidate one saved object, never holding the metadata lock over I/O."""
        with self.lock:
            if self.stopped.is_set():return
            entry=next(((key,task) for key,task in self.cache_checks.items()
                        if 'metadata' not in task or not self.cache_readers.get(key)),None)
            if entry is None:return
            key,task=entry
        root,asset_id=key;row=task['row'];context=task['context']
        def guard():
            if (self.stopped.is_set() or self.config.data.get('revision')!=task['revision'] or
                    self._settings(root)['revision']!=task['settings_revision'] or
                    self._connection_context(root,row['source_id'])!=context):
                raise ConflictError('Attachment cache check expired')
        keep=False
        try:
            guard()
            if 'metadata' not in task:
                provider=self._provider(row['source_id'],root,guard=guard)
                try:task['metadata']=provider.stat(row['path'])
                except RemoteStorageError as error:
                    if error.code!='remote_not_found':raise
                    task['metadata']=None
            with self.lock,self.cache_lock:
                guard()
                if self.cache_readers.get(key):
                    keep=True
                    return
                with self._db(root) as db:
                    current=self._resolve(db,asset_id=asset_id)
                    self._require_current(current,row)
                    if (current['source_id'],current['path'],current['state'],_remote_version(current))!=(
                            row['source_id'],row['path'],row['state'],_remote_version(row)):return
                    metadata=task['metadata']
                    if metadata is None or _remote_version(metadata)!=_remote_version(row):
                        if metadata is not None:self._upsert(db,row['source_id'],metadata,state=row['state'])
                        self._drop_cache_row(db,root,asset_id)
                        for cached in db.execute('SELECT file FROM ranges WHERE asset_id=?',(asset_id,)).fetchall():
                            self._remove_cached_file(root,asset_id,self._state('cache',cached[0]))
                        db.execute('DELETE FROM ranges WHERE asset_id=?',(asset_id,))
                    else:
                        for table in ('cache','ranges'):
                            db.execute('UPDATE '+table+' SET verified=? WHERE asset_id=?',(time.time(),asset_id))
                    self.cache_checked[key]=((context,task['revision'],task['settings_revision'],_remote_version(row),row.get('content_generation',0)),time.time())
                    if len(self.cache_checked)>128:self.cache_checked.pop(next(iter(self.cache_checked)))
            self._connection_ready(root,row['source_id'],context=context)
        except RemoteStorageError as error:
            self._connection_failed(root,row['source_id'],error,context=context)
        except (ConflictError,PermissionError,InterruptedError,FileNotFoundError,ValueError,OSError,sqlite3.Error):pass
        finally:
            if not keep:
                with self.lock:
                    if self.cache_checks.get(key) is task:self.cache_checks.pop(key,None)

    def _cached(self,root,row,*,cache_first=False):
        with self._db(root) as db:
            self._require_current(self._resolve(db,asset_id=row['id']),row)
            item=db.execute('SELECT * FROM cache WHERE asset_id=?',(row['id'],)).fetchone()
            path=None;verified=0
            if item:
                path=self._cache_file_path(root,item['file'])
                valid=not is_link(path) and path.is_file() and path.stat().st_size==item['size']
                valid=valid and (item['size'],item['etag'],item['mtime'])==(row['size'],row['etag'],row['mtime'])
                if valid:
                    identity=_json(_version(path.stat()))
                    if identity!=item['identity']:
                        digest,_=_hash_file(path);valid=digest==item['sha256']
                        if valid:db.execute('UPDATE cache SET identity=? WHERE asset_id=?',(identity,row['id']))
                if not valid:
                    self._drop_cache_row(db,root,row['id']);item=None;path=None
                else:
                    db.execute('UPDATE cache SET accessed=? WHERE asset_id=?',(time.time(),row['id']))
                    verified=item['verified']
            if item is None:
                alias=self._vault_alias_for(db,row)
                if not alias:return None
                candidate=self.config.path_for(alias)
                if is_link(candidate) or not candidate.is_file() or candidate.stat().st_size!=row['size']:return None
                digest,_=_hash_file(candidate)
                if row['sha256'] and digest!=row['sha256']:return None
                self._register_vault_cache(db,row,candidate,sha256=digest,alias=alias)
                path=candidate;verified=time.time()
        if cache_first:
            self._queue_cache_check(root,row,verified)
            return path
        source=next((s for s in self._settings(root)['sources'] if s['id']==row['source_id']),None)
        if source and source.get('enabled',True) and time.time()-verified>=self.cache_ttl:
            try:
                provider=self._provider(row['source_id'],root);remote=provider.stat(row['path'])
            except RemoteStorageError as error:
                self.connections[row['source_id']]={**self.connections.get(row['source_id'],{}),'state':error.state,'code':error.code,'checked_at':time.time()}
                if error.state not in {'unreachable','auth_required'}:raise
                with self._db(root) as db:self._require_current(self._resolve(db,asset_id=row['id']),row)
                return path
            self._root(root)
            self._connection_ready(root,row['source_id'],context=provider.connection_context)
            with self._db(root) as db:
                self._require_current(self._resolve(db,asset_id=row['id']),row)
                if (remote['size'],remote['etag'],remote['mtime'])!=(row['size'],row['etag'],row['mtime']):
                    self._upsert(db,row['source_id'],remote,state=row['state'])
                    self._drop_cache_row(db,root,row['id'])
                    row.update(dict(db.execute('SELECT * FROM assets WHERE id=?',(row['id'],)).fetchone()))
                    return None
                db.execute('UPDATE cache SET verified=? WHERE asset_id=?',(time.time(),row['id']))
        return path

    def materialize(self,root,path='',*,asset_id='',source_id='',cache_first=False):
        self._root(root)
        self.stat(root,path,asset_id=asset_id,source_id=source_id)
        with self.lock,self._db(root) as db:row=self._resolve(db,path,asset_id,source_id)
        self._require_available(row)
        if row['source_id']=='local':return self.config.path_for(row['path'])
        with self.lock:
            asset_lock=self.asset_locks.setdefault((str(root),row['id']),threading.Lock())
        # Only identical asset downloads serialize. Metadata queries and other
        # transfers never wait for a network read or a multi-GB SHA calculation.
        with asset_lock:
            with self.lock,self._db(root) as db:row=self._resolve(db,asset_id=row['id']);alias=self._vault_alias_for(db,row)
            self._require_available(row)
            cached=self._cached(root,row,cache_first=cache_first)
            if cached:return cached
            # Pending bytes are durable outbox data, not disposable cache.
            if row['state']=='pending':
                with self._db(root) as db:
                    jobs=[json.loads(job[0]) for job in db.execute("SELECT payload FROM jobs WHERE kind='upload' AND state!='completed'").fetchall()]
                for value in jobs:
                    if value.get('asset_id')==row['id']:
                        self._check_job(value,authorize=False)
                        staged=self._state('outbox',value['id']+'.blob')
                        if staged.is_file() and _hash_file(staged)[0]==value['sha256']:return staged
                raise FileNotFoundError('Pending attachment bytes are unavailable')
            self._refresh_remote_version(root,row)
            maximum=self._settings(root)['cache_max_bytes']
            if row['size']>maximum:raise ValueError('Attachment exceeds the disk cache limit; use byte ranges')
            with self.lock:self._evict(root,reserve=row['size'])
            use_vault=bool(alias) and not (self.cache_readers.get((str(root),row['id'])) and self.config.path_for(alias).exists())
            if use_vault:
                destination=self.config.path_for(alias);destination.parent.mkdir(parents=True,exist_ok=True)
                temporary=destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.partial')
                cache_key=self._vault_cache_key(alias)
            else:
                self._state('cache').mkdir(parents=True,exist_ok=True,mode=0o700)
                cache_key=uuid.uuid4().hex+'.cache';temporary=self._state('cache',cache_key+'.partial');destination=self._state('cache',cache_key)
            provider=self._provider(row['source_id'],root)
            result=provider.download(row['path'],temporary,expected_size=row['size'],expected_etag=row['etag'],max_bytes=maximum)
            try:
                self._root(root)
                self._observe_remote_version(root,row,result)
            except Exception:
                temporary.unlink(missing_ok=True);raise
            if row['sha256'] and result['sha256']!=row['sha256']:
                temporary.unlink(missing_ok=True);raise ConflictError('Attachment checksum changed')
            with self.lock,self._db(root) as db:
                current=self._resolve(db,asset_id=row['id'])
                try:self._require_current(current,row)
                except Exception:temporary.unlink(missing_ok=True);raise
                if (current['size'],current['etag'],current['mtime'])!=(row['size'],row['etag'],row['mtime']):
                    temporary.unlink(missing_ok=True);raise ConflictError('Attachment metadata changed')
                os.replace(temporary,destination);private_file_mode(destination)
                db.execute('INSERT OR REPLACE INTO cache(asset_id,file,size,sha256,etag,mtime,accessed,verified,identity) VALUES(?,?,?,?,?,?,?,?,?)',
                           (row['id'],cache_key,row['size'],result['sha256'],row['etag'],row['mtime'],time.time(),time.time(),_json(_version(destination.stat()))))
                db.execute('UPDATE assets SET sha256=?,updated=? WHERE id=?',(result['sha256'],time.time(),row['id']))
            with self.lock:self._evict(root,keep=row['id'])
            self._connection_ready(root,row['source_id'],context=provider.connection_context)
            return destination

    def read_range(self,root,path='',start=0,end=None,*,asset_id='',source_id='',cache_first=False):
        self._root(root)
        self.stat(root,path,asset_id=asset_id,source_id=source_id)
        with self.lock,self._db(root) as db:row=self._resolve(db,path,asset_id,source_id)
        self._require_available(row)
        if type(start)is not int or start<0 or (end is not None and (type(end)is not int or end<start)):raise ValueError('Invalid attachment byte range')
        local=self.config.path_for(row['path']) if row['source_id']=='local' else self._cached(root,row,cache_first=cache_first)
        if row['state']=='pending':local=self.materialize(root,asset_id=row['id'])
        requested_end=end
        if start>=row['size']:
            return b'',{**self._public_asset(row,bool(local)),'start':start,'end':start-1,'total':row['size']}
        end=min(row['size']-1,end if end is not None else row['size']-1)
        if end-start+1>8*1024*1024:raise ValueError('Attachment byte range exceeds 8 MiB')
        if local:
            descriptor=os.open(local,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
            with os.fdopen(descriptor,'rb') as stream:
                before=os.fstat(stream.fileno())
                if not statlib.S_ISREG(before.st_mode) or before.st_size!=row['size']:raise ConflictError('Attachment changed')
                stream.seek(start);data=stream.read(max(0,end-start+1))
                if _version(os.fstat(stream.fileno()))!=_version(before):raise ConflictError('Attachment changed while reading')
            with self.lock,self._db(root) as db:self._require_current(self._resolve(db,asset_id=row['id']),row)
            return data,{**self._public_asset(row,bool(local)),'start':start,'end':end,'total':row['size']}
        partial=self._range_cached(root,row,start,end,cache_first=cache_first)
        if partial is not None:
            return partial,{**self._public_asset(row),'cache_state':'partial','start':start,'end':end,'total':row['size']}
        self._refresh_remote_version(root,row)
        if start>=row['size']:return b'',{**self._public_asset(row),'start':start,'end':start-1,'total':row['size']}
        end=min(requested_end if requested_end is not None else row['size']-1,row['size']-1)
        if end-start+1>8*1024*1024:raise ValueError('Attachment byte range exceeds 8 MiB')
        provider=self._provider(row['source_id'],root)
        data,metadata=provider.read_range(row['path'],start,end,expected_etag=row['etag'],expected_size=row['size'])
        self._observe_remote_version(root,row,metadata)
        self._store_range(root,row,start,end,data)
        self._connection_ready(root,row['source_id'],context=provider.connection_context)
        return data,{**self._public_asset(row),'cache_state':'partial' if self._settings(root)['cache_max_bytes']>=len(data) else 'none','start':start,'end':end,'total':row['size']}

    def _range_cached(self,root,row,start,end,*,cache_first=False):
        with self.lock,self._db(root) as db:
            self._require_current(self._resolve(db,asset_id=row['id']),row)
            item=db.execute('SELECT * FROM ranges WHERE asset_id=? AND start<=? AND end>=? ORDER BY size LIMIT 1',(row['id'],start,end)).fetchone()
            if not item:return None
            path=self._state('cache',item['file'])
            valid=not is_link(path) and path.is_file() and path.stat().st_size==item['size']
            valid=valid and (item['object_size'],item['etag'],item['mtime'])==(row['size'],row['etag'],row['mtime'])
            if valid:
                identity=_json(_version(path.stat()))
                if identity!=item['identity']:
                    valid=_hash_file(path)[0]==item['sha256']
                    if valid:db.execute('UPDATE ranges SET identity=? WHERE asset_id=? AND start=? AND end=?',(identity,row['id'],item['start'],item['end']))
            if not valid:
                self._remove_cached_file(root,row['id'],path)
                db.execute('DELETE FROM ranges WHERE asset_id=? AND start=? AND end=?',(row['id'],item['start'],item['end']));return None
        source=next((s for s in self._settings(root)['sources'] if s['id']==row['source_id']),None)
        if cache_first:
            self._queue_cache_check(root,row,item['verified'])
        if not cache_first and source and source.get('enabled',True) and time.time()-item['verified']>=self.cache_ttl:
            try:
                provider=self._provider(row['source_id'],root);remote=provider.stat(row['path'])
            except RemoteStorageError as error:
                self.connections[row['source_id']]={**self.connections.get(row['source_id'],{}),'state':error.state,'code':error.code,'checked_at':time.time()}
                if error.state not in {'unreachable','auth_required'}:raise
            else:
                self._root(root)
                self._connection_ready(root,row['source_id'],context=provider.connection_context)
                with self.lock,self._db(root) as db:
                    self._require_current(self._resolve(db,asset_id=row['id']),row)
                    if (remote['size'],remote['etag'],remote['mtime'])!=(row['size'],row['etag'],row['mtime']):
                        self._upsert(db,row['source_id'],remote,state=row['state'])
                        row.update(dict(db.execute('SELECT * FROM assets WHERE id=?',(row['id'],)).fetchone()))
                        for old in db.execute('SELECT file FROM ranges WHERE asset_id=?',(row['id'],)).fetchall():self._remove_cached_file(root,row['id'],self._state('cache',old[0]))
                        db.execute('DELETE FROM ranges WHERE asset_id=?',(row['id'],));return None
                    db.execute('UPDATE ranges SET verified=? WHERE asset_id=? AND start=? AND end=?',(time.time(),row['id'],item['start'],item['end']))
        with self.lock,self._db(root) as db:
            self._require_current(self._resolve(db,asset_id=row['id']),row)
            descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
            with os.fdopen(descriptor,'rb') as stream:
                stream.seek(start-item['start']);data=stream.read(end-start+1)
            if len(data)!=end-start+1:raise ConflictError('Attachment range cache changed')
            db.execute('UPDATE ranges SET accessed=? WHERE asset_id=? AND start=? AND end=?',(time.time(),row['id'],item['start'],item['end']))
        return data

    def _store_range(self,root,row,start,end,data):
        maximum=self._settings(root)['cache_max_bytes']
        if not data or len(data)>maximum:return
        with self.lock:
            self._root(root);self._evict(root,reserve=len(data))
            directory=self._state('cache');directory.mkdir(parents=True,exist_ok=True,mode=0o700)
            filename=uuid.uuid4().hex+'.range';path=self._state('cache',filename)
            with path.open('xb') as dst:dst.write(data);dst.flush();os.fsync(dst.fileno())
            private_file_mode(path)
            with self._db(root) as db:
                current=self._resolve(db,asset_id=row['id'])
                try:self._require_current(current,row)
                except Exception:path.unlink(missing_ok=True);raise
                if (current['size'],current['etag'],current['mtime'])!=(row['size'],row['etag'],row['mtime']):
                    path.unlink(missing_ok=True);raise ConflictError('Attachment metadata changed')
                previous=db.execute('SELECT file FROM ranges WHERE asset_id=? AND start=? AND end=?',(row['id'],start,end)).fetchone()
                if previous:self._remove_cached_file(root,row['id'],self._state('cache',previous[0]))
                db.execute('INSERT OR REPLACE INTO ranges VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                           (row['id'],start,end,filename,len(data),row['size'],hashlib.sha256(data).hexdigest(),row['etag'],row['mtime'],time.time(),time.time(),_json(_version(path.stat()))))

    def _evict(self,root,keep='',reserve=0):
        maximum=max(0,self._settings(root)['cache_max_bytes']-reserve)
        with self._db(root) as db:
            items=db.execute("SELECT asset_id,file,size,accessed,'cache' AS kind,0 AS start,0 AS end FROM cache UNION ALL SELECT asset_id,file,size,accessed,'ranges' AS kind,start,end FROM ranges ORDER BY accessed").fetchall();total=sum(r['size'] for r in items)
            for item in items:
                if total<=maximum:break
                if item['asset_id']==keep or self.cache_readers.get((str(root),item['asset_id'])):continue
                self._cache_file_path(root,item['file']).unlink(missing_ok=True)
                if item['kind']=='cache':db.execute('DELETE FROM cache WHERE asset_id=?',(item['asset_id'],))
                else:db.execute('DELETE FROM ranges WHERE asset_id=? AND start=? AND end=?',(item['asset_id'],item['start'],item['end']))
                total-=item['size']

    def clear_cache(self,root):
        self._root(root)
        with self.lock,self._db(root) as db:
            items=list(db.execute('SELECT * FROM cache').fetchall())
            ranges=list(db.execute('SELECT * FROM ranges').fetchall())
            for item in items:self._remove_cached_file(root,item['asset_id'],self._cache_file_path(root,item['file']))
            for item in ranges:self._remove_cached_file(root,item['asset_id'],self._state('cache',item['file']))
            db.execute('DELETE FROM cache')
            db.execute('DELETE FROM ranges')
        return {'cleared':len(items)+len(ranges),'outbox_preserved':True,'vault_cache_cleared':True}

    def _outbox_usage(self):
        directory=self._state('outbox')
        if not directory.exists():return 0
        return sum(p.stat().st_size for p in directory.iterdir() if not is_link(p) and p.is_file())

    def _job_save(self,db,value):
        # Explicit cancel removes the durable job; do not recreate it from an
        # in-flight worker that finishes after DELETE.
        if value['id'] in self.cancelled or value.get('state')=='cancelled':
            value['state']='cancelled'
            db.execute('DELETE FROM jobs WHERE id=?',(value['id'],))
            return
        value['updated_at']=time.time()
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,payload=excluded.payload,updated=excluded.updated',
                   (value['id'],value['kind'],value['state'],_json(value),value['created_at'],value['updated_at']))

    @staticmethod
    def _public_job(value):
        result={k:copy.deepcopy(v) for k,v in value.items() if k not in {'credential_revision','source_revision','workspace_revision','source_version','guards','_speed_marks','_transfer_saved_at','_last_speed_bps','_last_speed_at'}}
        if result.get('state') in {'running','completed'}:result.pop('error',None)
        result.update(job_id='remote:'+value['id'],remote_saved=value['kind']=='upload' and value['state']=='completed')
        if value.get('requested_path'):result['path']=value['requested_path']
        return result

    def _report_transfer(self,value,*,sent=0,total=0,item=None,force=False,phase=None):
        now=time.time()
        released=sum(i.get('size',0) for i in value.get('items',[]) if i.get('state')=='released')
        previous_phase=(value.get('transfer') or {}).get('phase') or ''
        current_phase=phase if phase is not None else previous_phase
        phase_changed=phase is not None and current_phase!=previous_phase
        # During readback, the file is already on the server; keep overall bytes at
        # released+size while file_bytes track the verify download.
        if current_phase=='verifying':
            bytes_done=released+(total or 0);file_done=sent;speed_basis=released+sent
        else:
            bytes_done=released+max(0,min(sent,total or sent));file_done=sent;speed_basis=bytes_done
        bytes_total=value.get('total_bytes') or sum(i.get('size',0) for i in value.get('items',[]))
        if phase_changed:
            value['_speed_marks']=[];value.pop('_last_speed_bps',None);value.pop('_last_speed_at',None)
        marks=value.setdefault('_speed_marks',[])
        previous=marks[-1][1] if marks else None
        marks.append([now,speed_basis])
        while len(marks)>1 and now-marks[0][0]>5:marks.pop(0)
        if len(marks)>=2 and marks[-1][0]>marks[0][0]:
            speed=(marks[-1][1]-marks[0][1])/(marks[-1][0]-marks[0][0])
        else:speed=0.0
        if speed>0:
            value['_last_speed_bps']=speed;value['_last_speed_at']=now
        elif value.get('_last_speed_bps') and now-value.get('_last_speed_at',0)<4:
            speed=value['_last_speed_bps']
        else:speed=0.0
        value['transfer']={'bytes_done':bytes_done,'bytes_total':bytes_total,'file_bytes_done':file_done,'file_bytes_total':total,
                           'speed_bps':max(0.0,speed),'phase':current_phase,
                           'path':(item or {}).get('path') or value.get('requested_path'),'updated_at':now}
        last=value.get('_transfer_saved_at',0)
        moved=previous is None or speed_basis!=previous
        if force or (total and sent>=total) or sent==0 or (moved and now-last>=0.25) or phase_changed:
            value['_transfer_saved_at']=now
            with self.lock,self._db(value['root']) as db:self._job_save(db,value)

    def _new_job(self,root,source_id,owner,kind):
        source=self._source(source_id,root)
        if source_id=='local':raise ValueError('Select a remote attachment source')
        credentials=self.credentials.get(source_id)
        return {'id':uuid.uuid4().hex,'kind':kind,'root':str(root),'source_id':source_id,'owner':owner,
                'workspace_revision':self.config.data.get('revision',''),'source_revision':self._source_revision(source),
                'credential_revision':credentials[2] if credentials else '',
                'state':'queued','created_at':time.time(),'updated_at':time.time()}

    def _check_job(self,value,*,authorize=True):
        self._root(value['root'])
        if value['kind']=='upload' and value.get('attachment_upload',True):require_allowed(self._files(),value['requested_path'])
        if value['kind']=='migration':
            for item in value.get('items',[]):
                if item['state']!='released':require_allowed(self._files(),item['path'])
        if self.stopped.is_set():raise InterruptedError('Attachment storage stopped')
        if value['id'] in self.cancelled:raise InterruptedError('Attachment transfer cancelled')
        if value['workspace_revision']!=self.config.data.get('revision',''):
            raise ConflictError('Attachment workspace settings changed')
        source=self._source(value['source_id'],value['root'])
        if self._source_revision(source)!=value['source_revision']:raise ConflictError('Attachment source settings changed')
        if authorize:
            guard=self.guards.get(value['id'])
            if guard is not None:
                if guard() is False:raise PermissionError('Attachment owner authorization expired')
            elif value['owner']!='local':
                if not callable(self.authorize_owner) or self.authorize_owner(value['root'],value['owner'],value['workspace_revision']) is False:
                    raise PermissionError('Attachment owner authorization expired')
            credentials=self.credentials.get(value['source_id'])
            if not credentials:raise RemoteStorageError('credentials_required','auth_required')
            if credentials[3] not in {'local',value['owner']}:raise PermissionError('Attachment credentials belong to another owner')
            if value['credential_revision'] and credentials[2]!=value['credential_revision']:
                raise PermissionError('Attachment source credentials changed')
            if not value['credential_revision']:value['credential_revision']=credentials[2]

    def queue_upload(self,root,source_id,path,local_path,*,owner='local',guard=None,idempotency_key='',fingerprint='',attachment=True):
        self._root(root);path=remote_path(path,allow_empty=False)
        if not isinstance(owner,str) or not 1<=len(owner)<=256:raise ValueError('Invalid attachment owner')
        if (not isinstance(idempotency_key,str) or not isinstance(fingerprint,str) or
                len(idempotency_key)>512 or len(fingerprint)>512 or bool(idempotency_key)!=bool(fingerprint)):
            raise ValueError('Provide a bounded idempotency key and fingerprint together')
        if idempotency_key:
            with self.lock,self._db(root) as db:
                previous=db.execute('SELECT fingerprint,job_id FROM upload_receipts WHERE owner=? AND operation_key=?',(owner,idempotency_key)).fetchone()
                if previous:
                    if previous['fingerprint']!=fingerprint:raise ConflictError('Upload operation key was already used with different arguments')
                    result=json.loads(db.execute('SELECT payload FROM jobs WHERE id=?',(previous['job_id'],)).fetchone()[0])
                    return self._public_job(result)
        if attachment:require_allowed(self._files(),path)
        value=self._new_job(root,source_id,owner,'upload');value['attachment_upload']=attachment;value['asset_id']=uuid.uuid4().hex
        value['requested_path']=path
        source=self._source(source_id,root);name=PurePosixPath(path).name
        # Opaque unique keys keep retries from overwriting an existing object.
        value['remote_path']='/'.join(p for p in (source['upload_directory'],value['id']+'-'+name) if p)
        directory=self._state('outbox');directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        staged=self._state('outbox',value['id']+'.blob')
        # Stage outside the manager lock so paste/upload hashing and copies do not
        # stall note opens and other attachment reads that share the same lock.
        try:
            size,value['sha256']=self._stage_upload(root,local_path,staged,guard)
            value['size']=size
        except Exception:
            staged.unlink(missing_ok=True)
            raise
        with self.lock:
            if attachment:require_allowed(self._files(),path)
            if guard is not None:self.guards[value['id']]=guard
            try:
                with self._db(root) as db:
                    if idempotency_key:
                        previous=db.execute('SELECT fingerprint,job_id FROM upload_receipts WHERE owner=? AND operation_key=?',(owner,idempotency_key)).fetchone()
                        if previous:
                            if previous['fingerprint']!=fingerprint:raise ConflictError('Upload operation key was already used with different arguments')
                            staged.unlink(missing_ok=True)
                            return self._public_job(json.loads(db.execute('SELECT payload FROM jobs WHERE id=?',(previous['job_id'],)).fetchone()[0]))
                    item={'path':value['remote_path'],'size':size,'mtime':'','mime':mimetypes.guess_type(name)[0] or 'application/octet-stream'}
                    self._upsert(db,source_id,item,asset_id=value['asset_id'],sha256=value['sha256'],state='pending')
                    old=db.execute('SELECT asset_id FROM aliases WHERE path=?',(path,)).fetchone()
                    if old:raise ConflictError('Attachment logical path already exists')
                    db.execute('INSERT INTO aliases VALUES(?,?)',(path,value['asset_id']))
                    # Staging bytes sit under `_attachments` for the note link while
                    # upload is pending. After promote, note-sized images stay as
                    # vault cache; larger/non-image originals drop to thumbnails.
                    self._job_save(db,value)
                    if idempotency_key:db.execute('INSERT INTO upload_receipts VALUES(?,?,?,?)',(owner,idempotency_key,fingerprint,value['id']))
            except Exception:
                staged.unlink(missing_ok=True);self.guards.pop(value['id'],None);raise
        self.wake.set();return self._public_job(value)

    def _stage_upload(self,root,original,staged,guard=None):
        """A failed staging attempt must not consume durable outbox quota."""
        created=False
        try:
            if isinstance(original,(bytes,bytearray)):
                size=len(original);source=None
            else:
                original=Path(original)
                if is_link(original) or not original.is_file():raise ValueError('Upload source must be a regular file')
                size=original.stat().st_size;source=original
            if self._outbox_usage()+size>self._settings(root)['outbox_max_bytes']:raise ValueError('Attachment outbox is full')
            if size+1024*1024>shutil.disk_usage(staged.parent).free:raise ValueError('Insufficient space for attachment outbox')
            if guard is not None:guard()
            if source is None:
                digest=hashlib.sha256()
                with staged.open('xb') as dst:
                    created=True;digest.update(original);dst.write(original);dst.flush();os.fsync(dst.fileno())
                private_file_mode(staged)
                return size,digest.hexdigest()
            # Prefer a same-volume hard link so paste returns after one hash instead
            # of copy + three full reads. Falls back to a single-pass copy+hash.
            try:
                os.link(source,staged)
                created=True
                private_file_mode(staged)
                digest,version=_hash_file(staged)
                if _version(source.stat())!=version:raise ConflictError('Upload source changed')
                return size,digest
            except OSError:
                if created:
                    staged.unlink(missing_ok=True);created=False
            digest=hashlib.sha256()
            descriptor=os.open(source,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
            with os.fdopen(descriptor,'rb') as src,staged.open('xb') as dst:
                created=True
                before_version=_version(os.fstat(src.fileno()))
                while chunk:=src.read(1024*1024):
                    if guard is not None:guard()
                    digest.update(chunk);dst.write(chunk)
                dst.flush();os.fsync(dst.fileno())
                if _version(os.fstat(src.fileno()))!=before_version:raise ConflictError('Upload source changed')
            if _version(source.stat())!=before_version:raise ConflictError('Upload source changed')
            private_file_mode(staged)
            return size,digest.hexdigest()
        except Exception:
            if created:staged.unlink(missing_ok=True)
            raise

    def snapshot_local_metadata(self,root,paths):
        """Read local identities for a move journal without creating a manifest."""
        self._root(root);path=self._state('manifest.sqlite')
        if not path.is_file():return {}
        if not isinstance(paths,(list,tuple,set)) or len(paths)>10000:raise ValueError('Invalid attachment metadata paths')
        result={}
        with self.lock:
            db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10)
            try:
                for value in paths:
                    value=relative(value)
                    if not value:raise ValueError('Select an attachment path')
                    rows=db.execute("SELECT path,id FROM assets WHERE source_id='local' AND (path=? OR (path>=? AND path<?))",
                                    (value,value+'/',value+'0')).fetchall()
                    result.update(dict(rows))
            finally:db.close()
        return result

    def sync_local_paths(self,root,moves):
        """Keep local metadata identities through explicit completed moves/undo."""
        self._root(root)
        if isinstance(moves,dict):moves=[{'source':old,'destination':new} for old,new in moves.items()]
        if not isinstance(moves,list) or len(moves)>10000:raise ValueError('Invalid attachment metadata moves')
        normalized=[(relative(move['source']),relative(move['destination']),move.get('asset_id','')) for move in moves]
        if any(not old or not new or (key and not re.fullmatch('[0-9a-f]{32}',key)) for old,new,key in normalized):
            raise ValueError('Invalid attachment metadata move path')
        changed=0
        with self.lock,self._db(root) as db:
            expanded=[]
            for old,new,expected_id in normalized:
                rows=db.execute("SELECT * FROM assets WHERE source_id='local' AND (path=? OR (path>=? AND path<?))",(old,old+'/',old+'0')).fetchall()
                for row in rows:
                    if expected_id and row['id']!=expected_id:continue
                    expanded.append((row['path'],new+row['path'][len(old):],row))
            for old,new,row in expanded:
                if old==new:continue
                other=db.execute("SELECT id FROM assets WHERE source_id='local' AND path=?",(new,)).fetchone()
                alias=db.execute('SELECT asset_id FROM aliases WHERE path=?',(new,)).fetchone()
                if (other and other[0]!=row['id']) or (alias and alias[0]!=row['id']):
                    raise ConflictError('Destination has different attachment metadata; existing records retained')
                target=self.config.path_for(new)
                if not target.is_file():raise ConflictError('Moved attachment is unavailable')
                info=target.stat()
                db.execute('UPDATE assets SET path=?,name=?,size=?,mtime=?,mtime_ns=?,metadata_revision=?,updated=? WHERE id=?',
                           (new,PurePosixPath(new).name,info.st_size,str(info.st_mtime_ns),info.st_mtime_ns,uuid.uuid4().hex,time.time(),row['id']))
                # A completed rename changes its old local alias. Other aliases
                # remain attached to the same durable identity.
                db.execute('DELETE FROM aliases WHERE path=? AND asset_id=?',(old,row['id']))
                db.execute('INSERT OR REPLACE INTO aliases VALUES(?,?)',(new,row['id']));changed+=1
        return {'updated':changed}

    def job(self,root,key,action='',owner='local',guard=None):
        if not re.fullmatch('[0-9a-f]{32}',str(key)):raise ValueError('Invalid attachment job ID')
        reset=False
        with self.lock,self._db(root) as db:
            row=db.execute('SELECT payload FROM jobs WHERE id=?',(key,)).fetchone()
            if not row:raise FileNotFoundError('Attachment job not found')
            value=json.loads(row[0])
            if value['root']!=str(root):raise ConflictError('Attachment job belongs to another folder')
            if owner!=value['owner']:raise PermissionError('Attachment job belongs to another owner')
            if action:
                if action not in {'execute','resume','cancel'}:raise ValueError('Invalid attachment job action')
                if action=='cancel':
                    value['state']='cancelled';self.cancelled.add(key)
                    db.execute('DELETE FROM jobs WHERE id=?',(key,))
                    self.wake.set();return self._public_job(value)
                if value['state']=='completed':return self._public_job(value)
                if guard is not None:self.guards[key]=guard
                self.cancelled.discard(key)
                if action=='execute' and value['kind']=='migration':value['confirmed']=True
                value['workspace_revision']=self.config.data.get('revision','')
                value['source_revision']=self._source_revision(self._source(value['source_id'],root))
                current=self.credentials.get(value['source_id']);value['credential_revision']=current[2] if current else ''
                self._check_job(value,authorize=False);value['state']='queued';value.pop('error',None)
                reset=True
                for field in ('retry_attempts','next_retry_at','retry_paused'):value.pop(field,None)
                self._job_save(db,value)
        if reset:self._reset_connection(root,value['source_id'])
        self.wake.set();return self._public_job(value)

    def jobs(self,root,owner='local'):
        with self.lock,self._db(root) as db:
            # Cancel removes jobs; purge any leftover cancelled rows from older builds.
            db.execute("DELETE FROM jobs WHERE state='cancelled'")
            values=[]
            for row in db.execute('SELECT id,payload FROM jobs ORDER BY created DESC').fetchall():
                value=json.loads(row[1])
                if value.get('state')=='cancelled':
                    db.execute('DELETE FROM jobs WHERE id=?',(row[0],))
                    continue
                values.append(value)
        return [self._public_job(v) for v in values if v['owner']==owner]

    def _run_upload(self,value):
        root=value['root'];self._check_job(value)
        staged=self._state('outbox',value['id']+'.blob')
        if not staged.is_file() or _hash_file(staged)[0]!=value['sha256']:raise ConflictError('Attachment outbox bytes changed')
        provider=self._provider(value['source_id'],root,guard=lambda:self._check_job(value))
        # A previous PUT may have succeeded before a crash. Read the existing
        # unique object back rather than overwriting or trusting its existence.
        try:
            meta=provider.stat(value['remote_path'])
        except RemoteStorageError as error:
            if error.code!='remote_not_found':raise
            meta=None
        if meta is not None:
            if meta['size']<value['size']:
                self._verify_partial(provider,value['remote_path'],staged,meta['size'])
                old=value['remote_path'];value.setdefault('remote_orphans',[]).append(old)
                source=self._source(value['source_id'],root)
                value['remote_path']='/'.join(p for p in (source['upload_directory'],uuid.uuid4().hex+'-'+PurePosixPath(value['requested_path']).name) if p)
                with self.lock,self._db(root) as db:
                    db.execute('UPDATE assets SET path=?,updated=? WHERE id=?',(value['remote_path'],time.time(),value['asset_id']))
                    self._job_save(db,value)
                result=provider.upload(value['remote_path'],staged,expected_sha256=value['sha256'])
            else:result=provider.checksum(value['remote_path'],expected_size=value['size'],expected_sha256=value['sha256'])
        else:result=provider.upload(value['remote_path'],staged,expected_sha256=value['sha256'])
        self._check_job(value)
        with self.lock,self._db(root) as db:
            self._check_job(value)
            self._upsert(db,value['source_id'],result,asset_id=value['asset_id'],sha256=value['sha256'])
            # The catalog is already current. Only the changed directory and
            # ancestors need a fresh receipt, never unrelated cached branches.
            parts=value['remote_path'].split('/')
            db.executemany('INSERT OR REPLACE INTO discovery_changes VALUES(?,?,?)',
                           [(value['source_id'],'/'.join(parts[:depth]),time.time()) for depth in range(len(parts))])
        from vault_rag.attachment_server_references import publish
        publish(self,root,value['source_id'],value['asset_id'],provider)
        try:
            from vault_rag.attachment_server_catalog import publish_member
            publish_member(self,root,value['source_id'],value['asset_id'],provider)
        except (ConflictError,ValueError,RemoteStorageError):
            # Membership publish retries with the job; references already landed.
            raise
        self._check_job(value)
        with self.lock,self._db(root) as db:
            self._check_job(value)
            value['state']='completed';value['verified']=True;value.pop('error',None)
            for field in ('retry_attempts','next_retry_at','retry_paused'):value.pop(field,None)
            self._job_save(db,value)
        # Staging under `_attachments` backs the pending note link. After promote,
        # keep note-sized images as vault cache so embeds stay local; drop larger
        # / non-image staging so the device keeps membership + thumbnails only.
        self._drop_upload_staging(root,value)
        staged.unlink(missing_ok=True)
        self._connection_ready(root,value['source_id'],context=provider.connection_context)

    _NOTE_IMAGE_SUFFIXES=frozenset({'.png','.jpg','.jpeg','.gif','.webp','.bmp','.tif','.tiff','.avif'})
    _NOTE_IMAGE_CACHE_MAX=16*1024*1024

    def _drop_local_original(self,root,*,path,asset_id=''):
        """Drop vault originals after server authority; keep only lightweight previews.

        Full originals return only when the user explicitly caches them. Catalog
        import/sync never downloads bytes—this only removes leftover staging copies.
        """
        if not path or path.startswith(self.config.data.get('attachment_folder','_attachments')+'/_remote/'):
            return
        try:
            vault=self.config.path_for(path)
        except (ValueError,OSError):
            return
        if vault.is_file() and Path(path).suffix.lower() in self._NOTE_IMAGE_SUFFIXES:
            try:
                workspace=getattr(getattr(self.runtime,'files',None),'workspace',None)
                if workspace is not None:
                    workspace.thumbnail(root,path)
            except Exception:
                pass
        if vault.is_file():
            self._remove_cached_file(root,asset_id,vault)
            parent=vault.parent
            try:
                if parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                pass
        if asset_id:
            with self.lock,self._db(root) as db:
                row=db.execute('SELECT file FROM cache WHERE asset_id=?',(asset_id,)).fetchone()
                if row and self._is_vault_cache(row[0]):
                    db.execute('DELETE FROM cache WHERE asset_id=?',(asset_id,))
        changed=getattr(getattr(self.runtime,'files',None),'changed',None)
        if callable(changed):changed(path)

    def _retain_vault_staging(self,root,*,path,asset_id=''):
        """Keep pasted note images as same-origin vault cache after promote."""
        if not path or not asset_id:return False
        if Path(path).suffix.lower() not in self._NOTE_IMAGE_SUFFIXES:return False
        try:
            vault=self.config.path_for(path)
        except (ValueError,OSError):
            return False
        if not vault.is_file() or is_link(vault):return False
        try:
            if vault.stat().st_size>self._NOTE_IMAGE_CACHE_MAX:return False
        except OSError:
            return False
        try:
            workspace=getattr(getattr(self.runtime,'files',None),'workspace',None)
            if workspace is not None:workspace.thumbnail(root,path)
        except Exception:
            pass
        with self.lock,self._db(root) as db:
            row=db.execute('SELECT * FROM assets WHERE id=?',(asset_id,)).fetchone()
            if not row or not vault.is_file():return False
            self._register_vault_cache(db,row,vault,sha256=row['sha256'] or '',verified=time.time(),alias=path)
        changed=getattr(getattr(self.runtime,'files',None),'changed',None)
        if callable(changed):changed(path)
        return True

    def _drop_upload_staging(self,root,value):
        """Keep note-sized image staging as vault cache; drop other originals."""
        path=value.get('requested_path') or ''
        asset_id=value.get('asset_id','')
        if self._retain_vault_staging(root,path=path,asset_id=asset_id):return
        self._drop_local_original(root,path=path,asset_id=asset_id)

    def _job_retry_due(self,value):
        if value.get('state') not in {'waiting_for_connection','waiting_for_auth'}:return True
        if value['source_id'] not in self.credentials:return False
        state=self._connection_state(value['root'],value['source_id'])
        return not state.get('retry_paused') and (state['state']!='unreachable' or (state.get('next_retry_at') or 0)<=time.time())

    def _defer_job(self,value,error):
        # Slow networks and timeouts must not discard work. Only auth failures
        # pause automatic retries; everything else waits and resumes.
        if isinstance(error,RemoteStorageError) and error.state=='auth_required':
            value['state']='waiting_for_auth';value['error']=error.code
        else:
            value['state']='waiting_for_connection'
            value['error']=getattr(error,'code',None) or 'connection_unavailable'
        state=self._connection_state(value['root'],value['source_id'])
        attempts=int(value.get('retry_attempts') or state.get('retry_attempts') or 0)+1
        value['retry_attempts']=attempts
        value['next_retry_at']=time.time()+min(3600,max(5,2**min(attempts,10)))
        value['retry_paused']=bool(state.get('retry_paused')) if value['state']=='waiting_for_auth' else False

    @staticmethod
    def _verify_partial(provider,path,local,size):
        """Recognize our incomplete unique object without mutating it."""
        digest=hashlib.sha256();remaining=size
        descriptor=os.open(local,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
        with os.fdopen(descriptor,'rb') as stream:
            while remaining:
                provider.guard();chunk=stream.read(min(1024*1024,remaining))
                if not chunk:raise ConflictError('Upload prefix is unavailable')
                digest.update(chunk);remaining-=len(chunk)
        provider.checksum(path,expected_size=size,expected_sha256=digest.hexdigest())

    def _loop(self):
        while not self.stopped.is_set():
            self.wake.wait(3);self.wake.clear()
            if self.stopped.is_set():break
            try:
                self.process_cache_checks()
                self.poll_connections()
                self.poll_scans()
                self.process_pending()
            except Exception:pass  # Persisted job states contain sanitized errors.

    def process_pending(self):
        if not self.worker_lock.acquire(blocking=False):return
        try:
            root=self._root()
            with self.lock,self._db(root) as db:
                values=[json.loads(r[0]) for r in db.execute("SELECT payload FROM jobs WHERE kind='upload' AND state IN ('queued','waiting_for_connection','waiting_for_auth','uploading','verifying') ORDER BY created")]
            for value in values:
                if self.stopped.is_set():break
                if value.get('next_retry_at') and value['next_retry_at']>time.time() and value.get('state')=='waiting_for_connection':
                    continue
                if not self._job_retry_due(value):continue
                try:self._run_upload(value)
                except RemoteStorageError as error:
                    self._defer_job(value,error)
                except PermissionError:
                    value['state']='waiting_for_authorization';value['error']='owner_or_credentials_changed'
                except AttachmentTypeError:
                    value['state']='conflict';value['error']='attachment_file_type_not_allowed'
                except (ConflictError,ValueError,FileNotFoundError):
                    value['state']='conflict';value['error']='attachment_or_settings_changed'
                except InterruptedError:
                    value['state']='cancelled' if value['id'] in self.cancelled else 'waiting_for_connection'
                    value['error']='transfer_cancelled' if value['id'] in self.cancelled else 'service_stopped'
                    if value['state']=='waiting_for_connection':
                        value['retry_attempts']=int(value.get('retry_attempts') or 0)+1
                        value['next_retry_at']=time.time()+min(3600,max(5,2**min(value['retry_attempts'],10)))
                except (TimeoutError,OSError,ConnectionError) as error:
                    self._defer_job(value,RemoteStorageError('connection_unavailable','unreachable',reason=type(error).__name__))
                except Exception:
                    # Treat unexpected transport faults as retryable; never drop
                    # slow WAN uploads as terminal failures.
                    self._defer_job(value,RemoteStorageError('attachment_operation_failed','unreachable'))
                with self.lock,self._db(root) as db:self._job_save(db,value)
        finally:self.worker_lock.release()
        # Confirmed migrations may resume after reconnection/restart. Planning
        # alone never grants authority to upload or release an original.
        with self.lock,self._db(root) as db:
            migrations=[json.loads(r[0]) for r in db.execute("SELECT payload FROM jobs WHERE kind='migration' AND state IN ('queued','running','waiting_for_connection','waiting_for_auth')")]
        for value in migrations:
            if value.get('confirmed') and not self.stopped.is_set() and self._job_retry_due(value):
                self.migrate(root,value['id'],owner=value['owner'])

    def migration_plan(self,root,source_id,paths=None,*,owner='local',guard=None):
        from vault_rag.attachment_migrations import ASSETS,SOURCE_MARKERS,SOURCE_RESOURCE_TYPES
        from vault_rag.attachment_references import OPAQUE_RESOURCE_TYPES,discover_project_dependencies
        self._root(root);files=self._files();extensions=extensions_for(files);value=self._new_job(root,source_id,owner,'migration')
        folder=self.config.data.get('attachment_folder','_attachments')
        folder_key=path_key(folder)
        def collect_attachment_paths():
            directory=files.config.path_for(folder)
            if not directory.is_dir():return set()
            return {p.relative_to(files.config.root).as_posix() for p in files.walk(folder,strict=True)}
        # Remote migration previews only the attachment folder (plus nested project
        # trees inside it). Whole-vault walks made preview slow and over-protected.
        if paths is None:
            scoped=collect_attachment_paths()
            selected=set(scoped)
        else:
            selected={relative(p) for p in paths}
            scoped=set(selected)
            if any(under(p,folder) for p in selected):scoped|=collect_attachment_paths()
        if len(selected)>10000:raise ValueError('Select at most 10000 attachments')
        project_marker={'.html','.htm'}|SOURCE_RESOURCE_TYPES
        project_roots=set()
        for entry in scoped:
            if Path(entry).suffix.lower() in project_marker or PurePosixPath(entry).name in SOURCE_MARKERS:
                project=entry.rpartition('/')[0]
                if not project or project in {'.',''}:continue
                if path_key(project)==folder_key:continue
                if under(project,folder):project_roots.add(project)
        websites=getattr(self.runtime,'websites',None)
        registered_roots=set()
        if websites:
            for project in websites.projects:
                if project.get('vault')!=str(root):continue
                directory=relative(project.get('directory') or '')
                if not directory or directory in {'.',''}:continue
                if path_key(directory)==folder_key:continue
                # Always retain registered HTML trees and their attachment-folder
                # dependencies; HTML/Design assets stay project-local, not NAS-bound.
                registered_roots.add(directory)
                project_roots.add(directory)
        # Include project files outside the attachment folder so dependency discovery
        # can protect shared central copies referenced by those projects.
        dependency_paths=set(scoped)
        if registered_roots:
            for directory in registered_roots:
                base=files.config.path_for(directory)
                if not base.is_dir():continue
                for path in files.walk(directory,strict=True):
                    dependency_paths.add(path.relative_to(files.config.root).as_posix())
        reference_sources={p for p in dependency_paths if Path(p).suffix.lower() not in OPAQUE_RESOURCE_TYPES|{'.md','.markdown'}}
        protected=discover_project_dependencies(files,dependency_paths,project_roots,reference_sources=reference_sources)
        remote_aliases={}
        with self.lock,self._db(root) as db:
            for path in selected:
                row=db.execute("SELECT a.source_id,a.state FROM aliases al JOIN assets a ON a.id=al.asset_id WHERE al.path=?",(path,)).fetchone()
                if row:remote_aliases[path]=(row[0],row[1])
        value.update(state='planned',items=[],exclusions=[],blockers=protected['blockers'],completed=0)
        for path in sorted(selected):
            original=files.config.path_for(path)
            source_state=remote_aliases.get(path)
            if source_state and (source_state[0]!='local' or source_state[1]=='redirected'):
                value['exclusions'].append({'path':path,'reason':'Already on the attachment server'});continue
            if not original.is_file() or is_link(original):
                value['exclusions'].append({'path':path,'reason':'Attachment path not found'});continue
            if path in protected['protected']:
                value['exclusions'].append({'path':path,'reason':'Preserved HTML project resource or shared runtime dependency'});continue
            if Path(path).suffix.lower() not in ASSETS or not allows(path,extensions):
                value['exclusions'].append({'path':path,'reason':'File type is not enabled for attachments'});continue
            digest,version=_hash_file(original)
            value['items'].append({'path':path,'size':version[2],'sha256':digest,'source_version':version,'state':'planned'})
        value['total_bytes']=sum(item['size'] for item in value['items'])
        if guard is not None:self.guards[value['id']]=guard
        with self.lock,self._db(root) as db:self._job_save(db,value)
        result=self._public_job(value)
        # This is a preview only: no remote PUT, copy, rename or deletion.
        result['confirmation_required']=True;return result

    def migrate(self,root,key,*,owner='local',guard=None):
        self._root(root)
        with self.lock,self._db(root) as db:
            row=db.execute("SELECT payload FROM jobs WHERE id=? AND kind='migration'",(key,)).fetchone()
            if not row:raise FileNotFoundError('Attachment migration plan not found')
            value=json.loads(row[0])
        if value['owner']!=owner:raise PermissionError('Attachment plan belongs to another owner')
        if guard is not None:self.guards[key]=guard
        if value.get('blockers'):raise ConflictError('Resolve project dependency blockers before migration')
        if value['state']=='completed':return self._public_job(value)
        if not self.worker_lock.acquire(blocking=False):raise ConflictError('Another attachment transfer is running')
        try:
            value['confirmed']=True;value['state']='running';value.pop('error',None)
            for field in ('retry_attempts','next_retry_at','retry_paused'):value.pop(field,None)
            with self.lock,self._db(root) as db:self._job_save(db,value)
            self._check_job(value)
            for item in value['items']:
                if item['state']=='released':continue
                if item['state'] not in {'mapped','releasing'}:item['state']='uploading'
                self._report_transfer(value,sent=0,total=item.get('size',0),item=item,force=True,phase='hashing')
                self._check_job(value);self._migrate_one(value,item)
                value['completed']=sum(i['state']=='released' for i in value['items'])
                self._report_transfer(value,sent=0,total=0,item=None,force=True,phase='')
            value['state']='completed';value.pop('error',None);value.pop('transfer',None)
            for field in ('_speed_marks','_transfer_saved_at','_last_speed_bps','_last_speed_at'):value.pop(field,None)
            self._connection_ready(root,value['source_id'],context=(str(root),value['source_id'],value['source_revision'],value['credential_revision']))
        except RemoteStorageError as error:
            self._defer_job(value,error)
        except PermissionError:value['state']='waiting_for_authorization';value['error']='owner_or_credentials_changed'
        except InterruptedError:value['state']='cancelled' if key in self.cancelled else 'waiting_for_connection';value['error']='transfer_stopped'
        except (ConflictError,ValueError,FileNotFoundError):value['state']='conflict';value['error']='attachment_or_settings_changed'
        except Exception:value['state']='failed';value['error']='attachment_operation_failed'
        finally:
            with self.lock,self._db(root) as db:self._job_save(db,value)
            self.worker_lock.release()
        return self._public_job(value)

    def _migrate_one(self,value,item):
        root=value['root'];source=self.config.path_for(item['path']);files=self._files()
        require_allowed(files,item['path'])
        # Repair journals written by the earlier scan/upload race as well as
        # using the canonical identity for new migrations. A release filename
        # is an independent recovery key and must retain its existing value.
        if item.get('remote_path') and item.get('state') in {'mapped','releasing'}:
            with self.lock,self._db(root) as db:
                actual=db.execute('SELECT id FROM assets WHERE source_id=? AND path=?',(value['source_id'],item['remote_path'])).fetchone()
                if actual and item.get('asset_id')!=actual[0]:
                    item['asset_id']=actual[0];self._job_save(db,value)
                if actual:
                    old=db.execute("SELECT id FROM assets WHERE source_id='local' AND path=? AND state!='redirected'",(item['path'],)).fetchone()
                    if old:self._record_redirect(db,old[0],actual[0],item['path'],value['id'])
        # Crash recovery for older releases that moved bytes into a claim file:
        # restore them as a vault-path cache instead of deleting.
        if item.get('release_file'):
            claim=self._state('release',item['release_file'])
            if claim.exists():
                if _hash_file(claim)[0]!=item['sha256']:
                    if not source.exists():move_exclusive(claim,source)
                    raise ConflictError('Source changed during migration release')
                if not source.exists():move_exclusive(claim,source)
                elif _hash_file(source)[0]!=item['sha256']:raise ConflictError('A new local source appeared during migration')
                else:claim.unlink(missing_ok=True)
                self._check_job(value)
                provider=self._provider(value['source_id'],root,guard=lambda:self._check_job(value))
                from vault_rag.attachment_server_references import publish
                from vault_rag.attachment_server_catalog import publish_member
                publish(self,root,value['source_id'],item['asset_id'],provider)
                publish_member(self,root,value['source_id'],item['asset_id'],provider)
                with self.lock,self._db(root) as db:self._activate_redirects(db,item['asset_id'])
                self._finish_release(value,item);return
        # A releasing journal has already verified bytes and published mappings.
        # The local cache may be absent after a previous finish attempt. Never
        # remove a different file which appeared at the old path meanwhile.
        if item['state']=='releasing':
            if source.exists() and _hash_file(source)[0]!=item['sha256']:
                raise ConflictError('A new local source appeared during migration')
            self._check_job(value)
            self._finish_release(value,item);return
        size=item.get('size',0)
        self._report_transfer(value,sent=0,total=size,item=item,force=True,phase='hashing')
        current_hash,current_version=_hash_file(source)
        if current_hash!=item['sha256'] or current_version!=item['source_version']:raise ConflictError('Source changed since migration planning')
        provider=self._provider(value['source_id'],root,guard=lambda:self._check_job(value))
        if item['state'] not in {'mapped','releasing'}:
            if not item.get('remote_path'):
                remote=self._source(value['source_id'],root)
                item['remote_path']='/'.join(p for p in (remote['upload_directory'],uuid.uuid4().hex+'-'+source.name) if p)
                item['asset_id']=uuid.uuid4().hex
                with self.lock,self._db(root) as db:self._job_save(db,value)
            check_dir=self._state('migration');check_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
            self._report_transfer(value,sent=0,total=size,item=item,force=True,phase='probing')
            try:remote_meta=provider.stat(item['remote_path']);exists=True
            except RemoteStorageError as error:
                if error.code!='remote_not_found':raise
                exists=False
            if exists and remote_meta['size']<item['size']:
                self._verify_partial(provider,item['remote_path'],source,remote_meta['size'])
                item.setdefault('remote_orphans',[]).append(item['remote_path'])
                remote=self._source(value['source_id'],root)
                item['remote_path']='/'.join(p for p in (remote['upload_directory'],uuid.uuid4().hex+'-'+source.name) if p)
                with self.lock,self._db(root) as db:self._job_save(db,value)
                exists=False
            if exists:
                self._report_transfer(value,sent=0,total=size,item=item,force=True,phase='verifying')
                result=provider.checksum(item['remote_path'],expected_size=item['size'],expected_sha256=item['sha256'],
                                         progress=lambda sent,total:self._report_transfer(value,sent=sent,total=total,item=item,phase='verifying'))
            else:
                def on_phase(phase):
                    self._report_transfer(value,sent=0,total=size,item=item,force=True,phase=phase)
                result=provider.upload(item['remote_path'],source,expected_sha256=item['sha256'],
                                       progress=lambda sent,total:self._report_transfer(value,sent=sent,total=total,item=item,phase='uploading'),
                                       on_phase=on_phase,
                                       verify_progress=lambda sent,total:self._report_transfer(value,sent=sent,total=total,item=item,phase='verifying'))
            self._check_job(value)
            # Commit identities before dropping local originals (preview-only default).
            with self.lock,self._db(root) as db:
                asset_id=self._upsert(db,value['source_id'],result,asset_id=item['asset_id'],sha256=item['sha256'],state='migration_pending')
                item['asset_id']=asset_id
                old=db.execute('SELECT asset_id FROM aliases WHERE path=?',(item['path'],)).fetchone()
                if old and old[0]!=asset_id:
                    previous=db.execute('SELECT * FROM assets WHERE id=?',(old[0],)).fetchone()
                    if not previous or previous['source_id']!='local':raise ConflictError('Existing attachment alias conflicts')
                    db.execute('UPDATE assets SET description=?,tags=?,category=?,metadata_revision=?,updated=? WHERE id=?',
                               (previous['description'],previous['tags'],previous['category'],previous['metadata_revision'],time.time(),asset_id))
                    db.execute('UPDATE aliases SET asset_id=? WHERE asset_id=?',(asset_id,old[0]))
                    self._record_redirect(db,old[0],asset_id,item['path'],value['id'])
                db.execute('INSERT OR REPLACE INTO aliases VALUES(?,?)',(item['path'],asset_id))
                item['state']='mapped';self._job_save(db,value)
        self._check_job(value)
        provider=self._provider(value['source_id'],root,guard=lambda:self._check_job(value))
        from vault_rag.attachment_server_references import publish
        from vault_rag.attachment_server_catalog import publish_member
        publish(self,root,value['source_id'],item['asset_id'],provider)
        publish_member(self,root,value['source_id'],item['asset_id'],provider)
        self._check_job(value)
        if _hash_file(source)!=(item['sha256'],item['source_version']):raise ConflictError('Local attachment changed before release')
        item['state']='releasing'
        with self.lock,self._db(root) as db:
            self._job_save(db,value)
            self._activate_redirects(db,item['asset_id'])
        self._finish_release(value,item)

    def _finish_release(self,value,item):
        """Authority is on the server; local originals are removed unless the user caches them."""
        root=value['root'];self._root(root);item['state']='released';item.pop('release_file',None)
        with self.lock,self._db(root) as db:
            db.execute('UPDATE assets SET state=\'ready\',updated=? WHERE id=?',(time.time(),item['asset_id']))
            self._activate_redirects(db,item['asset_id'])
            self._job_save(db,value)
        self._drop_local_original(root,path=item['path'],asset_id=item['asset_id'])

    def stop(self):
        self.stopped.set();self.wake.set();deadline=time.monotonic()+2
        self.thread.join(timeout=max(0,deadline-time.monotonic()))
        with self.lock:threads=list(self.scan_threads.values())
        for thread in threads:thread.join(timeout=max(0,deadline-time.monotonic()))
        with self.lock:self.credentials.clear();self.guards.clear();self.cache_checks.clear()
