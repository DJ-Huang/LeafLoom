"""Focused safety and persistence checks for structured Design Studio documents."""
import base64
import copy
import json
import hashlib
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from vault_rag.design_documents import DesignDocuments, DOCUMENT_PATH, _diff, _patch
from vault_rag.local_state import ConflictError, Files, LocalConfig


class DesignDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.root = self.home / 'vault'
        self.root.mkdir()
        self.config = LocalConfig(self.home / 'config')
        self.config.save({'root': str(self.root), 'include_roots': ['Projects']})
        self.files = Files(self.config)
        self.studio = SimpleNamespace(config=self.config, runtime=SimpleNamespace(), files=self.files)
        self.service = DesignDocuments(self.studio)
        self.directory = 'Projects/Pets'
        (self.root / self.directory).mkdir(parents=True)
        self.current = self.service.create(self.directory, 'Pet Home')
        self.page = self.current['document']['pages'][0]['id']

    def tearDown(self):
        self.temp.cleanup()

    @property
    def path(self):
        return self.root / self.directory / DOCUMENT_PATH

    def apply(self, *commands, operation_id=None, label='Edit'):
        self.current = self.service.apply(self.directory, list(commands), self.current['revision'],
                                          operation_id or str(id(commands)) + '-' + self.current['revision'], label)
        return self.current

    def history(self, action):
        self.current = self.service.history(self.directory, action, self.current['revision'],
                                            action + '-' + self.current['revision'])
        return self.current

    def node(self, node_id='cat', **extra):
        return {'id': node_id, 'type': 'text', 'name': 'Cat', 'style': {'x': 10, 'y': 20, 'width': 100, 'height': 40},
                'props': {'text': 'Cat'}, 'children': [], **extra}

    def test_create_manifest_and_explicit_revision(self):
        self.assertEqual(self.current['document']['name'], 'Pet Home')
        self.assertFalse(self.current['history']['can_undo'])
        self.assertNotIn('nodes', self.service.manifest(self.directory)['manifest']['pages'][0])
        with self.assertRaises(ConflictError):
            self.service.apply(self.directory, [{'type': 'project.update', 'patch': {'name': 'Oops'}}], None, 'missing')
        with self.assertRaises(ConflictError):
            self.service.apply(self.directory, [{'type': 'project.update', 'patch': {'name': 'Oops'}}], self.current['revision'], 'wrong-workspace', workspace_revision='stale')
        with self.assertRaises(ConflictError):
            self.service.create(self.directory, 'Duplicate')

    def test_quiet_reads_reuse_parsed_document_without_exposing_mutable_cache(self):
        self.service.read(self.directory)
        with patch.object(self.service, 'validate', side_effect=AssertionError('Quiet read reparsed document')):
            current = self.service.read(self.directory)
            current['document']['name'] = 'Caller mutation'
            self.assertEqual(self.service.read(self.directory)['document']['name'], 'Pet Home')
        document = self.current['document']
        document['name'] = 'Changed on disk'
        self.path.write_text(json.dumps(document))
        with self.assertRaises(ConflictError):
            self.service.read(self.directory)

    def test_synced_vault_keeps_history_across_machine_roots(self):
        self.apply({'type': 'project.update', 'patch': {'name': 'Synced design'}})
        original = self.path.read_bytes()
        foreign_owner = 'D:\\Knowledge\n' + self.directory
        with self.service._database(self.current['document']['id']) as db:
            db.execute('UPDATE meta SET owner=? WHERE id=1', (foreign_owner,))
        destination = self.home / 'synced-vault'
        shutil.copytree(self.root, destination)
        self.config.save({'root': str(destination)})
        self.service = DesignDocuments(self.studio)
        synced = self.service.read(self.directory)
        self.assertEqual(synced['document'], self.current['document'])
        self.assertEqual(synced['revision'], self.current['revision'])
        self.assertTrue(synced['history']['can_undo'])
        self.assertEqual((destination / self.directory / DOCUMENT_PATH).read_bytes(), original)
        with self.service._database(synced['document']['id']) as db:
            self.assertEqual(db.execute('SELECT owner FROM meta WHERE id=1').fetchone()[0], foreign_owner)
        self.history('undo')
        self.assertEqual(self.current['document']['name'], 'Pet Home')
        self.history('redo')
        self.assertEqual(self.current['document']['name'], 'Synced design')
        self.assertEqual(self.path.read_bytes(), original)

    def test_synced_identity_still_rejects_a_different_relative_directory(self):
        with self.service._database(self.current['document']['id']) as db:
            db.execute('UPDATE meta SET owner=? WHERE id=1', ('D:\\Knowledge\n' + self.directory,))
        shutil.copytree(self.root / self.directory, self.root / 'Projects/Copy')
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ConflictError, 'another directory'):
            self.service.read('Projects/Copy')
        with self.assertRaisesRegex(ConflictError, 'different directory'):
            self.service.relocate('Projects/Unrelated', 'Projects/Copy')
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual((self.root / 'Projects/Copy' / DOCUMENT_PATH).read_bytes(), original)
        self.assertEqual(self.service.read(self.directory)['revision'], self.current['revision'])

    def test_synced_root_does_not_bypass_external_content_conflicts(self):
        with self.service._database(self.current['document']['id']) as db:
            db.execute('UPDATE meta SET owner=? WHERE id=1', ('/another/computer/vault\n' + self.directory,))
        document = copy.deepcopy(self.current['document'])
        document['name'] = 'External edit'
        self.path.write_text(json.dumps(document))
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ConflictError, 'changed outside the studio'):
            self.service.read(self.directory)
        self.assertEqual(self.path.read_bytes(), original)
        with self.service._database(document['id']) as db:
            self.assertEqual(db.execute('SELECT revision FROM meta WHERE id=1').fetchone()[0], self.current['revision'])

    def test_synced_history_recovers_a_pending_save_without_changing_owner(self):
        with patch('vault_rag.design_documents.atomic_write', side_effect=OSError('interruption')):
            with self.assertRaises(OSError):
                self.apply({'type': 'project.update', 'patch': {'name': 'Pending synced edit'}})
        foreign_owner = 'D:\\Knowledge\n' + self.directory
        with self.service._database(self.current['document']['id']) as db:
            db.execute('UPDATE meta SET owner=? WHERE id=1', (foreign_owner,))
        self.current = DesignDocuments(self.studio).read(self.directory)
        self.assertEqual(self.current['document']['name'], 'Pending synced edit')
        with self.service._database(self.current['document']['id']) as db:
            self.assertEqual(db.execute('SELECT owner FROM meta WHERE id=1').fetchone()[0], foreign_owner)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM pending').fetchone()[0], 0)
        self.history('undo')
        self.assertEqual(self.current['document']['name'], 'Pet Home')

    def test_page_projection_loads_embedded_closure_and_keeps_inactive_asset_usage(self):
        document = copy.deepcopy(self.current['document'])
        document['assets']['cat-image'] = {'id': 'cat-image', 'name': 'Cat', 'path': 'Design/Assets/cat.png'}
        document['pages'][0]['nodes'] = [self.node('embed', type='page', props={'pageId': 'details'})]
        document['pages'] += [
            {'id': 'details', 'name': 'Details', 'width': 400, 'height': 400, 'nodes': [self.node('card-instance', type='instance', props={'componentId': 'card'})]},
            {'id': 'nested', 'name': 'Nested', 'width': 400, 'height': 400, 'nodes': [self.node('nested-label')]},
            {'id': 'inactive', 'name': 'Inactive', 'width': 400, 'height': 400, 'css': '.large { color: red; }', 'nodes': [self.node('inactive-cat', type='image', props={'assetId': 'cat-image'})]},
        ]
        document['components']['card'] = {'id': 'card', 'name': 'Card', 'version': 1, 'node': self.node('master-embed', type='page', props={'pageId': 'nested'})}
        self.apply({'type': 'document.replace', 'document': document})
        view = self.service.page_view(self.directory, self.page)
        pages = {page['id']: page for page in view['document']['pages']}
        self.assertEqual(view['view_page_id'], self.page)
        self.assertTrue(all(pages[key]['loaded'] for key in (self.page, 'details', 'nested')))
        self.assertFalse(pages['inactive']['loaded'])
        self.assertEqual(pages['inactive']['nodes'], [])
        self.assertEqual(pages['inactive']['node_count'], 1)
        self.assertNotIn('css', pages['inactive'])
        self.assertEqual(view['document']['assets']['cat-image']['references'], [{'page_id': 'inactive', 'page_name': 'Inactive', 'node_id': 'inactive-cat', 'node_name': 'Cat'}])
        self.assertIn('card', view['document']['components'])
        # The client-only projection must never contaminate canonical persistence.
        canonical = self.service.read(self.directory)
        self.assertNotIn('loaded', canonical['document']['pages'][0])
        self.assertEqual(len(canonical['document']['pages'][3]['nodes']), 1)
        self.assertNotIn('references', canonical['document']['assets']['cat-image'])

    def test_page_projection_defaults_and_uses_cached_usage_index(self):
        self.apply({'type': 'page.create', 'page': {'id': 'other', 'name': 'Other'}},
                   {'type': 'node.create', 'page_id': 'other', 'node': self.node()})
        first = self.service.project_view(self.current, 'unknown-page')
        self.assertEqual(first['view_page_id'], self.page)
        with patch('vault_rag.design_documents._walk', side_effect=AssertionError('Quiet projection rebuilt usage index')):
            second = self.service.page_view(self.directory, 'other')
        self.assertEqual(second['view_page_id'], 'other')
        self.assertEqual(second['document']['pages'][1]['nodes'][0]['id'], 'cat')
        self.assertFalse(second['document']['pages'][0]['loaded'])

    def contextual_document(self):
        document = copy.deepcopy(self.current['document'])
        document['pages'][0]['migration'] = {'contextVariants': [{'context': {'settingsFrom': 'game'}, 'pageId': 'settings-game'}]}
        document['pages'].append({'id': 'settings-game', 'name': 'Settings from game', 'width': 720, 'height': 1560,
                                  'migration': {'contextSource': {'pageId': self.page, 'context': {'settingsFrom': 'game'}}},
                                  'nodes': [self.node('variant-label')]})
        return document

    def test_context_variant_pages_are_loaded_and_duplicate_as_independent_snapshots(self):
        self.apply({'type': 'document.replace', 'document': self.contextual_document()})
        view = self.service.page_view(self.directory, self.page)
        self.assertTrue(all(page['loaded'] for page in view['document']['pages']))
        self.apply({'type': 'page.duplicate', 'page_id': self.page, 'new_id': 'source-copy'},
                   {'type': 'page.duplicate', 'page_id': 'settings-game', 'new_id': 'variant-copy'})
        pages = {page['id']: page for page in self.current['document']['pages']}
        self.assertNotIn('contextVariants', pages['source-copy']['migration'])
        self.assertNotIn('contextSource', pages['variant-copy']['migration'])
        self.assertEqual(pages[self.page]['migration']['contextVariants'][0]['pageId'], 'settings-game')
        self.assertNotEqual(pages['settings-game']['nodes'][0]['id'], pages['variant-copy']['nodes'][0]['id'])
        self.history('undo')
        self.assertEqual(len(self.current['document']['pages']), 2)

    def test_context_variant_ownership_scalar_bounds_and_recursive_embeds_are_validated(self):
        document = self.contextual_document()
        invalid = []
        orphan = copy.deepcopy(document)
        orphan['pages'][0]['migration'] = {}
        invalid.append(orphan)
        mismatched = copy.deepcopy(document)
        mismatched['pages'][1]['migration']['contextSource']['context']['settingsFrom'] = 'pause'
        invalid.append(mismatched)
        non_scalar = copy.deepcopy(document)
        for page in non_scalar['pages']:
            entry = page['migration'].get('contextSource') or page['migration']['contextVariants'][0]
            entry['context']['settingsFrom'] = {'nested': 'game'}
        invalid.append(non_scalar)
        too_long = copy.deepcopy(document)
        too_long['pages'][0]['migration']['contextVariants'][0]['context']['settingsFrom'] = 'x' * 201
        invalid.append(too_long)
        chained = copy.deepcopy(document)
        chained['pages'][1]['migration']['contextVariants'] = []
        invalid.append(chained)
        duplicate_context = copy.deepcopy(document)
        duplicate_context['pages'][0]['migration']['contextVariants'] *= 2
        invalid.append(duplicate_context)
        self_mapped = copy.deepcopy(document)
        self_mapped['pages'][0]['migration']['contextVariants'][0]['pageId'] = self.page
        invalid.append(self_mapped)
        recursive = copy.deepcopy(document)
        recursive['pages'][1]['nodes'] = [self.node('loop', type='page', props={'pageId': self.page})]
        invalid.append(recursive)
        before = self.path.read_bytes()
        for index, value in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.service.validate(value)
        self.assertEqual(self.path.read_bytes(), before)

    def test_context_variant_delete_explains_dependency_and_can_unlink_in_one_transaction(self):
        self.apply({'type': 'document.replace', 'document': self.contextual_document()})
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'contextVariants entry before deleting'):
            self.apply({'type': 'page.delete', 'page_id': 'settings-game'})
        self.assertEqual(self.path.read_bytes(), before)
        self.apply({'type': 'page.delete', 'page_id': 'settings-game'},
                   {'type': 'page.update', 'page_id': self.page, 'patch': {'migration': {}}})
        self.assertEqual(len(self.current['document']['pages']), 1)

    def test_document_replacement_rejects_page_projection_without_writing(self):
        self.apply({'type': 'page.create', 'page': {'id': 'other', 'name': 'Other'}},
                   {'type': 'node.create', 'page_id': 'other', 'node': self.node()})
        before = self.path.read_bytes()
        projected = self.service.page_view(self.directory, self.page)['document']
        with self.assertRaisesRegex(ValueError, 'complete document'):
            self.apply({'type': 'document.replace', 'document': projected})
        self.assertEqual(self.path.read_bytes(), before)
        current = self.service.read(self.directory)
        self.assertEqual(current['revision'], self.current['revision'])
        self.assertEqual(current['document']['pages'][1]['nodes'][0]['id'], 'cat')

    def test_shared_style_script_operations_reference_guards_and_history(self):
        self.apply({'type': 'script.create', 'script': {'id': 'pulse', 'name': 'Pulse', 'source': 'export function mount(ctx) {}'}},
                   {'type': 'style.create', 'style': {'id': 'card', 'name': 'Card', 'style': {'background': '#fff'}}},
                   {'type': 'node.create', 'page_id': self.page, 'node': self.node(props={'text': 'Cat', 'scriptId': 'pulse', 'styleId': 'card'})})
        with self.assertRaises(ValueError):
            self.apply({'type': 'script.delete', 'script_id': 'pulse'})
        with self.assertRaises(ValueError):
            self.apply({'type': 'style.delete', 'style_id': 'card'})
        self.apply({'type': 'script.update', 'script_id': 'pulse', 'patch': {'source': 'export function mount(ctx) { return () => {}; }'}},
                   {'type': 'style.update', 'style_id': 'card', 'patch': {'style': {'color': '#123'}}})
        self.assertEqual(self.current['document']['styles']['card']['style']['background'], '#fff')
        self.history('undo')
        self.assertNotIn('color', self.current['document']['styles']['card']['style'])
        manifest = self.service.manifest(self.directory)['manifest']
        self.assertNotIn('source', manifest['scripts']['pulse'])

    def test_nested_deltas_round_trip(self):
        before = {'pages': [{'id': 'a', 'nodes': [self.node()]}], 'assets': {'old': {'path': 'old'}}}
        after = copy.deepcopy(before)
        after['pages'][0]['nodes'][0]['style']['x'] = 400
        after['pages'][0]['nodes'].append(self.node('dog'))
        after['assets'] = {'new': {'path': 'new'}}
        forward, inverse = _diff(before, after)
        self.assertEqual(_patch(before, forward), after)
        self.assertEqual(_patch(after, inverse), before)
        smaller = copy.deepcopy(after)
        smaller['pages'][0]['nodes'].pop(0)
        fwd, inv = _diff(after, smaller)
        self.assertEqual(_patch(after, fwd), smaller)
        self.assertEqual(_patch(smaller, inv), after)

    def test_cross_page_script_history_survives_restart_and_over_fifty_edits(self):
        self.apply({'type': 'node.create', 'page_id': self.page, 'node': self.node()},
                   {'type': 'page.create', 'page': {'id': 'gallery', 'name': 'Gallery'}}, label='Build home and gallery')
        self.apply({'type': 'node.create', 'page_id': 'gallery', 'node': self.node('dog', script={'source': 'export function mount(ctx) { return () => {}; }'})}, label='Add scripted dog')
        for index in range(55):
            self.apply({'type': 'node.update', 'page_id': self.page, 'node_id': 'cat', 'patch': {'style': {'x': index}, 'hidden': index % 2 == 0}}, label=f'Move {index}')
        self.service = DesignDocuments(self.studio)
        history = self.service.history(self.directory)
        self.assertEqual(history['total'], 57)
        self.assertEqual(len(history['entries']), 50)
        self.assertEqual(len(self.service.history(self.directory, offset=50)['entries']), 7)
        for _ in range(56):
            self.history('undo')
        self.assertEqual(self.current['document']['pages'][1]['nodes'], [])
        self.history('redo')
        self.assertIn('script', self.current['document']['pages'][1]['nodes'][0])

    def test_batch_is_atomic_duplicate_identity_and_nonfinite_json_rejected(self):
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.apply({'type': 'node.create', 'page_id': self.page, 'node': self.node()},
                       {'type': 'node.create', 'page_id': self.page, 'node': self.node()})
        self.assertEqual(self.path.read_bytes(), original)
        with self.assertRaises(ValueError):
            self.apply({'type': 'page.update', 'page_id': self.page, 'patch': {'width': float('nan')}})
        with self.assertRaises(ValueError):
            self.apply({'type': 'node.create', 'node': self.node()})
        self.assertEqual(self.path.read_bytes(), original)

    def test_replay_cas_and_branching(self):
        original_revision = self.current['revision']
        command = {'type': 'node.create', 'page_id': self.page, 'node': self.node()}
        self.apply(command, operation_id='add-cat')
        replay = self.service.apply(self.directory, [command], original_revision, 'add-cat', 'Edit')
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['revision'], self.current['revision'])
        with self.assertRaises(ConflictError):
            self.service.apply(self.directory, [{'type': 'project.update', 'patch': {'name': 'Different'}}], self.current['revision'], 'add-cat')
        with self.assertRaises(ConflictError):
            self.service.apply(self.directory, [command], original_revision, 'stale')
        self.history('undo')
        replay = self.service.apply(self.directory, [command], original_revision, 'add-cat', 'Edit')
        self.assertEqual(replay['document']['pages'][0]['nodes'], [])
        self.apply({'type': 'project.update', 'patch': {'name': 'New branch'}})
        self.assertFalse(self.current['history']['can_redo'])
        self.assertEqual(self.service.history(self.directory)['total'], 1)

    def test_components_embed_cycles_and_detach(self):
        self.apply({'type': 'component.create', 'component': {'id': 'card', 'name': 'Card', 'node': self.node('master')}},
                   {'type': 'node.create', 'page_id': self.page, 'node': self.node('instance', type='instance', props={'componentId': 'card', 'overrides': {'text': 'Kitten'}})})
        with self.assertRaises(ValueError):
            self.apply({'type': 'component.delete', 'component_id': 'card'})
        self.apply({'type': 'component.detach', 'page_id': self.page, 'node_id': 'instance'},
                   {'type': 'component.delete', 'component_id': 'card'})
        detached = self.current['document']['pages'][0]['nodes'][0]
        self.assertEqual(detached['props']['text'], 'Kitten')
        self.assertEqual(detached['id'], 'instance')
        self.assertEqual(detached['type'], 'text')
        with self.assertRaises(ValueError):
            self.apply({'type': 'node.create', 'page_id': self.page, 'node': self.node('loop', type='page', props={'pageId': self.page})})
        with self.assertRaises(ValueError):
            self.apply({'type': 'component.create', 'component': {'id': 'loop', 'name': 'Loop', 'node': self.node('loop-master', type='instance', props={'componentId': 'loop'})}})

    def test_detach_materializes_keyed_descendant_overrides(self):
        root = self.node('master', type='container', children=[self.node('master-label')])
        self.apply({'type': 'component.create', 'component': {'id': 'card', 'name': 'Card', 'node': root}},
                   {'type': 'node.create', 'page_id': self.page, 'node': self.node('instance', type='instance', props={'componentId': 'card', 'overrides': {'master-label': {'props': {'text': 'Kitten'}, 'style': {'color': '#123'}}}})})
        self.apply({'type': 'component.detach', 'page_id': self.page, 'node_id': 'instance'})
        label = self.current['document']['pages'][0]['nodes'][0]['children'][0]
        self.assertEqual(label['props']['text'], 'Kitten')
        self.assertEqual(label['style']['color'], '#123')

    def test_duplicate_remaps_literal_script_find_calls_across_page_siblings(self):
        source = """export function mount(ctx) {
 const child=ctx.find('child'); const root=ctx.find("group"); const sibling=ctx.find(`sibling`);
 const label="ctx.find('child')"; // ctx.find('child')
 ctx.find(dynamicId); ctx.assets.resolve('child');
}"""
        group = self.node('group', type='container', props={'targetId': 'child'}, script={'source': source}, children=[self.node('child')])
        self.apply({'type': 'node.create', 'page_id': self.page, 'node': group},
                   {'type': 'node.create', 'page_id': self.page, 'node': self.node('sibling')})
        self.apply({'type': 'node.duplicate', 'page_id': self.page, 'node_id': 'group'})
        duplicate = self.current['document']['pages'][0]['nodes'][1]
        rewritten = duplicate['script']['source']
        self.assertIn("ctx.find('" + duplicate['children'][0]['id'] + "')", rewritten)
        self.assertIn('ctx.find("' + duplicate['id'] + '")', rewritten)
        self.assertIn('ctx.find(`sibling`)', rewritten)
        self.assertIn('const label="ctx.find(\'child\')"; // ctx.find(\'child\')', rewritten)
        self.assertIn("ctx.assets.resolve('child')", rewritten)
        self.assertEqual(duplicate['props']['targetId'], duplicate['children'][0]['id'])
        self.apply({'type': 'page.update', 'page_id': self.page, 'patch': {'script': {'source': "export function mount(ctx) { ctx.find('child'); ctx.find('sibling'); }"}}},
                   {'type': 'page.duplicate', 'page_id': self.page, 'new_id': 'copied-page'})
        copied = self.current['document']['pages'][1]
        child_id, sibling_id = copied['nodes'][0]['children'][0]['id'], copied['nodes'][2]['id']
        self.assertIn("ctx.find('" + child_id + "')", copied['script']['source'])
        self.assertIn("ctx.find('" + sibling_id + "')", copied['script']['source'])
        self.assertIn('ctx.find(`' + sibling_id + '`)', copied['nodes'][0]['script']['source'])

    def test_detach_remaps_master_and_instance_script_find_calls_to_materialized_nodes(self):
        source = "export function mount(ctx) { ctx.find('master-label'); ctx.find('master'); /* ctx.find('master-label') */ }"
        root = self.node('master', type='container', script={'source': source}, children=[self.node('master-label')])
        self.apply({'type': 'component.create', 'component': {'id': 'card', 'name': 'Card', 'node': root}},
                   {'type': 'node.create', 'page_id': self.page, 'node': self.node('inherited', type='instance', props={'componentId': 'card'})},
                   {'type': 'node.create', 'page_id': self.page, 'node': self.node('overridden', type='instance', props={'componentId': 'card'}, script={'source': source + '\n// instance override'})})
        self.apply({'type': 'component.detach', 'page_id': self.page, 'node_id': 'inherited'},
                   {'type': 'component.detach', 'page_id': self.page, 'node_id': 'overridden'})
        for detached in self.current['document']['pages'][0]['nodes']:
            rewritten = detached['script']['source']
            self.assertIn("ctx.find('" + detached['children'][0]['id'] + "')", rewritten)
            self.assertIn("ctx.find('" + detached['id'] + "')", rewritten)
            self.assertIn("/* ctx.find('master-label') */", rewritten)
        self.assertIn('// instance override', self.current['document']['pages'][0]['nodes'][1]['script']['source'])
        self.assertEqual(self.current['document']['components']['card']['node']['script']['source'], source)

    def test_component_from_node_and_structural_edits_share_script_remapping_and_history(self):
        source = "export function mount(ctx) { ctx.find('label'); ctx.find('card'); /* ctx.find('label') */ }"
        child_source = "export function mount(ctx) { ctx.find('label'); const text=\"ctx.find('label')\"; }"
        card = self.node('card', type='container', style={'x': 50, 'y': 70, 'width': 200, 'height': 150, 'rotate': 15, 'opacity': .7, 'background': '#fff'},
                         script={'source': source}, animation={'preset': 'breathe'}, locked=True,
                         children=[self.node('label', script={'source': child_source})])
        self.apply({'type': 'node.create', 'page_id': self.page, 'node': card})
        self.apply({'type': 'component.from_node', 'page_id': self.page, 'node_id': 'card', 'component_id': 'main', 'name': 'Card'})
        component = self.current['document']['components']['main']
        master, instance = component['node'], self.current['document']['pages'][0]['nodes'][0]
        child_id, root_id = master['children'][0]['id'], master['id']
        self.assertEqual(instance['id'], 'card')
        self.assertEqual(instance['props'], {'componentId': 'main'})
        self.assertEqual(instance['style']['x'], 50)
        self.assertNotIn('background', instance['style'])
        self.assertTrue(instance['locked'])
        self.assertNotIn('script', instance)
        self.assertNotIn('animation', instance)
        self.assertEqual((master['style']['x'], master['style']['rotate'], master['style']['opacity']), (0, 0, 1))
        self.assertEqual(master['style']['background'], '#fff')
        self.assertIn("ctx.find('" + child_id + "')", master['script']['source'])
        self.assertIn("ctx.find('" + root_id + "')", master['script']['source'])
        self.assertIn("/* ctx.find('label') */", master['script']['source'])
        self.history('undo')
        self.assertEqual(self.current['document']['components'], {})
        self.assertEqual(self.current['document']['pages'][0]['nodes'][0]['script']['source'], source)
        self.history('redo')
        self.apply({'type': 'component.edit', 'component_id': 'main', 'commands': [
            {'type': 'node.duplicate', 'node_id': child_id},
            {'type': 'node.update', 'node_id': root_id, 'patch': {'name': 'Updated card'}},
        ]})
        edited = self.current['document']['components']['main']
        self.assertEqual(edited['version'], 2)
        self.assertEqual(edited['node']['id'], root_id)
        duplicate = edited['node']['children'][1]
        self.assertIn("ctx.find('" + duplicate['id'] + "')", duplicate['script']['source'])
        self.assertIn('const text="ctx.find(\'label\')"', duplicate['script']['source'])
        self.history('undo')
        self.assertEqual(self.current['document']['components']['main']['version'], 1)
        self.assertEqual(len(self.current['document']['components']['main']['node']['children']), 1)

    def test_component_edit_rejects_root_changes_and_scope_escape_atomically(self):
        root = self.node('master', type='container', children=[self.node('child')])
        self.apply({'type': 'component.create', 'component': {'id': 'card', 'name': 'Card', 'node': root}})
        before = self.path.read_bytes()
        invalid = [
            {'type': 'node.delete', 'node_id': 'master'},
            {'type': 'node.duplicate', 'node_id': 'master', 'parent_id': 'master'},
            {'type': 'node.move', 'node_id': 'master'},
            {'type': 'node.ungroup', 'node_id': 'master'},
            {'type': 'node.move', 'node_id': 'child', 'target_page_id': self.page},
            {'type': 'node.create', 'node': self.node('sibling-root')},
            {'type': 'project.update', 'patch': {'name': 'Escaped'}},
        ]
        for index, command in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.apply({'type': 'component.edit', 'component_id': 'card', 'commands': [
                    {'type': 'node.update', 'node_id': 'master', 'patch': {'name': 'Uncommitted'}}, command]})
            self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.service.read(self.directory)['document']['components']['card']['version'], 1)

    def test_component_edit_can_detach_nested_instance_using_canonical_references(self):
        inner = self.node('inner-master', type='container', script={'source': "export function mount(ctx) { ctx.find('inner-label'); }"},
                          children=[self.node('inner-label')])
        outer = self.node('outer-master', type='container', children=[self.node('nested', type='instance', props={'componentId': 'inner'})])
        self.apply({'type': 'component.create', 'component': {'id': 'inner', 'name': 'Inner', 'node': inner}},
                   {'type': 'component.create', 'component': {'id': 'outer', 'name': 'Outer', 'node': outer}})
        self.apply({'type': 'component.edit', 'component_id': 'outer', 'commands': [{'type': 'component.detach', 'node_id': 'nested'}]})
        detached = self.current['document']['components']['outer']['node']['children'][0]
        self.assertEqual(detached['id'], 'nested')
        self.assertEqual(detached['type'], 'container')
        self.assertIn("ctx.find('" + detached['children'][0]['id'] + "')", detached['script']['source'])

    def test_group_ungroup_duplicate_and_move(self):
        self.apply({'type': 'node.create', 'page_id': self.page, 'node': self.node()},
                   {'type': 'node.create', 'page_id': self.page, 'node': self.node('dog', style={'x': 150, 'y': 60, 'width': 70, 'height': 40})})
        self.apply({'type': 'node.group', 'page_id': self.page, 'node_ids': ['cat', 'dog'], 'node_id': 'pets'})
        group = self.current['document']['pages'][0]['nodes'][0]
        self.assertEqual(group['style']['x'], 10)
        self.assertEqual(group['children'][1]['style']['x'], 140)
        with self.assertRaises(ValueError):
            self.apply({'type': 'node.move', 'page_id': self.page, 'node_id': 'pets', 'parent_id': 'cat'})
        self.apply({'type': 'node.duplicate', 'page_id': self.page, 'node_id': 'pets'})
        groups = self.current['document']['pages'][0]['nodes']
        self.assertNotEqual(groups[0]['children'][0]['id'], groups[1]['children'][0]['id'])
        self.apply({'type': 'node.ungroup', 'page_id': self.page, 'node_id': 'pets'})
        nodes = self.current['document']['pages'][0]['nodes']
        self.assertAlmostEqual(nodes[0]['style']['x'], 10)
        self.assertAlmostEqual(nodes[1]['style']['x'], 150)
        self.apply({'type': 'page.create', 'page': {'id': 'gallery'}}, {'type': 'page.move', 'page_id': 'gallery', 'index': 0},
                   {'type': 'node.move', 'page_id': self.page, 'node_id': 'cat', 'target_page_id': 'gallery'})
        self.assertEqual(self.current['document']['pages'][0]['nodes'][0]['id'], 'cat')

    def test_ungroup_uses_runtime_origin_and_preserves_nonuniform_scale(self):
        group = self.node('group', type='container', style={'x': 100, 'y': 200, 'width': 400, 'height': 400, 'rotate': 90, 'scaleX': 2, 'scaleY': 3},
                          children=[self.node('child', style={'x': 10, 'y': 20, 'width': 100, 'height': 40, 'rotate': 30})])
        self.apply({'type': 'node.create', 'page_id': self.page, 'node': group})
        self.apply({'type': 'node.ungroup', 'page_id': self.page, 'node_id': 'group'})
        child = self.current['document']['pages'][0]['nodes'][0]
        self.assertAlmostEqual(child['style']['x'], 40)
        self.assertAlmostEqual(child['style']['y'], 220)
        self.assertTrue(child['style']['transform'].startswith('matrix('))
        self.assertEqual(child['style']['rotate'], 0)

    def test_asset_reference_protection_import_replay_and_binary_retention(self):
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=')
        before = self.current['revision']
        self.current = self.service.import_asset(self.directory, 'cat.png', png, before, 'import-cat')
        asset = self.current['asset']
        target = self.root / self.directory / asset['path']
        self.assertEqual(target.read_bytes(), png)
        replay = self.service.import_asset(self.directory, 'cat.png', png, before, 'import-cat')
        self.assertTrue(replay['replayed'])
        self.apply({'type': 'node.create', 'page_id': self.page, 'node': self.node(type='image', props={'assetId': asset['id']})})
        with self.assertRaises(ValueError):
            self.apply({'type': 'asset.delete', 'asset_id': asset['id']})
        self.apply({'type': 'node.delete', 'page_id': self.page, 'node_id': 'cat'},
                   {'type': 'asset.delete', 'asset_id': asset['id']})
        self.assertEqual(target.read_bytes(), png)
        self.history('undo')
        self.assertIn(asset['id'], self.current['document']['assets'])
        with self.assertRaises(ValueError):
            self.apply({'type': 'asset.register', 'asset': {'id': 'escape', 'path': '../outside.png'}})

    def test_connected_asset_file_import_compact_replay_and_undo(self):
        source = self.root / 'clip.mp4'
        content = b'fictional-video-frame' * 220000
        source.write_bytes(content)
        revision = self.current['revision']
        args = (self.directory, 'clip.mp4', 'clip.mp4', revision, 'import-local-clip')
        result = self.service.import_workspace_asset(*args, expected_sha256=hashlib.sha256(content).hexdigest(),
                                                     include_document=False)
        self.assertNotIn('document', result)
        self.assertLess(len(json.dumps(result)), 3000)
        target = self.root / self.directory / result['asset']['path']
        self.assertEqual(target.read_bytes(), content)
        self.assertEqual(source.read_bytes(), content)
        self.assertTrue(self.service.import_workspace_asset(*args, include_document=False)['replayed'])
        self.current = self.service.read(self.directory)
        self.history('undo')
        self.assertNotIn(result['asset']['id'], self.current['document']['assets'])
        self.assertEqual(target.read_bytes(), content)

    def test_connected_asset_file_rejects_escape_links_hash_and_size(self):
        source = self.root / 'clip.mp4'
        source.write_bytes(b'original')
        outside = self.home / 'outside.mp4'
        outside.write_bytes(b'outside')
        for path in ('../outside.mp4', str(outside), '.hidden.mp4'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.service.import_workspace_asset(self.directory, 'clip.mp4', path,
                    self.current['revision'], 'invalid-' + path)
        link = self.root / 'link.mp4'
        link.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.service.import_workspace_asset(self.directory, 'clip.mp4', 'link.mp4',
                self.current['revision'], 'linked')
        with self.assertRaisesRegex(ConflictError, 'SHA-256'):
            self.service.import_workspace_asset(self.directory, 'clip.mp4', 'clip.mp4',
                self.current['revision'], 'wrong-hash', expected_sha256='0' * 64)
        with patch('vault_rag.design_documents.MAX_ASSET_BYTES', 2), self.assertRaises(ValueError):
            self.service.import_workspace_asset(self.directory, 'clip.mp4', 'clip.mp4',
                self.current['revision'], 'too-large')
        self.assertEqual(self.service.read(self.directory)['revision'], self.current['revision'])
        self.assertFalse((self.root / self.directory / 'Design/Assets/Imported').exists())

    def test_asset_file_changed_during_copy_is_not_registered(self):
        source = (self.root / 'clip.mp4').resolve()
        source.write_bytes(b'original')
        original_open = Path.open
        class ChangingReader:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def fileno(self):
                return self.stream.fileno()
            def read(self, limit):
                content = self.stream.read(limit)
                source.write_bytes(content + b'changed')
                return content
        def open_file(path, mode='r', *args, **kwargs):
            stream = original_open(path, mode, *args, **kwargs)
            return ChangingReader(stream) if path == source and mode == 'rb' else stream
        with patch.object(Path, 'open', open_file), self.assertRaisesRegex(ConflictError, 'changed while copying'):
            self.service.import_workspace_asset(self.directory, 'clip.mp4', 'clip.mp4',
                self.current['revision'], 'source-changed')
        self.assertEqual(self.service.read(self.directory)['revision'], self.current['revision'])

    def test_asset_source_parent_link_swap_is_rechecked_before_registration(self):
        folder = (self.root / 'Source').resolve()
        folder.mkdir()
        source = folder / 'clip.mp4'
        source.write_bytes(b'original')
        moved = (self.home / 'moved-source').resolve()
        original_open = Path.open
        class SwappingReader:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def fileno(self):
                return self.stream.fileno()
            def read(self, limit):
                data = self.stream.read(limit)
                folder.rename(moved)
                folder.symlink_to(moved, target_is_directory=True)
                return data
        def open_file(path, mode='r', *args, **kwargs):
            stream = original_open(path, mode, *args, **kwargs)
            return SwappingReader(stream) if path == source and mode == 'rb' else stream
        with patch.object(Path, 'open', open_file), self.assertRaises(ValueError):
            self.service.import_workspace_asset(self.directory, 'clip.mp4', 'Source/clip.mp4',
                self.current['revision'], 'source-parent-changed')
        self.assertEqual(self.service.read(self.directory)['revision'], self.current['revision'])

    def test_asset_replace_and_delete_track_native_paths_css_without_rewriting_comments(self):
        for key in ('old', 'new'):
            target = self.root / self.directory / f'Design/Assets/{key}.png'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(key.encode())
        self.apply({'type': 'asset.register', 'asset': {'id': 'old', 'path': 'Design/Assets/old.png'}},
                   {'type': 'asset.register', 'asset': {'id': 'new', 'path': 'Design/Assets/new.png'}},
                   {'type': 'page.update', 'page_id': self.page, 'patch': {'basePath': 'Design/UI/Site/', 'css': ".bg{background:url('../../Assets/old.png')} /* url('../../Assets/old.png') */ .label{content:\"url('../../Assets/old.png')\"}"}},
                   {'type': 'node.create', 'page_id': self.page, 'node': self.node('image', type='image', props={'src': '__STUDIO_ASSET__/Design/Assets/old.png'})},
                   {'type': 'node.create', 'page_id': self.page, 'node': self.node('native', type='element', props={'tag': 'img', 'attributes': {'src': '../../Assets/old.png', 'style': "background-image:url('../../Assets/old.png'); /* url('../../Assets/old.png') */"}})})
        with self.assertRaises(ValueError):
            self.apply({'type': 'asset.delete', 'asset_id': 'old'})
        self.apply({'type': 'asset.replace', 'asset_id': 'old', 'replacement_id': 'new'})
        page = self.current['document']['pages'][0]
        self.assertEqual(page['nodes'][0]['props']['src'], '__STUDIO_ASSET__/Design/Assets/new.png')
        self.assertEqual(page['nodes'][1]['props']['attributes']['src'], '../../Assets/new.png')
        self.assertIn("background-image:url('../../Assets/new.png')", page['nodes'][1]['props']['attributes']['style'])
        self.assertIn("/* url('../../Assets/old.png') */", page['css'])
        self.assertIn('content:"url(\'../../Assets/old.png\')"', page['css'])
        self.assertIn("background:url('../../Assets/new.png')", page['css'])
        self.apply({'type': 'asset.delete', 'asset_id': 'old'})
        self.assertEqual((self.root / self.directory / 'Design/Assets/old.png').read_bytes(), b'old')

    def test_script_only_asset_is_guarded_replaced_and_projected_with_comments_preserved(self):
        source = "export function mount(ctx) { const image=ctx.assets.resolve('old'); const label=\"ctx.assets.resolve('old')\"; /* ctx.assets.resolve('old') */ }"
        self.apply({'type': 'asset.register', 'asset': {'id': 'old', 'path': 'Design/Assets/old.png'}},
                   {'type': 'asset.register', 'asset': {'id': 'new', 'path': 'Design/Assets/new.png'}},
                   {'type': 'node.create', 'page_id': self.page, 'node': self.node(script={'source': source})})
        uses = self.service.page_view(self.directory)['document']['assets']['old']['references']
        self.assertEqual(uses[0]['node_id'], 'cat')
        with self.assertRaises(ValueError):
            self.apply({'type': 'asset.delete', 'asset_id': 'old'})
        self.apply({'type': 'asset.replace', 'asset_id': 'old', 'replacement_id': 'new'})
        replaced = self.current['document']['pages'][0]['nodes'][0]['script']['source']
        self.assertIn("const image=ctx.assets.resolve('new')", replaced)
        self.assertIn('const label="ctx.assets.resolve(\'old\')"', replaced)
        self.assertIn("/* ctx.assets.resolve('old') */", replaced)
        self.apply({'type': 'asset.delete', 'asset_id': 'old'})

    def test_responsive_mixed_data_urls_and_filename_commas_guard_delete_and_replace(self):
        old = 'Design/Assets/wide,version2.png'
        new = 'Design/Assets/replacement.png'
        data = 'data:image/svg+xml,%3Csvg%3E,%3C/svg%3E'
        candidates = '  ' + data + ' 1x,\n __STUDIO_ASSET__/' + old + '?v=2#crop 2x,  '
        preload = data + ' 1x, ../../Assets/wide,version2.png 640w'
        markup = '<picture><source srcset="' + candidates + '"></picture><link imagesrcset="' + preload + '">'
        self.apply({'type': 'asset.register', 'asset': {'id': 'old', 'path': old}},
                   {'type': 'asset.register', 'asset': {'id': 'new', 'path': new}},
                   {'type': 'page.update', 'page_id': self.page, 'patch': {'basePath': 'Design/UI/Site/'}},
                   {'type': 'node.create', 'page_id': self.page, 'node': self.node('native-responsive', type='element', props={'authored': True, 'tag': 'img', 'attributes': {'srcset': candidates, 'imagesrcset': preload}})},
                   {'type': 'node.create', 'page_id': self.page, 'node': self.node('html-responsive', type='html', props={'html': markup})})
        uses = self.service.page_view(self.directory)['document']['assets']['old']['references']
        self.assertEqual({item.get('node_id') for item in uses if item.get('node_id')}, {'native-responsive', 'html-responsive'})
        with self.assertRaisesRegex(ValueError, 'Referenced asset'):
            self.apply({'type': 'asset.delete', 'asset_id': 'old'})
        self.apply({'type': 'asset.replace', 'asset_id': 'old', 'replacement_id': 'new'})
        nodes = self.current['document']['pages'][0]['nodes']
        self.assertEqual(nodes[0]['props']['attributes']['srcset'], candidates.replace(old, new))
        self.assertEqual(nodes[0]['props']['attributes']['imagesrcset'], preload.replace('wide,version2.png', 'replacement.png'))
        self.assertEqual(nodes[1]['props']['html'], markup.replace(old, new).replace('wide,version2.png', 'replacement.png'))
        with self.assertRaisesRegex(ValueError, 'Referenced asset'):
            self.apply({'type': 'asset.delete', 'asset_id': 'new'})
        self.apply({'type': 'asset.delete', 'asset_id': 'old'})

    def test_imagesrcset_only_reference_is_protected_in_markup_and_attributes(self):
        self.apply({'type': 'asset.register', 'asset': {'id': 'preload', 'path': 'media/preload.png'}},
                   {'type': 'node.create', 'page_id': self.page, 'node': self.node('preload-link', type='element', props={'attributes': {'imagesrcset': 'data:image/png;base64,AAAA 1x, media/preload.png 2x'}})})
        with self.assertRaisesRegex(ValueError, 'Referenced asset'):
            self.apply({'type': 'asset.delete', 'asset_id': 'preload'})
        self.apply({'type': 'node.delete', 'page_id': self.page, 'node_id': 'preload-link'},
                   {'type': 'node.create', 'page_id': self.page, 'node': self.node('preload-html', type='html', props={'html': '<link imagesrcset="data:image/png;base64,AAAA 1x, media/preload.png 2x">'})})
        with self.assertRaisesRegex(ValueError, 'Referenced asset'):
            self.apply({'type': 'asset.delete', 'asset_id': 'preload'})

    def test_external_edits_are_preserved(self):
        document = self.current['document']
        document['name'] = 'External change'
        raw = json.dumps(document).encode()
        self.path.write_bytes(raw)
        with self.assertRaises(ConflictError):
            self.apply({'type': 'project.update', 'patch': {'name': 'Lost external edit'}})
        self.assertEqual(self.path.read_bytes(), raw)

    def test_pending_commit_recovers_before_and_after_file_replace(self):
        for phase in ('before', 'after'):
            with self.subTest(phase=phase):
                original_revision = self.current['revision']
                command = {'type': 'project.update', 'patch': {'name': 'Recovered ' + phase}}
                target = 'vault_rag.design_documents.atomic_write' if phase == 'before' else 'vault_rag.design_documents.DesignDocuments._finish'
                with patch(target, side_effect=OSError('simulated process interruption')):
                    with self.assertRaises(OSError):
                        self.service.apply(self.directory, [command], original_revision, 'crash-' + phase, 'Recovered edit')
                self.service = DesignDocuments(self.studio)
                self.current = self.service.read(self.directory)
                self.assertEqual(self.current['document']['name'], 'Recovered ' + phase)
                replay = self.service.apply(self.directory, [command], original_revision, 'crash-' + phase, 'Recovered edit')
                self.assertTrue(replay['replayed'])
                self.history('undo')
                self.assertEqual(self.current['document']['name'], 'Pet Home')

    def test_pending_external_conflict_does_not_overwrite(self):
        with patch('vault_rag.design_documents.atomic_write', side_effect=OSError('interruption')):
            with self.assertRaises(OSError):
                self.apply({'type': 'project.update', 'patch': {'name': 'Pending'}})
        external = self.current['document']
        external['name'] = 'User external edit'
        raw = json.dumps(external).encode()
        self.path.write_bytes(raw)
        with self.assertRaises(ConflictError):
            self.service.read(self.directory)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_project_move_rebinds_persistent_history(self):
        self.apply({'type': 'project.update', 'patch': {'name': 'Moved'}})
        destination = 'Projects/Relocated'
        (self.root / self.directory).rename(self.root / destination)
        with self.assertRaises(ConflictError):
            self.service.read(destination)
        self.current = self.service.relocate(self.directory, destination)
        self.directory = destination
        self.history('undo')
        self.assertEqual(self.current['document']['name'], 'Pet Home')

    def test_symlink_state_and_asset_paths_are_rejected(self):
        outside = self.home / 'outside'
        outside.mkdir()
        (self.root / self.directory / 'media').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.apply({'type': 'asset.register', 'asset': {'id': 'link', 'path': 'media/pet.png'}})
        state = self.root / '.vault-rag' / 'design-studio' / self.current['document']['id']
        database = state / 'history.sqlite3'
        original = database.read_bytes()
        database.unlink()
        (outside / 'database').write_bytes(original)
        database.symlink_to(outside / 'database')
        with self.assertRaises(ValueError):
            self.service.read(self.directory)


if __name__ == '__main__':
    unittest.main()
