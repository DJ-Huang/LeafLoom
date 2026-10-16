"""Unit and integration tests for LeafLoom Design Studio (HTTP APIs, HTML viewer routes, and MCP tools)."""
import json
from pathlib import Path
import tempfile
import unittest

from starlette.testclient import TestClient
from vault_rag.knowledge import Runtime
from vault_rag.local_state import LocalConfig
from vault_rag.web_server import create_app


class DesignStudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.root = (self.home / 'vault').resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = LocalConfig(self.home / 'state')
        self.config.save({
            'root': str(self.root),
            'include_roots': ['Projects'],
            'mcp_scopes': {
                'read_workspace': True,
                'write_workspace': True,
            },
        })
        (self.root / 'Projects' / 'Games').mkdir(parents=True, exist_ok=True)
        self.static = self.home / 'static'
        self.static.mkdir()
        (self.static / 'index.html').write_text('<html>shared app</html>', encoding='utf-8')
        self.runtime = Runtime(self.config)
        self.app = create_app(self.config, self.runtime, start_background=False, static_dir=self.static)
        self.client = TestClient(self.app, base_url='http://127.0.0.1:18080', client=('127.0.0.1', 12345))
        self.client.__enter__()
        self.token = (self.config.directory / 'auth-token').read_text().strip()
        self.auth = {'Authorization': 'Bearer ' + self.token}
        mcp_cfg = self.client.post('/api/mcp-access', headers=self.auth, json={'kind': 'local', 'enabled': True, 'write': True})
        self.assertEqual(mcp_cfg.status_code, 200, mcp_cfg.text)
        self.mcp_token = mcp_cfg.json()['token']
        self.mcp_auth = {
            'Authorization': 'Bearer ' + self.mcp_token,
            'Accept': 'application/json, text/event-stream',
        }

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.runtime.stop()
        self.temp.cleanup()

    def mcp_call(self, name: str, arguments: dict):
        res = self.client.post(
            '/mcp',
            headers=self.mcp_auth,
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'tools/call',
                'params': {'name': name, 'arguments': arguments},
            },
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()['result']
        self.assertFalse(body.get('isError'), body)
        return body.get('structuredContent') or json.loads(body['content'][0]['text'])

    def test_create_list_upsert_transform_and_check_via_http(self):
        # 1. Initially empty
        res = self.client.get('/api/design/projects', headers=self.auth)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()['projects'], [])

        # 2. Create a design project inside Projects/Games/StarCraftUI
        create_res = self.client.post(
            '/api/design/projects',
            headers=self.auth,
            json={
                'directory': 'Projects/Games/StarCraftUI',
                'name': '星际工坊 UI',
                'preset': 'game-landscape',
            },
        )
        self.assertEqual(create_res.status_code, 200, create_res.text)
        proj = create_res.json()['project']
        self.assertEqual(proj['directory'], 'Projects/Games/StarCraftUI')
        self.assertEqual(proj['width'], 1560)
        self.assertEqual(proj['height'], 720)
        self.assertEqual(proj['board_count'], 3)
        self.assertIsNotNone(proj['html_project_id'])

        proj_dir = self.root / 'Projects/Games/StarCraftUI'
        self.assertTrue((proj_dir / 'Design/project-spec.json').is_file())
        self.assertTrue((proj_dir / 'Design/Assets/manifest.json').is_file())
        self.assertTrue((proj_dir / 'Design/UI/Site/ui-gallery.html').is_file())
        self.assertTrue((proj_dir / 'Design/UI/Site/screen.html').is_file())
        self.assertTrue((proj_dir / 'README.md').is_file())

        # 3. Verify HtmlProjectServer serves the project and built-in layer_review engine
        sess_res = self.client.post(
            '/api/html-sessions',
            headers=self.auth,
            json={
                'root': str(self.root),
                'path': proj['entry'],
                'project_id': proj['html_project_id'],
            },
        )
        self.assertEqual(sess_res.status_code, 200, sess_res.text)
        sess = sess_res.json()
        opened = self.client.get(sess['url'])
        self.assertEqual(opened.status_code, 200)
        origin = sess['origin']
        js_res = self.client.get(origin + '/__leafloom__/design/layer_review.js')
        self.assertEqual(js_res.status_code, 200)
        self.assertIn('GameDesignLayers', js_res.text)
        css_res = self.client.get(origin + '/__leafloom__/design/layer_review.css')
        self.assertEqual(css_res.status_code, 200)
        self.assertIn('.gdl-transform-grid', css_res.text)

        # 4. Add a new screen artboard
        screen_res = self.client.post(
            '/api/design/projects/screens',
            headers=self.auth,
            json={
                'directory': 'Projects/Games/StarCraftUI',
                'screen_id': 'inventory',
                'name': '星际背包页',
                'group': '核心系统',
                'caption': '装备槽位与合成强化面板',
                'html': '<div data-layer-id="inventory/grid" data-layer-name="背包网格" data-layer-type="group">Grid</div>',
                'css': '.inventory { background: #101820; }',
            },
        )
        self.assertEqual(screen_res.status_code, 200, screen_res.text)
        self.assertEqual(screen_res.json()['project']['board_count'], 4)

        # 5. Save and merge layer transforms
        t_res = self.client.post(
            '/api/design/projects/transforms',
            headers=self.auth,
            json={
                'directory': 'Projects/Games/StarCraftUI',
                'board_id': 'home',
                'transforms': {
                    'home/title': {'tx': 24, 'ty': -12, 'rotate': 5, 'text': '星际指挥中心'},
                    'home/primary-btn': {'scaleX': 1.2, 'scaleY': 1.2},
                },
            },
        )
        self.assertEqual(t_res.status_code, 200, t_res.text)
        self.assertEqual(t_res.json()['layer_count'], 2)

        get_t = self.client.get(
            '/api/design/projects/transforms',
            params={'directory': 'Projects/Games/StarCraftUI', 'board_id': 'home'},
            headers=self.auth,
        )
        self.assertEqual(get_t.status_code, 200)
        self.assertEqual(get_t.json()['transforms']['home/title']['tx'], 24)
        self.assertEqual(get_t.json()['transforms']['home/title']['text'], '星际指挥中心')

        # 6. Check project contract
        check_res = self.client.post(
            '/api/design/projects/check',
            headers=self.auth,
            json={'directory': 'Projects/Games/StarCraftUI'},
        )
        self.assertEqual(check_res.status_code, 200, check_res.text)
        self.assertTrue(check_res.json()['ok'])
        self.assertEqual(check_res.json()['errors'], [])

    def test_mcp_design_tools_end_to_end(self):
        ws = self.config.data['revision']
        created = self.mcp_call(
            'design_create_project',
            {
                'directory': 'Projects/Games/MCPDesign',
                'name': 'MCP 协同设计项目',
                'workspace_revision': ws,
                'preset': 'mobile-portrait',
            },
        )
        self.assertTrue(created['ok'])
        self.assertEqual(created['project']['directory'], 'Projects/Games/MCPDesign')

        listed = self.mcp_call('design_list_projects', {'folder': 'Projects'})
        self.assertEqual(len(listed['projects']), 1)

        upserted = self.mcp_call(
            'design_upsert_screen',
            {
                'directory': 'Projects/Games/MCPDesign',
                'screen_id': 'shop',
                'name': '商店画板',
                'workspace_revision': created['workspace_revision'],
                'caption': '每日精选与礼包列表',
            },
        )
        self.assertTrue(upserted['ok'])
        self.assertEqual(upserted['project']['board_count'], 4)

        updated_layers = self.mcp_call(
            'design_update_layers',
            {
                'directory': 'Projects/Games/MCPDesign',
                'board_id': 'shop',
                'workspace_revision': upserted['workspace_revision'],
                'layers': {
                    'shop/hero-card': {'tx': 10, 'ty': 20, 'opacity': 0.9},
                },
            },
        )
        self.assertTrue(updated_layers['ok'])
        self.assertEqual(updated_layers['layer_count'], 1)

        inspected = self.mcp_call(
            'design_get_project',
            {'directory': 'Projects/Games/MCPDesign', 'board_id': 'shop'},
        )
        self.assertEqual(inspected['board_transforms']['shop/hero-card']['tx'], 10)

        checked = self.mcp_call(
            'design_check_project',
            {'directory': 'Projects/Games/MCPDesign'},
        )
        self.assertTrue(checked['ok'])


if __name__ == '__main__':
    unittest.main()
