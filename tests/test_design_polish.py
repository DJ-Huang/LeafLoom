"""Linked style, component inheritance, honest import and template polish contracts."""
import copy
import unittest

from tests import test_design_documents, test_design_workspace
from vault_rag.design_documents import component_overrides, resolve_style, style_ids
from vault_rag.design_templates import load_template


class DesignStylePolishTests(unittest.TestCase):
    setUp = test_design_documents.DesignDocumentTests.setUp
    tearDown = test_design_documents.DesignDocumentTests.tearDown
    apply = test_design_documents.DesignDocumentTests.apply
    history = test_design_documents.DesignDocumentTests.history
    node = test_design_documents.DesignDocumentTests.node

    def install_styles(self):
        self.apply(
            {'type': 'node.create', 'page_id': self.page, 'node': self.node('title', style={'color': '#000000', 'fontSize': 10, 'padding': 2})},
            {'type': 'style.create', 'style': {'id': 'brand', 'name': 'Brand', 'kind': 'color', 'style': {'color': '#334455'}}},
            {'type': 'style.create', 'style': {'id': 'heading', 'name': 'Heading', 'kind': 'typography', 'style': {'fontFamily': 'Georgia', 'fontSize': 32, 'lineHeight': 1.25}}},
            {'type': 'style.create', 'style': {'id': 'comfortable', 'name': 'Comfortable', 'kind': 'spacing', 'style': {'padding': 16, 'gap': 8, 'borderRadius': 12}}})

    def title(self):
        return self.current['document']['pages'][0]['nodes'][0]

    def resolved(self):
        return resolve_style(self.current['document'], self.title())

    def test_independent_styles_update_without_copied_values_and_survive_history(self):
        self.install_styles()
        for key in ('brand', 'heading', 'comfortable'):
            self.apply({'type': 'style.apply', 'page_id': self.page, 'node_ids': ['title'], 'style_id': key})
        self.assertEqual(style_ids(self.title()), ['brand', 'heading', 'comfortable'])
        self.assertEqual(self.title()['style'], {})
        self.assertEqual((self.resolved()['color'], self.resolved()['fontSize'], self.resolved()['padding']), ('#334455', 32, 16))
        self.apply({'type': 'style.update', 'style_id': 'brand', 'patch': {'style': {'color': '#778899'}}})
        self.assertEqual(self.resolved()['color'], '#778899')
        self.assertNotIn('color', self.title()['style'])
        self.history('undo')
        self.assertEqual(self.resolved()['color'], '#334455')
        self.history('redo')
        self.assertEqual(self.resolved()['color'], '#778899')
        self.assertEqual(self.service.read(self.directory)['document'], self.current['document'])

    def test_same_category_replaces_link_legacy_works_and_detach_keeps_appearance(self):
        self.install_styles()
        self.apply({'type': 'node.update', 'page_id': self.page, 'node_id': 'title', 'patch': {'props': {'styleId': 'brand'}}})
        self.apply({'type': 'style.apply', 'page_id': self.page, 'node_ids': ['title'], 'style_id': 'heading'})
        self.apply({'type': 'style.create', 'style': {'id': 'contrast', 'kind': 'color', 'style': {'color': '#abcdef'}}},
                   {'type': 'style.apply', 'page_id': self.page, 'node_ids': ['title'], 'style_id': 'contrast'})
        self.assertEqual(style_ids(self.title()), ['heading', 'contrast'])
        self.assertNotIn('styleId', self.title()['props'])
        before = self.resolved()
        self.apply({'type': 'style.detach', 'page_id': self.page, 'node_ids': ['title'], 'style_id': 'contrast'})
        self.assertEqual(self.resolved(), before)
        self.assertEqual(style_ids(self.title()), ['heading'])
        self.apply({'type': 'style.update', 'style_id': 'heading', 'patch': {'style': {'fontSize': 48}}})
        self.assertEqual(self.resolved()['fontSize'], 48)
        self.assertEqual(self.resolved()['color'], '#abcdef')

    def test_local_style_override_survives_shared_update_and_apply_restores_link(self):
        self.install_styles()
        self.apply({'type': 'style.apply', 'page_id': self.page, 'node_ids': ['title'], 'style_id': 'brand'},
                   {'type': 'node.update', 'page_id': self.page, 'node_id': 'title', 'patch': {'style': {'color': 'red'}}},
                   {'type': 'style.update', 'style_id': 'brand', 'patch': {'style': {'color': 'blue'}}})
        self.assertEqual(self.resolved()['color'], 'red')
        self.apply({'type': 'style.apply', 'page_id': self.page, 'node_ids': ['title'], 'style_id': 'brand'})
        self.assertEqual(self.resolved()['color'], 'blue')
        with self.assertRaisesRegex(ValueError, 'shared styles'):
            self.apply({'type': 'style.delete', 'style_id': 'brand'})

    def test_invalid_style_references_and_kind_reject_without_partial_edits(self):
        self.install_styles()
        for bad in ('missing', ['missing'], ['brand', 'brand'], [3]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.apply({'type': 'node.update', 'page_id': self.page, 'node_id': 'title', 'patch': {'props': {'styleIds': bad}}})
        with self.assertRaises(ValueError):
            self.apply({'type': 'style.create', 'style': {'id': 'bad', 'kind': 'nonsense', 'style': {}}})
        self.assertEqual(self.service.read(self.directory)['document'], self.current['document'])

    def test_replacing_theme_keeps_unmatched_custom_tokens_defined(self):
        self.install_styles()
        self.apply({'type': 'style.create', 'style': {'id': 'theme', 'kind': 'color', 'style': {'--paper': '#fafafa', '--ink': '#222222'}}},
                   {'type': 'style.apply', 'page_id': self.page, 'node_ids': ['title'], 'style_id': 'theme'},
                   {'type': 'style.apply', 'page_id': self.page, 'node_ids': ['title'], 'style_id': 'brand'})
        self.assertEqual(style_ids(self.title()), ['brand'])
        self.assertEqual(self.resolved()['--paper'], '#fafafa')
        self.assertEqual(self.resolved()['color'], '#334455')

    def component(self):
        self.apply({'type': 'node.create', 'page_id': self.page, 'node': self.node('card', type='container',
                   style={'x': 10, 'y': 20, 'width': 300, 'height': 100, 'widthMode': 'hug', 'heightMode': 'hug', 'layout': 'row', 'padding': 20},
                   children=[self.node('label', props={'text': 'Main label'}, style={'color': '#111111', 'fontSize': 24})])},
                   {'type': 'component.from_node', 'page_id': self.page, 'node_id': 'card', 'component_id': 'card-master'})
        component = self.current['document']['components']['card-master']
        return component['node']['id'], component['node']['children'][0]['id']

    def test_component_master_propagates_except_overrides_and_property_reset_inherits(self):
        root, label = self.component()
        instance = self.title()
        self.assertEqual((instance['style']['widthMode'], instance['style']['heightMode']), ('hug', 'hug'))
        self.apply({'type': 'component.override', 'page_id': self.page, 'node_id': 'card', 'target_id': label,
                    'patch': {'props': {'text': 'Instance label'}, 'style': {'color': '#cc0000'}}})
        self.apply({'type': 'component.edit', 'component_id': 'card-master', 'commands': [
            {'type': 'node.update', 'node_id': label, 'patch': {'props': {'text': 'New main label'}, 'style': {'color': '#0000cc', 'fontSize': 30}}}]})
        master = self.current['document']['components']['card-master']
        self.assertEqual(master['node']['children'][0]['props']['text'], 'New main label')
        overrides = component_overrides(master, self.title())
        self.assertEqual(overrides[label]['props']['text'], 'Instance label')
        self.apply({'type': 'component.reset_override', 'page_id': self.page, 'node_id': 'card', 'target_id': label, 'section': 'style', 'property': 'color'})
        self.assertNotIn('style', self.title()['props']['overrides'][label])
        self.apply({'type': 'component.detach', 'page_id': self.page, 'node_id': 'card'})
        detached = self.title()['children'][0]
        self.assertEqual((detached['props']['text'], detached['style']['color'], detached['style']['fontSize']), ('Instance label', '#0000cc', 30))
        self.history('undo')
        self.apply({'type': 'component.reset_override', 'page_id': self.page, 'node_id': 'card'})
        self.assertNotIn('overrides', self.title()['props'])

    def test_null_override_resets_and_unknown_targets_are_atomic(self):
        _, label = self.component()
        self.apply({'type': 'component.override', 'page_id': self.page, 'node_id': 'card', 'target_id': label, 'patch': {'props': {'text': 'Local'}}},
                   {'type': 'component.override', 'page_id': self.page, 'node_id': 'card', 'target_id': label, 'patch': {'props': {'text': None}}})
        self.assertNotIn('overrides', self.title()['props'])
        for patch in ({'id': 'other'}, {'props': {'styleIds': ['missing']}}, {'props': {'componentId': 'missing'}}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.apply({'type': 'component.override', 'page_id': self.page, 'node_id': 'card', 'target_id': label, 'patch': patch})
        with self.assertRaisesRegex(ValueError, 'target'):
            self.apply({'type': 'component.override', 'page_id': self.page, 'node_id': 'card', 'target_id': 'missing', 'patch': {'props': {'text': 'Bad'}}})
        self.assertEqual(self.service.read(self.directory)['document'], self.current['document'])

    def test_shared_styles_can_be_applied_inside_main_component(self):
        root, label = self.component()
        self.apply({'type': 'style.create', 'style': {'id': 'brand', 'kind': 'color', 'style': {'color': 'purple'}}},
                   {'type': 'component.edit', 'component_id': 'card-master', 'commands': [
                       {'type': 'style.apply', 'node_ids': [label], 'style_id': 'brand'}]})
        node = self.current['document']['components']['card-master']['node']['children'][0]
        self.assertEqual(resolve_style(self.current['document'], node)['color'], 'purple')
        self.assertEqual(node['props']['styleIds'], ['brand'])

    def test_legacy_flat_overrides_normalize_before_edit_or_detach(self):
        root, _ = self.component()
        self.apply({'type': 'node.update', 'page_id': self.page, 'node_id': 'card', 'patch': {'props': {'overrides': {'text': 'Legacy root'}}}},
                   {'type': 'component.override', 'page_id': self.page, 'node_id': 'card', 'target_id': root, 'patch': {'style': {'background': 'red'}}})
        self.assertEqual(self.title()['props']['overrides'][root], {'props': {'text': 'Legacy root'}, 'style': {'background': 'red'}})

    def test_page_projection_loads_component_override_dependencies(self):
        self.apply({'type': 'page.create', 'page': {'id': 'first', 'name': 'First', 'width': 200, 'height': 200, 'nodes': []}},
                   {'type': 'page.create', 'page': {'id': 'second', 'name': 'Second', 'width': 200, 'height': 200, 'nodes': []}},
                   {'type': 'component.create', 'component': {'id': 'embed', 'node': self.node('embed-master', type='page', props={'pageId': 'first'})}},
                   {'type': 'node.create', 'page_id': self.page, 'node': self.node('embed-instance', type='instance', props={'componentId': 'embed'})},
                   {'type': 'component.override', 'page_id': self.page, 'node_id': 'embed-instance', 'target_id': 'embed-master', 'patch': {'props': {'pageId': 'second'}}})
        view = self.service.page_view(self.directory, self.page)
        self.assertTrue(next(page for page in view['document']['pages'] if page['id'] == 'second')['loaded'])

    def test_nested_legacy_overrides_validate_effective_component_assets(self):
        self.apply({'type': 'asset.register', 'asset': {'id': 'valid-image', 'path': 'Design/Assets/image.png'}},
                   {'type': 'component.create', 'component': {'id': 'B', 'node': self.node('b-root', type='image', props={})}},
                   {'type': 'component.create', 'component': {'id': 'A', 'node': self.node('a-root', type='instance', props={'componentId': 'B'})}},
                   {'type': 'node.create', 'page_id': self.page, 'node': self.node('instance-A', type='instance', props={'componentId': 'A'})})
        for nested in ({'assetId': 'missing'}, {'b-root': {'props': {'assetId': 'missing'}}}, {'styleIds': ['missing-style']}):
            with self.subTest(nested=nested), self.assertRaisesRegex(ValueError, 'missing|shared styles'):
                self.apply({'type': 'component.override', 'page_id': self.page, 'node_id': 'instance-A', 'target_id': 'a-root',
                            'patch': {'props': {'overrides': nested}}})
        self.apply({'type': 'component.override', 'page_id': self.page, 'node_id': 'instance-A', 'target_id': 'a-root',
                    'patch': {'props': {'overrides': {'assetId': 'valid-image'}}}})
        self.assertEqual(self.title()['props']['overrides']['a-root']['props']['overrides']['assetId'], 'valid-image')
        self.assertEqual(self.service.read(self.directory)['document'], self.current['document'])

    def test_forma_branding_and_styles_are_real_editable_and_reversible(self):
        document = load_template('forma')
        document['id'] = self.current['document']['id']
        self.apply({'type': 'document.replace', 'document': document})
        def walk(nodes):
            for node in nodes:
                yield node
                yield from walk(node.get('children', []))
        self.assertEqual(sum(1 for page in document['pages'] for _ in walk(page['nodes'])), 328)
        for page in document['pages']:
            root = page['nodes'][0]
            self.assertIn('brand and layout', root['name'])
            self.assertEqual(resolve_style(document, root)['--forma-paper'], '#eeeae2')
            self.assertIn('background:var(--forma-paper)', page['css'])
            self.assertIn('var(--forma-font-serif)', page['css'])
            self.assertIn('var(--forma-gutter-desktop)', page['css'])
        self.apply({'type': 'project.rebrand', 'brand': 'New Studio', 'contact': 'hello@example.test'},
                   {'type': 'style.update', 'style_id': 'forma-brand-palette', 'patch': {'style': {'--forma-paper': '#fafafa'}}})
        for page in self.current['document']['pages']:
            self.assertEqual(resolve_style(self.current['document'], page['nodes'][0])['--forma-paper'], '#fafafa')
            bindings = [n for n in walk(page['nodes']) if n['props'].get('templateText')]
            self.assertEqual(len(bindings), 3)
            self.assertTrue(all('FORMA' not in n['props']['text'] for n in bindings))
            self.assertIn('hello@example.test', [n['props']['text'] for n in bindings])
        self.assertEqual(self.current['document']['metadata']['branding']['brand'], 'New Studio')
        self.history('undo')
        self.assertEqual(self.current['document']['metadata']['branding']['brand'], 'forma')


class DesignImportPolishTests(unittest.TestCase):
    setUp = test_design_workspace.DesignWorkspaceTests.setUp
    tearDown = test_design_workspace.DesignWorkspaceTests.tearDown
    summary = test_design_workspace.DesignWorkspaceTests.summary
    create = test_design_workspace.DesignWorkspaceTests.create

    def test_capture_report_distinguishes_preserved_converted_and_unsupported(self):
        document = copy.deepcopy(self.project['document'])
        page = document['pages'][0]
        document['migration'] = {'status': 'capture_required', 'boards': [{'id': page['id']}]}
        current = self.docs.apply(self.directory, [{'type': 'document.replace', 'document': document}], self.project['revision'], 'prepare-report')
        page['migration'] = {'warnings': ['Canvas drawing needs review'], 'report': {
            'retained': [{'kind': 'authored_nodes', 'count': 5, 'description': 'Editable DOM'}],
            'converted': [{'kind': 'navigation', 'count': 2, 'description': 'Managed links'}],
            'unsupported': [{'kind': 'canvas_bitmap', 'count': 1, 'description': 'Canvas drawing not captured'}]}}
        result = self.workspace.finish_migration(self.directory, [page], current['revision'], 'finish-report')
        report = result['document']['migration']['report']
        self.assertEqual(report['fidelity'], 'review_required')
        self.assertEqual(report['retained'][0]['kind'], 'source_copy')
        self.assertEqual(report['converted'][0]['page_id'], page['id'])
        self.assertEqual(report['unsupported'][0]['kind'], 'canvas_bitmap')
        self.assertEqual(report['warnings'], ['Canvas drawing needs review'])
        self.assertEqual(result['document']['pages'][0]['migration']['report'], page['migration']['report'])

    def test_old_capture_clients_get_script_limitations_in_report(self):
        document = copy.deepcopy(self.project['document'])
        page = document['pages'][0]
        document['migration'] = {'status': 'capture_required', 'boards': [{'id': page['id']}]}
        current = self.docs.apply(self.directory, [{'type': 'document.replace', 'document': document}], self.project['revision'], 'prepare-old-report')
        page['migration'] = {'interactions': {'navigation': 1, 'scriptSources': ['app.js'], 'inlineHandlers': 2}, 'unavailableStylesheets': ['remote.css']}
        result = self.workspace.finish_migration(self.directory, [page], current['revision'], 'finish-old-report')
        self.assertEqual({item['kind'] for item in result['document']['migration']['report']['unsupported']}, {'script_runtime', 'inline_handlers', 'unreadable_stylesheets'})

    def test_library_tracks_and_remaps_every_linked_style(self):
        current = self.docs.apply(self.directory, [
            {'type': 'style.create', 'style': {'id': 'color', 'kind': 'color', 'style': {'color': 'red'}}},
            {'type': 'style.create', 'style': {'id': 'type', 'kind': 'typography', 'style': {'fontSize': 24}}},
            {'type': 'component.create', 'component': {'id': 'label', 'name': 'Label', 'node': {'id': 'label-root', 'type': 'text', 'name': 'Label', 'style': {}, 'props': {'text': 'Label', 'styleIds': ['color', 'type']}, 'children': []}}}],
            self.project['revision'], 'prepare-style-library')
        state = self.workspace.publish(self.directory, 'component', 'label', self.workspace.state()['revision'], 'publish-style-library')
        key = state['items'][0]['id']
        target = self.create('Projects/Imported')
        imported = self.workspace.import_library('Projects/Imported', key, target['revision'], 'import-style-library')
        component = next(iter(imported['document']['components'].values()))
        linked = component['node']['props']['styleIds']
        self.assertEqual(len(linked), 2)
        self.assertNotIn('color', linked)
        self.assertTrue(all(key in imported['document']['styles'] for key in linked))
        self.assertEqual(resolve_style(imported['document'], component['node']), {'color': 'red', 'fontSize': 24})


if __name__ == '__main__':
    unittest.main()
