"""Fast refreshes must still honor disk versions, isolated drafts and queued writes."""
import os
import threading
import time
import unittest
from unittest.mock import patch
from ruamel.yaml import YAML
from tests import test_databases as fixture
from vault_rag.note_operations import NoteError


class DatabaseRefreshTests(unittest.TestCase):
    setUp = fixture.DatabaseTests.setUp
    refresh = fixture.DatabaseTests.refresh
    command = fixture.DatabaseTests.command
    record = fixture.DatabaseTests.record

    def test_parsed_config_is_reused_without_sharing_mutable_edit_state(self):
        self.db._documents.clear()
        original = YAML.load
        calls = []
        def load(yaml, text, *args, **kwargs):
            calls.append(text)
            return original(yaml, text, *args, **kwargs)
        with patch.object(YAML, 'load', load):
            first = self.db.config_read('Media.base')
            _, editable, _ = self.db.document('Media.base')
            editable['views'][0]['name'] = 'Unsaved edit'
            for _ in range(3): self.db.query('Media.base')
            self.assertEqual(self.db.config_read('Media.base')['views'][0]['name'], first['views'][0]['name'])
        self.assertEqual(len(calls), 1)

    def test_config_cache_uses_content_version_even_when_file_stamp_is_unchanged(self):
        file = self.root/'Media.base'
        before = file.stat(); text = file.read_text()
        self.db.config_read('Media.base')
        file.write_text(text.replace('name: Table', 'name: Other'))
        os.utime(file, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(self.db.config_read('Media.base')['views'][0]['name'], 'Other')
        self.assertNotEqual(self.db.config_read('Media.base')['revision'], self.c['revision'])

    def test_cached_yaml_keeps_directives_and_unknown_tagged_fields(self):
        file = self.root/'Media.base'
        file.write_text('%TAG !vendor! tag:example.test,2026:\n---\n# Preserve this directive\nunknown: !vendor!kind kept\n' + file.read_text())
        self.refresh()
        for _ in range(2): self.db.config_read('Media.base')
        self.command({'type': 'field.set', 'key': 'description', 'field': {'type': 'text'}})
        self.assertIn('%TAG !vendor!', file.read_text())
        self.assertIn('# Preserve this directive', file.read_text())
        self.assertEqual(YAML().load(file.read_text())['unknown'].tag.value, 'tag:example.test,2026:kind')

    def test_row_snapshot_cache_refreshes_on_catalog_and_configuration_changes(self):
        record = self.record('Snapshot', category='Before')
        self.assertEqual(self.db.query('Media.base')['results'][0]['metadata']['category'], 'Before')
        self.command({'type': 'record.update', 'path': record['path'], 'record_revision': record['revision'], 'values': {'category': 'After'}})
        self.assertEqual(self.db.query('Media.base')['results'][0]['metadata']['category'], 'After')
        view = self.c['views'][0]['id']
        self.command({'type': 'view.update', 'view_id': view, 'patch': {'leafloom': {'conditions': [{'field': 'category', 'operator': 'eq', 'value': 'Before'}]}}})
        self.assertEqual(self.db.query('Media.base')['total'], 0)

    def test_config_cache_does_not_cross_vaults(self):
        self.db.config_read('Media.base')
        other = self.home/'other'; other.mkdir()
        (other/'Media.base').write_text('views:\n  - type: list\n    name: Other vault\n')
        self.config.save({'root': str(other)})
        self.assertEqual(self.db.config_read('Media.base')['views'][0]['name'], 'Other vault')

    def test_queue_blocks_stale_queries_but_does_not_force_a_global_scan(self):
        record = self.record('Queued')
        runtime = self.runtime
        runtime.root = str(self.config.root)
        with runtime.pending_lock: runtime.pending.clear()
        worker = threading.Thread(target=runtime.loop, daemon=True)
        runtime.thread = worker; runtime.threads = [worker]; worker.start()
        with patch.object(runtime.catalog, 'prepare_metadata', side_effect=AssertionError('unnecessary global scan')):
            with runtime.catalog.update_lock:
                self.db.notes.properties(record['path'], self.ws, record['revision'], {'category': 'Updated'})
                self.assertTrue(runtime.catalog.metadata_ready)
                self.assertTrue(runtime.catalog_pending())
                self.assertFalse(runtime.ensure_metadata())
                with self.assertRaises(NoteError) as pending: self.db.query('Media.base')
                self.assertEqual(pending.exception.code, 'metadata_pending')
                self.assertEqual(pending.exception.details['retry_after_ms'], 25)
            deadline = time.monotonic()+3
            while runtime.catalog_pending() and time.monotonic() < deadline: time.sleep(.01)
            self.assertFalse(runtime.catalog_pending())
            self.assertEqual(self.db.query('Media.base')['results'][0]['metadata']['category'], 'Updated')
        self.assertEqual(self.config.data['include_roots'], [])

    def test_creation_receipt_can_return_the_saved_row_before_indexing(self):
        command = {'type': 'record.create', 'title': 'Immediate', 'values': {}, 'return_record': True}
        result = self.db.command('Media.base', command, self.ws, self.c['revision'], 'immediate-row')
        self.assertTrue(result['visible'])
        self.assertEqual(result['record']['revision'], result['revision'])
        self.assertEqual(result['record']['title'], 'Immediate')
        self.assertEqual(result['record']['path'], result['path'])
        self.assertNotIn(result['path'], self.runtime.catalog.entries)
        self.assertEqual(self.db.command('Media.base', command, self.ws, 'old', 'immediate-row'), result)

    def test_recent_row_checks_are_filtered_and_independent_of_pagination(self):
        for i in range(205): (self.root/'Media'/f'{i:03}.md').write_text('# Fixture\n')
        record = self.record('ZZZ')
        page = self.db.query('Media.base', recent_paths=[record['path'], 'Outside.md'])
        self.assertNotIn(record['path'], [r['path'] for r in page['results']])
        self.assertEqual([r['path'] for r in page['recent_records']], [record['path']])
        self.assertEqual(self.db.query('Media.base', search='not-matching', recent_paths=[record['path']])['recent_records'], [])
        with self.assertRaises(ValueError): self.db.query('Media.base', recent_paths=['x']*21)


if __name__ == '__main__': unittest.main()
