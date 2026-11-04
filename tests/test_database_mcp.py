"""Database workflows through the real authenticated HTTP MCP boundary."""
import json
import unittest
from uuid import uuid4
from starlette.testclient import TestClient
from tests import test_databases as fixture
from vault_rag.web_server import create_app


class DatabaseMcpTests(unittest.TestCase):
    def setUp(self):
        fixture.DatabaseTests.setUp(self)
        self.app = create_app(self.config, self.runtime, start_background=False)
        self.client = TestClient(self.app, base_url='http://127.0.0.1:18080', client=('127.0.0.1', 12345))
        self.client.__enter__(); self.addCleanup(self.client.__exit__, None, None, None)
        self.auth = {'Authorization': 'Bearer '+(self.config.directory/'auth-token').read_text().strip()}
        self.grant(True)

    refresh = fixture.DatabaseTests.refresh

    def grant(self, write):
        result = self.client.post('/api/mcp-access', headers=self.auth, json={'kind': 'local', 'enabled': True, 'write': write})
        self.assertEqual(result.status_code, 200, result.text)
        if result.json().get('token'):
            self.headers = {'Authorization': 'Bearer '+result.json()['token'], 'Accept': 'application/json, text/event-stream'}

    def request(self, method, params):
        response = self.client.post('/mcp', headers=self.headers, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['result']

    def call(self, tool, arguments, error=False):
        result = self.request('tools/call', {'name': tool, 'arguments': arguments})
        self.assertEqual(bool(result.get('isError')), error, result)
        if error: return result.get('structuredContent') or result
        return result.get('structuredContent') or json.loads(result['content'][0]['text'])

    def read(self, **kwargs):
        return self.call('vault_database', {'path': 'Media.base', **kwargs})

    def write(self, command, operation_id=None, revision=None, error=False):
        c = self.read(action='config')
        result = self.call('vault_database_update', {'path': 'Media.base', 'command': command,
            'workspace_revision': c['workspace_revision'], 'expected_revision': revision or c['revision'],
            'operation_id': operation_id or uuid4().hex}, error)
        self.refresh()
        return result

    def board(self):
        self.write({'type': 'view.add', 'view': {'name': 'Board', 'type': 'leafloomBoard'}, 'preset': 'tasks'})
        return self.read(action='config')['views'][-1]

    def test_discovery_schema_and_capabilities_describe_every_command(self):
        tools = {tool['name']: tool for tool in self.request('tools/list', {})['tools']}
        capabilities = self.read(action='capabilities')
        schema = json.dumps(tools['vault_database_update']['inputSchema'])
        for command in capabilities['commands']:
            self.assertIn('"'+command+'"', schema)
        self.assertEqual(len(capabilities['commands']), 15)
        self.assertTrue(tools['vault_database']['annotations']['readOnlyHint'])
        self.assertFalse(tools['vault_database_update']['annotations']['readOnlyHint'])
        self.assertIn('record_path', tools['vault_database']['inputSchema']['properties'])
        self.assertIn('recent_paths', tools['vault_database']['inputSchema']['properties'])
        for tool in ['vault_update_note', 'vault_files', 'vault_files_update', 'vault_move', 'vault_delete', 'vault_list_records', 'vault_read_record', 'vault_restore']:
            self.assertIn(tool, tools)
        self.assertIn('Media.base', [r['path'] for r in self.read(action='list')['results']])
        self.assertEqual(self.config.data['include_roots'], [])

    def test_records_all_views_body_media_fields_and_saved_receipts(self):
        view = self.board()
        self.write({'type': 'field.set', 'key': 'score', 'displayName': 'Rating', 'field': {'type': 'number', 'vendor': 'keep'}})
        self.write({'type': 'field.set', 'key': 'checked', 'field': {'type': 'checkbox'}})
        cmd = {'type': 'record.create', 'title': 'A', 'values': {'score': 2, 'checked': True, 'start_date': '2028-02-29', 'end_date': '2028-03-01', 'attachments': ['[[cover.png]]']}, 'return_record': True}
        created = self.write(cmd, 'create-once')
        retry = self.write(cmd, 'create-once', revision='old')
        self.assertEqual(created, retry); self.assertEqual(created['record']['metadata']['score'], 2)
        for v in self.c['views']:
            page = self.read(action='query', view_id=v['id'], recent_paths=[created['path']])
            if v['type'] == 'leafloomBoard': page = self.read(action='query', view_id=v['id'], group_key='"open"')
            self.assertEqual(page['total'], 1)
            self.assertEqual(page['results'][0]['path'], created['path'])
        body = self.read(action='record', record_path=created['path'])
        self.assertEqual(body['markdown_link'], '[['+created['path']+']]')
        saved = self.call('vault_update_note', {'path': body['path'], 'workspace_revision': self.ws,
            'expected_revision': body['revision'], 'mode': 'append', 'text': '# Original Markdown\n'})
        self.refresh(); body = self.read(action='record', record_path=created['path'])
        part = self.read(action='record', record_path=created['path'], offset=3, text_limit=12)
        self.assertEqual(part['text'], body['text'][3:15]); self.assertEqual(part['next_offset'], 15)
        self.write({'type': 'record.update', 'path': body['path'], 'record_revision': body['revision'],
            'values': {'title': 'Renamed', 'start_date': '2028-03-01', 'end_date': '2028-03-03'}})
        after = self.read(action='record', record_path=body['path']); self.assertIn('# Original Markdown', after['text'])
        copy = self.write({'type': 'record.duplicate', 'path': after['path'], 'record_revision': after['revision']}, 'duplicate-once')
        copied = self.read(action='record', record_path=copy['path']); self.assertIn('# Original Markdown', copied['text'])
        self.assertEqual(copied['metadata']['attachments'], ['[[cover.png]]'])
        self.write({'type': 'field.remove', 'key': 'score'})
        self.assertEqual(self.read(action='record', record_path=after['path'])['metadata']['score'], 2)
        before = self.read(action='record', record_path=copy['path'])
        preview = self.write({'type': 'record.trash', 'path': copy['path'], 'record_revision': before['revision'], 'dry_run': True, 'limit': 1})
        self.write({'type': 'record.trash', 'path': copy['path'], 'record_revision': before['revision'], 'dry_run': False, 'operation_token': preview['operation_token']})
        self.assertFalse((self.root/copy['path']).exists()); self.assertTrue((self.root/created['path']).exists())

    def test_view_layout_filters_sort_group_and_removal_preserve_unknown_settings(self):
        board = self.board(); c = self.read(action='config')
        for view in c['views']:
            patch = {'name': 'Custom '+view['type'], 'order': ['title', 'category'], 'sort': [{'property': 'title', 'direction': 'DESC'}],
                     'leafloom': {'vendor': {'keep': True}, 'conditions': [{'field': 'title', 'operator': 'contains', 'value': 'Match'}]}}
            if view['type'] == 'cards': patch['leafloom'].update(coverField='cover', cardSize='large', fit='contain')
            if view['type'] == 'leafloomTimeline': patch['leafloom'].update(startField='start_date', endField='end_date')
            if view['type'] == 'leafloomBoard': patch['leafloom']['board'] = {'groupOrder': ['"done"', '"open"'], 'hiddenGroups': ['"done"'], 'collapsedGroups': ['"open"'], 'hideEmpty': True}
            self.write({'type': 'view.update', 'view_id': view['id'], 'patch': patch})
        self.write({'type': 'record.create', 'title': 'Match B'})
        self.write({'type': 'record.create', 'title': 'Match A'})
        self.write({'type': 'record.create', 'title': 'Excluded'})
        table = self.c['views'][0]
        query = self.read(action='query', view_id=table['id'], limit=1)
        self.assertEqual(query['total'], 2); self.assertEqual(query['results'][0]['title'], 'Match B')
        page = self.read(action='query', view_id=table['id'], limit=1, cursor=query['next_cursor'])
        self.assertEqual(page['results'][0]['title'], 'Match A')
        self.write({'type': 'view.update', 'unexpected': 'ignored', 'view_id': table['id'], 'patch': {}}, error=True)
        self.write({'type': 'view.update', 'view_id': table['id'], 'patch': {'groupBy': {'property': 'status'}}})
        self.assertTrue(self.read(action='config')['views'][0]['leafloom']['vendor']['keep'])
        self.write({'type': 'view.remove', 'view_id': board['id']})
        self.assertEqual(len(list((self.root/'Media').glob('*.md'))), 3)

    def test_board_groups_manual_moves_undo_and_migration(self):
        view = self.board()
        self.write({'type': 'board.group.set', 'view_id': view['id'], 'value': 'review', 'label': 'Review', 'color': 'purple'})
        self.write({'type': 'board.group.set', 'view_id': view['id'], 'value': 'review', 'label': 'Ready for review'})
        self.assertEqual(self.c['fields']['status']['optionMeta']['review'], {'label': 'Ready for review', 'color': 'purple'})
        a = self.write({'type': 'record.create', 'title': 'A'}); b = self.write({'type': 'record.create', 'title': 'B'})
        def move(path, target, **position):
            row = self.read(action='record', record_path=path); summary = self.read(action='query', view_id=view['id'])
            return {'type': 'record.move', 'view_id': view['id'], 'path': path, 'record_revision': row['revision'],
                    'group_key': json.dumps(target), 'catalog_version': summary['catalog_version'], **position}
        first = self.write(move(b['path'], 'open', before_path=a['path']), 'reorder')
        self.assertEqual(self.read(action='query', view_id=view['id'], group_key='"open"')['results'][0]['path'], b['path'])
        moved = self.write(move(a['path'], 'review'), 'cross-column')
        self.assertEqual(self.read(action='record', record_path=a['path'])['metadata']['status'], 'review')
        self.write({'type': 'board.undo', 'move_id': moved['undo_id']}, 'undo')
        self.assertEqual(self.read(action='record', record_path=a['path'])['metadata']['status'], 'open')
        self.write(move(a['path'], 'review'), 'cross-again')
        preview = self.write({'type': 'board.group.remove', 'view_id': view['id'], 'group_key': '"review"', 'dry_run': True})
        cmd = {'type': 'board.group.remove', 'view_id': view['id'], 'group_key': '"review"', 'records': preview['records'], 'catalog_version': preview['catalog_version'], 'target_value': 'done'}
        result = self.write(cmd, 'delete-group')
        self.assertEqual(result, self.write(cmd, 'delete-group', revision='stale'))
        self.assertNotIn('review', self.c['fields']['status']['options'])
        self.assertEqual(self.read(action='record', record_path=a['path'])['metadata']['status'], 'done')

    def test_permissions_versions_outside_paths_invalid_commands_and_query_limits(self):
        self.grant(False)
        self.read(action='capabilities'); self.read(action='config')
        self.write({'type': 'field.remove', 'key': 'cover'}, error=True)
        self.grant(True)
        created = self.write({'type': 'record.create', 'title': 'Guarded'})
        self.write({'type': 'record.update', 'path': created['path'], 'record_revision': 'stale', 'values': {'title': 'Unsafe'}}, error=True)
        self.write({'type': 'field.remove', 'key': 'cover'}, revision='stale', error=True)
        self.write({'type': 'execute', 'code': 'unsafe'}, error=True)
        self.call('vault_database_update', {'path': 'Media.base', 'workspace_revision': 'stale', 'expected_revision': self.c['revision'], 'command': {'type': 'field.remove', 'key': 'cover'}}, error=True)
        (self.root/'Outside.md').write_text('# Outside')
        self.call('vault_database', {'action': 'record', 'path': 'Media.base', 'record_path': 'Outside.md'}, error=True)
        self.call('vault_database', {'action': 'record', 'path': 'Media.base', 'record_path': '../escape.md'}, error=True)
        for params in [{'limit': 201}, {'recent_paths': ['x']*21}]:
            self.call('vault_database', {'action': 'query', 'path': 'Media.base', **params}, error=True)
        self.assertEqual(self.config.data['include_roots'], [])

    def test_create_database_task_template_and_file_lifecycle_without_record_deletion(self):
        args = {'path': 'Tasks.base', 'workspace_revision': self.ws, 'operation_id': 'task-database', 'command': {'type': 'create', 'preset': 'tasks'}}
        self.call('vault_database_update', args); self.refresh()
        c = self.call('vault_database', {'action': 'config', 'path': 'Tasks.base'})
        self.assertEqual(len(c['views']), 5); self.assertEqual(c['views'][0]['type'], 'leafloomBoard')
        self.call('vault_update_note', {'path': 'Tasks.base', 'workspace_revision': self.ws,
            'expected_revision': c['revision'], 'text': 'unsafe raw YAML'}, error=True)
        record = self.call('vault_database_update', {'path': 'Tasks.base', 'workspace_revision': self.ws,
            'expected_revision': c['revision'], 'operation_id': 'task-record', 'command': {'type': 'record.create', 'title': 'Retained'}})
        self.refresh()
        (self.root/'Dashboard.md').write_text('![[Tasks.base#view='+c['views'][0]['id']+']]')
        self.refresh()
        preview = self.call('vault_move', {'path': 'Tasks.base', 'destination': 'Renamed.base', 'workspace_revision': self.ws})
        self.call('vault_move', {'path': 'Tasks.base', 'destination': 'Invalid.txt', 'workspace_revision': self.ws}, error=True)
        self.call('vault_move', {'path': 'Tasks.base', 'destination': 'Renamed.base', 'workspace_revision': self.ws,
            'dry_run': False, 'operation_token': preview['operation_token']}); self.refresh()
        self.call('vault_database', {'action': 'config', 'path': 'Renamed.base'})
        self.assertIn('![[Renamed.base#view=', (self.root/'Dashboard.md').read_text())
        preview = self.call('vault_delete', {'path': 'Renamed.base', 'workspace_revision': self.ws})
        self.call('vault_delete', {'path': 'Renamed.base', 'workspace_revision': self.ws, 'dry_run': False, 'operation_token': preview['operation_token']})
        self.assertTrue((self.root/record['path']).is_file())
        records = self.call('vault_list_records', {'kind': 'trash', 'path': 'Renamed.base'})
        snapshot = self.call('vault_read_record', {'kind': 'trash', 'id': records['results'][0]['id']})
        self.call('vault_restore', {'kind': 'trash', 'id': snapshot['record']['id'], 'workspace_revision': self.ws,
            'expected_revision': snapshot['expected_revision'], 'record_revision': snapshot['record_revision']})
        restored = self.call('vault_database', {'action': 'config', 'path': 'Renamed.base'})
        self.assertEqual(restored['folder'], c['folder'])

    def test_creation_through_mcp_inherits_the_selected_view_type_and_board_column(self):
        board = self.board()
        self.write({'type': 'field.set', 'key': 'record_type', 'field': {
            'type': 'select', 'options': ['task', 'document', 'setting']}})
        config = self.read(action='config')
        for kind, view in [('task', board), ('document', config['views'][2]), ('setting', config['views'][0])]:
            self.write({'type': 'view.update', 'view_id': view['id'], 'patch': {'leafloom': {
                'conditions': [{'field': 'record_type', 'operator': 'eq', 'value': kind}]}}})
            result = self.write({'type': 'record.create', 'view_id': view['id'], 'title': 'Auto-'+kind,
                                 'return_record': True})
            self.assertEqual(result['record']['metadata']['record_type'], kind)
            self.assertTrue(result['visible'])
        result = self.write({'type': 'record.create', 'view_id': board['id'], 'title': 'Column',
                             'group_key': '"done"', 'return_record': True})
        self.assertEqual(result['record']['metadata']['record_type'], 'task')
        self.assertEqual(result['record']['metadata']['status'], 'done')
        self.assertTrue(result['visible'])

    def test_view_move_is_discoverable_version_checked_and_write_guarded(self):
        c = self.read(action='config'); ids = [v['id'] for v in c['views']]
        self.write({'type': 'view.move', 'view_id': ids[0], 'after_view_id': ids[-1]})
        moved = self.read(action='config')
        self.assertEqual([v['id'] for v in moved['views']], ids[1:]+ids[:1])
        cmd = {'type': 'view.move', 'view_id': ids[0], 'before_view_id': ids[1]}
        self.write(cmd, revision=c['revision'], error=True)
        self.grant(False)
        self.write(cmd, error=True)
        self.assertEqual([v['id'] for v in self.read(action='config')['views']], ids[1:]+ids[:1])

    def test_field_creation_and_detail_layout_use_the_same_mcp_save(self):
        c = self.read(action='config'); view = c['views'][0]
        self.write({'type': 'field.set', 'key': 'rating', 'displayName': 'Rating', 'field': {'type': 'number'},
                    'detail_view_id': view['id'], 'detail_fields': ['title', 'category']})
        c = self.read(action='config')
        self.assertEqual(c['views'][0]['leafloom']['detailFields'], ['title', 'category', 'rating'])
        self.assertEqual(c['fields']['rating']['displayName'], 'Rating')

    def test_property_actions_keep_source_values_and_preserve_layouts_through_mcp(self):
        c = self.read(action='config'); view = c['views'][0]
        self.write({'type': 'field.set', 'key': 'category', 'field': {}, 'displayName': 'Discipline'})
        created = self.write({'type': 'record.create', 'title': 'Keep source', 'values': {'category': 'Design'}})
        before = self.read(action='record', record_path=created['path'])
        self.write({'type': 'view.update', 'view_id': view['id'], 'patch': {'leafloom': {
            'detailFields': ['category', 'title'], 'detailExtraOrder': ['cover', 'file.ctime', 'category']}}})
        self.write({'type': 'field.remove', 'key': 'category'})
        after = self.read(action='record', record_path=created['path'])
        self.assertEqual(before['revision'], after['revision'])
        self.assertEqual(after['metadata']['category'], 'Design')
        self.assertNotIn('category', self.read(action='config')['views'][0]['leafloom']['detailExtraOrder'])
        self.write({'type': 'field.remove', 'key': 'title'}, error=True)

    def test_option_editing_preserves_values_and_task_roles_through_mcp(self):
        board = self.board()
        self.write({'type': 'field.set', 'key': 'topics', 'field': {'type': 'multiselect', 'options': ['old', 'keep']}})
        note = self.write({'type': 'record.create', 'title': 'Original choices', 'values': {'topics': ['old', 'keep'], 'status': 'done'}})
        before = self.read(action='record', record_path=note['path'])
        self.write({'type': 'field.set', 'key': 'topics', 'field': {'options': ['keep', 'new'], 'optionMeta': {
            'old': {'label': 'Historical', 'color': 'purple'}, 'keep': {'label': 'Renamed', 'color': 'blue'}}}})
        self.assertEqual(self.read(action='record', record_path=note['path'])['revision'], before['revision'])
        c = self.read(action='config')
        self.write({'type': 'field.set', 'key': 'status', 'field': {'options': ['open', 'complete']},
                    'task_setup': {**c['tasks'], 'completedStatuses': ['complete']}})
        self.assertEqual(self.read(action='record', record_path=note['path'])['revision'], before['revision'])
        self.assertFalse(next(g for g in self.read(action='query', view_id=board['id'])['groups'] if g['value'] == 'done')['configured'])
        self.write({'type': 'record.update', 'path': note['path'], 'record_revision': before['revision'], 'values': {'topics': ['old', 'new']}})
        self.write({'type': 'record.create', 'title': 'Reject historical assignment', 'values': {'topics': ['old']}}, error=True)
