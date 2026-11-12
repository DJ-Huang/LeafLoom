"""Paged attachment metadata across the local filename index and remote manifest.

Only metadata is joined here. Listing and resolving a remote attachment never
downloads it or adds it to the note/retrieval catalogs.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import posixpath
import re
import sqlite3
import uuid
from contextlib import closing, nullcontext
from pathlib import PurePosixPath

from vault_rag.attachment_scan_policy import register_scan_scope
from vault_rag.attachment_policy import extensions_for, register_policy
from vault_rag.local_state import ConflictError, relative
from vault_rag.platform_support import path_key


_CURSOR_PREFIX = 'ac1.'
_KINDS = {'all', 'image', 'pdf', 'audio', 'video', 'other'}
_SORTS = {'path': 'path', 'name': 'name_key', 'modified': 'mtime_ns', 'size': 'size'}
_KIND_SQL = ("CASE WHEN mime LIKE 'image/%' THEN 'image' "
             "WHEN mime='application/pdf' THEN 'pdf' WHEN mime LIKE 'audio/%' THEN 'audio' "
             "WHEN mime LIKE 'video/%' THEN 'video' ELSE 'other' END")
_STALE = 'Attachment results changed; start from the first page'


class AttachmentCatalog:
    def __init__(self, local_index, remote):
        object.__setattr__(self, '_local_index', local_index)
        object.__setattr__(self, '_remote', remote)

    def __getattr__(self, name):
        return getattr(self._local_index, name)

    def __setattr__(self, name, value):
        if name in {'_local_index', '_remote', 'presentation'}:
            object.__setattr__(self, name, value)
        else:
            setattr(self._local_index, name, value)

    def _manifest(self, files):
        if self._remote is None:
            return None
        # Avoid creating a manifest (or scanning the vault) for existing local-
        # only installations. state_path also rejects substituted symlinks.
        # Do not call manifest_path(): that opens a writer and waits on the
        # scan lock. Listing only reads a catalog that is already on disk.
        path = files.state_path('remote-attachments', 'manifest.sqlite')
        if not path.is_file():
            return None
        return path

    @staticmethod
    def _local_ready(files):
        path = files.state_path('attachments.sqlite')
        for suffix in ('-journal', '-wal', '-shm'):
            files.state_path('attachments.sqlite' + suffix)
        if not path.is_file():
            return False
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
                return db.execute('PRAGMA user_version').fetchone()[0] == 1 and bool(
                    db.execute('SELECT 1 FROM state WHERE root=?', (str(files.config.root),)).fetchone())
        except sqlite3.Error:
            return False

    @classmethod
    def _catalog_connection(cls, local, files, *, include_local=True):
        if not include_local or not cls._local_ready(files):
            # A server catalog remains browsable before local setup, including
            # when an incompatible local index is preserved for a newer app.
            db = sqlite3.connect(':memory:', uri=True)
            db.execute('PRAGMA busy_timeout=2000')
            db.executescript('''CREATE TABLE assets(path TEXT PRIMARY KEY,path_key TEXT,name TEXT,name_key TEXT,
                size INTEGER,mtime_ns INTEGER,mime TEXT,attachment INTEGER);
                CREATE TABLE state(root TEXT PRIMARY KEY,scanned_at REAL);''')
            return db
        # Retain the native index's schema and sidecar validation, then enable
        # URI parsing explicitly. Some bundled SQLite builds disable URI names
        # on ordinary connections, including for ATTACH statements.
        with closing(local._connect(files)):
            pass
        path = files.state_path('attachments.sqlite')
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)
        db.execute('PRAGMA busy_timeout=2000')
        return db

    @staticmethod
    def _attach(db, path, files):
        db.execute('PRAGMA busy_timeout=2000')
        for suffix in ('-journal', '-wal', '-shm'):
            if path.with_name(path.name + suffix).is_symlink():
                raise ValueError('Attachment manifest sidecar cannot be a link')
        db.execute('ATTACH DATABASE ? AS manifest', (path.as_uri() + '?mode=ro',))
        db.row_factory = sqlite3.Row
        register_policy(db, extensions_for(files))
        register_scan_scope(db, [])
        db.create_function('catalog_path_key', 1, path_key, deterministic=True)
        db.create_function('catalog_basename', 1, lambda p: PurePosixPath(p).name, deterministic=True)
        # Trust the local filename index. Stating every path made large or
        # networked vaults exceed the client's timeout and replace the page
        # with a retry. Virtual `_remote/` names are catalog aliases, not
        # local files. A file removed outside the app stays listed until the
        # index updates.
        indexed = {row[0]: (row[1],row[2]) for row in db.execute('SELECT path,size,mtime_ns FROM main.assets')}
        # A completed migration can precede the filename-index notification.
        # Only its recorded source version may suppress that stale index row;
        # an unrelated local file at the same alias remains a local original.
        if indexed and db.execute("SELECT 1 FROM manifest.sqlite_master WHERE type='table' AND name='jobs'").fetchone():
            for path,size,mtime in db.execute("SELECT json_extract(i.value,'$.path'),"
                    "json_extract(i.value,'$.source_version[2]'),json_extract(i.value,'$.source_version[3]') "
                    "FROM manifest.jobs j,json_each(j.payload,'$.items') i "
                    "WHERE j.kind='migration' AND json_extract(i.value,'$.state')='released'"):
                if indexed.get(path)==(size,mtime):indexed.pop(path,None)
        virtual_prefix = files.config.data.get('attachment_folder', '_attachments') + '/_remote/'
        def exists(path):
            if not isinstance(path, str) or path.startswith(virtual_prefix):
                return False
            return path in indexed
        db.create_function('catalog_local_exists', 1, exists)

    @staticmethod
    def _cte(*, remote_only=False):
        # Aliases are authoritative once a verified migration has released its
        # local source. A pending migration keeps the existing local entry.
        # Vault-path caches and pending promotes keep their logical aliases even
        # while the bytes still exist under `_attachments`. Those paths must not
        # also appear as independent local originals.
        remote_path = "? || a.source_id || '/' || a.path" if remote_only else "COALESCE(x.logical_path,? || a.source_id || '/' || a.path)"
        return f'''WITH alias_choice AS (
            SELECT al.asset_id,MIN(al.path) AS logical_path FROM manifest.aliases al
            JOIN manifest.assets owner ON owner.id=al.asset_id
            WHERE NOT catalog_local_exists(al.path)
               OR EXISTS (SELECT 1 FROM manifest.cache c WHERE c.asset_id=al.asset_id AND c.file='vault:'||al.path)
               OR owner.state IN ('pending','migration_pending')
            GROUP BY al.asset_id
        ), catalog AS (
            SELECT l.path,l.name,l.name_key,l.size,l.mtime_ns,l.mime,
                COALESCE(m.id,'') AS asset_id,'local' AS storage_id,
                '' AS remote_path,COALESCE(m.state,'ready') AS state,
                COALESCE(m.description,'') AS description,COALESCE(m.tags,'[]') AS tags,
                COALESCE(m.category,'') AS category,COALESCE(m.metadata_revision,'') AS metadata_revision,
                'complete' AS cache_state
            FROM main.assets l LEFT JOIN manifest.assets m
                ON m.source_id='local' AND m.path=l.path
            WHERE attachment_allowed(l.path)=1 AND catalog_local_exists(l.path)
              AND NOT EXISTS (
                SELECT 1 FROM manifest.aliases al JOIN manifest.assets a ON a.id=al.asset_id
                WHERE al.path=l.path AND a.source_id!='local' AND a.state NOT IN ('missing','excluded','redirected','migration_pending')
                  AND EXISTS (SELECT 1 FROM alias_choice chosen WHERE chosen.asset_id=a.id AND chosen.logical_path=l.path)
              )
            UNION ALL
            SELECT {remote_path} AS path,
                catalog_basename(COALESCE(x.logical_path,a.path)) AS name,
                catalog_path_key(catalog_basename(COALESCE(x.logical_path,a.path))) AS name_key,
                a.size,a.mtime_ns,a.mime,a.id AS asset_id,a.source_id AS storage_id,
                a.path AS remote_path,a.state,a.description,a.tags,a.category,a.metadata_revision,
                CASE WHEN c.asset_id IS NOT NULL AND c.size=a.size
                    AND (a.state='pending' OR (c.etag=a.etag AND c.mtime=a.mtime)) THEN 'complete' WHEN EXISTS (
                        SELECT 1 FROM manifest.ranges r WHERE r.asset_id=a.id
                            AND r.object_size=a.size AND r.etag=a.etag AND r.mtime=a.mtime
                    ) THEN 'partial' ELSE 'none' END AS cache_state
            FROM manifest.assets a LEFT JOIN alias_choice x ON x.asset_id=a.id
                LEFT JOIN manifest.cache c ON c.asset_id=a.id
            WHERE a.source_id!='local' AND attachment_scan_scope(a.source_id,a.path)=1 AND attachment_allowed(a.path)=1 AND attachment_allowed(COALESCE(x.logical_path,a.path))=1 AND a.state NOT IN ('missing','excluded') AND (a.state!='migration_pending' OR NOT EXISTS (
                SELECT 1 FROM manifest.aliases pending JOIN main.assets l
                    ON l.path=pending.path AND attachment_allowed(l.path)=1 AND catalog_local_exists(l.path)
                WHERE pending.asset_id=a.id
            ))
        ) '''

    @staticmethod
    def _settings_stamp(files, settings):
        return [files.config.data.get('revision'), files.config.data.get('attachment_folder', '_attachments'), settings]

    @staticmethod
    def _scope(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:32]

    @staticmethod
    def _decode(cursor, scope, sort):
        try:
            if not cursor.startswith(_CURSOR_PREFIX):
                raise ValueError()
            encoded = cursor[len(_CURSOR_PREFIX):]
            value = json.loads(base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True))
            if (not isinstance(value, list) or len(value) != 5 or value[0] != scope or
                    any(not isinstance(v, str) for v in value[2:]) or
                    type(value[1]) is not (str if sort in {'path', 'name'} else int)):
                raise ValueError()
            return value[1:]
        except (ValueError, TypeError, UnicodeError):
            raise ConflictError(_STALE) from None

    @staticmethod
    def _encode(scope, row, field):
        value = [scope, row[field], row['path'], row['storage_id'], row['asset_id']]
        return _CURSOR_PREFIX + base64.urlsafe_b64encode(json.dumps(value, ensure_ascii=False).encode()).decode().rstrip('=')

    @staticmethod
    def _public(row, sources):
        value = {key: row[key] for key in ('path', 'name', 'size', 'mime', 'asset_id', 'storage_id',
                 'remote_path', 'state', 'description', 'category', 'metadata_revision', 'cache_state')}
        local = value['storage_id'] == 'local'
        source = sources.get(value['storage_id'], {})
        value.update(mtime=row['mtime_ns'] / 1e9, tags=json.loads(row['tags']),
                     source_id=value['storage_id'], source='local' if local else 'remote',
                     source_name='Local' if local else source.get('name', value['storage_id']),
                     source_enabled=local or bool(source) and source.get('enabled', True),
                     capabilities={'rename': local, 'move': local, 'trash': local})
        for key in ('cover_id','attachment_uid'):
            if key in row.keys(): value[key]=row[key]
        return value

    @staticmethod
    def _as_local_items(result):
        """Local-index rows use the same public fields as the unified catalog."""
        for item in result['items']:
            item.update(asset_id='', storage_id='local', remote_path='', state='ready', description='',
                        category='', metadata_revision='', cache_state='complete', tags=[],
                        source_id='local', source='local', source_name='Local', source_enabled=True,
                        capabilities={'rename': True, 'move': True, 'trash': True})
        return result

    def _blank_page(self, files):
        summary = {'files': 0, 'bytes': 0, 'kinds': {},
                   'by_source': {'local': {'files': 0, 'bytes': 0}, 'remote': {'files': 0, 'bytes': 0}}}
        storages = []
        if self._remote is not None:
            try:
                storages = self._storage_options(self._remote._settings(str(files.config.root)))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                storages = []
        return {'items': [], 'next_cursor': None, 'cursor': None, 'total': 0, 'summary': summary, 'storages': storages}

    def _cache_failed(self, local, files, error, *, query, after, limit, kind, sort, order, cursor, source, storage_id,
                      tags, category, group_id):
        """A locked or missing server catalog must not hide local files or raise."""
        cache_only = source == 'remote' or storage_id not in {'', 'local'}
        if cursor.startswith(_CURSOR_PREFIX):
            raise ConflictError(_STALE)
        if cache_only:
            result = self._blank_page(files)
        else:
            result = self._local_listing(local, files, query=query, after=after, limit=limit, kind=kind,
                sort=sort, order=order, cursor=cursor, tags=tags, category=category, group_id=group_id)
        result.setdefault('warning', 'cache_unavailable')
        if error is not None:
            logging.getLogger(__name__).warning('Saved attachment catalog unavailable: %s', type(error).__name__)
        return result

    @staticmethod
    def _local_group_clause(group, device=''):
        """Filter the local filename index without opening the server catalog.

        Returns None when membership depends on server metadata (tags, categories
        or explicit remote identities). Callers then show an empty local page
        instead of every local file or a failed request.
        """
        if not group:
            return '1=1', []
        rules = {key: value for key, value in (group.get('rules') or {}).items() if value}
        if set(rules) - {'directories', 'sources', 'formats'}:
            return None
        parts, args = [], []
        if 'sources' in rules and 'local' not in rules['sources']:
            parts.append('0=1')
        if 'directories' in rules:
            dir_parts = []
            for raw in rules['directories']:
                if not isinstance(raw, str) or not raw.strip():
                    continue
                directory = raw.strip().strip('/')
                dir_parts.append("(path=? OR path LIKE ? ESCAPE '\\')")
                args.extend([directory, directory.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '/%'])
            if not dir_parts:
                return '0=1', []
            parts.append('(' + ' OR '.join(dir_parts) + ')')
        if 'formats' in rules:
            fmt_parts = []
            for raw in rules['formats']:
                if not isinstance(raw, str) or not raw.strip():
                    continue
                extension = raw.strip().lower().lstrip('.')
                fmt_parts.append("lower(name) LIKE ? ESCAPE '\\'")
                args.append('%.' + extension.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_'))
            if not fmt_parts:
                return '0=1', []
            parts.append('(' + ' OR '.join(fmt_parts) + ')')
        clause = (' AND '.join(parts) or '1=1') if rules else '0=1'
        for field, operator in (('included', 'OR'), ('excluded', 'AND NOT')):
            paths = [member['path'] for member in group.get(field) or []
                     if device and member.get('scope') == 'local:' + device and member.get('path')]
            if paths:
                clause = '(' + clause + ') ' + operator + ' path IN (' + ','.join('?' * len(paths)) + ')'
                args.extend(paths)
        return clause, args

    def _local_listing(self, local, files, *, query, after, limit, kind, sort, order, cursor, tags, category, group_id):
        if cursor.startswith(_CURSOR_PREFIX):
            raise ConflictError(_STALE)
        if not self._local_ready(files):
            result = self._blank_page(files)
            result['warning'] = 'local_catalog_missing'
            return result
        predicate, predicate_args = '', []
        presentation = self.__dict__.get('presentation')
        clause = None if tags or category else ('1=1', [])
        if clause and presentation and group_id:
            _, device, group = presentation.resolve_group(str(files.config.root), group_id)
            clause = self._local_group_clause(group, device)
        if clause is None:
            result = self._blank_page(files)
            result['warning'] = 'local_group_uncached'
            return result
        if clause[0] != '1=1':
            predicate, predicate_args = clause
        result = local.listing(query, after, limit, kind=kind, sort=sort, order=order, cursor=cursor,
                               predicate=predicate, predicate_args=predicate_args)
        self._as_local_items(result)
        result['summary']['by_source'] = {
            'local': {'files': result['summary']['files'], 'bytes': result['summary']['bytes']},
            'remote': {'files': 0, 'bytes': 0},
        }
        result['result_summary']['by_source'] = {
            'local': {'files': result['result_summary']['files'], 'bytes': result['result_summary']['bytes']},
            'remote': {'files': 0, 'bytes': 0},
        }
        result['storages'] = self._blank_page(files)['storages']
        return result

    def listing(self, query='', after='', limit=100, *, kind='all', sort='path', order='asc', cursor='',
                source='all', storage_id='', tags=None, category='', group_id=''):
        tags = [] if tags is None else tags
        if (any(not isinstance(v, str) for v in (query, after, cursor, source, storage_id, category)) or
                len(query) > 500 or len(after) > 8192 or len(cursor) > 8192 or len(category) > 200 or
                not isinstance(tags, list) or len(tags) > 100 or
                any(not isinstance(t, str) or len(t) > 100 for t in tags)):
            raise ValueError('Invalid attachment query')
        if storage_id and storage_id != 'local':
            try:
                storage_id = uuid.UUID(storage_id).hex
            except ValueError:
                raise ValueError('Invalid attachment storage ID') from None
        if source not in {'all', 'local', 'remote'} or kind not in _KINDS or sort not in _SORTS or order not in {'asc', 'desc'}:
            raise ValueError('Invalid attachment filter or sort')
        if after.startswith(_CURSOR_PREFIX) and not cursor:
            cursor, after = after, ''
        if after and (cursor or sort != 'path' or order != 'asc'):
            raise ValueError('Use a cursor for sorted attachments')
        limit = max(1, min(int(limit), 500))
        local = self._local_index
        remote_only = source == 'remote' or storage_id not in {'', 'local'}
        with nullcontext() if remote_only else local.lock:
            files = local._snapshot()
            root = files.config.root
            local_only = source == 'local' or storage_id == 'local'
            remote_only = source == 'remote' or storage_id not in {'', 'local'}
            options = dict(query=query, after=after, limit=limit, kind=kind, sort=sort, order=order,
                           cursor=cursor, tags=tags, category=category, group_id=group_id)
            if local_only:
                if remote_only:
                    return self._blank_page(files)
                return self._local_listing(local, files, **options)
            # A local fallback cursor stays in its own snapshot until the caller
            # refreshes from the first page. It cannot enter the merged catalog.
            if not remote_only and source == 'all' and cursor and not cursor.startswith(_CURSOR_PREFIX):
                return self._cache_failed(local, files, None, source=source, storage_id=storage_id, **options)
            path = self._manifest(files)
            if path is None:
                if remote_only:
                    return self._cache_failed(local, files, None, source=source, storage_id=storage_id, **options)
                result = self._local_listing(local, files, **options)
                if result['storages']:
                    result.setdefault('warning', 'cache_unavailable')
                return result
            presentation = self.__dict__.get('presentation')
            try:
                local._check_root(root)
                settings = self._remote._settings(str(root))
                stamp = self._settings_stamp(files, settings)
                prefix = files.config.data.get('attachment_folder', '_attachments') + '/_remote/'
                return self._finish_cached_listing(
                    local, files, root, path, presentation, settings, stamp, prefix, query, after, limit,
                    kind, sort, order, cursor, source, storage_id, tags, category, group_id)
            except (sqlite3.Error, json.JSONDecodeError) as exc:
                return self._cache_failed(local, files, exc, source=source, storage_id=storage_id, **options)

    def _finish_cached_listing(self, local, files, root, path, presentation, settings, stamp, prefix,
                               query, after, limit, kind, sort, order, cursor, source, storage_id, tags, category, group_id):
        remote_only = source == 'remote' or storage_id not in {'', 'local'}
        with closing(self._catalog_connection(local, files, include_local=not remote_only)) as db:
                self._attach(db, path, files)
                register_scan_scope(db, settings['sources'])
                # Directory/source/format groups (e.g. Unity Asset) filter in SQL and
                # enrich only the returned page — restart must not reload the whole
                # asset library just to show membership from the local manifest.
                light_group = False
                membership = None
                if presentation and group_id:
                    from vault_rag.attachment_presentation import membership_sql
                    _, _, group = presentation.resolve_group(str(root), group_id)
                    primary = ''
                    try:
                        primary = str(presentation.library.settings(str(root)).get('storage_id') or '')
                    except (FileNotFoundError, ValueError, ConflictError, AttributeError, TypeError, sqlite3.Error):
                        primary = ''
                    membership = membership_sql(group, primary_storage_id=primary)
                    light_group = bool(membership) and not query and not tags and not category
                # The default grid reads the local index and the saved server
                # catalog only. Loading the asset library here can lock or time
                # out and used to fail the whole list, including local files.
                # Tag/include groups still enrich; directory groups stay light.
                use_enriched = False
                if presentation and group_id and not light_group:
                    view_stamp = presentation.prepare(db, str(root), group_id, enrich=True)
                    use_enriched = True
                elif presentation and group_id:
                    view_stamp = presentation.prepare(db, str(root), group_id, enrich=False)
                else:
                    view_stamp = ''
                db.execute('BEGIN')
                scanned = db.execute('SELECT scanned_at FROM main.state WHERE root=?', (str(root),)).fetchone()
                generation = db.execute('SELECT generation FROM manifest.catalog_state WHERE id=1').fetchone()[0]
                # Cursor scope follows the local index generation and the saved
                # catalog generation. It does not walk the vault to see which
                # files still exist on disk.
                local_generation = 0 if remote_only else local.generation
                presence = f'{local_generation}:{generation}'
                scope = self._scope([str(root), stamp, scanned[0] if scanned else None, local_generation,
                                     generation, presence, query, kind, sort, order, source, storage_id,
                                     sorted(set(tags)), category, group_id, view_stamp])
                origins, origin_args = ['1=1'], [prefix]
                if source == 'local':
                    origins.append("storage_id='local'")
                elif source == 'remote':
                    origins.append("storage_id!='local'")
                if storage_id:
                    origins.append('storage_id=?')
                    origin_args.append(storage_id)
                cte = self._cte(remote_only=remote_only)
                if use_enriched:
                    cte = presentation.cte(cte)
                # Materialize group membership once. Unity Asset groups previously
                # re-ran the Python matcher for COUNT, facets, and the page query.
                if presentation and group_id:
                    db.execute('DROP TABLE IF EXISTS attachment_group_hit')
                    db.execute('CREATE TEMP TABLE attachment_group_hit(storage_id TEXT NOT NULL, path TEXT NOT NULL, '
                               'PRIMARY KEY(storage_id, path)) WITHOUT ROWID')
                    # CTE binds the logical remote prefix once (`? || source_id || '/' || path`).
                    if membership:
                        predicate_sql, membership_args = membership
                        db.execute(cte + 'INSERT OR IGNORE INTO attachment_group_hit(storage_id, path) '
                                   'SELECT storage_id, path FROM catalog WHERE ' + predicate_sql,
                                   [prefix, *membership_args])
                    else:
                        db.execute(cte + 'INSERT OR IGNORE INTO attachment_group_hit(storage_id, path) '
                                   'SELECT storage_id, path FROM catalog WHERE '
                                   'attachment_group_matches(storage_id,path,remote_path,name,tags,category,asset_id)=1',
                                   [prefix])
                    origins.append('EXISTS (SELECT 1 FROM attachment_group_hit g '
                                   'WHERE g.storage_id=catalog.storage_id AND g.path=catalog.path)')
                where, args = list(origins), list(origin_args)
                if query:
                    pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
                    where.append("(path LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\' OR category LIKE ? ESCAPE '\\')")
                    args.extend([pattern] * 5)
                if kind != 'all':
                    where.append('(' + _KIND_SQL + ')=?')
                    args.append(kind)
                if category:
                    where.append('category=?')
                    args.append(category)
                for tag in sorted(set(tags)):
                    where.append('EXISTS (SELECT 1 FROM json_each(catalog.tags) WHERE value=?)')
                    args.append(tag)
                predicate = ' AND '.join(where)
                total = db.execute(cte + 'SELECT COUNT(*) FROM catalog WHERE ' + predicate, args).fetchone()[0]
                # Keep type facets independent of the selected kind/search,
                # while scoping all counts and bytes to the selected origin.
                stats = db.execute(cte + "SELECT CASE WHEN storage_id='local' THEN 'local' ELSE 'remote' END," +
                                   _KIND_SQL + ',COUNT(*),COALESCE(SUM(size),0) FROM catalog WHERE ' +
                                   ' AND '.join(origins) + ' GROUP BY 1,2', origin_args).fetchall()
                summary = {'files': sum(r[2] for r in stats), 'bytes': sum(r[3] for r in stats), 'kinds': {},
                           'by_source': {'local': {'files': 0, 'bytes': 0}, 'remote': {'files': 0, 'bytes': 0}}}
                for origin, file_kind, count, size in stats:
                    summary['kinds'][file_kind] = summary['kinds'].get(file_kind, 0) + count
                    summary['by_source'][origin]['files'] += count
                    summary['by_source'][origin]['bytes'] += size
                result_summary = None
                if presentation:
                    if light_group and kind == 'all':
                        result_summary = summary
                    else:
                        matched = db.execute(cte + "SELECT CASE WHEN storage_id='local' THEN 'local' ELSE 'remote' END," +
                            _KIND_SQL + ',COUNT(*),COALESCE(SUM(size),0) FROM catalog WHERE ' + predicate + ' GROUP BY 1,2', args).fetchall()
                        result_summary = {'files': sum(r[2] for r in matched), 'bytes': sum(r[3] for r in matched), 'kinds': {},
                            'by_source': {'local': {'files': 0, 'bytes': 0}, 'remote': {'files': 0, 'bytes': 0}}}
                        for origin, file_kind, count, size in matched:
                            result_summary['kinds'][file_kind] = result_summary['kinds'].get(file_kind, 0) + count
                            result_summary['by_source'][origin]['files'] += count
                            result_summary['by_source'][origin]['bytes'] += size
                field = _SORTS[sort]
                direction, sign = ('ASC', '>') if order == 'asc' else ('DESC', '<')
                if cursor:
                    token = self._decode(cursor, scope, sort)
                    # The final source/asset keys disambiguate matching paths
                    # without dropping or repeating rows across page edges.
                    predicate += f' AND ({field},path,storage_id,asset_id) {sign} (?,?,?,?)'
                    args.extend(token)
                elif after:
                    predicate += ' AND path>?'
                    args.append(after)
                rows = db.execute(cte + 'SELECT * FROM catalog WHERE ' + predicate +
                    f' ORDER BY {field} {direction},path {direction},storage_id {direction},asset_id {direction} LIMIT ?',
                    (*args, limit + 1)).fetchall()
        sources = {s['id']: s for s in settings['sources']}
        items = []
        for row in rows[:limit]:
            try:
                # Apply the same rooted/hidden/link boundary to logical
                # remote names; this does not read remote content.
                files.config.path_for(row['path'])
            except (ValueError, OSError):
                continue
            # Light directory groups stay on the local manifest for the grid;
            # product covers/tags are filled when the detail pane opens.
            items.append(self._public(row, sources))
        local._check_root(root)
        # Don't block the page on a scan that is holding the writer lock.
        # A missed stamp check only means this page might be one revision old.
        if self._remote.lock.acquire(timeout=0.2):
            try:
                if stamp != self._settings_stamp(local._snapshot(), self._remote._settings(str(root))):
                    raise ConflictError(_STALE)
            finally:
                self._remote.lock.release()
        next_cursor = self._encode(scope, rows[limit - 1], field) if len(rows) > limit else None
        return dict(items=items, next_cursor=next_cursor, cursor=next_cursor, total=total,
                    summary=summary, **({'result_summary': result_summary} if presentation else {}),
                    storages=self._storage_options(settings),
                    last_scanned_at=scanned[0] if scanned else None)

    @staticmethod
    def _storage_options(settings):
        # Labels and stable IDs support source selection without exposing URLs
        # or credentials, including to MCP clients.
        return [{'storage_id': item['id'], 'name': item.get('name', ''),
                 'enabled': item.get('enabled', True)} for item in settings['sources']]

    def resolve(self, target, source=''):
        if not isinstance(target, str) or len(target) > 4096 or re.match(r'^[a-zA-Z]+:', target):
            return []
        files = self._local_index._snapshot()
        self._local_index._check_root(files.config.root)
        # Exact local paths retain precedence, even while another computer's
        # migration/deletion is still arriving through folder sync.
        for candidate in (str(PurePosixPath(source).parent / target), target):
            try:
                rel = relative(posixpath.normpath(candidate))
                if files.config.path_for(rel).is_file():
                    self._local_index._check_root(files.config.root)
                    return [rel]
            except (ValueError, OSError):
                continue
        remote = self._resolve_remote(target, source, exact_only=True) if self._remote else []
        if remote:
            return remote
        if ('/' in target or '\\' in target) and PurePosixPath(target).suffix.lower() not in {'', '.md', '.markdown', '.txt', '.base'}:
            return []
        local = self._local_index.resolve(target, source)
        remote = self._resolve_remote(target, source) if self._remote else []
        # Changing the upload destination must never choose a different
        # same-name attachment. Exact paths above are the disambiguation.
        return [] if local and remote else local or remote

    def _resolve_remote(self, target, source='', *, exact_only=False):
        if not isinstance(target, str) or len(target) > 4096 or re.match(r'^[a-zA-Z]+:', target):
            return []
        local = self._local_index
        with local.lock:
            files = local._snapshot()
            path = self._manifest(files)
            if path is None:
                return []
            root = files.config.root
            candidates = []
            for candidate in (str(PurePosixPath(source).parent / target), target):
                try:
                    normalized = relative(posixpath.normpath(candidate))
                    if normalized and normalized not in candidates:
                        candidates.append(normalized)
                except ValueError:
                    continue
            if not candidates:
                return []
            with self._remote.lock, closing(self._catalog_connection(local, files)) as db:
                self._attach(db, path, files)
                prefix = files.config.data.get('attachment_folder', '_attachments') + '/_remote/'
                for candidate in candidates:
                    rows = db.execute('SELECT a.id,x.path FROM manifest.aliases x JOIN manifest.assets a ON a.id=x.asset_id '
                                      "WHERE a.source_id!='local' AND x.path=? LIMIT 2", (candidate,)).fetchall()
                    if not rows:
                        rows = db.execute('SELECT a.id,COALESCE((SELECT MIN(path) FROM manifest.aliases WHERE asset_id=a.id AND NOT catalog_local_exists(path)),'
                            '? || a.source_id || \'/\' || a.path) AS path FROM manifest.assets a '
                            "WHERE a.source_id!='local' AND (a.path=? OR ? || a.source_id || '/' || a.path=?) LIMIT 2",
                            (prefix, candidate, prefix, candidate)).fetchall()
                    if rows:
                        return self._resolved(files, root, rows)
                # A basename is safe only when exactly one remote asset matches;
                # multiple aliases for that same asset do not create ambiguity.
                if exact_only or '/' in target or '\\' in target:
                    return []
                rows = db.execute('SELECT a.id,COALESCE((SELECT MIN(path) FROM manifest.aliases WHERE asset_id=a.id AND NOT catalog_local_exists(path)),'
                    '? || a.source_id || \'/\' || a.path) AS path FROM manifest.assets a '
                    "WHERE a.source_id!='local' AND (catalog_path_key(a.name)=? OR EXISTS ("
                    'SELECT 1 FROM manifest.aliases x WHERE x.asset_id=a.id AND catalog_path_key(catalog_basename(x.path))=?)) LIMIT 2',
                    (prefix, path_key(PurePosixPath(target).name), path_key(PurePosixPath(target).name))).fetchall()
                return self._resolved(files, root, rows)

    def _resolved(self, files, root, rows):
        self._local_index._check_root(root)
        if len(rows) != 1:
            return []
        try:
            files.config.path_for(rows[0]['path'])
        except (ValueError, OSError):
            return []
        return [rows[0]['path']]
