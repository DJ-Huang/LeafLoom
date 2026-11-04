"""Board contracts in temporary fictional vaults; no production service or data."""
import json
import unittest
from unittest.mock import patch
from tests import test_databases as fixture
from vault_rag.databases import Databases
from vault_rag.local_state import ConflictError
from vault_rag.note_operations import NoteError


class DatabaseBoardTests(unittest.TestCase):
    setUp = fixture.DatabaseTests.setUp
    refresh = fixture.DatabaseTests.refresh
    command = fixture.DatabaseTests.command
    record = fixture.DatabaseTests.record

    def board(self):
        self.command({'type': 'view.add', 'view': {'type': 'leafloomBoard', 'name': 'Tasks'}, 'preset': 'tasks'})
        return self.c['views'][-1]

    def move(self, view, path, value='done', **extra):
        summary = self.db.query('Media.base', view['id'])
        row = next(r for r in self.db.query_rows(self.c, view)[0] if r['path'] == path)
        cmd = {'type': 'record.move', 'view_id': view['id'], 'path': path, 'record_revision': row['revision'],
               'group_key': json.dumps(value), 'catalog_version': summary['catalog_version'], **extra}
        return cmd

    def test_preset_defaults_and_column_metadata(self):
        view = self.board(); self.assertEqual(len(self.c['views']), 5)
        self.assertEqual(self.c['tasks']['dueField'], 'end_date')
        self.record('First'); self.record('Second', status='done', priority='high')
        query = self.db.query('Media.base', view['id'])
        self.assertEqual(query['total'], 2); self.assertEqual(query['results'], [])
        self.assertEqual([(g['value'], g['count']) for g in query['groups']], [('open', 1), ('in-progress', 0), ('done', 1)])
        page = self.db.query('Media.base', view['id'], group_key='"open"')
        self.assertEqual(page['results'][0]['metadata']['status'], 'open')
        self.assertEqual(self.c['fields']['status']['optionMeta']['done']['labelKey'], 'db.done')
        self.assertEqual(self.config.data['include_roots'], [])

    def test_task_create_template_and_incompatible_names(self):
        self.db.command('Tasks.base', {'type': 'create', 'preset': 'tasks'}, self.ws, operation_id='tasks')
        c = self.db.config_read('Tasks.base'); self.assertEqual(c['views'][0]['type'], 'leafloomBoard'); self.assertEqual(len(c['views']), 5)
        self.command({'type': 'field.set', 'key': 'status', 'field': {'type': 'number'}})
        self.board(); self.assertEqual(self.c['tasks']['statusField'], 'task_status')
        self.assertEqual(self.c['fields']['status']['type'], 'number')

    def test_column_paging_unknown_empty_and_stale_cursor(self):
        view = self.board()
        for i in range(2400):
            value = ['open', 'in-progress', 'done'][i % 3]
            (self.root/'Media'/f'{i:04}.md').write_text(f'---\nstatus: {value}\n---\n')
        (self.root/'Media/Unset.md').write_text('# Unset')
        (self.root/'Media/Old.md').write_text('---\nstatus: retired\n---\n# Preserved')
        self.refresh(); query = self.db.query('Media.base', view['id'])
        self.assertEqual([g['count'] for g in query['groups']], [800, 800, 800, 1, 1])
        old = next(g for g in query['groups'] if g['value'] == 'retired'); self.assertFalse(old['configured'])
        page = self.db.query('Media.base', view['id'], group_key='"done"', limit=100)
        self.assertEqual(page['total'], 800); self.assertEqual(len(page['results']), 100)
        self.assertTrue(all(r['metadata']['status'] == 'done' for r in page['results']))
        other = self.db.query('Media.base', view['id'], group_key='"done"', limit=100, cursor=page['next_cursor'])
        self.assertFalse(set(r['path'] for r in page['results']) & set(r['path'] for r in other['results']))
        with self.assertRaises(NoteError): self.db.query('Media.base', view['id'], group_key='"open"', cursor=page['next_cursor'])
        self.record('A-new-task')
        with self.assertRaises(NoteError): self.db.query('Media.base', view['id'], group_key='"done"', cursor=page['next_cursor'])

    def test_move_order_undo_retry_and_body(self):
        view = self.board(); a = self.record('A'); b = self.record('B'); c = self.record('C')
        file = self.root/b['path']; file.write_text(file.read_text()+'# Literal body\n\n```yaml\nstatus: untouched\n```\n'); self.refresh()
        before = file.read_bytes(); command = self.move(view, b['path'], 'open', before_path=a['path'])
        result = self.command(command, operation_id='reorder')
        self.assertEqual(file.read_bytes(), before)
        page = self.db.query('Media.base', view['id'], group_key='"open"')
        self.assertEqual([r['path'] for r in page['results']], [b['path'], a['path'], c['path']])
        # Lost replies can be retried with the read-time versions.
        retry = self.db.command('Media.base', command, self.ws, 'old', 'reorder')
        self.assertEqual(result['undo_id'], retry['undo_id'])
        command = self.move(view, b['path']); result = self.command(command, operation_id='move')
        self.assertEqual(self.db.query('Media.base', view['id'], group_key='"done"')['results'][0]['path'], b['path'])
        self.assertIn('status: untouched', file.read_text())
        self.command({'type': 'board.undo', 'move_id': result['undo_id']}, operation_id='undo')
        self.assertEqual(file.read_bytes(), before)
        self.assertEqual(Databases(self.config, self.runtime).query('Media.base', view['id'], group_key='"open"')['results'][0]['path'], b['path'])

    def test_sorted_view_cross_moves_and_filters(self):
        view = self.board(); a = self.record('A', priority='low'); b = self.record('B', priority='high')
        self.command({'type': 'view.update', 'view_id': view['id'], 'patch': {'sort': [{'property': 'priority', 'direction': 'ASC'}]}})
        view = self.c['views'][-1]
        self.assertEqual(self.db.query('Media.base', view['id'], group_key='"open"')['results'][0]['path'], b['path'])
        with self.assertRaisesRegex(ValueError, 'boardAutoOrder'): self.command(self.move(view, a['path'], 'open'), operation_id='bad-sort')
        self.command(self.move(view, a['path']), operation_id='cross-sort')
        self.command({'type': 'view.update', 'view_id': view['id'], 'patch': {'leafloom': {'conditions': [{'field': 'status', 'operator': 'eq', 'value': 'open'}]}}})
        view = self.c['views'][-1]; self.command(self.move(view, b['path']), operation_id='out-of-filter')
        self.assertEqual(self.db.query('Media.base', view['id'])['total'], 0)

    def test_reject_conflicts_and_keep_files(self):
        view = self.board(); a = self.record('A'); command = self.move(view, a['path'])
        before = (self.root/'Media.base').read_bytes()
        (self.root/a['path']).write_text('# External edit'); self.refresh()
        with self.assertRaises(ConflictError): self.command(command, operation_id='stale')
        self.assertEqual((self.root/'Media.base').read_bytes(), before)
        self.assertEqual((self.root/a['path']).read_text(), '# External edit')
        with self.assertRaises(ValueError): self.command(self.move(view, a['path'], 'retired'), operation_id='unknown')

    def test_write_failure_rolls_back_and_interrupted_move_recovers(self):
        view = self.board(); a = self.record('A'); file = self.root/a['path']; original = file.read_bytes()
        command = self.move(view, a['path']); save = self.runtime.files.save
        def fail(path, *args, **kwargs):
            if path == 'Media.base': raise OSError('fictional disk failure')
            return save(path, *args, **kwargs)
        with patch.object(self.runtime.files, 'save', side_effect=fail):
            with self.assertRaises(OSError): self.command(command, operation_id='failed')
        self.assertEqual(file.read_bytes(), original)
        def interrupt(path, *args, **kwargs):
            if path == 'Media.base': raise KeyboardInterrupt()
            return save(path, *args, **kwargs)
        with patch.object(self.runtime.files, 'save', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt): self.command(command, operation_id='interrupted')
        self.assertNotEqual(file.read_bytes(), original)
        Databases(self.config, self.runtime).config_read('Media.base')
        self.assertEqual(file.read_bytes(), original)

    def test_external_edit_blocks_undo_and_rename_updates_references(self):
        view = self.board(); a = self.record('A'); self.record('B')
        result = self.command(self.move(view, a['path']), operation_id='move')
        file = self.root/a['path']; file.write_text(file.read_text()+'external'); self.refresh()
        with self.assertRaises(ConflictError): self.command({'type': 'board.undo', 'move_id': result['undo_id']}, operation_id='blocked-undo')
        self.runtime.files.move(a['path'], 'Media/Renamed.md'); self.refresh()
        self.assertIn('Media/Renamed.md', self.c['views'][-1]['leafloom']['board']['manualOrder'])
        self.assertNotIn(a['path'], self.c['views'][-1]['leafloom']['board']['manualOrder'])

    def test_noop_and_note_only_moves(self):
        view = self.board(); a = self.record('A'); b = self.record('B')
        self.command(self.move(view, a['path'], 'open', before_path=b['path']), operation_id='initial-order')
        prior = self.c['revision']
        result = self.command(self.move(view, a['path'], 'open', before_path=b['path']), operation_id='same-order')
        self.assertFalse(result['changed']); self.assertEqual(self.c['revision'], prior)
        self.command(self.move(view, a['path'], 'done'), operation_id='last-position')
        prior = self.c['revision']
        result = self.command(self.move(view, a['path'], 'open'), operation_id='note-only')
        self.assertTrue(result['changed']); self.assertEqual(self.c['revision'], prior)
        self.assertEqual(self.db.query('Media.base', view['id'], group_key='"open"')['total'], 2)

    def test_new_task_visibility_and_unknown_scalar(self):
        view = self.board()
        self.command({'type': 'view.update', 'view_id': view['id'], 'patch': {'leafloom': {'conditions': [{'field': 'status', 'operator': 'eq', 'value': 'open'}]}}})
        result = self.command({'type': 'record.create', 'view_id': view['id'], 'group_key': '"done"', 'title': 'Outside'}, operation_id='outside')
        self.assertFalse(result['visible'])
        self.command({'type': 'view.update', 'view_id': view['id'], 'patch': {'leafloom': {'conditions': []}}})
        (self.root/'Media/Boolean.md').write_text('---\nstatus: false\n---\n')
        self.refresh(); query = self.db.query('Media.base', view['id'])
        group = next(g for g in query['groups'] if g['value'] == 'False')
        self.assertEqual(self.db.query('Media.base', view['id'], group_key=group['key'])['total'], 1)

    def test_recovery_keeps_external_edits_and_crlf_body(self):
        view = self.board(); a = self.record('Encoding')
        file = self.root/a['path']; file.write_bytes(b'\xef\xbb\xbf---\r\nstatus: open\r\ncustom: retained\r\n---\r\n\r\n# Body\r\nLiteral \n mixed newline.\r\n');self.refresh()
        original = file.read_bytes();command = self.move(view, a['path']); save = self.runtime.files.save
        def fail(path, *args, **kwargs):
            if path == 'Media.base':
                file.write_bytes(file.read_bytes()+b'External addition\r\n')
                raise OSError('fictional write failure')
            return save(path, *args, **kwargs)
        with patch.object(self.runtime.files, 'save', side_effect=fail):
            with self.assertRaises(ConflictError): self.command(command, operation_id='conflict-recovery')
        self.assertIn(b'External addition',file.read_bytes());self.assertTrue(file.read_bytes().startswith(b'\xef\xbb\xbf'))
        with self.assertRaises(ConflictError): self.db.config_read('Media.base')
        # Explicitly restoring the original file lets the safe rollback finish.
        file.write_bytes(original);self.refresh();self.assertEqual(file.read_bytes(),original)

    def test_view_patch_keeps_unknown_settings_and_group_change_resets_columns(self):
        view = self.board();a=self.record('A');self.command(self.move(view,a['path']),operation_id='order')
        self.command({'type':'view.update','view_id':view['id'],'patch':{'leafloom':{'board':{'vendorExtension':{'keep':True},'hiddenGroups':['"done"']}}}})
        self.command({'type':'view.update','view_id':view['id'],'patch':{'leafloom':{'board':{'hideEmpty':True}}}})
        board=self.c['views'][-1]['leafloom']['board'];self.assertEqual(board['vendorExtension'],{'keep':True});self.assertIn(a['path'],board['manualOrder']);self.assertEqual(board['hiddenGroups'],['"done"'])
        self.command({'type':'view.update','view_id':view['id'],'patch':{'groupBy':{'property':'priority'}}})
        board=self.c['views'][-1]['leafloom']['board'];self.assertEqual(board['hiddenGroups'],[]);self.assertIn(a['path'],board['manualOrder'])
        self.command({'type':'view.update','view_id':view['id'],'task_setup':{**self.c['tasks'],'vendorExtension':{'keep':True}},'patch':{}})
        self.command({'type':'view.add','view':{'type':'leafloomBoard','name':'Another board'},'preset':'tasks'})
        self.assertEqual(self.c['tasks']['vendorExtension'],{'keep':True})

    def test_move_requires_current_workspace_and_stays_in_record_folder(self):
        view=self.board();a=self.record('A');cmd=self.move(view,a['path']);before=(self.root/a['path']).read_bytes()
        with self.assertRaises(ConflictError):self.db.command('Media.base',cmd,'stale-workspace',self.c['revision'],'blocked')
        (self.root/'Outside.md').write_text('# Outside')
        with self.assertRaises(ValueError):self.command({**cmd,'path':'Outside.md'},operation_id='outside-folder')
        self.assertEqual((self.root/a['path']).read_bytes(),before)

    def test_stale_neighbor_and_crlf_base_rename(self):
        view=self.board();a=self.record('A');b=self.record('B')
        cmd=self.move(view,a['path'],'open',before_path=b['path'])
        (self.root/b['path']).write_text('# External neighbor edit')
        with self.assertRaises(ConflictError):self.db.command('Media.base',cmd,self.ws,self.c['revision'],'changed-neighbor')
        self.refresh();self.command(self.move(view,a['path'],'done'),operation_id='rank-before-rename')
        base=self.root/'Media.base';base.write_bytes(b'\xef\xbb\xbf'+base.read_bytes().replace(b'\n',b'\r\n'));self.refresh()
        self.runtime.files.move(a['path'],'Media/Renamed.md');self.refresh()
        result=base.read_bytes();self.assertTrue(result.startswith(b'\xef\xbb\xbf'));self.assertNotIn(b'\n',result.replace(b'\r\n',b''));self.assertIn('Media/Renamed.md',self.c['views'][-1]['leafloom']['board']['manualOrder'])


if __name__ == '__main__': unittest.main()
