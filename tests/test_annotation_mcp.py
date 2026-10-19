"""MCP authorization and annotations end-to-end, using disposable fictional notes."""
import json
from pathlib import Path

from starlette.testclient import TestClient

from vault_rag.local_state import LocalConfig
from vault_rag.knowledge import Runtime
from vault_rag.web_server import create_app


def test_annotation_mcp_permissions_and_threads(tmp_path):
    vault = tmp_path / 'vault'
    vault.mkdir()
    note = vault / 'sample.md'
    note.write_text('Original Markdown source.\n', encoding='utf-8')
    config = LocalConfig(tmp_path / 'config')
    config.save({'root': str(vault), 'include_roots': ['']})
    runtime = Runtime(config)
    app = create_app(config, runtime, start_background=False)

    with TestClient(app, base_url='http://127.0.0.1:18080', client=('127.0.0.1', 12345)) as client:
        legacy = {'Authorization': 'Bearer ' + (config.directory / 'auth-token').read_text().strip()}

        def credential(write):
            result = client.post('/api/mcp-access', headers=legacy,
                                 json={'kind': 'local', 'enabled': True, 'write': write})
            assert result.status_code == 200, result.text
            return result.json().get('token')

        token = credential(False)

        def request(method, params, credential_value=None):
            response = client.post('/mcp',
                                   headers={
                                       'Authorization': 'Bearer ' + (credential_value or token),
                                       'Accept': 'application/json, text/event-stream',
                                   },
                                   json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
            assert response.status_code == 200, response.text
            return response.json()['result']

        def tool(name, args, credential_value=None):
            result = request('tools/call', {'name': name, 'arguments': args}, credential_value)
            return json.loads(result['content'][0]['text'])

        catalogue = request('tools/list', {})['tools']
        by_name = {tool['name']: tool for tool in catalogue}
        expected = {
            'vault_list_annotations', 'vault_add_annotation',
            'vault_reply_annotation', 'vault_set_annotation_status',
        }
        assert expected.issubset(by_name)
        assert by_name['vault_list_annotations']['annotations']['readOnlyHint']
        assert not by_name['vault_add_annotation']['annotations']['readOnlyHint']

        empty = tool('vault_list_annotations', {'path': 'sample.md'})
        assert empty['annotations'] == []
        assert not (vault / '.vault-rag' / 'annotations.sqlite').exists()

        denied = tool('vault_add_annotation', {
            'path': 'sample.md', 'workspace_revision': config.data['revision'],
            'kind': 'comment', 'content': 'Needs review',
        })
        assert denied['error_code'] == 'permission_denied'
        assert note.read_text() == 'Original Markdown source.\n'

        token = credential(True) or token
        result = tool('vault_add_annotation', {
            'path': 'sample.md', 'workspace_revision': config.data['revision'],
            'kind': 'comment', 'content': 'First comment',
        })
        assert result['ok'] and result['id']
        thread_id = result['id']

        reply = tool('vault_reply_annotation', {
            'path': 'sample.md', 'annotation_id': thread_id,
            'workspace_revision': config.data['revision'], 'content': 'First reply',
        })
        assert reply['ok']

        annotations = tool('vault_list_annotations', {'path': 'sample.md'})
        assert len(annotations['annotations']) == 1
        item = annotations['annotations'][0]
        assert len(item['messages']) == 2
        assert item['messages'][1]['content'] == 'First reply'

        resolved = tool('vault_set_annotation_status', {
            'path': 'sample.md', 'annotation_id': thread_id,
            'revision': item['revision'], 'workspace_revision': config.data['revision'],
            'status': 'resolved',
        })
        assert resolved['ok']
        changed = tool('vault_list_annotations', {'path': 'sample.md'})['annotations'][0]
        assert changed['status'] == 'resolved'
        assert note.read_text() == 'Original Markdown source.\n'
    runtime.stop()
