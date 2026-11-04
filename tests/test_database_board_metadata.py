"""Metadata handoff regressions with real database services in isolated vaults."""
import json
import unittest
from unittest.mock import patch
from starlette.testclient import TestClient
from tests import test_databases as fixture
from vault_rag.note_operations import NoteOperations
from vault_rag.web_server import create_app


class DatabaseBoardMetadataTests(unittest.TestCase):
    setUp = fixture.DatabaseTests.setUp
    refresh = fixture.DatabaseTests.refresh
    command = fixture.DatabaseTests.command
    record = fixture.DatabaseTests.record

    def test_incremental_ready_catalog_does_not_require_another_global_scan(self):
        self.record('Task', category='before')
        path = self.root/'Media/Task.md'
        path.write_text(path.read_text().replace('category: before', 'category: after'))
        self.runtime.catalog.apply(['Media/Task.md'])
        self.assertTrue(self.runtime.catalog.metadata_ready)
        with patch.object(self.runtime, 'ensure_metadata', side_effect=AssertionError('unnecessary full scan')):
            self.assertEqual(self.db.query('Media.base')['results'][0]['metadata']['category'], 'after')
        version = self.runtime.catalog.version
        self.runtime.catalog.apply(['Media/Task.md'])
        self.assertEqual(self.runtime.catalog.version, version, 'duplicate watcher event must not invalidate a current move')
        self.assertEqual(self.config.data['include_roots'], [])

    def test_metadata_finishes_between_the_readiness_checks(self):
        self.runtime.catalog.metadata_ready = False
        def finish():
            self.runtime.catalog.metadata_ready = True
            return True
        with patch.object(self.runtime, 'ensure_metadata', side_effect=finish):
            self.assertIs(self.db.notes.metadata(), self.runtime.catalog)

    def test_incremental_update_does_not_promote_an_unprepared_namespace(self):
        self.runtime.catalog.metadata_ready = False
        self.runtime.catalog.complete_namespace = False
        (self.root/'Media/New.md').write_text('---\ncategory: hidden until prepared\n---\n')
        self.runtime.catalog.apply(['Media/New.md'])
        self.assertFalse(self.runtime.catalog.metadata_ready)
        self.assertFalse(self.runtime.catalog.complete_namespace)

    def test_http_metadata_race_is_retryable_before_query_or_move_writes(self):
        self.command({'type': 'view.add', 'view': {'type': 'leafloomBoard', 'name': 'Tasks'}, 'preset': 'tasks'})
        record = self.record('Task')
        config = self.c; view = config['views'][-1]
        summary = self.db.query('Media.base', view['id'])
        app = create_app(self.config, self.runtime, start_background=False)
        token = (self.config.directory/'auth-token').read_text().strip()
        real_metadata = NoteOperations.metadata
        def race(notes):
            # The route sees a ready catalog; the worker invalidates it before the service reads it.
            notes.runtime.catalog.metadata_ready = False
            return real_metadata(notes)
        before_note = (self.root/record['path']).read_bytes()
        before_base = (self.root/'Media.base').read_bytes()
        with TestClient(app, base_url='http://127.0.0.1:18080', headers={'Authorization': 'Bearer '+token}) as client:
            cases = [('/api/bases/query', {'path': 'Media.base', 'view_id': view['id']}),
                     ('/api/bases/commands', {'path': 'Media.base', 'workspace_revision': self.ws,
                      'expected_revision': config['revision'], 'operation_id': 'pending-move',
                      'command': {'type': 'record.move', 'view_id': view['id'], 'path': record['path'],
                       'record_revision': record['revision'], 'catalog_version': summary['catalog_version'], 'group_key': json.dumps('done')}})]
            for route, body in cases:
                self.runtime.catalog.metadata_ready = True
                with patch.object(NoteOperations, 'metadata', race), patch.object(self.runtime, 'ensure_metadata', return_value=False):
                    response = client.post(route, json=body)
                self.assertEqual(response.status_code, 503, response.text)
                self.assertTrue(response.json()['pending'])
                self.assertEqual(response.json()['error_code'], 'metadata_pending')
                self.assertEqual(response.json()['retry_after_ms'], 600)
                self.assertEqual((self.root/record['path']).read_bytes(), before_note)
                self.assertEqual((self.root/'Media.base').read_bytes(), before_base)


if __name__ == '__main__':
    unittest.main()
