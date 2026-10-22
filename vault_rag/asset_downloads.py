"""Durable, bounded full-file downloads, separate from preview caches and originals.

Only configured WebDAV providers supply bytes. Records contain revision identifiers,
never credentials or service URLs. Public job records never contain local paths.
"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import stat
import threading
import time
import uuid

import httpx

from vault_rag.local_state import ConflictError
from vault_rag.remote_webdav import RemoteStorageError


DEFAULT_MAX_BYTES = 20 * 1024**3
DEFAULT_RESERVE_BYTES = 5 * 1024**3
_PENDING = {'queued', 'downloading', 'paused'}
_ID = re.compile(r'^[0-9a-f]{32}$')
_HANDLE = re.compile(r'^[A-Za-z0-9_-]{43}$')
_SHA = re.compile(r'^[0-9a-f]{64}$')
_CHUNK = 1024 * 1024


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def _strong(etag):
    return isinstance(etag, str) and bool(re.fullmatch(r'"[^"\x00-\x20\x7f]*"', etag))


def _version(meta):
    return (int(meta['size']), meta.get('etag', ''), meta.get('mtime', ''))


def _identity(row):
    return _json([row['id'], row['source_id'], row['path'], row['size'], row.get('etag', ''),
                  row.get('mtime', ''), row.get('content_generation', 0), row.get('sha256', '')])


class AssetDownloads:
    def __init__(self, remote, *, max_bytes=DEFAULT_MAX_BYTES, reserve_bytes=DEFAULT_RESERVE_BYTES,
                 handle_ttl=24 * 3600, retention=7 * 24 * 3600, clock=time.time,
                 disk_usage=shutil.disk_usage, start_worker=True):
        if type(max_bytes) is not int or max_bytes < 1 or type(reserve_bytes) is not int or reserve_bytes < 0:
            raise ValueError('Invalid download storage budget')
        if handle_ttl <= 0 or retention <= 0:
            raise ValueError('Invalid download retention')
        self.remote = remote
        self.max_bytes, self.reserve_bytes = max_bytes, reserve_bytes
        self.handle_ttl, self.retention = handle_ttl, retention
        self.clock, self.disk_usage = clock, disk_usage
        self.lock, self.worker_lock = threading.RLock(), threading.Lock()
        self.stopped, self.wake = threading.Event(), threading.Event()
        self.recovered, self.cancelled, self.guards = set(), set(), {}
        self.consumer_pins = {}
        self.thread = None
        if start_worker:
            self.thread = threading.Thread(target=self._loop, name='asset-downloads', daemon=True)
            self.thread.start()

    def _root(self, root=None):
        return self.remote._root(root)

    def _path(self, root, *parts):
        self._root(root)
        files = self.remote._files()
        if str(files.config.root) != str(root):
            raise ConflictError('Connected attachment folder changed')
        return files.state_path('asset-downloads', *parts)

    @contextmanager
    def _db(self, root):
        directory = self._path(root)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        file = self._path(root, 'downloads.sqlite')
        for suffix in ('-journal', '-wal', '-shm'):
            self._path(root, 'downloads.sqlite' + suffix)
        db = sqlite3.connect(file, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > 1:
                raise ValueError('Download records belong to a newer version')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),max_bytes INTEGER NOT NULL,revision TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY,asset_id TEXT NOT NULL,owner TEXT NOT NULL,workspace_revision TEXT NOT NULL,
                    source_id TEXT NOT NULL,source_revision TEXT NOT NULL,credential_revision TEXT NOT NULL,
                    snapshot TEXT NOT NULL,identity TEXT NOT NULL,state TEXT NOT NULL,size INTEGER NOT NULL,
                    downloaded INTEGER NOT NULL DEFAULT 0,head TEXT NOT NULL DEFAULT '{}',sha256 TEXT NOT NULL DEFAULT '',
                    handle TEXT NOT NULL DEFAULT '',expires REAL,created REAL NOT NULL,updated REAL NOT NULL,
                    accessed REAL NOT NULL,error TEXT NOT NULL DEFAULT '',attempts INTEGER NOT NULL DEFAULT 0,retry_at REAL);
                CREATE INDEX IF NOT EXISTS asset_download_jobs_state ON jobs(state,created);
                PRAGMA user_version=1;
            ''')
            db.execute('INSERT OR IGNORE INTO settings VALUES(1,?,?)', (self.max_bytes, uuid.uuid4().hex))
            if root not in self.recovered:
                db.execute("UPDATE jobs SET state='queued',retry_at=NULL WHERE state='downloading'")
                self.recovered.add(root)
            yield db
            self._root(root)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def settings(self, root=None):
        root = self._root(root)
        with self.lock, self._db(root) as db:
            value = dict(db.execute('SELECT max_bytes,revision FROM settings WHERE id=1').fetchone())
        return {**value, 'reserve_bytes': self.reserve_bytes, 'handle_ttl_seconds': self.handle_ttl,
                'retention_seconds': self.retention}

    def configure(self, root, max_bytes, expected_revision=''):
        root = self._root(root)
        if type(max_bytes) is not int or not 1 <= max_bytes <= 1024**5:
            raise ValueError('Invalid download storage budget')
        with self.lock, self._db(root) as db:
            previous = db.execute('SELECT * FROM settings WHERE id=1').fetchone()
            if expected_revision and expected_revision != previous['revision']:
                raise ConflictError('Download settings changed')
            pending = db.execute("SELECT COALESCE(SUM(size),0) FROM jobs WHERE state IN ('queued','downloading','paused')").fetchone()[0]
            if pending > max_bytes:
                raise ValueError('Download storage is reserved by unfinished jobs')
            self._cleanup(db, root, required=0, maximum=max_bytes)
            db.execute('UPDATE settings SET max_bytes=?,revision=? WHERE id=1', (max_bytes, uuid.uuid4().hex))
        return self.settings(root)

    def _files(self, root, job):
        if not _ID.fullmatch(job['id']):
            raise ValueError('Invalid download job ID')
        return self._path(root, job['id'] + '.part'), self._path(root, job['id'] + '.bin')

    def _usage(self, db, root):
        used = reserved = active = ready = 0
        for row in db.execute('SELECT * FROM jobs'):
            job = dict(row)
            size = 0
            for file in self._files(root, job):
                try:
                    info = file.lstat()
                    if not stat.S_ISREG(info.st_mode):
                        raise ValueError('Download staging must contain regular files')
                    size += info.st_size
                except FileNotFoundError:
                    pass
            used += size
            if job['state'] in _PENDING:
                reserved += max(job['size'], size)
                active += 1
            else:
                reserved += size
            ready += int(job['state'] == 'ready')
        maximum = db.execute('SELECT max_bytes FROM settings WHERE id=1').fetchone()[0]
        return {'used_bytes': used, 'reserved_bytes': reserved, 'max_bytes': maximum,
                'active_jobs': active, 'ready_jobs': ready}

    def usage(self, root):
        root = self._root(root)
        with self.lock, self._db(root) as db:
            self._cleanup(db, root)
            return self._usage(db, root)

    def _delete_files(self, root, job):
        for file in self._files(root, job):
            file.unlink(missing_ok=True)

    def _cleanup(self, db, root, *, required=0, maximum=None, keep=''):
        maximum = maximum if maximum is not None else db.execute('SELECT max_bytes FROM settings WHERE id=1').fetchone()[0]
        now = self.clock()
        rows = [dict(row) for row in db.execute("SELECT * FROM jobs WHERE state NOT IN ('queued','downloading','paused') ORDER BY accessed,created")]
        for job in rows:
            if job['id'] == keep or self.consumer_pins.get((root, job['id']), 0):
                continue
            expired = now - job['accessed'] >= self.retention
            over = self._usage(db, root)['reserved_bytes'] + required > maximum
            if job['state'] != 'released' and not expired and not (over and job['state'] == 'ready'):
                continue
            self._delete_files(root, job)
            db.execute("UPDATE jobs SET state=?,downloaded=0,handle='',expires=NULL,updated=? WHERE id=?",
                       ('released' if job['state'] == 'released' else 'evicted', now, job['id']))
        if self._usage(db, root)['reserved_bytes'] + required > maximum:
            raise ValueError('Download storage budget is full')

    def _snapshot(self, root, asset_id):
        self._root(root)
        with self.remote.lock, self.remote._db(root) as db:
            row = self.remote._resolve(db, asset_id=asset_id)
            self.remote._require_available(row)
        if row['source_id'] == 'local':
            raise ValueError('Select a remote attachment for staged download')
        return row

    def _authorize(self, root, owner, revision, guard=None):
        self._root(root)
        if not isinstance(owner, str) or not 1 <= len(owner) <= 256:
            raise ValueError('Invalid download owner')
        if guard is not None and guard() is False:
            raise PermissionError('Download authorization expired')
        if owner != 'local':
            authorize = getattr(self.remote, 'authorize_reader', None) or getattr(self.remote, 'authorize_owner', None)
            if not callable(authorize) or authorize(root, owner, revision) is False:
                raise PermissionError('Download authorization expired')

    def _visible(self, root, job, owner, guard=None):
        self._authorize(root, owner, self.remote.config.data.get('revision', ''), guard)
        if owner != 'local' and owner != job['owner']:
            raise FileNotFoundError('Download job is unavailable')

    def _get(self, db, job_id):
        if not isinstance(job_id, str) or not _ID.fullmatch(job_id):
            raise ValueError('Invalid download job ID')
        row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row:
            raise FileNotFoundError('Download job is unavailable')
        return dict(row)

    def _public(self, job):
        meta = json.loads(job['snapshot'])
        result = {'job_id': job['id'], 'asset_id': job['asset_id'], 'name': meta.get('name', 'attachment'),
                  'delivery': 'local_ui', 'verified': job['state']=='ready' and bool(job['sha256']),
                  'mime': meta.get('mime', 'application/octet-stream'), 'state': job['state'],
                  'downloaded': job['downloaded'], 'size': job['size'], 'sha256': job['sha256'],
                  'error': job['error'], 'created_at': job['created'], 'updated_at': job['updated'],
                  'expires_at': job['expires'], 'retry_at': job['retry_at']}
        head = json.loads(job['head'])
        result['version_state'] = 'strong_etag' if _strong(head.get('etag')) else 'weak_metadata'
        result['checksum_state'] = 'trusted_sha256' if meta.get('sha256') else 'computed_sha256'
        if job['state'] == 'ready' and job['expires'] is not None and job['expires'] > self.clock():
            result['handle'] = job['handle']
        return result

    def prepare(self, root, asset_id, *, owner='local', guard=None):
        root = self._root(root)
        revision = self.remote.config.data.get('revision', '')
        self._authorize(root, owner, revision, guard)
        asset = self._snapshot(root, asset_id)
        context = self.remote._connection_context(root, asset['source_id'])
        identity = _identity(asset)
        now = self.clock()
        with self.lock, self._db(root) as db:
            rows = db.execute("SELECT * FROM jobs WHERE asset_id=? AND owner=? AND identity=? AND source_revision=? AND state NOT IN ('released','evicted','failed') ORDER BY created DESC",
                              (asset['id'], owner, identity, context[2])).fetchall()
            if rows:
                job = dict(rows[0])
                if job['state'] == 'ready' and not self._files(root, job)[1].is_file():
                    db.execute("UPDATE jobs SET state='evicted',handle='' WHERE id=?", (job['id'],))
                else:
                    if job['state'] == 'ready':
                        handle, expires = job['handle'], job['expires']
                        if not handle or expires is None or expires <= now:
                            handle, expires = secrets.token_urlsafe(32), now + self.handle_ttl
                        db.execute('UPDATE jobs SET handle=?,expires=?,accessed=?,updated=?,workspace_revision=? WHERE id=?',
                                   (handle, expires, now, now, revision, job['id']))
                    elif job['state'] == 'paused':
                        db.execute("UPDATE jobs SET state='queued',credential_revision=?,workspace_revision=?,error='',retry_at=NULL,updated=? WHERE id=?",
                                   (context[3], revision, now, job['id']))
                    if guard is not None:
                        self.guards[job['id']] = guard
                    self.wake.set()
                    return self._public(self._get(db, job['id']))
            self._cleanup(db, root, required=asset['size'])
            job_id = uuid.uuid4().hex
            db.execute('''INSERT INTO jobs(id,asset_id,owner,workspace_revision,source_id,source_revision,credential_revision,
                       snapshot,identity,state,size,created,updated,accessed) VALUES(?,?,?,?,?,?,?,?,?,'queued',?,?,?,?)''',
                       (job_id, asset['id'], owner, revision, asset['source_id'], context[2], context[3],
                        _json(asset), identity, asset['size'], now, now, now))
            if guard is not None:
                self.guards[job_id] = guard
            result = self._public(self._get(db, job_id))
        self.wake.set()
        return result

    def status(self, root, job_id, *, owner='local', guard=None):
        root = self._root(root)
        with self.lock, self._db(root) as db:
            job = self._get(db, job_id)
        self._visible(root, job, owner, guard)
        return self._public(job)

    def list(self, root, *, owner='local', guard=None, limit=100):
        root = self._root(root)
        self._authorize(root, owner, self.remote.config.data.get('revision', ''), guard)
        limit = max(1, min(int(limit), 500))
        with self.lock, self._db(root) as db:
            rows = db.execute('SELECT * FROM jobs' + ('' if owner == 'local' else ' WHERE owner=?') + ' ORDER BY created DESC LIMIT ?',
                              (limit,) if owner == 'local' else (owner, limit)).fetchall()
        return {'jobs': [self._public(dict(row)) for row in rows]}

    def release(self, root, job_id, *, owner='local', guard=None):
        root = self._root(root)
        with self.lock, self._db(root) as db:
            job = self._get(db, job_id)
        self._visible(root, job, owner, guard)
        with self.lock, self._db(root) as db:
            job = self._get(db, job_id)
            self.cancelled.add(job_id)
            db.execute("UPDATE jobs SET state='released',handle='',expires=NULL,retry_at=NULL,updated=? WHERE id=?", (self.clock(), job_id))
            # An active writer observes cancellation before its next write and
            # cleans up itself; do not race an open file on Windows.
            if job['state'] != 'downloading' and not self.consumer_pins.get((root, job_id), 0):
                self._delete_files(root, job)
            self.guards.pop(job_id, None)
        return {'released': True}

    def retry(self, root, job_id, *, owner='local', guard=None):
        root = self._root(root)
        with self.lock, self._db(root) as db:
            job = self._get(db, job_id)
        self._visible(root, job, owner, guard)
        if job['state'] not in {'paused', 'failed'}:
            return self._public(job)
        asset = self._snapshot(root, job['asset_id'])
        if _identity(asset) != job['identity']:
            raise ConflictError('Attachment changed; prepare a new download')
        context = self.remote._connection_context(root, job['source_id'])
        with self.lock, self._db(root) as db:
            job = self._get(db, job_id)
            if context[2] != job['source_revision']:
                self._delete_files(root, job)
                db.execute("UPDATE jobs SET head='{}',downloaded=0 WHERE id=?", (job_id,))
            db.execute("UPDATE jobs SET state='queued',source_revision=?,credential_revision=?,workspace_revision=?,error='',retry_at=NULL,updated=? WHERE id=?",
                       (context[2], context[3], self.remote.config.data.get('revision', ''), self.clock(), job_id))
            if guard is not None:
                self.guards[job_id] = guard
            result = self._public(self._get(db, job_id))
        self.wake.set()
        return result

    def resolve_handle(self, root, handle, *, owner='local', guard=None):
        """Resolve without retaining the file; streamed responses must acquire it."""
        return self._resolve_handle(root, handle, owner=owner, guard=guard)['path']

    def acquire_handle(self, root, handle, *, owner='local', guard=None):
        """Internal response lease; always pair with release_handle in finally.

        The returned Path is for the authenticated local response only and must
        never be serialized into a public job or MCP result.
        """
        return self._resolve_handle(root, handle, owner=owner, guard=guard, acquire=True)

    def _resolve_handle(self, root, handle, *, owner='local', guard=None, acquire=False):
        root = self._root(root)
        if not isinstance(handle, str) or not _HANDLE.fullmatch(handle):
            raise FileNotFoundError('Download handle is unavailable')
        with self.lock, self._db(root) as db:
            row = db.execute("SELECT * FROM jobs WHERE handle=? AND state='ready'", (handle,)).fetchone()
            if not row:
                raise FileNotFoundError('Download handle is unavailable')
            job = dict(row)
        self._visible(root, job, owner, guard)
        if job['expires'] is None or job['expires'] <= self.clock():
            raise FileNotFoundError('Download handle expired')
        self._check(root, job, credentials=False)
        file = self._files(root, job)[1]
        metadata = json.loads(job['snapshot'])
        with self.lock:
            with self._db(root) as db:
                current = self._get(db, job['id'])
                if current['state'] != 'ready' or current['handle'] != handle or current['expires'] <= self.clock():
                    raise FileNotFoundError('Download handle is unavailable')
                info = file.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_size != job['size']:
                    raise FileNotFoundError('Downloaded file is unavailable')
                db.execute('UPDATE jobs SET accessed=? WHERE id=?', (self.clock(), job['id']))
            # The same lock excludes release/LRU until the consumer owns a pin.
            if acquire:
                key = (root, job['id'])
                self.consumer_pins[key] = self.consumer_pins.get(key, 0) + 1
        return {'path': file, 'job_id': job['id'], 'name': metadata.get('name', 'attachment'),
                'mime': metadata.get('mime', 'application/octet-stream')}

    def release_handle(self, root, job_id):
        """Drop one consumer pin, including after its vault was disconnected."""
        if not isinstance(job_id, str) or not _ID.fullmatch(job_id):
            raise ValueError('Invalid download job ID')
        root = str(root)
        key = (root, job_id)
        with self.lock:
            count = self.consumer_pins.get(key, 0)
            if count <= 0:
                return
            if count > 1:
                self.consumer_pins[key] = count - 1
                return
            del self.consumer_pins[key]
            # Unpin a retired vault without touching its files. Its next normal
            # recovery pass will remove any explicitly released staging copy.
            try:
                self._root(root)
            except (ConflictError, ValueError):
                return
            with self._db(root) as db:
                job = self._get(db, job_id)
                if job['state'] == 'released':
                    self._delete_files(root, job)
                    db.execute('UPDATE jobs SET downloaded=0,updated=? WHERE id=?', (self.clock(), job_id))

    def _check(self, root, job, *, credentials=True):
        self._root(root)
        if self.stopped.is_set() or job['id'] in self.cancelled:
            raise InterruptedError('Download stopped')
        self._authorize(root, job['owner'], job['workspace_revision'], self.guards.get(job['id']))
        asset = self._snapshot(root, job['asset_id'])
        if _identity(asset) != job['identity']:
            raise ConflictError('Attachment changed during download')
        context = self.remote._connection_context(root, job['source_id'])
        if context[2] != job['source_revision']:
            raise PermissionError('Attachment source changed')
        if credentials:
            credential = self.remote.credentials.get(job['source_id'])
            if not credential:
                raise RemoteStorageError('credentials_required', 'auth_required')
            if credential[3] not in {'local', job['owner']}:
                raise PermissionError('Attachment credentials belong to another owner')
            if job['credential_revision'] and context[3] != job['credential_revision']:
                raise PermissionError('Attachment credentials changed')
        return context

    def _update(self, root, job_id, **values):
        allowed = {'state', 'downloaded', 'head', 'sha256', 'handle', 'expires', 'updated', 'accessed', 'error', 'attempts', 'retry_at', 'credential_revision'}
        if set(values) - allowed:
            raise ValueError('Invalid download update')
        with self.lock, self._db(root) as db:
            current = self._get(db, job_id)
            if current['state'] in {'released', 'evicted'}:
                raise InterruptedError('Download released')
            db.execute('UPDATE jobs SET ' + ','.join(key + '=?' for key in values) + ' WHERE id=?', (*values.values(), job_id))

    def process_pending(self, root=None):
        """One job per pass; exposed for deterministic tests and service polling."""
        if not self.worker_lock.acquire(blocking=False):
            return
        try:
            root = self._root(root)
            with self.lock, self._db(root) as db:
                self._cleanup(db, root)
                row = db.execute("SELECT * FROM jobs WHERE state='queued' OR (state='paused' AND retry_at IS NOT NULL AND retry_at<=?) ORDER BY created LIMIT 1", (self.clock(),)).fetchone()
                if not row:
                    return
                job = dict(row)
                db.execute("UPDATE jobs SET state='downloading',attempts=attempts+1,error='',retry_at=NULL,updated=? WHERE id=?", (self.clock(), job['id']))
                job['attempts'] += 1
            self._run(root, job)
        finally:
            self.worker_lock.release()

    def _open(self, file, *, create=False):
        flags = os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
        if create:
            flags |= os.O_CREAT | os.O_EXCL
        descriptor = os.open(file, flags, 0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError('Download staging must be a regular file')
        return os.fdopen(descriptor, 'r+b')

    def _run(self, root, job):
        provider = None
        head = json.loads(job['head'])
        part = complete = None
        try:
            part, complete = self._files(root, job)
            context = self._check(root, job)
            if not job['credential_revision']:
                job['credential_revision'] = context[3]
                self._update(root, job['id'], credential_revision=context[3])
            provider = self.remote._provider(job['source_id'], root, guard=lambda: self._check(root, job))
            head = provider.stat(json.loads(job['snapshot'])['path'])
            original = json.loads(job['snapshot'])
            if head['size'] != job['size'] or (_strong(original.get('etag')) and head['etag'] != original['etag']):
                raise RemoteStorageError('remote_version_changed')
            if original.get('mtime') and head.get('mtime') and original['mtime'] != head['mtime']:
                raise RemoteStorageError('remote_version_changed')
            if complete.exists() and not part.exists():
                os.replace(complete, part)  # Recover a crash between rename and journal commit.
            previous = json.loads(job['head'])
            resume = part.exists() and _strong(head.get('etag')) and previous and _version(previous) == _version(head)
            if part.exists() and not resume:
                part.unlink()
            offset = part.stat().st_size if part.exists() else 0
            if offset > job['size']:
                raise RemoteStorageError('invalid_content_length')
            if self.disk_usage(self._path(root)).free < job['size'] - offset + self.reserve_bytes:
                raise RemoteStorageError('insufficient_disk_space')
            self._update(root, job['id'], head=_json(head))
            with self._open(part, create=not part.exists()) as output:
                offset = os.fstat(output.fileno()).st_size
                if offset > job['size']:
                    raise RemoteStorageError('invalid_content_length')
                digest = hashlib.sha256()
                while chunk := output.read(_CHUNK):
                    provider.guard()
                    digest.update(chunk)
                digest = self._stream(provider, root, job, head, output, offset, digest)
                output.flush()
                os.fsync(output.fileno())
            provider.guard()
            after = provider.stat(original['path'])
            if _version(after) != _version(head):
                raise RemoteStorageError('remote_version_changed')
            actual = digest.hexdigest()
            expected = original.get('sha256', '')
            if expected and (not _SHA.fullmatch(expected) or expected != actual):
                raise RemoteStorageError('checksum_mismatch')
            provider.guard()
            os.replace(part, complete)
            self._update(root, job['id'], state='ready', downloaded=job['size'], sha256=actual,
                         handle=secrets.token_urlsafe(32), expires=self.clock() + self.handle_ttl,
                         error='', retry_at=None, accessed=self.clock(), updated=self.clock())
        except Exception as error:
            try:
                self._root(root)
            except (ConflictError, ValueError):
                self.recovered.discard(root)
                return  # Leave this vault's journal for recovery if it reconnects.
            if isinstance(error, httpx.HTTPError) and provider is not None:
                try:
                    provider._failed('connection_unavailable', 'unreachable')
                except RemoteStorageError as recorded:
                    error = recorded
            if job['id'] in self.cancelled:
                try:
                    self._delete_files(root, job)
                except (OSError, ValueError, ConflictError):
                    pass
                return
            code = error.code if isinstance(error, RemoteStorageError) else ('insufficient_disk_space' if isinstance(error, OSError) and error.errno in {errno.ENOSPC, errno.EDQUOT} else
                    'asset_changed' if isinstance(error, ConflictError) else
                    'authorization_changed' if isinstance(error, PermissionError) else 'interrupted' if isinstance(error, InterruptedError) else 'download_failed')
            # Only explicit, fixed diagnostics leave this module.
            known = {'credentials_required', 'authentication_required', 'connection_unavailable', 'service_temporarily_unavailable',
                     'remote_version_changed', 'remote_not_found', 'insufficient_disk_space', 'invalid_content_length',
                     'invalid_range_response', 'unexpected_login_page', 'checksum_mismatch', 'redirect_refused',
                     'asset_changed', 'authorization_changed', 'interrupted', 'download_failed'}
            if code not in known:
                code = 'download_failed'
            resumable_error = code in {'connection_unavailable', 'service_temporarily_unavailable', 'credentials_required', 'interrupted'}
            if part is not None and (not _strong(head.get('etag')) or not (resumable_error or code == 'insufficient_disk_space')):
                try:
                    part.unlink(missing_ok=True)
                    if complete is not None:
                        complete.unlink(missing_ok=True)
                except OSError:
                    pass
            paused = resumable_error or code in {'authentication_required', 'insufficient_disk_space', 'authorization_changed'}
            retry_at = self.clock() + min(60, 2 ** min(job['attempts'], 6)) if resumable_error else None
            try:
                downloaded = part.stat().st_size if part is not None and part.exists() else 0
                self._update(root, job['id'], state='paused' if paused else 'failed', downloaded=downloaded,
                             error=code, retry_at=retry_at, updated=self.clock())
            except (OSError, ValueError, ConflictError, InterruptedError):
                pass  # A switched root or explicit release owns the next transition.

    def _stream(self, provider, root, job, head, output, offset, digest):
        size = job['size']
        if offset == size and offset:
            return digest
        headers = {}
        if _strong(head.get('etag')):
            headers['If-Match'] = head['etag']
        elif head.get('mtime'):
            headers['If-Unmodified-Since'] = head['mtime']
        if offset:
            headers.update(Range=f'bytes={offset}-', **{'If-Range': head['etag']})
        provider.guard()
        with provider._client() as client, client.stream('GET', provider.url(head['path']), headers=headers) as response:
            if response.status_code == 412:
                raise RemoteStorageError('remote_version_changed')
            provider._status(response, (200, 206) if offset else (200,))
            if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                raise RemoteStorageError('invalid_content_length')
            if _strong(head.get('etag')) and response.headers.get('etag') != head['etag']:
                raise RemoteStorageError('remote_version_changed')
            if 'text/html' in response.headers.get('content-type', '').lower() and Path(head['path']).suffix.lower() not in {'.html', '.htm'}:
                raise RemoteStorageError('unexpected_login_page')
            if offset and response.status_code == 200:
                offset = 0
                output.seek(0)
                output.truncate()
                digest = hashlib.sha256()
            if response.headers.get('content-length') != str(size - offset):
                raise RemoteStorageError('invalid_content_length')
            if offset and response.headers.get('content-range') != f'bytes {offset}-{size - 1}/{size}':
                raise RemoteStorageError('invalid_range_response')
            total, published = offset, self.clock()
            for chunk in response.iter_bytes(chunk_size=_CHUNK):
                provider.guard()
                total += len(chunk)
                if total > size:
                    raise RemoteStorageError('invalid_content_length')
                digest.update(chunk)
                output.write(chunk)
                if self.clock() - published >= 0.25:
                    self._update(root, job['id'], downloaded=total, updated=self.clock())
                    published = self.clock()
            if total != size:
                provider._failed('connection_unavailable', 'unreachable')
        return digest

    def _loop(self):
        while not self.stopped.is_set():
            try:
                root = self._root()
                if self._path(root, 'downloads.sqlite').exists():
                    self.process_pending(root)
            except Exception:
                pass  # Keep private diagnostics and transient startup failures local.
            self.wake.wait(2)
            self.wake.clear()

    def stop(self):
        self.stopped.set()
        self.wake.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)

    close = stop
