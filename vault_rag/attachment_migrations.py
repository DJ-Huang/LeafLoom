"""Journaled, explicitly confirmed consolidation of standalone attachments.

Only disposable derived indexes are rebuilt. Original bytes and edited document
versions remain in the protected operation journal, including after rollback.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import threading
import time
import uuid

from vault_rag.local_state import Files, ConflictError, atomic_write, digest, relative, under
from vault_rag.platform_support import move_exclusive, path_key, preserve_file_mode

ASSETS = {'.png','.jpg','.jpeg','.gif','.webp','.avif','.bmp','.ico','.tif','.tiff',
          '.pdf','.mp3','.m4a','.wav','.ogg','.flac','.aac','.mp4','.mov','.webm','.m4v','.avi',
          '.doc','.docx','.xls','.xlsx','.ppt','.pptx','.odt','.ods','.odp',
          '.zip','.7z','.rar','.tar','.gz','.bz2','.epub','.woff','.woff2','.ttf','.otf'}
DOCUMENTS = {'.md','.markdown','.txt','.base','.html','.htm','.css','.svg','.js','.mjs','.cjs','.json','.yaml','.yml','.xml'}
SOURCE_MARKERS = {'package.json','pyproject.toml','Cargo.toml','go.mod','CMakeLists.txt'}
ACTIVE = {'planning','running','rolling_back'}
MAX_DOCUMENT = 10 * 1024 * 1024


def file_hash(path):
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Attachment must be a regular file')
        value = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
    if (before.st_size,before.st_mtime_ns,before.st_ino) != (after.st_size,after.st_mtime_ns,after.st_ino):
        raise ConflictError('File changed while reading: ' + path.name)
    return value


class AttachmentMigrations:
    def __init__(self, runtime, websites=None):
        self.runtime = runtime
        self.config = runtime.config
        self.websites = websites
        self.lock = threading.RLock()
        self.threads = {}
        self.cancels = {}

    def _files(self):
        with self.config.lock:
            config = copy.copy(self.config)
            config.data = dict(config.data)
        return Files(config)

    def _guard(self, root):
        if self.config.data.get('root') != root or str(self.config.root) != root:
            raise ConflictError('Connected folder changed; switch back before resuming this migration')

    def _directory(self, files, key):
        if not isinstance(key,str) or not re.fullmatch('[0-9a-f]{32}', key):
            raise ValueError('Invalid attachment migration ID')
        path = files.state_path('attachment-migrations', key)
        if path.exists() and os.name != 'nt' and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError('Migration journal directory must be private (mode 0700)')
        return path

    def _record(self, files, key):
        self._directory(files,key)
        return files.state_path('attachment-migrations',key,'manifest.json')

    def _save(self, files, job):
        with self.lock:
            job['updated_at'] = time.time()
            # Validate every internal path before writing the journal.
            path = self._record(files,job['id'])
            atomic_write(path,json.dumps(job,ensure_ascii=False,sort_keys=True).encode())

    def _load(self, files, key):
        with self.lock:
            path = self._record(files,key)
            job = json.loads(path.read_text(encoding='utf-8'))
            if job.get('id') != key or job.get('root') != str(files.config.root):
                raise ValueError('Migration journal belongs to a different folder')
            if job.get('version') != 1:
                raise ValueError('Unsupported attachment migration journal version')
            if job['state'] in ACTIVE and not self.threads.get(key,threading.Thread()).is_alive():
                job['state'] = 'interrupted'
                self._save(files,job)
            return job

    @staticmethod
    def _public(job):
        keys = ('id','root','destination','state','phase','progress','summary','error','created_at','updated_at','warnings')
        result = {k:job[k] for k in keys if k in job}
        result['moves'] = [{k:m[k] for k in ('source','destination','size')} for m in job.get('moves',[])[:200]]
        result['blockers'] = job.get('blockers',[])[:200]
        result['exclusions'] = job.get('exclusions',[])[:200]
        result['preview_limited'] = len(job.get('moves',[])) > 200
        return result

    def list(self):
        files=self._files();root=str(files.config.root)
        directory=files.state_path('attachment-migrations')
        if not directory.exists():return {'jobs':[]}
        jobs=[]
        for path in directory.iterdir():
            if not re.fullmatch('[0-9a-f]{32}',path.name):continue
            try:jobs.append(self._public(self._load(files,path.name)))
            except (OSError,ValueError):continue
        self._guard(root)
        return {'jobs':sorted(jobs,key=lambda j:j['created_at'],reverse=True)}

    def get(self,key):
        files=self._files();job=self._load(files,key);self._guard(job['root'])
        return self._public(job)

    def _start(self, files, job, action):
        with self.lock:
            if any(t.is_alive() for t in self.threads.values()):
                raise ConflictError('Another attachment migration is still running')
            cancel=threading.Event();self.cancels[job['id']]=cancel
            job['state']='planning' if action=='plan' else 'rolling_back' if action=='rollback' else 'running'
            job.pop('error',None);self._save(files,job)
            thread=threading.Thread(target=self._worker,args=(files,job,action,cancel),daemon=True,
                                    name='attachment-migration-'+job['id'][:8])
            self.threads[job['id']]=thread;thread.start()
        return self._public(job)

    def create(self,root,destination='_attachments'):
        self._guard(root);files=self._files();destination=relative(destination)
        if not destination:raise ValueError('Choose a dedicated attachment directory')
        path=files.config.path_for(destination,writable=True)
        if path.exists() and not path.is_dir():raise ValueError('Attachment destination is not a directory')
        key=uuid.uuid4().hex
        job={'version':1,'id':key,'root':root,'destination':destination,'state':'planning','phase':'planning',
             'created_at':time.time(),'progress':{'done':0,'total':0},'summary':{'files':0,'bytes':0,'notes':0},
             'moves':[],'edits':[],'documents':{},'blockers':[],'exclusions':[],
             'previous_attachment_folder':self.config.data.get('attachment_folder','_attachments')}
        self._directory(files,key).mkdir(parents=True,mode=0o700)
        return self._start(files,job,'plan')

    def action(self,key,action,root,confirm=False):
        self._guard(root);files=self._files();job=self._load(files,key)
        if action=='cancel':
            if job['state'] in ACTIVE:
                self.cancels.get(key,threading.Event()).set()
                return self._public(job)
            if job['state']=='ready':job['state']='cancelled';self._save(files,job)
            return self._public(job)
        if confirm is not True:raise ValueError('Explicit confirmation is required')
        allowed={'execute':{'ready'},'resume':{'interrupted','failed'},
                 'rollback':{'completed','interrupted','failed','conflict'}}
        if action not in allowed or job['state'] not in allowed[action]:
            raise ConflictError('Migration is not ready for this action')
        if job.get('blockers'):raise ConflictError('Resolve preview blockers before migrating')
        if action=='resume' and job['phase']=='planning':
            return self._start(files,job,'plan')
        if action=='resume' and job['phase']=='rollback':
            return self._start(files,job,'rollback')
        return self._start(files,job,'rollback' if action=='rollback' else 'execute')

    def _check(self,job,cancel):
        self._guard(job['root'])
        if cancel.is_set():raise InterruptedError('Migration cancelled')

    def _plan(self, files, job, cancel):
        from vault_rag.attachment_references import plan_references, discover_project_dependencies
        job.update(moves=[],edits=[],documents={},blockers=[],exclusions=[])
        # One onboarding job prepares the metadata database and migration plan.
        # This stage never moves source files; confirmation remains mandatory.
        def index_progress(done):
            self._check(job,cancel)
            job['progress']={'done':done,'total':0}
            self._save(files,job)
        with self.runtime.files.attachments.lock:
            self._check(job,cancel)
            self.runtime.files.attachments.refresh(cancel=cancel,progress=index_progress)
        self._check(job,cancel)
        root=files.config.root;target=job['destination'];paths=set()
        for path in files.walk(strict=True):
            self._check(job,cancel);paths.add(path.relative_to(root).as_posix())
        project_roots={str(PurePosixPath(p).parent) for p in paths if Path(p).suffix.lower() in ('.html','.htm')}
        project_roots={'' if p=='.' else p for p in project_roots}
        if self.websites:
            project_roots.update(p['directory'] for p in self.websites.projects if p['vault']==job['root'])
        source_roots={p.rpartition('/')[0] for p in paths if PurePosixPath(p).name in SOURCE_MARKERS}
        if any(under(target,p) for p in project_roots|source_roots):
            job['blockers'].append({'path':target,'reason':'Destination is inside an HTML or source project; choose another directory'})
        dependencies=discover_project_dependencies(files,paths,project_roots|source_roots)
        protected=dependencies['protected']
        job['blockers'].extend(dependencies['blockers'])
        candidates=[];reserved={path_key(p) for p in paths}
        for path in sorted(paths):
            suffix=Path(path).suffix.lower()
            if under(path,target):continue
            if suffix not in ASSETS:
                if suffix=='.svg':job['exclusions'].append({'path':path,'reason':'Vector resource retained for dependency review'})
                if suffix not in DOCUMENTS and suffix not in {'.py','.ts','.tsx','.jsx','.toml','.ini','.cfg','.log','.csv','.srt','.vtt'}:
                    job['exclusions'].append({'path':path,'reason':'Unknown or source format; not automatically classified as an attachment'})
                continue
            if path in protected:
                job['exclusions'].append({'path':path,'reason':'Preserved HTML project resource or shared runtime dependency'});continue
            if any(under(path,p) for p in source_roots):
                job['exclusions'].append({'path':path,'reason':'Preserved inside source project'});continue
            candidates.append(path)
        job['progress']={'done':0,'total':len(candidates)};self._save(files,job)
        for index,path in enumerate(candidates):
            self._check(job,cancel);source=files.config.path_for(path);size=source.stat().st_size;sha=file_hash(source)
            dest=target+'/'+path
            if path_key(dest) in reserved or files.config.path_for(dest).exists():
                original=PurePosixPath(dest);tag=hashlib.sha256(path.encode()).hexdigest()[:12];n=0
                while True:
                    name=original.stem+'--'+tag+('-'+str(n) if n else '')+original.suffix
                    dest=str(original.with_name(name));n+=1
                    if path_key(dest) not in reserved and not files.config.path_for(dest).exists():break
            files.config.path_for(dest,writable=True);reserved.add(path_key(dest))
            job['moves'].append({'source':path,'destination':dest,'size':size,'sha256':sha,'backup':str(index)})
            job['progress']['done']=index+1
            if index%20==0:self._save(files,job)
        mapping={m['source']:m['destination'] for m in job['moves']}
        scan_paths={p for p in paths if p not in protected}
        # Source/config files may refer outside their own project. Leave them
        # unchanged, but let unsupported reference checks block unsafe moves.
        scan_paths.update(p for p in paths if any(under(p,root) for root in source_roots) and Path(p).suffix.lower() in {'.json','.toml','.yaml','.yml','.ini','.cfg','.xml'})
        result=plan_references(files,mapping,paths,scan_paths=scan_paths)
        job['blockers'].extend(result['blockers'])
        for path in sorted(paths):
            if Path(path).suffix.lower() in ASSETS:continue
            p=files.config.path_for(path)
            if p.stat().st_size>MAX_DOCUMENT:
                job['blockers'].append({'path':path,'reason':'Document exceeds safe reference analysis limit'});continue
            job['documents'][path]=file_hash(p)
        for index,(path,edit) in enumerate(sorted(result['edits'].items())):
            self._check(job,cancel)
            before,after=edit['before'],edit['after']
            for kind,data in (('before',before),('after',after)):
                self._directory(files,job['id'])
                atomic_write(files.state_path('attachment-migrations',job['id'],'notes',str(index)+'.'+kind),data)
            job['edits'].append({'path':path,'before_hash':digest(before),'after_hash':digest(after),'backup':str(index)})
        job['summary']={'files':len(job['moves']),'bytes':sum(m['size'] for m in job['moves']),
                        'notes':len(job['edits']),'excluded':len(job['exclusions']),'blockers':len(job['blockers']),
                        'references':result.get('references',0)}
        job['state']='blocked' if job['blockers'] else 'ready';job['phase']='planned'
        self._save(files,job)

    def _note_bytes(self,files,job,edit,kind):
        path=files.state_path('attachment-migrations',job['id'],'notes',edit['backup']+'.'+kind)
        data=path.read_bytes()
        if digest(data)!=edit[kind+'_hash']:raise ConflictError('Migration document backup changed')
        return data

    def _backup(self,files,job,move):
        return files.state_path('attachment-migrations',job['id'],'originals',move['backup'])

    def _validate_documents(self,files,job,allow_after=True):
        edits={e['path']:e for e in job['edits']}
        current={p.relative_to(files.config.root).as_posix() for p in files.walk(strict=True)
                 if p.suffix.lower() not in ASSETS}
        if current!=set(job['documents']):raise ConflictError('Document list changed; preview again before moving attachments')
        for path,before in job['documents'].items():
            allowed={before}
            if allow_after and path in edits:allowed.add(edits[path]['after_hash'])
            if file_hash(files.config.path_for(path)) not in allowed:
                raise ConflictError('Document changed since preview: '+path)

    def _intent(self,files,job,move):
        return files.state_path('attachment-migrations',job['id'],'copy-intents',move['backup']+'.json')

    def _owned(self,files,job,move):
        intent=self._intent(files,job,move)
        if not intent.is_file():return False
        value=json.loads(intent.read_text())
        return value=={'source':move['source'],'destination':move['destination'],'sha256':move['sha256']}

    def _copy(self,files,job,move):
        source=files.config.path_for(move['source']);dest=files.config.path_for(move['destination'],writable=True)
        backup=self._backup(files,job,move)
        stage=files.state_path('attachment-migrations',job['id'],'staging',move['backup'])
        if dest.exists():
            if not self._owned(files,job,move) or stage.exists() or file_hash(dest)!=move['sha256']:
                raise ConflictError('Destination is occupied or changed: '+move['destination'])
            return
        origin=source if source.exists() else backup
        if not origin.is_file() or file_hash(origin)!=move['sha256']:raise ConflictError('Source changed: '+move['source'])
        if not stage.exists():
            stage.parent.mkdir(parents=True,exist_ok=True)
            temp=files.state_path('attachment-migrations',job['id'],'staging',move['backup']+'.partial-'+uuid.uuid4().hex)
            try:
                with origin.open('rb') as src,temp.open('xb') as out:
                    preserve_file_mode(out,origin)
                    shutil.copyfileobj(src,out,length=1024*1024);out.flush();os.fsync(out.fileno())
                if file_hash(temp)!=move['sha256']:raise ConflictError('Copied attachment verification failed')
                move_exclusive(temp,stage)
            finally:temp.unlink(missing_ok=True)
        if file_hash(stage)!=move['sha256']:raise ConflictError('Staged attachment changed')
        # Durable publish intent + disappearance of staging distinguishes our
        # atomic publication from an unrelated same-content destination.
        atomic_write(self._intent(files,job,move),json.dumps({'source':move['source'],'destination':move['destination'],'sha256':move['sha256']}).encode())
        dest.parent.mkdir(parents=True,exist_ok=True);files.config.path_for(move['destination'],writable=True)
        move_exclusive(stage,dest)

    def _execute(self,files,job,cancel):
        self._check(job,cancel);self._validate_documents(files,job)
        required=sum(m['size'] for m in job['moves'] if not files.config.path_for(m['destination']).exists())
        required+=sum(len(self._note_bytes(files,job,e,'after')) for e in job['edits'])+4*1024*1024
        if shutil.disk_usage(files.config.root).free<required:raise OSError('Insufficient disk space for verified copies and recovery')
        # Check every original before changing any document, including resumes.
        for move in job['moves']:
            source=files.config.path_for(move['source']);backup=self._backup(files,job,move)
            existing=source if source.exists() else backup
            if not existing.is_file() or file_hash(existing)!=move['sha256']:raise ConflictError('Source changed: '+move['source'])
        job['phase']='copying';job['progress']={'done':0,'total':len(job['moves'])};self._save(files,job)
        for index,move in enumerate(job['moves']):
            self._check(job,cancel);self._copy(files,job,move);job['progress']['done']=index+1
            if index%20==0:self._save(files,job)
        self._validate_documents(files,job);job['phase']='rewriting';self._save(files,job)
        for edit in job['edits']:
            with self.config.lock,self.runtime.files.lock:
                self._check(job,cancel);p=files.config.path_for(edit['path'],writable=True);current=file_hash(p)
                if current==edit['after_hash']:continue
                if current!=edit['before_hash']:raise ConflictError('Document changed: '+edit['path'])
                atomic_write(p,self._note_bytes(files,job,edit,'after'))
        self._validate_documents(files,job);job['phase']='retiring';self._save(files,job)
        for index,move in enumerate(job['moves']):
            self._check(job,cancel);source=files.config.path_for(move['source'],writable=True);backup=self._backup(files,job,move)
            dest=files.config.path_for(move['destination'])
            if not dest.is_file() or file_hash(dest)!=move['sha256']:raise ConflictError('Copied attachment changed')
            if source.exists():
                if backup.exists():raise ConflictError('Both source and recovery original exist; review required')
                if file_hash(source)!=move['sha256']:raise ConflictError('Original changed before retirement')
                backup.parent.mkdir(parents=True,exist_ok=True);move_exclusive(source,backup)
                if file_hash(backup)!=move['sha256']:
                    # An external editor raced retirement: preserve its newest
                    # bytes at the original path whenever that path is vacant.
                    if not source.exists():move_exclusive(backup,source)
                    raise ConflictError('Original changed during retirement; latest bytes preserved')
            elif not backup.is_file() or file_hash(backup)!=move['sha256']:
                raise ConflictError('Recovery original is missing or changed')
            job['progress']['done']=index+1
            if index%20==0:self._save(files,job)
        self._check(job,cancel)
        with self.config.lock:
            self._guard(job['root']);self.config.save({'attachment_folder':job['destination']})
        job['phase']='indexing';self._save(files,job)
        self._reindex(job,strict=True)
        job['state']='completed';job['phase']='completed';self._save(files,job)

    def _rollback(self,files,job):
        self._guard(job['root']);self._validate_documents(files,job)
        # Preflight all paths before restoring anything. Never overwrite a later edit.
        for move in job['moves']:
            dest=files.config.path_for(move['destination'])
            stage=files.state_path('attachment-migrations',job['id'],'staging',move['backup'])
            if dest.exists() and (not self._owned(files,job,move) or stage.exists()):
                raise ConflictError('Destination is not owned by this migration: '+move['destination'])
            for p in (files.config.path_for(move['source']),files.config.path_for(move['destination']),self._backup(files,job,move)):
                if p.exists() and (not p.is_file() or file_hash(p)!=move['sha256']):
                    raise ConflictError('File changed; automatic rollback stopped: '+move['source'])
            if not files.config.path_for(move['source']).exists() and not self._backup(files,job,move).exists():
                raise ConflictError('Recovery original missing: '+move['source'])
        job['phase']='rollback';self._save(files,job)
        # Restore original attachments before reverting references.
        for move in job['moves']:
            self._guard(job['root']);source=files.config.path_for(move['source'],writable=True);backup=self._backup(files,job,move)
            if not source.exists():source.parent.mkdir(parents=True,exist_ok=True);move_exclusive(backup,source)
        for edit in job['edits']:
            with self.config.lock,self.runtime.files.lock:
                self._guard(job['root']);p=files.config.path_for(edit['path'],writable=True);current=file_hash(p)
                if current==edit['after_hash']:atomic_write(p,self._note_bytes(files,job,edit,'before'))
                elif current!=edit['before_hash']:raise ConflictError('Document changed during rollback')
        # Retain migrated copies too; no irreversible deletion is part of rollback.
        for move in job['moves']:
            self._guard(job['root']);dest=files.config.path_for(move['destination'],writable=True)
            if dest.exists():
                if file_hash(dest)!=move['sha256']:raise ConflictError('Destination changed during rollback')
                retained=files.state_path('attachment-migrations',job['id'],'rolled-back-copies',move['backup'])
                if retained.exists():raise ConflictError('Rollback recovery destination already exists')
                retained.parent.mkdir(parents=True,exist_ok=True);move_exclusive(dest,retained)
        with self.config.lock:
            self._guard(job['root'])
            if self.config.data.get('attachment_folder')==job['destination']:
                self.config.save({'attachment_folder':job['previous_attachment_folder']})
        self._reindex(job);job['state']='rolled_back';job['phase']='rolled_back';self._save(files,job)

    def _reindex(self,job,strict=False):
        self._guard(job['root'])
        try:self.runtime.files.attachments.refresh()
        except (OSError,ValueError,sqlite3.Error) as error:
            if strict:raise
            job.setdefault('warnings',[]).append('Index refresh failed: '+str(error))
        self.runtime.files_changed(*(m['source'] for m in job['moves']),*(m['destination'] for m in job['moves']),*(e['path'] for e in job['edits']))
        self.runtime.publish('files',[],reset=True)

    def _worker(self,files,job,action,cancel):
        if action!='plan':
            with self.config.lock,self.runtime.files.lock:
                self.runtime.files.migration_active=True
        try:
            if action=='plan':self._plan(files,job,cancel)
            elif action=='rollback':self._rollback(files,job)
            else:self._execute(files,job,cancel)
        except Exception as error:
            job['error']=str(error)
            if action=='plan':job['state']='cancelled' if isinstance(error,InterruptedError) else 'failed'
            elif self.config.data.get('root')!=job['root']:
                job['state']='interrupted'
            elif action=='rollback':job['state']='conflict'
            else:
                try:self._rollback(files,job)
                except Exception as rollback_error:
                    job['state']='conflict';job['error']+='; rollback stopped: '+str(rollback_error)
            self._save(files,job)
            logging.getLogger(__name__).warning('Attachment migration %s: %s',job['id'],job['state'])
        finally:
            if action!='plan':
                with self.config.lock,self.runtime.files.lock:
                    self.runtime.files.migration_active=False

    def stop(self):
        for event in self.cancels.values():event.set()
        for thread in self.threads.values():thread.join(timeout=2)
