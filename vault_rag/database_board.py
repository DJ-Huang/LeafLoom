"""Database board configuration, independently paged columns and recoverable moves."""
from __future__ import annotations

import base64
import copy
import io
import json
import re
import time
from pathlib import Path
from ruamel.yaml import YAML
from vault_rag.local_state import ConflictError, atomic_write, digest, relative, under

COLORS = {'gray', 'blue', 'green', 'red', 'orange', 'yellow', 'purple', 'pink'}


def group_key(value):
    return json.dumps(None if value in ('', None) else str(value), ensure_ascii=False, separators=(',', ':'))


def property_text(text, updates):
    # Prepare the metadata prefix for a guarded save; the note body stays literal.
    nl = '\r\n' if '\r\n' in text else '\n'
    match = re.match(r'^---\r?\n(.*?)\r?\n---(?:\r?\n|$)', text, re.S)
    yaml = YAML(); yaml.preserve_quotes = True; yaml.width = 4096
    data = yaml.load(match.group(1).replace('\r\n', '\n')) if match else {}
    data = data or {}
    for key, value in updates.items():
        if value is None: data.pop(key, None)
        else: data[key] = value
    out = io.StringIO(); yaml.dump(data, out)
    return ('---\n' + out.getvalue().rstrip('\n') + '\n---\n').replace('\n', nl) + (text[match.end():] if match else text)


def serialized(text, old):
    remainder = old.replace(b'\r\n', b'')
    if '\r' not in text and b'\r\n' in old and b'\n' not in remainder and b'\r' not in remainder:
        text = text.replace('\n', '\r\n')
    return (b'\xef\xbb\xbf' if old.startswith(b'\xef\xbb\xbf') else b'') + text.encode('utf-8')


class DatabaseBoard:
    def __init__(self, database):
        self.db = database
        self.files, self.config = database.files, database.config

    def suggestion(self, data):
        fields = self.db.fields(data)
        def choose(preferred, kind):
            preferred = [k for k in preferred if isinstance(k, str) and k]
            for key in preferred:
                if fields.get(key, {}).get('type') == kind and not fields[key].get('readonly'): return key
            for key in preferred:
                alias = next((k for k, v in fields.items() if k.removeprefix('note.') == key and v.get('type') == kind and not v.get('readonly')), None)
                if alias: return alias
            name = preferred[0]
            if name in {k.removeprefix('note.') for k in fields}: name = 'task_' + name
            base, index = name, 2
            while name in {k.removeprefix('note.') for k in fields}: name = base + '_' + str(index); index += 1
            return name
        existing = data.get('leafloom', {}).get('tasks', {})
        if not isinstance(existing, dict): existing = {}
        status = choose([existing.get('statusField', 'status'), 'status'], 'select')
        priority = choose([existing.get('priorityField', 'priority'), 'priority'], 'select')
        ends = [v.get('leafloom', {}).get('endField') for v in data.get('views', []) if v.get('type') == 'leafloomTimeline']
        due = choose([existing.get('dueField', 'due'), 'due', *[k for k in ends if k], 'end_date'], 'date')
        options = fields.get(status, {}).get('options', []) if status in fields else ['open', 'in-progress', 'done']
        return {'statusField': status, 'priorityField': priority, 'dueField': due,
                'initialStatus': existing.get('initialStatus', 'open' if 'open' in options else ''),
                'completedStatuses': existing.get('completedStatuses', ['done'] if 'done' in options else []),
                'newFields': [k for k in (status, priority, due) if k not in fields]}

    def setup(self, data, requested=None):
        if requested is not None and not isinstance(requested, dict): raise ValueError('db.boardTaskFields')
        existing = data.get('leafloom', {}).get('tasks', {})
        task = {**(existing if isinstance(existing, dict) else {}), **self.suggestion(data), **(requested or {})}; task.pop('newFields', None)
        fields = data.setdefault('leafloom', {}).setdefault('fields', {})
        definitions = {
            'statusField': {'type': 'select', 'options': ['open', 'in-progress', 'done'], 'optionMeta': {
                'open': {'labelKey': 'db.todo', 'color': 'gray'}, 'in-progress': {'labelKey': 'db.doing', 'color': 'blue'}, 'done': {'labelKey': 'db.done', 'color': 'green'}}},
            'priorityField': {'type': 'select', 'options': ['high', 'medium', 'low'], 'optionMeta': {
                'high': {'labelKey': 'db.high', 'color': 'red'}, 'medium': {'labelKey': 'db.mediumPriority', 'color': 'yellow'}, 'low': {'labelKey': 'db.low', 'color': 'gray'}}},
            'dueField': {'type': 'date'}}
        for role, spec in definitions.items():
            key = task.get(role)
            if not isinstance(key, str) or not key: raise ValueError('db.boardTaskFields')
            found = self.db.fields(data).get(key)
            if found:
                if found.get('type') != spec['type'] or found.get('readonly'): raise ValueError('db.boardTaskFields')
            else:
                fields[key] = copy.deepcopy(spec)
                data.setdefault('properties', {})[key] = {'displayName': {'statusField': 'db.status', 'priorityField': 'db.priority', 'dueField': 'db.due'}[role]}
        if len({task[k] for k in definitions}) != 3: raise ValueError('db.boardTaskFields')
        opts = self.db.fields(data)[task['statusField']].get('options', [])
        if task.get('initialStatus') not in opts or not task.get('completedStatuses') or any(v not in opts for v in task['completedStatuses']):
            raise ValueError('db.boardChooseStates')
        data['leafloom']['tasks'] = task
        return task

    def prepare_view(self, data, view, command):
        if command.get('preset') == 'tasks' or command.get('task_setup') is not None:
            task = self.setup(data, command.get('task_setup'))
            view.setdefault('groupBy', {'property': task['statusField']})
            view.setdefault('order', ['title', task['priorityField'], task['dueField'], 'category'])
        view.setdefault('leafloom', {}).setdefault('board', {})
        return view

    def validate(self, data):
        fields = self.db.fields(data)
        for field in fields.values():
            meta = field.get('optionMeta', {})
            if not isinstance(meta, dict): raise ValueError('db.invalidOption')
            for value, entry in meta.items():
                if not isinstance(value, str) or not isinstance(entry, dict) or any(not isinstance(entry.get(k, ''), str) for k in ('label', 'labelKey')) or entry.get('color', 'gray') not in COLORS:
                    raise ValueError('db.invalidOption')
        tasks = data.get('leafloom', {}).get('tasks')
        if tasks:
            if not isinstance(tasks, dict): raise ValueError('db.boardTaskFields')
            for role, kind in [('statusField', 'select'), ('priorityField', 'select'), ('dueField', 'date')]:
                if fields.get(tasks.get(role), {}).get('type') != kind: raise ValueError('db.boardTaskFields')
            opts = fields[tasks['statusField']].get('options', [])
            if tasks.get('initialStatus') not in opts or not tasks.get('completedStatuses') or any(v not in opts for v in tasks['completedStatuses']): raise ValueError('db.boardChooseStates')
        for view in data.get('views', []):
            if view.get('type') != 'leafloomBoard': continue
            if not isinstance(view.get('groupBy', {}), dict): raise ValueError('db.boardInvalid')
            key = view.get('groupBy', {}).get('property')
            if key and (fields.get(key, {}).get('type') != 'select' or fields[key].get('readonly')): raise ValueError('db.boardSelectField')
            board = view.get('leafloom', {}).get('board', {})
            if not isinstance(board, dict): raise ValueError('db.boardInvalid')
            for name in ('manualOrder', 'groupOrder', 'hiddenGroups', 'collapsedGroups'):
                values = board.get(name, [])
                if not isinstance(values, list) or any(not isinstance(v, str) for v in values) or len(values) != len(set(values)): raise ValueError('db.boardInvalid')
                if name == 'manualOrder':
                    for value in values:
                        if relative(value) != value or not value.endswith('.md'): raise ValueError('db.boardInvalid')

    def groups(self, config, view, rows):
        from vault_rag.databases import cell
        key = view.get('groupBy', {}).get('property')
        if not key: return []
        spec = config['fields'][key]; options = spec.get('options', [])
        values = {group_key(v): v for v in options if v != ''}
        counts = {}
        for row in rows:
            raw = cell(row, key); raw = None if raw in ('', None) else str(raw)
            encoded = group_key(raw); values.setdefault(encoded, raw); counts[encoded] = counts.get(encoded, 0) + 1
        order = {k: i for i, k in enumerate(view.get('leafloom', {}).get('board', {}).get('groupOrder', []))}
        groups = [{'key': k, 'value': value, 'count': counts.get(k, 0), 'configured': value in options or value is None,
                   **copy.deepcopy(spec.get('optionMeta', {}).get(value, {}))} for k, value in values.items()]
        groups.sort(key=lambda g: (order.get(g['key'], len(order)), g['value'] is None, g['value'] not in options,
                                   options.index(g['value']) if g['value'] in options else 0, str(g['value']).casefold()))
        return groups

    def ordered(self, rows, view):
        order = {p: i for i, p in enumerate(view.get('leafloom', {}).get('board', {}).get('manualOrder', []))}
        return sorted(rows, key=lambda row: (order.get(row['path'], len(order)), row['path']))

    def query(self, config, view, rows, version, search, group=None, cursor='', limit=100, anchor_path=''):
        from vault_rag.databases import cell
        if not 1 <= limit <= 200: raise ValueError('limit must be between 1 and 200')
        board = view.get('leafloom', {}).get('board', {})
        grouping = view.get('groupBy', {})
        if not isinstance(board, dict) or not isinstance(grouping, dict): raise ValueError('db.boardInvalid')
        if grouping.get('property') and config['fields'].get(grouping['property'], {}).get('type') != 'select': raise ValueError('db.boardSelectField')
        groups = self.groups(config, view, rows)
        common = {'ok': True, 'groups': groups, 'config_revision': config['revision'], 'catalog_version': version,
                  'workspace_revision': config['workspace_revision'], 'board_total': len(rows), 'needs_group': not view.get('groupBy', {}).get('property')}
        if group in (None, ''): return {**common, 'results': [], 'total': len(rows), 'next_cursor': None}
        selected = next((g for g in groups if g['key'] == group), None)
        if selected is None: raise ValueError('db.boardMissingGroup')
        subset = [row for row in rows if group_key(cell(row, view['groupBy']['property'])) == group]
        if not view.get('sort'): subset = self.ordered(subset, view)
        # On refresh, retain enough of the existing prefix to restore the scroll anchor.
        if anchor_path and not cursor:
            index = next((i for i, r in enumerate(subset) if r['path'] == anchor_path), -1)
            if index >= 0:
                # The regular cursor implementation pins all rows as well as the snapshot.
                key = [config['path'], config['revision'], version, view['leafloom']['id'], search, group]
                signature = digest(json.dumps([self.db.notes.workspace_revision, key, subset], ensure_ascii=False, sort_keys=True, default=str))
                offset = max(0, index - limit // 2)
                cursor = base64.urlsafe_b64encode(json.dumps([signature, offset]).encode()).decode()
        key = [config['path'], config['revision'], version, view['leafloom']['id'], search, group]
        page = self.db.notes.page(subset, limit, cursor, key=key)
        previous = None
        if cursor:
            signature, offset = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            if offset > 0: previous = base64.urlsafe_b64encode(json.dumps([signature, max(0, offset-limit)]).encode()).decode()
        return {**common, **page, 'group': selected, 'previous_cursor': previous}

    def _location(self, operation_id):
        if not isinstance(operation_id, str) or not re.fullmatch(r'[\w-]{1,128}', operation_id): raise ValueError('db.boardOperationId')
        return self.files.state_path('database-board-operations', digest(operation_id) + '.json')

    def _store(self, path, record):
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, json.dumps(record, ensure_ascii=False).encode())

    def _pending(self, operation_id):
        return self.files.state_path('database-board-pending', digest(operation_id) + '.json')

    def _current(self, entry):
        file = self.config.path_for(entry['path'], writable=True)
        return digest(file.read_bytes()) if file.is_file() else None

    def _rollback(self, record):
        conflicts = []
        for entry in reversed(record['files']):
            now = self._current(entry)
            if now == entry['before_hash']: continue
            if now != entry['after_hash']:
                conflicts.append(entry['path']); continue
            self.files.save(entry['path'], base64.b64decode(entry['before']).decode('utf-8-sig'), now, expected_root=record['root'])
        return conflicts

    def recover(self, database):
        # Scan only pending pointers, not the accumulated operation history.
        with self.config.lock, self.files.lock:
            directory = self.files.state_path('database-board-pending')
            if not directory.exists(): return
            for pointer in directory.glob('*.json'):
                pointer = self.files.state_path('database-board-pending', pointer.name)
                location = self._location(json.loads(pointer.read_text())['operation_id'])
                record = json.loads(location.read_text())
                if record.get('database') != database: continue
                if record.get('root') != str(self.config.root): raise ConflictError('db.boardRecoveryConflict')
                if record['state'] == 'committed': pointer.unlink(missing_ok=True); continue
                if all(self._current(e) == e['after_hash'] for e in record['files']):
                    record['state'] = 'committed'; self._store(location, record); pointer.unlink(missing_ok=True)
                    self.files.changed(*(e['path'] for e in record['files'])); continue
                conflicts = self._rollback(record)
                record['state'] = 'conflict' if conflicts else 'rolled_back'; self._store(location, record)
                if conflicts: raise ConflictError('db.boardRecoveryConflict')
                pointer.unlink(missing_ok=True)

    def replay(self, database, command, operation_id):
        location = self._location(operation_id)
        if not location.exists(): return None
        record = json.loads(location.read_text())
        signature = digest(json.dumps([database, command], sort_keys=True, ensure_ascii=False))
        if record.get('root') != str(self.config.root): raise ConflictError('db.boardConflict')
        if record['signature'] != signature: raise ConflictError('operation_id was used for another command')
        if record['state'] == 'committed': return self.result(record)
        if record['state'] == 'conflict': raise ConflictError('db.boardRecoveryConflict')
        return None

    def result(self, record):
        result = {**record['result'], 'undo_id': record['operation_id']}
        note = next((e for e in record['files'] if e['path'] != record['database']), None)
        if note and self._current(note) == note['after_hash']: result['note'] = self.files.read(note['path'])
        return result

    def transaction(self, database, command, operation_id, changes):
        entries = []
        for path, text, expected in changes:
            old = self.config.path_for(path, writable=True).read_bytes()
            if digest(old) != expected: raise ConflictError('db.boardConflict')
            after = serialized(text, old)
            if after == old: continue
            entries.append({'path': path, 'before': base64.b64encode(old).decode(), 'after': base64.b64encode(after).decode(),
                            'before_hash': expected, 'after_hash': digest(after)})
        config_revision = next((e['after_hash'] for e in entries if e['path'] == database), self.files.read(database)['etag'])
        record_revision = next((e['after_hash'] for e in entries if e['path'] != database), command.get('record_revision', ''))
        record = {'database': database, 'root': str(self.config.root), 'operation_id': operation_id, 'time': time.time(),
                  'signature': digest(json.dumps([database, command], sort_keys=True, ensure_ascii=False)), 'state': 'pending', 'files': entries,
                  'result': {'ok': True, 'changed': bool(entries), 'path': command.get('path', ''), 'config_revision': config_revision,
                             'record_revision': record_revision, 'workspace_revision': self.db.notes.workspace_revision}}
        location = self._location(operation_id); pointer = self._pending(operation_id)
        self._store(location, record); self._store(pointer, {'operation_id': operation_id})
        try:
            for entry in entries:
                result = self.files.save(entry['path'], base64.b64decode(entry['after']).decode('utf-8-sig'), entry['before_hash'], expected_root=record['root'])
                entry['history_id'] = result.get('history_id'); self._store(location, record)
            record['state'] = 'committed'; self._store(location, record); pointer.unlink(missing_ok=True)
        except Exception:
            conflicts = self._rollback(record)
            record['state'] = 'conflict' if conflicts else 'rolled_back'; self._store(location, record)
            if not conflicts: pointer.unlink(missing_ok=True)
            if conflicts: raise ConflictError('db.boardRecoveryConflict') from None
            raise
        return self.result(record)

    def set_group(self, data, command):
        view = self.db.view(data, command['view_id'])
        key = view.get('groupBy', {}).get('property')
        spec = self.db.fields(data).get(key, {})
        if view.get('type') != 'leafloomBoard' or spec.get('type') != 'select' or spec.get('readonly'):
            raise ValueError('db.boardSelectField')
        value = command['value']
        if not isinstance(value, str) or not value: raise ValueError('db.boardMissingGroup')
        field = data.setdefault('leafloom', {}).setdefault('fields', {}).setdefault(key, {})
        field['options'] = list(dict.fromkeys([*spec.get('options', []), value]))
        meta = field.setdefault('optionMeta', {}).setdefault(value, {})
        for name in ('label', 'color'):
            if name in command:
                if not isinstance(command[name], str): raise ValueError('db.invalidOption')
                meta[name] = command[name]

    def remove_group(self, database, data, yaml, value, command, operation_id):
        from vault_rag.databases import cell
        view = self.db.view(data, command['view_id'])
        key = view.get('groupBy', {}).get('property')
        if view.get('type') != 'leafloomBoard' or not key: raise ValueError('db.boardSelectField')
        config = self.db.config_read(database); spec = config['fields'].get(key, {})
        if spec.get('type') != 'select' or spec.get('readonly'): raise ValueError('db.boardSelectField')
        try: group = json.loads(command['group_key'])
        except (ValueError, TypeError): raise ValueError('db.boardMissingGroup') from None
        if not isinstance(group, str) or not group: raise ValueError('db.boardMissingGroup')
        # Removing an option affects every record in the database, including rows
        # excluded by the current view, search, hidden columns or loaded pages.
        rows, version = self.db.query_rows(config, {})
        affected = sorted((r for r in rows if group_key(cell(r, key)) == group_key(group)), key=lambda r: r['path'])
        if group not in spec.get('options', []) and not affected: raise ValueError('db.boardUnknownGroup')
        records = [{'path': r['path'], 'revision': r['revision']} for r in affected]
        if command.get('dry_run'):
            return {'ok': True, 'dry_run': True, 'records': records, 'count': len(records),
                    'config_revision': value['etag'], 'catalog_version': version, 'workspace_revision': config['workspace_revision']}
        if command.get('catalog_version') != version or command.get('records') != records: raise ConflictError('db.boardConflict')
        target = command.get('target_value')
        if target is not None and (not isinstance(target, str) or target == group or target not in spec.get('options', [])):
            raise ValueError('db.boardUnknownGroup')
        task = data.get('leafloom', {}).get('tasks')
        if task and task['statusField'] == key:
            if task['initialStatus'] == group:
                if target is None: raise ValueError('db.deleteGroupTaskTarget')
                task['initialStatus'] = target
            if group in task['completedStatuses']:
                completed = [v for v in task['completedStatuses'] if v != group]
                if target is not None and target not in completed: completed.append(target)
                if not completed: raise ValueError('db.deleteGroupTaskTarget')
                task['completedStatuses'] = completed
        field = data.setdefault('leafloom', {}).setdefault('fields', {}).setdefault(key, {})
        field['options'] = [v for v in spec.get('options', []) if v != group]
        field.get('optionMeta', {}).pop(group, None)
        encoded = group_key(group)
        for item in data.get('views', []):
            if item.get('type') != 'leafloomBoard' or item.get('groupBy', {}).get('property') != key: continue
            board = item.get('leafloom', {}).get('board', {})
            for name in ('groupOrder', 'hiddenGroups', 'collapsedGroups'):
                if name in board: board[name] = [v for v in board[name] if v != encoded]
            # Migrated records must remain discoverable even if the destination
            # column was previously hidden or collapsed in another board.
            if records:
                for name in ('hiddenGroups', 'collapsedGroups'):
                    if name in board: board[name] = [v for v in board[name] if v != group_key(target)]
        self.db.validate_config(data)
        changes = []
        for row in affected:
            note = self.files.read(row['path'])
            if note['etag'] != row['revision']: raise ConflictError('db.boardConflict')
            updates = self.db.validate_values(data, {key: target}, note['metadata'])
            changes.append((row['path'], property_text(note['text'], updates), note['etag']))
        out = io.StringIO(); yaml.dump(data, out)
        changes.append((database, out.getvalue(), value['etag']))
        result = self.transaction(database, command, operation_id, changes)
        self.db.remember_document(database, result['config_revision'], data, yaml)
        return result

    def move(self, database, data, yaml, value, command, operation_id):
        from vault_rag.databases import cell
        view = self.db.view(data, command.get('view_id'))
        if view.get('type') != 'leafloomBoard' or not view.get('groupBy', {}).get('property'): raise ValueError('db.boardSelectField')
        target = relative(command['path']); folder = data.get('leafloom', {}).get('folder')
        if not target.endswith('.md') or (folder is not None and not under(target, folder)): raise ValueError('Record is outside the database folder')
        note = self.files.read(target)
        if note['etag'] != command.get('record_revision'): raise ConflictError('db.boardConflict')
        config = self.db.config_read(database)
        rows, version = self.db.query_rows(config, view, command.get('search', ''))
        if command.get('catalog_version') != version: raise ConflictError('db.boardConflict')
        row = next((r for r in rows if r['path'] == target), None)
        if not row or row['revision'] != note['etag']: raise ConflictError('db.boardConflict')
        key = view['groupBy']['property']; spec = config['fields'][key]
        try: group = json.loads(command['group_key'])
        except (ValueError, TypeError, KeyError): raise ValueError('db.boardMissingGroup') from None
        if group is not None and (not isinstance(group, str) or group not in spec.get('options', [])): raise ValueError('db.boardUnknownGroup')
        cross = group_key(cell(row, key)) != group_key(group)
        if not cross and view.get('sort'): raise ValueError('db.boardAutoOrder')
        before, after = command.get('before_path'), command.get('after_path')
        if before and after: raise ValueError('Choose one neighboring record')
        anchor = before or after
        if anchor and (view.get('sort') or anchor == target or not any(r['path'] == anchor and group_key(cell(r, key)) == group_key(group) for r in rows)):
            raise ConflictError('db.boardConflict')
        if anchor:
            neighbor = next(r for r in rows if r['path'] == anchor)
            if self.files.read(anchor)['etag'] != neighbor['revision']: raise ConflictError('db.boardConflict')
        all_rows, _ = self.db.query_rows(config, view, '')
        board = view.setdefault('leafloom', {}).setdefault('board', {})
        ordered = list(dict.fromkeys([*board.get('manualOrder', []), *[r['path'] for r in self.ordered(all_rows, view)], target]))
        ordered.remove(target)
        if anchor:
            position = ordered.index(anchor) + (1 if after else 0)
        else:
            members = {r['path'] for r in all_rows if group_key(cell(r, key)) == group_key(group)}
            positions = [i for i, p in enumerate(ordered) if p in members]
            position = positions[-1] + 1 if positions else len(ordered)
        ordered.insert(position, target); board['manualOrder'] = ordered
        self.db.validate_config(data)
        out = io.StringIO(); yaml.dump(data, out)
        changes = []
        if cross:
            updates = self.db.validate_values(data, {key: group}, note['metadata'])
            changes.append((target, property_text(note['text'], updates), note['etag']))
        changes.append((database, out.getvalue(), value['etag']))
        result = self.transaction(database, command, operation_id, changes)
        self.db.remember_document(database, result['config_revision'], data, yaml)
        return result

    def undo(self, database, command, operation_id):
        source = json.loads(self._location(command.get('move_id')).read_text())
        if source.get('database') != database or source.get('root') != str(self.config.root) or source['state'] != 'committed': raise ConflictError('db.boardConflict')
        changes = []
        for entry in source['files']:
            if self._current(entry) != entry['after_hash']: raise ConflictError('db.boardConflict')
            changes.append((entry['path'], base64.b64decode(entry['before']).decode('utf-8-sig'), entry['after_hash']))
        return self.transaction(database, command, operation_id, changes)


def rename_board_references(text, mapping):
    yaml = YAML(); yaml.preserve_quotes = True
    from ruamel.yaml.error import YAMLError
    try: data = yaml.load(text)
    except YAMLError: return text
    if not isinstance(data, dict): return text
    changed = False
    for view in data.get('views', []):
        if not isinstance(view, dict) or view.get('type') != 'leafloomBoard': continue
        board = view.get('leafloom', {}).get('board', {})
        if not isinstance(board, dict): continue
        previous = board.get('manualOrder', [])
        if not isinstance(previous, list) or any(not isinstance(path, str) for path in previous): continue
        updated = [mapping.get(path, path) for path in previous]
        if updated != previous: board['manualOrder'] = updated; changed = True
    if not changed: return text
    out = io.StringIO(); yaml.dump(data, out); return out.getvalue()
