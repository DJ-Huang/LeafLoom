"""Safe board group removal, in a disposable fictional vault."""
import json
from unittest import TestCase
from unittest.mock import patch
from tests import test_database_board as fixture
from vault_rag.databases import Databases
from vault_rag.local_state import ConflictError


class DatabaseGroupTests(TestCase):
    setUp = fixture.DatabaseBoardTests.setUp
    refresh = fixture.DatabaseBoardTests.refresh
    command = fixture.DatabaseBoardTests.command
    record = fixture.DatabaseBoardTests.record
    board = fixture.DatabaseBoardTests.board

    def group(self, value='custom'):
        field = self.c['fields']['status']
        self.command({'type': 'field.set', 'key': 'status', 'field': {
            **field, 'options': [*field['options'], value],
            'optionMeta': {**field['optionMeta'], value: {'label': 'Custom group', 'color': 'purple'}}}})

    def preview(self, view, value='custom'):
        return self.command({'type': 'board.group.remove', 'view_id': view['id'], 'group_key': json.dumps(value), 'dry_run': True})

    def removal(self, view, preview, value='custom', target=None):
        return {'type': 'board.group.remove', 'view_id': view['id'], 'group_key': json.dumps(value),
                'records': preview['records'], 'catalog_version': preview['catalog_version'], 'target_value': target}

    def test_all_pages_and_view_filtered_records_move_to_ungrouped_with_body_preserved(self):
        view = self.board(); self.group()
        for i in range(205):
            (self.root/'Media'/f'{i:03}.md').write_text(f'---\nstatus: custom\nprivate: keep\n---\n\nLiteral {i}\n')
        self.refresh(); before = {p.name: p.read_text().split('---', 2)[2] for p in (self.root/'Media').glob('*.md')}
        self.command({'type': 'view.update', 'view_id': view['id'], 'patch': {'leafloom': {'conditions': [{'field': 'status', 'operator': 'eq', 'value': 'done'}]}}})
        preview = self.preview(view); self.assertEqual(preview['count'], 205)
        self.assertTrue(preview['dry_run']); self.assertIn('custom', self.c['fields']['status']['options'])
        command = self.removal(view, preview); result = self.command(command, operation_id='remove-populated')
        self.assertEqual(result, self.db.command('Media.base', command, self.ws, 'stale', 'remove-populated'))
        for p in (self.root/'Media').glob('*.md'):
            note = self.runtime.files.read('Media/'+p.name)
            self.assertNotIn('status', note['metadata']); self.assertEqual(note['metadata']['private'], 'keep')
            self.assertEqual(p.read_text().split('---', 2)[2], before[p.name])
        self.assertNotIn('custom', self.c['fields']['status']['options'])
        table = self.c['views'][0]; self.assertEqual(self.db.query('Media.base', table['id'])['total'], 205)
        self.assertEqual(self.config.data['include_roots'], [])

    def test_empty_group_and_shared_column_settings_are_removed_without_note_writes(self):
        view = self.board(); self.group(); other = self.record('Untouched')
        original = (self.root/other['path']).read_bytes()
        self.command({'type': 'view.add', 'view': {'type': 'leafloomBoard', 'name': 'Second', 'groupBy': {'property': 'status'}}})
        for board in [v for v in self.c['views'] if v['type'] == 'leafloomBoard']:
            self.command({'type': 'view.update', 'view_id': board['id'], 'patch': {'leafloom': {'board': {
                'groupOrder': ['"custom"', '"open"'], 'hiddenGroups': ['"custom"'], 'collapsedGroups': ['"custom"'], 'extension': True}}}})
        preview = self.preview(view); self.assertEqual(preview['count'], 0)
        self.command(self.removal(view, preview), operation_id='empty')
        c = Databases(self.config, self.runtime).config_read('Media.base')
        self.assertNotIn('custom', c['fields']['status']['optionMeta'])
        for board in [v for v in c['views'] if v['type'] == 'leafloomBoard']:
            for key in ('groupOrder', 'hiddenGroups', 'collapsedGroups'):
                self.assertNotIn('"custom"', board['leafloom']['board'][key])
            self.assertTrue(board['leafloom']['board']['extension'])
        self.assertEqual((self.root/other['path']).read_bytes(), original)

    def test_task_roles_require_an_explicit_replacement(self):
        view = self.board(); self.group(); task = self.record('Initial')
        preview = self.preview(view, 'open')
        with self.assertRaisesRegex(ValueError, 'deleteGroupTaskTarget'):
            self.command(self.removal(view, preview, 'open'), operation_id='no-replacement')
        self.command(self.removal(view, preview, 'open', 'custom'), operation_id='replace-initial')
        self.assertEqual(self.c['tasks']['initialStatus'], 'custom')
        self.assertEqual(self.runtime.files.read(task['path'])['metadata']['status'], 'custom')
        preview = self.preview(view, 'done')
        self.command(self.removal(view, preview, 'done', 'in-progress'), operation_id='replace-completed')
        self.assertEqual(self.c['tasks']['completedStatuses'], ['in-progress'])

    def test_legacy_option_can_be_removed_but_ungrouped_cannot(self):
        view = self.board(); task = self.record('Old', status='open')
        p = self.root/task['path']; p.write_text(p.read_text().replace('status: open', 'status: retired')); self.refresh()
        preview = self.preview(view, 'retired')
        self.command(self.removal(view, preview, 'retired', 'done'), operation_id='legacy')
        self.assertEqual(self.runtime.files.read(task['path'])['metadata']['status'], 'done')
        with self.assertRaisesRegex(ValueError, 'boardMissingGroup'):
            self.preview(view, None)

    def test_stale_record_configuration_and_new_members_reject_without_overwriting(self):
        view = self.board(); self.group(); task = self.record('External', status='custom')
        preview = self.preview(view); before = (self.root/'Media.base').read_bytes()
        p = self.root/task['path']; p.write_text(p.read_text()+'External edit\n')
        with self.assertRaises(ConflictError): self.command(self.removal(view, preview), operation_id='stale-note')
        self.assertIn('External edit', p.read_text()); self.assertEqual((self.root/'Media.base').read_bytes(), before)
        self.refresh(); preview = self.preview(view); self.record('New-member', status='custom')
        with self.assertRaises(ConflictError): self.command(self.removal(view, preview), operation_id='new-member')
        preview = self.preview(view); cmd = self.removal(view, preview)
        with self.assertRaises(ConflictError): self.db.command('Media.base', cmd, 'old-workspace', self.c['revision'], 'wrong-workspace')
        with self.assertRaises(ConflictError): self.db.command('Media.base', cmd, self.ws, 'old-config', 'wrong-config')

    def test_failed_config_save_rolls_back_only_this_transaction_and_can_retry(self):
        view = self.board(); self.group(); self.record('A', status='custom'); self.record('B', status='custom')
        preview = self.preview(view); cmd = self.removal(view, preview)
        paths = [self.root/r['path'] for r in preview['records']]+[self.root/'Media.base']
        before = {p: p.read_bytes() for p in paths}; save = self.runtime.files.save
        def fail(path, *args, **kwargs):
            if path == 'Media.base': raise OSError('Fixture save failure')
            return save(path, *args, **kwargs)
        with patch.object(self.runtime.files, 'save', side_effect=fail):
            with self.assertRaises(OSError): self.command(cmd, operation_id='rollback')
        self.assertEqual({p: p.read_bytes() for p in paths}, before)
        self.command(cmd, operation_id='rollback')
        self.assertNotIn('custom', self.c['fields']['status']['options'])
