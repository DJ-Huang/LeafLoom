"""Motion starter contracts: independent copies, editable effects and portable scripts."""
import io
import json
import zipfile
import unittest

from tests.test_design_templates import nodes
from tests import test_design_studio
from vault_rag.design_templates import load_template, template_path


class MotionTemplateTests(unittest.TestCase):
    setUp = test_design_studio.DesignStudioTests.setUp
    tearDown = test_design_studio.DesignStudioTests.tearDown

    def create(self, directory='Motion'):
        response = self.client.post('/api/design/projects', headers=self.auth, json={
            'root': str(self.root), 'directory': directory, 'name': 'My motion lab',
            'managed': True, 'template_id': 'motion'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_packaged_examples_are_safe_and_complete(self):
        self.assertEqual(self.client.get('/api/design/templates/motion/preview', headers=self.auth).status_code, 404)
        document = load_template('motion')
        all_nodes = nodes(document)
        ids = {node['id'] for node in all_nodes}
        for node_id in ('motion-hover', 'motion-bounce', 'motion-tilt', 'motion-orbit'):
            self.assertIn(node_id, ids)
        animations = [node['animation'] for node in all_nodes if node.get('animation')]
        self.assertTrue({'appear', 'hover', 'click'} <= {a.get('trigger', 'appear') for a in animations})
        self.assertTrue(all(a.get('iterations', 1) != 'Infinity' for a in animations))
        scripts = [node['script'] for node in all_nodes if node.get('script')]
        self.assertGreaterEqual(len(scripts), 2)
        for script in scripts:
            self.assertIn('mount(ctx)', script['source'])
            self.assertIn('prefers-reduced-motion', script['source'])
            self.assertNotRegex(script['source'], r'\bfetch\s*\(|\bsetInterval\s*\(')
        self.assertNotRegex(json.dumps(document), r'https?://|file://|/Users/|/home/|/workspace/')
        page_ids = {page['id'] for page in document['pages']}
        for node in all_nodes:
            target = node.get('props', {}).get('navigateTo')
            if target:
                self.assertIn(target, page_ids)

    def test_edit_reopen_and_export_preserve_effects_without_mutating_template(self):
        original = (template_path('motion') / 'project.json').read_bytes()
        created = self.create()
        second = self.create('SecondMotion')
        self.assertNotEqual(created['document']['id'], second['document']['id'])
        response = self.client.post('/api/design/operations', headers=self.auth, json={
            'root': str(self.root), 'directory': 'Motion', 'expected_revision': created['revision'],
            'operation_id': 'motion-edit-duration', 'commands': [{'type': 'node.update',
                'page_id': 'motion-home', 'node_id': 'motion-bounce',
                'patch': {'animation': {'preset': 'bounce', 'trigger': 'click', 'duration': 720, 'iterations': 1}}}]})
        self.assertEqual(response.status_code, 200, response.text)
        saved = self.client.get('/api/design/document', headers=self.auth, params={'directory': 'Motion'}).json()
        bounce = next(node for node in nodes(saved['document']) if node['id'] == 'motion-bounce')
        self.assertEqual(bounce['animation']['duration'], 720)
        response = self.client.post('/api/design/export', headers=self.auth,
                                    json={'root': str(self.root), 'directory': 'Motion'})
        self.assertEqual(response.status_code, 200, response.text)
        archive = self.client.get(response.json()['url'])
        with zipfile.ZipFile(io.BytesIO(archive.content)) as exported:
            portable = json.loads(exported.read('document.js').decode().removeprefix('window.STUDIO_DOCUMENT=').strip().removesuffix(';'))
            self.assertEqual(portable['pages'], saved['document']['pages'])
        self.assertEqual((template_path('motion') / 'project.json').read_bytes(), original)
        self.assertEqual(load_template('motion')['pages'], second['document']['pages'])


if __name__ == '__main__':
    unittest.main()
