"""Versioned, recoverable structured documents for the visual Design Studio.

The JSON document is portable user content. SQLite stores reversible differences,
checkpoints and request receipts in the vault's private directory. A durable pending
commit bridges SQLite and atomic file replacement, including process interruption.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import math
import mimetypes
from pathlib import Path
import sqlite3
import time
import uuid
from collections import OrderedDict
from typing import Any

from vault_rag.local_state import ConflictError, atomic_write, relative
from vault_rag.design_references import AssetReferences, rewrite_script


DOCUMENT_PATH = 'Design/studio/project.json'
NODE_TYPES = {'container', 'text', 'image', 'button', 'shape', 'svg', 'html', 'page', 'instance', 'element'}
MAX_DOCUMENT_BYTES = 32 * 1024 * 1024
MAX_ASSET_BYTES = 128 * 1024 * 1024
STYLE_KINDS = {'color', 'typography', 'spacing'}
STYLE_KEYS = {
    'color': {'color', 'background', 'backgroundColor', 'backgroundImage', 'borderColor', 'fill', 'stroke'},
    'typography': {'font', 'fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'lineHeight', 'letterSpacing',
                   'textTransform', 'textDecoration', 'textAlign', 'wordSpacing'},
    'spacing': {'padding', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'gap', 'rowGap', 'columnGap', 'borderRadius'},
}


def style_ids(node):
    """Legacy single style first, then ordered independently linked styles."""
    props = node.get('props', {})
    return list(dict.fromkeys(([props['styleId']] if props.get('styleId') else []) + props.get('styleIds', [])))


def resolve_style(document, node):
    result = {}
    for key in style_ids(node):
        shared = document.get('styles', {}).get(key, {})
        result.update(shared.get('style', shared))
    result.update(node.get('style', {}))
    return copy.deepcopy(result)


def component_overrides(component, instance):
    """Normalize the original flat root-props form without losing user content."""
    overrides = copy.deepcopy(instance.get('props', {}).get('overrides', {}))
    if not isinstance(overrides, dict):
        raise ValueError('Component overrides must be an object')
    known = {node['id'] for node in _walk([component['node']])}
    keyed = any(key in known for key in overrides) or all(
        isinstance(value, dict) and set(value) <= {'style', 'props'} for value in overrides.values())
    return overrides if keyed else {component['node']['id']: {'props': overrides}}


def _id() -> str:
    return uuid.uuid4().hex


def _json(value: Any) -> bytes:
    try:
        result = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError('Design documents must contain finite JSON values') from exc
    if len(result) > MAX_DOCUMENT_BYTES:
        raise ValueError('Design document exceeds 32 MiB; split large source or media into assets')
    return result


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _diff(before: Any, after: Any, path: list | None = None) -> tuple[list, list]:
    """Paired JSON deltas; an insertion stores only the changed list segment."""
    path = path or []
    if before == after:
        return [], []
    forward, inverse = [], []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in before.keys() - after.keys():
            forward.append({'op': 'delete', 'path': path + [key]})
            inverse.insert(0, {'op': 'set', 'path': path + [key], 'value': before[key]})
        for key in after.keys() - before.keys():
            forward.append({'op': 'set', 'path': path + [key], 'value': after[key]})
            inverse.insert(0, {'op': 'delete', 'path': path + [key]})
        for key in before.keys() & after.keys():
            fwd, inv = _diff(before[key], after[key], path + [key])
            forward.extend(fwd)
            inverse = inv + inverse
        return forward, inverse
    if isinstance(before, list) and isinstance(after, list):
        if len(before) == len(after):
            for index, (old, new) in enumerate(zip(before, after)):
                fwd, inv = _diff(old, new, path + [index])
                forward.extend(fwd)
                inverse = inv + inverse
            return forward, inverse
        start = 0
        while start < min(len(before), len(after)) and before[start] == after[start]:
            start += 1
        tail = 0
        while tail < min(len(before), len(after)) - start and before[-tail - 1] == after[-tail - 1]:
            tail += 1
        old_end, new_end = len(before) - tail, len(after) - tail
        return ([{'op': 'splice', 'path': path, 'index': start, 'count': old_end - start, 'values': after[start:new_end]}],
                [{'op': 'splice', 'path': path, 'index': start, 'count': new_end - start, 'values': before[start:old_end]}])
    return ([{'op': 'set', 'path': path, 'value': after}], [{'op': 'set', 'path': path, 'value': before}])


def _patch(document: dict, operations: list) -> dict:
    result = copy.deepcopy(document)
    for item in operations:
        path = item['path']
        if not path and item['op'] == 'set':
            result = copy.deepcopy(item['value'])
            continue
        target = result
        for key in path[:-1] if item['op'] != 'splice' else path:
            target = target[key]
        if item['op'] == 'splice':
            index = item['index']
            target[index:index + item['count']] = copy.deepcopy(item['values'])
        elif item['op'] == 'delete':
            del target[path[-1]]
        else:
            target[path[-1]] = copy.deepcopy(item['value'])
    return result


def _walk(nodes: list):
    for node in nodes:
        yield node
        yield from _walk(node.get('children', []))


def validate_page_contexts(pages: list, edges: dict | None = None) -> dict:
    """Validate ordinary pages used as context-dependent visual variants.

    The forward pageId is a render dependency. contextSource only records the
    corresponding ownership; it must not create a second, reverse embed edge.
    """
    indexed = {page['id']: page for page in pages}
    owners = {}

    def context_key(context):
        if not isinstance(context, dict) or not 1 <= len(context) <= 16:
            raise ValueError('Page variant context requires 1 to 16 scalar fields')
        normalized = {}
        for key, value in context.items():
            if not isinstance(key, str) or not key or len(key) > 64:
                raise ValueError('Page variant context keys must contain 1 to 64 characters')
            if isinstance(value, str):
                valid = len(value) <= 200
            elif value is None or isinstance(value, bool):
                valid = True
            elif isinstance(value, (int, float)):
                valid = abs(value) <= 10 ** 15 and math.isfinite(value)
                if valid and isinstance(value, float) and value.is_integer():
                    value = int(value)
            else:
                valid = False
            if not valid:
                raise ValueError('Page variant context values must be bounded plain scalars')
            normalized[key] = value
        return json.dumps(normalized, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))

    for page in pages:
        metadata = page.get('migration', {})
        if not isinstance(metadata, dict):
            raise ValueError('Page migration metadata must be an object')
        if 'contextVariants' not in metadata:
            continue
        variants = metadata['contextVariants']
        if not isinstance(variants, list) or len(variants) > 32:
            raise ValueError('Page contextVariants must contain at most 32 entries')
        if 'contextSource' in metadata:
            raise ValueError('Context variant pages cannot declare further variants')
        contexts = set()
        for variant in variants:
            if not isinstance(variant, dict):
                raise ValueError('Page context variant must be an object')
            key = context_key(variant.get('context'))
            target_id = variant.get('pageId')
            if not isinstance(target_id, str) or target_id not in indexed:
                raise ValueError('Page is referenced by a context variant route; remove its owning page contextVariants entry before deleting it')
            if target_id == page['id']:
                raise ValueError('Page context variant must reference another existing page')
            if key in contexts or target_id in owners:
                raise ValueError('Page context variants require distinct contexts and a single owning page')
            contexts.add(key)
            target = indexed[target_id].get('migration', {})
            source = target.get('contextSource') if isinstance(target, dict) else None
            if not isinstance(source, dict) or source.get('pageId') != page['id'] or context_key(source.get('context')) != key:
                raise ValueError('Page context variant and contextSource must agree')
            if 'contextVariants' in target:
                raise ValueError('Context variant pages cannot declare further variants')
            owners[target_id] = page['id']
            if edges is not None:
                edges['p:' + page['id']].add('p:' + target_id)
    for page in pages:
        metadata = page.get('migration', {})
        if 'contextSource' in metadata:
            source = metadata['contextSource']
            if not isinstance(source, dict) or owners.get(page['id']) != source.get('pageId'):
                raise ValueError('Page contextSource requires a matching declaration on its owning page')
    return owners


def _find(nodes: list, node_id: str):
    for index, node in enumerate(nodes):
        if node['id'] == node_id:
            return nodes, index, node
        found = _find(node.get('children', []), node_id)
        if found:
            return found
    return None


def _merge(target: dict, patch: dict, *, immutable: tuple = ('id',)) -> None:
    if not isinstance(patch, dict):
        raise ValueError('patch must be an object')
    if any(key in patch for key in immutable):
        raise ValueError('Stable identity and managed children cannot be overwritten by a property patch')
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif key in ('style', 'props', 'script', 'animation') and isinstance(value, dict):
            current = target.setdefault(key, {})
            if not isinstance(current, dict):
                current = target[key] = {}
            for name, prop in value.items():
                if prop is None:
                    current.pop(name, None)
                else:
                    current[name] = copy.deepcopy(prop)
        else:
            target[key] = copy.deepcopy(value)


def _remap_script(binding, mapping):
    if isinstance(binding, dict) and isinstance(binding.get('source'), str):
        binding['source'] = rewrite_script(binding['source'], lambda kind, value: mapping.get(value) if kind == 'node' else None)


def _fresh_node(node: dict, mapping: dict | None = None, *, root_id: str | None = None) -> dict:
    result = copy.deepcopy(node)
    if mapping is None:
        mapping = {item.get('id'): _id() for item in _walk([result])}
    if root_id is not None:
        mapping[result['id']] = root_id
    for item in _walk([result]):
        item['id'] = mapping[item.get('id')]
        # Only typed element fields and literal runtime helper calls are owned
        # references. Comments and unrelated JavaScript strings stay intact.
        for key in ('targetId', 'nodeId'):
            if item.get('props', {}).get(key) in mapping:
                item['props'][key] = mapping[item['props'][key]]
        _remap_script(item.get('script'), mapping)
    return result


class DesignDocuments:
    def __init__(self, studio):
        self.studio = studio
        self.config, self.runtime, self.files = studio.config, studio.runtime, studio.files
        self._parsed = OrderedDict()
        self._view_indexes = OrderedDict()

    def _cached_document(self, path, project=None):
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        key = str(path)
        cached = self._parsed.get(key)
        if cached is not None and cached['signature'] == signature:
            self._parsed.move_to_end(key)
            return cached
        if stat.st_size > MAX_DOCUMENT_BYTES:
            raise ValueError('Design document exceeds 32 MiB')
        raw = path.read_bytes()
        after_stat = path.stat()
        if signature != (after_stat.st_mtime_ns, after_stat.st_size, after_stat.st_ino):
            raise ConflictError('Design document changed while being read; retry with a stable version')
        document = json.loads(raw)
        self.validate(document, project or path.parents[2])
        return self._remember(path, document, raw, signature)

    def _remember(self, path, document, raw, signature):
        value = {'signature': signature,
                 'document': document, 'hash': _hash(raw), 'size': len(raw)}
        self._parsed[str(path)] = value
        self._parsed.move_to_end(str(path))
        # Avoid retaining every opened game's full tree. One large active
        # document is allowed, while other entries share a 32 MiB raw-size budget.
        while len(self._parsed) > 1 and (len(self._parsed) > 8 or sum(item['size'] for item in self._parsed.values()) > MAX_DOCUMENT_BYTES):
            self._parsed.popitem(last=False)
        return value

    @property
    def workspace_revision(self):
        return self.config.data.get('revision', '')

    def _paths(self, directory: str):
        directory = relative(directory)
        if not directory:
            raise ValueError('Managed projects require a project subdirectory')
        project = self.config.path_for(directory, writable=True)
        if not project.is_dir():
            raise FileNotFoundError(directory)
        path = self.config.path_for(f'{directory}/{DOCUMENT_PATH}', writable=True)
        return directory, project, path

    def _database(self, document_id: str):
        if not isinstance(document_id, str) or not document_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in document_id):
            raise ValueError('Invalid project document ID')
        state = self.files.state_path('design-studio', document_id)
        state.mkdir(parents=True, exist_ok=True)
        db_path = self.files.state_path('design-studio', document_id, 'history.sqlite3')
        self.files.state_path('design-studio', document_id, 'history.sqlite3-journal')
        self.files.state_path('design-studio', document_id, 'history.sqlite3-wal')
        self.files.state_path('design-studio', document_id, 'history.sqlite3-shm')
        # State path validation also rejects a malicious pre-existing database link.
        db = sqlite3.connect(db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=DELETE')
        db.execute('PRAGMA synchronous=FULL')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS meta (id INTEGER PRIMARY KEY CHECK(id=1), revision TEXT NOT NULL,
                content_hash TEXT NOT NULL, cursor INTEGER NOT NULL, owner TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS operations (seq INTEGER PRIMARY KEY AUTOINCREMENT,
                parent INTEGER NOT NULL, label TEXT NOT NULL, created REAL NOT NULL,
                forward TEXT NOT NULL, inverse TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
            CREATE INDEX IF NOT EXISTS operations_branch ON operations(active,parent);
            CREATE TABLE IF NOT EXISTS receipts (operation_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                revision TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS checkpoints (seq INTEGER PRIMARY KEY, document BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS pending (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
        ''')
        return db

    def _load(self, directory: str):
        directory, project, path = self._paths(directory)
        if not path.is_file():
            raise FileNotFoundError(f'No managed design document in {directory}')
        cached = self._cached_document(path, project)
        document = cached['document']
        db = self._database(document['id'])
        try:
            meta = db.execute('SELECT * FROM meta WHERE id=1').fetchone()
            owner = str(self.config.root) + '\n' + directory
            if meta is None:
                with db:
                    db.execute('INSERT INTO meta VALUES (1,?,?,0,?)', (_id(), cached['hash'], owner))
                    db.execute('INSERT INTO checkpoints VALUES (0,?)', (path.read_bytes(),))
            elif meta['owner'] != owner:
                raise ConflictError('Project identity belongs to another directory; duplicate with a new document ID')
            self._recover(db, path)
            cached = self._cached_document(path, project)
            meta = db.execute('SELECT * FROM meta WHERE id=1').fetchone()
            if cached['hash'] != meta['content_hash']:
                raise ConflictError('Design document changed outside the studio; history and external file are preserved; reload and reconcile before writing')
            return directory, project, path, cached['document'], db, meta
        except BaseException:
            db.close()
            raise

    def _recover(self, db, path):
        # Hold the database write reservation across the file replacement. This
        # also serializes recovery performed by a second service process.
        db.execute('BEGIN IMMEDIATE')
        try:
            pending = db.execute('SELECT payload FROM pending WHERE id=1').fetchone()
            if pending is None:
                db.commit()
                return
            record = json.loads(pending['payload'])
            raw = path.read_bytes()
            current_hash = _hash(raw)
            if current_hash == record['before_hash']:
                atomic_write(path, record['after'].encode('utf-8'))
            elif current_hash != record['after_hash']:
                raise ConflictError('Interrupted design save conflicts with an external edit; pending recovery and user file were preserved')
            self._finish(db, record)
        except BaseException:
            db.rollback()
            raise

    def _finish(self, db, record):
        with db:
            cursor = record['cursor']
            if record['action'] == 'apply':
                db.execute('UPDATE operations SET active=0 WHERE active=1 AND seq>?', (cursor,))
                insert = db.execute('INSERT INTO operations(parent,label,created,forward,inverse) VALUES(?,?,?,?,?)',
                                    (cursor, record['label'], record['created'], json.dumps(record['forward']), json.dumps(record['inverse'])))
                cursor = insert.lastrowid
                if cursor % 50 == 0:
                    db.execute('INSERT OR REPLACE INTO checkpoints VALUES (?,?)', (cursor, record['after'].encode('utf-8')))
            db.execute('UPDATE meta SET revision=?,content_hash=?,cursor=? WHERE id=1',
                       (record['revision'], record['after_hash'], cursor))
            db.execute('INSERT INTO receipts VALUES(?,?,?)', (record['operation_id'], record['fingerprint'], record['revision']))
            db.execute('DELETE FROM pending WHERE id=1')

    def _commit(self, db, path, before: dict, after: dict, meta, operation_id: str, fingerprint: str,
                label: str, *, action='apply', cursor=None):
        forward, inverse = _diff(before, after)
        raw = _json(after)
        record = {'action': action, 'cursor': meta['cursor'] if cursor is None else cursor,
                  'revision': _id(), 'before_hash': meta['content_hash'], 'after_hash': _hash(raw),
                  'after': raw.decode('utf-8'), 'forward': forward, 'inverse': inverse,
                  'label': label, 'created': time.time(), 'operation_id': operation_id, 'fingerprint': fingerprint}
        db.execute('BEGIN IMMEDIATE')
        try:
            current = db.execute('SELECT revision FROM meta WHERE id=1').fetchone()
            if current['revision'] != meta['revision'] or db.execute('SELECT id FROM pending WHERE id=1').fetchone():
                raise ConflictError('Another design save is in progress or has completed; refresh before retrying')
            if _hash(path.read_bytes()) != meta['content_hash']:
                raise ConflictError('Design document changed during save; user content was not overwritten')
            db.execute('INSERT INTO pending VALUES(1,?)', (json.dumps(record, ensure_ascii=False),))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        self._recover(db, path)

    def _history_state(self, db, cursor):
        undo = db.execute('SELECT label FROM operations WHERE seq=? AND active=1', (cursor,)).fetchone()
        redo = db.execute('SELECT label FROM operations WHERE parent=? AND active=1 ORDER BY seq LIMIT 1', (cursor,)).fetchone()
        return {'can_undo': undo is not None, 'can_redo': redo is not None,
                'undo_label': undo['label'] if undo else '', 'redo_label': redo['label'] if redo else ''}

    def _result(self, directory, path, db, *, replayed=False, operation_revision=None, include_document=True):
        meta = db.execute('SELECT * FROM meta WHERE id=1').fetchone()
        result = {'ok': True, 'directory': directory,
                  'revision': meta['revision'], 'workspace_revision': self.workspace_revision,
                  'history': self._history_state(db, meta['cursor'])}
        if include_document:
            cached = self._cached_document(path)
            if cached['hash'] != meta['content_hash']:
                raise ConflictError('Design document changed externally; the save receipt and external content were preserved')
            result['document'] = copy.deepcopy(cached['document'])
        if replayed:
            result.update(replayed=True, operation_revision=operation_revision)
        return result

    def _receipt(self, db, operation_id, fingerprint):
        if not isinstance(operation_id, str) or not operation_id.strip() or len(operation_id) > 200:
            raise ValueError('A nonempty operation_id of at most 200 characters is required')
        row = db.execute('SELECT * FROM receipts WHERE operation_id=?', (operation_id,)).fetchone()
        if row and row['fingerprint'] != fingerprint:
            raise ConflictError('operation_id was already used for a different operation')
        return row

    def _revision(self, meta, expected_revision):
        if expected_revision is None or str(expected_revision) != meta['revision']:
            raise ConflictError('Design revision changed; read the current document and retry without overwriting newer changes')

    def create(self, directory: str, name: str, width=720, height=1560, *, initial_document=None):
        with self.config.lock, self.files.lock:
            directory, project, path = self._paths(directory)
            if path.exists():
                raise ConflictError('A managed design document already exists in this project')
            document = {'schemaVersion': 1, 'id': _id(), 'name': str(name).strip() or project.name,
                        'pages': [{'id': _id(), 'name': 'Home', 'group': '', 'width': width, 'height': height, 'nodes': []}],
                        'assets': {}, 'components': {}, 'styles': {}, 'scripts': {}}
            if initial_document is not None:
                document = copy.deepcopy(initial_document)
                document['id'] = _id()
                document['name'] = str(name).strip() or project.name
            self.validate(document, project)
            atomic_write(path, _json(document))
            self._changed(directory, path)
            return self.read(directory)

    def read(self, directory: str, page_id: str | None = None):
        with self.config.lock, self.files.lock:
            directory, _, path, document, db, _ = self._load(directory)
            try:
                result = self._result(directory, path, db)
                if page_id is not None:
                    result['page'] = self._page(result['document'], page_id)
                return result
            finally:
                db.close()

    def manifest(self, directory: str):
        with self.config.lock, self.files.lock:
            directory, _, path, document, db, _ = self._load(directory)
            try:
                result = self._result(directory, path, db, include_document=False)
                result['manifest'] = {key: copy.deepcopy(document[key]) for key in ('schemaVersion', 'id', 'name', 'assets', 'styles')}
                result['manifest']['pages'] = [{key: copy.deepcopy(value) for key, value in page.items() if key not in ('nodes', 'css', 'script')} |
                                               {'node_count': sum(1 for _ in _walk(page['nodes']))} for page in document['pages']]
                result['manifest']['components'] = {key: {name: copy.deepcopy(value) for name, value in component.items() if name != 'node'} for key, component in document['components'].items()}
                result['manifest']['scripts'] = {key: {name: copy.deepcopy(value) for name, value in script.items() if name != 'source'} if isinstance(script, dict) else {'id': key} for key, script in document['scripts'].items()}
                return result
            finally:
                db.close()

    def _view_index(self, document, revision):
        key = (document['id'], revision)
        cached = self._view_indexes.get(key)
        if cached is not None:
            self._view_indexes.move_to_end(key)
            return cached
        references = {asset_id: [] for asset_id in document['assets']}
        asset_index = AssetReferences(document['assets'])
        node_counts, dependencies, component_dependencies = {}, {}, {}

        def asset_ids(node, base_path=''):
            return asset_index.process({key: value for key, value in node.items() if key != 'children'}, base_path=base_path)[0]

        def inspect(nodes, page_id, page_name, component_id=None, base_path=''):
            found_pages, found_components, count = set(), set(), 0
            def override_dependencies(component, instance, depth=0):
                if depth > 100:
                    return
                targets = {item['id']: item for item in _walk([component['node']])}
                for target_id, patch in component_overrides(component, instance).items():
                    if not isinstance(patch, dict) or not isinstance(patch.get('props'), dict):
                        continue
                    props = patch['props']
                    if props.get('pageId'):
                        found_pages.add(props['pageId'])
                    if props.get('componentId'):
                        found_components.add(props['componentId'])
                    effective = {**targets.get(target_id, {}).get('props', {}), **props}
                    nested = document['components'].get(effective.get('componentId'))
                    if nested and isinstance(effective.get('overrides'), dict):
                        override_dependencies(nested, {'props': effective}, depth + 1)
            for node in _walk(nodes):
                count += 1
                props = node.get('props', {})
                if node['type'] == 'page' and props.get('pageId'):
                    found_pages.add(props['pageId'])
                if node['type'] == 'instance' and props.get('componentId'):
                    found_components.add(props['componentId'])
                    component = document['components'].get(props['componentId'])
                    if component:
                        override_dependencies(component, node)
                reference = {'page_id': page_id, 'page_name': page_name, 'node_id': node['id'], 'node_name': node.get('name') or node['id']}
                if component_id is not None:
                    reference['component_id'] = component_id
                for asset_id in asset_ids(node, base_path):
                    references[asset_id].append(dict(reference))
            return count, found_pages, found_components

        for component_id, component in document['components'].items():
            _, embedded, nested = inspect([component['node']], '', component.get('name', component_id), component_id)
            component_dependencies[component_id] = (embedded, nested)

        def component_pages(component_ids, visited=None):
            visited = set() if visited is None else visited
            result = set()
            for component_id in component_ids:
                if component_id in visited or component_id not in component_dependencies:
                    continue
                visited.add(component_id)
                embedded, nested = component_dependencies[component_id]
                result.update(embedded)
                result.update(component_pages(nested, visited))
            return result

        for page in document['pages']:
            count, embedded, components = inspect(page['nodes'], page['id'], page.get('name', page['id']), base_path=page.get('basePath', ''))
            node_counts[page['id']] = count
            contextual = {variant['pageId'] for variant in page.get('migration', {}).get('contextVariants', [])}
            dependencies[page['id']] = embedded | component_pages(components) | contextual
            for asset_id in asset_index.process({key: value for key, value in page.items() if key != 'nodes'}, base_path=page.get('basePath', ''))[0]:
                references[asset_id].append({'page_id': page['id'], 'page_name': page.get('name', page['id']), 'node_id': '', 'node_name': page.get('name', page['id'])})
        for table, context in (('scripts', 'script'), ('styles', 'style')):
            for resource_id, resource in document[table].items():
                for asset_id in asset_index.process(resource, context=context)[0]:
                    name = resource.get('name', resource_id) if isinstance(resource, dict) else resource_id
                    references[asset_id].append({'page_id': '', 'page_name': name, 'node_id': resource_id, 'node_name': name})
        index = {'references': references, 'node_counts': node_counts, 'dependencies': dependencies}
        self._view_indexes[key] = index
        self._view_indexes.move_to_end(key)
        while len(self._view_indexes) > 8:
            self._view_indexes.popitem(last=False)
        return index

    def project_view(self, result: dict, page_id: str | None = None):
        with self.config.lock, self.files.lock:
            return self._project_view(result, page_id)

    def _project_view(self, result: dict, page_id: str | None = None):
        """Project a canonical response for a client; never persist this shape.

        Inactive page source is omitted. Their metadata, original node counts
        and asset usage remain available without loading every page's tree.
        """
        document = result.get('document')
        if not isinstance(document, dict):
            raise ValueError('A full canonical document response is required for a page view')
        pages = {page['id']: page for page in document['pages']}
        selected = page_id if page_id in pages else document['pages'][0]['id']
        revision = result.get('revision')
        index = self._view_index(document, revision if revision is not None else _hash(_json(document)))
        loaded, pending = set(), [selected]
        while pending:
            current = pending.pop()
            if current in loaded or current not in pages:
                continue
            loaded.add(current)
            pending.extend(index['dependencies'].get(current, ()))
        projected = {key: copy.deepcopy(value) for key, value in document.items() if key != 'pages'}
        projected['pages'] = []
        for page in document['pages']:
            include = page['id'] in loaded
            value = {key: copy.deepcopy(child) for key, child in page.items() if key not in ('nodes', 'loaded', 'node_count') and (include or key not in ('css', 'script'))}
            value.update(nodes=copy.deepcopy(page['nodes']) if include else [], loaded=include, node_count=index['node_counts'][page['id']])
            projected['pages'].append(value)
        for asset_id, asset in projected['assets'].items():
            asset['references'] = copy.deepcopy(index['references'].get(asset_id, []))
        value = {key: copy.deepcopy(child) for key, child in result.items() if key not in ('document', 'page')}
        value.update(document=projected, view_page_id=selected)
        if 'page' in result:
            value['page'] = next(page for page in projected['pages'] if page['id'] == selected)
        return value

    def page_view(self, directory: str, page_id: str | None = None):
        with self.config.lock, self.files.lock:
            directory, _, path, document, db, _ = self._load(directory)
            try:
                result = self._result(directory, path, db, include_document=False)
                result['document'] = document
                return self.project_view(result, page_id)
            finally:
                db.close()

    def relocate(self, old_directory: str, new_directory: str):
        """Rebind history after a verified project move performed by the workspace."""
        with self.config.lock, self.files.lock:
            old_directory = relative(old_directory)
            directory = relative(new_directory)
            private = directory.startswith('.vault-rag/design-studio/workspace-trash/')
            if private:
                parts = Path(directory).parts[1:]
                project = self.files.state_path(*parts)
                path = self.files.state_path(*parts, 'Design', 'studio', 'project.json')
            else:
                directory, project, path = self._paths(directory)
            document = json.loads(path.read_bytes())
            self.validate(document, None if private else project)
            db = self._database(document['id'])
            try:
                row = db.execute('SELECT owner FROM meta WHERE id=1').fetchone()
                old_owner = str(self.config.root) + '\n' + old_directory
                new_owner = str(self.config.root) + '\n' + directory
                if row is not None and row['owner'] not in (old_owner, new_owner):
                    raise ConflictError('Project history belongs to a different directory')
                self._recover(db, path)
                with db:
                    db.execute('UPDATE meta SET owner=? WHERE id=1', (new_owner,))
            finally:
                db.close()
            return {'ok': True, 'directory': directory} if private else self.read(directory)

    def replay(self, directory, operation_id, request_identity):
        """Internal adapters may recover a receipt before rebuilding derived commands."""
        with self.config.lock, self.files.lock:
            directory, _, path, _, db, _ = self._load(directory)
            try:
                fingerprint = _hash(_json({'request_identity': request_identity}))
                receipt = self._receipt(db, operation_id, fingerprint)
                return self._result(directory, path, db, replayed=True, operation_revision=receipt['revision']) if receipt else None
            finally:
                db.close()

    def apply(self, directory: str, commands: list, expected_revision, operation_id: str, label='', workspace_revision=None, *, request_identity=None):
        with self.config.lock, self.files.lock:
            if workspace_revision is not None and workspace_revision != self.workspace_revision:
                raise ConflictError('Workspace changed; read the current workspace before applying design edits')
            if not isinstance(commands, list) or not commands or len(commands) > 10000:
                raise ValueError('commands must be a nonempty list of at most 10000 operations')
            fingerprint = _hash(_json({'request_identity': request_identity} if request_identity is not None else {'commands': commands, 'label': label}))
            directory, project, path, document, db, meta = self._load(directory)
            try:
                receipt = self._receipt(db, operation_id, fingerprint)
                if receipt:
                    return self._result(directory, path, db, replayed=True, operation_revision=receipt['revision'])
                self._revision(meta, expected_revision)
                after = copy.deepcopy(document)
                try:
                    for command in commands:
                        self._command(after, command)
                except (KeyError, TypeError, AttributeError) as exc:
                    raise ValueError('Malformed design command: missing or invalid arguments') from exc
                self.validate(after, project)
                self._commit(db, path, document, after, meta, operation_id, fingerprint, str(label or commands[0].get('type', 'Edit')))
                self._changed(directory, path)
                return self._result(directory, path, db)
            finally:
                db.close()

    def history(self, directory: str, action='list', expected_revision=None, operation_id=None, offset=0, limit=50):
        with self.config.lock, self.files.lock:
            directory, project, path, document, db, meta = self._load(directory)
            try:
                if action == 'list':
                    offset, limit = max(0, int(offset)), max(1, min(200, int(limit)))
                    rows = db.execute('SELECT seq,parent,label,created FROM operations WHERE active=1 ORDER BY seq DESC LIMIT ? OFFSET ?', (limit, offset)).fetchall()
                    count = db.execute('SELECT count(*) FROM operations WHERE active=1').fetchone()[0]
                    return {'ok': True, 'directory': directory, 'revision': meta['revision'], 'workspace_revision': self.workspace_revision,
                            'history': self._history_state(db, meta['cursor']), 'entries': [dict(row) | {'applied': row['seq'] <= meta['cursor']} for row in rows],
                            'total': count, 'offset': offset, 'limit': limit}
                if action not in ('undo', 'redo'):
                    raise ValueError('history action must be list, undo or redo')
                fingerprint = _hash(_json({'action': action}))
                receipt = self._receipt(db, operation_id, fingerprint)
                if receipt:
                    return self._result(directory, path, db, replayed=True, operation_revision=receipt['revision'])
                self._revision(meta, expected_revision)
                if action == 'undo':
                    row = db.execute('SELECT * FROM operations WHERE seq=? AND active=1', (meta['cursor'],)).fetchone()
                else:
                    row = db.execute('SELECT * FROM operations WHERE parent=? AND active=1 ORDER BY seq LIMIT 1', (meta['cursor'],)).fetchone()
                if row is None:
                    raise ValueError(f'Nothing to {action}')
                after = _patch(document, json.loads(row['inverse' if action == 'undo' else 'forward']))
                self.validate(after, project)
                self._commit(db, path, document, after, meta, operation_id, fingerprint, row['label'], action=action,
                             cursor=row['parent'] if action == 'undo' else row['seq'])
                self._changed(directory, path)
                return self._result(directory, path, db)
            finally:
                db.close()

    def import_asset(self, directory: str, name: str, data, expected_revision, operation_id: str, mime=''):
        if isinstance(data, str):
            try:
                data = base64.b64decode(data.split(',', 1)[1] if data.startswith('data:') else data, validate=True)
            except (ValueError, TypeError) as exc:
                raise ValueError('Asset data must be valid base64') from exc
        if not isinstance(data, (bytes, bytearray)) or not data or len(data) > MAX_ASSET_BYTES:
            raise ValueError('Asset data must contain 1 byte to 128 MiB')
        name = Path(str(name).replace('\\', '/')).name
        extension = Path(name).suffix.lower()
        allowed = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.avif', '.ico', '.bmp', '.tif', '.tiff', '.woff', '.woff2', '.ttf', '.otf', '.mp4', '.webm', '.mp3', '.wav', '.ogg', '.json', '.js', '.mjs', '.css'}
        if extension not in allowed:
            raise ValueError('Unsupported asset extension')
        digest = _hash(bytes(data))
        asset_id = 'asset-' + _hash((str(operation_id) + '\n' + digest + '\n' + name).encode())[:32]
        rel_path = f'Design/Assets/Imported/{digest}{extension}'
        asset = {'id': asset_id, 'name': name, 'path': rel_path, 'mime': str(mime or mimetypes.guess_type(name)[0] or 'application/octet-stream'),
                 'size': len(data), 'sha256': digest, 'tags': [], 'category': ''}
        if extension in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.avif', '.bmp', '.tif', '.tiff'}:
            try:
                from PIL import Image
                with Image.open(io.BytesIO(data)) as image:
                    asset.update(width=image.width, height=image.height, alpha=('A' in image.getbands() or 'transparency' in image.info))
            except (ImportError, OSError, ValueError):
                pass
        with self.config.lock, self.files.lock:
            directory, _, _ = self._paths(directory)
            target = self.config.path_for(f'{directory}/{rel_path}', writable=True)
            # Check CAS and request replay before creating a retained media object.
            command = {'type': 'asset.register', 'asset': asset}
            fingerprint = _hash(_json({'commands': [command], 'label': 'Import ' + name}))
            _, _, _, _, db, meta = self._load(directory)
            try:
                receipt = self._receipt(db, operation_id, fingerprint)
                if not receipt:
                    self._revision(meta, expected_revision)
                if target.exists() and _hash(target.read_bytes()) != digest:
                    raise ConflictError('Imported asset content changed externally; original bytes were preserved')
                if not target.exists():
                    atomic_write(target, bytes(data))
            finally:
                db.close()
            result = self.apply(directory, [command], expected_revision, operation_id, 'Import ' + name)
            result['asset'] = result['document']['assets'].get(asset_id, asset)
            return result

    def _changed(self, directory, path):
        rel = path.relative_to(self.config.root).as_posix()
        self.files.changed(rel)
        events = getattr(self.runtime, 'events', None)
        if events is not None:
            events.publish('files', paths=[rel], design_document={'directory': directory})

    @staticmethod
    def _page(document, page_id):
        page = next((page for page in document['pages'] if page['id'] == page_id), None)
        if page is None:
            raise ValueError(f'Unknown page: {page_id}')
        return page

    @staticmethod
    def _node(document, page_id, node_id):
        found = _find(DesignDocuments._page(document, page_id)['nodes'], node_id)
        if found is None:
            raise ValueError(f'Unknown element: {node_id}')
        return found

    @staticmethod
    def _insert(items, value, index=None):
        if index is None:
            items.append(value)
        else:
            if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index <= len(items):
                raise ValueError('Insertion index is outside its container')
            items.insert(index, value)

    def _children(self, document, page_id, parent_id=None):
        if parent_id is None:
            return self._page(document, page_id)['nodes']
        node = self._node(document, page_id, parent_id)[2]
        if node['type'] not in ('container', 'button', 'shape', 'html', 'svg', 'element'):
            raise ValueError('This element cannot contain editable children')
        return node.setdefault('children', [])

    def _command(self, document, command):
        if not isinstance(command, dict):
            raise ValueError('Every command must be an object')
        kind = command.get('type')
        if kind == 'document.replace':
            replacement = copy.deepcopy(command.get('document'))
            if not isinstance(replacement, dict) or replacement.get('id') != document['id']:
                raise ValueError('Replacement must retain the project identity')
            pages = replacement.get('pages')
            if isinstance(pages, list) and any(isinstance(page, dict) and 'loaded' in page for page in pages):
                raise ValueError('Full document replacement requires the complete document, not a page projection')
            document.clear()
            document.update(replacement)
        elif kind == 'project.update':
            patch = command.get('patch', {})
            if set(patch) - {'name', 'description', 'cover', 'tags', 'favorite', 'archived', 'folder'}:
                raise ValueError('Use structural commands to edit project content')
            _merge(document, patch)
        elif kind == 'project.rebrand':
            metadata = document.get('metadata', {})
            if metadata.get('template') != 'forma':
                raise ValueError('This project does not have editable template branding')
            brand = command.get('brand')
            if not isinstance(brand, str) or not brand.strip() or len(brand) > 80:
                raise ValueError('Brand name must contain 1 to 80 characters')
            branding = metadata.setdefault('branding', {})
            branding['brand'] = brand.strip()
            if 'contact' in command:
                contact = command['contact']
                if not isinstance(contact, str) or len(contact) > 160:
                    raise ValueError('Contact caption must contain at most 160 characters')
                branding['contact'] = contact.strip()
            groups = [page['nodes'] for page in document['pages']] + [[component['node']] for component in document['components'].values()]
            for group in groups:
                for node in _walk(group):
                    props = node.get('props', {})
                    binding = props.get('templateText', {})
                    if not isinstance(binding, dict) or binding.get('field') not in branding:
                        continue
                    text = branding[binding['field']]
                    if binding.get('uppercase'):
                        text = text.upper()
                    props['text'] = str(binding.get('prefix', '')) + text + str(binding.get('suffix', ''))
        elif kind == 'page.create':
            page = copy.deepcopy(command.get('page', {}))
            page.setdefault('id', _id())
            page.setdefault('name', 'Page')
            page.setdefault('group', '')
            page.setdefault('width', 720)
            page.setdefault('height', 1560)
            page.setdefault('nodes', [])
            self._insert(document['pages'], page, command.get('index'))
        elif kind == 'page.update':
            _merge(self._page(document, command['page_id']), command.get('patch', {}), immutable=('id', 'nodes'))
        elif kind == 'page.delete':
            page = self._page(document, command['page_id'])
            if len(document['pages']) == 1:
                raise ValueError('A project must retain at least one page')
            document['pages'].remove(page)
        elif kind == 'page.duplicate':
            page = copy.deepcopy(self._page(document, command['page_id']))
            page['id'] = command.get('new_id') or _id()
            page['name'] = command.get('name') or page['name'] + ' copy'
            mapping = {item['id']: _id() for item in _walk(page['nodes'])}
            mapping[command['page_id']] = page['id']
            page['nodes'] = [_fresh_node(node, mapping) for node in page['nodes']]
            _remap_script(page.get('script'), mapping)
            # A normal duplicate is an independent snapshot, rather than a
            # second owner of the source's contextual render dependencies.
            if isinstance(page.get('migration'), dict):
                page['migration'].pop('contextVariants', None)
                page['migration'].pop('contextSource', None)
            self._insert(document['pages'], page, command.get('index'))
        elif kind == 'page.reorder':
            ids = command.get('page_ids', [])
            if not isinstance(ids, list) or len(ids) != len(document['pages']) or set(ids) != {p['id'] for p in document['pages']}:
                raise ValueError('page_ids must include every page exactly once')
            pages = {p['id']: p for p in document['pages']}
            document['pages'] = [pages[key] for key in ids]
        elif kind == 'page.move':
            page = self._page(document, command['page_id'])
            document['pages'].remove(page)
            self._insert(document['pages'], page, command['index'])
        elif kind == 'node.create':
            node = copy.deepcopy(command.get('node', {}))
            node.setdefault('id', _id())
            node.setdefault('type', 'container')
            node.setdefault('name', node['type'])
            node.setdefault('children', [])
            node.setdefault('style', {})
            node.setdefault('props', {})
            self._insert(self._children(document, command['page_id'], command.get('parent_id')), node, command.get('index'))
        elif kind == 'node.update':
            _merge(self._node(document, command['page_id'], command['node_id'])[2], command.get('patch', {}), immutable=('id', 'children'))
        elif kind == 'node.replace':
            items, index, _ = self._node(document, command['page_id'], command['node_id'])
            replacement = copy.deepcopy(command.get('node', {}))
            if replacement.get('id') != command['node_id']:
                raise ValueError('Replacement must retain the element identity')
            items[index] = replacement
        elif kind == 'node.delete':
            items, index, _ = self._node(document, command['page_id'], command['node_id'])
            items.pop(index)
        elif kind == 'node.duplicate':
            items, index, node = self._node(document, command['page_id'], command['node_id'])
            target = self._children(document, command['page_id'], command.get('parent_id')) if 'parent_id' in command else items
            self._insert(target, _fresh_node(node), command.get('index', index + 1 if target is items else None))
        elif kind == 'node.move':
            items, index, node = self._node(document, command['page_id'], command['node_id'])
            if command.get('parent_id') in {item['id'] for item in _walk([node])}:
                raise ValueError('An element cannot be moved inside itself')
            target = self._children(document, command.get('target_page_id', command['page_id']), command.get('parent_id'))
            items.pop(index)
            self._insert(target, node, command.get('index'))
        elif kind == 'node.group':
            ids = command.get('node_ids', [])
            if not isinstance(ids, list) or len(ids) < 2 or len(set(ids)) != len(ids):
                raise ValueError('Select at least two distinct sibling elements to group')
            matches = [self._node(document, command['page_id'], key) for key in ids]
            siblings = matches[0][0]
            if any(item[0] is not siblings for item in matches):
                raise ValueError('Grouped elements must share a parent')
            ordered = sorted(matches, key=lambda item: item[1])
            children = [item[2] for item in ordered]
            # Relative placement retains every child's canvas position. Authored
            # CSS layouts remain in a neutral wrapper instead of guessing offsets.
            positioned = all(isinstance(node.get('style', {}).get('x', 0), (int, float)) and
                             isinstance(node.get('style', {}).get('y', 0), (int, float)) for node in children)
            left = min(node.get('style', {}).get('x', 0) for node in children) if positioned else 0
            top = min(node.get('style', {}).get('y', 0) for node in children) if positioned else 0
            width = max((node.get('style', {}).get('x', 0) + node.get('style', {}).get('width', 0) for node in children
                         if isinstance(node.get('style', {}).get('width', 0), (int, float))), default=left) - left if positioned else 0
            height = max((node.get('style', {}).get('y', 0) + node.get('style', {}).get('height', 0) for node in children
                          if isinstance(node.get('style', {}).get('height', 0), (int, float))), default=top) - top if positioned else 0
            for _, index, _ in reversed(ordered):
                siblings.pop(index)
            if positioned:
                for node in children:
                    style = node.setdefault('style', {})
                    style['x'], style['y'] = style.get('x', 0) - left, style.get('y', 0) - top
            group = {'id': command.get('node_id') or _id(), 'type': 'container', 'name': command.get('name', 'Group'),
                     'style': {'x': left, 'y': top, 'width': max(1, width), 'height': max(1, height)},
                     'props': {}, 'children': children}
            siblings.insert(ordered[0][1], group)
        elif kind == 'node.ungroup':
            siblings, index, node = self._node(document, command['page_id'], command['node_id'])
            if node['type'] != 'container':
                raise ValueError('Only a container can be ungrouped')
            group_style = node.get('style', {})
            if group_style.get('transform') or group_style.get('transformOrigin', '0 0') != '0 0':
                raise ValueError('Ungroup requires a group with the default origin and editable rotation/scale')
            angle = math.radians(float(group_style.get('rotate', 0)))
            gx, gy = float(group_style.get('x', 0)), float(group_style.get('y', 0))
            gsx, gsy = float(group_style.get('scaleX', 1)), float(group_style.get('scaleY', 1))
            children = node.get('children', [])
            for child in children:
                style = child.setdefault('style', {})
                cx, cy = float(style.get('x', 0)), float(style.get('y', 0))
                style['x'] = gx + cx * gsx * math.cos(angle) - cy * gsy * math.sin(angle)
                style['y'] = gy + cx * gsx * math.sin(angle) + cy * gsy * math.cos(angle)
                child_rotate = float(style.get('rotate', 0))
                csx, csy = float(style.get('scaleX', 1)), float(style.get('scaleY', 1))
                if gsx != gsy and child_rotate % 180:
                    # Nonuniform scaling of an already rotated child creates
                    # shear; a CSS matrix preserves that geometry exactly.
                    ca = math.radians(child_rotate)
                    a, b, c, d = math.cos(angle) * gsx, math.sin(angle) * gsx, -math.sin(angle) * gsy, math.cos(angle) * gsy
                    e, f, g, h = math.cos(ca) * csx, math.sin(ca) * csx, -math.sin(ca) * csy, math.cos(ca) * csy
                    matrix = (a * e + c * f, b * e + d * f, a * g + c * h, b * g + d * h)
                    style['transform'] = 'matrix(' + ','.join(str(value) for value in (*matrix, 0, 0)) + ')' + (' ' + str(style['transform']) if style.get('transform') else '')
                    style['rotate'], style['scaleX'], style['scaleY'] = 0, 1, 1
                else:
                    style['rotate'] = child_rotate + float(group_style.get('rotate', 0))
                    style['scaleX'], style['scaleY'] = csx * gsx, csy * gsy
                if 'opacity' in group_style:
                    style['opacity'] = float(style.get('opacity', 1)) * float(group_style['opacity'])
                if node.get('hidden'):
                    child['hidden'] = True
            siblings[index:index + 1] = children
        elif kind == 'component.create':
            component = copy.deepcopy(command.get('component', {}))
            component.setdefault('id', _id())
            component.setdefault('name', 'Component')
            component['version'] = 1
            if component['id'] in document['components']:
                raise ValueError('Component identity already exists')
            document['components'][component['id']] = component
        elif kind == 'component.from_node':
            items, index, source = self._node(document, command['page_id'], command['node_id'])
            component_id = command.get('component_id') or _id()
            if not isinstance(component_id, str) or not component_id or component_id in document['components']:
                raise ValueError('Component identity must be new and nonempty')
            master = _fresh_node(source)
            resolved = resolve_style(document, source)
            geometry = {'x', 'y', 'width', 'height', 'widthMode', 'heightMode', 'minWidth', 'maxWidth', 'minHeight', 'maxHeight',
                        'flexGrow', 'flexShrink', 'flexBasis', 'alignSelf', 'rotate', 'scaleX', 'scaleY', 'transform', 'transformOrigin',
                        'position', 'left', 'top', 'right', 'bottom', 'zIndex', 'opacity'}
            instance = {'id': source['id'], 'name': source.get('name', 'Instance'), 'type': 'instance',
                        'style': {key: copy.deepcopy(value) for key, value in resolved.items() if key in geometry},
                        'props': {'componentId': component_id}, 'children': []}
            for key in ('hidden', 'locked'):
                if key in source:
                    instance[key] = source[key]
                    master.pop(key, None)
            # Placement belongs to the instance, appearance and behavior to the
            # master. The runtime gives the master the instance's content size.
            master.setdefault('style', {}).update(x=0, y=0, rotate=0, scaleX=1, scaleY=1, opacity=1,
                                                 position='absolute', transform='', transformOrigin='0 0', zIndex=0)
            document['components'][component_id] = {'id': component_id, 'name': command.get('name') or source.get('name', 'Component'),
                                                     'version': 1, 'node': master}
            items[index] = instance
        elif kind == 'component.edit':
            component = document['components'].get(command['component_id'])
            if component is None:
                raise ValueError('Unknown component')
            commands = command.get('commands')
            if not isinstance(commands, list) or not commands or len(commands) > 10000:
                raise ValueError('Component edits require 1 to 10000 element commands')
            root_id = component['node']['id']
            page_id = 'component:' + command['component_id']
            page = {'id': page_id, 'nodes': [copy.deepcopy(component['node'])]}
            transient = {**document, 'pages': [page]}
            for nested in commands:
                if not isinstance(nested, dict) or not (str(nested.get('type', '')).startswith('node.') or nested.get('type') in (
                        'component.detach', 'component.override', 'component.reset_override', 'style.apply', 'style.detach')):
                    raise ValueError('Component edits accept only element commands and nested instance detachment')
                if nested.get('type') in ('node.delete', 'node.duplicate', 'node.move', 'node.ungroup') and nested.get('node_id') == root_id:
                    raise ValueError('A main component must retain its single root; insert and edit content inside the root')
                if nested.get('target_page_id') not in (None, page_id, nested.get('page_id')):
                    raise ValueError('Elements cannot be moved outside the main component while editing it')
                inner = {**nested, 'page_id': page_id}
                if 'target_page_id' in inner:
                    inner['target_page_id'] = page_id
                self._command(transient, inner)
                if len(page['nodes']) != 1 or page['nodes'][0].get('id') != root_id:
                    raise ValueError('A main component must retain its single root; insert and edit content inside the root')
            component['node'] = page['nodes'][0]
            component['version'] += 1
        elif kind == 'component.update':
            component = document['components'].get(command['component_id'])
            if component is None:
                raise ValueError('Unknown component')
            _merge(component, command.get('patch', {}), immutable=('id', 'version'))
            component['version'] += 1
        elif kind == 'component.delete':
            if document['components'].pop(command['component_id'], None) is None:
                raise ValueError('Unknown component')
        elif kind in ('component.override', 'component.reset_override'):
            _, _, instance = self._node(document, command['page_id'], command['node_id'])
            if instance['type'] != 'instance':
                raise ValueError('Only a component instance can have overrides')
            component = document['components'].get(instance.get('props', {}).get('componentId'))
            if not component:
                raise ValueError('Unknown component')
            overrides = component_overrides(component, instance)
            target_id = command.get('target_id')
            if kind == 'component.override':
                if not _find([component['node']], target_id):
                    raise ValueError('Override target must belong to the main component')
                patch = command.get('patch')
                if not isinstance(patch, dict) or not patch or set(patch) - {'style', 'props'}:
                    raise ValueError('Component overrides accept style and props property patches')
                if any(value is not None and not isinstance(value, dict) for value in patch.values()):
                    raise ValueError('Component override style and props must be objects')
                target = overrides.setdefault(target_id, {})
                _merge(target, patch)
            elif target_id is None:
                if command.get('section') or command.get('property'):
                    raise ValueError('Choose an override target before resetting a property')
                overrides = {}
            else:
                if not _find([component['node']], target_id) and target_id not in overrides:
                    raise ValueError('Unknown component override target')
                section, prop = command.get('section'), command.get('property')
                if section is not None and section not in ('style', 'props'):
                    raise ValueError('Override section must be style or props')
                if prop is not None and (not section or not isinstance(prop, str) or not prop):
                    raise ValueError('Resetting an override property requires a section and property name')
                if not section:
                    overrides.pop(target_id, None)
                elif prop is None:
                    overrides.get(target_id, {}).pop(section, None)
                else:
                    overrides.get(target_id, {}).get(section, {}).pop(prop, None)
            # An absent entry means inherit. Never persist a null "override"
            # that would erase a main-component property during rendering.
            overrides = {key: {section: value for section, value in patch.items() if value}
                         for key, patch in overrides.items()}
            overrides = {key: patch for key, patch in overrides.items() if patch}
            if overrides:
                instance.setdefault('props', {})['overrides'] = overrides
            else:
                instance.setdefault('props', {}).pop('overrides', None)
        elif kind == 'component.detach':
            items, index, node = self._node(document, command['page_id'], command['node_id'])
            if node['type'] != 'instance':
                raise ValueError('Only a component instance can be detached')
            component = document['components'].get(node.get('props', {}).get('componentId'))
            if component is None:
                raise ValueError('Unknown component')
            source = copy.deepcopy(component['node'])
            overrides = component_overrides(component, node)
            for child in _walk([source]):
                patch = overrides.get(child['id'])
                if patch is not None:
                    if not isinstance(patch, dict):
                        raise ValueError('Element overrides must be property patches')
                    _merge(child, {key: value for key, value in patch.items() if key in ('style', 'props')})
            source.setdefault('style', {}).update(resolve_style(document, node))
            for key in ('script', 'animation', 'hidden', 'locked'):
                if key in node:
                    source[key] = copy.deepcopy(node[key])
            items[index] = _fresh_node(source, root_id=node['id'])
        elif kind == 'asset.register':
            asset = copy.deepcopy(command.get('asset', {}))
            asset.setdefault('id', _id())
            if asset['id'] in document['assets']:
                raise ValueError('Asset identity already exists')
            document['assets'][asset['id']] = asset
        elif kind == 'asset.update':
            asset = document['assets'].get(command['asset_id'])
            if asset is None:
                raise ValueError('Unknown asset')
            _merge(asset, command.get('patch', {}), immutable=('id', 'path', 'sha256', 'size'))
        elif kind == 'asset.delete':
            if command['asset_id'] not in document['assets']:
                raise ValueError('Unknown asset')
            references = AssetReferences(document['assets'])
            groups = [*document['pages'], *document['components'].values()]
            used = set().union(*(references.process(group)[0] for group in groups))
            for table, context in (('styles', 'style'), ('scripts', 'script')):
                for resource in document[table].values():
                    used.update(references.process(resource, context=context)[0])
            if command['asset_id'] in used:
                raise ValueError('Referenced asset is still used by elements, CSS or scripts; replace or remove its references before deleting')
            if document['assets'].pop(command['asset_id'], None) is None:
                raise ValueError('Unknown asset')
        elif kind == 'asset.replace':
            if command['asset_id'] not in document['assets'] or command['replacement_id'] not in document['assets']:
                raise ValueError('Unknown asset')
            references = AssetReferences(document['assets'])
            scopes = [page for page in document['pages'] if not command.get('page_id') or page['id'] == command['page_id']]
            if not command.get('page_id'):
                scopes += list(document['components'].values())
            options = {'old_id': command['asset_id'], 'new_id': command['replacement_id']}
            for scope in scopes:
                if command.get('node_ids'):
                    nodes = scope.get('nodes', [scope['node']] if 'node' in scope else [])
                    for node in _walk(nodes):
                        if node['id'] in command['node_ids']:
                            references.process(node, base_path=scope.get('basePath', ''), **options)
                else:
                    references.process(scope, **options)
            if not command.get('page_id') and not command.get('node_ids'):
                for table, context in (('styles', 'style'), ('scripts', 'script')):
                    for resource_id, resource in document[table].items():
                        document[table][resource_id] = references.process(resource, context=context, **options)[1]
        elif kind in ('style.apply', 'style.detach'):
            style_id = command.get('style_id')
            resource = document['styles'].get(style_id)
            if not isinstance(resource, dict):
                raise ValueError('Unknown shared style')
            selected = command.get('node_ids', [command['node_id']] if command.get('node_id') else [])
            if not isinstance(selected, list) or not selected or len(selected) > 10000 or any(not isinstance(value, str) for value in selected):
                raise ValueError('Choose at least one element for a shared style')
            for node_id in dict.fromkeys(selected):
                _, _, node = self._node(document, command['page_id'], node_id)
                before = resolve_style(document, node)
                linked = style_ids(node)
                props = node.setdefault('props', {})
                if kind == 'style.apply':
                    category = resource.get('kind')
                    values = resource.get('style', resource)
                    removed = [key for key in linked if key == style_id or category in STYLE_KINDS and document['styles'][key].get('kind') == category]
                    linked = [key for key in linked if key not in removed] + [style_id]
                    clear = set(values) | STYLE_KEYS.get(category, set())
                    for key in removed:
                        previous = document['styles'][key]
                        clear.update(previous.get('style', previous))
                    for key in clear:
                        node.setdefault('style', {}).pop(key, None)
                        # Removing a theme must not leave authored var() uses
                        # undefined. Keep unmatched custom tokens at their
                        # current values while the replacement supplies its own.
                        if key.startswith('--') and key not in values and key in before:
                            node['style'][key] = before[key]
                else:
                    linked = [key for key in linked if key != style_id]
                props.pop('styleId', None)
                if linked:
                    props['styleIds'] = linked
                else:
                    props.pop('styleIds', None)
                if kind == 'style.detach':
                    after = resolve_style(document, node)
                    # Freeze only values that actually depended on this style;
                    # independent typography/spacing references remain live.
                    for key, value in before.items():
                        if key not in after or after[key] != value:
                            node.setdefault('style', {})[key] = value
        elif kind in ('style.create', 'script.create'):
            resource_kind = kind.split('.')[0]
            resource = copy.deepcopy(command.get(resource_kind, {}))
            if not isinstance(resource, dict):
                raise ValueError('A shared style or script must be an object')
            if resource_kind == 'style' and 'kind' in resource and resource['kind'] not in STYLE_KINDS:
                raise ValueError('Shared style kind must be color, typography or spacing')
            resource.setdefault('id', _id())
            resource.setdefault('name', resource_kind.title())
            resource.setdefault('style' if resource_kind == 'style' else 'source', {} if resource_kind == 'style' else 'export function mount(ctx) {}')
            table = document[resource_kind + 's']
            if resource['id'] in table:
                raise ValueError('Resource identity already exists')
            table[resource['id']] = resource
        elif kind in ('style.update', 'script.update', 'style.delete', 'script.delete'):
            resource_kind, action = kind.split('.')
            resource_id = command[resource_kind + '_id']
            table = document[resource_kind + 's']
            if resource_id not in table:
                raise ValueError('Unknown style or script module')
            if action == 'delete':
                del table[resource_id]
            else:
                if not isinstance(table[resource_id], dict):
                    raise ValueError('Convert this legacy resource to a structured object before updating')
                if resource_kind == 'style' and command.get('patch', {}).get('kind') not in (None, *STYLE_KINDS):
                    raise ValueError('Shared style kind must be color, typography or spacing')
                _merge(table[resource_id], command.get('patch', {}))
        else:
            raise ValueError(f'Unknown design command: {kind}')

    def validate(self, document: dict, project: Path | None = None):
        _json(document)
        if not isinstance(document, dict) or document.get('schemaVersion') != 1:
            raise ValueError('Unsupported managed design schema')
        if not isinstance(document.get('id'), str) or not document['id']:
            raise ValueError('A project requires a stable document ID')
        for key in ('assets', 'components', 'styles', 'scripts'):
            if not isinstance(document.get(key), dict):
                raise ValueError(f'{key} must be an object')
        pages = document.get('pages')
        if not isinstance(pages, list) or not pages:
            raise ValueError('A project requires at least one page')
        page_ids, all_ids, edges = set(), set(), {}

        def identity(value):
            if not isinstance(value, str) or not value or len(value) > 200 or value in all_ids:
                raise ValueError('Page and element IDs must be nonempty and globally unique')
            all_ids.add(value)

        for page in pages:
            if not isinstance(page, dict):
                raise ValueError('Page must be an object')
            identity(page.get('id'))
            page_ids.add(page['id'])
            for dimension in ('width', 'height'):
                value = page.get(dimension)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 1 <= value <= 32768:
                    raise ValueError('Page dimensions must be finite numbers between 1 and 32768')
            if not isinstance(page.get('nodes'), list):
                raise ValueError('Page nodes must be an array')
            edges['p:' + page['id']] = set()
        validate_page_contexts(pages, edges)
        for key, asset in document['assets'].items():
            if not isinstance(asset, dict) or asset.get('id') != key:
                raise ValueError('Asset identity must match its key')
            path = asset.get('path', '')
            if not isinstance(path, str) or not path or relative(path) != path or path.startswith('.'):
                raise ValueError('Asset paths must be project-relative local paths')
            if project is not None:
                full = project / path
                self.config.path_for(full.relative_to(self.config.root).as_posix())
        for key, component in document['components'].items():
            if not isinstance(component, dict) or component.get('id') != key or not isinstance(component.get('node'), dict):
                raise ValueError('Component requires a matching identity and root node')
            edges['c:' + key] = set()
        for key, resource in document['styles'].items():
            if not isinstance(resource, dict):
                raise ValueError('A shared style must be an object')
            if 'id' in resource and resource['id'] != key:
                raise ValueError('Shared style identity must match its key')
            if 'style' in resource and not isinstance(resource['style'], dict):
                raise ValueError('Shared style properties must be an object')
            # Older portable resources may carry their own category labels.
            # Keep them readable; newly authored categories use STYLE_KINDS.
            if 'kind' in resource and not isinstance(resource['kind'], str):
                raise ValueError('Shared style kind must be text')

        def linked_styles(props):
            if props.get('styleId') and props['styleId'] not in document['styles']:
                raise ValueError('Referenced shared style does not exist')
            if 'styleIds' in props:
                linked = props['styleIds']
                if not isinstance(linked, list) or len(linked) > 64 or any(not isinstance(value, str) or not value for value in linked):
                    raise ValueError('Shared style references must be an array of at most 64 identities')
                if len(set(linked)) != len(linked) or any(value not in document['styles'] for value in linked):
                    raise ValueError('Referenced shared styles must exist and be distinct')

        def override_references(props, owner, depth=0, target=None):
            if depth > 100:
                raise ValueError('Component override nesting exceeds the supported depth')
            linked_styles(props)
            for field, table, prefix in (('assetId', 'assets', None), ('scriptId', 'scripts', None),
                                         ('componentId', 'components', 'c:'), ('pageId', None, 'p:'), ('navigateTo', None, None)):
                key = props.get(field)
                if key:
                    if not isinstance(key, str) or key not in (document[table] if table else page_ids):
                        raise ValueError('Component override references a missing resource')
                    if prefix and (field != 'pageId' or (target or {}).get('type') == 'page'):
                        edges[owner].add(prefix + key)
            effective = {**(target or {}).get('props', {}), **props}
            nested = effective.get('overrides')
            if nested is not None:
                if not isinstance(nested, dict):
                    raise ValueError('Component overrides must be an object')
                component = document['components'].get(effective.get('componentId'))
                if component is None:
                    raise ValueError('Nested overrides require an existing component target')
                targets = {item['id']: item for item in _walk([component['node']])}
                for target_id, patch in component_overrides(component, {'props': effective}).items():
                    if not isinstance(patch, dict) or set(patch) - {'style', 'props'}:
                        raise ValueError('Element overrides must be style and props property patches')
                    if any(not isinstance(value, dict) for value in patch.values()):
                        raise ValueError('Component override style and props must be objects')
                    override_references(patch.get('props', {}), owner, depth + 1, targets.get(target_id))

        def nodes(values, owner, depth=0):
            if depth > 100 or not isinstance(values, list):
                raise ValueError('Element nesting exceeds the supported depth')
            for node in values:
                if not isinstance(node, dict) or node.get('type') not in NODE_TYPES:
                    raise ValueError('Unknown element type')
                identity(node.get('id'))
                for key in ('style', 'props'):
                    if key in node and not isinstance(node[key], dict):
                        raise ValueError(f'Element {key} must be an object')
                props = node.get('props', {})
                if props.get('assetId') and props['assetId'] not in document['assets']:
                    raise ValueError('Referenced asset does not exist; replace its references before deleting')
                page_id = props.get('pageId')
                if props.get('navigateTo') and props['navigateTo'] not in page_ids:
                    raise ValueError('Navigation references a missing page')
                if page_id:
                    if page_id not in page_ids:
                        raise ValueError('Referenced page does not exist')
                    # Navigation is not an embed edge and may return to the same page.
                    if node['type'] == 'page':
                        edges[owner].add('p:' + page_id)
                component_id = props.get('componentId')
                if component_id:
                    if component_id not in document['components']:
                        raise ValueError('Referenced component does not exist; detach instances before deleting')
                    edges[owner].add('c:' + component_id)
                if node['type'] == 'page' and not page_id:
                    raise ValueError('Embedded page requires pageId')
                if node['type'] == 'instance' and not component_id:
                    raise ValueError('Component instance requires componentId')
                for key in ('script', 'animation'):
                    if key in node and not isinstance(node[key], dict):
                        raise ValueError(f'Element {key} must be an object')
                if 'script' in node and not isinstance(node['script'].get('source', ''), str):
                    raise ValueError('Script source must be text')
                module_id = node.get('script', {}).get('moduleId') or props.get('scriptId')
                if module_id and module_id not in document['scripts']:
                    raise ValueError('Referenced script module does not exist')
                linked_styles(props)
                if node['type'] == 'instance' and 'overrides' in props:
                    component = document['components'][component_id]
                    targets = {item['id']: item for item in _walk([component['node']])}
                    for target_id, patch in component_overrides(component, node).items():
                        if not isinstance(patch, dict) or set(patch) - {'style', 'props'}:
                            raise ValueError('Element overrides must be style and props property patches')
                        if any(not isinstance(value, dict) for value in patch.values()):
                            raise ValueError('Component override style and props must be objects')
                        override_references(patch.get('props', {}), owner, target=targets.get(target_id))
                nodes(node.get('children', []), owner, depth + 1)

        for page in pages:
            nodes(page['nodes'], 'p:' + page['id'])
        for key, component in document['components'].items():
            nodes([component['node']], 'c:' + key)
        visiting, visited = set(), set()

        def visit(key):
            if key in visiting:
                raise ValueError('Pages and components cannot contain cyclic embeds')
            if key in visited:
                return
            visiting.add(key)
            for target in edges[key]:
                visit(target)
            visiting.remove(key)
            visited.add(key)

        for key in edges:
            visit(key)
        return document
