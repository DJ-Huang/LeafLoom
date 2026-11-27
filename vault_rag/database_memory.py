"""An in-memory file store for the normal database service.

Only the encrypted package is persisted. Ordinary vault paths, history and
catalog state never receive private database content.
"""
from pathlib import PurePosixPath
import secrets
import threading
import time
from types import SimpleNamespace
import uuid

import frontmatter

from vault_rag.catalog import Catalog
from vault_rag.database_board import property_text, serialized
from vault_rag.databases import Databases
from vault_rag.local_state import ConflictError, digest, relative
from vault_rag.note_operations import NoteOperations

DEFINITION = '.vault-rag/Database.base'


class MemoryPath:
    def __init__(self, storage, path):
        self.storage, self.path = storage, path

    @property
    def parent(self):
        return MemoryPath(self.storage, self.path.rpartition('/')[0])

    @property
    def name(self):
        return self.path.rsplit('/', 1)[-1]

    @property
    def suffix(self):
        return PurePosixPath(self.path).suffix

    @property
    def stem(self):
        return PurePosixPath(self.path).stem

    def relative_to(self, root):
        return PurePosixPath(self.path)

    def is_file(self):
        return self.path in self.storage.files

    def is_dir(self):
        return self.path in self.storage.directories

    def exists(self):
        return self.is_file() or self.is_dir()

    def read_bytes(self):
        if not self.is_file():
            raise FileNotFoundError('db.securityFileMissing')
        return self.storage.files[self.path][0]

    def read_text(self):
        return self.read_bytes().decode('utf-8')

    def stat(self):
        data = self.read_bytes()
        _, modified, created = self.storage.files[self.path]
        return SimpleNamespace(st_size=len(data), st_mtime=modified,
                               st_mtime_ns=int(modified * 1e9), st_ctime=created, st_birthtime=created)

    def mkdir(self, parents=False, exist_ok=False):
        if self.exists():
            if not (exist_ok and self.is_dir()):
                raise FileExistsError('db.securityFileExists')
            return
        if parents:
            self.parent.mkdir(parents=True, exist_ok=True)
        elif not self.parent.is_dir():
            raise FileNotFoundError('db.securityFileMissing')
        self.storage.directories.add(self.path)
        self.storage.mutated = True

    def glob(self, pattern):
        return [MemoryPath(self.storage, name) for name in self.storage.files
                if name.rpartition('/')[0] == self.path and PurePosixPath(name).match(pattern)]

    def unlink(self, missing_ok=False):
        if missing_ok and not self.is_file():
            return
        self.read_bytes()
        del self.storage.files[self.path]
        self.storage.mutated = True


class PrivateNotes(NoteOperations):
    def metadata(self):
        return self.runtime.catalog

    def operation(self, action, path, workspace_revision, destination='', dry_run=True,
                  operation_token=None, limit=50, cursor=''):
        self.check_workspace(workspace_revision)
        if action != 'delete':
            raise ValueError('db.securityInvalid')
        current = self.files.read(path)
        token = digest(self.workspace_revision + '\n' + path + '\n' + current['etag'])
        if dry_run:
            return {'ok': True, 'dry_run': True, 'operation_token': token}
        if not isinstance(operation_token, str) or not secrets.compare_digest(operation_token, token):
            raise ConflictError('db.recordConflict')
        key = uuid.uuid4().hex
        trash = self.files.state_path('trash', key, 'content')
        self.files.write_state(trash, self.config.path_for(path).read_bytes())
        self.config.path_for(path).unlink()
        self.files.changed(path)
        return {'ok': True, 'path': path, 'id': key}


class MemoryDatabase:
    def __init__(self, root, revision, files=None, directories=None, version=0):
        self.files = {} if files is None else files
        self.directories = {'', '.vault-rag'} if directories is None else directories
        self.root, self.data = root, {'revision': revision}
        self.lock = threading.RLock()
        self.mutated = False
        self.catalog = Catalog(self)
        self.catalog.version = version
        for path in self.files:
            if path.lower().endswith('.md') and not path.startswith('.vault-rag/'):
                self.catalog.entries[path] = self.catalog._entry(root, self.path_for(path))
        runtime = SimpleNamespace(catalog=self.catalog, files=self)
        self.database = Databases(self, runtime, PrivateNotes(self, runtime))

    def path_for(self, path, *, writable=False):
        return MemoryPath(self, relative(path))

    def state_path(self, *parts):
        return self.path_for('/'.join(('.vault-rag', *parts)))

    def write_state(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        self.files[path.path] = (data, now, self.files[path.path][2] if path.is_file() else now)
        self.mutated = True

    def changed(self, *paths):
        entries = self.catalog.entries.copy()
        for path in paths:
            if not path.lower().endswith('.md'):
                continue
            file = self.path_for(path)
            if file.is_file():
                entries[path] = self.catalog._entry(self.root, file, force=True)
            else:
                entries.pop(path, None)
        self.catalog.entries = entries
        self.catalog.version += 1

    def read(self, rel):
        path = self.path_for(rel)
        data = path.read_bytes()
        text = data.decode('utf-8-sig')
        try:
            metadata = frontmatter.loads(text).metadata if path.suffix.lower() == '.md' else {}
        except (ValueError, TypeError):
            metadata = {}
        return {'path': rel, 'root': str(self.root), 'text': text, 'etag': digest(data),
                'metadata': metadata, 'mtime': path.stat().st_mtime}

    def save(self, rel, text, etag, *, expected_root=None):
        path = self.path_for(rel)
        old = path.read_bytes()
        if (expected_root and expected_root != str(self.root)) or digest(old) != etag:
            raise ConflictError('db.recordConflict')
        new = serialized(text, old)
        history = None
        if new != old:
            if len(new) > 10 * 1024 * 1024:
                raise ValueError('db.securityTooLarge')
            history = uuid.uuid4().hex
            self.write_state(self.state_path('history', history, 'content'), old)
            self.write_state(path, new)
            self.changed(rel)
        return {**self.read(rel), 'history_id': history}

    def properties(self, rel, updates, etag, *, expected_root=None):
        text = property_text(self.read(rel)['text'], updates)
        return self.save(rel, text, etag, expected_root=expected_root)

    def create(self, rel, *, directory=False, text=''):
        path = self.path_for(rel)
        if path.exists():
            raise ConflictError('db.securityFileExists')
        if directory:
            path.mkdir()
        else:
            self.write_state(path, text.encode())
            self.changed(rel)
