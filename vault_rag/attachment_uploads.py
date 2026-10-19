"""Shared streaming upload target: stage beside the destination, publish exclusively."""
from __future__ import annotations

import os
import uuid

from vault_rag.local_state import ConflictError, relative


class UploadTarget:
    def __init__(self, runtime, *, folder='', name='', root=None, revision=None,
                 create_folder=False, central=False, unique=False):
        self.runtime = runtime
        self.config = runtime.config
        self.published = False
        if not name or name in {'.', '..'} or '/' in name or '\\' in name or '\x00' in name:
            raise ValueError('文件名无效')
        if (create_folder or central or unique) and root is None:
            raise ValueError('创建附件目录需要指定关联目录')
        with self.config.lock, runtime.files.lock:
            runtime.files.ensure_mutable()
            self.root = str(self.config.root)
            self.revision = self.config.data.get('revision')
            if (root is not None and root != self.root) or (revision is not None and revision != self.revision):
                raise ConflictError('关联目录已切换，附件未写入')
            if central:
                folder = self.config.data.get('attachment_folder', '_attachments')
            self.rel = '/'.join(x for x in (relative(folder), name) if x)
            self.destination = self.config.path_for(self.rel, writable=True)
            self.unique = unique
            if self.destination.exists() and not unique:
                raise ConflictError('同名文件已存在')
            if create_folder or central:
                self.destination.parent.mkdir(parents=True, exist_ok=True)
            self.config.path_for(self.rel, writable=True)
            self.temp = self.destination.with_name('.upload-' + uuid.uuid4().hex)
            self.stream = self.temp.open('xb')

    def finish(self):
        if not self.stream.closed:
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.stream.close()

    def commit(self, before_publish=None):
        self.finish()
        with self.config.lock, self.runtime.files.lock:
            self.runtime.files.ensure_mutable()
            if str(self.config.root) != self.root or self.config.data.get('revision') != self.revision:
                raise ConflictError('关联目录已切换，附件未写入')
            if self.config.path_for(self.rel, writable=True) != self.destination:
                raise ConflictError('附件目录已变化，未写入')
            destination = self.destination
            number = 2
            while True:
                rel = destination.relative_to(self.config.root).as_posix()
                self.config.path_for(rel, writable=True)
                if before_publish:
                    before_publish(rel, self.temp.relative_to(self.config.root).as_posix())
                try:
                    os.link(self.temp, destination)
                    break
                except FileExistsError:
                    if not self.unique:
                        raise ConflictError('同名文件已存在') from None
                    destination = self.destination.with_name(self.destination.stem + f' ({number})' + self.destination.suffix)
                    number += 1
            self.published = True
            self.runtime.files_changed(rel)
            return {'path': rel}

    def close(self):
        self.stream.close()
        self.temp.unlink(missing_ok=True)
