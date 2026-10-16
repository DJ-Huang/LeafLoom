"""Ephemeral, credential-scoped files for the CLI bridge; never a vault or index."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import secrets
import shutil
import tempfile
import time

from vault_rag.local_state import relative
from vault_rag.platform_support import is_link, protect_private_directory


class FeishuFiles:
    CHUNK = 256 * 1024
    MAX_FILE = 256 * 1024 * 1024
    MAX_TOTAL = 1024 * 1024 * 1024
    TTL = 24 * 60 * 60

    def __init__(self, config):
        self.config = config
        self.temp = tempfile.TemporaryDirectory(prefix='feishu-transfer-', dir=config.directory)
        self.root = Path(self.temp.name)
        protect_private_directory(self.root)
        self.entries = {}

    def purge(self):
        now = time.time()
        for key, row in list(self.entries.items()):
            if now >= row['expires_at']:
                (self.root / key).unlink(missing_ok=True)
                del self.entries[key]

    def usage(self, owner):
        self.purge()
        return sum(row['size'] for row in self.entries.values() if row['owner'] == owner)

    def get(self, owner, file_id, source_check):
        self.purge()
        row = self.entries.get(file_id)
        if row is None or row['owner'] != owner:
            raise FileNotFoundError('Temporary file is unavailable for this credential')
        for source in row['sources']:
            source_check(source)
        return row

    def info(self, file_id):
        row = self.entries[file_id]
        return {k: row[k] for k in ('name', 'size', 'sha256', 'complete', 'expires_at')} | {'file_id': file_id}

    def allocate(self, owner, name, sources=()):
        if not isinstance(name, str) or not name or relative(name) != name or '/' in name or '\\' in name:
            raise ValueError('Use a plain filename')
        if len(name.encode('utf-8')) > 200 or name.startswith('.'):
            raise ValueError('Invalid filename')
        if sum(row['owner'] == owner for row in self.entries.values()) >= 1024:
            raise ValueError('Too many temporary files; remove unused files')
        key = secrets.token_hex(24)
        (self.root / key).touch(exist_ok=False)
        self.entries[key] = dict(owner=owner, name=name, size=0, sha256='', complete=False,
                                 expires_at=time.time() + self.TTL, sources=list(sources))
        return key

    def discard(self, key):
        (self.root / key).unlink(missing_ok=True)
        self.entries.pop(key, None)

    def register(self, owner, path, sources=()):
        size = path.stat().st_size
        if size > self.MAX_FILE or self.usage(owner) + size > self.MAX_TOTAL:
            raise ValueError('Temporary file quota exceeded')
        key = self.allocate(owner, path.name, sources)
        try:
            digest = hashlib.sha256()
            written = 0
            with path.open('rb') as src, (self.root / key).open('wb') as dst:
                while chunk := src.read(self.CHUNK):
                    written += len(chunk)
                    if written > size:
                        raise ValueError('File changed while copying')
                    dst.write(chunk)
                    digest.update(chunk)
            if written != size:
                raise ValueError('File changed while copying')
            self.entries[key].update(size=written, sha256=digest.hexdigest(), complete=True)
            return self.info(key)
        except Exception:
            self.discard(key)
            raise

    def operation(self, owner, source_check, action, *, file_id='', name='', offset=0,
                  data_base64='', complete=False, size=None, sha256='', path=''):
        self.purge()
        if action == 'import_workspace':
            source = {'root': str(self.config.root), 'path': relative(path)}
            source_check(source)
            p = self.config.path_for(path)
            if not p.is_file():
                raise ValueError('Select a regular connected file')
            return {'ok': True, **self.register(owner, p, [source])}
        if action == 'put':
            if type(offset) is not int or offset < 0 or type(complete) is not bool:
                raise ValueError('Invalid chunk offset or completion flag')
            if not isinstance(data_base64, str) or len(data_base64) > (self.CHUNK + 2) // 3 * 4:
                raise ValueError('Chunk exceeds 256 KiB')
            try:
                chunk = base64.b64decode(data_base64, validate=True)
            except (ValueError, TypeError) as error:
                raise ValueError('Invalid Base64 chunk') from error
            if len(chunk) > self.CHUNK:
                raise ValueError('Chunk exceeds 256 KiB')
            if not file_id and offset != 0:
                raise ValueError('New files start at offset zero')
            if complete and (type(size) is not int or not isinstance(sha256, str) or
                             len(sha256) != 64):
                raise ValueError('Completion requires total size and SHA-256')
            key = file_id or self.allocate(owner, name)
            row = self.get(owner, key, source_check)
            if row['complete'] or offset != row['size']:
                raise ValueError('Chunks must be sequential; completed files are immutable')
            total = offset + len(chunk)
            if total > self.MAX_FILE or self.usage(owner) + len(chunk) > self.MAX_TOTAL:
                if not file_id:
                    self.discard(key)
                raise ValueError('Temporary file quota exceeded')
            with (self.root / key).open('ab') as stream:
                stream.write(chunk)
            row['size'] = total
            if complete:
                with (self.root / key).open('rb') as stream:
                    actual = hashlib.file_digest(stream, 'sha256').hexdigest()
                if size != total or sha256.lower() != actual:
                    self.discard(key)
                    raise ValueError('File size or SHA-256 mismatch; upload discarded')
                row.update(sha256=actual, complete=True)
            return {'ok': True, **self.info(key)}
        row = self.get(owner, file_id, source_check)
        if action == 'stat':
            return {'ok': True, **self.info(file_id)}
        if action == 'remove':
            self.discard(file_id)
            return {'ok': True}
        if action == 'get':
            if type(offset) is not int or not 0 <= offset <= row['size'] or not row['complete']:
                raise ValueError('Invalid offset or unfinished file')
            with (self.root / file_id).open('rb') as stream:
                stream.seek(offset)
                chunk = stream.read(self.CHUNK)
            return {'ok': True, **self.info(file_id), 'offset': offset,
                    'next_offset': offset + len(chunk), 'eof': offset + len(chunk) == row['size'],
                    'data_base64': base64.b64encode(chunk).decode('ascii')}
        raise ValueError('Unknown temporary file action')

    @staticmethod
    def job_path(job, value):
        if not isinstance(value, str) or not value or '\\' in value or ':' in value or relative(value) != value:
            raise ValueError('Use a relative path inside the command directory')
        p = job / value
        if not p.resolve().is_relative_to(job):
            raise ValueError('Path escapes the command directory')
        for component in [p, *p.parents]:
            if component == job:
                break
            if is_link(component):
                raise ValueError('Links and junctions are not allowed')
        return p

    def prepare(self, owner, source_check, job, input_files):
        if not isinstance(input_files, dict) or len(input_files) > 100:
            raise ValueError('Invalid input_files mapping')
        sources = []
        paths = set()
        for rel, file_id in input_files.items():
            p = self.job_path(job, rel)
            row = self.get(owner, file_id, source_check)
            if not row['complete']:
                raise ValueError('Input file is not complete')
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists():
                raise ValueError('Duplicate input path')
            shutil.copyfile(self.root / file_id, p)
            paths.add(p)
            sources.extend(source for source in row['sources'] if source not in sources)
        return paths, sources

    def scan(self, owner, job, inputs):
        outputs = []
        total = self.usage(owner)
        pending = [job]
        count = 0
        while pending:
            directory = pending.pop()
            for p in directory.iterdir():
                count += 1
                if count > 4096 or is_link(p):
                    raise ValueError('Command output has too many entries or contains a link')
                if p.is_dir():
                    pending.append(p)
                elif p.is_file():
                    size = p.stat().st_size
                    if size > self.MAX_FILE:
                        raise ValueError('Command file exceeds 256 MiB')
                    if p not in inputs:
                        total += size
                        outputs.append(p)
                else:
                    raise ValueError('Only regular output files are allowed')
                if total > self.MAX_TOTAL:
                    raise ValueError('Temporary file quota exceeded')
        return outputs
