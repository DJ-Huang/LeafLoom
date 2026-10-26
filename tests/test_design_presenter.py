"""Presenter-note persistence, revision history, and audience privacy boundaries."""
import copy
import json
import unittest
import zipfile
from unittest.mock import patch
from vault_rag.design_presenter import audience_document, validate_notes
from vault_rag.design_publishing import plan
from tests import test_design_documents as documents_tests
from tests.test_design_publishing import document
from tests import test_html_projects as website_tests
from tests import test_design_workspace as workspace_tests


class NotesTests(unittest.TestCase):
    def test_schema_is_optional_but_validates_stable_cues(self):
        for value in ({'overview': '', 'cues': {}}, {'overview': 'Private', 'cues': {'case:stable': 'Speaker text'}}):
            validate_notes(value)
        for value in ([], {'overview': 1}, {'cues': {'': 'x'}}, {'cues': {'id': []}}, {'extra': 'x'}):
            with self.assertRaises(ValueError):
                validate_notes(value)

    def test_publication_snapshot_excludes_notes_without_mutating_source(self):
        source = document()
        source['pages'][0]['presenterNotes'] = {'overview': 'PRIVATE', 'cues': {'step:one': 'PRIVATE'}}
        before = copy.deepcopy(source)
        public = audience_document(source)
        self.assertNotIn('presenterNotes', public['pages'][0])
        items, _ = plan(source, ['one'])
        self.assertNotIn('PRIVATE', json.dumps(items))
        self.assertEqual(source, before)


class NotesHistoryTests(unittest.TestCase):
    setUp = documents_tests.DesignDocumentTests.setUp
    tearDown = documents_tests.DesignDocumentTests.tearDown
    apply = documents_tests.DesignDocumentTests.apply
    history = documents_tests.DesignDocumentTests.history
    # Reuse only the fixture, not the inherited full suite.
    def test_presenter_notes_save_duplicate_undo_redo_and_revision(self):
        notes = {'overview': 'Private lecture', 'cues': {'step:stable': 'Observe reflection'}}
        self.apply({'type': 'page.update', 'page_id': self.page, 'patch': {'presenterNotes': notes}}, label='Notes')
        self.assertEqual(self.service.read(self.directory)['document']['pages'][0]['presenterNotes'], notes)
        self.history('undo')
        self.assertNotIn('presenterNotes', self.current['document']['pages'][0])
        self.history('redo')
        self.apply({'type': 'page.duplicate', 'page_id': self.page, 'new_id': 'copy'})
        self.assertEqual(self.current['document']['pages'][1]['presenterNotes'], notes)


class NotesOriginTests(unittest.TestCase):
    setUp = website_tests.WebsiteTests.setUp
    tearDown = website_tests.WebsiteTests.tearDown
    put = website_tests.WebsiteTests.put
    project = website_tests.WebsiteTests.project
    session = website_tests.WebsiteTests.session
    def test_project_origin_cannot_read_notes_from_managed_source(self):
        source = document()
        source['pages'][0]['presenterNotes'] = {'overview': 'PRIVATE', 'cues': {}}
        self.put('site/Design/studio/project.json', json.dumps(source).encode())
        session = self.session()
        response = self.client.get(session['origin'] + '/Design/studio/project.json')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('PRIVATE', response.text)
        self.assertIn('no-store', response.headers['cache-control'])
        self.assertIn('PRIVATE', (self.root / 'site/Design/studio/project.json').read_text())


class NotesExportTests(unittest.TestCase):
    setUp = workspace_tests.DesignWorkspaceTests.setUp
    tearDown = workspace_tests.DesignWorkspaceTests.tearDown
    create = workspace_tests.DesignWorkspaceTests.create
    summary = workspace_tests.DesignWorkspaceTests.summary

    def test_html_export_strips_notes_and_project_copy_retains_them(self):
        notes = {'overview': 'PRIVATE-NOTE', 'cues': {'step:one': 'PRIVATE-NOTE'}}
        page_id = self.project['document']['pages'][0]['id']
        self.docs.apply(self.directory, [{'type': 'page.update', 'page_id': page_id, 'patch': {'presenterNotes': notes}}], self.project['revision'], 'notes')
        self.workspace.copy_project(self.directory, 'Projects/Copy')
        self.assertEqual(self.docs.read('Projects/Copy')['document']['pages'][0]['presenterNotes'], notes)
        with patch.object(self.workspace, 'session', return_value={'origin': 'http://localhost:1000', 'id': 'session'}):
            exported = self.workspace.export(self.directory)
        with zipfile.ZipFile(self.root / exported['path']) as archive:
            self.assertNotIn(b'PRIVATE-NOTE', archive.read('document.js'))
            self.assertNotIn(b'presenterNotes', archive.read('document.js'))
