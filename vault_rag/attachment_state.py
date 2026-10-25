"""Device-private attachment state; never a database shared by folder sync.

Upgrade takes consistent SQLite snapshots and leaves all legacy material intact.
Release claims stay beside originals so rename remains on the same filesystem.
"""
from contextlib import closing
import hashlib
import json
import shutil
import sqlite3
import threading
import uuid

from vault_rag.platform_support import is_link, path_key, private_file_mode

_LOCK = threading.RLock()
_DIRECTORIES = {'remote-attachments', 'asset-library', 'attachment-groups'}
_MIGRATE_DIRECTORIES = _DIRECTORIES | {'asset-downloads', 'attachment-downloads'}


def device_attachment_state(parts):
    return bool(parts) and (parts[0] in _DIRECTORIES or parts[0] in {
        'attachment-index-job.json', 'attachment-thumbnails', 'remote-attachment-thumbnails',
        'attachment-downloads', 'asset-downloads',
    } or parts[0].startswith(('attachments.sqlite', 'attachments-before-v1-'))) and not (
        parts[0] == 'remote-attachments' and len(parts) > 1 and parts[1] == 'release')


def _copy(source, target):
    if is_link(source):
        raise ValueError('Legacy attachment state cannot contain links')
    if source.is_dir():
        target.mkdir()
        for child in source.iterdir():
            # Rebuildable bytes need no upgrade copy. Transfer staging does.
            if source.name == 'remote-attachments' and child.name in {'cache', 'ranges', 'release'}:
                continue
            if child.name.endswith(('-wal', '-shm', '-journal')):
                continue
            _copy(child, target / child.name)
    elif source.is_file():
        if source.suffix == '.sqlite':
            watched = [source, *(source.with_name(source.name + suffix) for suffix in ('-wal', '-journal'))]
            def versions():
                return [(p.stat().st_ino, p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None for p in watched]
            before = versions()
            for suffix in ('-wal', '-shm', '-journal'):
                if is_link(source.with_name(source.name + suffix)):
                    raise ValueError('Legacy attachment database sidecar cannot be a link')
            with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=10)) as old:
                with closing(sqlite3.connect(target)) as new:
                    old.backup(new)
                    if new.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                        raise ValueError('Legacy attachment database needs recovery; original preserved')
                    if source.name == 'manifest.sqlite':
                        tables = {row[0] for row in new.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                        for table in ('cache', 'ranges'):
                            if table in tables:
                                new.execute('DELETE FROM ' + table)
                        new.commit()
            if versions() != before:
                raise ValueError('Legacy attachment database changed during upgrade; stop the old app and sync, then retry')
        else:
            before = source.stat()
            shutil.copyfile(source, target)
            after = source.stat()
            if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                raise ValueError('Legacy attachment state changed during upgrade; retry after stopping sync')
        private_file_mode(target)
    else:
        raise ValueError('Legacy attachment state must be regular files')


def attachment_state_root(config):
    key = hashlib.sha256(path_key(str(config.root)).encode()).hexdigest()
    parent = config.directory / 'attachment-workspaces'
    target = parent / key
    with _LOCK:
        if is_link(parent) or is_link(target):
            raise ValueError('Device attachment state cannot be a link')
        if target.is_dir():
            return target
        parent.mkdir(exist_ok=True, mode=0o700)
        stage = parent / (key + '.partial-' + uuid.uuid4().hex)
        stage.mkdir(mode=0o700)
        try:
            legacy = config.root / '.vault-rag'
            if is_link(legacy):
                raise ValueError('Legacy attachment state cannot be a link')
            if legacy.is_dir():
                settings = legacy / 'remote-attachments' / 'settings.json'
                for component in (settings.parent, settings):
                    if is_link(component):
                        raise ValueError('Legacy attachment settings cannot be a link')
                value = json.loads(settings.read_text()) if settings.is_file() else None
                if value is not None and not isinstance(value, dict):
                    raise ValueError('Legacy attachment settings must be an object; original preserved')
                foreign = value is not None and value.get('root') != str(config.root)
                if foreign:
                    # A synced vault can arrive at a different OS/path. Reuse
                    # public server configuration, never another root's queues,
                    # authorization, local identities or recovery operations.
                    destination = stage / 'remote-attachments'
                    destination.mkdir(mode=0o700)
                    value.update(root=str(config.root), revision=uuid.uuid4().hex)
                    (destination / 'settings.json').write_text(json.dumps(value, ensure_ascii=False))
                    private_file_mode(destination / 'settings.json')
                else:
                    for child in legacy.iterdir():
                        if child.name in _MIGRATE_DIRECTORIES or child.name in {'attachments.sqlite', 'attachment-index-job.json'}:
                            _copy(child, stage / child.name)
            # Publish a complete snapshot once. Later folder-sync updates cannot
            # replace this machine's DB, settings, credentials or transfer queue.
            try:
                stage.rename(target)
            except OSError:
                if not target.is_dir() or is_link(target):
                    raise
            return target
        finally:
            if stage.exists():
                shutil.rmtree(stage)
