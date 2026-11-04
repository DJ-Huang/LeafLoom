"""Device-local directory checkpoints. Cache hits never authorize original bytes.

Servers without a change feed need eventual directory revalidation. An unfinished
pass reuses committed directories regardless of age; unchanged directories back
off independently, up to a week. Parent ETags never stand in for descendant changes.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import ExitStack
import hashlib
import json
import sqlite3
import threading
import time
import uuid

from vault_rag.attachment_scan_policy import SCAN_INTERVAL, MAX_DIRECTORY_INTERVAL, idle_interval
from vault_rag.remote_ignore import IGNORE_NAME, MAX_IGNORE_BYTES, IgnoreRuleError, RemoteIgnore
from vault_rag.remote_webdav import RemoteStorageError, remote_path

DIRECTORY_TTL = SCAN_INTERVAL
DIRECTORY_WORKERS = 2


def discovery_context(root, source_revision, credential_revision, metadata_directory):
    return hashlib.sha256(json.dumps([str(root),source_revision,credential_revision,metadata_directory]).encode()).hexdigest()


class DirectoryCheckpoints:
    def __init__(self, path, source_id, context, check, *, force_full=False, upload_directory=None):
        self.source_id,self.context,self.check=source_id,context,check
        self.upload_directory=upload_directory
        self.db=sqlite3.connect(path,timeout=15);self.db.row_factory=sqlite3.Row
        try:
            check()
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS discovery_changes(source_id TEXT NOT NULL,path TEXT NOT NULL,changed_at REAL NOT NULL,PRIMARY KEY(source_id,path));
                CREATE TABLE IF NOT EXISTS discovery_intervals(source_id TEXT NOT NULL,path TEXT NOT NULL,
                    checked_at REAL NOT NULL,check_interval REAL NOT NULL,PRIMARY KEY(source_id,path));
                CREATE TABLE IF NOT EXISTS discovery_runs(source_id TEXT PRIMARY KEY,context TEXT NOT NULL,
                    cycle TEXT NOT NULL,mode TEXT NOT NULL,complete INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS discovery_directories(source_id TEXT NOT NULL,path TEXT NOT NULL,
                    context TEXT NOT NULL,cycle TEXT NOT NULL,checked_at REAL NOT NULL,entries TEXT NOT NULL,
                    rule BLOB,PRIMARY KEY(source_id,path));
            ''')
            previous=self.db.execute('SELECT * FROM discovery_runs WHERE source_id=?',(source_id,)).fetchone()
            valid=previous is not None and previous['context']==context
            self.resumed=bool(valid and not previous['complete'] and not force_full)
            if self.resumed:self.cycle,self.mode=previous['cycle'],previous['mode']
            else:
                self.cycle=uuid.uuid4().hex
                populated=self.db.execute('SELECT 1 FROM discovery_directories WHERE source_id=? AND context=? LIMIT 1',(source_id,context)).fetchone()
                self.mode='full' if force_full or not populated else 'incremental'
            with self.db:
                check()
                if not valid:
                    self.db.execute('DELETE FROM discovery_directories WHERE source_id=?',(source_id,))
                    self.db.execute('DELETE FROM discovery_intervals WHERE source_id=?',(source_id,))
                self.db.execute('INSERT OR REPLACE INTO discovery_runs VALUES(?,?,?,?,0)',(source_id,context,self.cycle,self.mode))
        except BaseException:self.db.close();raise

    @property
    def label(self):return 'resume' if self.resumed else self.mode

    def interval_limit(self, path):
        upload=self.upload_directory
        # Check the upload tree and its ancestors promptly, including a newly
        # created upload directory. Other branches age independently.
        hot=upload is not None and (not path or not upload or path==upload or path.startswith(upload+'/') or upload.startswith(path+'/'))
        return DIRECTORY_TTL if hot else MAX_DIRECTORY_INTERVAL

    def load(self, path):
        if self.db.execute('SELECT 1 FROM discovery_changes WHERE source_id=? AND path=?',(self.source_id,path)).fetchone():return None
        row=self.receipt(path)
        if row is None:return None
        interval=min(self.interval_limit(path),max(DIRECTORY_TTL,row['check_interval']))
        if row['cycle']!=self.cycle and (self.mode=='full' or time.time()-row['checked_at']>=interval):return None
        try:
            if len(row['entries'])>32*1024*1024:raise ValueError
            entries=json.loads(row['entries'])
            if not isinstance(entries,list) or not all(isinstance(item,dict) for item in entries):raise ValueError
            if not any(item.get('path')==path and item.get('is_dir') is True for item in entries):raise ValueError
            for item in entries:
                rel=remote_path(item['path'])
                child=rel[len(path)+1:] if path and rel!=path else rel
                if rel!=path and (path and not rel.startswith(path+'/') or '/' in child):raise ValueError
                if type(item.get('is_dir'))is not bool or type(item.get('size'))is not int or item['size']<0:raise ValueError
            rule=bytes(row['rule']) if row['rule'] is not None else None
            if rule is not None and len(rule)>MAX_IGNORE_BYTES:raise ValueError
            return entries,rule,row['checked_at']
        except (ValueError,TypeError,KeyError):
            self.invalidate(path);return None

    def receipt(self, path):
        # Keep the original receipt schema readable/writable by older releases.
        # If one rewrites a receipt, its old adaptive interval no longer applies.
        return self.db.execute('''SELECT d.*,COALESCE(i.check_interval,?) AS check_interval FROM discovery_directories d
            LEFT JOIN discovery_intervals i ON i.source_id=d.source_id AND i.path=d.path AND i.checked_at=d.checked_at
            WHERE d.source_id=? AND d.path=? AND d.context=?''',(DIRECTORY_TTL,self.source_id,path,self.context)).fetchone()

    def invalidate(self, directory):
        self.check()
        with self.db:
            for table in ('discovery_directories','discovery_intervals'):
                self.db.execute(f'DELETE FROM {table} WHERE source_id=? AND (path=? OR substr(path,1,?)=?)',
                                (self.source_id,directory,len(directory)+1,directory+'/'))
                if not directory:self.db.execute(f'DELETE FROM {table} WHERE source_id=?',(self.source_id,))
            self.check()

    def failed_directory(self, directory, error):
        if directory and isinstance(error,RemoteStorageError) and error.code=='remote_not_found':
            # A cached parent may still name a directory deleted externally.
            # Re-read that parent on resume rather than retrying the missing
            # child forever inside the same unfinished cycle.
            self.check()
            with self.db:
                self.db.execute('DELETE FROM discovery_directories WHERE source_id=? AND path=?',
                                (self.source_id,directory.rpartition('/')[0]))

    def save(self, path, entries, rule, checked_at):
        # Publish only after the corresponding manifest batch committed. A crash
        # before this receipt costs a re-read, never a skipped uncommitted batch.
        self.check()
        before=self.receipt(path)
        interval=DIRECTORY_TTL
        if before:
            try:
                def signature(items):
                    # Directory validators are not recursive change signals.
                    return sorted((item['path'],item['is_dir'],
                        *(str(item.get(key,'')) if not item['is_dir'] else '' for key in ('size','etag','mtime','mime')))
                        for item in items if item['path']!=path)
                unchanged=signature(json.loads(before['entries']))==signature(entries) and before['rule']==rule
                interval=idle_interval(before['check_interval'],changed=not unchanged,maximum=self.interval_limit(path))
                old={item['path'] for item in json.loads(before['entries']) if item['is_dir'] and item['path']!=path}
                new={item['path'] for item in entries if item['is_dir'] and item['path']!=path}
                for directory in old-new:self.invalidate(directory)
            except (ValueError,TypeError,KeyError):self.invalidate(path)
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO discovery_directories VALUES(?,?,?,?,?,?,?)',
                (self.source_id,path,self.context,self.cycle,checked_at,json.dumps(entries,ensure_ascii=False,separators=(',',':')),rule))
            self.db.execute('INSERT OR REPLACE INTO discovery_intervals VALUES(?,?,?,?)',(self.source_id,path,checked_at,interval))
            # A local upload racing this read keeps its dirty marker for the
            # next pass; a pre-existing change has now been observed.
            self.db.execute('DELETE FROM discovery_changes WHERE source_id=? AND path=? AND changed_at<=?',(self.source_id,path,checked_at))
            self.check()

    def complete(self):
        self.check()
        with self.db:
            self.db.execute('UPDATE discovery_runs SET complete=1 WHERE source_id=? AND context=? AND cycle=?',
                            (self.source_id,self.context,self.cycle))
            self.check()

    def close(self):self.db.close()

    def scan(self, provider, path='', *, max_files=100000,max_depth=32,on_batch=None,ignore=None,prune_reserved=True,read_ignore=True):
        path=remote_path(path);pending=[(path,0)];remote_pending=[];seen=set();result=[];active={}
        reserved=(provider.source['metadata_directory'],) if prune_reserved else ()
        ignore=ignore or RemoteIgnore(reserved);provider.ignore_checks=[];provider.scan_checkpoint=self
        excluded=0;reused=0;resources=[];resources_lock=threading.Lock();local=threading.local()

        def fetch(directory):
            provider.guard()
            started=time.time()
            if not hasattr(local,'provider'):
                local.provider=provider.fork();stack=ExitStack()
                with resources_lock:resources.append(stack)
                stack.enter_context(local.provider.session())
            peer=local.provider
            entries=peer._propfind(directory,retry_timeouts=2)
            rule=None
            if read_ignore:
                for item in entries:
                    if item['path']!=directory and not item['is_dir'] and item['name']==IGNORE_NAME:
                        if item['size']>MAX_IGNORE_BYTES:raise RemoteStorageError('ignore_rules_too_large')
                        try:rule=peer._ignore_bytes(item['path'],expected_etag=item.get('etag',''))
                        except RemoteStorageError as error:
                            if error.code!='remote_not_found':raise
                        break
            peer.guard()
            return entries,rule,started

        def accept(directory, depth, data, cached):
            nonlocal excluded,reused
            self.check();entries,rule,checked_at=data;batch=[]
            if not any(item['path']==directory and item['is_dir'] for item in entries):raise RemoteStorageError('incomplete_webdav_listing')
            for item in entries:
                rel=remote_path(item['path'])
                if rel==directory:continue
                if directory and not rel.startswith(directory+'/'):raise RemoteStorageError('out_of_scope_href')
                child=rel[len(directory)+1:] if directory else rel
                if '/' in child:raise RemoteStorageError('out_of_scope_href')
            if rule is not None:
                try:ignore.add(directory,rule)
                except IgnoreRuleError as error:raise RemoteStorageError(str(error)) from None
                provider.ignore_checks.append(('/'.join(p for p in (directory,IGNORE_NAME) if p),hashlib.sha256(rule).hexdigest()))
            seen.add(directory);reused+=int(cached)
            for item in entries:
                rel=item['path']
                if rel==directory or any(rel==prefix or rel.startswith(prefix+'/') for prefix in reserved):continue
                if item['is_dir']:pending.append((rel,depth+1))
                else:
                    item={**item,'excluded':ignore.excluded(rel),'ignore_control':item['name']==IGNORE_NAME,'_directory_cached':cached}
                    excluded+=int(item['excluded']);result.append(item);batch.append(item)
                if len(result)+len(pending)+len(remote_pending)+len(active)>max_files:raise RemoteStorageError('directory_count_limit')
            counts={'scanned':len(result),'directories':len(seen),'pending_directories':len(pending)+len(remote_pending)+len(active),
                    'excluded':excluded,'cached_directories':reused,'scan_mode':self.label}
            if on_batch is not None:on_batch(batch,counts)
            if not cached:self.save(directory,entries,rule,checked_at)

        try:
            with ThreadPoolExecutor(max_workers=DIRECTORY_WORKERS,thread_name_prefix='attachment-directory') as workers:
                try:
                    while pending or remote_pending or active:
                        self.check()
                        # Drain cached branches before waiting on the network so
                        # reconnecting immediately restores the prior progress.
                        while pending:
                            directory,depth=pending.pop()
                            if directory in seen or any(entry[0]==directory for entry in active.values()):continue
                            if depth>max_depth:raise RemoteStorageError('directory_depth_limit')
                            cached=self.load(directory)
                            if cached is not None:accept(directory,depth,cached,True)
                            else:remote_pending.append((directory,depth))
                        while remote_pending and len(active)<DIRECTORY_WORKERS:
                            directory,depth=remote_pending.pop()
                            active[workers.submit(fetch,directory)]=(directory,depth)
                        if not active:continue
                        completed,_=wait(active,return_when=FIRST_COMPLETED)
                        # Commit every successful result even if a sibling's
                        # connection failed, leaving only failed work to retry.
                        failure=None
                        for future in completed:
                            directory,depth=active.pop(future)
                            try:accept(directory,depth,future.result(),False)
                            except BaseException as error:
                                self.failed_directory(directory,error);failure=failure or error
                        if failure is not None:
                            # The other bounded worker may already have completed
                            # useful work. Journal it before returning the error.
                            for future,(directory,depth) in list(active.items()):
                                try:accept(directory,depth,future.result(),False)
                                except BaseException as error:self.failed_directory(directory,error)
                                active.pop(future,None)
                            raise failure
                finally:
                    for future in active:future.cancel()
        finally:
            for resource in resources:resource.close()
        return result
