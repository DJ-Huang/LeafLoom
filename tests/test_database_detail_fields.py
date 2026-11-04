"""Property creation and detail visibility share one guarded configuration save."""
import unittest
from vault_rag.local_state import ConflictError
from tests import test_databases as fixture


class DatabaseDetailFieldsTests(unittest.TestCase):
    setUp = fixture.DatabaseTests.setUp
    refresh = fixture.DatabaseTests.refresh
    command = fixture.DatabaseTests.command
    record = fixture.DatabaseTests.record

    def test_create_and_show_field_is_one_save_and_preserves_original_note(self):
        note = self.record('Original', category='kept'); before = (self.root/note['path']).read_bytes()
        view = self.c['views'][0]
        self.command({'type': 'view.update', 'view_id': view['id'], 'patch': {'leafloom': {'vendor': {'keep': True}}}})
        result = self.command({'type': 'field.set', 'key': 'score', 'displayName': 'Score', 'field': {'type': 'number'},
                               'detail_view_id': view['id'], 'detail_fields': ['title', 'category']})
        self.assertEqual(self.c['views'][0]['leafloom']['detailFields'], ['title', 'category', 'score'])
        self.assertEqual(self.c['views'][0]['leafloom']['vendor'], {'keep': True})
        self.assertEqual(self.c['fields']['score']['type'], 'number')
        self.assertEqual(result['revision'], self.c['revision'])
        self.assertEqual((self.root/note['path']).read_bytes(), before)
        self.command({'type': 'field.remove', 'key': 'score'})
        self.assertEqual(self.c['views'][0]['leafloom']['detailFields'], ['title', 'category'])

    def test_bad_layout_or_stale_revision_never_partially_creates_a_field(self):
        before = (self.root/'Media.base').read_bytes(); view = self.c['views'][0]
        args = {'type': 'field.set', 'key': 'rating', 'field': {'type': 'number'}}
        for patch in [{'detail_view_id': view['id']}, {'detail_fields': ['title']},
                      {'detail_view_id': 'missing', 'detail_fields': ['title']},
                      {'detail_view_id': view['id'], 'detail_fields': ['unknown']},
                      {'detail_view_id': view['id'], 'detail_fields': [1]},
                      {'detail_view_id': view['id'], 'detail_fields': 'title'}]:
            with self.subTest(patch=patch), self.assertRaises(ValueError): self.command({**args, **patch})
            self.assertEqual((self.root/'Media.base').read_bytes(), before)
        with self.assertRaises(ConflictError):
            self.db.command('Media.base', {**args, 'detail_view_id': view['id'], 'detail_fields': ['title']}, self.ws, 'stale')
        self.assertNotIn('rating', self.db.config_read('Media.base')['fields'])

    def test_rename_reorder_and_remove_keep_note_bytes_and_unknown_field_settings(self):
        from vault_rag.databases import Databases
        self.command({'type': 'field.set', 'key': 'category', 'field': {'vendor': {'preserve': True}}})
        note = self.record('Preserved', category='Design'); contents = (self.root/note['path']).read_bytes()
        view = self.c['views'][0]
        self.command({'type': 'view.update', 'view_id': view['id'], 'patch': {'groupBy': {'property': 'category'}, 'leafloom': {
            'detailFields': ['title', 'category', 'attachments'], 'detailExtraOrder': ['cover', 'file.ctime', 'category'],
            'conditions': [{'field': 'category', 'operator': 'eq', 'value': 'Design'}]}}})
        stale = self.c['revision']
        self.command({'type': 'field.set', 'key': 'category', 'field': {}, 'displayName': 'Discipline'})
        self.assertEqual(self.c['fields']['category']['displayName'], 'Discipline')
        self.assertEqual(self.c['fields']['category']['vendor'], {'preserve': True})
        self.command({'type': 'view.update', 'view_id': view['id'], 'patch': {'leafloom': {
            'detailFields': ['attachments', 'title', 'category'], 'detailExtraOrder': ['file.ctime', 'cover', 'category']}}})
        restarted = Databases(self.config, self.runtime).config_read('Media.base')
        self.assertEqual(restarted['views'][0]['leafloom']['detailFields'], ['attachments', 'title', 'category'])
        self.assertEqual(restarted['views'][0]['leafloom']['detailExtraOrder'], ['file.ctime', 'cover', 'category'])
        with self.assertRaises(ConflictError):
            self.db.command('Media.base', {'type': 'field.remove', 'key': 'category'}, self.ws, stale)
        self.command({'type': 'field.remove', 'key': 'category'})
        self.assertNotIn('category', self.c['fields'])
        self.assertNotIn('category', self.c['views'][0]['leafloom']['detailFields'])
        self.assertNotIn('category', self.c['views'][0]['leafloom']['detailExtraOrder'])
        self.assertNotIn('groupBy', self.c['views'][0])
        self.assertEqual(self.c['views'][0]['leafloom']['conditions'], [])
        self.assertEqual((self.root/note['path']).read_bytes(), contents)
        self.assertEqual(self.db.query('Media.base', view['id'])['results'][0]['metadata']['category'], 'Design')

    def test_builtin_and_readonly_field_removal_is_rejected_without_writing(self):
        self.command({'type': 'field.set', 'key': 'locked', 'field': {'type': 'text', 'readonly': True}})
        before = (self.root/'Media.base').read_bytes()
        for key in ['title', 'file.ctime', 'file.mtime', 'formula.total', 'locked']:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'builtInFieldProtected'):
                self.command({'type': 'field.remove', 'key': key})
        self.assertEqual((self.root/'Media.base').read_bytes(), before)

    def test_select_and_multiselect_option_edits_preserve_history_and_reject_new_unknown_values(self):
        for key, kind in [('kind', 'select'), ('topics', 'multiselect')]:
            self.command({'type': 'field.set', 'key': key, 'displayName': 'Original '+key, 'field': {'type': kind, 'options': ['a', 'b'],
                'vendor': {'keep': True}, 'optionMeta': {'a': {'label': 'Alpha', 'color': 'blue', 'vendor': 'keep'}, 'b': {'label': 'Beta', 'color': 'gray'}}}})
        note = self.record('Choices', kind='a', topics=['a', 'b']); original = (self.root/note['path']).read_bytes()
        self.command({'type': 'field.set', 'key': 'kind', 'field': {}})
        self.assertEqual(self.c['fields']['kind']['displayName'], 'Original kind')
        for key in ['kind', 'topics']:
            self.command({'type': 'field.set', 'key': key, 'displayName': 'Edited '+key, 'field': {
                'options': ['new'], 'optionMeta': {'a': {'label': 'Renamed', 'color': 'purple', 'vendor': 'keep'}, 'b': {'label': 'Beta', 'color': 'gray'}, 'new': {'label': 'New', 'color': 'green'}}}})
            self.assertEqual(self.c['fields'][key]['vendor'], {'keep': True})
            self.assertEqual(self.c['fields'][key]['optionMeta']['a']['vendor'], 'keep')
        self.assertEqual((self.root/note['path']).read_bytes(), original)
        self.command({'type': 'record.update', 'path': note['path'], 'record_revision': note['revision'], 'values': {'kind': 'a', 'topics': ['b', 'new']}})
        current = self.db.files.read(note['path'])
        with self.assertRaises(ValueError):
            self.command({'type': 'record.update', 'path': note['path'], 'record_revision': current['etag'], 'values': {'topics': ['b', 'unknown']}})
        with self.assertRaisesRegex(ValueError, 'configured option'): self.record('New-unknown', kind='a')
        self.command({'type': 'record.update', 'path': note['path'], 'record_revision': current['etag'], 'values': {'topics': ['new']}})
        current = self.db.files.read(note['path'])
        with self.assertRaises(ValueError):
            self.command({'type': 'record.update', 'path': note['path'], 'record_revision': current['etag'], 'values': {'topics': ['b']}})

    def test_status_option_deletion_requires_and_atomically_saves_explicit_role_replacements(self):
        self.command({'type': 'view.add', 'view': {'type': 'leafloomBoard', 'name': 'Board'}, 'preset': 'tasks'})
        note = self.record('Previously-done', status='done'); source = (self.root/note['path']).read_bytes(); original = (self.root/'Media.base').read_bytes()
        command = {'type': 'field.set', 'key': 'status', 'field': {'options': ['review', 'complete'], 'optionMeta': {
            'review': {'label': 'Review', 'color': 'orange'}, 'complete': {'label': 'Complete', 'color': 'green'}, 'done': {'label': 'Done', 'color': 'green'}}}}
        with self.assertRaisesRegex(ValueError, 'boardChooseStates'): self.command(command)
        self.assertEqual((self.root/'Media.base').read_bytes(), original)
        self.command({**command, 'task_setup': {**self.c['tasks'], 'initialStatus': 'review', 'completedStatuses': ['complete']}})
        self.assertEqual(self.c['tasks']['initialStatus'], 'review'); self.assertEqual(self.c['tasks']['completedStatuses'], ['complete'])
        self.assertEqual((self.root/note['path']).read_bytes(), source)
        board = next(v for v in self.c['views'] if v['type'] == 'leafloomBoard')
        historical = next(g for g in self.db.query('Media.base', board['id'])['groups'] if g['value'] == 'done')
        self.assertFalse(historical['configured']); self.assertEqual(historical['count'], 1)
        created = self.record('New-workflow')
        self.assertEqual(self.db.files.read(created['path'])['metadata']['status'], 'review')
        before = (self.root/'Media.base').read_bytes()
        with self.assertRaisesRegex(ValueError, 'invalidOption'):
            self.command({'type': 'field.set', 'key': 'status', 'field': {'optionMeta': {'review': {'color': 'invalid-color'}}}})
        self.assertEqual((self.root/'Media.base').read_bytes(), before)

    def test_managed_empty_option_lists_reject_new_assignments_and_keep_existing_values(self):
        for key, kind, value in [('choice', 'select', 'old'), ('labels', 'multiselect', ['old'])]:
            self.command({'type': 'field.set', 'key': key, 'field': {'type': kind, 'options': ['old'], 'allowCustomOptions': False}})
            note = self.record('Empty-'+key, **{key: value}); before = (self.root/note['path']).read_bytes()
            self.command({'type': 'field.set', 'key': key, 'field': {'options': []}})
            self.assertEqual((self.root/note['path']).read_bytes(), before)
            self.command({'type': 'record.update', 'path': note['path'], 'record_revision': note['revision'], 'values': {key: value}})
            with self.assertRaisesRegex(ValueError, 'configured option'): self.record('Reject-'+key, **{key: value})
        # Existing unrestricted empty lists remain compatible.
        self.record('Legacy-free-choice', category='Unconfigured label')
