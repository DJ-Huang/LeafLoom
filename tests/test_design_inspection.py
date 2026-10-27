"""Bounded MCP projections with large embedded source and exact source recovery."""
import copy
import json
import unittest
from unittest.mock import patch

from tests import test_design_documents as fixtures
from vault_rag.local_state import ConflictError


class DesignInspectionTests(unittest.TestCase):
    setUp = fixtures.DesignDocumentTests.setUp
    tearDown = fixtures.DesignDocumentTests.tearDown
    apply = fixtures.DesignDocumentTests.apply
    node = fixtures.DesignDocumentTests.node

    def large_document(self):
        document = copy.deepcopy(self.current['document'])
        for index in range(25):
            document['pages'].append({'id': f'page-{index}', 'name': f'Page {index}', 'width': 720, 'height': 1560,
                'css': '/* private page source */' * 1000,
                'nodes': [self.node(f'node-{index}-{child}', type='html',
                    props={'html': '<div>large embedded source</div>' * 200}) for child in range(30)]})
        document['scripts']['large-script'] = {'id': 'large-script', 'source': '// private script\n' * 10000}
        return document

    def test_large_document_defaults_paginate_without_copying_source(self):
        self.apply({'type': 'document.replace', 'document': self.large_document()})
        original = json.dumps(self.current, ensure_ascii=False)
        with patch('vault_rag.design_documents.copy.deepcopy', side_effect=AssertionError('Summary copied full document')):
            first = self.service.inspect(self.directory)
        self.assertNotIn('document', first)
        self.assertEqual(first['total'], 26)
        self.assertEqual(first['next_offset'], 20)
        self.assertEqual(first['manifest']['counts']['scripts'], 1)
        self.assertEqual(first['manifest']['pages'][1]['node_count'], 30)
        summary = json.dumps(first, ensure_ascii=False)
        self.assertNotIn('private page source', summary)
        self.assertNotIn('large embedded source', summary)
        self.assertLess(len(summary), 12000)
        self.assertLess(len(summary), len(original) // 100)
        second = self.service.inspect(self.directory, offset=first['next_offset'], expected_revision=first['revision'])
        self.assertIsNone(second['next_offset'])
        self.assertEqual(len(second['manifest']['pages']), 6)
        # Caller mutation cannot contaminate the revision-local index.
        first['manifest']['pages'][0]['name'] = 'Caller change'
        self.assertEqual(self.service.inspect(self.directory)['manifest']['pages'][0]['name'], 'Home')
        print(f'\nDesign payload regression: full={len(original)} chars; summary={len(summary)} chars')

    def test_selected_page_and_node_reads_do_not_include_other_pages(self):
        node_id = 'n' * 200
        parent = self.node(node_id, type='container', children=[self.node('child', props={'text': 'X' * 500})])
        self.apply({'type': 'node.create', 'page_id': self.page, 'node': parent},
                   {'type': 'page.create', 'page': {'id': 'other', 'nodes': [self.node('unrelated')]}})
        index = self.service.inspect(self.directory, self.page, limit=1)
        self.assertEqual(index['nodes'][0]['id'], node_id)
        self.assertEqual(index['nodes'][0]['child_count'], 1)
        self.assertNotIn('children', index['nodes'][0])
        self.assertEqual(index['next_offset'], 1)
        child = self.service.inspect(self.directory, self.page, offset=1)['nodes'][0]
        self.assertEqual(child['parent_id'], node_id)
        self.assertTrue(child['text_truncated'])
        exact = self.service.inspect(self.directory, self.page, node_id=node_id, full=True)
        self.assertEqual(exact['nodes'][0], parent)
        page = self.service.inspect(self.directory, self.page, full=True)
        self.assertEqual([p['id'] for p in page['pages']], [self.page])
        self.assertNotIn('document', page)
        self.assertNotIn('unrelated', json.dumps(page))
        self.assertEqual(self.service.inspect(self.directory, full=True)['document'], self.current['document'])

    def test_resource_index_and_exact_source_preserve_all_data(self):
        document = self.large_document()
        self.apply({'type': 'document.replace', 'document': document})
        index = self.service.inspect(self.directory, section='scripts')
        self.assertEqual(index['scripts'], [{'id': 'large-script'}])
        source = self.service.inspect(self.directory, section='scripts', item_id='large-script', full=True)
        self.assertEqual(source['scripts'], [document['scripts']['large-script']])
        self.assertNotIn('pages', source)

    def test_pagination_rejects_stale_revision_and_invalid_selectors(self):
        before = self.service.inspect(self.directory)
        self.apply({'type': 'project.update', 'patch': {'name': 'New version'}})
        with self.assertRaises(ConflictError):
            self.service.inspect(self.directory, expected_revision=before['revision'])
        for args in ({'page_id': 'missing'}, {'section': 'nodes'}, {'node_id': 'missing'},
                     {'section': 'scripts', 'page_id': self.page}, {'section': 'scripts', 'item_id': 'missing'},
                     {'manifest': True, 'full': True}, {'section': 'nodes', 'page_id': self.page, 'full': True}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.service.inspect(self.directory, **args)

    def test_compact_undo_redo_receipts_and_retry_keep_revision_guards(self):
        self.apply({'type': 'node.create', 'page_id': self.page, 'node': self.node()})
        args = (self.directory, 'undo', self.current['revision'], 'compact-undo')
        result = self.service.history(*args, include_document=False)
        self.assertNotIn('document', result)
        replay = self.service.history(*args, include_document=False)
        self.assertTrue(replay['replayed'])
        self.assertNotIn('document', replay)
        redone = self.service.history(self.directory, 'redo', result['revision'], 'compact-redo', include_document=False)
        self.assertNotIn('document', redone)
        self.assertEqual(self.service.read(self.directory)['document']['pages'][0]['nodes'][0]['id'], 'cat')


if __name__ == '__main__':
    unittest.main()
