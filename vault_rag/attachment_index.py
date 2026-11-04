"""Rebuildable filename index. Original files remain the source of truth.

Discovery only stats files: no attachment decoding, hashing or note parsing.
The same namespace supports cold basename links without building RAG metadata.
"""
from __future__ import annotations

import copy
import base64
import hashlib
import json
import mimetypes
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import PurePosixPath
from urllib.parse import quote

from vault_rag.attachment_policy import extensions_for, register_policy
from vault_rag.local_state import ConflictError, relative
from vault_rag.platform_support import private_file_mode, path_key


class AttachmentIndex:
    def __init__(self, files):
        self.files = files
        self.lock = threading.RLock()
        self.ready_root = None
        self.generation = time.time_ns()

    def _snapshot(self):
        with self.files.config.lock:
            config = copy.copy(self.files.config)
            config.data = dict(config.data)
        files = copy.copy(self.files)
        files.config = config
        return files

    def _check_root(self, root):
        if (self.files.config.data.get('root') != str(root) or
                str(self.files.config.root) != str(root)):
            raise ConflictError('关联目录已变化，请重新打开目录')

    def _connect(self, files):
        # Validate the DB and SQLite's possible sidecars, including existing links.
        path = files.state_path('attachments.sqlite')
        for suffix in ('-journal', '-wal', '-shm'):
            files.state_path('attachments.sqlite' + suffix)
        path.parent.mkdir(exist_ok=True)
        db = sqlite3.connect(path, timeout=10)
        try:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > 1:
                raise ValueError('Attachment index was created by a newer version')
            if version == 0:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if tables:
                    columns = [r[1] for r in db.execute('PRAGMA table_info(assets)')]
                    if tables - {'assets', 'state'} or columns != ['path','path_key','name','name_key','size','mtime_ns','mime','attachment']:
                        raise ValueError('Unsupported legacy attachment index; database preserved')
                    if 'state' in tables and [r[1] for r in db.execute('PRAGMA table_info(state)')] != ['root','scanned_at']:
                        raise ValueError('Unsupported legacy attachment state; database preserved')
                    backup = files.state_path('attachments-before-v1-' + str(time.time_ns()) + '.sqlite')
                    with closing(sqlite3.connect(backup)) as previous:
                        db.backup(previous)
                    private_file_mode(backup)
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS assets('
                           'path TEXT PRIMARY KEY, path_key TEXT NOT NULL, name TEXT NOT NULL, '
                           'name_key TEXT NOT NULL, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, '
                           'mime TEXT NOT NULL, attachment INTEGER NOT NULL)')
                db.execute('CREATE INDEX IF NOT EXISTS assets_path_key ON assets(path_key)')
                db.execute('CREATE INDEX IF NOT EXISTS assets_name_key ON assets(name_key)')
                db.execute('CREATE INDEX IF NOT EXISTS assets_listing ON assets(attachment,path)')
                db.execute('CREATE TABLE IF NOT EXISTS state(root TEXT PRIMARY KEY, scanned_at REAL NOT NULL)')
                db.execute('PRAGMA user_version=1')
                db.commit()
            private_file_mode(path)
            return db
        except Exception:
            db.close()
            raise

    @staticmethod
    def _row(root, path, stat):
        rel = path.relative_to(root).as_posix()
        return (rel, path_key(rel), path.name, path_key(path.name), stat.st_size,
                stat.st_mtime_ns, mimetypes.guess_type(path.name)[0] or 'application/octet-stream',
                int(path.suffix.lower() not in ('.md', '.txt', '.base')))

    @staticmethod
    def _upsert(db, row):
        db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET '
                   'path_key=excluded.path_key,name=excluded.name,name_key=excluded.name_key,'
                   'size=excluded.size,mtime_ns=excluded.mtime_ns,mime=excluded.mime,'
                   'attachment=excluded.attachment WHERE assets.mtime_ns!=excluded.mtime_ns '
                   'OR assets.size!=excluded.size', row)

    def refresh(self, cancel=None, progress=None):
        with self.lock:
            files = self._snapshot()
            root = files.config.root
            with closing(self._connect(files)) as db, db:
                db.execute('CREATE TEMP TABLE seen(path TEXT PRIMARY KEY)')
                stats = {}
                done = 0
                for path in files.walk(stats=stats, strict=True):
                    if cancel is not None and cancel.is_set():
                        raise InterruptedError("Attachment index build cancelled")
                    done += 1
                    if progress is not None and done % 100 == 0:
                        progress(done)
                    stat = stats.pop(path)
                    self._upsert(db, self._row(root, path, stat))
                    db.execute('INSERT OR IGNORE INTO seen VALUES(?)', (path.relative_to(root).as_posix(),))
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Attachment index build cancelled")
                if progress is not None:
                    progress(done)
                self._check_root(root)
                db.execute('DELETE FROM assets WHERE path NOT IN (SELECT path FROM seen)')
                db.execute('DELETE FROM state')
                db.execute('INSERT INTO state VALUES(?,?)', (str(root), time.time()))
            self.ready_root = str(root)
            return {'ready': True}

    def _ensure(self):
        root = str(self.files.config.root)
        if self.ready_root == root:
            return
        files = self._snapshot()
        with closing(self._connect(files)) as db:
            ready = db.execute('SELECT 1 FROM state WHERE root=?', (root,)).fetchone()
        self._check_root(root)
        if ready:
            self.ready_root = root
        else:
            self.refresh()

    def apply(self, paths):
        """Watcher batches update only affected files/subtrees after first use."""
        with self.lock:
            files = self._snapshot()
            root = files.config.root
            if self.ready_root != str(root):
                if not files.state_path('attachments.sqlite').is_file():
                    return
                with closing(self._connect(files)) as db:
                    if not db.execute('SELECT 1 FROM state WHERE root=?', (str(root),)).fetchone():
                        return
                self.ready_root = str(root)
            with closing(self._connect(files)) as db, db:
                for value in sorted(set(paths)):
                    rel = relative(value)
                    # Remove cached descendants even when a path became a link.
                    if not rel:
                        db.execute('DELETE FROM assets')
                    else:
                        db.execute('DELETE FROM assets WHERE path=?', (rel,))
                        # A BINARY prefix range uses the primary-key index even
                        # for large subtrees; no table-wide substr/LIKE scan.
                        db.execute('DELETE FROM assets WHERE path>=? AND path<?',
                                   (rel + '/', rel + '0'))
                    try:
                        path = files.config.path_for(rel)
                        if path.is_file():
                            self._upsert(db, self._row(root, path, path.stat()))
                        elif path.is_dir():
                            stats = {}
                            for child in files.walk(rel, stats=stats, strict=True):
                                self._upsert(db, self._row(root, child, stats.pop(child)))
                    except (FileNotFoundError, ValueError):
                        continue
                self._check_root(root)
                # Incremental changes invalidate sorted cursors just like a full scan.
                self.generation += 1

    def resolve(self, target, source=''):
        """Indexed candidates; Files.resolve preserves path precedence/ambiguity."""
        with self.lock:
            self._ensure()
            files = self._snapshot()
            root = files.config.root
            base = PurePosixPath(target).name
            # Exact paths can contain ../ in a note-relative link. The existing
            # resolver normalizes them and rejects escape attempts below.
            import posixpath
            keys = {path_key(posixpath.normpath(value)) for candidate in
                    (str(PurePosixPath(source).parent / target), target)
                    for value in (candidate, candidate + '.md')}
            with closing(self._connect(files)) as db:
                rows = db.execute('SELECT path FROM assets WHERE name_key IN (?,?) OR path_key IN (' +
                                  ','.join('?' for _ in keys) + ')',
                                  (path_key(base), path_key(base + '.md'), *keys)).fetchall()
            paths = set()
            for (rel,) in rows:
                try:
                    if files.config.path_for(rel).is_file():
                        paths.add(rel)
                except (ValueError, OSError):
                    continue
            self._check_root(root)
            # Files.resolve already decoded once before entering this index.
            # Re-encode literal %, # and | to avoid a second interpretation.
            return files.resolve(quote(target, safe='/'), source, paths=paths)

    def listing(self, query='', after='', limit=100, *, kind='all', sort='path', order='asc', cursor=''):
        limit = max(1, min(int(limit), 500))
        if len(query)>500 or len(after)>4096 or len(cursor)>8192:
            raise ValueError('Attachment query is too long')
        fields={'path':'path','name':'name_key','modified':'mtime_ns','size':'size'}
        if kind not in {'all','image','pdf','audio','video','other'} or sort not in fields or order not in {'asc','desc'}:
            raise ValueError('Invalid attachment filter or sort')
        if after and (cursor or sort!='path' or order!='asc'):
            raise ValueError('Use a cursor for sorted attachments')
        category="CASE WHEN mime LIKE 'image/%' THEN 'image' WHEN mime='application/pdf' THEN 'pdf' WHEN mime LIKE 'audio/%' THEN 'audio' WHEN mime LIKE 'video/%' THEN 'video' ELSE 'other' END"
        with self.lock:
            self._ensure();files=self._snapshot();root=files.config.root
            pattern='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            with closing(self._connect(files)) as db:
                extensions=extensions_for(files);register_policy(db,extensions)
                scanned=db.execute('SELECT scanned_at FROM state WHERE root=?',(str(root),)).fetchone()
                scope=hashlib.sha256(json.dumps([str(root),query,kind,sort,order,scanned,self.generation,extensions],ensure_ascii=False).encode()).hexdigest()[:24]
                where="attachment_allowed(path)=1 AND path LIKE ? ESCAPE '\\'";args=[pattern]
                if kind!='all':where+=' AND ('+category+')=?';args.append(kind)
                total=db.execute('SELECT count(*) FROM assets WHERE '+where,args).fetchone()[0]
                stats=db.execute('SELECT '+category+',count(*),coalesce(sum(size),0) FROM assets WHERE attachment_allowed(path)=1 GROUP BY 1').fetchall()
                summary={'files':sum(r[1] for r in stats),'bytes':sum(r[2] for r in stats),'kinds':{r[0]:r[1] for r in stats}}
                field=fields[sort];direction='ASC' if order=='asc' else 'DESC';sign='>' if order=='asc' else '<'
                if cursor:
                    try:
                        token=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)))
                        if not isinstance(token,list) or len(token)!=3 or token[0]!=scope or not isinstance(token[2],str) or not isinstance(token[1],str if sort in {'path','name'} else int):raise ValueError()
                        where+=f' AND ({field} {sign} ? OR ({field}=? AND path {sign} ?))';args.extend([token[1],token[1],token[2]])
                    except (ValueError,TypeError,KeyError):raise ConflictError('Attachment results changed; start from the first page')
                elif after:where+=' AND path>?';args.append(after)
                rows=db.execute('SELECT path,name,size,mtime_ns,mime,'+field+' FROM assets WHERE '+where+f' ORDER BY {field} {direction},path {direction} LIMIT ?',(*args,limit+1)).fetchall()
            items=[]
            for row in rows[:limit]:
                try:files.config.path_for(row[0])
                except (ValueError,OSError):continue
                items.append(dict(path=row[0],name=PurePosixPath(row[0]).name,size=row[2],mtime=row[3]/1e9,mime=row[4]))
            self._check_root(root)
            next_cursor=None;next_after=None
            if len(rows)>limit:
                last=rows[limit-1];next_after=last[0]
                next_cursor=base64.urlsafe_b64encode(json.dumps([scope,last[5],last[0]],ensure_ascii=False).encode()).decode().rstrip('=')
            return {'items':items,'next_cursor':next_after if sort=='path' and order=='asc' and not cursor else next_cursor,
                    'cursor':next_cursor,'total':total,'summary':summary,'last_scanned_at':scanned[0] if scanned else None}
