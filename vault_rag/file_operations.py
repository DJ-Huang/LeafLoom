"""Rooted file workflows shared by the two public MCP file tools.

Transfers are private to a credential generation. Durable operation receipts and
the existing attachment journals make retries and recovery explicit.
"""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import tempfile
import threading
import time
import uuid
from urllib.parse import quote

from vault_rag.attachment_uploads import UploadTarget
from vault_rag.file_downloads import download_file
from vault_rag.local_state import ConflictError, atomic_write, digest, relative
from vault_rag.note_operations import NoteError
from vault_rag.platform_support import protect_private_directory, is_link


class FileOperations:
    CHUNK = 256 * 1024
    MAX_FILE = 256 * 1024 * 1024
    MAX_TOTAL = 1024 * 1024 * 1024
    TTL = 24 * 60 * 60

    def __init__(self, config, runtime, notes, workspace, migrations, index_jobs):
        self.config, self.runtime, self.notes = config, runtime, notes
        self.workspace, self.migrations, self.index_jobs = workspace, migrations, index_jobs
        self.lock = threading.RLock()
        self.requests = threading.RLock()
        self.temp = tempfile.TemporaryDirectory(prefix='attachment-transfer-', dir=config.directory)
        self.directory = Path(self.temp.name)
        protect_private_directory(self.directory)
        self.transfers, self.threads, self.stops = {}, {}, {}

    def _check(self, revision, check):
        check()
        with self.config.lock:
            self.notes.check_workspace(revision)

    @staticmethod
    def _name(name):
        if (not isinstance(name, str) or not name or name.startswith('.') or
                '/' in name or '\\' in name or any(ord(c) < 32 for c in name) or len(name.encode('utf-8')) > 200):
            raise ValueError('Use a plain attachment filename')
        if Path(name).suffix.lower() in {'.md', '.txt', '.base'}:
            raise ValueError('Use the note tools for Markdown, TXT and Base files')
        return name

    def _path(self, path):
        path = relative(path)
        self._name(PurePosixPath(path).name)
        p = self.config.path_for(path)
        if not stat.S_ISREG(p.stat().st_mode):
            raise ValueError('Select a regular attachment file')
        return path, p

    def _file_name(self, file):
        fallback = 'attachment-' + digest(file['file_id'])[:12]
        extension = mimetypes.guess_extension(file.get('mime_type', ''), strict=False) or ''
        return self._name(file.get('file_name') or fallback + extension)

    def _revision(self, p, revision):
        info = p.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Select a regular file')
        return digest(json.dumps([revision, str(p), info.st_dev, info.st_ino,
                                  info.st_size, info.st_mtime_ns, info.st_ctime_ns]))

    def _stat(self, path, revision, source_note=''):
        path, p = self._path(path)
        result = self.workspace.details(str(self.config.root), path)
        result['revision'] = self._revision(p, revision)
        link = path
        if source_note:
            self.notes.note_path(source_note)
            link = posixpath.relpath(path, posixpath.dirname(source_note) or '.')
        label = p.name.replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]')
        result['markdown_link'] = '[' + label + '](<' + quote(link, safe='/') + '>)'
        if result['mime'].startswith('image/'):
            result['markdown_embed'] = '!' + result['markdown_link']
        return result

    def _chunk(self, p, request, revision, check):
        with self.config.lock:
            self._check(revision, check)
            if self._revision(p, revision) != request.expected_revision:
                raise ConflictError('File changed; stat the file again before reading')
            descriptor = os.open(p, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            current = p.stat()
            if not stat.S_ISREG(opened.st_mode) or (opened.st_ino, opened.st_size, opened.st_mtime_ns) != (current.st_ino, current.st_size, current.st_mtime_ns):
                raise ConflictError('File changed while opening')
            if request.offset > opened.st_size:
                raise ValueError('Offset is beyond the end of the file')
            stream.seek(request.offset)
            data = stream.read(request.limit)
            after = os.fstat(stream.fileno())
        self._check(revision, check)
        if ((opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) !=
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or
                self._revision(p, revision) != request.expected_revision):
            raise ConflictError('File changed while reading')
        return dict(offset=request.offset, next_offset=request.offset + len(data),
                    eof=request.offset + len(data) == opened.st_size, size=opened.st_size,
                    revision=request.expected_revision, data_base64=base64.b64encode(data).decode('ascii'))

    @staticmethod
    def _job_id(value):
        kind, sep, key = value.partition(':')
        if not sep or kind not in {'operation', 'upload', 'download', 'index'} or not re.fullmatch('[a-f0-9]{32}', key):
            raise ValueError('Use the complete job_id returned by the file tools')
        return kind, key

    def _operation_info(self, job):
        value = self.migrations._public(job)
        value.pop('root', None)
        value['job_id'] = 'operation:' + job['id']
        return value

    def _transfer(self, key, owner, revision):
        row = self.transfers.get(key)
        if row is None or row['owner'] != owner or row['workspace_revision'] != revision:
            raise FileNotFoundError('Upload is unavailable for this credential and workspace')
        if row['expires_at'] <= time.time():
            raise NoteError('transfer_expired', 'Upload expired; start a new transfer')
        return row

    @staticmethod
    def _transfer_info(row):
        keys = ('state', 'size', 'expected_size', 'name', 'sha256', 'expires_at', 'results', 'error', 'error_code')
        return {k: row[k] for k in keys if k in row} | {'job_id': 'upload:' + row['id']}

    def _download_info(self, root, key, revision):
        job = self.workspace.download_status(root, key)
        result = {k: v for k, v in job.items() if k not in {'root', 'revision'}}
        result['job_id'] = 'download:' + key
        if job['state'] == 'completed':
            path = self.workspace.download_file(root, key)
            result.update(revision=self._revision(path, revision), size=path.stat().st_size, name='LeafLoom-attachments.zip')
        return result

    def read(self, request, revision, owner, grant, check):
        self._check(revision, check)
        root = str(self.config.root)
        action = request.action
        if action == 'list':
            status = self.index_jobs.status(root)
            if not status['usable']:
                raise NoteError('initialization_required', 'Initialize the attachment index with vault_files_update reindex', status=status)
            try:
                value = self.runtime.files.attachments.listing(request.query, limit=request.limit,
                    kind=request.kind, sort=request.sort, order=request.order, cursor=request.cursor)
            except ConflictError:
                if request.cursor:
                    raise NoteError('stale_cursor', 'Attachment results changed; restart pagination') from None
                raise
            value['next_cursor'] = value.pop('cursor')
        elif action == 'stat':
            with self.config.lock:
                value = self._stat(request.path, revision, request.source_note)
        elif action == 'read':
            if bool(request.path) == bool(request.job_id):
                raise ValueError('Select exactly one path or download job_id')
            with self.config.lock:
                if request.job_id:
                    kind, key = self._job_id(request.job_id)
                    if kind != 'download':
                        raise ValueError('Only download jobs have readable output')
                    p = self.workspace.download_file(root, key)
                else:
                    _, p = self._path(request.path)
            value = self._chunk(p, request, revision, check)
        elif action == 'export':
            for path in request.paths:
                self._path(path)
            job = self.workspace.download(root, request.paths, guard=lambda: self._check(revision, check))
            value = {'job_id': 'download:' + job['id'], 'state': job['state']}
        else:
            value = self._status(request, revision, owner)
        self._check(revision, check)
        return {'ok': True, **value, 'workspace_revision': revision}

    def _status(self, request, revision, owner):
        root = str(self.config.root)
        if request.job_id:
            kind, key = self._job_id(request.job_id)
            if kind == 'upload':
                with self.lock:
                    return self._transfer_info(self._transfer(key, owner, revision))
            if kind == 'download':
                return self._download_info(root, key, revision)
            if kind == 'index':
                value = self.index_jobs.status(root)
                if value.get('job_id') != key:
                    raise FileNotFoundError('Index job is unavailable')
                return {**value, 'job_id': request.job_id}
            files = self.migrations._files()
            job = self.migrations._load(files, key)
            value = self._operation_info(job)
            if request.section != 'jobs':
                rows = job.get(request.section, [])
                if request.section == 'moves':
                    rows = [{k: m[k] for k in ('source', 'destination', 'size')} for m in rows]
                page = self.notes.page(rows, request.limit, request.cursor,
                    key=[request.job_id, value['revision'], request.section])
                value.update(page=page)
            return value
        rows = []
        for job in self.migrations.list()['jobs']:
            rows.append({k: v for k, v in self._operation_info(job).items()
                         if k in {'job_id', 'state', 'kind', 'phase', 'summary', 'revision', 'created_at'}})
        with self.lock:
            rows.extend(self._transfer_info(row) for row in self.transfers.values()
                        if row['owner'] == owner and row['workspace_revision'] == revision and row['expires_at'] > time.time())
        files = self.migrations._files()
        directory = files.state_path('attachment-downloads')
        if directory.exists():
            for path in directory.iterdir():
                if re.fullmatch('[a-f0-9]{32}', path.name):
                    try:
                        rows.append(self._download_info(root, path.name, revision))
                    except (ValueError, OSError, ConflictError):
                        continue
        return {**self.notes.page(rows, request.limit, request.cursor, key='file-jobs'),
                'index': self.index_jobs.status(root),
                'attachment_folder': self.config.data.get('attachment_folder', '_attachments'),
                'limits': dict(chunk_bytes=self.CHUNK, file_bytes=self.MAX_FILE, temporary_bytes=self.MAX_TOTAL, ttl_seconds=self.TTL)}

    def _receipt_path(self, owner, operation_id):
        return self.runtime.files.state_path('file-receipts', digest(owner + ':' + operation_id) + '.json')

    def _receipt(self, owner, operation_id, fingerprint):
        path = self._receipt_path(owner, operation_id)
        if not path.exists():
            return None
        row = json.loads(path.read_text(encoding='utf-8'))
        if row['fingerprint'] != fingerprint:
            raise ConflictError('operation_id was already used with different arguments')
        if row['state'] in {'publishing', 'published'}:
            result = row['result']
            destination = self.config.path_for(result['path'])
            stage = destination.parent / row['staging_name']
            owned = (not is_link(stage) and stage.is_file() and destination.is_file() and os.path.samefile(stage, destination))
            if row['state'] == 'published' and destination.is_file() and not stage.exists():
                info = destination.stat()
                owned = [info.st_dev, info.st_ino] == row.get('published_identity')
                if owned:
                    with destination.open('rb') as stream:
                        owned = hashlib.file_digest(stream, 'sha256').hexdigest() == result['sha256']
            if not owned:
                raise ConflictError('Upload publication was interrupted; inspect its destination before retrying')
            stage.unlink(missing_ok=True)
            result.update(size=destination.stat().st_size, revision=self._revision(destination, self.notes.workspace_revision))
            transfer = self.transfers.get(row.get('upload_id'))
            if transfer and transfer['expected_size'] is not None:
                transfer.update(state='completed', results=[result])
                (self.directory / transfer['id']).unlink(missing_ok=True)
            self._save_receipt(owner, operation_id, fingerprint, result)
            self.runtime.files_changed(result['path'])
            self.runtime.publish('files', [result['path']])
            return result
        return row['result']

    def _save_receipt(self, owner, operation_id, fingerprint, result, **extra):
        path = self._receipt_path(owner, operation_id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write(path, json.dumps({'fingerprint':fingerprint, 'result':result, 'state':'complete', **extra}, ensure_ascii=False).encode())

    def write(self, request, revision, operation_id, files, owner, grant, check):
        self._check(revision, check)
        if files and not (request.action == 'upload' and request.source == 'files'):
            raise ValueError('files is only accepted for upload source=files')
        # Signed URLs are ephemeral; identity and placement determine the receipt.
        identity = [{k: f[k] for k in ('file_id', 'file_name', 'mime_type') if k in f} for f in files]
        fingerprint = digest(json.dumps([revision, request.model_dump(), identity], sort_keys=True))
        with self.requests:
            with grant(), self.config.lock, self.lock:
                self.notes.check_workspace(revision)
                root = str(self.config.root)
                previous = self._receipt(owner, operation_id, fingerprint)
                if previous is not None:
                    if previous.get('job_id', '').startswith('upload:'):
                        key = previous['job_id'].split(':')[1]
                        row = self.transfers.get(key)
                        if row and row['owner'] == owner:
                            previous = {**previous, **self._transfer_info(row)}
                        elif previous.get('state') in {'staging', 'running'}:
                            previous = {**previous, 'state':'interrupted',
                                'error':'Temporary transfer is unavailable; inspect saved results before uploading remaining files'}
                    return {'ok': True, **previous, 'workspace_revision': revision, 'replayed': True}
            if request.action == 'upload' and request.source == 'commit':
                value = self._upload(request, revision, operation_id, fingerprint, files, owner, grant, check)
            else:
                with grant(), self.config.lock, self.lock:
                    self.notes.check_workspace(revision)
                    value = self._dispatch(request, revision, operation_id, fingerprint, files, owner, grant, check)
            with self.config.lock:
                if str(self.config.root) == root and not (request.action == 'upload' and request.source == 'files'):
                    self._save_receipt(owner, operation_id, fingerprint, value)
            return {'ok': True, **value, 'workspace_revision': self.notes.workspace_revision}

    def _dispatch(self, request, revision, operation_id, fingerprint, files, owner, grant, check):
        if request.action == 'upload':
            return self._upload(request, revision, operation_id, fingerprint, files, owner, grant, check)
        if request.action in {'move', 'trash', 'organize'}:
            root = str(self.config.root)
            guard = lambda: self._check(revision, check)
            if request.action == 'organize':
                job = self.migrations.create(root, request.destination, guard=guard)
            elif request.action == 'trash':
                job = self.migrations.create(root, '', selection=request.paths, kind='trash', guard=guard)
            elif request.destination_kind == 'path':
                if len(request.paths) != 1:
                    raise ValueError('A full destination path requires exactly one source')
                destination = relative(request.destination)
                self._name(PurePosixPath(destination).name)
                job = self.migrations.create(root, posixpath.dirname(destination), selection=request.paths,
                    kind='move', destinations={request.paths[0]: destination}, guard=guard)
            else:
                job = self.migrations.create(root, request.destination, selection=request.paths, kind='move', guard=guard)
            return self._operation_info(job)
        if request.action == 'reindex':
            value = self.index_jobs.start(str(self.config.root), guard=lambda: self._check(revision, check))
            value['job_id'] = 'index:' + value['job_id']
            return value
        return self._update_job(request, revision, owner, check)

    def _update_job(self, request, revision, owner, check):
        kind, key = self._job_id(request.job_id)
        root = str(self.config.root)
        if kind == 'operation':
            job = self.migrations.action(key, 'rollback' if request.command == 'undo' else request.command,
                root, request.confirm, expected_revision=request.expected_revision if request.command != 'cancel' else None,
                guard=lambda: self._check(revision, check))
            return self._operation_info(job)
        if request.command != 'cancel':
            raise ValueError('This job only supports cancel; start a new transfer or index job to retry')
        if kind == 'upload':
            row = self._transfer(key, owner, revision)
            self.stops[key].set()
            if row['state'] == 'staging':
                row['state'] = 'cancelled'
                (self.directory / key).unlink(missing_ok=True)
            return self._transfer_info(row)
        if kind == 'download':
            self.workspace.download_status(root, key, cancel=True)
            return self._download_info(root, key, revision)
        value = self.index_jobs.status(root)
        if value.get('job_id') != key:
            raise FileNotFoundError('Index job is unavailable')
        return {**self.index_jobs.cancel_job(root), 'job_id': request.job_id}

    def _purge(self):
        for key, row in list(self.transfers.items()):
            if row['expires_at'] <= time.time() and not self.threads.get(key, threading.Thread()).is_alive():
                (self.directory / key).unlink(missing_ok=True)
                del self.transfers[key]
                self.stops.pop(key, None)

    def _quota(self, owner, increment=0):
        total = sum(row['size'] for row in self.transfers.values()
                    if row['owner'] == owner and row['state'] in {'staging', 'running', 'interrupted'})
        if total + increment > self.MAX_TOTAL:
            raise ValueError('Temporary attachment quota exceeded')

    def _allocate(self, revision, owner, name, size=None, sha256='', folder=''):
        self._purge()
        if sum(row['owner'] == owner for row in self.transfers.values()) >= 1024:
            raise ValueError('Too many transfers; wait for unused transfers to expire')
        self._name(name)
        folder = relative(folder or self.config.data.get('attachment_folder', '_attachments'))
        self.config.path_for(folder, writable=True)
        key = uuid.uuid4().hex
        row = dict(id=key, owner=owner, workspace_revision=revision, root=str(self.config.root), name=name, folder=folder,
                   size=0, expected_size=size, sha256=sha256.lower(), state='staging',
                   expires_at=time.time() + self.TTL, results=[])
        (self.directory / key).touch(exist_ok=False)
        self.transfers[key] = row
        self.stops[key] = threading.Event()
        return row

    def _upload(self, request, revision, operation_id, fingerprint, files, owner, grant, check):
        source = request.source
        if source == 'begin':
            self._quota(owner, request.size)
            return self._transfer_info(self._allocate(revision, owner, request.name, request.size, request.sha256, request.folder))
        if source == 'files':
            if not 1 <= len(files) <= 100:
                raise ValueError('Select between 1 and 100 files')
            if sum(t.is_alive() for t in self.threads.values()) >= 2:
                raise ConflictError('Wait for current file uploads to finish')
            for f in files:
                if not f['file_id']:
                    raise ValueError('File reference requires file_id')
                self._file_name(f)
            name = self._file_name(files[0])
            row = self._allocate(revision, owner, name, folder=request.folder)
            row['state'] = 'running'
            self._save_receipt(owner, operation_id, fingerprint, self._transfer_info(row))
            thread = threading.Thread(target=self._upload_worker,
                args=(row, list(files), operation_id, fingerprint, grant, check), daemon=True)
            self.threads[row['id']] = thread
            thread.start()
            return self._transfer_info(row)
        _, key = self._job_id(request.job_id)
        if not request.job_id.startswith('upload:'):
            raise ValueError('Select an upload job')
        row = self._transfer(key, owner, revision)
        if source == 'abort':
            self.stops[key].set()
            if row['state'] == 'staging':
                row['state'] = 'cancelled'
                (self.directory / key).unlink(missing_ok=True)
            return self._transfer_info(row)
        if row['state'] != 'staging':
            raise ConflictError('Upload is not accepting chunks')
        p = self.directory / key
        if source == 'chunk':
            try:
                chunk = base64.b64decode(request.data_base64, validate=True)
            except ValueError:
                raise ValueError('Invalid Base64 chunk') from None
            if len(chunk) > self.CHUNK or request.offset > row['size']:
                raise ValueError('Invalid upload chunk size or offset')
            if request.offset < row['size']:
                with p.open('rb') as stream:
                    stream.seek(request.offset)
                    if request.offset + len(chunk) > row['size'] or stream.read(len(chunk)) != chunk:
                        raise ConflictError('Chunk conflicts with already received bytes')
                return self._transfer_info(row)
            if row['size'] + len(chunk) > row['expected_size']:
                raise ValueError('Chunk exceeds the declared file size')
            self._quota(owner, len(chunk))
            with p.open('ab') as stream:
                stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            row['size'] += len(chunk)
            return self._transfer_info(row)
        with p.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if row['size'] != row['expected_size'] or actual != row['sha256']:
            raise ValueError('Upload size or SHA-256 mismatch; transfer is not saved')
        result = self._publish(row, p, row['name'], operation_id, fingerprint, grant, check)
        row['state'] = 'completed'
        row['results'] = [result]
        p.unlink(missing_ok=True)
        return {**self._transfer_info(row), **result}

    def _publish(self, row, source, name, operation_id, fingerprint, grant, check, *, receipt_owner=None):
        revision, owner = row['workspace_revision'], receipt_owner or row['owner']
        target = None
        receipt_saved = False
        try:
            with grant(), self.config.lock:
                self.notes.check_workspace(revision)
                check()
                target = UploadTarget(self.runtime, folder=row['folder'], name=name, root=str(self.config.root),
                                      revision=revision, create_folder=True, unique=True)
            sha = hashlib.sha256()
            written = 0
            with source.open('rb') as stream:
                while chunk := stream.read(self.CHUNK):
                    self._check(revision, check)
                    written += len(chunk)
                    if written > self.MAX_FILE:
                        raise ValueError('File exceeds the upload size limit')
                    sha.update(chunk)
                    target.stream.write(chunk)
            if row['expected_size'] is not None and (written != row['expected_size'] or sha.hexdigest() != row['sha256']):
                raise ConflictError('Staged upload changed before publication')
            target.finish()
            with grant(), self.config.lock:
                self.notes.check_workspace(revision)
                check()
                def intent(path, staging):
                    self._save_receipt(owner, operation_id, fingerprint,
                        {'path': path, 'saved': True, 'index_pending': True},
                        state='publishing', staging_name=PurePosixPath(staging).name, upload_id=row['id'])
                result = target.commit(before_publish=intent)
                result.update(saved=True, index_pending=True)
                with self.lock:
                    row['results'].append(result)
                p = self.config.path_for(result['path'])
                result.update(size=p.stat().st_size,
                    sha256=sha.hexdigest(),
                    markdown_link='[' + name.replace('[', '\\[').replace(']', '\\]') + '](<' + quote(result['path'], safe='/') + '>)')
                info = p.stat()
                self._save_receipt(owner, operation_id, fingerprint, result, state='published',
                    staging_name=target.temp.name, published_identity=[info.st_dev,info.st_ino], upload_id=row['id'])
                # Unlinking the staging hardlink changes ctime. Capture the public
                # file version only after cleanup, so it is immediately readable.
                target.close()
                result['revision'] = self._revision(p, revision)
                self._save_receipt(owner, operation_id, fingerprint, result)
                receipt_saved = True
            try:
                self._check(revision, check)
                if self.index_jobs.status(row['root'])['usable']:
                    self.runtime.files.attachments.apply([result['path']])
                    result['index_pending'] = False
            except Exception:
                pass
            self.runtime.publish('files', [result['path']])
            return result
        finally:
            if target and target.published and not receipt_saved:
                row['state'] = 'interrupted'
            if target and (not target.published or receipt_saved):
                target.close()

    def _upload_worker(self, row, files, operation_id, fingerprint, grant, check):
        key = row['id']
        p = self.directory / key
        def guarded():
            if self.stops[key].is_set():
                raise InterruptedError('Upload cancelled')
            self._check(row['workspace_revision'], check)
            if row['expires_at'] <= time.time():
                raise ValueError('Upload expired')
        try:
            for index, file in enumerate(files):
                guarded()
                name = self._file_name(file)
                def progress(size):
                    with self.lock:
                        self._quota(row['owner'], size - row['size'])
                        row['size'] = size
                with p.open('wb') as stream:
                    download_file(file['download_url'], stream, check=guarded, progress=progress, max_size=self.MAX_FILE)
                    stream.flush()
                    os.fsync(stream.fileno())
                guarded()
                # Each file has its own publication receipt; the batch has a separate receipt.
                self._publish(row, p, name, operation_id + ':' + str(index), fingerprint, grant, guarded,
                              receipt_owner='batch:' + row['owner'])
                with self.lock:
                    row['size'] = 0
                with self.config.lock:
                    if str(self.config.root) == row['root']:
                        self._save_receipt(row['owner'], operation_id, fingerprint, self._transfer_info(row))
            row['state'] = 'completed'
        except Exception as error:
            row['state'] = 'cancelled' if isinstance(error, InterruptedError) else 'failed'
            row['error_code'] = ('permission_denied' if isinstance(error, PermissionError) else
                                 'write_conflict' if isinstance(error, ConflictError) else 'upload_failed')
            # Never reflect a signed URL, HTTP exception, path or credential.
            row['error'] = 'Upload stopped; inspect completed results before retrying remaining files'
        finally:
            p.unlink(missing_ok=True)
            with self.config.lock:
                if str(self.config.root) == row['root']:
                    self._save_receipt(row['owner'], operation_id, fingerprint, self._transfer_info(row))

    def stop(self):
        for event in self.stops.values():
            event.set()
        for thread in self.threads.values():
            thread.join(timeout=2)
        if not any(thread.is_alive() for thread in self.threads.values()):
            self.temp.cleanup()
