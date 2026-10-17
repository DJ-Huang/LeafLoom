"""Explicit browser development keeps default origins and access boundaries."""
import argparse
import html
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.responses import Response
from vault_rag.dev_frontend import DevFrontend
from vault_rag.knowledge import Runtime
from vault_rag.local_state import LocalConfig
from vault_rag.web_server import create_app

spec = importlib.util.spec_from_file_location('dev_browser', Path(__file__).parents[1] / 'scripts' / 'dev-browser.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class BrowserLauncherTests(unittest.TestCase):
    def test_home_required_and_ports_validated(self):
        for value in ('0', '1023', '65536', 'invalid'):
            with self.assertRaises(argparse.ArgumentTypeError):launcher.port_number(value)
        self.assertEqual(launcher.port_number('36229'), 36229)
        with self.assertRaises(SystemExit), patch('sys.stderr'):
            launcher.parser().parse_args([])

    def test_fresh_state_reused_without_rewriting_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / 'browser'
            config = launcher.prepare_config(home, 36229, loopback_ui=True)
            self.assertEqual(config.data['port'], 36229)
            self.assertIsNone(config.data['root'])
            self.assertEqual(config.data['include_roots'], [])
            original = config.path.read_bytes()
            launcher.prepare_config(home, 36229, loopback_ui=True)
            self.assertEqual(config.path.read_bytes(), original)
            self.assertEqual(json.loads((home / launcher.MARKER).read_text())['ui'], 'localhost')
            for port, mode in [(36230, True), (36229, False)]:
                with self.assertRaisesRegex(ValueError, 'different port or UI mode'):
                    launcher.prepare_config(home, port, loopback_ui=mode)
            self.assertEqual(config.path.read_bytes(), original)

    def test_refuses_unmarked_state_and_invalid_upstream_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / 'existing'; home.mkdir()
            original = b'leave me unchanged'
            (home / 'config.json').write_bytes(original)
            with self.assertRaisesRegex(ValueError, 'unmarked'):
                launcher.prepare_config(home, 36229)
            self.assertEqual((home / 'config.json').read_bytes(), original)
            self.assertEqual([p.name for p in home.iterdir()], ['config.json'])
            for upstream in ['http://localhost:5173', 'https://127.0.0.1:5173', 'http://evil.example:5173', 'http://127.0.0.1:36229']:
                fresh = Path(directory) / 'fresh'
                with self.assertRaises(ValueError):
                    launcher.prepare_config(fresh, 36229, dev_server=upstream)
                self.assertFalse(fresh.exists())

    def test_loopback_requires_explicit_dev_before_state_creation(self):
        with patch('vault_rag.web_server.LocalConfig') as config:
            with self.assertRaisesRegex(ValueError, 'explicit development frontend'):
                create_app(dev_ui_loopback=True)
            config.assert_not_called()
        with patch('vault_rag.web_server.LocalConfig') as config:
            with self.assertRaises(ValueError):
                create_app(dev_server='http://evil.example:5173', dev_ui_loopback=True)
            config.assert_not_called()

    def test_launcher_uses_real_runtime_and_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / 'browser'
            with patch('vault_rag.web_server.create_app') as factory, patch('vault_rag.web_server.create_server') as server, patch('builtins.print'):
                launcher.main(['--home', str(home), '--loopback-ui'])
                args, kwargs = factory.call_args
                self.assertIsInstance(args[0], LocalConfig)
                self.assertEqual(kwargs, {'dev_server': 'http://127.0.0.1:5173', 'dev_ui_loopback': True})
                self.assertNotIn('start_background', kwargs)
                server.return_value.run.assert_called_once()


class BrowserOriginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.root = self.home / 'notes'; self.root.mkdir()
        site = self.root / 'site'; site.mkdir()
        (site / 'index.html').write_bytes(b'<h1>original fictional project</h1>')
        (self.root / 'note.md').write_text('# Fictional note\n')
        self.config = LocalConfig(self.home / 'state')
        self.config.save({'root': str(self.root), 'port': 36229})
        self.runtime = Runtime(self.config)
        self.runtime.catalog.scan()
        self.app = create_app(self.config, self.runtime, start_background=False,
                              dev_server='http://127.0.0.1:5173', dev_ui_loopback=True)
        self.origin = 'http://localhost:36229'
        self.client = TestClient(self.app, base_url=self.origin)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def login(self):
        async def frontend(_self, path, query=''):
            return Response('vite:' + path, media_type='text/html')
        with patch.object(DevFrontend, 'response', frontend):
            result = self.client.get('/')
        self.assertEqual(result.text, 'vite:/')
        return result

    def test_cookie_auth_csrf_host_origin_and_file_api(self):
        self.assertEqual(self.client.get('/api/session').status_code, 401)
        response = self.login()
        cookie = response.headers['set-cookie'].lower()
        self.assertIn('httponly', cookie); self.assertIn('samesite=strict', cookie)
        self.assertNotIn('domain=', cookie)
        self.assertEqual(self.client.get('/api/session').json()['ui_url'], self.origin + '/')
        self.assertEqual(self.client.get('/api/file?path=note.md').json()['text'], '# Fictional note\n')
        self.assertEqual(self.client.post('/api/activity', json={}).status_code, 403)
        self.assertEqual(self.client.post('/api/activity', json={}, headers={'X-Vault-CSRF': 'bad'}).status_code, 403)
        self.assertEqual(self.client.post('/api/activity', json={}, headers={'X-Vault-CSRF': self.app.state.csrf}).status_code, 200)
        self.assertEqual(self.client.get('/api/session', headers={'Host': 'evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/session', headers={'Origin': 'http://evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/session', headers={'Origin': 'null'}).status_code, 403)
        old_host = 'app' + self.app.state.websites.suffix
        self.assertEqual(self.client.get(f'http://{old_host}:36229/').status_code, 403)
        csp = response.headers['content-security-policy']
        for directive in ["default-src 'self'", "object-src 'none'", "frame-ancestors 'self'", 'ws://127.0.0.1:5173']:
            self.assertIn(directive, csp)

    def test_saved_and_draft_projects_never_reach_management(self):
        self.login()
        headers = {'X-Vault-CSRF': self.app.state.csrf}
        project = self.client.post('/api/html-projects', headers=headers, json={
            'root': str(self.root), 'directory': 'site', 'entry': 'site/index.html'}).json()
        for draft in (None, '<h1>unsaved fictional draft</h1>'):
            data = {'root': str(self.root), 'path': 'site/index.html', 'project_id': project['id']}
            if draft is not None:data['draft'] = draft
            session = self.client.post('/api/html-sessions', headers=headers, json=data).json()
            self.assertTrue(session['origin'].startswith('http://' + ('p-' if draft is None else 'd-')))
            self.assertIn(self.app.state.websites.suffix, session['origin'])
            self.assertNotEqual(session['origin'], self.origin)
            self.assertEqual(self.client.get(session['url']).status_code, 200)
            page = self.client.get(session['origin'] + '/index.html')
            self.assertEqual(page.text, draft or '<h1>original fictional project</h1>')
            self.assertIn(self.origin, page.headers['content-security-policy'])
            forged = dict(headers, Cookie='; '.join(f'{c.name}={c.value}' for c in self.client.cookies.jar))
            for path in ['/api/session', '/api/tree', '/mcp', '/ai-mcp', '/src/main.tsx']:
                self.assertEqual(self.client.get(session['origin'] + path, headers=forged).status_code, 404, path)
            self.assertEqual(self.client.post(session['origin'] + '/api/activity', headers=forged, json={}).status_code, 405)
            self.assertEqual(self.client.get('/api/session', headers={'Origin': session['origin']}).status_code, 403)

    def test_ip_entry_migrates_once_to_literal_localhost(self):
        legacy = 'http://127.0.0.1:36229'
        page = self.client.get(legacy + '/')
        settings = json.loads(html.unescape(re.search('data-settings="([^"]+)"', page.text).group(1)))
        self.assertEqual(settings['target'], self.origin)
        payload = {'local': [['draft:fictional', 'keep this draft']], 'session': [], 'returnTo': '?note=note.md'}
        path = '/__leafloom__/transfer?nonce=' + settings['nonce']
        sent = self.client.post(legacy + path, json=payload, headers={'Origin': legacy})
        self.assertEqual(sent.status_code, 200)
        self.assertTrue(sent.json()['url'].startswith(self.origin + '/__leafloom__/migrate?ticket='))
        ticket = sent.json()['url'].split('ticket=')[1]
        transfer = self.origin + '/__leafloom__/transfer?ticket=' + ticket
        self.assertEqual(self.client.get(transfer).json()['local'], payload['local'])
        self.assertEqual(self.client.delete(transfer).status_code, 200)
        self.assertEqual(self.client.get(transfer).status_code, 400)
        self.assertEqual(self.client.post(legacy + path, json=payload, headers={'Origin': legacy}).status_code, 400)

    def test_production_and_desktop_dev_defaults_keep_named_origin(self):
        for dev_server in (None, 'http://127.0.0.1:5173'):
            app = create_app(self.config, Runtime(self.config), start_background=False, dev_server=dev_server)
            self.assertEqual(app.state.websites.ui_host, 'app' + app.state.websites.suffix)
            self.assertTrue(app.state.websites.ui_origin.startswith('http://app.'))


if __name__ == '__main__':unittest.main()
