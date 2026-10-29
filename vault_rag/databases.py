"""File-backed databases. Markdown remains the record of truth; no RAG scope changes."""
from __future__ import annotations

import copy
import datetime as dt
import io
import json
import math
import re
import uuid
from collections import OrderedDict
import yaml
from pathlib import Path
from functools import cmp_to_key

from ruamel.yaml import YAML

from vault_rag.catalog import Expr, list_value
from vault_rag.local_state import ConflictError, atomic_write, digest, relative, under
from vault_rag.note_operations import NoteError, NoteOperations

TYPES = {'text', 'number', 'select', 'multiselect', 'date', 'checkbox', 'url', 'attachment'}
VIEWS = {'table', 'list', 'cards', 'leafloomTimeline', 'leafloomBoard'}


def safe(value):
    return json.loads(json.dumps(value, default=str, ensure_ascii=False, allow_nan=False))


def key_name(key):
    return key[5:] if key.startswith('note.') else key


def cell(row, key):
    if key == 'title':
        return row['title']
    return row['file'].get(key[5:]) if key.startswith('file.') else row['metadata'].get(key_name(key))


class Databases:
    def __init__(self, config, runtime, notes=None):
        self.config, self.runtime, self.files = config, runtime, runtime.files
        self.notes = notes or NoteOperations(config, runtime)
        self._documents = OrderedDict()
        self._rows = OrderedDict()
        from vault_rag.database_board import DatabaseBoard
        self.board = DatabaseBoard(self)

    def remember_document(self, path, revision, data, yaml=None):
        # The file hash, not timestamps, binds the cache to the bytes read/saved.
        key = (str(self.config.root), path, revision)
        with self.config.lock:
            self._documents[key] = (copy.deepcopy(data), copy.deepcopy(yaml.version) if yaml else None,
                                    copy.deepcopy(yaml.tags) if yaml else None)
            self._documents.move_to_end(key)
            while len(self._documents) > 16: self._documents.popitem(last=False)

    def document(self, path):
        path = relative(path)
        if Path(path).suffix.lower() != '.base':
            raise ValueError('Database path must end in .base')
        self.board.recover(path)
        value = self.files.read(path)
        yaml = YAML(); yaml.preserve_quotes = True
        key = (value['root'], path, value['etag'])
        with self.config.lock:
            cached = self._documents.get(key)
            if cached is not None:
                self._documents.move_to_end(key)
                yaml.version=copy.deepcopy(cached[1]);yaml.tags=copy.deepcopy(cached[2])
                return value, copy.deepcopy(cached[0]), yaml
        data = yaml.load(value['text']) or {}
        if not isinstance(data, dict) or not isinstance(data.get('views', []), list):
            raise ValueError('Invalid database configuration')
        if not isinstance(data.get('leafloom', {}), dict) or not isinstance(data.get('properties', {}), dict) or any(not isinstance(v, dict) for v in data.get('views', [])):
            raise ValueError('Invalid database configuration')
        if data.get('leafloom', {}).get('schemaVersion', 1) != 1:
            raise ValueError('Unsupported database schema version; source kept unchanged')
        self.remember_document(path, value['etag'], data, yaml)
        return value, data, yaml

    def fields(self, data):
        result = {'title': {'type': 'text', 'displayName': 'title'},
                  'file.ctime': {'type': 'date', 'displayName': 'file.ctime', 'readonly': True},
                  'file.mtime': {'type': 'date', 'displayName': 'file.mtime', 'readonly': True}}
        for key, spec in data.get('leafloom', {}).get('fields', {}).items():
            result[key] = {**dict(spec), 'displayName': data.get('properties', {}).get(key, {}).get('displayName', key)}
        for view in data.get('views', []):
            for key in view.get('order', ['status', 'priority', 'due'] if not data.get('leafloom') else []):
                if key not in {'title', 'file.name'}:
                    result.setdefault(key, {'type': 'text', 'displayName': key, 'readonly': key.startswith(('file.', 'formula.'))})
        for key, spec in data.get('properties', {}).items():
            result.setdefault(key, {'type': 'text', **dict(spec), 'readonly': key.startswith(('file.', 'formula.'))})
        return result

    def config_read(self, path):
        with self.config.lock:
            value, data, _ = self.document(path)
            views = []
            for index, view in enumerate(data.get('views', [])):
                views.append({**safe(view), 'id': view.get('leafloom', {}).get('id', f'legacy-{index}'),
                              'supported': view.get('type') in VIEWS})
            return {'ok': True, 'path': path, 'root': value['root'], 'revision': value['etag'],
                    'workspace_revision': self.notes.workspace_revision,
                    'fields': safe(self.fields(data)), 'views': views,
                    'folder': data.get('leafloom', {}).get('folder'), 'config': safe(data),
                    'tasks': safe(data.get('leafloom', {}).get('tasks')), 'suggested_tasks': self.board.suggestion(data)}

    def discover(self, folder='', limit=100, cursor=''):
        catalog = self.notes.metadata()
        with catalog.lock:
            rows = [{'path': p, 'title': e['title']} for p, e in sorted(catalog.entries.items())
                    if p.endswith('.base') and under(p, folder)]
        return self.notes.page(rows, limit, cursor, key=['databases', folder])

    def view(self, data, view_id):
        for index, view in enumerate(data.get('views', [])):
            if (not view_id and index == 0) or view_id in (view.get('leafloom', {}).get('id', f'legacy-{index}'), view.get('name')):
                return view
        raise ValueError('Database view not found')

    def matches(self, condition, row):
        if not condition:
            return True
        if isinstance(condition, str):
            # Support standard note.property names without modifying the interpreter.
            return bool(Expr(condition, {**row['metadata'], 'note': row['metadata'], 'file': row['file']}).run())
        if not isinstance(condition, dict) or len(condition) != 1:
            raise ValueError('Invalid database filter')
        op, values = next(iter(condition.items()))
        if op not in {'and', 'or', 'not'} or not isinstance(values, list):
            raise ValueError('Invalid database filter operator')
        checks = [self.matches(v, row) for v in values]
        return all(checks) if op == 'and' else any(checks) if op == 'or' else not any(checks)

    def query_rows(self, config, view, search=''):
        data = config['config']; catalog = self.notes.metadata()
        with catalog.lock:
            version = catalog.version; snapshot = catalog.entries
        definition = {k: view.get(k) for k in ('type', 'filters', 'sort', 'groupBy')}
        definition['conditions'] = view.get('leafloom', {}).get('conditions', [])
        key = (config['root'], config['workspace_revision'], config['path'], config['revision'], version,
               id(snapshot), search, json.dumps(definition, sort_keys=True, default=str))
        with self.config.lock:
            cached = self._rows.get(key)
            if cached is not None:
                self._rows.move_to_end(key)
                return cached, version
        entries = list(snapshot.values())
        rows = []; folder = config['folder']; filters = view.get('leafloom', {}).get('conditions', [])
        for entry in entries:
            if not entry['path'].endswith('.md') or (folder is not None and not under(entry['path'], folder)): continue
            row = {'path': entry['path'], 'title': entry['title'], 'metadata': safe(entry['metadata']),
                   'file': safe(entry['file']), 'revision': entry['sha256']}
            if search and search.casefold() not in (row['title'] + ' ' + json.dumps(row['metadata'], ensure_ascii=False)).casefold(): continue
            if not self.matches(data.get('filters'), row) or not self.matches(view.get('filters'), row): continue
            if not all(self.condition(c, row) for c in filters): continue
            rows.append(row)
        sorts = list(view.get('sort', [])); group = view.get('groupBy', {}).get('property')
        if group and view.get('type') != 'leafloomBoard': sorts.insert(0, {'property': group, 'direction': view.get('groupBy', {}).get('direction', 'ASC')})
        def compare(a, b):
            for spec in sorts:
                key = spec.get('property') or spec.get('column'); x, y = cell(a, key), cell(b, key)
                if x is None or y is None: n = (x is None) - (y is None)
                else:
                    field = config['fields'].get(key, {}); type_ = field.get('type')
                    try:
                        if type_ == 'number': x, y = float(x), float(y)
                        elif type_ == 'checkbox': x, y = bool(x), bool(y)
                        elif type_ == 'select' and view.get('type') == 'leafloomBoard':
                            options = field.get('options', [])
                            x, y = (options.index(x) if x in options else len(options), str(x)), (options.index(y) if y in options else len(options), str(y))
                        else: x, y = str(x).casefold(), str(y).casefold()
                        n = ((x > y) - (x < y)) * (-1 if spec.get('direction', 'ASC').upper() == 'DESC' else 1)
                    except (TypeError, ValueError): n = (str(x) > str(y)) - (str(x) < str(y))
                if n: return n
            return (a['path'] > b['path']) - (a['path'] < b['path'])
        rows.sort(key=cmp_to_key(compare))
        # Internal query snapshots are read-only; columns only slice/reorder them.
        with self.config.lock:
            self._rows[key] = rows
            self._rows.move_to_end(key)
            while len(self._rows) > 4: self._rows.popitem(last=False)
        return rows, version

    def query(self, path, view_id='', search='', cursor='', limit=100, group_key=None, anchor_path='', recent_paths=None):
        with self.config.lock:
            config = self.config_read(path); data = config['config']; view = self.view(data, view_id)
            if view.get('type') not in VIEWS: raise ValueError('This view uses the legacy viewer')
            if recent_paths is not None and (not isinstance(recent_paths, list) or len(recent_paths) > 20 or any(not isinstance(p, str) for p in recent_paths)):
                raise ValueError('recent_paths must contain at most 20 paths')
            rows, version = self.query_rows(config, view, search)
            requested = set(recent_paths or [])
            recent = {'recent_records': [r for r in rows if r['path'] in requested]} if requested else {}
            if view.get('type') == 'leafloomBoard':
                return {**self.board.query(config, view, rows, version, search, group_key, cursor, limit, anchor_path), **recent}
            counts = {}; group = view.get('groupBy', {}).get('property')
            if group:
                for row in rows:
                    raw_group = cell(row, group); name = '' if raw_group is None else str(raw_group); counts[name] = counts.get(name, 0) + 1
            page = self.notes.page(rows, limit, cursor, key=[path, config['revision'], version, view_id, search])
            return {**page, 'groups': counts, 'config_revision': config['revision'], 'catalog_version': version, **recent}

    def condition(self, condition, row):
        key, op, value = condition['field'], condition['operator'], condition.get('value')
        actual = cell(row, key)
        if op == 'empty': return actual is None or actual == '' or actual == []
        if op == 'not_empty': return not self.condition({'field': key, 'operator': 'empty'}, row)
        if op == 'eq': return actual == value
        if op == 'neq': return actual != value
        if op == 'contains': return value in actual if isinstance(actual, list) else str(value).casefold() in str(actual or '').casefold()
        if op in {'gt', 'lt', 'gte', 'lte'}:
            try:
                return {'gt': lambda: actual > value, 'lt': lambda: actual < value,
                        'gte': lambda: actual >= value, 'lte': lambda: actual <= value}[op]()
            except TypeError: return False
        raise ValueError('Unsupported filter operator')

    def validate_values(self, data, updates, old=None):
        if not isinstance(updates, dict): raise ValueError('Record values must be an object')
        fields = self.fields(data)
        for key, value in updates.items():
            if key not in fields or key.startswith(('file.', 'formula.')):
                raise ValueError('Choose a configured editable field')
            if value is None: continue
            spec = fields[key]; kind = spec.get('type', 'text')
            valid = (kind in {'text', 'url', 'select', 'date'} and isinstance(value, str) or
                     kind == 'number' and type(value) in (int, float) or
                     kind == 'checkbox' and type(value) is bool or
                     kind in {'multiselect', 'attachment'} and isinstance(value, list) and all(isinstance(v, str) for v in value))
            if not valid: raise ValueError(f'Invalid value for {key}')
            if kind == 'number' and not math.isfinite(value): raise ValueError('Number must be finite')
            if kind == 'date':
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value): raise ValueError('Use YYYY-MM-DD dates')
                dt.date.fromisoformat(value)
            if kind == 'url' and value and not re.match(r'^https?://[^\s]+$', value): raise ValueError('Use an HTTP(S) URL')
            if kind in {'select', 'multiselect'} and spec.get('options'):
                if any(v not in spec['options'] for v in (value if isinstance(value, list) else [value])):
                    raise ValueError('Select a configured option')
        merged = {**(old or {}), **{key_name(k): v for k, v in updates.items()}}
        for view in data.get('views', []):
            if view.get('type') != 'leafloomTimeline': continue
            opts = view.get('leafloom', {}); start, end = opts.get('startField'), opts.get('endField')
            if not start or not end or not ({start, end} & set(updates)): continue
            a, b = merged.get(key_name(start)), merged.get(key_name(end))
            if a and b and str(b) < str(a): raise ValueError('End date must not be before start date')
        return {key_name(k): v for k, v in updates.items()}

    def validate_config(self, data):
        leaf = data.setdefault('leafloom', {}); leaf.setdefault('schemaVersion', 1)
        folder = leaf.get('folder')
        if folder is not None:
            self.config.path_for(folder, writable=True)
            if not self.config.path_for(folder).is_dir(): raise ValueError('Record folder must exist')
        fields = leaf.setdefault('fields', {})
        for key, spec in fields.items():
            if not re.fullmatch(r'(?:note\.)?[^.\s/\\]+', key) or key_name(key) in {'title', 'file', 'formula', 'note'}:
                raise ValueError('Invalid or reserved field key')
            if spec.get('type') not in TYPES: raise ValueError('Unsupported field type')
            if 'options' in spec and (not isinstance(spec['options'], list) or not all(isinstance(x, str) for x in spec['options'])):
                raise ValueError('Options must be text values')
        keys = [key_name(k) for k in fields]
        if len(set(keys)) != len(keys): raise ValueError('Duplicate field keys')
        ids = set()
        for view in data.get('views', []):
            opts = view.setdefault('leafloom', {}); opts.setdefault('id', uuid.uuid4().hex)
            if opts['id'] in ids: raise ValueError('Duplicate view ID')
            ids.add(opts['id'])
            if view.get('type') == 'leafloomTimeline' and opts.get('startField') and opts.get('startField') == opts.get('endField'):
                raise ValueError('Choose two distinct date fields')
            for date_key in ('startField', 'endField'):
                key = opts.get(date_key)
                if key and self.fields(data).get(key, {}).get('type') != 'date': raise ValueError('Timeline requires date fields')
            for c in opts.get('conditions', []):
                if c.get('field') not in self.fields(data) or c.get('operator') not in {'empty', 'not_empty', 'eq', 'neq', 'contains', 'gt', 'lt', 'gte', 'lte'}:
                    raise ValueError('Invalid filter condition')
        if not data.get('views'): raise ValueError('Keep at least one view')
        self.board.validate(data)

    def command(self, path, command, workspace_revision, expected_revision='', operation_id=''):
        with self.config.lock, self.files.lock:
            self.notes.check_workspace(workspace_revision)
            if not isinstance(command, dict): raise ValueError('Database command must be an object')
            action = command.get('type'); path = relative(path)
            if action != 'create': self.board.recover(path)
            if action in {'record.move', 'board.undo'} or action == 'board.group.remove' and not command.get('dry_run'):
                replay = self.board.replay(path, command, operation_id)
                if replay is not None: return replay
            required = {'field.set': ('key', 'field'), 'field.remove': ('key',), 'view.add': ('view',),
                        'view.update': ('view_id', 'patch'), 'view.remove': ('view_id',),
                        'record.update': ('path', 'record_revision'), 'record.duplicate': ('path', 'record_revision'), 'record.trash': ('path',),
                        'record.move': ('path', 'record_revision', 'view_id', 'group_key', 'catalog_version'), 'board.undo': ('move_id',),
                        'board.group.remove': ('view_id', 'group_key')}
            if any(k not in command for k in required.get(action, ())): raise ValueError('Missing database command arguments')
            for name in ('field', 'view', 'patch'):
                if name in command and not isinstance(command[name], dict): raise ValueError('Configuration changes must be objects')
            if action in {'create', 'record.create', 'record.duplicate'}:
                if not re.fullmatch(r'[\w-]{1,128}', operation_id): raise ValueError('Creation requires a unique operation_id')
                receipt = self.files.state_path('database-receipts', digest(operation_id) + '.json')
                signature = digest(json.dumps([path, command], sort_keys=True, ensure_ascii=False))
                if receipt.exists():
                    previous = json.loads(receipt.read_text())
                    if previous['signature'] != signature: raise ConflictError('operation_id was used for another command')
                    if previous.get('result'): return previous['result']
                    target = previous['target']
                    if self.config.path_for(target).is_file():
                        if digest(self.config.path_for(target).read_bytes()) != previous['content_hash']:
                            raise ConflictError('Creation outcome changed; inspect the target before retrying')
                        result = {'ok': True, 'path': target, 'revision': self.files.read(target)['etag'], 'workspace_revision': workspace_revision}
                        if action in {'record.create', 'record.duplicate'}:
                            _, original_data, _ = self.document(path)
                            result.update(self.creation_result(original_data, self.view(original_data, command.get('view_id', '')), target, command.get('search', ''), command.get('return_record', False)))
                        atomic_write(receipt, json.dumps({**previous, 'result': result}).encode()); return result
                else: previous = None
            if action == 'create':
                path = relative(path)
                if not path.endswith('.base'): raise ValueError('Database path must end in .base')
                self.config.path_for(path, writable=True)
                if self.config.path_for(path).exists(): raise ConflictError('Database already exists')
                folder = relative(command.get('folder', str(Path(path).with_suffix(''))))
                if not self.config.path_for(folder).exists():
                    self.files.create(folder, directory=True)
                data = {'properties': {}, 'leafloom': {'schemaVersion': 1, 'folder': folder, 'fields': {
                    'category': {'type': 'select', 'options': []}, 'attachments': {'type': 'attachment'},
                    'cover': {'type': 'attachment'}, 'start_date': {'type': 'date'}, 'end_date': {'type': 'date'}}},
                    'views': [{'type': kind, 'name': name, 'order': ['title', 'category', 'attachments', 'start_date', 'end_date'],
                               'leafloom': {'id': uuid.uuid4().hex, **({'coverField': 'cover'} if kind == 'cards' else {}),
                                            **({'startField': 'start_date', 'endField': 'end_date'} if kind == 'leafloomTimeline' else {})}}
                              for kind, name in [('table', 'Table'), ('list', 'List'), ('cards', 'Gallery'), ('leafloomTimeline', 'Timeline')]]}
                if command.get('preset') == 'tasks':
                    board = self.board.prepare_view(data, {'type': 'leafloomBoard', 'name': 'Board', 'leafloom': {'id': uuid.uuid4().hex}}, {'preset': 'tasks'})
                    task = data['leafloom']['tasks']
                    for existing in data['views']:
                        if existing['type'] in {'table', 'list'}: existing['order'] = ['title', task['statusField'], task['priorityField'], 'start_date', task['dueField'], 'category', 'attachments']
                        elif existing['type'] == 'cards': existing['order'] = ['title', task['statusField'], task['priorityField'], task['dueField'], 'category']
                    data['views'].insert(0, board)
                self.validate_config(data); yaml = YAML(); out = io.StringIO(); yaml.dump(data, out)
                return self.create_once(path, out.getvalue(), receipt, signature)
            value, data, yaml = self.document(path)
            for index, existing_view in enumerate(data.get('views', [])):
                existing_view.setdefault('leafloom', {}).setdefault('id', f'legacy-{index}')
            if expected_revision != value['etag']: raise ConflictError('Database changed; reload configuration before saving')
            if action == 'record.move': return self.board.move(path, data, yaml, value, command, operation_id)
            if action == 'board.undo': return self.board.undo(path, command, operation_id)
            if action == 'board.group.remove': return self.board.remove_group(path, data, yaml, value, command, operation_id)
            if action == 'record.duplicate':
                source = relative(command['path']); folder = data.get('leafloom', {}).get('folder')
                if not source.endswith('.md') or (folder is not None and not under(source, folder)):
                    raise ValueError('Record is outside the database folder')
                note = self.files.read(source)
                if note['etag'] != command['record_revision']: raise ConflictError('db.recordConflict')
                title = str(command.get('title', '')).strip() or str(note['metadata'].get('name') or note['metadata'].get('title') or Path(source).stem) + ' (copy)'
                filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', title).strip('. ')[:100] or 'Untitled'
                target = previous['target'] if previous else Path(source).with_name(filename + '.md').as_posix()
                if not previous:
                    n = 1
                    while self.config.path_for(target).exists():
                        n += 1; target = Path(source).with_name(f'{filename} ({n}).md').as_posix()
                updates = {'title': title}
                if 'name' in note['metadata']: updates['name'] = title
                if 'id' in note['metadata']: updates['id'] = uuid.uuid4().hex
                from vault_rag.database_board import property_text
                return self.create_once(target, property_text(note['text'], updates), receipt, signature, data=data, view=self.view(data, command.get('view_id', '')), search=command.get('search', ''), return_record=command.get('return_record', False))
            if action == 'record.create':
                folder = data.get('leafloom', {}).get('folder')
                if folder is None: raise ValueError('Configure a record folder before creating records')
                title = str(command.get('title', '')).strip() or 'Untitled'
                filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', title).strip('. ')[:100] or 'Untitled'
                target = f'{folder}/{filename}.md' if folder else filename + '.md'
                if previous: target = previous['target']
                else:
                    n = 1
                    while self.config.path_for(target).exists():
                        n += 1; target = '/'.join(x for x in [folder, f'{filename} ({n}).md'] if x)
                initial = {}; tasks = data.get('leafloom', {}).get('tasks')
                if tasks: initial[tasks['statusField']] = tasks['initialStatus']
                if command.get('group_key') is not None:
                    v = self.view(data, command.get('view_id')); group = v.get('groupBy', {}).get('property')
                    if v.get('type') != 'leafloomBoard' or not group: raise ValueError('db.boardSelectField')
                    initial[group] = json.loads(command['group_key'])
                values = self.validate_values(data, {**initial, **command.get('values', {})}); values['title'] = title
                out = io.StringIO(); yaml.dump(values, out)
                return self.create_once(target, '---\n' + out.getvalue() + '---\n\n', receipt, signature, data=data, view=self.view(data, command.get('view_id', '')), search=command.get('search', ''), return_record=command.get('return_record', False))
            if action in {'record.update', 'record.trash'}:
                target = relative(command['path']); folder = data.get('leafloom', {}).get('folder')
                if not target.endswith('.md') or (folder is not None and not under(target, folder)):
                    raise ValueError('Record is outside the database folder')
                if action == 'record.trash':
                    if command.get('record_revision') and self.files.read(target)['etag'] != command['record_revision']:
                        raise ConflictError('db.recordConflict')
                    return self.notes.operation('delete', target, workspace_revision, '', command.get('dry_run', True), command.get('operation_token'))
                old = self.files.read(target)
                updates = self.validate_values(data, command.get('values', {}), old['metadata'])
                if 'title' in updates and 'name' in old['metadata']:
                    updates['name'] = updates.pop('title')
                result = self.files.properties(target, updates, command['record_revision'], expected_root=value['root'])
                return {'ok': True, 'path': target, 'revision': result['etag'], 'note': result, 'history_id': result.get('history_id'), 'catalog_version': self.runtime.catalog.version}
            if action == 'field.set':
                key = command['key']; fields = data.setdefault('leafloom', {}).setdefault('fields', {})
                fields[key] = {**fields.get(key, {}), **command['field']}
                data.setdefault('properties', {}).setdefault(key, {})['displayName'] = command.get('displayName', key)
            elif action == 'field.remove':
                key = command['key']; data.setdefault('leafloom', {}).setdefault('fields', {}).pop(key, None)
                data.setdefault('properties', {}).pop(key, None)
                if key in [data.get('leafloom', {}).get('tasks', {}).get(role) for role in ('statusField', 'priorityField', 'dueField')]: data['leafloom'].pop('tasks', None)
                for v in data.get('views', []):
                    if 'order' in v: v['order'] = [k for k in v['order'] if k != key]
                    if v.get('groupBy', {}).get('property') == key: v.pop('groupBy', None)
                    v['sort'] = [s for s in v.get('sort', []) if s.get('property') != key]
                    opts = v.get('leafloom', {})
                    opts['conditions'] = [c for c in opts.get('conditions', []) if c.get('field') != key]
                    for name in ('startField', 'endField', 'coverField'):
                        if opts.get(name) == key: opts.pop(name)
            elif action == 'view.add':
                if command['view'].get('type') not in VIEWS: raise ValueError('Unsupported view type')
                added = copy.deepcopy(command['view'])
                if added.get('type') == 'leafloomBoard': self.board.prepare_view(data, added, command)
                data.setdefault('views', []).append(added)
            elif action in {'view.update', 'view.remove'}:
                v = self.view(data, command['view_id'])
                if command.get('task_setup') is not None: self.board.setup(data, command['task_setup'])
                if action == 'view.remove': data['views'].remove(v)
                else:
                    patch = copy.deepcopy(command['patch'])
                    previous_group = v.get('groupBy', {}).get('property')
                    if 'leafloom' in patch:
                        if isinstance(patch['leafloom'].get('board'), dict):
                            patch['leafloom']['board'] = {**v.get('leafloom', {}).get('board', {}), **patch['leafloom']['board']}
                        patch['leafloom'] = {**v.get('leafloom', {}), **patch['leafloom'], 'id': v.get('leafloom', {}).get('id', command['view_id'])}
                    v.update(patch)
                    if v.get('type') == 'leafloomBoard' and previous_group != v.get('groupBy', {}).get('property'):
                        board = v.setdefault('leafloom', {}).setdefault('board', {})
                        for name in ('groupOrder', 'hiddenGroups', 'collapsedGroups'): board[name] = []
            else: raise ValueError('Unsupported database command')
            self.validate_config(data); out = io.StringIO(); yaml.dump(data, out)
            result = self.files.save(path, out.getvalue(), expected_revision, expected_root=value['root'])
            self.remember_document(path, result['etag'], data, yaml)
            return {'ok': True, 'path': path, 'revision': result['etag'], 'history_id': result.get('history_id')}

    def creation_result(self, data, view, target, search='', return_record=False):
        entry = self.runtime.catalog._entry(self.config.root, self.config.path_for(target), force=True)
        row = {'path': target, 'title': entry['title'], 'metadata': safe(entry['metadata']), 'file': safe(entry['file']), 'revision': entry['sha256']}
        visible = bool(self.matches(data.get('filters'), row) and self.matches(view.get('filters'), row) and all(self.condition(c, row) for c in view.get('leafloom', {}).get('conditions', [])) and (not search or search.casefold() in (row['title']+' '+json.dumps(row['metadata'],ensure_ascii=False)).casefold()))
        return {'visible': visible, **({'record': row, 'catalog_version': self.runtime.catalog.version} if return_record else {})}

    def created_visible(self, data, view, target, search=''):
        return self.creation_result(data, view, target, search)['visible']

    def create_once(self, target, text, receipt, signature, data=None, view=None, search='', return_record=False):
        previous = {'signature': signature, 'target': target, 'content_hash': digest(text.encode())}
        receipt.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(receipt, json.dumps(previous).encode())
        self.files.create(target, text=text)
        result = {'ok': True, 'path': target, 'revision': self.files.read(target)['etag'], 'workspace_revision': self.notes.workspace_revision}
        if data is not None and view is not None: result.update(self.creation_result(data, view, target, search, return_record))
        atomic_write(receipt, json.dumps({**previous, 'result': result}).encode())
        return result


def legacy_base(self, path, view_index=None):
    import hashlib
    raw=self.files.read(path)['text'];data=yaml.safe_load(raw) or {};rows=[]
    profiles=json.loads((Path(__file__).parent/'tasknotes_profiles.json').read_text(encoding='utf-8'))
    today=dt.date.today()
    def day(value):
        try:return dt.date.fromisoformat(str(value)[:10])
        except (ValueError,TypeError):return None
    def open_task(row):
        return row.get('status')!='done' if not row.get('recurrence') else today not in [day(v) for v in list_value(row.get('complete_instances'))]
    def matches(filter_,row):
        if not filter_:return True
        profile=profiles.get(hashlib.sha256(json.dumps(filter_,ensure_ascii=False,sort_keys=True).encode()).hexdigest())
        if profile:
            if not open_task(row):return False
            due=day(row.get('due'));scheduled=day(row.get('scheduled'));dates=[v for v in (due,scheduled) if v]
            if profile=='Today':return today in dates
            if profile=='Overdue':return any(v<today for v in dates)
            if profile=='This Week':return any(today<=v<=today+dt.timedelta(days=7) for v in dates)
            if profile=='Unscheduled':return not dates
            if profile=='Not Blocked':
                for block in list_value(row.get('blockedBy')):
                    key=str(block.get('uid','')) if isinstance(block,dict) else str(block).strip('[]')
                    targets=self.resolve(key)
                    if any(self.entries[t]['metadata'].get('status')!='done' for t in targets):return False
                return True
        if isinstance(filter_,str):return bool(Expr(filter_,row).run())
        if isinstance(filter_,dict):return all((all(matches(v,row) for v in vals) if op=='and' else any(matches(v,row) for v in vals) if op=='or' else not any(matches(v,row) for v in vals)) for op,vals in filter_.items())
        raise ValueError('视图筛选格式无效')
    for entry in self.entries.values():
        if entry['path'].lower().endswith('.md'):
            row={**entry['metadata'],'file':entry['file']}
            if matches(data.get('filters'),row):rows.append({'path':entry['path'],'title':entry['title'],'metadata':entry['metadata'],'file':entry['file'],'etag':entry['sha256']})
    for index,view in enumerate(data.get('views',[])):
        if view_index is not None and index!=view_index:
            view['rows']=[];continue
        try:
            view['rows']=[r for r in rows if matches(view.get('filters'),{**r['metadata'],'file':r['file']})]
            for sort in reversed(view.get('sort',[])):
                key=sort.get('property') or sort.get('column');reverse=sort.get('direction','ASC')=='DESC'
                view['rows'].sort(key=lambda r:(r['metadata'].get(key) is not None,str(r['metadata'].get(key,''))),reverse=reverse)
        except ValueError as e:view['rows']=[];view['error']=str(e)
    return {'properties':data.get('properties',{}),'views':data.get('views',[]),'active_view':view_index}
