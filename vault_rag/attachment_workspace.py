"""Rooted attachment previews, advisory resource status and bounded ZIP jobs."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import stat
from pathlib import Path, PurePosixPath
import re
import shutil
import threading
import time
import uuid
import warnings
import zipfile

from vault_rag.local_state import ConflictError, atomic_write, relative
from vault_rag.attachment_migrations import ASSETS, SOURCE_MARKERS, SOURCE_RESOURCE_TYPES
from vault_rag.attachment_references import OPAQUE_RESOURCE_TYPES, discover_project_dependencies


class AttachmentWorkspace:
    def __init__(self, runtime, migrations):
        self.runtime=runtime;self.config=runtime.config;self.migrations=migrations
        self.images=threading.BoundedSemaphore(2);self.lock=threading.RLock()
        self.protection_lock=threading.Lock();self.protection=None;self.downloads={};self.stops={};self.threads={}

    def files(self,root):
        self.migrations._guard(root)
        return self.migrations._files()

    def _protected(self,files):
        root=str(files.config.root)
        stamp=(root,self.config.data.get('revision'),self.runtime.catalog.version)
        with self.protection_lock:
            if self.protection and self.protection[0]==stamp and time.monotonic()-self.protection[1]<20:
                return self.protection[2]
            paths={p.relative_to(files.config.root).as_posix() for p in files.walk(strict=True)}
            scopes={p.rpartition('/')[0] for p in paths if Path(p).suffix.lower() in {'.html','.htm'}|SOURCE_RESOURCE_TYPES or PurePosixPath(p).name in SOURCE_MARKERS}
            if self.migrations.websites:
                scopes.update(p['directory'] for p in self.migrations.websites.projects if p['vault']==root)
            sources={p for p in paths if Path(p).suffix.lower() not in OPAQUE_RESOURCE_TYPES|{'.md','.markdown'}}
            protected=discover_project_dependencies(files,paths,scopes,reference_sources=sources)['protected']
            protected.update(p for p in paths if Path(p).suffix.lower() not in ASSETS)
            self.migrations._guard(root)
            with self.lock:self.protection=(stamp,time.monotonic(),protected)
            return protected
    def details(self,root,path):
        files=self.files(root);path=relative(path);p=files.config.path_for(path);info=p.stat()
        if not p.is_file():raise ValueError('Select an attachment file')
        result={'path':path,'name':p.name,'size':info.st_size,'mtime':info.st_mtime,
                'mime':mimetypes.guess_type(p.name)[0] or 'application/octet-stream',
                'protected':path in self._protected(files)}
        self.migrations._guard(root);self.config.path_for(path);return result

    def thumbnail(self,root,path):
        from PIL import Image, ImageOps, UnidentifiedImageError
        files=self.files(root);path=relative(path);source=files.config.path_for(path)
        if source.suffix.lower() not in {'.png','.jpg','.jpeg','.gif','.webp','.bmp','.tif','.tiff','.avif'}:
            raise ValueError('Thumbnail format is unsupported')
        before=source.stat()
        if before.st_size>64*1024*1024:raise ValueError('Image is too large for a thumbnail')
        key=hashlib.sha256(json.dumps([root,path,before.st_size,before.st_mtime_ns,self.config.data.get('revision')]).encode()).hexdigest()
        target=files.state_path('attachment-thumbnails',key+'.webp')
        with self.images:
            target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if not target.exists():
                import io
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter('error',Image.DecompressionBombWarning)
                        with os.fdopen(os.open(source,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0)),'rb') as stream, Image.open(stream) as picture:
                            opened=os.fstat(stream.fileno())
                            if not stat.S_ISREG(opened.st_mode) or (opened.st_size,opened.st_mtime_ns,opened.st_ino)!=(before.st_size,before.st_mtime_ns,before.st_ino):raise ConflictError('Image changed while opening')
                            if picture.width*picture.height>32_000_000:raise ValueError('Image is too large for a thumbnail')
                            picture.seek(0);picture.draft('RGB',(256,256))
                            picture=ImageOps.exif_transpose(picture);picture.thumbnail((256,256))
                            picture=picture.convert('RGBA' if 'A' in picture.getbands() else 'RGB')
                            data=io.BytesIO();picture.save(data,'WEBP',quality=78)
                except (UnidentifiedImageError,OSError,Image.DecompressionBombWarning,Image.DecompressionBombError) as error:
                    raise ValueError('Image thumbnail is unavailable') from error
                after=files.config.path_for(path).stat()
                self.migrations._guard(root)
                if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):
                    raise ConflictError('Image changed while preparing its thumbnail')
                atomic_write(target,data.getvalue())
                entries=list(target.parent.glob('*.webp'))
                if len(entries)>1024:
                    for old in sorted(entries,key=lambda p:p.stat().st_mtime)[:len(entries)-1024]:
                        if old!=target:old.unlink(missing_ok=True)
        self.migrations._guard(root);self.config.path_for(path)
        return target

    def operation(self,root,kind,paths,destination='',name=''):
        self.files(root)
        if kind not in {'move','rename','trash'}:raise ValueError('Invalid attachment operation')
        if not isinstance(paths,list) or not 1<=len(paths)<=100 or any(not isinstance(p,str) for p in paths):
            raise ValueError('Select between 1 and 100 attachments')
        destinations={}
        if kind=='rename':
            if len(paths)!=1 or not name or '/' in name or '\\' in name or name in {'.','..'}:
                raise ValueError('Enter one valid file name')
            destination=paths[0].rpartition('/')[0]
            destinations={paths[0]:'/'.join(p for p in (destination,name) if p)}
        return self.migrations.create(root,destination,selection=paths,kind=kind,destinations=destinations)

    def _download_path(self,files,key,name):
        if not re.fullmatch('[0-9a-f]{32}',key):raise ValueError('Invalid attachment download ID')
        return files.state_path('attachment-downloads',key,name)

    def _save_download(self,files,job):
        atomic_write(self._download_path(files,job['id'],'job.json'),json.dumps(job).encode())

    def download(self,root,paths):
        files=self.files(root)
        if not isinstance(paths,list) or not 1<=len(paths)<=100 or any(not isinstance(p,str) for p in paths):
            raise ValueError('Select between 1 and 100 attachments')
        paths=list(dict.fromkeys(relative(p) for p in paths))
        for path in paths:
            if not files.config.path_for(path).is_file():raise ValueError('Select attachment files')
        with self.lock:
            directory=files.state_path('attachment-downloads')
            if directory.exists():
                for entry in directory.iterdir():
                    if re.fullmatch('[0-9a-f]{32}',entry.name) and not self.threads.get(entry.name,threading.Thread()).is_alive():
                        checked=self._download_path(files,entry.name,'job.json')
                        if checked.exists() and time.time()-checked.stat().st_mtime>3600:
                            shutil.rmtree(checked.parent);self.downloads.pop(entry.name,None);self.stops.pop(entry.name,None);self.threads.pop(entry.name,None)
            if sum(t.is_alive() for t in self.threads.values())>=2:raise ConflictError('Wait for the current downloads to finish')
            key=uuid.uuid4().hex;stop=threading.Event();self.stops[key]=stop
            job={'id':key,'root':root,'revision':self.config.data.get('revision'),'state':'running','done':0,'total':len(paths),'created_at':time.time()}
            self._download_path(files,key,'job.json').parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            self.downloads[key]=job;self._save_download(files,job)
            thread=threading.Thread(target=self._zip,args=(files,job,paths,stop),daemon=True)
            self.threads[key]=thread;thread.start()
            return dict(job)

    def _download_guard(self,job):
        self.migrations._guard(job['root'])
        if job.get('revision')!=self.config.data.get('revision'):
            raise ConflictError('Attachment download settings changed; prepare a new download')

    def _zip(self,files,job,paths,stop):
        output=self._download_path(files,job['id'],'attachments.zip')
        partial=self._download_path(files,job['id'],'partial.zip')
        try:
            total=sum(files.config.path_for(p).stat().st_size for p in paths)
            if total+4*1024*1024>shutil.disk_usage(files.config.root).free:raise ValueError('Insufficient space for attachment download')
            with zipfile.ZipFile(partial,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
                for index,path in enumerate(paths):
                    self._download_guard(job)
                    if stop.is_set():raise InterruptedError()
                    source=files.config.path_for(path);before=source.stat()
                    with os.fdopen(os.open(source,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0)),'rb') as src,archive.open(path,'w',force_zip64=True) as dst:
                        opened=os.fstat(src.fileno())
                        if not stat.S_ISREG(opened.st_mode) or (opened.st_size,opened.st_mtime_ns,opened.st_ino)!=(before.st_size,before.st_mtime_ns,before.st_ino):raise ConflictError('Attachment changed while opening')
                        while data:=src.read(1024*1024):
                            if stop.is_set():raise InterruptedError()
                            self._download_guard(job);dst.write(data)
                    after=files.config.path_for(path).stat()
                    if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):
                        raise ConflictError('Attachment changed while preparing download')
                    job['done']=index+1;self._save_download(files,job)
            self._download_guard(job);partial.rename(output);job['state']='completed'
        except Exception as error:
            job['state']='cancelled' if isinstance(error,InterruptedError) else 'failed'
            job['error']=str(error) or 'Download cancelled'
        finally:
            partial.unlink(missing_ok=True);self._save_download(files,job)

    def download_status(self,root,key,cancel=False):
        files=self.files(root);record=self._download_path(files,key,'job.json')
        job=json.loads(record.read_text())
        if job['root']!=root:raise ConflictError('Download belongs to another folder')
        self._download_guard(job)
        if time.time()-job['created_at']>3600:
            self._download_path(files,key,'attachments.zip').unlink(missing_ok=True)
            raise ValueError('Attachment download expired')
        if cancel:self.stops.get(key,threading.Event()).set()
        if job['state']=='running' and not self.threads.get(key,threading.Thread()).is_alive():
            job['state']='interrupted';self._save_download(files,job)
        return job

    def download_file(self,root,key):
        job=self.download_status(root,key)
        if job['state']!='completed':raise ConflictError('Attachment download is not ready')
        return self._download_path(self.files(root),key,'attachments.zip')

    def stop(self):
        for event in self.stops.values():event.set()
        for thread in self.threads.values():thread.join(timeout=2)
