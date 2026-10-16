"""Production HTTP MCP workflows with fictional notes and no real model or credentials."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from vault_rag.knowledge import Runtime
from vault_rag.local_state import ConflictError, digest
from vault_rag.web_server import create_app
from vault_rag.local_state import LocalConfig


class UnavailableModel:
    ready = False
    fingerprint = 'fictional-model'
    model_id = 'fictional-model'

    def status(self):
        return {'prepared': False, 'loaded': False}


class WorkspaceMcpTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name).resolve()
        self.root = self.home / 'notes'
        self.root.mkdir()
        for folder in ('Selected', 'Archive', 'Topics', 'Templates', 'Web', 'Daily'):
            (self.root / folder).mkdir()
        self.put('Selected/a.md', '---\nid: a\nverified_status: limited\ntags: [demo]\n---\n# Alpha\nshared evidence')
        self.put('Archive/b.md', '---\nid: b\ntags: [demo]\n---\n# Archive\nprivate evidence')
        self.put('Topics/topic.md', '# Topic\n[[a]]')
        self.put('Web/page.html', '<!doctype html><title>Example page</title><h1>private evidence</h1>')
        self.config = LocalConfig(self.home / 'state')
        self.config.save({'root': str(self.root), 'include_roots': ['Selected'], 'wiki_roots': ['Topics']})
        self.runtime = Runtime(self.config)
        self.runtime.model = self.runtime.knowledge.model = UnavailableModel()
        self.addCleanup(self.runtime.stop)
        self.app = create_app(self.config, self.runtime, start_background=False)
        self.manager = TestClient(self.app, base_url='http://127.0.0.1:18080', client=('127.0.0.1', 12345))
        self.client = self.manager.__enter__()
        self.addCleanup(self.manager.__exit__, None, None, None)
        self.legacy = {'Authorization': 'Bearer ' + (self.config.directory / 'auth-token').read_text().strip()}
        self.ws = self.config.data['revision']
        self.runtime.catalog.scan()
        self.local = self.configure('local', enabled=True, write=True)['token']

    def put(self, path, text):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode('utf-8'))
        return p

    def configure(self, kind, **values):
        response = self.client.post('/api/mcp-access', headers=self.legacy,
                                    json={'kind': kind, **values})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def request(self, method, params=None, token='local'):
        headers = {'Accept': 'application/json, text/event-stream'}
        if token == 'local':
            headers['Authorization'] = 'Bearer ' + self.local
        elif token == 'legacy':
            headers.update(self.legacy)
        elif token:
            headers['Authorization'] = token
        return self.client.post('/mcp', headers=headers,
                                json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}})

    def call(self, name, args=None, *, token='local', error=None):
        deadline = time.monotonic() + 4
        while True:
            response = self.request('tools/call', {'name': name, 'arguments': args or {}}, token)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()['result']
            value = json.loads(result['content'][0]['text'])
            self.assertEqual(value, result['structuredContent'])
            if value.get('error_code') != 'metadata_pending' or time.monotonic() >= deadline:
                break
            time.sleep(.01)
        if error:
            self.assertTrue(result['isError'], value)
            self.assertEqual(value['error_code'], error, value)
        else:
            self.assertFalse(result.get('isError'), value)
        return value

    def read(self, path):
        return self.call('vault_read_note', {'note_id': path})

    def update(self, path, **values):
        read = self.read(path)
        return self.call('vault_update_note', {'path': path, 'workspace_revision': read['workspace_revision'],
                         'expected_revision': read['revision'], **values})

    def preview_commit(self, tool, **values):
        args = {'workspace_revision': self.ws, **values}
        preview = self.call(tool, args)
        self.assertTrue(preview['dry_run'])
        return self.call(tool, {**args, 'dry_run': False, 'operation_token': preview['operation_token']})

    def restore(self, kind, id, **overrides):
        record = self.call('vault_read_record', {'kind': kind, 'id': id})
        return self.call('vault_restore', {'kind': kind, 'id': id,
                         **{key: record[key] for key in ('workspace_revision', 'expected_revision', 'record_revision')}, **overrides})

    def test_discovery_scopes_and_structured_errors(self):
        tools = {t['name']: t for t in self.request('tools/list').json()['result']['tools']}
        self.assertEqual(len(tools), 23)
        self.assertTrue(tools['vault_find_notes']['annotations']['readOnlyHint'])
        self.assertTrue(tools['vault_delete']['annotations']['destructiveHint'])
        self.assertNotIn('ctx', tools['vault_read_note']['inputSchema']['properties'])
        for token in ('', 'legacy'):
            status = self.call('vault_index_status', token=token)
            self.assertFalse(status['capabilities']['read_workspace'])
            self.call('vault_read_note', {'note_id': 'Archive/b.md'}, token=token, error='permission_denied')
        self.assertEqual(self.read('Archive/b.md')['text'].splitlines()[-1], 'private evidence')
        self.assertIn('doctype', self.read('Web/page.html')['text'])
        self.assertIn('Topic', self.read('Topics/topic.md')['text'])
        found = self.call('vault_find_notes', {'query': 'private evidence'})
        self.assertEqual({row['path'] for row in found['results']}, {'Archive/b.md', 'Web/page.html'})
        self.assertEqual(len(self.call('vault_find_notes', {'tags': ['demo']})['results']), 2)
        rag = self.call('vault_search', {'query': 'private', 'mode': 'rag'})
        self.assertEqual(rag['results'], [])
        self.assertTrue(rag['degraded'])
        self.call('vault_get_note', {'note_id': 'Archive/b.md'}, token='', error='retrieval_failed')
        self.call('vault_read_note', {'note_id': 'no-such-id'}, error='not_found')

    def test_long_notes_unique_ids_and_snapshot_pagination(self):
        self.put('Archive/long.txt', '字' * 25001)
        self.put('Archive/duplicate.md', '---\nid: a\n---\nDuplicate')
        self.runtime.catalog.scan()
        read = self.read('Archive/long.txt')
        self.assertEqual(len(read['text']), 12000)
        second = self.call('vault_read_note', {'note_id': 'Archive/long.txt', 'offset': read['next_offset'], 'limit': 24000})
        self.assertIsNone(second['next_offset'])
        ambiguous = self.call('vault_read_note', {'note_id': 'a'}, error='ambiguous_note')
        self.assertEqual(len(ambiguous['candidates']), 2)
        page = self.call('vault_find_notes', {'limit': 1})
        next_page = self.call('vault_find_notes', {'limit': 1, 'cursor': page['next_cursor']})
        self.assertNotEqual(page['results'], next_page['results'])
        self.put('Archive/new.md', 'new')
        self.runtime.catalog.scan()
        self.call('vault_find_notes', {'limit': 1, 'cursor': page['next_cursor']}, error='stale_cursor')
        listing = self.call('vault_list_directory', {'path': 'Archive'})
        self.assertTrue(any(row['path'] == 'Archive/long.txt' for row in listing['results']))

    def test_edit_append_properties_bom_newlines_and_history_restore(self):
        path = 'Archive/encoding.md'
        original = b'\xef\xbb\xbf---\r\nid: encoding\r\n# keep comment\r\nunknown: "quoted"\r\n---\r\nAlpha\r\nBeta\r\n'
        (self.root / path).write_bytes(original)
        updated = self.update(path, mode='edit', edits=[{'old_text': 'Alpha', 'new_text': 'Gamma'}])
        raw = (self.root / path).read_bytes()
        self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
        self.assertIn(b'Gamma\r\nBeta\r\n', raw)
        read = self.read(path)
        self.call('vault_update_properties', {'path': path, 'workspace_revision': self.ws,
                  'expected_revision': read['revision'], 'updates': {'status': 'done'}})
        raw = (self.root / path).read_bytes()
        self.assertIn(b'# keep comment\r\n', raw)
        self.assertIn(b'unknown: "quoted"\r\n', raw)
        self.assertNotIn(b'\n', raw.replace(b'\r\n', b''))
        self.update(path, mode='append', text='Tail\r\n')
        self.assertTrue((self.root / path).read_bytes().endswith(b'Tail\r\n'))
        self.restore('history', updated['history_id'])
        self.assertEqual((self.root / path).read_bytes(), original)
        records = self.call('vault_list_records', {'kind': 'history', 'path': path, 'limit': 1})
        self.assertTrue(records['next_cursor'])

    def test_atomic_edit_rejections_and_optimistic_conflicts(self):
        path = 'Archive/b.md'
        read = self.read(path)
        base = {'path': path, 'workspace_revision': self.ws, 'expected_revision': read['revision'], 'mode': 'edit'}
        for edits in ([{'old_text': 'absent', 'new_text': ''}],
                      [{'old_text': 'private evidence', 'new_text': 'x'}, {'old_text': 'evidence', 'new_text': 'y'}],
                      [{'old_text': '#', 'new_text': 'z'}, {'old_text': '', 'new_text': 'z'}]):
            self.call('vault_update_note', {**base, 'edits': edits}, error='invalid_request')
            self.assertEqual(self.read(path)['revision'], read['revision'])
        self.put(path, 'outside edit')
        self.call('vault_update_note', {**base, 'mode': 'replace', 'text': 'bad'}, error='write_conflict')
        self.assertEqual((self.root / path).read_text(), 'outside edit')
        # A change during history capture must also survive the final save check.
        files = self.runtime.files
        history = files._history
        def changed_during_backup(p):
            result = history(p)
            p.write_text('new external edit')
            return result
        with patch.object(files, '_history', side_effect=changed_during_backup):
            with self.assertRaises(ConflictError):
                files.save(path, 'bad', digest(b'outside edit'))
        self.assertEqual((self.root / path).read_text(), 'new external edit')

    def test_templates_daily_query_graph_and_reindex(self):
        self.put('Templates/demo.md', '# {{date}}\n<% tp.file.cursor %>Demo')
        self.put('Templates/tpl-daily-note.md', '# {{date}}\nDaily')
        templates = self.call('vault_list_templates')
        self.assertEqual(len(templates['results']), 2)
        result = self.call('vault_create_note', {'path': 'Archive/template.md', 'workspace_revision': self.ws,
                           'template': 'Templates/demo.md'})
        self.assertIsInstance(result['cursor'], int)
        self.call('vault_create_note', {'path': 'Archive/template.md', 'workspace_revision': self.ws}, error='write_conflict')
        day = self.call('vault_daily_note', {'workspace_revision': self.ws, 'date': '2026-10-16'})
        self.assertTrue(day['created'])
        self.assertIn('# 2026-10-16', self.read(day['path'])['text'])
        self.assertFalse(self.call('vault_daily_note', {'workspace_revision': self.ws, 'date': '2026-10-16'})['created'])
        query = self.call('vault_query', {'query': 'TABLE file.name\nFROM "Archive"'})
        self.assertTrue(any(row['path'] == 'Archive/b.md' for row in query['results']))
        self.call('vault_query', {'query': 'LIST\nWHERE eval("danger")'}, error='invalid_request')
        links = self.call('vault_links', {'path': 'Selected/a.md'})
        self.assertEqual(links['results'][0]['source'], 'Topics/topic.md')
        graph = self.call('vault_graph', {'path': 'Selected/a.md'})
        self.assertEqual(len(graph['results']), 2)
        self.assertEqual(self.call('vault_reindex', {'workspace_revision': self.ws})['state'], 'queued')

    def test_directory_move_references_undo_and_conflicting_preview(self):
        self.call('vault_create_folder', {'path': 'Projects', 'workspace_revision': self.ws})
        self.put('Projects/a.md', '# Project\n[asset](asset.png)')
        (self.root / 'Projects/asset.png').write_bytes(b'fictional image')
        self.put('Archive/link.md', '[[Projects/a|Project]]\n```\n[[Projects/a]]\n```')
        moved = self.preview_commit('vault_move', path='Projects', destination='Renamed')
        self.assertTrue((self.root / 'Renamed/asset.png').exists())
        self.assertIn('[[Renamed/a|Project]]', self.read('Archive/link.md')['text'])
        self.assertIn('```\n[[Projects/a]]', self.read('Archive/link.md')['text'])
        self.restore('operations', moved['operation_id'])
        self.assertTrue((self.root / 'Projects/a.md').exists())
        preview = self.call('vault_move', {'path': 'Projects', 'destination': 'Other', 'workspace_revision': self.ws})
        (self.root / 'Projects/asset.png').write_bytes(b'changed')
        self.call('vault_move', {'path': 'Projects', 'destination': 'Other', 'workspace_revision': self.ws,
                  'dry_run': False, 'operation_token': preview['operation_token']}, error='write_conflict')
        self.assertFalse((self.root / 'Other').exists())

    def test_recoverable_delete_restore_conflicts_and_backup_changes(self):
        deleted = self.preview_commit('vault_delete', path='Archive/b.md')
        self.assertFalse((self.root / 'Archive/b.md').exists())
        record = self.call('vault_read_record', {'kind': 'trash', 'id': deleted['id']})
        self.put('Archive/b.md', 'new occupant')
        self.call('vault_restore', {'kind': 'trash', 'id': deleted['id'], **{k: record[k] for k in
                  ('workspace_revision', 'expected_revision', 'record_revision')}}, error='write_conflict')
        (self.root / 'Archive/b.md').unlink()
        self.restore('trash', deleted['id'])
        self.assertIn('private evidence', self.read('Archive/b.md')['text'])
        saved = self.update('Archive/b.md', text='updated')
        record = self.call('vault_read_record', {'kind': 'history', 'id': saved['history_id']})
        self.runtime.files.state_path('history', saved['history_id'], 'content').write_text('tampered backup')
        self.call('vault_restore', {'kind': 'history', 'id': saved['history_id'], **{k: record[k] for k in
                  ('workspace_revision', 'expected_revision', 'record_revision')}}, error='write_conflict')
        self.assertEqual(self.read('Archive/b.md')['text'], 'updated')

    def test_permissions_rotation_csrf_and_no_api_privilege(self):
        self.configure('local', enabled=True, write=False)
        self.call('vault_create_note', {'path': 'Archive/no.md', 'workspace_revision': self.ws}, error='permission_denied')
        self.read('Archive/b.md')
        self.configure('tunnel', enabled=True, write=True)
        tunnel = self.app.state.mcp_access.tunnel_authorization()
        created = self.call('vault_create_note', {'path': 'Archive/from-chatgpt.txt', 'workspace_revision': self.ws,
                            'text': 'chat'}, token=tunnel)
        self.assertTrue(created['saved'])
        self.assertEqual(self.client.get('/api/status', headers={'Authorization': tunnel}).status_code, 401)
        self.assertEqual(self.client.get('/api/status', headers={'Authorization': 'Bearer ' + self.local}).status_code, 401)
        self.configure('tunnel', enabled=True, write=False)
        self.assertEqual(self.request('tools/list', token=tunnel).status_code, 401)
        tunnel = self.app.state.mcp_access.tunnel_authorization()
        self.call('vault_create_note', {'path': 'Archive/no.md', 'workspace_revision': self.ws}, token=tunnel, error='permission_denied')
        previous = self.local
        self.local = self.configure('local', enabled=True, write=False, rotate=True)['token']
        self.assertEqual(self.request('tools/list', token='Bearer ' + previous).status_code, 401)
        self.assertEqual(self.request('tools/list', token='Bearer invalid').status_code, 401)
        malformed = self.client.post('/mcp', headers=[(b'Authorization', b'Bearer caf\xe9'),
            (b'Accept', b'application/json, text/event-stream')],
            json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}})
        self.assertEqual(malformed.status_code, 401)
        self.assertNotIn(self.local, (self.config.directory / 'mcp-access.json').read_text())
        self.assertNotIn('token', self.client.get('/api/mcp-access', headers=self.legacy).json())
        self.client.cookies.set('vault_session', self.legacy['Authorization'][7:])
        self.assertEqual(self.client.post('/api/mcp-access', json={'kind': 'local', 'enabled': True, 'write': True}).status_code, 403)
        self.configure('local', enabled=False, write=False)
        self.assertEqual(self.request('tools/list').status_code, 401)

    def test_root_switch_protected_subtrees_and_symlinks(self):
        for path in ('../outside.md', '.hidden.md', '.vault-rag/notes.md'):
            self.call('vault_create_note', {'path': path, 'workspace_revision': self.ws}, error='invalid_request')
        self.put('Blocked/a.md', 'note')
        self.put('Blocked/.secret', 'keep')
        self.call('vault_delete', {'path': 'Blocked', 'workspace_revision': self.ws}, error='invalid_request')
        self.assertTrue((self.root / 'Blocked/.secret').exists())
        try:
            (self.root / 'escape').symlink_to(self.home, target_is_directory=True)
        except OSError:
            pass  # Windows runners may lack symbolic-link privileges.
        else:
            self.call('vault_read_note', {'note_id': 'escape/test.md'}, error='invalid_request')
        next_root = self.home / 'other'
        next_root.mkdir()
        self.config.save({'root': str(next_root)})
        self.runtime.configuration_changed()
        self.call('vault_create_note', {'path': 'wrong.md', 'workspace_revision': self.ws}, error='write_conflict')
        self.assertFalse((next_root / 'wrong.md').exists())
        self.call('vault_read_note', {'note_id': 'Archive/b.md'}, error='not_found')

    def test_first_global_search_reports_pending_and_hydrates_unselected_notes(self):
        from vault_rag.catalog import Catalog
        catalog = Catalog(self.runtime.files, lazy=True)
        self.runtime.catalog = self.runtime.knowledge.catalog = catalog
        with patch.object(self.runtime, 'ensure_metadata', return_value=False):
            response = self.request('tools/call', {'name': 'vault_find_notes', 'arguments': {'query': 'private'}}).json()['result']
        self.assertTrue(response['isError'])
        self.assertEqual(response['structuredContent']['error_code'], 'metadata_pending')
        ready = self.call('vault_find_notes', {'query': 'private'})
        self.assertEqual(len(ready['results']), 2)

    def test_move_failure_keeps_external_edits_and_journal(self):
        self.put('Archive/ref.md', '[[Selected/a]]')
        import vault_rag.local_state as state
        original_write = state.atomic_write
        def fail_after_move(path, data):
            if Path(path) == self.root / 'Archive/ref.md' and b'Renamed' in data:
                Path(path).write_text('external change during move')
                raise OSError('fictional disk failure')
            return original_write(path, data)
        with patch.object(state, 'atomic_write', side_effect=fail_after_move):
            with self.assertRaises(ConflictError):
                self.runtime.files.move('Selected/a.md', 'Selected/Renamed.md')
        self.assertEqual((self.root / 'Archive/ref.md').read_text(), 'external change during move')
        self.assertTrue((self.root / 'Selected/a.md').exists())
        self.assertFalse((self.root / 'Selected/Renamed.md').exists())
        records = self.runtime.files.records('operations')
        self.assertEqual(records[0]['state'], 'partial')
        self.assertIn('Archive/ref.md', records[0]['conflicts'])

    def test_text_limits_uppercase_markdown_and_overlapping_occurrences(self):
        path = 'Archive/UPPER.MD'
        self.call('vault_create_note', {'path': path, 'workspace_revision': self.ws,
                  'text': '---\nid: upper-id\n---\naaa'})
        read = self.read(path)
        self.assertEqual(read['metadata']['id'], 'upper-id')
        self.assertEqual(self.read('upper-id')['path'], path)
        self.call('vault_update_note', {'path': path, 'workspace_revision': self.ws,
                  'expected_revision': read['revision'], 'mode': 'edit',
                  'edits': [{'old_text': 'aa', 'new_text': 'b'}]}, error='invalid_request')
        queried = self.call('vault_query', {'query': 'LIST\nWHERE id = "upper-id"'})
        self.assertEqual(queried['results'][0]['path'], path)
        oversized = 'x' * (10 * 1024 * 1024 + 1)
        with self.assertRaises(ValueError):self.runtime.files.create('Archive/too-big.md', text=oversized)
        self.assertFalse((self.root / 'Archive/too-big.md').exists())
        with self.assertRaises(ValueError):self.runtime.files.save(path, oversized, read['revision'])
        self.assertEqual(self.read(path)['revision'], read['revision'])

    def test_folder_trash_pagination_root_daily_and_credential_persistence(self):
        self.put('Folder/a.md', 'A')
        self.put('Folder/b.txt', 'B')
        (self.root / 'Folder/asset.png').write_bytes(b'asset')
        preview = self.call('vault_delete', {'path': 'Folder', 'workspace_revision': self.ws, 'limit': 1})
        self.assertEqual(len(preview['affected_paths']), 1)
        self.assertEqual(preview['total'], 4)
        self.assertTrue(preview['next_cursor'])
        deleted = self.call('vault_delete', {'path': 'Folder', 'workspace_revision': self.ws,
                            'dry_run': False, 'operation_token': preview['operation_token']})
        record = self.call('vault_read_record', {'kind': 'trash', 'id': deleted['id'], 'path_limit': 1})
        self.assertTrue(record['directory'])
        self.assertTrue(record['next_cursor'])
        self.restore('trash', deleted['id'])
        self.assertEqual((self.root / 'Folder/asset.png').read_bytes(), b'asset')
        from vault_rag.mcp_access import McpAccess
        persisted = McpAccess(self.config)
        self.assertEqual(persisted.principal('Bearer ' + self.local, 'legacy'), 'local')
        self.config.save({'daily_folder': ''})
        self.runtime.configuration_changed()
        daily = self.call('vault_daily_note', {'workspace_revision': self.config.data['revision'], 'date': '2026-10-17'})
        self.assertEqual(daily['path'], '2026-10-17.md')


if __name__ == '__main__':
    unittest.main()
