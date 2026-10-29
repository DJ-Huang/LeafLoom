"""Immutable, verified server references, independent of a device's SQLite DB.

Records contain relative paths and public IDs only. Concurrent records merge
only when they name the same object; conflicting aliases never pick a winner.
"""
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor

from vault_rag.local_state import ConflictError, relative
from vault_rag.remote_webdav import RemoteStorageError, remote_path

SCHEMA = 'leafloom.attachment-reference.v1'
MAX_RECORD = 128 * 1024
MAX_TOTAL = 16 * 1024 * 1024


def _directory(remote, root, source_id):
    return remote._source(source_id, root)['metadata_directory'] + '/attachments/v1'


def _check(remote, root, source_id, directory, provider):
    provider.guard()
    if _directory(remote, root, source_id) != directory:
        raise ConflictError('Attachment reference namespace changed')


def publish(remote, root, source_id, asset_id, provider, *, verified_directories=None):
    directory = _directory(remote, root, source_id)
    _check(remote, root, source_id, directory, provider)
    with remote.lock, remote._db(root) as db:
        row = db.execute('SELECT * FROM assets WHERE id=? AND source_id=?', (asset_id, source_id)).fetchone()
        if not row:
            raise ConflictError('Attachment identity changed before publishing references')
        aliases = {r[0] for r in db.execute('SELECT path FROM aliases WHERE asset_id=?', (asset_id,))}
        aliases.add('/'.join((remote.config.data.get('attachment_folder', '_attachments'), '_remote', source_id, row['path'])))
        ids = {asset_id, *(r[0] for r in db.execute('SELECT old_id FROM asset_redirects WHERE new_id=?', (asset_id,)))}
        value = {'schema': SCHEMA, 'path': row['path'], 'aliases': sorted(aliases), 'asset_ids': sorted(ids)}
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    if len(data) > MAX_RECORD:
        raise ValueError('Attachment reference record is too large')
    if len(aliases) > 512 or len(ids) > 512:
        raise ValueError('Too many attachment reference aliases')
    key = hashlib.sha256(data).hexdigest()
    if verified_directories is None:
        provider.ensure_directory(directory)
    _check(remote, root, source_id, directory, provider)
    provider.put_immutable(directory + '/' + key + '.json', data, max_bytes=MAX_RECORD,
                           verified_directories=verified_directories)
    _check(remote, root, source_id, directory, provider)


def pull(remote, root, source_id, provider):
    directory = _directory(remote, root, source_id)
    _check(remote, root, source_id, directory, provider)
    try:
        provider.stat(directory)
    except RemoteStorageError as error:
        if error.code == 'remote_not_found':
            return 0
        raise
    records = provider.scan(directory, max_files=10000, max_depth=1, prune_reserved=False, read_ignore=False)
    digests = [item['path'].rsplit('/', 1)[-1][:-5] for item in records]
    with remote.lock, remote._db(root) as db:
        cached = {}
        for offset in range(0, len(digests), 256):
            batch = digests[offset:offset + 256]
            cached.update((row[0], bytes(row[1])) for row in db.execute(
                'SELECT digest,data FROM reference_records WHERE digest IN (' + ','.join('?' for _ in batch) + ')', batch))
    aliases = {}; identities = {}; total = 0
    accepted = {}
    for item in records:
        _check(remote, root, source_id, directory, provider)
        name = item['path'].removeprefix(directory + '/')
        if not re.fullmatch(r'[0-9a-f]{64}\.json', name):
            raise ValueError('Unsupported server attachment reference record')
        if item['size'] > MAX_RECORD or total + item['size'] > MAX_TOTAL:
            raise ValueError('Server attachment references exceed the size limit')
        data = cached.get(name[:-5])
        if data is None or hashlib.sha256(data).hexdigest() != name[:-5]:
            data = provider.read_bytes(item['path'], max_bytes=MAX_RECORD)
        total += len(data)
        if len(data) > MAX_RECORD or total > MAX_TOTAL or hashlib.sha256(data).hexdigest() != name[:-5]:
            raise ValueError('Server attachment reference checksum mismatch')
        accepted[name[:-5]] = data
        value = json.loads(data)
        if (not isinstance(value, dict) or set(value) != {'schema', 'path', 'aliases', 'asset_ids'} or
                value['schema'] != SCHEMA or not isinstance(value['path'], str) or
                not isinstance(value['aliases'], list) or not 1 <= len(value['aliases']) <= 512 or
                not isinstance(value['asset_ids'], list) or not 1 <= len(value['asset_ids']) <= 512):
            raise ValueError('Invalid server attachment reference record')
        physical = remote_path(value['path'], allow_empty=False)
        if physical == directory or physical.startswith(directory + '/'):
            raise ValueError('Attachment references cannot address their metadata')
        for alias in value['aliases']:
            if not isinstance(alias, str) or len(alias) > 4096 or not relative(alias) or relative(alias) != alias:
                raise ValueError('Invalid server attachment alias')
            remote.config.path_for(alias)
            if alias in aliases and aliases[alias] != physical:
                raise ConflictError('Server attachment alias is ambiguous; references preserved')
            aliases[alias] = physical
        for identity in value['asset_ids']:
            if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{32}', identity):
                raise ValueError('Invalid server attachment identity')
            if identity in identities and identities[identity] != physical:
                raise ConflictError('Server attachment identity is ambiguous; references preserved')
            identities[identity] = physical
    with remote.lock, remote._db(root) as db:
        _check(remote, root, source_id, directory, provider)
        db.executemany('INSERT INTO reference_records VALUES(?,?) ON CONFLICT(digest) DO UPDATE SET data=excluded.data '
                       'WHERE reference_records.data!=excluded.data', accepted.items())
        assets = {row['path']: row['id'] for row in db.execute("SELECT path,id FROM assets WHERE source_id=? AND state NOT IN ('pending','migration_pending','redirected')", (source_id,))}
        for alias, physical in aliases.items():
            key = assets.get(physical)
            if not key:
                continue
            current = db.execute('SELECT a.id,a.source_id FROM aliases x JOIN assets a ON a.id=x.asset_id WHERE x.path=?', (alias,)).fetchone()
            if current and current['id'] != key:
                # A surviving local original retains precedence in _resolve;
                # sharing its server mapping must not delete or rename it.
                if current['source_id'] != 'local':
                    raise ConflictError('Server attachment alias conflicts with another storage')
            db.execute('INSERT INTO aliases VALUES(?,?) ON CONFLICT(path) DO UPDATE SET asset_id=excluded.asset_id '
                       'WHERE aliases.asset_id!=excluded.asset_id', (alias, key))
        for identity, physical in identities.items():
            key = assets.get(physical)
            if not key or identity == key:
                continue
            current = db.execute('SELECT id,source_id,path FROM assets WHERE id=?', (identity,)).fetchone()
            old = db.execute('SELECT asset_id FROM reference_ids WHERE old_id=?', (identity,)).fetchone()
            if current or (old and old[0] != key):
                if (current and current['source_id'] == 'local' and aliases.get(current['path']) == physical):
                    # A peer can still have the original or a copied legacy ID.
                    # Bind the explicit old path but keep that file authoritative
                    # until its deletion arrives; never delete it during a scan.
                    remote._record_redirect(db,identity,key,current['path'],'server-reference')
                    continue
                # Existing local IDs use the migration redirect table instead.
                redirected = db.execute('SELECT new_id FROM asset_redirects WHERE old_id=?', (identity,)).fetchone()
                if not redirected or redirected[0] != key:
                    raise ConflictError('Server attachment identity conflicts with local metadata')
                continue
            db.execute('INSERT OR IGNORE INTO reference_ids VALUES(?,?)', (identity, key))
        _check(remote, root, source_id, directory, provider)
    return len(aliases)


def sync(remote, root, source_id, *, guard=None):
    """Explicit upgrade/backfill: publish old mappings, then import peer records."""
    remote._root(root)
    if source_id == 'local':
        raise ValueError('Select a remote attachment source')
    provider = remote._provider(source_id, root, guard=guard)
    directory = _directory(remote, root, source_id)
    def check():
        _check(remote, root, source_id, directory, provider)
    prefix = remote.config.data.get('attachment_folder', '_attachments') + '/_remote/'
    with remote.lock, remote._db(root) as db:
        keys = [row[0] for row in db.execute("SELECT DISTINCT a.id FROM assets a JOIN aliases x ON x.asset_id=a.id WHERE a.source_id=? AND a.state='ready' AND (a.sha256!='' OR substr(x.path,1,?)!=?)", (source_id, len(prefix), prefix))]
    def batch(batch_keys):
        worker = remote._provider(source_id, root, guard=check)
        with worker.session():
            directories = set()
            for key in batch_keys:
                publish(remote, root, source_id, key, worker, verified_directories=directories)
    if keys:
        # Each worker owns its reusable HTTP session. Immutable readback is
        # retained while directory checks are reused for this bounded batch.
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix='attachment-references') as pool:
            futures = [pool.submit(batch, keys[offset::4]) for offset in range(min(4, len(keys)))]
            for future in futures:
                future.result()
    with provider.session():
        return {'published': len(keys), 'aliases': pull(remote, root, source_id, provider)}
