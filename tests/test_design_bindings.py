"""Stable binding validation, projection and durable transaction regressions."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from vault_rag.design_bindings import binding_status, resolve_document, resolve_page
from vault_rag.design_documents import DesignDocuments
from vault_rag.local_state import ConflictError, Files, LocalConfig


class DesignBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        home = Path(self.temp.name)
        root = home / 'vault'
        (root / 'Projects/Test').mkdir(parents=True)
        config = LocalConfig(home / 'config')
        config.save({'root': str(root), 'include_roots': ['Projects']})
        self.service = DesignDocuments(SimpleNamespace(config=config, files=Files(config), runtime=SimpleNamespace()))
        self.current = self.service.create('Projects/Test', 'Test')
        self.page = self.current['document']['pages'][0]['id']
        self.apply({'type': 'node.create', 'page_id': self.page, 'node': {'id': 'title', 'type': 'text', 'props': {'text': 'Hello'}, 'script': {'source': 'export function mount(ctx) {}'}}},
                   {'type': 'binding.set', 'key': 'hero.title', 'kind': 'text', 'value': 'Hello'},
                   {'type': 'node.bind', 'page_id': self.page, 'node_id': 'title', 'key': 'hero.title'},
                   {'type': 'variant.set', 'variant': {'id': 'ja', 'locale': 'ja-JP', 'context': {'audience': 'launch'}}})

    def tearDown(self):
        self.temp.cleanup()

    def apply(self, *commands):
        self.current = self.service.apply('Projects/Test', list(commands), self.current['revision'], 'op-' + self.current['revision'])
        return self.current['document']

    def test_projection_fallback_and_stale_values(self):
        document = self.current['document']
        self.assertEqual(binding_status(document, 'ja'), {'missing': ['hero.title'], 'stale': []})
        self.assertEqual(resolve_page(document, self.page, 'ja')['nodes'][0]['props']['text'], 'Hello')
        self.apply({'type': 'variant.value.set', 'id': 'ja', 'key': 'hero.title', 'value': 'こんにちは'})
        document = self.apply({'type': 'binding.set', 'key': 'hero.title', 'value': 'Welcome'})
        self.assertEqual(binding_status(document, 'ja')['stale'], ['hero.title'])
        self.assertEqual(resolve_page(document, self.page, 'ja')['nodes'][0]['props']['text'], 'こんにちは')
        self.assertEqual(resolve_page(document, self.page)['nodes'][0]['props']['text'], 'Welcome')

    def test_variant_projection_preserves_source_scripts_and_components(self):
        document = self.apply({'type': 'variant.set', 'variant': {'id': 'ja', 'layout': {'title': {'fontSize': 21, 'width': 400}}, 'pageLayout': {self.page: {'height': 1900}}}})
        before = copy.deepcopy(document)
        resolved = resolve_document(document, 'ja')
        self.assertEqual(resolved['pages'][0]['height'], 1900)
        self.assertEqual(resolved['pages'][0]['nodes'][0]['style']['fontSize'], 21)
        self.assertEqual(resolved['pages'][0]['nodes'][0]['script'], document['pages'][0]['nodes'][0]['script'])
        self.assertEqual(document, before)
        self.assertNotIn('nodes', document['variants']['ja'])

    def test_undo_redo_and_reload_preserve_source_revisions(self):
        self.apply({'type': 'variant.value.set', 'id': 'ja', 'key': 'hero.title', 'value': 'こんにちは'})
        self.apply({'type': 'binding.set', 'key': 'hero.title', 'value': 'New'})
        self.current = self.service.history('Projects/Test', 'undo', self.current['revision'], 'undo')
        self.assertEqual(binding_status(self.current['document'], 'ja')['stale'], [])
        self.current = self.service.history('Projects/Test', 'redo', self.current['revision'], 'redo')
        reopened = DesignDocuments(self.service.studio).read('Projects/Test')
        self.assertEqual(binding_status(reopened['document'], 'ja')['stale'], ['hero.title'])
        with self.assertRaises(ConflictError):
            self.service.apply('Projects/Test', [{'type': 'binding.set', 'key': 'hero.title', 'value': 'Conflict'}], 'old-revision', 'conflict')

    def test_shared_image_assets_and_delete_protection(self):
        self.apply({'type': 'asset.register', 'asset': {'id': 'one', 'path': 'Assets/one.png'}},
                   {'type': 'asset.register', 'asset': {'id': 'two', 'path': 'Assets/two.png'}})
        document = self.apply({'type': 'node.create', 'page_id': self.page, 'node': {'id': 'photo', 'type': 'image', 'props': {'src': 'old.png'}}},
                              {'type': 'binding.set', 'key': 'hero.photo', 'kind': 'image', 'value': 'one'},
                              {'type': 'node.bind', 'page_id': self.page, 'node_id': 'photo', 'key': 'hero.photo'},
                              {'type': 'variant.value.set', 'id': 'ja', 'key': 'hero.photo', 'value': 'two'})
        resolved = resolve_document(document, 'ja')
        self.assertEqual(resolved['assets'], document['assets'])
        self.assertEqual(resolved['pages'][0]['nodes'][1]['props']['assetId'], 'two')
        self.assertNotIn('src', resolved['pages'][0]['nodes'][1]['props'])
        with self.assertRaises(ValueError):
            self.apply({'type': 'asset.delete', 'asset_id': 'two'})

    def test_invalid_batch_is_atomic(self):
        revision = self.current['revision']
        with self.assertRaises(ValueError):
            self.apply({'type': 'binding.set', 'key': 'hero.title', 'value': 'Changed'},
                       {'type': 'variant.value.set', 'id': 'ja', 'key': 'hero.title', 'value': 'Bad', 'source_revision': 999})
        self.assertEqual(self.service.read('Projects/Test')['revision'], revision)
        self.assertEqual(self.service.read('Projects/Test')['document']['bindings']['hero.title']['value'], 'Hello')

    def test_reject_unsafe_and_unbounded_metadata(self):
        commands = [
            {'type': 'binding.set', 'key': '../bad', 'kind': 'text', 'value': 'x'},
            {'type': 'binding.set', 'key': 'image', 'kind': 'image', 'value': 'https://evil.example/a'},
            {'type': 'variant.set', 'variant': {'id': 'ja', 'layout': {'title': {'backgroundImage': 'url(https://evil.example)'}}}},
            {'type': 'variant.set', 'variant': {'id': 'ja', 'layout': {'title': {'fontFamily': 'url(x)'}}}},
            {'type': 'variant.set', 'variant': {'id': 'ja', 'context': {'deep': {'nested': True}}}},
            {'type': 'variant.set', 'variant': {'id': 'ja', 'pageLayout': {self.page: {'height': -1}}}},
            {'type': 'binding.delete', 'key': 'hero.title'},
        ]
        for command in commands:
            with self.subTest(command=command), self.assertRaises(ValueError):
                self.apply(command)

    def test_full_variant_metadata_survives_page_projection(self):
        view = self.service.page_view('Projects/Test', self.page)
        self.assertEqual(view['document']['bindings'], self.current['document']['bindings'])
        self.assertEqual(view['document']['variants'], self.current['document']['variants'])

    def test_deletion_prunes_and_duplication_copies_layout_overrides(self):
        self.apply({'type': 'variant.set', 'variant': {'id': 'ja', 'layout': {'title': {'fontSize': 25}}, 'pageLayout': {self.page: {'height': 1200}}}})
        document = self.apply({'type': 'page.duplicate', 'page_id': self.page, 'new_id': 'page-copy'})
        new_node = document['pages'][1]['nodes'][0]['id']
        self.assertEqual(document['variants']['ja']['layout'][new_node], {'fontSize': 25})
        self.assertEqual(document['variants']['ja']['pageLayout']['page-copy'], {'height': 1200})
        document = self.apply({'type': 'page.delete', 'page_id': self.page})
        self.assertNotIn('title', document['variants']['ja']['layout'])
        self.assertNotIn(self.page, document['variants']['ja']['pageLayout'])
        self.current = self.service.history('Projects/Test', 'undo', self.current['revision'], 'undo-delete')
        self.assertIn('title', self.current['document']['variants']['ja']['layout'])

    def test_bound_direct_edit_rejected_unbinding_allows_local_copy(self):
        with self.assertRaisesRegex(ValueError, 'stable binding'):
            self.apply({'type': 'node.update', 'page_id': self.page, 'node_id': 'title', 'patch': {'props': {'text': 'Divergent'}}})
        document = self.apply({'type': 'node.bind', 'page_id': self.page, 'node_id': 'title', 'key': None},
                              {'type': 'node.update', 'page_id': self.page, 'node_id': 'title', 'patch': {'props': {'text': 'Independent'}}})
        self.assertEqual(resolve_page(document, self.page, 'ja')['nodes'][0]['props']['text'], 'Independent')
        self.assertEqual(document['bindings']['hero.title']['value'], 'Hello')

    def test_global_asset_replace_updates_sources_and_variants(self):
        self.apply({'type': 'asset.register', 'asset': {'id': 'one', 'path': 'Assets/one.png'}},
                   {'type': 'asset.register', 'asset': {'id': 'two', 'path': 'Assets/two.png'}},
                   {'type': 'binding.set', 'key': 'art', 'kind': 'image', 'value': 'one'},
                   {'type': 'variant.value.set', 'id': 'ja', 'key': 'art', 'value': 'one'})
        document = self.apply({'type': 'asset.replace', 'asset_id': 'one', 'replacement_id': 'two'},
                              {'type': 'asset.delete', 'asset_id': 'one'})
        self.assertEqual(document['bindings']['art']['value'], 'two')
        self.assertEqual(document['variants']['ja']['values']['art'], {'value': 'two', 'sourceRevision': 2})
        view = self.service.page_view('Projects/Test', self.page)
        self.assertTrue(any(ref.get('binding_key') == 'art' for ref in view['document']['assets']['two']['references']))

    def test_component_binding_projects_without_changing_script_or_identity(self):
        document = copy.deepcopy(self.current['document'])
        document['components']['card'] = {'id': 'card', 'version': 1, 'node': {'id': 'component-title', 'type': 'text', 'props': {'text': 'Original'}, 'script': {'source': 'export function mount(ctx) {}'}}}
        self.apply({'type': 'document.replace', 'document': document},
                   {'type': 'node.bind', 'page_id': 'component:card', 'node_id': 'component-title', 'key': 'hero.title'},
                   {'type': 'variant.value.set', 'id': 'ja', 'key': 'hero.title', 'value': 'こんにちは'})
        component = resolve_document(self.current['document'], 'ja')['components']['card']
        self.assertEqual(component['node']['props']['text'], 'こんにちは')
        self.assertEqual(component['node']['id'], 'component-title')
        self.assertEqual(component['version'], 2)
        self.assertEqual(component['node']['script'], document['components']['card']['node']['script'])

    def test_component_layout_edit_duplicate_delete_and_undo(self):
        self.apply({'type': 'component.create', 'component': {'id': 'card', 'node': {'id': 'card-root', 'type': 'container', 'children': [{'id': 'card-text', 'type': 'text', 'props': {'text': 'Hello'}}]}}},
                   {'type': 'node.bind', 'page_id': 'component:card', 'node_id': 'card-text', 'key': 'hero.title'},
                   {'type': 'variant.set', 'variant': {'id': 'ja', 'layout': {'card-text': {'fontSize': 30}, 'title': {'fontSize': 25}}, 'pageLayout': {self.page: {'height': 1200}}}})
        document = self.apply({'type': 'component.edit', 'component_id': 'card', 'commands': [{'type': 'node.duplicate', 'node_id': 'card-text'}]})
        duplicate_id = document['components']['card']['node']['children'][1]['id']
        self.assertEqual(document['variants']['ja']['layout'][duplicate_id], {'fontSize': 30})
        self.assertIn('title', document['variants']['ja']['layout'])
        self.assertIn(self.page, document['variants']['ja']['pageLayout'])
        document = self.apply({'type': 'component.edit', 'component_id': 'card', 'commands': [{'type': 'node.delete', 'node_id': 'card-text'}]})
        self.assertNotIn('card-text', document['variants']['ja']['layout'])
        self.current = self.service.history('Projects/Test', 'undo', self.current['revision'], 'undo-component-delete')
        self.assertIn('card-text', self.current['document']['variants']['ja']['layout'])
        document = self.apply({'type': 'component.delete', 'component_id': 'card'})
        self.assertEqual(document['variants']['ja']['layout'], {'title': {'fontSize': 25}})

    def test_detach_bound_component_preserves_local_override(self):
        self.apply({'type': 'component.create', 'component': {'id': 'card', 'node': {'id': 'card-text', 'type': 'text', 'props': {'text': 'Hello'}}}},
                   {'type': 'node.bind', 'page_id': 'component:card', 'node_id': 'card-text', 'key': 'hero.title'},
                   {'type': 'node.create', 'page_id': self.page, 'node': {'id': 'card-instance', 'type': 'instance', 'props': {'componentId': 'card', 'overrides': {'card-text': {'props': {'text': 'Local'}}}}}},
                   {'type': 'variant.set', 'variant': {'id': 'ja', 'layout': {'card-text': {'fontSize': 30}, 'card-instance': {'width': 300}}}})
        document = self.apply({'type': 'component.detach', 'page_id': self.page, 'node_id': 'card-instance'})
        detached = document['pages'][0]['nodes'][1]
        self.assertEqual(detached['props']['text'], 'Local')
        self.assertNotIn('bindingKey', detached['props'])
        self.assertEqual(document['variants']['ja']['layout']['card-instance'], {'fontSize': 30, 'width': 300})
        self.current = self.service.history('Projects/Test', 'undo', self.current['revision'], 'undo-detach')
        self.assertEqual(self.current['document']['pages'][0]['nodes'][1]['type'], 'instance')

    def test_synthetic_five_page_three_locale_fixture(self):
        from studio_publishing_fixture import fixture_document, ART_SVG
        document = fixture_document()
        self.service.validate(document)
        self.assertEqual(len(document['pages']), 5)
        self.assertEqual(len(document['variants']), 3)
        self.assertNotIn('<text', ART_SVG)
        for variant_id in document['variants']:
            self.assertEqual(binding_status(document, variant_id), {'missing': [], 'stale': []})
            self.assertEqual(len(resolve_document(document, variant_id)['assets']), 1)

    def test_clear_override_and_noop_source_does_not_stale(self):
        self.apply({'type': 'variant.value.set', 'id': 'ja', 'key': 'hero.title', 'value': ''})
        document = self.apply({'type': 'binding.set', 'key': 'hero.title', 'value': 'Hello'})
        self.assertEqual(binding_status(document, 'ja'), {'missing': [], 'stale': []})
        self.assertEqual(resolve_page(document, self.page, 'ja')['nodes'][0]['props']['text'], '')
        document = self.apply({'type': 'variant.value.set', 'id': 'ja', 'key': 'hero.title', 'value': None})
        self.assertEqual(binding_status(document, 'ja')['missing'], ['hero.title'])


if __name__ == '__main__':
    unittest.main()
