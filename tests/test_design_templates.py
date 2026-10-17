"""Built-in FORMA starter creation, isolation, runtime and boundary contracts."""
import io
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
import zipfile

from tests import test_design_studio
from vault_rag.design_templates import template_path


def nodes(document):
    def walk(items):
        for item in items:
            yield item
            yield from walk(item.get('children', []))
    return [node for page in document['pages'] for node in walk(page['nodes'])]


class DesignTemplateTests(unittest.TestCase):
    setUp = test_design_studio.DesignStudioTests.setUp
    tearDown = test_design_studio.DesignStudioTests.tearDown

    def create(self, directory='Projects/Forma', name='My editorial studio', **overrides):
        return self.client.post('/api/design/projects', headers=self.auth, json={
            'root': str(self.root), 'directory': directory, 'name': name,
            'managed': True, 'template_id': 'forma', **overrides})

    def read(self, directory='Projects/Forma'):
        response = self.client.get('/api/design/document', headers=self.auth, params={'directory': directory})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def post(self, endpoint, directory='Projects/Forma', **body):
        return self.client.post('/api/design/' + endpoint, headers=self.auth,
                                json={'root': str(self.root), 'directory': directory, **body})

    def test_creation_is_editable_persistent_and_independent(self):
        package = template_path('forma')
        original_bytes = {path.name: path.read_bytes() for path in package.iterdir() if path.is_file()}
        original = json.loads(original_bytes['project.json'])
        self.assertNotRegex(original_bytes['project.json'].decode(), r'https?://|file://|/Users/|/home/|/workspace/')
        first = self.create(name='自己的 FORMA 工作室')
        self.assertEqual(first.status_code, 200, first.text)
        first = first.json()
        second = self.create('Projects/Other', name='Second copy')
        self.assertEqual(second.status_code, 200, second.text)
        second = second.json()
        document = first['document']
        self.assertTrue(first['project']['managed'])
        self.assertEqual(document['name'], '自己的 FORMA 工作室')
        self.assertEqual(first['project']['name'], document['name'])
        self.assertEqual(len(document['pages']), 4)
        self.assertEqual(len(nodes(document)), 328)
        self.assertEqual(len({document['id'], second['document']['id'], original['id']}), 3)
        self.assertNotEqual(first['project']['html_project_id'], second['project']['html_project_id'])
        # Page-local IDs and navigation references remain consistent within each copy.
        page_ids = {page['id'] for page in document['pages']}
        for node in nodes(document):
            if node.get('props', {}).get('navigateTo'):
                self.assertIn(node['props']['navigateTo'], page_ids)
        node = next(node for node in nodes(document) if node.get('props', {}).get('text'))
        edited = self.post('operations', expected_revision=first['revision'], operation_id='edit-forma-title',
            commands=[{'type': 'node.update', 'page_id': document['pages'][0]['id'], 'node_id': node['id'], 'patch': {'props': {'text': 'A studio of my own'}}}])
        self.assertEqual(edited.status_code, 200, edited.text)
        reopened = self.read()
        self.assertEqual(next(item for item in nodes(reopened['document']) if item['id'] == node['id'])['props']['text'], 'A studio of my own')
        self.assertEqual(reopened['document']['name'], '自己的 FORMA 工作室')
        self.assertEqual(self.read('Projects/Other')['document'], second['document'])
        self.assertEqual({path.name: path.read_bytes() for path in package.iterdir() if path.is_file()}, original_bytes)

    def test_preview_auth_runtime_and_complete_portable_export(self):
        preview = self.client.get('/api/design/templates/forma/preview', headers=self.auth)
        self.assertEqual(preview.status_code, 200, preview.text[:100])
        self.assertEqual(preview.headers['content-type'], 'image/jpeg')
        self.assertTrue(preview.content.startswith(b'\xff\xd8\xff'))
        self.assertEqual(preview.content, (template_path('forma') / 'preview.jpg').read_bytes())
        self.client.cookies.clear()
        denied = self.client.get('/api/design/templates/forma/preview')
        self.assertIn(denied.status_code, (401, 403))
        created = self.create()
        self.assertEqual(created.status_code, 200, created.text)
        document = created.json()['document']
        session = self.post('session')
        self.assertEqual(session.status_code, 200, session.text)
        session = session.json()
        self.client.cookies.clear()
        runtime = self.client.get(session['origin'] + '/Design/studio/runtime.html?' + urlencode({'session': session['id']}))
        self.assertEqual(runtime.status_code, 200, runtime.text)
        self.assertIn('studio-root', runtime.text)
        exported = self.post('export')
        self.assertEqual(exported.status_code, 200, exported.text)
        downloaded = self.client.get(exported.json()['url'])
        self.assertEqual(downloaded.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
            for name in ('index.html', 'document.js', 'runtime.js', 'runtime.css'):
                self.assertIn(name, archive.namelist())
            script = archive.read('document.js').decode()
            exported_document = json.loads(script.removeprefix('window.STUDIO_DOCUMENT=').strip().removesuffix(';'))
            self.assertEqual(exported_document['pages'], document['pages'])
            self.assertEqual(len(nodes(exported_document)), 328)
            self.assertNotIn('.vault-rag', '\n'.join(archive.namelist()))

    def test_reject_unknown_template_before_creating_any_files(self):
        for template in ('unknown', '../forma', '', {'id': 'forma'}):
            with self.subTest(template=template):
                response = self.create(template_id=template)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertFalse((self.root / 'Projects/Forma').exists())
        preview = self.client.get('/api/design/templates/unknown/preview', headers=self.auth)
        self.assertIn(preview.status_code, (400, 404))

    def test_existing_project_directory_and_unrelated_files_are_never_overwritten(self):
        created = self.create()
        self.assertEqual(created.status_code, 200, created.text)
        for directory in ('Projects/Forma', 'Projects/Personal', 'Projects/Empty'):
            target = self.root / directory
            target.mkdir(parents=True, exist_ok=True)
            if directory.endswith('Personal'):
                (target / 'notes.txt').write_text('Keep my original work', encoding='utf-8')
            before = {str(p.relative_to(target)): p.read_bytes() for p in target.rglob('*') if p.is_file()}
            response = self.create(directory)
            self.assertEqual(response.status_code, 409, response.text)
            after = {str(p.relative_to(target)): p.read_bytes() for p in target.rglob('*') if p.is_file()}
            self.assertEqual(before, after)

    def test_failed_document_or_runtime_creation_rolls_back_new_directory(self):
        # Fail after scaffolding starts; retries must not encounter a half-created project.
        for method in ('vault_rag.design_documents.DesignDocuments.create',
                       'vault_rag.design_workspace.DesignWorkspace.install_runtime'):
            with self.subTest(method=method), patch(method, side_effect=ValueError('Injected creation failure')):
                response = self.create()
                self.assertEqual(response.status_code, 400, response.text)
                self.assertFalse((self.root / 'Projects/Forma').exists())
        response = self.create()
        self.assertEqual(response.status_code, 200, response.text)

    def test_root_guard_and_traversal_fail_without_writing(self):
        response = self.create(root='/wrong')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertFalse((self.root / 'Projects/Forma').exists())
        sentinel = self.home / 'outside.txt'
        sentinel.write_text('Untouched', encoding='utf-8')
        for directory in ('../escape', 'Projects/../../escape', str(self.home / 'escape')):
            with self.subTest(directory=directory):
                response = self.create(directory)
                self.assertIn(response.status_code, (400, 403, 409), response.text)
                self.assertFalse((self.home / 'escape').exists())
                self.assertFalse((self.root / 'escape').exists())
                self.assertEqual(sentinel.read_text(encoding='utf-8'), 'Untouched')


if __name__ == '__main__':
    unittest.main()
