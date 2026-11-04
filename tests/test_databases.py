"""File-backed database contracts, using disposable fictional workspaces."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient
from vault_rag.catalog import Catalog
from vault_rag.databases import Databases
from vault_rag.knowledge import Runtime
from vault_rag.local_state import LocalConfig, ConflictError
from vault_rag.note_operations import NoteError
from vault_rag.web_server import create_app


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name); self.root = self.home / 'vault'; self.root.mkdir()
        self.config = LocalConfig(self.home / 'state'); self.config.save({'root': str(self.root), 'include_roots': []})
        self.runtime = Runtime(self.config); self.addCleanup(self.runtime.stop)
        self.db = Databases(self.config, self.runtime); self.ws = self.config.data['revision']
        self.db.command('Media.base', {'type': 'create'}, self.ws, operation_id='create-db')
        self.refresh()

    def refresh(self):
        self.runtime.catalog.scan()
        self.c = self.db.config_read('Media.base')

    def command(self, command, **kw):
        result = self.db.command('Media.base', command, self.ws, self.c['revision'], **kw)
        self.refresh(); return result

    def record(self, title='Example', **values):
        return self.command({'type': 'record.create', 'title': title, 'values': values}, operation_id='record-'+title)

    def test_four_views_and_restart(self):
        self.assertEqual([v['type'] for v in self.c['views']], ['table', 'list', 'cards', 'leafloomTimeline'])
        result = self.record(attachments=['[[cover.png]]'], start_date='2028-02-29', end_date='2028-03-02')
        other = Databases(self.config, self.runtime)
        for view in self.c['views']:
            page = other.query('Media.base', view['id'])
            self.assertEqual(page['results'][0]['path'], result['path'])
        self.assertEqual(self.config.data['include_roots'], [])

    def test_create_retries_no_duplicates_or_overwrite(self):
        command = {'type': 'record.create', 'title': 'Duplicate', 'values': {}}
        a = self.db.command('Media.base', command, self.ws, self.c['revision'], 'repeat')
        self.assertEqual(a, self.db.command('Media.base', command, self.ws, 'stale', 'repeat'))
        b = self.db.command('Media.base', command, self.ws, self.c['revision'], 'different')
        self.assertNotEqual(a['path'], b['path'])
        with self.assertRaises(ConflictError):
            self.db.command('Media.base', {**command, 'title': 'Changed'}, self.ws, self.c['revision'], 'repeat')
        # A crash after publishing but before the receipt completes recovers the same target.
        receipt = next(p for p in self.files_receipts() if json.loads(p.read_text()).get('result') == b)
        value = json.loads(receipt.read_text()); value.pop('result'); receipt.write_text(json.dumps(value))
        self.assertEqual(b, self.db.command('Media.base', command, self.ws, self.c['revision'], 'different'))
        self.assertEqual(len(list((self.root/'Media').glob('*.md'))), 2)

    def files_receipts(self):
        return (self.root/'.vault-rag/database-receipts').glob('*.json')

    def test_types_sort_filters_group_and_stale_cursor(self):
        self.command({'type': 'field.set', 'key': 'score', 'field': {'type': 'number'}, 'displayName': 'Score'})
        self.command({'type': 'field.set', 'key': 'done', 'field': {'type': 'checkbox'}})
        for name, value in [('Two', 2), ('Ten', 10), ('One', 1)]: self.record(name, score=value, done=False)
        view = self.c['views'][0]['id']
        self.command({'type': 'view.update', 'view_id': view, 'patch': {'sort': [{'property': 'score', 'direction': 'ASC'}], 'groupBy': {'property': 'done'}}})
        page = self.db.query('Media.base', view, limit=2)
        self.assertEqual([r['metadata']['score'] for r in page['results']], [1, 2]); self.assertEqual(page['groups'], {'False': 3})
        self.assertEqual(self.db.query('Media.base', view, cursor=page['next_cursor'])['results'][0]['metadata']['score'], 10)
        self.command({'type': 'view.update', 'view_id': view, 'patch': {'leafloom': {'conditions': [{'field': 'score', 'operator': 'gt', 'value': 2}]}}})
        with self.assertRaises(NoteError): self.db.query('Media.base', view, cursor=page['next_cursor'])
        self.assertEqual(self.db.query('Media.base', view)['total'], 1)
        with self.assertRaises(ValueError): self.record('Invalid number', score='2')

    def test_dates_and_atomic_conflicts_preserve_body(self):
        r = self.record('Dates', start_date='2028-02-29', end_date='2028-03-02')
        p = self.root/r['path']; p.write_text(p.read_text()+'# Original body\n')
        self.refresh(); row = self.db.query('Media.base')['results'][0]
        with self.assertRaises(ConflictError):
            self.command({'type': 'record.update', 'path': r['path'], 'record_revision': r['revision'], 'values': {'start_date': '2028-03-01'}})
        before = p.read_bytes()
        with self.assertRaises(ValueError):
            self.command({'type': 'record.update', 'path': r['path'], 'record_revision': row['revision'], 'values': {'start_date': '2028-03-04', 'end_date': '2028-03-03'}})
        self.assertEqual(p.read_bytes(), before)
        self.command({'type': 'record.update', 'path': r['path'], 'record_revision': row['revision'], 'values': {'start_date': '2028-03-01', 'end_date': '2028-03-04'}})
        self.assertIn('# Original body', p.read_text())
        with self.assertRaises(ValueError): self.record('Not leap', start_date='2027-02-29')

    def test_unknown_yaml_comments_and_field_removal(self):
        p = self.root/'Media.base'; p.write_text('# Preserve this\nunknown: original\n'+p.read_text())
        self.refresh(); self.command({'type': 'field.set', 'key': 'notes', 'field': {'type': 'text'}, 'displayName': 'Notes'})
        r = self.record(notes='retained')
        self.command({'type': 'field.remove', 'key': 'notes'})
        self.assertIn('# Preserve this', p.read_text()); self.assertIn('unknown: original', p.read_text())
        self.assertIn('notes: retained', (self.root/r['path']).read_text())
        with self.assertRaises(ValueError): self.command({'type': 'view.remove', 'view_id': 'missing'})

    def test_access_boundaries_and_stale_workspace(self):
        with self.assertRaises(ConflictError): self.db.command('Media.base', {'type': 'field.remove', 'key': 'cover'}, 'old', self.c['revision'])
        with self.assertRaises(ValueError): self.db.config_read('../outside.base')
        (self.root/'outside.md').write_text('# Outside')
        with self.assertRaises(ValueError):
            self.command({'type': 'record.update', 'path': 'outside.md', 'record_revision': '', 'values': {}})
        other = self.home/'other'; other.mkdir(); self.config.save({'root': str(other)})
        with self.assertRaises(ConflictError): self.db.command('Media.base', {'type': 'field.remove', 'key': 'cover'}, self.ws, self.c['revision'])

    def test_recoverable_delete_requires_preview(self):
        r = self.record()
        with self.assertRaises(ConflictError): self.command({'type': 'record.trash', 'path': r['path'], 'dry_run': False})
        preview = self.command({'type': 'record.trash', 'path': r['path']})
        self.command({'type': 'record.trash', 'path': r['path'], 'dry_run': False, 'operation_token': preview['operation_token']})
        self.assertFalse((self.root/r['path']).exists()); self.assertEqual(len(self.runtime.files.records('trash')), 1)

    def test_legacy_views_unchanged(self):
        self.record()
        (self.root/'Legacy.base').write_text('filters: file.inFolder("Media")\nviews:\n  - type: tasknotesKanban\n    name: Tasks\n')
        self.refresh(); legacy = self.runtime.catalog.base('Legacy.base')
        self.assertEqual(len(legacy['views'][0]['rows']), 1)
        self.assertEqual(legacy['views'][0]['type'], 'tasknotesKanban')

    def test_thousands_paginate_after_sort(self):
        for i in range(2400): (self.root/'Media'/f'{i:04}.md').write_text(f'---\ncategory: group-{i%4}\n---\n')
        self.refresh(); page = self.db.query('Media.base')
        self.assertEqual(page['total'], 2400); self.assertEqual(len(page['results']), 100)
        self.assertEqual(len(self.db.query('Media.base', cursor=page['next_cursor'], limit=200)['results']), 200)

    def test_http_and_mcp_permissions_and_versions(self):
        app = create_app(self.config, self.runtime, start_background=False)
        token = (self.config.directory/'auth-token').read_text().strip()
        with TestClient(app, base_url='http://127.0.0.1:18080', client=('127.0.0.1', 12345)) as client:
            client.cookies.set('vault_session', token)
            self.assertEqual(client.get('/api/bases/config?path=Media.base').status_code, 200)
            self.assertEqual(client.post('/api/bases/commands', json={}).status_code, 403)
            headers = {'X-Vault-CSRF': app.state.csrf}
            self.assertEqual(client.post('/api/bases/query', headers=headers, json={'path': 'Media.base'}).json()['total'], 0)
            def configure(write):
                return client.post('/api/mcp-access', headers=headers, json={'kind': 'local', 'enabled': True, 'write': write}).json()
            connection = configure(False)
            mcp_headers = {'Authorization': 'Bearer '+connection['token'], 'Accept': 'application/json, text/event-stream'}
            def call(name, args):
                response = client.post('/mcp', headers=mcp_headers, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': args}})
                self.assertEqual(response.status_code, 200, response.text)
                return response.json()['result']
            self.assertFalse(call('vault_database', {'action': 'config', 'path': 'Media.base'}).get('isError'))
            args = {'path': 'Media.base', 'command': {'type': 'field.remove', 'key': 'cover'}, 'workspace_revision': self.ws, 'expected_revision': self.c['revision']}
            self.assertTrue(call('vault_database_update', args)['isError'])
            configure(True)
            args['expected_revision'] = 'stale'; self.assertTrue(call('vault_database_update', args)['isError'])
            args['expected_revision'] = self.c['revision']; self.assertFalse(call('vault_database_update', args).get('isError'))

if __name__ == '__main__': unittest.main()
