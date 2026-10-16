"""The dev bridge keeps the workspace origin and API authentication intact."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.responses import Response
from vault_rag.dev_frontend import DevFrontend
from vault_rag.knowledge import Runtime
from vault_rag.local_state import LocalConfig
from vault_rag.web_server import create_app


class DevFrontendTests(unittest.TestCase):
    def test_only_explicit_loopback_origin(self):
        for origin in ['https://127.0.0.1:5173', 'http://example.com:5173',
                       'http://localhost:5173', 'http://127.0.0.1:5173/path',
                       'http://user@127.0.0.1:5173', 'http://127.0.0.1:5173?q=1']:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                DevFrontend(origin)

    def test_dev_assets_keep_api_and_project_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            config = LocalConfig(Path(directory))
            runtime = Runtime(config)
            app = create_app(config, runtime, start_background=False, dev_server='http://127.0.0.1:5173')
            origin = app.state.websites.ui_origin
            async def frontend(_self, path, query=''):
                return Response('vite:' + path + '?' + query, media_type='text/html')
            with patch.object(DevFrontend, 'response', frontend), TestClient(app, base_url=origin) as client:
                root = client.get('/')
                self.assertEqual(root.status_code, 200)
                self.assertIn('vite:/?', root.text)
                self.assertIn('vault_session', root.cookies)
                self.assertIn('ws://127.0.0.1:5173', root.headers['content-security-policy'])
                self.assertEqual(client.get('/src/main.tsx?t=123').text, 'vite:/src/main.tsx?t=123')
                self.assertEqual(client.get('/@vite/client').status_code, 200)
                self.assertEqual(client.get('/api/session').json()['ui_url'], origin + '/')
                self.assertEqual(client.post('/api/config', json={}).status_code, 403)
                client.cookies.clear()
                self.assertEqual(client.get('/api/session').status_code, 401)
                self.assertEqual(client.post('/api/config', json={}).status_code, 401)
                self.assertEqual(client.get('/src/main.tsx', headers={'Origin': 'http://evil.example'}).status_code, 403)
                self.assertEqual(client.get('/src/main.tsx', headers={'Host': 'evil.example'}).status_code, 403)
                project_host = 'p-' + 'b' * 32 + '.' + app.state.websites.ui_host.split('.', 1)[1]
                result = client.get('/src/main.tsx', headers={'Host': project_host + ':18080'})
                self.assertNotIn('vite:', result.text)

    def test_production_ignores_dev_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            config = LocalConfig(Path(directory))
            static = Path(directory) / 'static'; static.mkdir()
            (static / 'index.html').write_text('production', encoding='utf-8')
            with patch.dict('os.environ', {'LEAFLOOM_DEV_SERVER': 'http://127.0.0.1:5173'}):
                app = create_app(config, Runtime(config), start_background=False, static_dir=static)
            with TestClient(app, base_url=app.state.websites.ui_origin) as client:
                response = client.get('/')
                self.assertEqual(response.text, 'production')
                self.assertNotIn('ws://', response.headers['content-security-policy'])
                self.assertNotIn("script-src 'self' 'unsafe-inline'", response.headers['content-security-policy'])
                self.assertEqual(client.get('/@vite/client').status_code, 404)


if __name__ == '__main__':
    unittest.main()
