"""ATELIER contracts: native art, complete locales and stable editable content."""
import io
import json
import unittest
import zipfile
from tests import test_design_studio
from tests.test_design_templates import nodes
from vault_rag.design_templates import load_template, template_path
from vault_rag.design_bindings import binding_status, resolve_document, validate_bindings


class AtelierTemplateTests(unittest.TestCase):
    setUp = test_design_studio.DesignStudioTests.setUp
    tearDown = test_design_studio.DesignStudioTests.tearDown

    def create(self, directory='Projects/Atelier'):
        response = self.client.post('/api/design/projects', headers=self.auth, json={
            'root': str(self.root), 'directory': directory, 'name': 'My lighting campaign',
            'managed': True, 'template_id': 'atelier'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_original_native_art_and_complete_locales(self):
        document = load_template('atelier')
        validate_bindings(document)
        self.assertEqual(len(document['pages']), 3)
        self.assertEqual(set(document['variants']), {'en', 'zh-CN', 'ja'})
        self.assertGreater(len(nodes(document)), 100)
        self.assertNotRegex(json.dumps(document), r'https?://|file://|/Users/|/home/|/workspace/|Lorem')
        self.assertEqual(document['assets'], {})
        self.assertTrue(all(node['type'] in ('element', 'button') for node in nodes(document)))
        for locale in document['variants']:
            self.assertEqual(binding_status(document, locale), {'missing': [], 'stale': []})
            projected = resolve_document(document, locale)
            hero = next(node for node in nodes(projected) if node['props'].get('bindingKey') == 'atelier.hero')
            self.assertEqual(hero['props']['text'], document['variants'][locale]['values']['atelier.hero']['value'])
        self.assertIn('CC0', (template_path('atelier') / 'README.md').read_text())

    def test_binding_edit_reopen_export_and_copy_isolation(self):
        original = (template_path('atelier') / 'project.json').read_bytes()
        first = self.create()
        second = self.create('Projects/AtelierCopy')
        self.assertNotEqual(first['document']['id'], second['document']['id'])
        response = self.client.post('/api/design/operations', headers=self.auth, json={
            'root': str(self.root), 'directory': 'Projects/Atelier', 'expected_revision': first['revision'],
            'operation_id': 'atelier-edit-title', 'commands': [
                {'type': 'binding.set', 'key': 'atelier.hero', 'value': 'A warmer\nway to live.'}]})
        self.assertEqual(response.status_code, 200, response.text)
        saved = self.client.get('/api/design/document', headers=self.auth, params={'directory': 'Projects/Atelier'}).json()['document']
        self.assertEqual(saved['bindings']['atelier.hero']['revision'], 2)
        self.assertIn('atelier.hero', binding_status(saved, 'ja')['stale'])
        for node in nodes(saved):
            if node['props'].get('bindingKey') == 'atelier.hero':
                self.assertEqual(node['props']['text'], 'A warmer\nway to live.')
        response = self.client.post('/api/design/export', headers=self.auth, json={'root':str(self.root),'directory':'Projects/Atelier'})
        self.assertEqual(response.status_code, 200, response.text)
        archive = self.client.get(response.json()['url'])
        with zipfile.ZipFile(io.BytesIO(archive.content)) as exported:
            portable = json.loads(exported.read('document.js').decode().removeprefix('window.STUDIO_DOCUMENT=').strip().removesuffix(';'))
            self.assertEqual(portable['bindings'], saved['bindings'])
            self.assertEqual(portable['variants'], saved['variants'])
        self.assertEqual((template_path('atelier') / 'project.json').read_bytes(), original)
        self.assertEqual(load_template('atelier')['pages'], second['document']['pages'])

    def test_packaged_preview(self):
        preview = self.client.get('/api/design/templates/atelier/preview', headers=self.auth)
        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview.content.startswith(b'\xff\xd8\xff'))
        self.assertEqual(preview.content, (template_path('atelier') / 'preview.jpg').read_bytes())


if __name__ == '__main__':
    unittest.main()
