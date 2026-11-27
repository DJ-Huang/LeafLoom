"""Preflight and publish an encrypted package before retiring its plaintext sources."""
from contextlib import closing
from hashlib import file_digest
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid

import frontmatter
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from vault_rag import database_envelope as envelope, locked_photos, protected_media
from vault_rag.database_board import property_text, serialized
from vault_rag.database_memory import DEFINITION, MemoryDatabase
from vault_rag.local_state import ConflictError, LINK_RE, digest, relative, under
from vault_rag.platform_support import move_exclusive
from vault_rag.database_security import resolve_asset

TRANSACTIONS = 'database-conversions'


def file_hash(path):
    with path.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def sync_directory(path):
    if os.name == 'nt':
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def recover_database_conversions(config, files):
    transactions = files.state_path(TRANSACTIONS)
    if not transactions.is_dir():
        return
    for directory in transactions.iterdir():
        journal = files.state_path(TRANSACTIONS, directory.name, 'journal.json')
        if not journal.is_file():
            # Before publishing the journal the workspace has not been changed.
            continue
        record = json.loads(journal.read_text(encoding='utf-8'))
        definition = config.path_for(record['path'], writable=True)
        actual = file_hash(definition)
        if actual not in (record['original'], record['converted']):
            raise ConflictError('db.securityRecovery')
        if actual == record['original']:
            for index, (state, source) in reversed(list(enumerate(record['sources']))):
                target = files.state_path(*source.split('/')) if state else config.path_for(source, writable=True)
                previous = files.state_path(TRANSACTIONS, directory.name, str(index))
                if previous.exists():
                    if target.exists():
                        raise ConflictError('db.securityRecovery')
                    move_exclusive(previous, target)
                    sync_directory(target.parent)
        for child in directory.iterdir():
            if child == journal:
                continue
            safe = files.state_path(TRANSACTIONS, directory.name, child.name)
            if safe.is_dir():
                shutil.rmtree(safe)
            else:
                safe.unlink()
        journal.unlink()
        directory.rmdir()


class DatabaseConversion:
    def __init__(self, config, runtime, databases, root, path):
        self.config, self.runtime, self.databases = config, runtime, databases
        self.root, self.path = root, relative(path)
        self.files = runtime.files
        self.imported_bytes = 0

    def guard(self):
        if self.root != str(self.config.root):
            raise ConflictError('db.securityWorkspaceChanged')
        self.files.ensure_mutable()
        if not self.path.lower().endswith('.base'):
            raise ValueError('db.securityInvalid')
        recover_database_conversions(self.config, self.files)

    def text_files(self, folder):
        paths = {}
        for file in self.files.walk(strict=True):
            name = file.relative_to(self.config.root).as_posix()
            paths[name] = file
            if name == self.path or file.suffix.lower() != '.base':
                continue
            if under(name, folder):
                raise ValueError('db.securitySharedFolder')
            if envelope.encrypted(file):
                continue
            try:
                parsed = YAML(typ='safe').load(file.read_text(encoding='utf-8-sig')) or {}
                other = parsed.get('leafloom', {}).get('folder')
            except (AttributeError, ValueError, TypeError, YAMLError):
                continue
            if isinstance(other, str) and (under(folder, other) or under(other, folder)):
                raise ValueError('db.securitySharedFolder')
        return paths

    def protected_sources(self, folder):
        if self.config.selected(folder, validated=True) or any(
                under(scope, folder) and self.config.selected(scope, validated=True)
                for scope in self.config.data['include_roots']):
            raise ValueError('db.securityIndexed')
        metadata = self.files.state_path('annotations.sqlite')
        if metadata.is_file():
            with closing(sqlite3.connect(metadata.as_uri() + '?mode=ro', uri=True)) as db:
                if any(under(path, folder) for path, in db.execute('SELECT path FROM documents')):
                    raise ValueError('db.securityAnnotated')
        state = self.files.state_path('generations')
        nodes = [self.files.state_path('nodes.jsonl')]
        if state.is_dir():
            nodes.extend(self.files.state_path('generations', entry.name, 'nodes.jsonl') for entry in state.iterdir())
        for node_file in nodes:
            if node_file.is_file():
                with node_file.open(encoding='utf-8') as stream:
                    if any(under(json.loads(line).get('metadata', {}).get('file_path', ''), folder)
                           for line in stream if line.strip()):
                        raise ValueError('db.securityIndexed')

    def linked_files(self, paths, entries, fields):
        found = set()
        for name in entries:
            if not name.lower().endswith('.md'):
                continue
            post = frontmatter.loads(paths[name].read_text(encoding='utf-8-sig'))
            targets = []
            for key in fields:
                value = post.metadata.get(key.removeprefix('note.'))
                values = value if isinstance(value, list) else [value] if isinstance(value, str) else []
                targets.extend((value, True) for value in values)
            targets.extend((match[2] or match[5], False) for match in LINK_RE.finditer(post.content))
            for target, explicit in targets:
                if isinstance(target, str):
                    match = LINK_RE.fullmatch(target.strip())
                    link = (match[2] or match[5]) if match else target
                    asset = resolve_asset(paths, link, name)
                    if asset and (explicit or paths[asset].suffix.lower() not in {'.md', '.base'}):
                        found.add(asset)
        return found.difference(entries)

    def old_state(self, folder):
        items = []
        for kind in ('history', 'trash', 'operations', 'database-receipts',
                     'database-board-operations', 'database-board-pending'):
            directory = self.files.state_path(kind)
            if not directory.is_dir():
                continue
            for child in directory.iterdir():
                record = self.files.state_path(kind, child.name, 'record.json') if child.is_dir() else self.files.state_path(kind, child.name)
                if not record.is_file():
                    continue
                data = json.loads(record.read_bytes())
                references = [data.get(key, '') for key in ('path', 'target', 'database', 'destination')]
                affected = lambda name: isinstance(name, str) and (name == self.path or under(name, folder))
                if kind == 'operations':
                    references.extend(edit.get(key, '') for edit in data.get('edits', []) for key in ('path', 'after_path'))
                    if any(map(affected, references)) and not all(affected(name) for name in references if name):
                        raise ValueError('db.securityOperationHistory')
                if not any(map(affected, references)):
                    continue
                if kind == 'database-board-pending':
                    raise ValueError('db.securityOperationHistory')
                items.append((kind, child.name))
        return items

    def inspect(self):
        self.guard()
        definition = self.config.path_for(self.path, writable=True)
        settings = self.databases.config_read(self.path)
        folder = settings['folder']
        if not folder or under(self.path, folder):
            raise ValueError('db.securityDedicatedFolder')
        snapshot = self.files.snapshot(folder)
        paths = self.text_files(folder)
        self.protected_sources(folder)
        entries = set(snapshot) - {name for name, kind in snapshot.items() if kind == 'directory'}
        external = self.linked_files(paths, entries, [
            key for key, field in settings['fields'].items() if field['type'] == 'attachment'])
        if any(paths[name].suffix.lower() == '.llphoto' for name in external):
            raise ValueError('db.securitySharedFolder')
        if any(paths[name].stat().st_nlink > 1 for name in entries | {self.path}):
            raise ValueError('db.securitySharedFolder')
        internal = self.old_state(folder)
        legacy = protected_media.galleries(self.config.root).get(folder)
        if not legacy and any(name.endswith(locked_photos.EXTENSION) for name in entries):
            raise ValueError('db.securityOldGalleryMissing')
        external_hashes = {name: file_hash(paths[name]) for name in external}
        if sum(paths[name].stat().st_size for name in entries | external | {self.path}) > envelope.MAX_BYTES:
            raise ValueError('db.securityTooLarge')
        info = {'revision': digest(json.dumps([
                    settings['revision'], snapshot, external_hashes,
                    internal], sort_keys=True)),
                'records': sum(name.lower().endswith('.md') for name in entries),
                'attachments': len(external) + sum(not name.lower().endswith('.md') for name in entries),
                'shared': len(external), 'legacy': legacy is not None}
        return info, definition, folder, snapshot, paths, external_hashes, internal, legacy

    def preview(self):
        with self.runtime.catalog.update_lock, self.config.lock, self.files.lock:
            return self.inspect()[0]

    def convert(self, body):
        catalog = self.runtime.catalog
        with catalog.update_lock, self.config.lock, self.files.lock:
            info, definition, folder, snapshot, paths, external, internal, legacy = self.inspect()
            if not isinstance(body, dict) or body.get('revision') != info['revision'] or body.get('confirm') is not True:
                raise ConflictError('db.securityPreviewChanged')
            secret, prefix = envelope.new_key(body.get('password'))
            current = MemoryDatabase(self.config.root, self.config.data['revision'])
            self.copy(current, DEFINITION, definition)
            for name, kind in snapshot.items():
                if kind == 'directory':
                    current.path_for(name).mkdir(parents=True, exist_ok=True)
                else:
                    self.copy(current, name, paths[name], kind)
            for name, expected in external.items():
                self.copy(current, name, paths[name], expected)
            for kind, name in internal:
                original = self.files.state_path(kind, name)
                copies = [entry for entry in original.rglob('*') if entry.is_file()] if original.is_dir() else [original]
                for entry in copies:
                    parts = entry.relative_to(self.files.state_path()).parts
                    verified = self.files.state_path(*parts)
                    self.copy(current, '/'.join(('.vault-rag', *parts)), verified)
            if legacy:
                self.import_legacy(current, legacy, body.get('old_password'))

            package = envelope.encode(secret, prefix, current.files, current.directories, current.catalog.version)
            self.publish(definition, folder, internal, package, secret, prefix, info['revision'])
            self.databases._documents.clear()
            self.databases._rows.clear()
            catalog.apply([self.path, folder])
            self.runtime.files_changed(self.path, folder)
            self.runtime.publish('files', [self.path, folder])
            return {'path': self.path}

    def copy(self, current, name, source, expected=None):
        stat = source.stat()
        remaining = envelope.MAX_BYTES - self.imported_bytes
        if stat.st_size > remaining:
            raise ValueError('db.securityTooLarge')
        with source.open('rb') as stream:
            content = stream.read(stat.st_size + 1)
        if len(content) != stat.st_size:
            raise ConflictError('db.securityPreviewChanged')
        if expected and digest(content) != expected:
            raise ConflictError('db.securityPreviewChanged')
        self.imported_bytes += len(content)
        current.write_state(current.path_for(name), content)
        current.files[name] = (content, stat.st_mtime, getattr(stat, 'st_birthtime', stat.st_ctime))

    def import_legacy(self, current, gallery, password):
        from PIL import Image

        key_file = protected_media.envelope_path(self.files.state_path())
        try:
            secret = locked_photos.unwrap_key(key_file.read_bytes(), password)
        except (locked_photos.Locked, ValueError, OSError) as exc:
            raise ValueError('db.securityOldPassword') from exc
        links = {}
        for name, (content, modified, created) in list(current.files.items()):
            if name.rpartition('/')[0] != gallery.assets or not name.endswith(locked_photos.EXTENSION):
                continue
            data = locked_photos.open_payload(secret, gallery.folder, Path(name).name, content)
            with Image.open(BytesIO(data)) as image:
                suffix = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}[image.format]
            target = name.removesuffix(locked_photos.EXTENSION) + suffix
            if current.path_for(target).exists():
                raise ValueError('db.securityInvalid')
            current.write_state(current.path_for(target), data)
            current.files[target] = (data, modified, created)
            current.path_for(name).unlink()
            links[Path(name).name] = Path(target).name
        for name, (content, modified, created) in list(current.files.items()):
            if not name.lower().endswith('.md') or name.startswith('.'):
                continue
            text = content.decode('utf-8-sig')
            post = frontmatter.loads(text)
            cipher = post.metadata.get(locked_photos.CAPTION_FIELD)
            if cipher:
                ident = post.metadata.get('photo_id') or digest(name)
                caption = locked_photos.open_caption(secret, gallery.folder, ident, cipher)
                field = 'title' if gallery.legacy else 'photo_caption'
                text = property_text(text, {field: caption, 'photo_id': None,
                                            locked_photos.CAPTION_FIELD: None})
            for old, new in links.items():
                text = text.replace(old, new)
            current.files[name] = (serialized(text, content), modified, created)

    def publish(self, definition, folder, internal, package, secret, prefix, revision):
        key = uuid.uuid4().hex
        stage = self.files.state_path(TRANSACTIONS, key, 'package')
        journal = self.files.state_path(TRANSACTIONS, key, 'journal.json')
        locked_photos.atomic_bytes(stage, package)
        envelope.decode(stage, secret, prefix)
        if self.inspect()[0]['revision'] != revision:
            shutil.rmtree(stage.parent)
            raise ConflictError('db.securityPreviewChanged')
        sources = [(False, folder), *((True, '/'.join(parts)) for parts in internal)]
        record = {'path': self.path, 'original': file_hash(definition), 'converted': digest(package),
                  'sources': sources}
        locked_photos.atomic_bytes(journal, json.dumps(record, ensure_ascii=False).encode())
        try:
            for index, (state, name) in enumerate(sources):
                source = self.files.state_path(*name.split('/')) if state else self.config.path_for(name, writable=True)
                move_exclusive(source, self.files.state_path(TRANSACTIONS, key, str(index)))
                sync_directory(source.parent)
                sync_directory(stage.parent)
            self.purge_catalogs(folder)
            locked_photos.atomic_bytes(definition, package)
        finally:
            recover_database_conversions(self.config, self.files)

    def purge_catalogs(self, folder):
        storage = self.files.state_path()
        device_attachments = self.files.state_path('attachments.sqlite')
        for path in {storage / 'catalog.sqlite', *storage.glob('catalog-before-v2-*.sqlite'),
                     storage / 'attachments.sqlite', device_attachments,
                     *storage.glob('attachments-before-v1-*.sqlite'),
                     *device_attachments.parent.glob('attachments-before-v1-*.sqlite')}:
            if not path.is_file() or path.is_symlink():
                continue
            with closing(sqlite3.connect(path)) as db:
                db.execute('PRAGMA secure_delete=ON')
                tables = {name for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in ('files', 'cached_entries', 'directories', 'assets'):
                    if table not in tables:
                        continue
                    matched = [(name,) for name, in db.execute('SELECT path FROM ' + table)
                               if name == self.path or under(name, folder)]
                    db.executemany('DELETE FROM ' + table + ' WHERE path=?', matched)
                db.commit()
                db.execute('VACUUM')
                if db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
                    raise ConflictError('db.securityPreviewChanged')
        # Cache keys include past configuration revisions and file timestamps,
        # so an older thumbnail cannot be traced back to its source path.
        for directory in {storage / 'attachment-thumbnails', self.files.state_path('attachment-thumbnails')}:
            if directory.is_symlink():
                raise ValueError('db.securityInvalid')
            for thumb in directory.glob('*.webp'):
                thumb.unlink(missing_ok=True)
