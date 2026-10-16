"""Managed Studio HTTP/MCP integration, isolation and portable export contracts."""
import io
import json
import unittest
import time
from urllib.parse import urlencode
import zipfile

from tests.test_design_studio import DesignStudioTests


class ManagedDesignTests(unittest.TestCase):
    setUp = DesignStudioTests.setUp
    tearDown = DesignStudioTests.tearDown
    mcp_call = DesignStudioTests.mcp_call

    def create(self):
        response = self.client.post('/api/design/projects', headers=self.auth, json={
            'root': str(self.root), 'directory': 'Projects/Studio', 'name': 'Studio', 'managed': True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['project']['managed'])
        return response.json()

    def post(self, endpoint, **body):
        return self.client.post('/api/design/' + endpoint, headers=self.auth,
                                json={'root': str(self.root), 'directory': 'Projects/Studio', **body})

    def test_managed_operations_cas_root_guard_and_reopened_history(self):
        value = self.create()
        page = value['document']['pages'][0]['id']
        operation = dict(commands=[{'type': 'node.create', 'page_id': page, 'node': {
            'id': 'title', 'type': 'text', 'name': 'Title', 'style': {'x': 30, 'y': 50, 'width': 300, 'height': 60},
            'props': {'text': 'Hello'}, 'script': {'source': 'export function mount(ctx){ctx.el.dataset.started="yes";return ()=>{}}'}, 'children': []}}],
            expected_revision=value['revision'], operation_id='create-title')
        edited = self.post('operations', **operation)
        self.assertEqual(edited.status_code, 200, edited.text)
        replay = self.post('operations', **operation)
        self.assertTrue(replay.json()['replayed'])
        stale = self.post('operations', **{**operation, 'operation_id': 'stale'})
        self.assertEqual(stale.status_code, 409)
        wrong = self.post('operations', **{**operation, 'root': '/other'})
        self.assertEqual(wrong.status_code, 409)
        current = self.client.get('/api/design/document?directory=Projects/Studio', headers=self.auth).json()
        undone = self.post('history', action='undo', expected_revision=current['revision'], operation_id='undo-title')
        self.assertEqual(undone.json()['document']['pages'][0]['nodes'], [])
        redone = self.post('history', action='redo', expected_revision=undone.json()['revision'], operation_id='redo-title')
        self.assertEqual(redone.json()['document']['pages'][0]['nodes'][0]['id'], 'title')
        # Compatibility tools must not overwrite managed documents without CAS.
        legacy = self.post('projects/transforms', board_id=page, transforms={'title': {'tx': 1}})
        self.assertEqual(legacy.status_code, 409)

    def test_runtime_capability_and_export_are_project_scoped(self):
        self.create()
        session = self.post('session').json()
        self.client.cookies.clear()
        runtime = self.client.get(session['origin'] + '/Design/studio/runtime.html?' + urlencode({'session': session['id']}))
        self.assertEqual(runtime.status_code, 200, runtime.text)
        denied = self.client.get(session['origin'] + '/Design/studio/project.json?session=' + session['id'])
        self.assertEqual(denied.status_code, 410)
        denied_api = self.client.get(session['origin'] + '/api/design/workspace?session=' + session['id'])
        self.assertNotEqual(denied_api.status_code, 200)
        exported = self.post('export')
        self.assertEqual(exported.status_code, 200, exported.text)
        downloaded = self.client.get(exported.json()['url'])
        self.assertEqual(downloaded.status_code, 200, downloaded.text[:100])
        archive = zipfile.ZipFile(io.BytesIO(downloaded.content))
        for name in ('index.html', 'document.js', 'runtime.js', 'runtime.css'):
            self.assertIn(name, archive.namelist())
        self.assertNotIn('.vault-rag', '\n'.join(archive.namelist()))

    def test_mcp_managed_commands_and_undo_share_http_document(self):
        value = self.mcp_call('design_create_project', {'directory': 'Projects/Studio', 'name': 'AI Studio',
                              'managed': True, 'workspace_revision': self.config.data['revision']})
        page = value['document']['pages'][0]['id']
        edited = self.mcp_call('design_operations', {'directory': 'Projects/Studio', 'workspace_revision': self.config.data['revision'],
            'expected_revision': value['revision'], 'operation_id': 'ai-edit', 'label': 'AI instruction',
            'commands': [{'type': 'page.update', 'page_id': page, 'patch': {'name': 'AI Page', 'script': {'source': 'export function mount(ctx){}'}}}]})
        self.assertTrue(edited['history']['can_undo'])
        read = self.mcp_call('design_document', {'directory': 'Projects/Studio'})
        self.assertEqual(read['document']['pages'][0]['name'], 'AI Page')
        undone = self.mcp_call('design_history', {'directory': 'Projects/Studio', 'action': 'undo',
            'workspace_revision': self.config.data['revision'], 'expected_revision': read['revision'], 'operation_id': 'undo-ai'})
        self.assertNotIn('script', undone['document']['pages'][0])

    def test_root_guard_precedes_creation(self):
        response = self.client.post('/api/design/projects', headers=self.auth, json={
            'root': '/wrong', 'directory': 'Projects/Wrong', 'name': 'Wrong', 'managed': True})
        self.assertEqual(response.status_code, 409)
        self.assertFalse((self.root / 'Projects/Wrong').exists())

    def test_project_trash_permanent_delete_requires_root_confirmation_and_revision(self):
        self.create()
        state = self.client.get('/api/design/workspace', headers=self.auth).json()
        deleted = self.post('workspace', action='delete', expected_revision=state['revision'], operation_id='delete-http-project').json()
        body = dict(directories=['Projects/Studio'], expected_revision=deleted['revision'], operation_id='purge-http-project')
        self.assertEqual(self.post('workspace/trash', **body).status_code, 400)
        self.assertEqual(self.post('workspace/trash', **body, confirm=True, root='/wrong').status_code, 409)
        self.assertEqual(self.post('workspace/trash', **{**body, 'expected_revision': state['revision']}, confirm=True).status_code, 409)
        purged = self.post('workspace/trash', **body, confirm=True)
        self.assertEqual(purged.status_code, 200, purged.text)
        self.assertEqual(purged.json()['deleted'], 1)
        self.assertNotIn('Projects/Studio', purged.json()['meta'])

    def test_ai_design_references_and_attached_project_write_scope(self):
        value = self.create()
        ai = self.app.state.ai
        reference = {'kind': 'design', 'root': str(self.root), 'path': 'Projects/Studio/Design/studio/project.json',
                     'label': 'Studio', 'text': 'Selected design elements'}
        refs, contexts = ai.validate_contexts({'references': [reference]})
        self.assertEqual(refs[0]['directory'], 'Projects/Studio')
        self.assertEqual(contexts, {})
        with self.assertRaises(ValueError):
            ai.validate_contexts({'references': [{**reference, 'path': 'Projects/Studio/private.json'}]})
        topic = ai.create('codex')
        private = ai.conversation(topic['id'], private=True)
        ai.execute('INSERT INTO turns(id,conversation_id,request_id,payload_hash,question,references_json,contexts_json,state,created) VALUES(?,?,?,?,?,?,?,?,?)',
                   ('design-turn', topic['id'], 'design-request', 'hash', 'Edit design', json.dumps(refs), '{}', 'running', time.time()))
        ai.active_turns[topic['id']] = 'design-turn'
        def call(arguments):
            response = self.client.post('/ai-mcp', headers={'Authorization': 'Bearer ' + private['capability'],
                'Accept': 'application/json, text/event-stream'}, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                'params': {'name': 'design_operations', 'arguments': arguments}})
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()['result']
        arguments = {'directory': 'Projects/Studio', 'expected_revision': value['revision'], 'operation_id': 'internal-ai-edit',
                     'workspace_revision': self.config.data['revision'], 'commands': [{'type': 'page.update',
                        'page_id': value['document']['pages'][0]['id'], 'patch': {'name': 'AI applied'}}]}
        result = call(arguments)
        self.assertFalse(result.get('isError'), result)
        denied = call({**arguments, 'directory': 'Projects/Other'})
        self.assertTrue(denied.get('isError'), denied)


if __name__ == '__main__':
    unittest.main()
