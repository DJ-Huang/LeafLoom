"""Workspace organization, portable libraries and exports for managed designs.

All mutations use the same rooted Files authority as notes. User artwork is never
rewritten by library publication, migration, thumbnails or HTML export.
"""
from __future__ import annotations

import copy
import hashlib
import html
import json
import mimetypes
import re
import shutil
import sqlite3
import stat
import time
import uuid
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any

from vault_rag.local_state import ConflictError, atomic_write, relative
from vault_rag.platform_support import is_link, move_exclusive
from vault_rag.design_documents import _diff, _patch, validate_page_contexts, history_owner_matches
from vault_rag.design_references import AssetReferences, script_references, rewrite_script, srcset_urls as _srcset_urls


RUNTIME = Path(__file__).parent / 'design_assets' / 'studio'


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode()


def _digest(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _walk(nodes):
    for node in nodes:
        yield node
        yield from _walk(node.get('children', []))



class _ExportHTMLReferences(HTMLParser):
    """Read URL-bearing markup attributes, including responsive image sources."""
    def __init__(self, add):
        super().__init__(convert_charrefs=True)
        self.add = add

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if not value:
                continue
            if name in ('src', 'href', 'xlink:href', 'poster'):
                self.add(value)
            elif name in ('srcset', 'imagesrcset'):
                for url in _srcset_urls(value):
                    self.add(url)


class DesignWorkspace:
    def __init__(self, studio, documents):
        self.studio, self.documents = studio, documents
        self.config, self.files, self.runtime = studio.config, studio.files, studio.runtime
        from vault_rag.design_publishing import DesignPublisher
        self.publisher = DesignPublisher(self)

    def _state(self, *parts):
        return self.files.state_path('design-studio', *parts)

    def _load(self):
        path = self._state('workspace.json')
        if not path.exists():
            return {'version': 1, 'meta': {}, 'library': {}, 'history': [], 'cursor': 0}
        state = json.loads(path.read_text())
        pending = self._state('workspace-pending.json')
        if pending.exists():
            journal = json.loads(pending.read_text())
            if _digest(state) == journal['after_hash']:
                self._purge_files(journal.get('purge', []))
                pending.unlink()
            elif _digest(state) == journal['before_hash']:
                self._move(journal.get('move'), recovering=True)
                atomic_write(path, _bytes(journal['after']))
                self._purge_files(journal.get('purge', []))
                pending.unlink()
                state = journal['after']
            else:
                raise ConflictError('Design workspace has external changes; pending operation retained')
        return state

    def _revision(self, state):
        return state.get('revision') or _digest(state)

    def _request(self, state, operation_id, fingerprint):
        if not isinstance(operation_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,128}', operation_id):
            raise ValueError('A unique operation_id of 8 to 128 characters is required')
        previous = state.get('receipts', {}).get(operation_id)
        if previous and previous != fingerprint:
            raise ConflictError('operation_id was already used for another workspace operation')
        return previous is not None

    @staticmethod
    def _entry(before, after, operation_id, label, forward=None, backward=None):
        # A metadata edit must not replicate every prior shared-library version.
        prior = {key: before[key] for key in ('meta', 'library')}
        next_value = {key: after[key] for key in ('meta', 'library')}
        difference, reverse = _diff(prior, next_value)
        return {'id': operation_id, 'label': label, 'time': time.time(), 'delta': difference, 'inverse': reverse,
                'forward': forward, 'backward': backward}

    def _validate_revision(self, state, expected):
        if not expected or expected != self._revision(state):
            raise ConflictError('Design workspace changed; refresh before retrying')

    def _path(self, name):
        name = relative(name)
        if name.startswith('.vault-rag/design-studio/'):
            return self.files.state_path(*PurePosixPath(name).parts[1:])
        return self.config.path_for(name, writable=True)

    def _move(self, action, recovering=False):
        if not action:
            return
        source, dest = self._path(action['source']), self._path(action['destination'])
        if recovering and not source.exists() and dest.exists():
            if (dest / 'Design/studio/project.json').is_file():
                self.documents.relocate(action['source'], action['destination'])
            return
        if not source.exists() or dest.exists():
            raise ConflictError('Project location changed; no files were overwritten')
        if source.is_relative_to(dest) or dest.is_relative_to(source):
            raise ValueError('Project destination must be outside the source')
        # A content guard prevents undo from removing newer user work.
        identity_path = source / 'Design/studio/project.json'
        if action.get('document_id') and (not identity_path.is_file() or json.loads(identity_path.read_text()).get('id') != action['document_id']):
            raise ConflictError('Project identity changed; no project was moved')
        if action.get('document_id'):
            self._validate_tree(source)
        if not action.get('document_id') and action.get('snapshot') and self._snapshot(source) != action['snapshot']:
            raise ConflictError('Project content changed after the operation; recovery data retained')
        dest.parent.mkdir(parents=True, exist_ok=True)
        move_exclusive(source, dest)
        if (dest / 'Design/studio/project.json').is_file():
            self.documents.relocate(action['source'], action['destination'])

    def _validate_tree(self, root):
        """Validate entry kinds without reading potentially gigabytes of media."""
        pending, files = [root], []
        while pending:
            path = pending.pop()
            if is_link(path):
                raise ValueError('Design projects cannot contain links or junctions')
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                pending.extend(path.iterdir())
            elif stat.S_ISREG(mode):
                files.append(path)
            else:
                raise ValueError('Design projects cannot contain special files')
        return files

    def _snapshot(self, root):
        out = {}
        for path in sorted(self._validate_tree(root)):
            with path.open('rb') as stream:
                out[path.relative_to(root).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
        return out

    def _commit(self, before, after, move=None, purge=None):
        path = self._state('workspace.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        # Persist the initial state so interrupted first operations recover too.
        if not path.exists():
            atomic_write(path, _bytes(before))
        elif _digest(json.loads(path.read_bytes())) != _digest(before):
            raise ConflictError('Workspace metadata changed outside the studio; no files were overwritten')
        after['revision'] = uuid.uuid4().hex
        pending = self._state('workspace-pending.json')
        atomic_write(pending, _bytes({'before_hash': _digest(before), 'after_hash': _digest(after), 'after': after, 'move': move, 'purge': purge or []}))
        try:
            self._move(move)
        except BaseException:
            # A rejected exclusive move did not alter user content and must not
            # leave an unfulfillable journal that blocks every subsequent read.
            if move and self._path(move['source']).exists():
                pending.unlink(missing_ok=True)
            raise
        atomic_write(path, _bytes(after))
        self._purge_files(purge or [])
        pending.unlink()
        self.runtime.events.publish('files', paths=[], design_workspace=True)

    def _trash_path(self, value):
        if not isinstance(value, str) or not re.fullmatch(r'\.vault-rag/design-studio/workspace-trash/[a-zA-Z0-9_-]{8,128}/content', value):
            raise ValueError('Invalid design project trash location')
        return self._path(value)

    def _purge_history_path(self, item):
        document_id = item.get('document_id')
        if not document_id:
            return None
        if not isinstance(document_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', document_id) or document_id in ('library-blobs', 'workspace-trash'):
            raise ValueError('Invalid project document ID')
        # Only the deleted project's own database may be removed. Shared
        # library resources and live project histories are independent.
        history = self._state(document_id)
        if history.exists():
            self._validate_tree(history)
            database = self._state(document_id, 'history.sqlite3')
            if database.exists():
                from urllib.parse import quote
                with sqlite3.connect('file:' + quote(str(database), safe='/') + '?mode=ro', uri=True) as db:
                    row = db.execute('SELECT owner FROM meta WHERE id=1').fetchone()
                if row is None or not history_owner_matches(row[0], item['trash']):
                    raise ConflictError('Project history location changed; permanent deletion stopped')
            elif not item.get('history_verified'):
                raise ConflictError('Project history identity is unavailable; permanent deletion stopped')
        return history

    def _purge_files(self, items):
        for item in items:
            content = self._trash_path(item['trash'])
            history = self._purge_history_path(item)
            if content.exists():
                self._validate_tree(content)
                shutil.rmtree(content)
            if history is not None and history.exists():
                shutil.rmtree(history)
            # Leave no empty operation directories, but never delete a sibling.
            if content.parent.exists() and not any(content.parent.iterdir()):
                content.parent.rmdir()

    def purge_trash(self, directories, expected_revision, operation_id, confirm=False):
        with self.config.lock, self.files.lock:
            if confirm is not True:
                raise ValueError('Confirm permanent project deletion before continuing')
            if directories is not None and (not isinstance(directories, list) or not directories or
                                             any(not isinstance(value, str) for value in directories)):
                raise ValueError('Select deleted projects or clear the project recycle bin')
            before = self._load()
            requested = None if directories is None else sorted({relative(value) for value in directories})
            fingerprint = _digest({'purge_trash': requested})
            if self._request(before, operation_id, fingerprint):
                return {**self.state(), 'deleted': before.get('purge_counts', {}).get(operation_id, 0), 'replayed': True}
            self._validate_revision(before, expected_revision)
            selected = requested if requested is not None else sorted(key for key, value in before['meta'].items() if value.get('deleted'))
            targets = []
            for directory in selected:
                meta = before['meta'].get(directory, {})
                if not meta.get('deleted') or not meta.get('trash'):
                    raise ValueError('Only projects in the recycle bin can be permanently deleted')
                content = self._trash_path(meta['trash'])
                item = {'trash': meta['trash']}
                if content.exists():
                    self._validate_tree(content)
                    document = content / 'Design/studio/project.json'
                    if document.is_file():
                        item['document_id'] = json.loads(document.read_bytes())['id']
                elif meta.get('project', {}).get('managed'):
                    item['document_id'] = meta['project']['id']
                history = self._purge_history_path(item)
                if history is not None and history.exists():
                    item['history_verified'] = True
                targets.append(item)

            after = copy.deepcopy(before)
            for directory in selected:
                del after['meta'][directory]
            # Remove only history involving these projects, including their
            # prior locations. Other project and shared-library undo survives.
            locations = set(selected) | {item['trash'] for item in targets}
            for entry in reversed(before['history']):
                for action in (entry.get('forward'), entry.get('backward')):
                    if action and ({action.get('source'), action.get('destination')} & locations):
                        locations.update((action['source'], action['destination']))
            def related(entry):
                for action in (entry.get('forward'), entry.get('backward')):
                    if action and ({action.get('source'), action.get('destination')} & locations):
                        return True
                for operation in entry.get('delta', []) + entry.get('inverse', []):
                    path = operation.get('path', [])
                    if path and path[0] == 'meta' and (len(path) == 1 or path[1] in locations):
                        return True
                if 'before_meta' in entry and any(entry['before_meta'].get(name) != entry.get('after_meta', {}).get(name) for name in locations):
                    return True
                return False
            retained, cursor = [], 0
            for index, entry in enumerate(after['history']):
                if related(entry):
                    continue
                for key in ('before_meta', 'after_meta'):
                    if key in entry:
                        entry[key] = {name: value for name, value in entry[key].items() if name not in locations}
                retained.append(entry)
                cursor += index < before['cursor']
            after['history'], after['cursor'] = retained, cursor
            after.setdefault('receipts', {})[operation_id] = fingerprint
            after.setdefault('purge_counts', {})[operation_id] = len(selected)
            self._commit(before, after, purge=targets)
            return {**self.state(), 'deleted': len(selected)}

    def state(self):
        with self.config.lock, self.files.lock:
            state = self._load()
            return {'ok': True, 'revision': self._revision(state), 'meta': state['meta'],
                    'items': [self._library_summary(i) for i in state['library'].values()],
                    'history': {'can_undo': state['cursor'] > 0, 'can_redo': state['cursor'] < len(state['history']),
                                'undo_label': state['history'][state['cursor'] - 1]['label'] if state['cursor'] > 0 else '',
                                'redo_label': state['history'][state['cursor']]['label'] if state['cursor'] < len(state['history']) else ''}}

    def record_creation(self, directory, label='Create project'):
        """Record an already exclusively created project; undo retains it in private trash."""
        with self.config.lock, self.files.lock:
            before = self._load()
            after = copy.deepcopy(before)
            key = uuid.uuid4().hex
            project = self.config.path_for(directory)
            reverse = {'source': directory, 'destination': f'.vault-rag/design-studio/workspace-trash/{key}/content'}
            managed = self.config.path_for(directory) / 'Design/studio/project.json'
            if managed.is_file():
                self._validate_tree(project)
                reverse['document_id'] = json.loads(managed.read_bytes())['id']
            else:
                reverse['snapshot'] = self._snapshot(project)
            forward = {**reverse, 'source': reverse['destination'], 'destination': directory}
            entry = self._entry(before, after, key, label, forward, reverse)
            after['history'] = after['history'][:after['cursor']] + [entry]
            after['cursor'] = len(after['history'])
            self._commit(before, after)

    def manage(self, directory, action, expected_revision, operation_id, **options):
        with self.config.lock, self.files.lock:
            before = self._load()
            fingerprint = _digest({'directory': directory, 'action': action, 'options': options})
            if self._request(before, operation_id, fingerprint):
                return self.state()
            self._validate_revision(before, expected_revision)
            directory = relative(directory)
            deleted = before['meta'].get(directory, {})
            project = deleted.get('project') if action == 'restore' else self.studio._project_summary(self.config.path_for(directory), self.config.root)
            if project is None:
                raise ValueError('Design project not found')
            after = copy.deepcopy(before)
            meta = after['meta'].setdefault(directory, {})
            move = reverse = None
            if action in ('favorite', 'archive', 'rename', 'cover'):
                key = {'favorite': 'favorite', 'archive': 'archived', 'rename': 'name', 'cover': 'cover'}[action]
                value = options.get('value')
                if action in ('favorite', 'archive') and not isinstance(value, bool):
                    raise ValueError('Expected a boolean value')
                if action in ('rename', 'cover') and not isinstance(value, str):
                    raise ValueError('Expected a text value')
                meta[key] = value
            elif action == 'open':
                meta['openedAt'] = time.time()
            elif action == 'restore':
                if not deleted.get('deleted') or not deleted.get('trash'):
                    raise ValueError('This project is not in the recycle bin')
                source = deleted['trash']
                move = {'source': source, 'destination': directory}
                managed = self._path(source) / 'Design/studio/project.json'
                if managed.is_file():
                    move['document_id'] = json.loads(managed.read_bytes())['id']
                else:
                    move['snapshot'] = self._snapshot(self._path(source))
                reverse = {**move, 'source': directory, 'destination': source}
                after['meta'][directory] = {key: value for key, value in meta.items() if key not in ('deleted', 'trash', 'project')}
            elif action in ('move', 'delete'):
                if not directory:
                    raise ValueError('The connected root cannot be moved or deleted')
                destination = relative(options.get('destination', '')) if action == 'move' else f'.vault-rag/design-studio/workspace-trash/{operation_id}/content'
                if not destination:
                    raise ValueError('A destination is required')
                if action == 'move':
                    self.config.path_for(destination, writable=True)
                move = {'source': directory, 'destination': destination}
                managed = self.config.path_for(directory) / 'Design/studio/project.json'
                if managed.is_file():
                    move['document_id'] = json.loads(managed.read_bytes())['id']
                else:
                    move['snapshot'] = self._snapshot(self.config.path_for(directory))
                reverse = {**move, 'source': destination, 'destination': directory}
                del after['meta'][directory]
                if action == 'move':
                    after['meta'][destination] = meta
                else:
                    after['meta'][directory] = {**meta, 'deleted': True, 'trash': destination, 'project': project}
            else:
                raise ValueError('Unknown project management action')
            after.setdefault('receipts', {})[operation_id] = fingerprint
            if action == 'open':
                # Recents are navigation state and do not clear a redo branch.
                self._commit(before, after)
            else:
                entry = self._entry(before, after, operation_id, action, move, reverse)
                after['history'] = after['history'][:after['cursor']] + [entry]
                after['cursor'] = len(after['history'])
                self._commit(before, after, move)
            return self.state()

    def history(self, action, expected_revision):
        with self.config.lock, self.files.lock:
            before = self._load()
            self._validate_revision(before, expected_revision)
            if action not in ('undo', 'redo'):
                raise ValueError('Expected undo or redo')
            cursor = before['cursor']
            index = cursor - 1 if action == 'undo' else cursor
            if index < 0 or index >= len(before['history']):
                return self.state()
            entry = before['history'][index]
            after = copy.deepcopy(before)
            prefix = 'before' if action == 'undo' else 'after'
            if 'delta' in entry:
                changed = _patch({key: before[key] for key in ('meta', 'library')}, entry['inverse' if action == 'undo' else 'delta'])
                after.update(changed)
            else:
                # Read histories created by the first experimental workspace.
                after['meta'] = copy.deepcopy(entry[prefix + '_meta'])
                after['library'] = copy.deepcopy(entry[prefix + '_library'])
            after['cursor'] += -1 if action == 'undo' else 1
            relocation = entry.get('backward' if action == 'undo' else 'forward')
            self._commit(before, after, relocation)
            result = self.state()
            if relocation:
                result['relocation'] = {key: relocation[key] for key in ('source', 'destination')}
            return result

    def install_runtime(self, directory):
        project = self.config.path_for(directory, writable=True)
        dest = self.config.path_for('/'.join(filter(None, (directory, 'Design/studio'))), writable=True)
        dest.mkdir(parents=True, exist_ok=True)
        for source in RUNTIME.iterdir():
            if source.suffix in ('.html', '.js', '.css'):
                target = self.config.path_for((dest / source.name).relative_to(self.config.root).as_posix(), writable=True)
                data = source.read_bytes()
                if not target.exists() or target.read_bytes() != data:
                    atomic_write(target, data)
        return project

    def session(self, directory, capture=False):
        self.install_runtime(directory)
        directory = relative(directory)
        canonical = '/'.join(filter(None, (directory, 'Design/studio/runtime.html')))
        entry = '/'.join(filter(None, (directory, 'Design/studio/' + ('capture.html' if capture else 'runtime.html'))))
        project = self.studio.websites.register(str(self.config.root), directory, canonical)
        return self.studio.websites.create(str(self.config.root), entry, project['id'])

    def _copy(self, source, destination):
        source, destination = relative(source), relative(destination)
        src, dest = self.config.path_for(source), self.config.path_for(destination, writable=True)
        if not destination or dest.exists() or dest.is_relative_to(src) or src.is_relative_to(dest):
            raise ConflictError('Choose a new project directory outside the source')
        self._validate_tree(src)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns('.vault-rag', '.git', '.DS_Store'))
        return dest

    def copy_project(self, source, destination):
        with self.config.lock, self.files.lock:
            display_name = self._load()['meta'].get(relative(source), {}).get('name')
            dest = self._copy(source, destination)
            managed = dest / 'Design/studio/project.json'
            if managed.exists():
                document = json.loads(managed.read_text())
                document['id'] = uuid.uuid4().hex
                document['name'] = str(display_name or document['name']) + ' Copy'
                atomic_write(managed, _bytes(document))
            spec = self.studio._find_spec_file(dest)
            if spec:
                value = json.loads(spec.read_text())
                value['project']['id'] = uuid.uuid4().hex
                value['project']['name'] = str(display_name or value['project'].get('name') or Path(source).name) + ' Copy'
                atomic_write(spec, _bytes(value))
            self.record_creation(destination, 'Duplicate project')
            self.files.changed(destination)
            return {'ok': True, 'directory': destination, 'project': self.studio._project_summary(dest, self.config.root)}

    def migrate(self, source, destination):
        """Copy first; browser captures each authored page in the isolated copy."""
        with self.config.lock, self.files.lock:
            summary = self.studio._project_summary(self.config.path_for(source), self.config.root)
            if not summary:
                raise ValueError('Design project not found')
            dest = self._copy(source, destination)
            recovery = self._recover_legacy_declarations(dest)
            value = self.documents.create(destination, summary['name'], summary['width'], summary['height'])
            self.install_runtime(destination)
            spec = json.loads(self.studio._find_spec_file(dest).read_text())
            assets_rel = spec.get('project', {}).get('sources', {}).get('assets', 'Design/Assets/manifest.json')
            manifest_path = self.config.path_for(destination + '/' + assets_rel)
            assets = {}
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text())
                for item in manifest.get('assets', []):
                    path = manifest_path.parent / item.get('path', '')
                    resolved = self.config.path_for(path.relative_to(self.config.root).as_posix())
                    if resolved.is_file():
                        asset = copy.deepcopy(item)
                        asset['path'] = resolved.relative_to(dest).as_posix()
                        asset['name'] = item.get('name') or path.name
                        asset_id = str(item.get('id') or 'asset-' + hashlib.sha256(asset['path'].encode()).hexdigest()[:24])
                        if asset_id in assets and assets[asset_id]['path'] != asset['path']:
                            asset_id += '-' + hashlib.sha256(asset['path'].encode()).hexdigest()[:8]
                        asset['id'] = asset_id
                        assets[asset_id] = asset
            document = value['document']
            document['assets'] = assets
            document['migration'] = {'source': source, 'status': 'capture_required', 'boards': summary['screens'],
                                     'entry': 'Design/UI/Site/screen.html', 'createdAt': time.time(), 'recovery': recovery}
            value = self.documents.apply(destination, [{'type': 'document.replace', 'document': document}],
                                         value['revision'], uuid.uuid4().hex, label='Prepare legacy migration')
            self.record_creation(destination, 'Convert legacy project')
            return {**value, 'session': self.session(destination, capture=True)}

    def _recover_legacy_declarations(self, project):
        """Restore only referenced missing literal bindings in a copied project.

        Old versions rewrote screens.js wholesale. Some projects preserve a
        native source snapshot; its metadata must never replace newer boards.
        No recovered expression or project code is evaluated by the service.
        """
        from vault_rag.design_literals import bindings, declarations, literal_values, tokens, insert_declarations, IDENTIFIER
        spec = json.loads(self.studio._find_spec_file(project).read_text(encoding='utf-8'))
        screens_rel = relative(spec.get('project', {}).get('sources', {}).get('screens', 'Design/UI/Site/screens.js'))
        target = self.config.path_for((project / screens_rel).relative_to(self.config.root).as_posix(), writable=True)
        backup = self.config.path_for((project / 'Design/Assets/source' / Path(screens_rel).name).relative_to(self.config.root).as_posix())
        if target.suffix.lower() != '.js' or not target.is_file() or not backup.is_file() or target == backup:
            return []
        current, original = target.read_bytes().decode('utf-8'), backup.read_bytes().decode('utf-8')
        present = bindings(current)
        needed = set()
        for path in target.parent.glob('*.js'):
            self.config.path_for(path.relative_to(self.config.root).as_posix())
            if path.is_file() and path.stat().st_size <= 8 * 1024 * 1024:
                needed.update(value for value, _, _ in tokens(path.read_text(encoding='utf-8')) if IDENTIFIER.fullmatch(value))
        literals = literal_values(original)
        names = sorted(set(literals) & needed - present - {'screens', 'variants', 'boards', '__data'})
        if not names:
            return []
        kinds = {item['name']: item['kind'] for item in declarations(original)}
        prefix = '/* LeafLoom: recovered missing literal declarations from preserved source. */\n'
        prefix += ''.join(kinds.get(name, 'const') + ' ' + name + ' = ' + json.dumps(literals[name], ensure_ascii=False, allow_nan=False) + ';\n' for name in names)
        atomic_write(target, insert_declarations(current, prefix).encode('utf-8'))
        return [{'name': name, 'path': screens_rel, 'from': backup.relative_to(project).as_posix(), 'method': 'static-literal'} for name in names]

    def finish_migration(self, directory, pages, expected_revision, operation_id):
        value = self.documents.read(directory)
        doc = value['document']
        if doc.get('migration', {}).get('status') != 'capture_required':
            raise ValueError('No pending migration in this project')
        expected_ids = {p['id'] for p in doc['migration']['boards']}
        if not isinstance(pages, list) or any(not isinstance(page, dict) or not isinstance(page.get('id'), str) for page in pages):
            raise ValueError('Capture pages must be an array with stable identities')
        actual_ids = {page['id'] for page in pages}
        if len(actual_ids) != len(pages) or not expected_ids <= actual_ids:
            raise ValueError('Capture must include every legacy artboard')
        variants = validate_page_contexts(pages)
        if any(page['id'] in expected_ids and 'contextSource' in page.get('migration', {}) for page in pages):
            raise ValueError('Source artboards cannot be replaced by context variants')
        if set(variants) != actual_ids - expected_ids or any(owner not in expected_ids for owner in variants.values()):
            raise ValueError('Extra capture pages must be declared context variants of a source artboard')
        doc['pages'] = pages
        doc['migration']['status'] = 'converted'
        report = {'pages': len(pages), 'source_pages': len(expected_ids), 'context_variants': len(variants),
                  'nodes': sum(1 for p in pages for _ in _walk(p['nodes'])),
                  'method': 'authored DOM/CSS; original scripts retained in copied source',
                  'retained': [{'kind': 'source_copy', 'count': 1, 'description': 'Original HTML, CSS, scripts and assets remain in the project copy; the source project was not changed'},
                               {'kind': 'assets', 'count': len(doc['assets']), 'description': 'Registered asset references retained'}],
                  'converted': [], 'unsupported': [], 'warnings': []}
        if variants:
            report['converted'].append({'kind': 'context_variants', 'count': len(variants),
                                        'description': 'Context-dependent screens captured as linked page variants'})
        for page in pages:
            metadata = page.get('migration', {})
            captured = metadata.get('report', {})
            if not isinstance(captured, dict):
                raise ValueError('Capture report must be an object')
            # Older clients still get an accurate basic report from their
            # retained interaction metadata, rather than a false "all kept".
            if not captured:
                interactions = metadata.get('interactions', {})
                captured = {'retained': [{'kind': 'authored_nodes', 'count': sum(1 for _ in _walk(page['nodes'])),
                                         'description': 'Editable authored DOM layers and readable CSS'}], 'converted': [], 'unsupported': []}
                for field, kind, description in (
                        ('navigation', 'navigation', 'Declarative page links converted to managed navigation'),
                        ('switches', 'switches', 'Recognized switches converted to editable scripts')):
                    if interactions.get(field):
                        captured['converted'].append({'kind': kind, 'count': interactions[field], 'description': description})
                if interactions.get('scriptSources'):
                    captured['unsupported'].append({'kind': 'script_runtime', 'count': len(interactions['scriptSources']),
                                                     'description': 'Original scripts are kept in the source copy; arbitrary runtime behavior is not replayed'})
                if interactions.get('inlineHandlers'):
                    captured['unsupported'].append({'kind': 'inline_handlers', 'count': interactions['inlineHandlers'],
                                                     'description': 'Inline event handlers were omitted'})
                if metadata.get('unavailableStylesheets'):
                    captured['unsupported'].append({'kind': 'unreadable_stylesheets', 'count': len(metadata['unavailableStylesheets']),
                                                     'description': 'Unreadable stylesheets were omitted'})
            for category in ('retained', 'converted', 'unsupported'):
                items = captured.get(category, [])
                if not isinstance(items, list):
                    raise ValueError('Capture report categories must be arrays')
                for item in items:
                    if (not isinstance(item, dict) or not isinstance(item.get('kind'), str)
                            or not isinstance(item.get('description'), str) or isinstance(item.get('count'), bool)
                            or not isinstance(item.get('count'), int) or item['count'] < 0):
                        raise ValueError('Capture report entries require kind, description and a nonnegative count')
                    report[category].append({**copy.deepcopy(item), 'page_id': page['id'], 'page_name': page.get('name', page['id'])})
            for warning in metadata.get('warnings', []):
                if isinstance(warning, str) and warning not in report['warnings']:
                    report['warnings'].append(warning)
        report['fidelity'] = 'review_required' if report['unsupported'] or report['warnings'] else 'converted'
        doc['migration']['report'] = report
        return self.documents.apply(directory, [{'type': 'document.replace', 'document': doc}], expected_revision, operation_id,
                                    label='Import legacy pages')

    def _library_summary(self, item):
        return {key: item[key] for key in ('id', 'name', 'kind', 'version', 'source_project') if key in item}

    def library(self):
        return self.state()

    def _dependencies(self, document, kind, item_id, directory):
        """Collect reachable resources, including typed references and module imports."""
        tables = {'component': 'components', 'asset': 'assets', 'style': 'styles', 'script': 'scripts', 'page': 'pages'}
        source = {key: document.get(table, {}) for key, table in tables.items() if key != 'page'}
        source['asset'] = dict(source['asset'])
        source['page'] = {page['id']: page for page in document.get('pages', [])}
        selected = {key: {} for key in tables}
        paths = {asset['path']: aid for aid, asset in source['asset'].items() if asset.get('path')}
        script_paths = {value.get('path', key): key for key, value in source['script'].items() if isinstance(value, dict)}
        import posixpath

        def asset_reference(name, base_path=''):
            if name in source['asset']:
                add('asset', name)
                return
            path = AssetReferences.path(name, base_path)
            if not path:
                return
            if path in paths:
                add('asset', paths[path])
                return
            # ctx.assets.resolve also accepts a local project path. Preserve
            # that fallback without importing files outside this project.
            target = self.config.path_for(directory + '/' + path)
            if target.is_file():
                asset_id = 'library-path-' + hashlib.sha256(path.encode()).hexdigest()[:24]
                source['asset'][asset_id] = {'id': asset_id, 'name': target.name, 'path': path,
                                              'mime': mimetypes.guess_type(path)[0] or 'application/octet-stream', 'size': target.stat().st_size}
                paths[path] = asset_id
                add('asset', asset_id)

        def add(resource_kind, key):
            if key in selected[resource_kind]:
                return
            value = source[resource_kind].get(key)
            if value is None:
                raise ValueError(f'Missing shared-library {resource_kind}: {key}')
            selected[resource_kind][key] = copy.deepcopy(value)
            scan(value, value.get('path', '') if isinstance(value, dict) else '')
            if resource_kind == 'asset' and Path(value.get('path', '')).suffix.lower() in ('.css', '.svg', '.js', '.mjs', '.json'):
                path = self.config.path_for(directory + '/' + value['path'])
                if path.is_file() and path.stat().st_size <= 2 * 1024 * 1024:
                    scan(path.read_text(encoding='utf-8'), value['path'])

        def scan(value, module_path=''):
            if isinstance(value, dict):
                typed = {'assetId': 'asset', 'componentId': 'component', 'pageId': 'page', 'navigateTo': 'page',
                         'scriptId': 'script', 'moduleId': 'script', 'styleId': 'style'}
                for key, child in value.items():
                    if key in typed and isinstance(child, str) and child:
                        add(typed[key], child)
                    elif key == 'styleIds' and isinstance(child, list):
                        for style_id in child:
                            add('style', style_id)
                    else:
                        if key in ('src', 'href', 'xlink:href', 'poster') and isinstance(child, str):
                            asset_reference(child, module_path)
                        elif key in ('srcset', 'imagesrcset') and isinstance(child, str):
                            for reference in _srcset_urls(child):
                                asset_reference(reference, module_path)
                        scan(child, module_path)
            elif isinstance(value, list):
                for child in value:
                    scan(child, module_path)
            elif isinstance(value, str):
                for path, aid in list(paths.items()):
                    if path in value:
                        add('asset', aid)
                for reference in script_references(value):
                    if reference['kind'] == 'asset':
                        asset_reference(reference['value'])
                    elif reference['kind'] == 'page' and reference['value'] in source['page']:
                        add('page', reference['value'])
                for match in re.finditer(r'(?:from\s*|import\s*\(?\s*)[\"\']([^\"\']+)[\"\']', value):
                    path = posixpath.normpath(posixpath.join(posixpath.dirname(module_path), match[1]))
                    script_id = script_paths.get(path) or (match[1] if match[1] in source['script'] else None)
                    if script_id:
                        add('script', script_id)
                for match in re.finditer(r'url\(\s*[\"\']?([^\"\')]+)|(?:src|href)=[\"\']([^\"\']+)', value):
                    asset_reference(match[1] or match[2], module_path)
                if '<' in value:
                    parser = _ExportHTMLReferences(lambda reference: asset_reference(reference, module_path))
                    parser.feed(value)

        add(kind, item_id)
        return selected

    def publish(self, directory, kind, item_id, expected_revision=None, operation_id=None):
        with self.config.lock, self.files.lock:
            before = self._load()
            operation_id = operation_id or uuid.uuid4().hex
            fingerprint = _digest({'directory': directory, 'kind': kind, 'item_id': item_id})
            if self._request(before, operation_id, fingerprint):
                return self.library()
            self._validate_revision(before, expected_revision)
            document = self.documents.read(directory)['document']
            # Library entries are portable source snapshots. Project-scoped keys
            # must never attach themselves to an unrelated destination binding.
            # The resolver copies, so neither source nor locale data is modified.
            from vault_rag.design_bindings import resolve_document
            document = resolve_document(document)
            def strip_links(props):
                props.pop('bindingKey', None)
                overrides = props.get('overrides', {})
                for override in overrides.values() if isinstance(overrides, dict) else ():
                    if isinstance(override, dict) and isinstance(override.get('props'), dict):
                        strip_links(override['props'])
            for nodes in ([page['nodes'] for page in document['pages']] +
                          [[component['node']] for component in document['components'].values()]):
                for node in _walk(nodes):
                    strip_links(node.get('props', {}))
            table = {'component': 'components', 'asset': 'assets', 'style': 'styles', 'script': 'scripts'}.get(kind)
            if not table or item_id not in document.get(table, {}):
                raise ValueError('Library source not found')
            after = copy.deepcopy(before)
            key = hashlib.sha256((document['id'] + ':' + kind + ':' + item_id).encode()).hexdigest()[:32]
            previous = after['library'].get(key, {})
            version = previous.get('version', 0) + 1
            value = copy.deepcopy(document[table][item_id])
            resources = {}
            dependencies = self._dependencies(document, kind, item_id, directory)
            for aid, asset in dependencies['asset'].items():
                if not isinstance(asset.get('path'), str):
                    continue
                path = self.config.path_for(directory + '/' + asset['path'])
                if not path.is_file():
                    raise ValueError('Missing library resource: ' + aid)
                data = path.read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                blob = self._state('library-blobs', digest)
                blob.parent.mkdir(parents=True, exist_ok=True)
                if blob.exists() and hashlib.sha256(blob.read_bytes()).hexdigest() != digest:
                    raise ConflictError('Shared library recovery blob changed externally')
                if not blob.exists():
                    atomic_write(blob, data)
                resources[aid] = {**asset, 'sha256': digest}
            entry = {'id': key, 'name': value.get('name', item_id) if isinstance(value, dict) else item_id,
                     'kind': kind, 'version': version, 'source_project': document['id'], 'source_id': item_id,
                     'value': value, 'assets': resources, 'components': dependencies['component'],
                     'pages': list(dependencies['page'].values()), 'scripts': dependencies['script'], 'styles': dependencies['style'],
                     'versions': previous.get('versions', {})}
            entry['versions'][str(version)] = {k: copy.deepcopy(v) for k, v in entry.items() if k != 'versions'}
            after['library'][key] = entry
            after.setdefault('receipts', {})[operation_id] = fingerprint
            after['history'] = after['history'][:after['cursor']] + [self._entry(before, after, operation_id, 'Publish library')]
            after['cursor'] = len(after['history'])
            self._commit(before, after)
            return self.library()

    def import_library(self, directory, item_id, expected_revision, operation_id, version=None, *, include_document=True):
        with self.config.lock, self.files.lock:
            request_identity = {'type': 'library.import', 'item_id': item_id, 'version': version}
            replay = self.documents.replay(directory, operation_id, request_identity, include_document=include_document)
            if replay:
                return replay
            item = self._load()['library'].get(item_id)
            if not item:
                raise ValueError('Library item not found')
            if version is not None:
                item = item.get('versions', {}).get(str(version))
                if not item:
                    raise ValueError('Library version not found')
            value = self.documents.read(directory)
            if expected_revision != value['revision']:
                raise ConflictError('Design revision changed; refresh before importing a library version')
            doc = value['document']
            namespace = 'lib-' + item_id[:12] + '-'
            # IDs stay stable across explicit version updates, including all
            # component descendants. Asset files retain their relative layout.
            def mapped(kind, key):
                return namespace + kind + '-' + hashlib.sha256(key.encode()).hexdigest()[:24]
            maps = {kind: {} for kind in ('asset', 'component', 'page', 'node', 'script', 'style')}
            paths = {}
            for kind, table in (('asset', 'assets'), ('component', 'components'), ('script', 'scripts'), ('style', 'styles')):
                maps[kind] = {key: mapped(kind, key) for key in item.get(table, {})}
            maps['page'] = {page['id']: mapped('page', page['id']) for page in item.get('pages', [])}
            for nodes in ([page['nodes'] for page in item.get('pages', [])] + [[component['node']] for component in item.get('components', {}).values()]):
                maps['node'].update({node['id']: mapped('node', node['id']) for node in _walk(nodes)})
            imported_before = any(isinstance(entry, dict) and entry.get('library', {}).get('id') == item_id
                                  for table in ('assets', 'components', 'scripts', 'styles') for entry in doc.get(table, {}).values())
            for aid, asset in item['assets'].items():
                new_id = maps['asset'][aid]
                path = f'Design/Assets/Library/{item_id}/v{item["version"]}/{relative(asset["path"])}'
                paths[asset['path']] = path
                target = self.config.path_for(directory + '/' + path, writable=True)
                target.parent.mkdir(parents=True, exist_ok=True)
                blob = self._state('library-blobs', asset['sha256'])
                data = blob.read_bytes()
                if hashlib.sha256(data).hexdigest() != asset['sha256']:
                    raise ConflictError('Shared library source blob changed externally')
                if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != asset['sha256']:
                    raise ConflictError('Imported library media changed externally')
                if not target.exists():
                    atomic_write(target, data)
                doc['assets'][new_id] = {**asset, 'id': new_id, 'path': path, 'library': {'id': item_id, 'version': item['version']}}
            for sid, script in item.get('scripts', {}).items():
                if isinstance(script, dict) and script.get('path'):
                    paths[script['path']] = f'Design/Library/{item_id}/{relative(script["path"])}'
            typed = {'assetId': 'asset', 'componentId': 'component', 'pageId': 'page', 'navigateTo': 'page',
                     'scriptId': 'script', 'moduleId': 'script', 'styleId': 'style', 'targetId': 'node', 'nodeId': 'node'}
            ids = {key: value for mapping in maps.values() for key, value in mapping.items()}
            def remap_source(source, module_path=''):
                def resolve(kind, name):
                    if name in maps.get(kind, {}):
                        return maps[kind][name]
                    if kind == 'asset':
                        return paths.get(AssetReferences.path(name))
                    if kind == 'module':
                        if name in maps['script']:
                            return maps['script'][name]
                        import posixpath
                        target = posixpath.normpath(posixpath.join(posixpath.dirname(module_path), name)) if name.startswith('.') else name.lstrip('/')
                        if target in paths:
                            current = paths.get(module_path, module_path)
                            relative_path = posixpath.relpath(paths[target], posixpath.dirname(current) or '.')
                            return relative_path if relative_path.startswith('.') else './' + relative_path
                    return None
                return rewrite_script(source, resolve)
            def remap(value):
                if isinstance(value, dict):
                    result = {}
                    for key, child in value.items():
                        if key in typed and isinstance(child, str):
                            result[key] = maps[typed[key]].get(child, child)
                        elif key == 'styleIds' and isinstance(child, list):
                            result[key] = [maps['style'].get(style_id, style_id) for style_id in child]
                        elif key == 'id' and isinstance(child, str):
                            result[key] = ids.get(child, child)
                        elif key == 'overrides' and isinstance(child, dict):
                            result[key] = {maps['node'].get(oid, oid): remap(override) for oid, override in child.items()}
                        elif key == 'source' and isinstance(child, str):
                            result[key] = remap_source(child, value.get('path', ''))
                        else:
                            result[key] = remap(child)
                    return result
                if isinstance(value, list):
                    return [remap(v) for v in value]
                if isinstance(value, str):
                    # Replace longest paths first to avoid replacing a parent of
                    # a later resource. Quoted IDs also cover ctx.asset()/refs().
                    for old, new in sorted(paths.items(), key=lambda item: len(item[0]), reverse=True):
                        value = value.replace(old, new)
                    for old, new in ids.items():
                        value = value.replace("'" + old + "'", "'" + new + "'").replace('"' + old + '"', '"' + new + '"')
                    return value
                return value
            for cid, component in item.get('components', {}).items():
                imported = remap(component)
                imported['id'] = maps['component'][cid]
                imported['library'] = {'id': item_id, 'version': item['version']}
                doc['components'][maps['component'][cid]] = imported
            # Embedded pages carry their dependency graph into the destination.
            for page in item.get('pages', []):
                imported = remap(page)
                imported['id'] = maps['page'][page['id']]
                doc['pages'] = [p for p in doc['pages'] if p['id'] != imported['id']] + [imported]
            table = {'component': 'components', 'asset': 'assets', 'style': 'styles', 'script': 'scripts'}[item['kind']]
            new_id = maps[item['kind']].get(item['source_id'], mapped(item['kind'], item['source_id']))
            imported_value = remap(item['value'])
            if isinstance(imported_value, dict):
                imported_value['id'] = new_id
                imported_value['library'] = {'id': item_id, 'version': item['version']}
            if table != 'assets':
                doc.setdefault(table, {})[new_id] = imported_value
            for sid, script in item.get('scripts', {}).items():
                imported = remap(script) if isinstance(script, dict) else remap_source(script) if isinstance(script, str) else script
                if isinstance(imported, dict):
                    imported.update(id=maps['script'][sid], library={'id': item_id, 'version': item['version']})
                doc.setdefault('scripts', {})[maps['script'][sid]] = imported
            for sid, style in item.get('styles', {}).items():
                doc.setdefault('styles', {})[maps['style'][sid]] = remap(style)
            return self.documents.apply(directory, [{'type': 'document.replace', 'document': doc}], expected_revision, operation_id,
                                        label='Update shared library' if imported_before else 'Import shared library', request_identity=request_identity,
                                        include_document=include_document)

    def export_preflight(self, directory, page_ids, expected_revision=None):
        value = self.documents.read(directory)
        if expected_revision and value['revision'] != expected_revision:
            raise ConflictError('Design changed; refresh before exporting')
        from vault_rag.design_export_selection import select_export
        _, report = select_export(value['document'], page_ids)
        return {'ok': True, 'revision': value['revision'],
                'missing_pages': report['missing_pages'], 'dynamic_warning': report['dynamic_warning']}

    def export(self, directory, page_ids=None, expected_revision=None, *, snapshot_dir=None):
        value = self.documents.read(directory)
        if expected_revision and value['revision'] != expected_revision:
            raise ConflictError('Design changed; refresh before exporting')
        from vault_rag.design_presenter import audience_document
        document = audience_document(value['document'])
        selection = None
        if page_ids is not None:
            from vault_rag.design_export_selection import select_export
            document, selection = select_export(document, page_ids)
        with self.config.lock, self.files.lock:
            document['name'] = self._load()['meta'].get(relative(directory), {}).get('name') or document['name']
        if snapshot_dir is None:
            self.install_runtime(directory)
        project = self.config.path_for(directory)
        # Export the resource graph, not archives, validation records or unrelated
        # source files that happen to live beside a design.
        from urllib.parse import unquote, urlsplit
        import posixpath
        resources = {asset['path'] for asset in document.get('assets', {}).values() if asset.get('path')}
        if selection is not None:
            resources.update(selection['paths'])
            for path in resources:
                if not self.config.path_for(directory + '/' + relative(path)).is_file():
                    raise ValueError('Missing export resource: ' + path)
        virtual_scripts = {(item.get('path', key) if isinstance(item, dict) else key)
                           for key, item in document.get('scripts', {}).items()
                           if isinstance(item, str) or isinstance(item, dict) and isinstance(item.get('source'), str)}
        scanned = set()
        def add(reference, base=''):
            if not isinstance(reference, str):
                return
            reference = reference.strip()
            if not reference or reference.lower().startswith(('#', 'data:', 'blob:')):
                return
            marker = '__STUDIO_ASSET__/'
            if reference.startswith(marker):
                reference, base = reference[len(marker):], ''
            elif reference in document.get('scripts', {}):
                # A registry module ID is resolved by the runtime, regardless
                # of the importing module's directory.
                return
            try:
                url = urlsplit(reference)
            except ValueError:
                return
            if url.scheme or url.netloc:
                return
            decoded = unquote(url.path)
            if decoded.startswith('/'):
                base = ''
            path = posixpath.normpath(posixpath.join(base, decoded.lstrip('/')))
            try:
                path = relative(path)
                target = self.config.path_for(directory + '/' + path)
            except ValueError:
                return
            if path.startswith('Design/exports/') or path.startswith('Design/studio/'):
                return
            if target.is_file():
                resources.add(path)
            elif path in virtual_scripts:
                return
            elif selection is not None:
                raise ValueError('Missing export resource: ' + path)
        def scan(value, base=''):
            if isinstance(value, dict):
                if isinstance(value.get('basePath'), str):
                    base = value['basePath']
                    if not base.endswith('/'):
                        base = posixpath.dirname(base)
                for key, child in value.items():
                    if key in ('src', 'href', 'xlink:href', 'path', 'poster') and isinstance(child, str): add(child, base)
                    if key in ('srcset', 'imagesrcset') and isinstance(child, str):
                        for reference in _srcset_urls(child): add(reference, base)
                    child_base = posixpath.dirname(value['path']) if key == 'source' and isinstance(value.get('path'), str) else base
                    scan(child, child_base)
            elif isinstance(value, list):
                for child in value: scan(child, base)
            elif isinstance(value, str):
                for match in re.finditer(r'__STUDIO_ASSET__/([^\s\"\'<>\)]+)', value): add(match[1])
                for match in re.finditer(r'url\(\s*[\"\']?([^\"\')]+)|(?:src|href)=[\"\']([^\"\']+)|(?:from\s*|import\s*\(?\s*)[\"\']([^\"\']+)', value):
                    add(next(x for x in match.groups() if x is not None), base)
                for match in re.finditer(r'@import\s+[\"\']([^\"\']+)', value, re.I): add(match[1], base)
                if '<' in value:
                    parser = _ExportHTMLReferences(lambda reference: add(reference, base))
                    parser.feed(value)
        if selection is None:
            scan(document)
        else:
            for key in ('pages', 'assets', 'components', 'styles', 'bindings', 'variants'):
                scan(document.get(key, {}))
            for script_id, script in document.get('scripts', {}).items():
                scan(script, posixpath.dirname(script_id) if isinstance(script, str) else '')
        for script in document.get('scripts', {}).values():
            if isinstance(script, dict):
                add(script.get('path', ''))
                scan(script.get('source', ''), posixpath.dirname(script.get('path', '')))
        while resources - scanned:
            for rel in list(resources - scanned):
                scanned.add(rel)
                path = self.config.path_for(directory + '/' + rel)
                if path.suffix.lower() in ('.js', '.mjs', '.css', '.html', '.htm', '.svg', '.json') and path.stat().st_size <= 2 * 1024 * 1024:
                    text = path.read_text(encoding='utf-8')
                    scan(text, posixpath.dirname(rel))
                    if path.suffix.lower() in ('.js', '.mjs'):
                        if selection is not None:
                            # Imported local modules may reference asset IDs
                            # that do not appear in the selected page tree.
                            for ref in script_references(text):
                                if ref['kind'] != 'asset':
                                    continue
                                asset = value['document'].get('assets', {}).get(ref['value'])
                                if asset:
                                    document.setdefault('assets', {})[ref['value']] = copy.deepcopy(asset)
                                    add(asset.get('path', ''))
                                else:
                                    add(ref['value'])
                        document.setdefault('scripts', {})[rel] = {'id': rel, 'path': rel, 'source': text}
        if snapshot_dir is None:
            export_id = uuid.uuid4().hex
            export_rel = f'Design/exports/{export_id}'
            dest = self.config.path_for(directory + '/' + export_rel, writable=True)
        else:
            # Internal publication jobs write their immutable snapshot outside
            # the source project; ordinary HTML exports keep their old location.
            dest = Path(snapshot_dir)
        dest.mkdir(parents=True, exist_ok=False)
        for name in ('runtime.js', 'runtime.css'):
            atomic_write(dest / name, (RUNTIME / name).read_bytes())
        # Keep project-relative paths intact in the bundle and copy referenced assets.
        for rel in sorted(resources):
            path = self.config.path_for(directory + '/' + rel)
            if not path.is_file():
                raise ValueError('Missing export resource: ' + rel)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        data = 'window.STUDIO_DOCUMENT=' + json.dumps(document, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c') + ';\n'
        atomic_write(dest / 'document.js', data.encode())
        entry = '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + html.escape(document['name']) + '</title><link rel="stylesheet" href="runtime.css"></head><body><div id="studio-root"></div><script src="document.js"></script><script src="runtime.js"></script></body></html>'
        atomic_write(dest / 'index.html', entry.encode())
        bundle = dest.with_suffix('.zip')
        with zipfile.ZipFile(bundle, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in dest.rglob('*'):
                if path.is_file():
                    archive.write(path, path.relative_to(dest))
        if snapshot_dir is not None:
            return {'ok': True, 'snapshot_path': str(bundle), 'revision': value['revision']}
        session = self.session(directory)
        return {'ok': True, 'path': bundle.relative_to(self.config.root).as_posix(),
                'name': document['name'],
                'url': session['origin'] + '/' + export_rel + '.zip?session=' + session['id'],
                'preview_url': session['origin'] + '/' + export_rel + '/index.html?session=' + session['id'],
                'revision': value['revision'],
                **({'missing_pages': selection['missing_pages'], 'dynamic_warning': selection['dynamic_warning']} if selection is not None else {})}
