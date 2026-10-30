"""View-scoped creation defaults preserve explicit intent and retry receipts."""
import unittest
from tests import test_database_board as fixture


class DatabaseCreationDefaultsTests(unittest.TestCase):
    setUp = fixture.DatabaseBoardTests.setUp
    refresh = fixture.DatabaseBoardTests.refresh
    command = fixture.DatabaseBoardTests.command
    board = fixture.DatabaseBoardTests.board

    def configure(self, view, conditions, **patch):
        self.command({'type': 'view.update', 'view_id': view['id'], 'patch': {**patch, 'leafloom': {'conditions': conditions}}})

    def field(self, key, kind='select', **extra):
        self.command({'type': 'field.set', 'key': key, 'field': {'type': kind, **extra}})

    def create(self, view, title, **extra):
        return self.command({'type': 'record.create', 'view_id': view['id'], 'title': title, 'return_record': True, **extra}, operation_id='create-'+title)

    def test_all_view_types_inherit_record_type_and_remain_visible(self):
        self.board(); self.field('record_type', options=['task', 'document', 'setting'])
        for view, kind in zip(self.c['views'], ['setting', 'task', 'document', 'task', 'task']):
            with self.subTest(view=view['type']):
                self.configure(view, [{'field': 'record_type', 'operator': 'eq', 'value': kind}])
                result = self.create(view, view['type'])
                self.assertEqual(result['record']['metadata']['record_type'], kind)
                self.assertTrue(result['visible'])
                rows, _ = self.db.query_rows(self.c, next(v for v in self.c['views'] if v['id'] == view['id']))
                self.assertIn(result['path'], [r['path'] for r in rows])

    def test_column_and_explicit_values_override_view_and_task_defaults(self):
        view = self.board(); self.field('record_type', options=['task', 'document'])
        self.configure(view, [{'field': 'record_type', 'operator': 'eq', 'value': 'task'},
                              {'field': 'status', 'operator': 'eq', 'value': 'in-progress'}])
        result = self.create(view, 'Inferred')
        self.assertEqual(result['record']['metadata']['status'], 'in-progress')
        self.assertTrue(result['visible'])
        result = self.create(view, 'Column', group_key='"done"')
        self.assertEqual(result['record']['metadata']['status'], 'done')
        self.assertFalse(result['visible'])
        result = self.create(view, 'Explicit', group_key='"done"', values={'record_type': 'document', 'status': 'open'})
        self.assertEqual(result['record']['metadata']['record_type'], 'document')
        self.assertEqual(result['record']['metadata']['status'], 'open')
        self.assertFalse(result['visible'])
        result = self.create(view, 'Explicit-null', values={'record_type': None})
        self.assertIsNone(result['record']['metadata']['record_type'])

    def test_ambiguous_negative_invalid_and_readonly_filters_do_not_invent_values(self):
        view = self.c['views'][0]
        self.field('record_type', options=['task', 'document']); self.field('score', 'number')
        self.field('locked', 'text', readonly=True)
        self.configure(view, [
            {'field': 'record_type', 'operator': 'eq', 'value': 'task'},
            {'field': 'record_type', 'operator': 'eq', 'value': 'document'},
            {'field': 'score', 'operator': 'eq', 'value': 'not a number'},
            {'field': 'locked', 'operator': 'eq', 'value': 'readonly'},
            {'field': 'file.ctime', 'operator': 'eq', 'value': 1},
            {'field': 'title', 'operator': 'eq', 'value': 'Do not replace the title'},
            {'field': 'category', 'operator': 'contains', 'value': 'not a default'},
        ])
        result = self.create(view, 'User-title', search='not the title')
        for key in ['record_type', 'score', 'locked', 'category', 'file.ctime']:
            self.assertNotIn(key, result['record']['metadata'])
        self.assertEqual(result['record']['title'], 'User-title'); self.assertFalse(result['visible'])
        self.configure(view, [{'field': 'record_type', 'operator': 'eq', 'value': 'retired'}])
        self.assertNotIn('record_type', self.create(view, 'Historical-option')['record']['metadata'])
        self.configure(view, [{'field': 'record_type', 'operator': 'neq', 'value': 'task'},
                              {'field': 'score', 'operator': 'gt', 'value': 2}])
        self.assertNotIn('score', self.create(view, 'Range')['record']['metadata'])

    def test_aliases_zero_false_dates_and_repeated_equalities_are_typed(self):
        view = self.c['views'][0]
        for key, kind in [('note.record_type', 'text'), ('score', 'number'), ('checked', 'checkbox')]: self.field(key, kind)
        self.configure(view, [{'field': 'note.record_type', 'operator': 'eq', 'value': 'document'},
                              {'field': 'note.record_type', 'operator': 'eq', 'value': 'document'},
                              {'field': 'score', 'operator': 'eq', 'value': 0},
                              {'field': 'checked', 'operator': 'eq', 'value': False},
                              {'field': 'start_date', 'operator': 'eq', 'value': '2028-02-29'}])
        result = self.create(view, 'Typed')
        self.assertEqual(result['record']['metadata']['record_type'], 'document')
        self.assertEqual(result['record']['metadata']['score'], 0)
        self.assertIs(result['record']['metadata']['checked'], False)
        self.assertEqual(result['record']['metadata']['start_date'], '2028-02-29')
        self.assertTrue(result['visible'])

    def test_invalid_or_null_equality_does_not_resolve_a_conflicting_value(self):
        view = self.c['views'][0]; self.field('record_type', options=['task', 'document'])
        for index, value in enumerate(['retired', None]):
            for reverse in [False, True]:
                conditions = [{'field': 'record_type', 'operator': 'eq', 'value': v} for v in ['task', value]]
                self.configure(view, conditions[::-1] if reverse else conditions)
                result = self.create(view, f'Conflicting-{index}-{reverse}')
                self.assertNotIn('record_type', result['record']['metadata'])
                self.assertFalse(result['visible'])

    def test_retry_replays_original_defaults_after_filter_changes_and_duplicate_keeps_source_type(self):
        view = self.c['views'][0]; self.field('record_type', options=['document', 'setting'])
        self.configure(view, [{'field': 'record_type', 'operator': 'eq', 'value': 'document'}])
        command = {'type': 'record.create', 'title': 'Saved', 'view_id': view['id'], 'return_record': True}
        first = self.command(command, operation_id='receipt')
        self.configure(view, [{'field': 'record_type', 'operator': 'eq', 'value': 'setting'}])
        self.assertEqual(first, self.db.command('Media.base', command, self.ws, 'old', 'receipt'))
        result = self.command({'type': 'record.duplicate', 'path': first['path'], 'record_revision': first['revision'],
                               'view_id': view['id'], 'return_record': True}, operation_id='copy')
        self.assertEqual(result['record']['metadata']['record_type'], 'document')
        self.assertFalse(result['visible'])
        self.assertEqual(len(list((self.root/'Media').glob('*.md'))), 2)

    def test_expression_filters_are_never_executed_to_compute_defaults(self):
        _, data, _ = self.db.document('Media.base')
        self.assertEqual(self.db.creation_defaults(data, {'filters': {'or': ['note.kind == "task"', 'note.kind == "document"']}}), {})
