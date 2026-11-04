"""Stable database view order preserves notes, settings and concurrency guards."""
import copy
import unittest
from vault_rag.databases import Databases
from vault_rag.local_state import ConflictError
from tests import test_databases as fixture


class DatabaseViewOrderTests(unittest.TestCase):
    setUp = fixture.DatabaseTests.setUp
    refresh = fixture.DatabaseTests.refresh
    command = fixture.DatabaseTests.command
    record = fixture.DatabaseTests.record

    def test_repeated_moves_persist_and_preserve_settings_ids_records_and_fixed_queries(self):
        self.command({'type': 'view.add', 'view': {'type': 'leafloomBoard', 'name': 'Board'}, 'preset': 'tasks'})
        self.command({'type': 'view.update', 'view_id': self.c['views'][2]['id'], 'patch': {
            'leafloom': {'vendor': {'keep': True}, 'conditions': [{'field': 'category', 'operator': 'eq', 'value': 'design'}]}}})
        record = self.record('Original', category='design'); contents = (self.root/record['path']).read_bytes()
        originals = {v['id']: copy.deepcopy(v) for v in self.c['views']}; ids = list(originals)
        for moved, relative, after, expected in [(ids[0], ids[-1], True, ids[1:]+ids[:1]),
                                                  (ids[0], ids[1], False, ids)]:
            self.command({'type': 'view.move', 'view_id': moved,
                          'after_view_id' if after else 'before_view_id': relative})
            other = Databases(self.config, self.runtime)
            self.assertEqual([v['id'] for v in other.config_read('Media.base')['views']], expected)
            self.assertEqual({v['id']: v for v in self.c['views']}, originals)
            self.assertEqual(other.query('Media.base', ids[2])['results'][0]['path'], record['path'])
        self.assertEqual((self.root/record['path']).read_bytes(), contents)

    def test_invalid_positions_never_save(self):
        a, b = [v['id'] for v in self.c['views'][:2]]; before = (self.root/'Media.base').read_bytes()
        for args in [{}, {'before_view_id': b, 'after_view_id': b}, {'before_view_id': a},
                     {'after_view_id': 'missing'}, {'before_view_id': ''}, {'after_view_id': 1}]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.command({'type': 'view.move', 'view_id': a, **args})
        for source in ['', 'missing', [], 'Table']:
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.command({'type': 'view.move', 'view_id': source, 'after_view_id': b})
        self.assertEqual((self.root/'Media.base').read_bytes(), before)

    def test_stale_configuration_and_workspace_are_rejected_and_noop_does_not_write(self):
        a, b = [v['id'] for v in self.c['views'][:2]]; old = self.c['revision']
        result = self.command({'type': 'view.move', 'view_id': a, 'before_view_id': b})
        self.assertFalse(result['changed']); self.assertEqual(result['revision'], old)
        self.command({'type': 'view.move', 'view_id': a, 'after_view_id': b})
        current = (self.root/'Media.base').read_bytes()
        for workspace, revision in [(self.ws, old), ('stale', self.c['revision'])]:
            with self.assertRaises(ConflictError):
                self.db.command('Media.base', {'type': 'view.move', 'view_id': a, 'before_view_id': b}, workspace, revision)
        self.assertEqual((self.root/'Media.base').read_bytes(), current)

    def test_legacy_ids_and_unknown_yaml_survive_reordering(self):
        path = self.root/'Media.base'; _, data, yaml = self.db.document('Media.base')
        for v in data['views']: v['leafloom'].pop('id')
        data['views'][0]['vendor'] = {'retained': [1, 2]}
        data['views'][1]['type'] = 'vendorView'
        import io
        out = io.StringIO(); yaml.dump(data, out); path.write_text('# Original comment\nunknown: keep\n'+out.getvalue())
        self.refresh()
        self.command({'type': 'view.move', 'view_id': 'legacy-0', 'after_view_id': 'legacy-3'})
        self.assertEqual([v['id'] for v in self.c['views']], ['legacy-1', 'legacy-2', 'legacy-3', 'legacy-0'])
        self.assertEqual(self.c['views'][-1]['vendor'], {'retained': [1, 2]})
        self.assertEqual(self.c['views'][0]['type'], 'vendorView')
        self.assertIn('# Original comment', path.read_text()); self.assertIn('unknown: keep', path.read_text())
