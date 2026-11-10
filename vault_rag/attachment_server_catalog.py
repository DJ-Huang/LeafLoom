"""Server-authoritative attachment membership catalog over WebDAV/SMB.

Immutable member records live under ``{metadata_directory}/attachments/v1/members/``.
Local ``manifest.sqlite`` is a projection: membership comes from publish/pull and
explicit import, not from routine directory discovery.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePosixPath

from vault_rag.attachment_scan_policy import in_scan_scope, normalize_scan_roots
from vault_rag.local_state import ConflictError, relative
from vault_rag.remote_webdav import RemoteStorageError, remote_path

SCHEMA = 'leafloom.attachment-member.v1'
MAX_RECORD = 128 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_MEMBERS = 200000


def _members_directory(remote, root, source_id):
    return remote._source(source_id, root)['metadata_directory'] + '/attachments/v1/members'


def _check(remote, root, source_id, directory, provider):
    provider.guard()
    if _members_directory(remote, root, source_id) != directory:
        raise ConflictError('Attachment catalog namespace changed')


def _record_payload(remote, root, source_id, asset_id, row, aliases):
    aliases = set(aliases)
    aliases.add('/'.join((remote.config.data.get('attachment_folder', '_attachments'), '_remote', source_id, row['path'])))
    value = {
        'schema': SCHEMA,
        'asset_id': asset_id,
        'path': row['path'],
        'size': int(row['size'] or 0),
        'mtime': str(row['mtime'] or ''),
        'etag': str(row['etag'] or ''),
        'mime': str(row['mime'] or 'application/octet-stream'),
        'sha256': str(row['sha256'] or ''),
        'aliases': sorted(aliases),
    }
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    if len(data) > MAX_RECORD:
        raise ValueError('Attachment catalog record is too large')
    if len(aliases) > 512:
        raise ValueError('Too many attachment catalog aliases')
    return hashlib.sha256(data).hexdigest(), data, value


def publish_member(remote, root, source_id, asset_id, provider, *, verified_directories=None):
    """Write an immutable membership record for a ready (or verified) asset."""
    directory = _members_directory(remote, root, source_id)
    _check(remote, root, source_id, directory, provider)
    with remote.lock, remote._db(root) as db:
        row = db.execute('SELECT * FROM assets WHERE id=? AND source_id=?', (asset_id, source_id)).fetchone()
        if not row:
            raise ConflictError('Attachment identity changed before publishing catalog')
        # migration_pending is published before local release so peers can see
        # the object; pending uploads wait until verification completes.
        if row['state'] in {'pending', 'redirected'}:
            raise ConflictError('Attachment is not ready for catalog membership')
        aliases = {r[0] for r in db.execute('SELECT path FROM aliases WHERE asset_id=?', (asset_id,))}
        digest, data, _ = _record_payload(remote, root, source_id, asset_id, row, aliases)
    if verified_directories is None:
        provider.ensure_directory(directory)
    _check(remote, root, source_id, directory, provider)
    provider.put_immutable(directory + '/' + digest + '.json', data, max_bytes=MAX_RECORD,
                           verified_directories=verified_directories)
    _check(remote, root, source_id, directory, provider)
    return digest


def _apply_member(remote, root, source_id, value, db):
    physical = remote_path(value['path'], allow_empty=False)
    directory = _members_directory(remote, root, source_id)
    if physical == directory or physical.startswith(directory + '/'):
        raise ValueError('Catalog members cannot address their metadata')
    asset_id = value['asset_id']
    if not isinstance(asset_id, str) or not re.fullmatch('[0-9a-f]{32}', asset_id):
        raise ValueError('Invalid catalog attachment identity')
    aliases = value.get('aliases') or []
    if not isinstance(aliases, list) or not 1 <= len(aliases) <= 512:
        raise ValueError('Invalid catalog aliases')
    for alias in aliases:
        if not isinstance(alias, str) or len(alias) > 4096 or not relative(alias) or relative(alias) != alias:
            raise ValueError('Invalid catalog alias')
        remote.config.path_for(alias)
    item = {
        'path': physical,
        'size': int(value.get('size') or 0),
        'mtime': str(value.get('mtime') or ''),
        'etag': str(value.get('etag') or ''),
        'mime': str(value.get('mime') or mimetypes.guess_type(physical)[0] or 'application/octet-stream'),
    }
    sha256 = str(value.get('sha256') or '')
    existing = db.execute('SELECT * FROM assets WHERE source_id=? AND path=?', (source_id, physical)).fetchone()
    if existing and existing['state'] in {'pending', 'migration_pending'}:
        return existing['id']
    by_id = db.execute('SELECT * FROM assets WHERE id=?', (asset_id,)).fetchone()
    if by_id and by_id['source_id'] != source_id:
        raise ConflictError('Catalog attachment identity conflicts with another storage')
    key = remote._upsert(db, source_id, item, asset_id=asset_id if not existing else existing['id'],
                         sha256=sha256 or (existing['sha256'] if existing else ''), state='ready')
    if existing and existing['id'] != key:
        key = existing['id']
    for alias in aliases:
        current = db.execute('SELECT a.id,a.source_id FROM aliases x JOIN assets a ON a.id=x.asset_id WHERE x.path=?',
                             (alias,)).fetchone()
        if current and current['id'] != key:
            if current['source_id'] != 'local':
                raise ConflictError('Catalog alias conflicts with another storage')
            continue
        db.execute('INSERT INTO aliases VALUES(?,?) ON CONFLICT(path) DO UPDATE SET asset_id=excluded.asset_id '
                   'WHERE aliases.asset_id!=excluded.asset_id', (alias, key))
    return key


def pull_members(remote, root, source_id, provider):
    """Project server membership into the local manifest."""
    directory = _members_directory(remote, root, source_id)
    _check(remote, root, source_id, directory, provider)
    try:
        provider.stat(directory)
    except RemoteStorageError as error:
        if error.code == 'remote_not_found':
            return {'members': 0}
        raise
    records = provider.scan(directory, max_files=MAX_MEMBERS, max_depth=1, prune_reserved=False, read_ignore=False)
    digests = [item['path'].rsplit('/', 1)[-1][:-5] for item in records]
    with remote.lock, remote._db(root) as db:
        cached = {}
        for offset in range(0, len(digests), 256):
            batch = digests[offset:offset + 256]
            if not batch:
                continue
            cached.update((row[0], bytes(row[1])) for row in db.execute(
                'SELECT digest,data FROM reference_records WHERE digest IN (' + ','.join('?' for _ in batch) + ')',
                batch))
    accepted = {}
    total = 0
    applied = 0
    for item in records:
        _check(remote, root, source_id, directory, provider)
        name = item['path'].removeprefix(directory + '/')
        if not re.fullmatch(r'[0-9a-f]{64}\.json', name):
            raise ValueError('Unsupported attachment catalog record')
        if item['size'] > MAX_RECORD or total + item['size'] > MAX_TOTAL:
            raise ValueError('Attachment catalog exceeds the size limit')
        data = cached.get(name[:-5])
        if data is None or hashlib.sha256(data).hexdigest() != name[:-5]:
            data = provider.read_bytes(item['path'], max_bytes=MAX_RECORD)
        total += len(data)
        if len(data) > MAX_RECORD or total > MAX_TOTAL or hashlib.sha256(data).hexdigest() != name[:-5]:
            raise ValueError('Attachment catalog checksum mismatch')
        value = json.loads(data)
        required = {'schema', 'asset_id', 'path', 'size', 'mtime', 'etag', 'mime', 'sha256', 'aliases'}
        if (not isinstance(value, dict) or not required.issubset(value) or value['schema'] != SCHEMA or
                not isinstance(value['path'], str)):
            raise ValueError('Invalid attachment catalog record')
        accepted[name[:-5]] = data
        with remote.lock, remote._db(root) as db:
            _check(remote, root, source_id, directory, provider)
            db.execute('INSERT INTO reference_records VALUES(?,?) ON CONFLICT(digest) DO UPDATE SET data=excluded.data '
                       'WHERE reference_records.data!=excluded.data', (name[:-5], data))
            _apply_member(remote, root, source_id, value, db)
            applied += 1
    return {'members': applied}


def publish_ready_members(remote, root, source_id, provider, *, asset_ids=None):
    """Publish membership for ready assets (bounded batches)."""
    directory = _members_directory(remote, root, source_id)
    with remote.lock, remote._db(root) as db:
        if asset_ids is None:
            keys = [row[0] for row in db.execute(
                "SELECT id FROM assets WHERE source_id=? AND state='ready'", (source_id,))]
        else:
            keys = list(asset_ids)
    if not keys:
        return 0

    def batch(batch_keys):
        worker = remote._provider(source_id, root)

        def check():
            _check(remote, root, source_id, directory, worker)

        worker.guard = check
        with worker.session():
            directories = set()
            for key in batch_keys:
                publish_member(remote, root, source_id, key, worker, verified_directories=directories)

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix='attachment-catalog') as pool:
        futures = [pool.submit(batch, keys[offset::4]) for offset in range(min(4, len(keys)))]
        for future in futures:
            future.result()
    return len(keys)


def sync_catalog(remote, root, source_id, *, guard=None, publish_local=True):
    """Publish local ready members (optional) then pull the server catalog."""
    remote._root(root)
    if source_id == 'local':
        raise ValueError('Select a remote attachment source')
    provider = remote._provider(source_id, root, guard=guard)
    published = 0
    with provider.session():
        if publish_local:
            published = publish_ready_members(remote, root, source_id, provider)
        pulled = pull_members(remote, root, source_id, provider)
    return {'published': published, **pulled}


def import_filesystem(remote, root, source_id, *, guard=None, force_app_only=True, progress=None):
    """One-time walk: register discovered files into the catalog, then app_only.

    After success, automatic discovery scans stop; membership is app/catalog only.
    """
    remote._root(root)
    if source_id == 'local':
        raise ValueError('Select a remote attachment source')
    source = remote._source(source_id, root)
    roots = normalize_scan_roots(source.get('scan_roots', ['']))
    provider = remote._provider(source_id, root, guard=guard)
    from vault_rag.attachment_policy import extensions_for
    from vault_rag.remote_ignore import RemoteIgnore
    ignore = RemoteIgnore((source.get('metadata_directory', ''),),
                          allowed_extensions=extensions_for(remote._files()))
    imported = 0
    with provider.session():
        provider.ensure_directory(_members_directory(remote, root, source_id))
        def on_batch(_batch, info):
            if progress:
                progress({'imported': imported, 'scanned': info.get('scanned', 0),
                          'directories': info.get('directories', 0),
                          'pending_directories': info.get('pending_directories', 0)})
        items = provider.scan(on_batch=on_batch, ignore=ignore, roots=roots)
        for item in items:
            if guard:
                guard()
            if item.get('excluded') or item.get('is_dir'):
                continue
            path = item['path']
            if not in_scan_scope(path, roots):
                continue
            asset_id = uuid.uuid4().hex
            key = None
            with remote.lock, remote._db(root) as db:
                existing = db.execute('SELECT id,state FROM assets WHERE source_id=? AND path=?',
                                      (source_id, path)).fetchone()
                if existing and existing['state'] in {'pending', 'migration_pending'}:
                    continue
                key = remote._upsert(db, source_id, item,
                                     asset_id=existing['id'] if existing else asset_id, state='ready')
                logical = '/'.join((remote.config.data.get('attachment_folder', '_attachments'),
                                    '_remote', source_id, path))
                if not db.execute('SELECT 1 FROM aliases WHERE path=?', (logical,)).fetchone():
                    conflict = db.execute('SELECT asset_id FROM aliases WHERE path=?', (logical,)).fetchone()
                    if conflict and conflict[0] != key:
                        raise ConflictError('Remote attachment logical path conflicts')
                    db.execute('INSERT OR IGNORE INTO aliases VALUES(?,?)', (logical, key))
            if not key:
                continue
            publish_member(remote, root, source_id, key, provider)
            from vault_rag.attachment_server_references import publish as publish_reference
            try:
                publish_reference(remote, root, source_id, key, provider)
            except (ConflictError, ValueError, RemoteStorageError):
                pass
            imported += 1
            if progress:
                progress({'imported': imported, 'scanned': imported, 'path': path,
                          'directories': 0, 'pending_directories': 0})
    if force_app_only:
        set_membership_mode(remote, root, source_id, 'app_only')
    return {'imported': imported, 'membership_mode': 'app_only' if force_app_only else source.get('membership_mode', 'discover')}


def set_membership_mode(remote, root, source_id, mode):
    if mode not in {'discover', 'app_only'}:
        raise ValueError('Invalid attachment membership mode')
    with remote.config.lock, remote.lock:
        settings = remote._settings(root)
        source = next((item for item in settings['sources'] if item['id'] == source_id), None)
        if source is None:
            raise ValueError('Attachment source is unavailable')
        source['membership_mode'] = mode
        remote.save(root, settings, settings['revision'])
    remote.auto_scans.pop((str(root), source_id), None)
    return {'storage_id': source_id, 'membership_mode': mode}
