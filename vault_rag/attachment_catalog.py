"""Paged attachment metadata across the local filename index and remote manifest.

Only metadata is joined here. Listing and resolving a remote attachment never
downloads it or adds it to the note/retrieval catalogs.
"""
from __future__ import annotations

import base64
import hashlib
import json
import posixpath
import re
import sqlite3
import uuid
from contextlib import closing
from pathlib import PurePosixPath

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
        path = files.state_path('remote-attachments', 'manifest.sqlite')
        if not path.is_file():
            return None
        return self._remote.manifest_path(str(files.config.root))

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
    def _catalog_connection(cls, local, files):
        if not cls._local_ready(files):
            # A server catalog remains browsable before local setup, including
            # when an incompatible local index is preserved for a newer app.
            db = sqlite3.connect(':memory:', uri=True)
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
        return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)

    @staticmethod
    def _attach(db, path, files):
        for suffix in ('-journal', '-wal', '-shm'):
            if path.with_name(path.name + suffix).is_symlink():
                raise ValueError('Attachment manifest sidecar cannot be a link')
        db.execute('ATTACH DATABASE ? AS manifest', (path.as_uri() + '?mode=ro',))
        db.row_factory = sqlite3.Row
        db.create_function('catalog_path_key', 1, path_key, deterministic=True)
        db.create_function('catalog_basename', 1, lambda p: PurePosixPath(p).name, deterministic=True)
        existing = {}
        # Logical remote aliases normally have no local directory. Validate this
        # shared prefix once per read snapshot instead of walking its thousands
        # of nonexistent descendants through path_for. Positive/local paths keep
        # the complete rooted, hidden-file and symlink checks below.
        virtual_prefix = files.config.data.get('attachment_folder','_attachments') + '/_remote/'
        try:virtual_absent = not files.config.path_for(virtual_prefix.rstrip('/')).is_dir()
        except (ValueError,OSError):virtual_absent = True
        def exists(path):
            if path in existing:
                return existing[path]
            if virtual_absent and path.startswith(virtual_prefix):
                existing[path] = False
                return False
            try:
                existing[path] = files.config.path_for(path).is_file()
            except (ValueError, OSError):
                existing[path] = False
            return existing[path]
        db.create_function('catalog_local_exists', 1, exists)

    @staticmethod
    def _cte():
        # Aliases are authoritative once a verified migration has released its
        # local source. A pending migration keeps the existing local entry.
        return '''WITH alias_choice AS (
            SELECT asset_id,MIN(path) AS logical_path FROM manifest.aliases
            WHERE NOT catalog_local_exists(path) GROUP BY asset_id
        ), catalog AS (
            SELECT l.path,l.name,l.name_key,l.size,l.mtime_ns,l.mime,
                COALESCE(m.id,'') AS asset_id,'local' AS storage_id,
                '' AS remote_path,COALESCE(m.state,'ready') AS state,
                COALESCE(m.description,'') AS description,COALESCE(m.tags,'[]') AS tags,
                COALESCE(m.category,'') AS category,COALESCE(m.metadata_revision,'') AS metadata_revision,
                'complete' AS cache_state
            FROM main.assets l LEFT JOIN manifest.assets m
                ON m.source_id='local' AND m.path=l.path
            WHERE l.attachment=1 AND catalog_local_exists(l.path)
            UNION ALL
            SELECT COALESCE(x.logical_path,? || a.source_id || '/' || a.path) AS path,
                catalog_basename(COALESCE(x.logical_path,a.path)) AS name,
                catalog_path_key(catalog_basename(COALESCE(x.logical_path,a.path))) AS name_key,
                a.size,a.mtime_ns,a.mime,a.id AS asset_id,a.source_id AS storage_id,
                a.path AS remote_path,a.state,a.description,a.tags,a.category,a.metadata_revision,
                CASE WHEN c.asset_id IS NOT NULL AND c.size=a.size AND c.etag=a.etag
                    AND c.mtime=a.mtime THEN 'complete' WHEN EXISTS (
                        SELECT 1 FROM manifest.ranges r WHERE r.asset_id=a.id
                            AND r.object_size=a.size AND r.etag=a.etag AND r.mtime=a.mtime
                    ) THEN 'partial' ELSE 'none' END AS cache_state
            FROM manifest.assets a LEFT JOIN alias_choice x ON x.asset_id=a.id
                LEFT JOIN manifest.cache c ON c.asset_id=a.id
            WHERE a.source_id!='local' AND a.state NOT IN ('missing','excluded') AND (a.state!='migration_pending' OR NOT EXISTS (
                SELECT 1 FROM manifest.aliases pending JOIN main.assets l
                    ON l.path=pending.path AND l.attachment=1 AND catalog_local_exists(l.path)
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
        with local.lock:
            files = local._snapshot()
            root = files.config.root
            path = self._manifest(files)
            presentation = self.__dict__.get('presentation')
            if presentation and path is None:
                with self._remote._db(str(root)): pass
                path = self._manifest(files)
            if path is None:
                if cursor.startswith(_CURSOR_PREFIX):
                    raise ConflictError(_STALE)
                result = local.listing(query, after, limit, kind=kind, sort=sort, order=order, cursor=cursor)
                if source == 'remote' or storage_id not in {'', 'local'} or tags or category:
                    result.update(items=[], total=0, cursor=None, next_cursor=None)
                if source == 'remote' or storage_id not in {'', 'local'}:
                    result['summary'] = {'files': 0, 'bytes': 0, 'kinds': {}}
                result['summary']['by_source'] = {
                    'local': {'files': result['summary']['files'], 'bytes': result['summary']['bytes']},
                    'remote': {'files': 0, 'bytes': 0},
                }
                settings = self._remote._settings(str(root)) if self._remote else {'sources': []}
                result['storages'] = self._storage_options(settings)
                return result
            # One lock covers the read snapshot and source settings. The facade
            # never invokes network or content methods while holding it.
            with self._remote.lock:
                local._check_root(root)
                local._check_root(root)
                files = local._snapshot()
                settings = self._remote._settings(str(root))
                stamp = self._settings_stamp(files, settings)
                prefix = files.config.data.get('attachment_folder', '_attachments') + '/_remote/'
                with closing(self._catalog_connection(local, files)) as db:
                    self._attach(db, path, files)
                    view_stamp = presentation.prepare(db,str(root),group_id) if presentation else ''
                    db.execute('BEGIN')
                    scanned = db.execute('SELECT scanned_at FROM main.state WHERE root=?', (str(root),)).fetchone()
                    generation = db.execute('SELECT generation FROM manifest.catalog_state WHERE id=1').fetchone()[0]
                    presence = [row[0] for row in db.execute('SELECT path FROM main.assets WHERE attachment=1 AND catalog_local_exists(path) '
                        'UNION SELECT path FROM manifest.aliases WHERE catalog_local_exists(path) ORDER BY path')]
                    scope = self._scope([str(root), stamp, scanned[0] if scanned else None, local.generation,
                                         generation, presence, query, kind, sort, order, source, storage_id, sorted(set(tags)), category, group_id, view_stamp])
                    origins, origin_args = ['1=1'], [prefix]
                    if source == 'local':
                        origins.append("storage_id='local'")
                    elif source == 'remote':
                        origins.append("storage_id!='local'")
                    if storage_id:
                        origins.append('storage_id=?')
                        origin_args.append(storage_id)
                    if presentation and group_id:
                        origins.append('attachment_group_matches(storage_id,path,remote_path,name,tags,category,asset_id)=1')
                    where, args = list(origins), list(origin_args)
                    if query:
                        pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
                        where.append("(path LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\' OR category LIKE ? ESCAPE '\\')")
                        args.extend([pattern] * 4)
                    if kind != 'all':
                        where.append('(' + _KIND_SQL + ')=?')
                        args.append(kind)
                    if category:
                        where.append('category=?')
                        args.append(category)
                    for tag in sorted(set(tags)):
                        where.append('EXISTS (SELECT 1 FROM json_each(catalog.tags) WHERE value=?)')
                        args.append(tag)
                    cte = presentation.cte(self._cte()) if presentation else self._cte()
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
                        matched = db.execute(cte + "SELECT CASE WHEN storage_id='local' THEN 'local' ELSE 'remote' END," +
                            _KIND_SQL + ',COUNT(*),COALESCE(SUM(size),0) FROM catalog WHERE ' + predicate + ' GROUP BY 1,2',args).fetchall()
                        result_summary={'files':sum(r[2] for r in matched),'bytes':sum(r[3] for r in matched),'kinds':{},
                            'by_source':{'local':{'files':0,'bytes':0},'remote':{'files':0,'bytes':0}}}
                        for origin,file_kind,count,size in matched:
                            result_summary['kinds'][file_kind]=result_summary['kinds'].get(file_kind,0)+count
                            result_summary['by_source'][origin]['files']+=count
                            result_summary['by_source'][origin]['bytes']+=size
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
                    items.append(self._public(row, sources))
                local._check_root(root)
                if stamp != self._settings_stamp(local._snapshot(), self._remote._settings(str(root))):
                    raise ConflictError(_STALE)
                next_cursor = self._encode(scope, rows[limit - 1], field) if len(rows) > limit else None
                return dict(items=items, next_cursor=next_cursor, cursor=next_cursor, total=total,
                            summary=summary, **({'result_summary':result_summary} if presentation else {}), storages=self._storage_options(settings),
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
