"""Workspace moves/history and shared-library dependency integrity."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import zipfile
from unittest.mock import patch

from vault_rag.design_documents import DesignDocuments
from vault_rag.design_workspace import DesignWorkspace, _walk
from vault_rag.local_state import ConflictError, Files, LocalConfig


class DesignWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'vault'
        self.root.mkdir()
        self.config = LocalConfig(Path(self.temp.name) / 'config')
        self.config.save({'root': str(self.root), 'include_roots': ['Projects']})
        self.files = Files(self.config)
        self.events = []
        runtime = SimpleNamespace(events=SimpleNamespace(publish=lambda kind, **value: self.events.append({'type': kind, **value})))
        self.studio = SimpleNamespace(config=self.config, files=self.files, runtime=runtime,
                                      _project_summary=self.summary, _find_spec_file=lambda project: project / 'Design/project-spec.json')
        self.docs = DesignDocuments(self.studio)
        self.workspace = DesignWorkspace(self.studio, self.docs)
        self.directory = 'Projects/Pets'
        self.project = self.create(self.directory)

    def tearDown(self):
        self.temp.cleanup()

    def summary(self, project, root):
        spec = project / 'Design/project-spec.json'
        if not spec.is_file():
            return None
        value = json.loads(spec.read_text())['project']
        return {'id': value['id'], 'name': value['name'], 'directory': project.relative_to(root).as_posix()}

    def create(self, directory):
        project = self.root / directory
        (project / 'Design').mkdir(parents=True)
        (project / 'Design/project-spec.json').write_text(json.dumps({'project': {'id': directory, 'name': 'Pet Home'}}))
        return self.docs.create(directory, 'Pet Home')

    def manage(self, action, operation_id, **options):
        return self.workspace.manage(self.directory, action, self.workspace.state()['revision'], operation_id, **options)

    def test_metadata_history_uses_deltas_and_receipts_survive_branching(self):
        revision = self.workspace.state()['revision']
        changed = self.manage('rename', 'rename-pets', value='A new name')
        self.assertEqual(changed['meta'][self.directory]['name'], 'A new name')
        self.assertEqual(self.events[-1]['type'], 'files')
        self.assertTrue('delta' in self.workspace._load()['history'][0])
        self.assertEqual(self.workspace.manage(self.directory, 'rename', revision, 'rename-pets', value='A new name')['revision'], changed['revision'])
        with self.assertRaises(ConflictError):
            self.workspace.manage(self.directory, 'rename', changed['revision'], 'rename-pets', value='Different')
        undone = self.workspace.history('undo', changed['revision'])
        self.assertNotIn(self.directory, undone['meta'])
        self.manage('favorite', 'favorite-pets', value=True)
        replay = self.workspace.manage(self.directory, 'rename', revision, 'rename-pets', value='A new name')
        self.assertNotIn('name', replay['meta'][self.directory])
        self.assertFalse(replay['history']['can_redo'])

    def test_managed_move_undo_keeps_newer_design_edits_and_history(self):
        self.manage('move', 'move-pets', destination='Projects/Moved')
        value = self.docs.read('Projects/Moved')
        value = self.docs.apply('Projects/Moved', [{'type': 'project.update', 'patch': {'name': 'After move'}}], value['revision'], 'edit-after-move')
        undone = self.workspace.history('undo', self.workspace.state()['revision'])
        self.assertEqual(undone['relocation'], {'source': 'Projects/Moved', 'destination': self.directory})
        restored = self.docs.read(self.directory)
        self.assertEqual(restored['document']['name'], 'After move')
        restored = self.docs.history(self.directory, 'undo', restored['revision'], 'undo-after-move')
        self.assertEqual(restored['document']['name'], 'Pet Home')
        redone = self.workspace.history('redo', self.workspace.state()['revision'])
        self.assertEqual(redone['relocation'], {'source': self.directory, 'destination': 'Projects/Moved'})

    def test_delete_restore_and_creation_history_rebind_owner(self):
        deleted = self.manage('delete', 'delete-pets')
        self.assertFalse((self.root / self.directory).exists())
        self.assertTrue(deleted['meta'][self.directory]['deleted'])
        self.workspace.history('undo', deleted['revision'])
        self.assertEqual(self.docs.read(self.directory)['document']['id'], self.project['document']['id'])
        # A separate workspace can undo creation after editing, without losing
        # either the edited document or its independent project history.
        self.workspace.record_creation(self.directory)
        value = self.docs.read(self.directory)
        self.docs.apply(self.directory, [{'type': 'project.update', 'patch': {'name': 'Edited creation'}}], value['revision'], 'edit-created')
        self.workspace.history('undo', self.workspace.state()['revision'])
        self.workspace.history('redo', self.workspace.state()['revision'])
        self.assertEqual(self.docs.read(self.directory)['document']['name'], 'Edited creation')

    def test_interrupted_move_recovers_and_rebinds_idempotently(self):
        original_write = __import__('vault_rag.design_workspace', fromlist=['atomic_write']).atomic_write

        def write(path, data):
            if path.name == 'workspace.json' and b'"move-pets"' in data:
                raise OSError('simulated interruption after move')
            return original_write(path, data)

        with patch('vault_rag.design_workspace.atomic_write', side_effect=write):
            with self.assertRaises(OSError):
                self.manage('move', 'move-pets', destination='Projects/Moved')
        self.assertTrue((self.root / 'Projects/Moved').is_dir())
        state = self.workspace.state()
        self.assertEqual(self.docs.read('Projects/Moved')['document']['id'], self.project['document']['id'])
        self.assertTrue(state['history']['can_undo'])
        replay = self.workspace.manage(self.directory, 'move', 'stale', 'move-pets', destination='Projects/Moved')
        self.assertEqual(state['revision'], replay['revision'])

    def test_move_cannot_target_private_state_or_existing_directory(self):
        with self.assertRaises(ValueError):
            self.manage('move', 'invalid-private', destination='.vault-rag/design-studio/other')
        (self.root / 'Projects/Existing').mkdir()
        with self.assertRaises(ConflictError):
            self.manage('move', 'invalid-exists', destination='Projects/Existing')
        self.assertTrue((self.root / self.directory).is_dir())
        self.assertFalse(self.workspace.state()['history']['can_undo'])

    def test_restore_specific_trash_item_preserves_other_workspace_actions(self):
        self.manage('delete', 'delete-pets')
        self.create('Projects/Dogs')
        self.workspace.manage('Projects/Dogs', 'favorite', self.workspace.state()['revision'], 'favorite-dogs', value=True)
        restored = self.manage('restore', 'restore-pets')
        self.assertTrue(restored['meta']['Projects/Dogs']['favorite'])
        self.assertNotIn('deleted', restored['meta'][self.directory])
        self.assertEqual(self.docs.read(self.directory)['document']['id'], self.project['document']['id'])
        self.workspace.history('undo', restored['revision'])
        self.assertFalse((self.root / self.directory).exists())

    def test_copy_assigns_independent_project_and_document_identity(self):
        self.workspace.copy_project(self.directory, 'Projects/Copy')
        value = self.docs.read('Projects/Copy')
        self.assertNotEqual(value['document']['id'], self.project['document']['id'])
        self.assertFalse(value['history']['can_undo'])
        self.assertNotEqual(self.summary(self.root / 'Projects/Copy', self.root)['id'], self.summary(self.root / self.directory, self.root)['id'])

    def test_finish_migration_only_accepts_declared_variants_and_retains_source_board_count(self):
        document = copy.deepcopy(self.project['document'])
        source_id = document['pages'][0]['id']
        document['migration'] = {'status': 'capture_required', 'boards': [{'id': source_id, 'name': 'Settings'}]}
        pending = self.docs.apply(self.directory, [{'type': 'document.replace', 'document': document}], self.project['revision'], 'migration-pending')
        source = copy.deepcopy(document['pages'][0])
        source['migration'] = {'contextVariants': [{'context': {'settingsFrom': 'game'}, 'pageId': 'settings-game'}]}
        variant = {'id': 'settings-game', 'name': 'Settings from game', 'width': 720, 'height': 1560, 'nodes': [],
                   'migration': {'contextSource': {'pageId': source_id, 'context': {'settingsFrom': 'game'}}}}
        unrelated = {'id': 'unrelated', 'name': 'Unrelated', 'width': 720, 'height': 1560, 'nodes': []}
        before = (self.root / self.directory / 'Design/studio/project.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'Extra capture pages'):
            self.workspace.finish_migration(self.directory, [source, variant, unrelated], pending['revision'], 'capture-unrelated')
        with self.assertRaisesRegex(ValueError, 'every legacy artboard'):
            self.workspace.finish_migration(self.directory, [variant], pending['revision'], 'capture-missing-source')
        self.assertEqual((self.root / self.directory / 'Design/studio/project.json').read_bytes(), before)
        converted = self.workspace.finish_migration(self.directory, [source, variant], pending['revision'], 'capture-complete')
        self.assertEqual(converted['document']['migration']['boards'], document['migration']['boards'])
        report = converted['document']['migration']['report']
        self.assertEqual((report['pages'], report['source_pages'], report['context_variants']), (2, 1, 1))

    def test_shared_component_keeps_context_variant_page_dependencies_and_remaps_ownership(self):
        document = copy.deepcopy(self.project['document'])
        source_id = document['pages'][0]['id']
        document['pages'][0]['migration'] = {'contextVariants': [{'context': {'settingsFrom': 'game'}, 'pageId': 'settings-game'}]}
        document['pages'].append({'id': 'settings-game', 'name': 'Settings from game', 'width': 720, 'height': 1560, 'nodes': [],
                                  'migration': {'contextSource': {'pageId': source_id, 'context': {'settingsFrom': 'game'}}}})
        document['components']['settings'] = {'id': 'settings', 'name': 'Settings', 'version': 1,
                                               'node': {'id': 'settings-embed', 'type': 'page', 'props': {'pageId': source_id}, 'style': {}, 'children': []}}
        self.docs.apply(self.directory, [{'type': 'document.replace', 'document': document}], self.project['revision'], 'prepare-context-library')
        state = self.workspace.publish(self.directory, 'component', 'settings', self.workspace.state()['revision'], 'publish-context-library')
        item_id = state['items'][0]['id']
        self.assertEqual({page['id'] for page in self.workspace._load()['library'][item_id]['pages']}, {source_id, 'settings-game'})
        target = self.create('Projects/Target')
        imported = self.workspace.import_library('Projects/Target', item_id, target['revision'], 'import-context-library')['document']
        component = next(iter(imported['components'].values()))
        pages = {page['id']: page for page in imported['pages']}
        base = pages[component['node']['props']['pageId']]
        mapping = base['migration']['contextVariants'][0]
        variant = pages[mapping['pageId']]
        self.assertNotEqual(base['id'], source_id)
        self.assertNotEqual(variant['id'], 'settings-game')
        self.assertEqual(variant['migration']['contextSource'], {'pageId': base['id'], 'context': mapping['context']})

    def test_managed_copy_moves_and_creation_do_not_hash_binary_content(self):
        target = self.root / self.directory / 'Design/Assets/binary.bin'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'media' * 100)
        with patch('vault_rag.design_workspace.hashlib.file_digest', side_effect=AssertionError('Managed move/copy hashed media')):
            self.workspace.copy_project(self.directory, 'Projects/Copy')
            self.manage('move', 'move-without-hash', destination='Projects/Moved')
            self.workspace.history('undo', self.workspace.state()['revision'])
            self.manage('delete', 'delete-without-hash')
            self.workspace.history('undo', self.workspace.state()['revision'])
        self.assertEqual(target.read_bytes(), b'media' * 100)

    def test_lightweight_copy_validation_still_rejects_links(self):
        outside = self.root.parent / 'outside.txt'
        outside.write_bytes(b'external')
        (self.root / self.directory / 'linked.txt').symlink_to(outside)
        with self.assertRaises(ValueError):
            self.workspace.copy_project(self.directory, 'Projects/Copy')
        self.assertFalse((self.root / 'Projects/Copy').exists())

    def test_renamed_display_title_is_used_by_copy_and_export_without_source_document_changes(self):
        path = self.root / self.directory / 'Design/studio/project.json'
        original = path.read_bytes()
        before = self.docs.read(self.directory)
        self.manage('rename', 'rename-pets', value='Renamed & Ready')
        self.workspace.copy_project(self.directory, 'Projects/Copy')
        copied = self.docs.read('Projects/Copy')
        self.assertEqual(copied['document']['name'], 'Renamed & Ready Copy')
        self.assertEqual(self.summary(self.root / 'Projects/Copy', self.root)['name'], 'Renamed & Ready Copy')
        with patch.object(self.workspace, 'session', return_value={'origin': 'http://localhost:1000', 'id': 'session'}):
            exported = self.workspace.export(self.directory)
        with zipfile.ZipFile(self.root / exported['path']) as archive:
            document = json.loads(archive.read('document.js').decode().removeprefix('window.STUDIO_DOCUMENT=').rstrip(';\n'))
            self.assertEqual(document['name'], 'Renamed & Ready')
            self.assertIn('<title>Renamed &amp; Ready</title>', archive.read('index.html').decode())
        after = self.docs.read(self.directory)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(after['revision'], before['revision'])
        self.assertEqual(after['document']['name'], 'Pet Home')
        self.assertEqual(self.docs.history(self.directory)['total'], 0)

    def prepare_library(self):
        document = copy.deepcopy(self.project['document'])
        for name in ('cat', 'unused'):
            path = f'Design/Assets/{name}.png'
            (self.root / self.directory / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / self.directory / path).write_bytes((name + '-bytes').encode())
            document['assets'][name] = {'id': name, 'name': name, 'path': path}
        def node(key, kind='container', props=None, children=None, **extra):
            return {'id': key, 'type': kind, 'name': key, 'style': {}, 'props': props or {}, 'children': children or [], **extra}
        document['pages'].append({'id': 'embedded', 'name': 'Details', 'width': 400, 'height': 400,
                                  'nodes': [node('detail-text', 'text', {'text': 'Details'})]})
        document['pages'].append({'id': 'unused-page', 'name': 'Unused', 'width': 400, 'height': 400,
                                  'nodes': [node('unused-text', 'text', {'text': 'Unused'})]})
        document['components']['child'] = {'id': 'child', 'name': 'Child', 'version': 1,
                                            'node': node('child-root', script={'moduleId': 'animate'})}
        document['components']['card'] = {'id': 'card', 'name': 'Pet card', 'version': 1,
                                           'node': node('card-root', children=[node('picture', 'image', {'assetId': 'cat'}),
                                                                             node('child-instance', 'instance', {'componentId': 'child'}),
                                                                             node('embed-instance', 'page', {'pageId': 'embedded'})])}
        document['scripts'] = {'animate': {'id': 'animate', 'path': 'scripts/animate.js', 'source': "import { helper } from './helper.js'; export function mount(ctx) { helper(ctx); }"},
                               'helper': {'id': 'helper', 'path': 'scripts/helper.js', 'source': 'export function helper(ctx) {}'},
                               'unused-script': {'id': 'unused-script', 'path': 'scripts/unused.js', 'source': '// unrelated'}}
        self.project = self.docs.apply(self.directory, [{'type': 'document.replace', 'document': document}], self.project['revision'], 'prepare-library')
        return self.workspace.publish(self.directory, 'component', 'card', self.workspace.state()['revision'], 'publish-card')

    def test_library_closure_remaps_all_node_ids_and_retry_is_idempotent(self):
        state = self.prepare_library()
        item_id = state['items'][0]['id']
        item = self.workspace._load()['library'][item_id]
        self.assertEqual(set(item['assets']), {'cat'})
        self.assertEqual(set(item['components']), {'card', 'child'})
        self.assertEqual([page['id'] for page in item['pages']], ['embedded'])
        self.assertEqual(set(item['scripts']), {'animate', 'helper'})
        target = self.create('Projects/Target')
        imported = self.workspace.import_library('Projects/Target', item_id, target['revision'], 'import-card')
        ids = [page['id'] for page in imported['document']['pages']]
        ids += [node['id'] for page in imported['document']['pages'] for node in _walk(page['nodes'])]
        ids += [node['id'] for component in imported['document']['components'].values() for node in _walk([component['node']])]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(node_id not in ('card-root', 'child-root', 'detail-text') for node_id in ids))
        self.assertEqual(len(imported['document']['pages']), 2)
        self.assertEqual(len(imported['document']['components']), 2)
        self.assertEqual(len(imported['document']['scripts']), 2)
        replay = self.workspace.import_library('Projects/Target', item_id, target['revision'], 'import-card')
        self.assertTrue(replay['replayed'])
        self.assertEqual(imported['revision'], replay['revision'])
        source_import = self.workspace.import_library(self.directory, item_id, self.project['revision'], 'import-into-source')
        self.assertEqual(len(source_import['document']['components']), 4)

    def test_library_update_keeps_stable_ids_original_media_and_can_undo(self):
        state = self.prepare_library()
        item_id = state['items'][0]['id']
        target = self.create('Projects/Target')
        imported = self.workspace.import_library('Projects/Target', item_id, target['revision'], 'import-card')
        original_asset = next(iter(imported['document']['assets'].values()))
        original_path = self.root / 'Projects/Target' / original_asset['path']
        component_ids = set(imported['document']['components'])
        (self.root / self.directory / 'Design/Assets/cat.png').write_bytes(b'new-cat-bytes')
        self.workspace.publish(self.directory, 'component', 'card', self.workspace.state()['revision'], 'publish-card-v2')
        updated = self.workspace.import_library('Projects/Target', item_id, imported['revision'], 'update-card')
        self.assertEqual(set(updated['document']['components']), component_ids)
        new_asset = updated['document']['assets'][original_asset['id']]
        self.assertNotEqual(new_asset['path'], original_asset['path'])
        self.assertEqual(original_path.read_bytes(), b'cat-bytes')
        self.assertEqual((self.root / 'Projects/Target' / new_asset['path']).read_bytes(), b'new-cat-bytes')
        restored = self.docs.history('Projects/Target', 'undo', updated['revision'], 'undo-library-update')
        self.assertEqual(restored['document']['assets'][original_asset['id']]['path'], original_asset['path'])
        version_one = self.workspace.import_library('Projects/Target', item_id, restored['revision'], 'pin-version-one', version=1)
        self.assertEqual(version_one['document']['assets'][original_asset['id']]['library']['version'], 1)

    def test_library_corrupt_blob_does_not_override_user_assets(self):
        state = self.prepare_library()
        item_id = state['items'][0]['id']
        target = self.create('Projects/Target')
        asset = next(iter(self.workspace._load()['library'][item_id]['assets'].values()))
        self.workspace._state('library-blobs', asset['sha256']).write_bytes(b'corrupted')
        with self.assertRaises(ConflictError):
            self.workspace.import_library('Projects/Target', item_id, target['revision'], 'import-corrupt')
        self.assertEqual(self.docs.read('Projects/Target')['document']['assets'], {})

    def test_library_script_only_helpers_include_media_pages_and_remap_literal_calls(self):
        document = copy.deepcopy(self.project['document'])
        for key in ('cat', 'unused', 'path-only'):
            path = f'Design/Assets/{key}.png'
            target = self.root / self.directory / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((key + '-bytes').encode())
            if key != 'path-only':
                document['assets'][key] = {'id': key, 'name': key, 'path': path}
        for key in ('target', 'popup', 'unused-page'):
            document['pages'].append({'id': key, 'name': key, 'width': 400, 'height': 400, 'nodes': []})
        source = """import { helper } from 'scripts/helper.js';
export function mount(ctx) {
 const registered=ctx.assets.resolve('cat');
 const path=ctx.assets.resolve('Design/Assets/path-only.png');
 ctx.navigate('target'); ctx.open("popup");
 const label="ctx.assets.resolve('unused')";
 // ctx.assets.resolve('unused'); ctx.navigate('unused-page');
}"""
        document['components']['scripted'] = {'id': 'scripted', 'name': 'Scripted', 'version': 1,
                                               'node': {'id': 'scripted-root', 'name': 'Scripted', 'type': 'container', 'style': {}, 'props': {}, 'children': [], 'script': {'source': source}}}
        document['scripts']['helper'] = {'id': 'helper', 'path': 'scripts/helper.js', 'source': 'export function helper() {}'}
        self.project = self.docs.apply(self.directory, [{'type': 'document.replace', 'document': document}], self.project['revision'], 'prepare-script-library')
        state = self.workspace.publish(self.directory, 'component', 'scripted', self.workspace.state()['revision'], 'publish-scripted')
        item_id = state['items'][0]['id']
        published = self.workspace._load()['library'][item_id]
        self.assertEqual({asset['path'] for asset in published['assets'].values()}, {'Design/Assets/cat.png', 'Design/Assets/path-only.png'})
        self.assertEqual({page['id'] for page in published['pages']}, {'target', 'popup'})
        target = self.create('Projects/Target')
        imported = self.workspace.import_library('Projects/Target', item_id, target['revision'], 'import-scripted')['document']
        cat_id = next(key for key, asset in imported['assets'].items() if asset['name'] == 'cat')
        target_id = next(page['id'] for page in imported['pages'] if page['name'] == 'target')
        popup_id = next(page['id'] for page in imported['pages'] if page['name'] == 'popup')
        component = next(iter(imported['components'].values()))
        rewritten = component['node']['script']['source']
        module_path = next(script['path'] for script in imported['scripts'].values())
        self.assertIn("from './" + module_path + "'", rewritten)
        self.assertIn("ctx.assets.resolve('" + cat_id + "')", rewritten)
        self.assertIn("ctx.navigate('" + target_id + "')", rewritten)
        self.assertIn('ctx.open("' + popup_id + '")', rewritten)
        self.assertIn('// ctx.assets.resolve(\'unused\'); ctx.navigate(\'unused-page\');', rewritten)
        self.assertIn('const label="ctx.assets.resolve(\'unused\')"', rewritten)
        path_asset = next(asset for asset in imported['assets'].values() if asset['name'] == 'path-only.png')
        self.assertIn("ctx.assets.resolve('" + path_asset['path'] + "')", rewritten)
        self.assertEqual((self.root / 'Projects/Target' / path_asset['path']).read_bytes(), b'path-only-bytes')


if __name__ == '__main__':
    unittest.main()
