"""Durable, owner-scoped delivery to a configured directory, never a caller path."""
from __future__ import annotations

from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import threading
import time
import uuid

from vault_rag.local_state import atomic_write, ConflictError
from vault_rag.platform_support import is_link, move_exclusive, downloads_directory
from vault_rag.asset_search import signature

_ID = re.compile(r'^[0-9a-f]{32}$')
_PENDING = {'queued','downloading','copying','verifying'}


def checked_directory(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Choose an absolute delivery directory')
    for component in [*reversed(path.parents), path]:
        if is_link(component):
            raise ValueError('Delivery directory cannot contain a link or junction')
        if component.exists() and not component.is_dir():
            raise ValueError('Delivery directory must be a folder')
    return path


class AssetDeliveries:
    def __init__(self, files):
        self.files = files
        self.lock = threading.RLock()
        self.copy_lock = threading.Lock()
        self.stopped = threading.Event()
        self.threads, self.guards, self.grants = {}, {}, {}
        self.device = self._device()

    def _device(self):
        path = self.files.config.directory/'asset-device.json'
        if is_link(path):
            raise ValueError('Invalid device identity path')
        try:
            value = json.loads(path.read_text())
        except FileNotFoundError:
            value = {'id':uuid.uuid4().hex}
            atomic_write(path,json.dumps(value).encode())
        return {'id':value['id'],'name':socket.gethostname(),'path_location':'service_host'}

    def directory(self):
        return self.files.runtime.files.state_path('asset-deliveries')

    def settings(self):
        path = self.files.runtime.files.state_path('asset-deliveries','settings.json')
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            return {'directory':str(downloads_directory()/'LeafLoomAssets'),'revision':'initial'}

    def configure(self, directory, revision, *, root=None):
        target = checked_directory(directory)
        if target==Path(target.anchor) or any(part in {'.vault-rag','.git'} for part in target.parts):
            raise ValueError('Choose a dedicated delivery folder')
        with self.lock, self.files.config.lock:
            if root is not None and str(self.files.config.root)!=root:
                raise ConflictError('Connected folder changed')
            current = self.settings()
            if current['revision']!=revision:
                raise ConflictError('Delivery settings changed; reload before saving')
            target.mkdir(parents=True,exist_ok=True)
            checked_directory(target)
            value = {'directory':str(target),'revision':uuid.uuid4().hex}
            self.directory().mkdir(parents=True,exist_ok=True)
            atomic_write(self.files.runtime.files.state_path('asset-deliveries','settings.json'),json.dumps(value).encode())
        return value

    def _path(self, job_id):
        if not _ID.fullmatch(job_id):
            raise ValueError('Invalid delivery ID')
        return self.files.runtime.files.state_path('asset-deliveries',job_id+'.json')

    def _load(self, job_id):
        return json.loads(self._path(job_id).read_text())

    def _save(self, job):
        job['revision'] = uuid.uuid4().hex
        job['updated_at'] = time.time()
        self.directory().mkdir(parents=True,exist_ok=True)
        atomic_write(self._path(job['job_id']),json.dumps(job,ensure_ascii=False).encode())

    def _check(self, job, guard=None):
        f = self.files
        if str(f.config.root)!=job['root'] or f.notes.workspace_revision!=job['workspace_revision']:
            raise ConflictError('Delivery workspace changed')
        if not f.remote.authorize_owner(job['root'],job['owner'],job['workspace_revision']):
            raise PermissionError('Delivery write permission was revoked')
        if guard:
            guard()
        settings = self.settings()
        if settings != job['settings']:
            raise ConflictError('Delivery directory changed; create a new delivery request')
        checked_directory(settings['directory'])
        if job['state']=='cancelled' or self.stopped.is_set():
            raise InterruptedError('Delivery cancelled or service stopped')

    def _visible(self, job, owner):
        if owner!='local' and job['owner']!=owner:
            raise FileNotFoundError('Delivery is unavailable for this credential')
        if str(self.files.config.root)!=job['root']:
            raise FileNotFoundError('Delivery belongs to another workspace')

    def _public(self, job):
        keys = ('job_id','state','revision','name','size','copied','sha256','created_at','updated_at','error','error_code','source_revision')
        result = {k:job[k] for k in keys if k in job}
        result['device'] = self.device
        result['source'] = {'path':job['source_path'],'asset_id':job.get('asset_id','')}
        if job['state']=='completed':
            target = Path(job['settings']['directory'])/job['job_id']/job['name']
            try:
                checked_directory(target.parent)
                info = target.lstat()
                valid = stat.S_ISREG(info.st_mode) and [info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns]==job['published_identity']
            except (OSError,ValueError):
                valid = False
            if valid:
                result['local_path'] = str(target)
                result['verified'] = True
            else:
                result.update(state='unavailable',verified=False,error='Delivered file was removed or changed')
        return result

    def create(self, request, revision, operation_id, owner, guard, grant=None):
        settings = self.settings()
        fingerprint = signature([request.model_dump(),revision,settings])
        job_id = signature([str(self.files.config.root),owner,operation_id])[:32]
        with self.lock:
            if grant:self.grants[job_id]=grant
            try:
                old = self._load(job_id)
            except FileNotFoundError:
                old = None
            if old:
                self._visible(old,owner)
                if old['fingerprint']!=fingerprint:
                    raise ConflictError('Delivery operation_id was reused with different arguments or settings')
                self._start(old,guard)
                return self._public(old)
            if sum(t.is_alive() for t in self.threads.values())>=20:
                raise ValueError('Too many active deliveries')
            info = self.files._stat(request.path,revision)
            if info['revision']!=request.expected_revision:
                raise ConflictError('Source changed; get fresh asset details')
            # Select only a current catalog member; direct arbitrary filesystem paths are never accepted.
            if not any(r['path']==request.path for r in self.files.asset_search._attachments()):
                raise FileNotFoundError('Source is outside the current asset catalog')
            self.files._name(info['name'])
            job = {'job_id':job_id,'owner':owner,'root':str(self.files.config.root),'workspace_revision':revision,
                   'fingerprint':fingerprint,'settings':settings,'source_path':request.path,'source_revision':info['revision'],
                   'asset_id':info.get('asset_id','') if info.get('storage_id','local')!='local' else '',
                   'name':info['name'],'size':info['size'],'copied':0,'sha256':'','state':'queued',
                   'created_at':time.time(),'error':''}
            self._check(job,guard)
            self._save(job)
            self._start(job,guard)
            return self._public(job)

    def _start(self, job, guard=None):
        key = job['job_id']
        if self.stopped.is_set() or job['state'] not in _PENDING or self.threads.get(key,threading.Thread()).is_alive():
            return
        if guard:
            self.guards[key] = guard
        thread = threading.Thread(target=self._run,args=(job['root'],key),name='asset-delivery',daemon=True)
        self.threads[key] = thread
        thread.start()

    def status(self, job_id, owner, guard=None, grant=None):
        with self.lock:
            job = self._load(job_id)
            self._visible(job,owner)
            if guard:
                guard()
            if owner==job['owner']:
                if grant:self.grants[job_id]=grant
                self._start(job,guard)
            return self._public(job)

    def listing(self, root):
        if str(self.files.config.root)!=root:
            raise ConflictError('Connected folder changed')
        directory = self.directory()
        jobs = []
        if directory.exists():
            for path in directory.glob('*.json'):
                if _ID.fullmatch(path.stem):
                    job = self._load(path.stem)
                    jobs.append(self._public(job))
        return sorted(jobs,key=lambda j:j['created_at'],reverse=True)[:100]

    def control(self, request, owner, guard, *, operation_id, grant=None):
        with self.lock:
            job = self._load(request.job_id)
            self._visible(job,owner)
            if grant:self.grants[job['job_id']]=grant
            previous = job.get('last_control',{})
            fingerprint = signature(request.model_dump())
            if previous.get('operation_id')==operation_id:
                if previous['fingerprint']!=fingerprint:
                    raise ConflictError('Control operation_id was reused with different arguments')
                guard()
                return self._public(job)
            if job['revision']!=request.expected_revision:
                raise ConflictError('Delivery changed; refresh its status')
            if job['state']=='completed':
                return self._public(job)
            job['last_control']={'operation_id':operation_id,'fingerprint':fingerprint}
            if request.command=='cancel':
                guard()
                job.update(state='cancelled',error='')
                self._save(job)
            else:
                if self.threads.get(job['job_id'],threading.Thread()).is_alive():
                    raise ConflictError('Wait for the current delivery attempt to stop')
                if job['owner']!=owner:
                    raise PermissionError('Retry requires the creating credential')
                job['state']='queued'
                self._check(job,guard)
                job['error']=''
                self._save(job)
                self._start(job,guard)
            return self._public(job)

    def _source(self, job, guard):
        f = self.files
        if f._stat(job['source_path'],job['workspace_revision'])['revision']!=job['source_revision']:
            raise ConflictError('Source changed; create a new delivery request')
        if job['asset_id']:
            downloads = f.asset_downloads
            staged = downloads.prepare(job['root'],job['asset_id'],owner=job['owner'],guard=guard)
            with self.lock:
                guard()
                job['state']='downloading'
                self._save(job)
            while staged['state'] in {'queued','downloading'}:
                guard()
                if self.stopped.wait(.25):
                    raise InterruptedError()
                staged = downloads.status(job['root'],staged['job_id'],owner=job['owner'],guard=guard)
            if staged['state']!='ready' or not staged.get('handle'):
                raise ValueError('Remote download is not ready; retry after resolving its connection or capacity')
            lease = downloads.acquire_handle(job['root'],staged['handle'],owner=job['owner'],guard=guard)
            return lease['path'], lease, staged['sha256']
        return f._path(job['source_path'])[1], None, ''

    def _run(self, root, job_id):
        lease, part = None, None
        job = None
        def guard():
            with self.lock:
                current = self._load(job_id)
                self._check(current,self.guards.get(job_id))
        try:
            with self.lock:
                job = self._load(job_id)
            guard()
            source, lease, expected_sha = self._source(job,guard)
            with self.copy_lock:
                guard()
                target_dir = checked_directory(Path(job['settings']['directory'])/job_id)
                target_dir.mkdir(parents=True,exist_ok=True)
                checked_directory(target_dir)
                target = target_dir/job['name']
                if target.exists() or is_link(target):
                    # Recover only a previously journaled publication, never adopt a caller's file.
                    if not job.get('publish_sha256') or is_link(target):
                        raise ConflictError('Delivery target already exists')
                    with target.open('rb') as stream:
                        checksum = hashlib.file_digest(stream,'sha256').hexdigest()
                    if checksum!=job['publish_sha256'] or target.stat().st_size!=job['size']:
                        raise ConflictError('Delivery publication was changed')
                else:
                    if shutil.disk_usage(target_dir).free < job['size']+5*1024**3:
                        raise ValueError('Insufficient delivery disk space; 5 GiB must remain free')
                    part = target_dir/('.'+uuid.uuid4().hex+'.part')
                    descriptor = os.open(source,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
                    with os.fdopen(descriptor,'rb') as src, part.open('xb') as dst:
                        before = os.fstat(src.fileno())
                        current = source.lstat()
                        if not stat.S_ISREG(before.st_mode) or (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns) or before.st_size!=job['size']:
                            raise ConflictError('Source changed while opening')
                        checksum, copied = hashlib.sha256(), 0
                        while data := src.read(1024*1024):
                            guard()
                            checked_directory(target_dir)
                            dst.write(data)
                            checksum.update(data)
                            copied += len(data)
                            with self.lock:
                                guard()
                                job.update(state='copying',copied=copied)
                                self._save(job)
                        dst.flush()
                        os.fsync(dst.fileno())
                        after = os.fstat(src.fileno())
                        if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                            raise ConflictError('Source changed during delivery')
                    checksum = checksum.hexdigest()
                    if copied!=job['size'] or (expected_sha and checksum!=expected_sha):
                        raise ConflictError('Delivery checksum mismatch')
                    guard()
                    if self.files._stat(job['source_path'],job['workspace_revision'])['revision']!=job['source_revision']:
                        raise ConflictError('Source changed before publication')
                    with part.open('rb') as stream:
                        if hashlib.file_digest(stream,'sha256').hexdigest()!=checksum:
                            raise ConflictError('Delivery readback checksum mismatch')
                    with self.grants.get(job_id,nullcontext)(), self.lock, self.files.config.lock:
                        guard()
                        if self.files._stat(job['source_path'],job['workspace_revision'])['revision']!=job['source_revision']:
                            raise ConflictError('Source changed before publication')
                        job.update(state='verifying',publish_sha256=checksum)
                        self._save(job)
                        checked_directory(target_dir)
                        move_exclusive(part,target)
                with self.grants.get(job_id,nullcontext)(), self.lock, self.files.config.lock:
                    guard()
                    info = target.stat()
                    job.update(state='completed',sha256=job['publish_sha256'],copied=job['size'],error='',error_code='',
                               published_identity=[info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns])
                    self._save(job)
        except Exception as error:
            if job is not None and str(self.files.config.root)==root:
                with self.lock:
                    try:
                        current = self._load(job_id)
                        if current['state']!='cancelled':
                            code, message = ('delivery_failed','Delivery stopped; check the source and connection before retrying')
                            if isinstance(error,PermissionError):
                                code,message = ('authorization_revoked','Delivery paused because write access was revoked')
                            elif isinstance(error,ConflictError):
                                code,message = ('write_conflict','Source, directory settings or destination changed; retrieve fresh details')
                            elif isinstance(error,ValueError) and str(error).startswith('Insufficient delivery disk space'):
                                code,message = ('insufficient_disk_space','Insufficient delivery disk space; 5 GiB must remain free')
                            job.update(state='paused' if self.stopped.is_set() or isinstance(error,PermissionError) else 'failed',
                                       error=message,error_code=code)
                            self._save(job)
                    except (OSError,ValueError):
                        pass
        finally:
            if part is not None:
                try:
                    checked_directory(part.parent)
                    part.unlink(missing_ok=True)
                except (OSError,ValueError):
                    pass
            if lease:
                self.files.asset_downloads.release_handle(root,lease['job_id'])

    def stop(self):
        self.stopped.set()
        for thread in list(self.threads.values()):
            thread.join(timeout=2)
