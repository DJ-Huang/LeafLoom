"""Workspace note workflows shared by HTTP MCP and authenticated browser routes.

Retrieval remains in Knowledge; workspace access never changes RAG eligibility.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
from pathlib import Path
import re
import secrets
import time

from vault_rag.catalog import list_value, render_template
from vault_rag.local_state import ConflictError, digest, relative, under

NOTE_EXTENSIONS = {'.md', '.txt', '.html', '.htm'}


class NoteError(ValueError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


class NoteOperations:
    def __init__(self, config, runtime):
        self.config, self.runtime, self.files = config, runtime, runtime.files
        self.previews = {}

    @property
    def workspace_revision(self):
        return self.config.data.get('revision', '')

    def check_workspace(self, revision):
        if not revision or revision != self.workspace_revision:
            raise ConflictError('Workspace changed; read its current workspace_revision and retry')
        self.config.root

    def note_path(self, path):
        path = relative(path)
        self.config.path_for(path, writable=True)
        if Path(path).suffix.lower() not in NOTE_EXTENSIONS:
            raise ValueError('Note operations support Markdown, TXT and HTML/HTM only')
        return path

    def file_operation_path(self, path):
        # Database definitions share guarded move/trash/history operations, but
        # generic note text mutation remains limited to its existing formats.
        path = relative(path)
        if Path(path).suffix.lower() == '.base':
            self.config.path_for(path, writable=True)
            return path
        return self.note_path(path)

    def metadata(self):
        catalog = self.runtime.catalog
        if self.runtime.catalog_pending():
            raise NoteError('metadata_pending', 'Workspace metadata is preparing; retry shortly', retry_after_ms=25)
        if catalog.metadata_ready and catalog.complete_namespace and catalog.root == self.config.data.get('root'):
            return catalog
        if not catalog.complete_namespace or catalog.root != self.config.data.get('root'):
            catalog.metadata_ready = False
        if self.runtime.ensure_metadata() and catalog is self.runtime.catalog and catalog.metadata_ready and catalog.complete_namespace and catalog.root == self.config.data.get('root'):
            return catalog
        raise NoteError('metadata_pending', 'Workspace metadata is preparing; retry shortly', retry_after_ms=600)

    def page(self, rows, limit=50, cursor='', *, key=''):
        if not 1 <= limit <= 200:
            raise ValueError('limit must be between 1 and 200')
        signature = digest(json.dumps([self.workspace_revision, key, rows], ensure_ascii=False, sort_keys=True, default=str))
        offset = 0
        if cursor:
            try:
                previous, offset = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            except (ValueError, TypeError, UnicodeError):
                raise ValueError('Invalid pagination cursor') from None
            if previous != signature:
                raise NoteError('stale_cursor', 'Results changed; restart pagination')
            if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
                raise ValueError('Invalid pagination offset')
        end = min(offset + limit, len(rows))
        next_cursor = base64.urlsafe_b64encode(json.dumps([signature, end]).encode()).decode() if end < len(rows) else None
        return {'ok': True, 'results': rows[offset:end], 'total': len(rows), 'next_cursor': next_cursor,
                'workspace_revision': self.workspace_revision}

    def segment(self, text, offset=0, limit=12000):
        if offset < 0 or not 1 <= limit <= 24000:
            raise ValueError('offset must be nonnegative; limit must be between 1 and 24000')
        end = min(offset + limit, len(text))
        return {'text': text[offset:end], 'offset': offset, 'total': len(text),
                'next_offset': end if end < len(text) else None, 'truncated': end < len(text)}

    def resolve(self, note_id):
        # An exact path does not need the global metadata worker.
        try:
            path = self.note_path(note_id)
            if self.config.path_for(path).is_file():
                return path
        except ValueError:
            # A path containing separators is never reinterpreted as an identity.
            if '/' in note_id or '\\' in note_id or note_id.startswith('.'):
                raise
        catalog = self.metadata()
        identities = (catalog.resolver_indexes or catalog.indexes(catalog.entries))[2]
        candidates = [p for p in sorted(set(catalog.resolve(note_id)) | set(identities.get(note_id, [])))
                      if Path(p).suffix.lower() in NOTE_EXTENSIONS and self.config.path_for(p).is_file()]
        if len(candidates) != 1:
            raise NoteError('ambiguous_note' if candidates else 'not_found',
                            'Select an exact note path' if candidates else 'Note not found', candidates=candidates)
        return candidates[0]

    def read(self, note_id, offset=0, limit=12000):
        with self.config.lock:
            path = self.resolve(note_id)
            value = self.files.read(path)
            return {'ok': True, 'path': path, 'file_path': path, 'revision': value['etag'],
                    'workspace_revision': self.workspace_revision, 'metadata': value['metadata'],
                    'retrieval_selected': self.config.selected(path),
                    **self.segment(value['text'], offset, limit)}

    def list_directory(self, path='', limit=50, cursor=''):
        with self.config.lock:
            path = relative(path)
            return self.page(self.files.tree(path), limit, cursor, key=['directory', path])

    def find(self, query='', folder='', tags=None, format=None, limit=50, cursor=''):
        with self.config.lock:
            catalog = self.metadata()
            folder = relative(folder)
            if not self.config.path_for(folder).is_dir():
                raise ValueError('folder must be an existing directory')
            if format not in (None, 'markdown', 'txt', 'html'):
                raise ValueError('format must be markdown, txt or html')
            extensions = {'markdown': {'.md'}, 'txt': {'.txt'}, 'html': {'.html', '.htm'}}.get(format, NOTE_EXTENSIONS)
            words = query.casefold().split()
            wanted = {t.lstrip('#') for t in tags or []}
            rows, unavailable = [], []
            for path in sorted(catalog.entries):
                if not under(path, folder) or Path(path).suffix.lower() not in extensions:
                    continue
                try:
                    value = self.files.read(path)
                except FileNotFoundError:
                    continue
                except (UnicodeError, ValueError) as error:
                    unavailable.append({'path': path, 'reason': str(error)})
                    # Name/path matches are still useful when the content cannot be searched.
                    value = {'metadata': {}, 'text': '', 'etag': None}
                meta, text = value['metadata'], value['text']
                title = str(meta.get('name') or meta.get('title') or Path(path).stem)
                if Path(path).suffix.lower() in ('.html', '.htm'):
                    match = re.search(r'<title\b[^>]*>(.*?)</title\s*>', text, re.I | re.S)
                    if match:
                        title = match.group(1).strip()
                haystack = (path + ' ' + title + ' ' + text).casefold()
                if not all(word in haystack for word in words):
                    continue
                actual_tags = {str(t).lstrip('#') for t in list_value(meta.get('tags'))}
                if not wanted.issubset(actual_tags):
                    continue
                at = min((text.casefold().find(word) for word in words if word in text.casefold()), default=0)
                rows.append({'path': path, 'title': title, 'tags': sorted(actual_tags),
                             'format': 'html' if Path(path).suffix.lower() in ('.html', '.htm') else 'markdown' if path.lower().endswith('.md') else 'txt',
                             'revision': value['etag'], 'excerpt': text[max(0, at - 80):at + 200]})
            result = self.page(rows, limit, cursor, key=['find', query, folder, tags, format])
            result.update(incomplete=bool(unavailable), content_unavailable=unavailable[:200], content_unavailable_total=len(unavailable))
            return result

    def query(self, query, limit=50, cursor=''):
        with self.config.lock:
            catalog = self.metadata()
            value = catalog.query(query)
            page = self.page(value['rows'], limit, cursor, key=['query', query])
            return {**value, **page, 'rows': page['results']}

    def changed(self, paths):
        # Called under config/files locks: never wait for catalog.update_lock.
        # Catalog workers take that lock before snapshotting config, so doing
        # synchronous catalog work here can deadlock after the file is committed.
        # Readers wait for the queued incremental batch, without rescanning the vault.
        # Standalone callers without a file worker keep explicit metadata preparation.
        if not self.runtime.thread or not self.runtime.thread.is_alive():
            self.runtime.catalog.metadata_ready = False
        self.runtime.files_changed(*paths)
        self.runtime.publish('files', paths)

    def saved(self, path, **extra):
        self.changed([path])
        value = self.files.read(path)
        return {'ok': True, 'path': path, 'revision': value['etag'], 'saved': True,
                'workspace_revision': self.workspace_revision,
                'index_pending': self.config.eligible(path, value['metadata']), **extra}

    def create(self, path, workspace_revision, text=None, template=None):
        with self.config.lock, self.files.lock:
            self.check_workspace(workspace_revision)
            path = self.note_path(path)
            if text is not None and template is not None:
                raise ValueError('Choose text or template, not both')
            if template is not None:
                template = self.note_path(template)
                if template not in {row['path'] for row in self._templates()}:
                    raise ValueError('Choose a template in the configured templates folder')
                rendered = render_template(self.files.read(template)['text'])
                text = rendered['text']
            self.files.create(path, text=text or '')
            return self.saved(path, cursor=rendered['cursor'] if template is not None else None)

    def update(self, path, workspace_revision, expected_revision, mode='replace', text=None, edits=None):
        with self.config.lock, self.files.lock:
            self.check_workspace(workspace_revision)
            path = self.note_path(path)
            value = self.files.read(path)
            if expected_revision != value['etag']:
                raise ConflictError('Note changed; read and merge the current version')
            if mode == 'edit':
                if not edits or text is not None:
                    raise ValueError('edit requires nonempty edits and no text')
                spans = []
                for edit in edits:
                    if set(edit) != {'old_text', 'new_text'} or not all(isinstance(v, str) for v in edit.values()):
                        raise ValueError('Each edit requires old_text and new_text strings')
                    old = edit['old_text']
                    start = value['text'].find(old)
                    if not old or start < 0 or value['text'].find(old, start + 1) >= 0:
                        raise ValueError('Every old_text must match exactly once; no changes saved')
                    spans.append((start, start + len(old), edit['new_text']))
                spans.sort()
                if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
                    raise ValueError('Edits overlap; no changes saved')
                new = value['text']
                for start, end, replacement in reversed(spans):
                    new = new[:start] + replacement + new[end:]
            elif mode in ('replace', 'append'):
                if text is None or edits is not None:
                    raise ValueError('replace/append requires text and no edits')
                new = value['text'] + text if mode == 'append' else text
            else:
                raise ValueError('mode must be replace, edit or append')
            result = self.files.save(path, new, expected_revision, expected_root=str(self.config.root))
            return self.saved(path, history_id=result.get('history_id'))

    def properties(self, path, workspace_revision, expected_revision, updates):
        with self.config.lock, self.files.lock:
            self.check_workspace(workspace_revision)
            path = self.note_path(path)
            if Path(path).suffix.lower() != '.md':
                raise ValueError('Properties require a Markdown note')
            result = self.files.properties(path, updates, expected_revision, expected_root=str(self.config.root))
            return self.saved(path, history_id=result.get('history_id'))

    def create_folder(self, path, workspace_revision):
        with self.config.lock, self.files.lock:
            self.check_workspace(workspace_revision)
            result = self.files.create(relative(path), directory=True)
            self.changed([result['path']])
            return {'ok': True, **result, 'workspace_revision': self.workspace_revision}

    def _operation_state(self, kind, source, destination=''):
        path = self.config.path_for(source, writable=True)
        if not path.is_dir():
            self.file_operation_path(source)
            if kind == 'move' and Path(source).suffix.lower() == '.base' and Path(destination).suffix.lower() != '.base':
                raise ValueError('Database destinations must end in .base')
        snapshot = self.files.snapshot(source)
        plan = self.files.plan_move(source, destination) if kind == 'move' else None
        edits = {path: [digest(old), digest(new)] for path, (old, new) in plan['edits'].items()} if plan else {}
        return {'tree': snapshot, 'edits': edits}

    def operation(self, kind, path, workspace_revision, destination='', dry_run=True, operation_token=None, limit=50, cursor=''):
        with self.config.lock, self.files.lock:
            self.check_workspace(workspace_revision)
            path, destination = relative(path), relative(destination)
            state = self._operation_state(kind, path, destination)
            signature = digest(json.dumps(state, sort_keys=True))
            if dry_run:
                now = time.monotonic()
                self.previews = {k: v for k, v in self.previews.items() if v['expires'] > now}
                if len(self.previews) >= 128:
                    self.previews.pop(next(iter(self.previews)))
                token = secrets.token_urlsafe(32)
                self.previews[token] = {'kind': kind, 'path': path, 'destination': destination,
                                        'workspace_revision': workspace_revision, 'signature': signature, 'expires': now + 300}
                page = self.page(sorted(set(state['tree']) | set(state['edits'])), limit, cursor,
                                 key=[kind, path, destination, signature])
                return {**page, 'dry_run': True, 'operation_token': token, 'expires_in_seconds': 300,
                        'path': path, 'destination': destination or None,
                        'affected_paths': page['results'],
                        'updated_links': len(state['edits']), 'workspace_revision': workspace_revision}
            previous = self.previews.pop(operation_token, None)
            expected = {'kind': kind, 'path': path, 'destination': destination,
                        'workspace_revision': workspace_revision, 'signature': signature}
            if not previous or previous['expires'] <= time.monotonic() or any(previous[k] != v for k, v in expected.items()):
                raise ConflictError('Operation expired or its affected files changed; request a new preview')
            result = self.files.move(path, destination, expected_state=state) if kind == 'move' else self.files.delete(path, expected_snapshot=state['tree'])
            paths = [path, destination] if destination else [path]
            self.changed(paths + list(state['edits']))
            return {'ok': True, **result, 'workspace_revision': workspace_revision,
                    'saved': True, 'index_pending': True}

    def _record(self, kind, key, *, validate_content=True):
        if kind not in ('history', 'trash', 'operations') or not re.fullmatch(r'[a-f0-9]{32}', key):
            raise ValueError('Invalid record')
        path = self.files.state_path(kind, key, 'record.json')
        raw = path.read_bytes()
        record = json.loads(raw)
        if record.get('id') != key:
            raise ValueError('Record identity does not match its directory')
        self.config.path_for(record['path'], writable=True)
        if kind == 'operations':
            destination = self.config.path_for(record['destination'], writable=True)
            source = self.config.path_for(record['path'], writable=True)
            if not (destination.is_dir() or source.is_dir()):
                self.file_operation_path(record['path'])
        if kind != 'operations':
            content = self.files.state_path(kind, key, 'content')
            if not content.is_dir():
                self.file_operation_path(record['path'])
        content_state = {}
        if validate_content:
            if kind == 'operations':
                for edit in record['edits']:
                    content_state[edit['backup']] = self.files.record_snapshot(kind, key, edit['backup'])
            else:
                content_state = self.files.record_snapshot(kind, key)
        return record, digest(raw + json.dumps(content_state, sort_keys=True).encode())

    def _restore_revision(self, kind, record):
        if kind == 'operations':
            paths = [record['destination']] + [row['after_path'] for row in record['edits']]
            state = {}
            for path in paths:
                if self.config.path_for(path).exists():
                    state.update(self.files.snapshot(path))
            return digest(json.dumps(state, sort_keys=True))
        path = self.config.path_for(record['path'])
        return digest(path.read_bytes()) if path.is_file() else 'missing' if not path.exists() else 'directory'

    def records(self, kind='history', path=None, limit=50, cursor=''):
        with self.config.lock:
            if path is not None:
                path = relative(path)
                self.config.path_for(path, writable=True)
            rows = self.files.records(kind, path, limit=None)
            # Filter unsupported standalone files; directories and operation journals remain recoverable.
            eligible = []
            for row in rows:
                try:
                    self._record(kind, row['id'], validate_content=False)
                except (ValueError, FileNotFoundError):
                    continue
                eligible.append({k: row[k] for k in ('id', 'path', 'destination', 'time', 'state') if k in row})
            return self.page(eligible, limit, cursor, key=['records', kind, path])

    def read_record(self, kind, id, offset=0, limit=12000, path_limit=50, path_cursor=''):
        with self.config.lock:
            record, revision = self._record(kind, id)
            summary = {k: record[k] for k in ('id', 'path', 'destination', 'time', 'state') if k in record}
            result = {'ok': True, 'record': summary, 'record_revision': revision,
                      'expected_revision': self._restore_revision(kind, record),
                      'workspace_revision': self.workspace_revision}
            if kind == 'operations':
                paths = set(record.get('mapping', {})) | set(record.get('mapping', {}).values())
                paths.update(record.get('conflicts', []))
                paths.update(row['path'] for row in record['edits'])
                paths.update(row['after_path'] for row in record['edits'])
                result.update(self.page(sorted(paths), path_limit, path_cursor, key=['record', kind, id, revision]))
                result['affected_paths'] = result['results']
                result['conflict_paths'] = [path for path in result['results'] if path in record.get('conflicts', [])]
                summary['conflict_count'] = len(record.get('conflicts', []))
            if kind != 'operations':
                content = self.files.state_path(kind, id, 'content')
                if content.is_file():
                    if content.stat().st_size > 10 * 1024 * 1024:
                        raise ValueError('Record is too large for text preview')
                    result.update(self.segment(content.read_bytes().decode('utf-8-sig'), offset, limit))
                else:
                    result['directory'] = True
                    paths = [record['path'] + ('/' + path if path else '') for path in self.files.record_snapshot(kind, id)]
                    result.update(self.page(paths, path_limit, path_cursor, key=['record', kind, id, revision]))
                    result['affected_paths'] = result['results']
            return result

    def restore(self, kind, id, workspace_revision, expected_revision, record_revision):
        with self.config.lock, self.files.lock:
            self.check_workspace(workspace_revision)
            record, revision = self._record(kind, id)
            if revision != record_revision or expected_revision != self._restore_revision(kind, record):
                raise ConflictError('Record or destination changed; preview the record again')
            result = self.files.restore(kind, id)
            paths = [record['path']]
            if kind == 'operations':
                paths += [record['destination']] + [row['path'] for row in record['edits']]
            self.changed(paths)
            return {'ok': True, **result, 'workspace_revision': workspace_revision, 'saved': True, 'index_pending': True}

    def links(self, path, limit=50, cursor=''):
        with self.config.lock:
            catalog = self.metadata()
            path = self.resolve(path)
            rows = sorted((row for row in catalog.links if row['source'] == path or row['target'] == path),
                          key=lambda row: (row['source'], row['target']))
            return self.page(rows, limit, cursor, key=['links', path])

    def graph(self, path, limit=50, cursor=''):
        with self.config.lock:
            catalog = self.metadata()
            path = self.resolve(path)
            graph = catalog.graph(path)
            result = self.page(graph['nodes'], limit, cursor, key=['graph', path])
            selected = {row['id'] for row in result['results']}
            links = [row for row in graph['links'] if row['source'] in selected and row['target'] in selected]
            result['links'] = links[:200]
            result['links_truncated'] = len(links)>200
            return result

    def _templates(self):
        folder = self.config.data['templates']
        if not self.config.path_for(folder).is_dir():
            return []
        return [{'path': row['path'], 'title': Path(row['name']).stem}
                for row in self.files.tree(folder) if not row['directory'] and Path(row['path']).suffix.lower() in NOTE_EXTENSIONS]

    def templates(self, limit=50, cursor=''):
        with self.config.lock:
            return self.page(self._templates(), limit, cursor, key='templates')

    def daily(self, workspace_revision, date=None):
        with self.config.lock, self.files.lock:
            self.check_workspace(workspace_revision)
            day = dt.date.fromisoformat(date) if date else dt.date.today()
            folder = self.config.data['daily_folder']
            if folder:
                self.config.path_for(folder, writable=True).mkdir(exist_ok=True)
            path = '/'.join(part for part in (folder, day.isoformat() + '.md') if part)
            if self.config.path_for(path).exists():
                return {'ok': True, 'path': path, 'created': False, 'workspace_revision': workspace_revision,
                        'revision': self.files.read(path)['etag']}
            template = self.config.data['templates'] + '/tpl-daily-note.md'
            text = self.files.read(template)['text'] if self.config.path_for(template).is_file() else '# {{date}}\n\n'
            self.files.create(path, text=render_template(text, now=dt.datetime.combine(day, dt.time()))['text'])
            return self.saved(path, created=True)

    def reindex(self, workspace_revision):
        with self.config.lock:
            self.check_workspace(workspace_revision)
            self.runtime.request_index(force=True)
            return {'ok': True, 'state': 'queued', 'workspace_revision': workspace_revision}
