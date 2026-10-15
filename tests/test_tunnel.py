"""Authentication boundary and owned runtime lifecycle; no real keys or remote calls."""
from __future__ import annotations
import json
import http.server
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient
from vault_rag.local_state import LocalConfig
from vault_rag.knowledge import Runtime
from vault_rag.web_server import create_app, create_server
from vault_rag.tunnel import TunnelManager, failure_code, request

INIT = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
    'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}}
HEADERS = {'Accept': 'application/json, text/event-stream'}


class McpSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.config = LocalConfig(self.home / 'state')
        self.runtime = Runtime(self.config)
        self.app = create_app(self.config, self.runtime, start_background=False)

    def tearDown(self):
        self.runtime.stop()
        self.temp.cleanup()

    def client(self, host='127.0.0.1'):
        return TestClient(self.app, base_url='http://127.0.0.1:18080', client=(host, 12345))

    def test_loopback_legacy_handshake_and_readonly_call_without_token(self):
        with self.client() as client:
            self.assertIn('result', client.post('/mcp', json=INIT, headers=HEADERS).json())
            self.assertEqual(client.post('/mcp', json={'jsonrpc': '2.0', 'method': 'notifications/initialized'}, headers=HEADERS).status_code, 202)
            tools = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}, headers=HEADERS).json()
            self.assertIn('vault_index_status', [t['name'] for t in tools['result']['tools']])
            result = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'vault_index_status', 'arguments': {}}}, headers=HEADERS).json()
            self.assertFalse(result['result'].get('isError', False))
            self.assertNotIn('error', json.loads(result['result']['content'][0]['text']))

    def test_peer_address_is_required_and_existing_tokens_remain_compatible(self):
        with self.client('203.0.113.5') as client:
            spoof = {**HEADERS, 'X-Forwarded-For': '127.0.0.1', 'Forwarded': 'for=127.0.0.1'}
            self.assertEqual(client.post('/mcp', json=INIT, headers=spoof).status_code, 401)
            self.assertEqual(client.post('/mcp/', json=INIT, headers=spoof).status_code, 401)
            client.cookies.set('vault_session', (self.config.directory / 'auth-token').read_text().strip())
            self.assertEqual(client.post('/mcp', json=INIT, headers=spoof).status_code, 401)
            bearer = 'Bearer ' + (self.config.directory / 'auth-token').read_text().strip()
            self.assertEqual(client.post('/mcp', json=INIT, headers={**HEADERS, 'Authorization': bearer}).status_code, 200)
        self.assertFalse(create_server(self.app, port=18080, proxy_headers=True).config.proxy_headers)

    def test_host_origin_api_and_ai_security_are_preserved(self):
        with self.client() as client:
            for header in ({'Host': 'evil.example'}, {'Origin': 'https://evil.example'}):
                self.assertEqual(client.post('/mcp', json=INIT, headers={**HEADERS, **header}).status_code, 403)
            self.assertEqual(client.get('/api/status').status_code, 401)
            token = (self.config.directory / 'auth-token').read_text().strip()
            client.cookies.set('vault_session', token)
            self.assertEqual(client.get('/api/status').status_code, 200)
            self.assertEqual(client.post('/api/create', json={'path': 'blocked.md'}).status_code, 403)
            self.assertEqual(client.post('/ai-mcp', json=INIT, headers=HEADERS).status_code, 401)
    def test_ipv6_loopback_is_recognized(self):
        with self.client('::1') as client:
            self.assertEqual(client.post('/mcp', json=INIT, headers=HEADERS).status_code, 200)


RUNNER = r'''
import http.server,json,sys
from pathlib import Path
class Handler(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200);self.end_headers()
  self.wfile.write(json.dumps({'components':{'control-plane':{'status':'ok'}}}).encode())
 def log_message(self,*args):pass
server=http.server.HTTPServer(('127.0.0.1',0),Handler)
Path(sys.argv[1]).write_text('http://127.0.0.1:'+str(server.server_port))
print('OAuth discovery failed: 404 metadata missing resource',flush=True)
server.serve_forever()
'''


class TunnelLifecycleTests(unittest.TestCase):
    def wait(self, predicate):
        deadline = time.monotonic() + 8
        while not predicate() and time.monotonic() < deadline: time.sleep(.03)
        self.assertTrue(predicate())

    def test_process_reconfiguration_disconnect_and_secret_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            states, launches, children = [], [], []
            popen = subprocess.Popen
            def launch(args, **kwargs):
                launches.append((args, dict(kwargs['env'])))
                health = args[args.index('--health.url-file') + 1]
                process = popen([sys.executable, '-u', '-c', RUNNER, health], **kwargs)
                children.append(process)
                return process
            def local_request(url, payload=None):
                if payload: return 200, {'result': {}}
                return request(url)
            with patch('vault_rag.tunnel.subprocess.Popen', side_effect=launch), patch('vault_rag.tunnel.request', side_effect=local_request), patch.dict(os.environ, {'MCP_EXTRA_HEADERS': 'Authorization: inherited-secret', 'OPENAI_API_KEY': 'unrelated-key'}):
                manager = TunnelManager(temp, 19234, lambda kind, **value: states.append(value))
                try:
                    config = {'enabled': True, 'binary': sys.executable, 'tunnelId': 'tunnel_'+'a'*32, 'apiKey': 'private-runtime-key'}
                    manager.configure(config)
                    self.wait(lambda: any(s['state'] == 'ready' for s in states))
                    self.assertEqual(launches[0][1]['CONTROL_PLANE_API_KEY'], config['apiKey'])
                    self.assertNotIn('MCP_EXTRA_HEADERS', launches[0][1])
                    self.assertNotIn('OPENAI_API_KEY', launches[0][1])
                    self.assertNotIn(config['apiKey'], repr(launches[0][0]))
                    self.assertNotIn(config['apiKey'], repr(states))
                    old = manager.process
                    manager.configure(config)
                    self.wait(lambda: len(launches) == 2)
                    self.assertIsNotNone(old.poll())
                    manager.configure({'enabled': False})
                    self.wait(lambda: states[-1]['state'] == 'disabled')
                    self.assertIsNone(manager.process)
                finally: manager.close()
                self.assertFalse(manager.thread.is_alive())
                self.assertTrue(all(child.poll() is not None for child in children))

    def test_auth_error_stops_and_requires_explicit_reconnect(self):
        with tempfile.TemporaryDirectory() as temp:
            states, children = [], []
            popen = subprocess.Popen
            def launch(args, **kwargs):
                process = popen([sys.executable, '-u', '-c', "import time;print('control-plane poll: 401 Unauthorized private-runtime-key',flush=True);time.sleep(60)"], **kwargs)
                children.append(process)
                return process
            with patch('vault_rag.tunnel.subprocess.Popen', side_effect=launch), patch('vault_rag.tunnel.request', return_value=(200, {'result': {}})):
                manager = TunnelManager(temp, 19234, lambda kind, **value: states.append(value))
                try:
                    manager.configure({'enabled': True, 'binary': sys.executable, 'tunnelId': 'tunnel_'+'a'*32, 'apiKey': 'private-runtime-key'})
                    self.wait(lambda: any(s.get('error') == 'tunnel.error.key' for s in states))
                    self.assertEqual(states[-1]['state'], 'failed')
                    self.assertIsNotNone(children[0].poll())
                    self.assertNotIn('private-runtime-key', repr(states))
                    self.assertEqual(len(children), 1)
                finally: manager.close()

    def test_network_retries_and_missing_binary_is_terminal(self):
        self.assertEqual(failure_code({'error': 'HTTP 403 Forbidden'}), 'tunnel.error.permission')
        self.assertEqual(failure_code({'id': 'tunnel_a401abc404'}), '')
        with tempfile.TemporaryDirectory() as temp:
            states = []
            with patch('vault_rag.tunnel.request', side_effect=OSError('private-runtime-key')):
                manager = TunnelManager(temp, 19234, lambda kind, **value: states.append(value))
                try:
                    manager.configure({'enabled': True, 'binary': sys.executable, 'tunnelId': 'tunnel_'+'a'*32, 'apiKey': 'private-runtime-key'})
                    self.wait(lambda: any(s.get('error') == 'tunnel.error.mcp' for s in states))
                    self.assertEqual(states[-1]['state'], 'reconnecting')
                    manager.configure({'enabled': True, 'binary': str(Path(temp)/'missing'), 'tunnelId': 'tunnel_'+'a'*32, 'apiKey': 'private-runtime-key'})
                    self.wait(lambda: states[-1].get('error') == 'tunnel.error.binary')
                    self.assertEqual(states[-1]['state'], 'failed')
                finally: manager.close()

    def test_official_bundled_runtime_against_local_control_plane(self):
        import platform as native_platform
        if not (sys.platform == 'win32' and native_platform.machine().lower() in ('amd64', 'x86_64') or sys.platform == 'darwin' and native_platform.machine().lower() == 'arm64'):
            self.skipTest('Official desktop runtime requires Windows x64 or macOS arm64')
        platform = 'windows-x64' if sys.platform == 'win32' else 'macos-arm64'
        binary = Path(__file__).resolve().parents[1] / 'desktop/resources/tunnel' / platform / ('tunnel-client-runtime.exe' if sys.platform == 'win32' else 'tunnel-client-runtime')
        if not binary.is_file(): self.skipTest('Build the native Tunnel payload first')
        class LocalServer(http.server.BaseHTTPRequestHandler):
            polls = 0
            def log_message(self, *args): pass
            def do_GET(self):
                if '/v1/tunnels/' in self.path and '/poll' in self.path:
                    LocalServer.polls += 1
                    time.sleep(.05)
                    self.send_response(204); self.end_headers()
                else:
                    self.send_response(404); self.end_headers(); self.wfile.write(b'{"detail":"Not Found"}')
            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                if not raw:
                    self.send_response(400); self.end_headers(); return
                payload = json.loads(raw)
                method = payload.get('method')
                if method == 'notifications/initialized':
                    self.send_response(202); self.end_headers(); return
                result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'fixture', 'version': '1'}} if method == 'initialize' else {'tools': []}
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
                self.wfile.write(json.dumps({'jsonrpc': '2.0', 'id': payload.get('id'), 'result': result}).encode())
        class FixtureServer(http.server.ThreadingHTTPServer):
            def handle_error(self, *args):
                if not isinstance(sys.exception(), (ConnectionError, BrokenPipeError)): super().handle_error(*args)
        server = FixtureServer(('127.0.0.1', 0), LocalServer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as temp:
            states = []
            popen = subprocess.Popen
            def launch(args, **kwargs):
                return popen([*args, '--control-plane.base-url', f'http://127.0.0.1:{server.server_port}'], **kwargs)
            try:
                with patch('vault_rag.tunnel.subprocess.Popen', side_effect=launch):
                    manager = TunnelManager(temp, server.server_port, lambda kind, **value: states.append(value))
                    try:
                        manager.configure({'enabled': True, 'binary': str(binary), 'tunnelId': 'tunnel_'+'a'*32, 'apiKey': 'sk-test-local-fixture-only'})
                        self.wait(lambda: any(s['state'] == 'ready' for s in states))
                        self.assertGreater(LocalServer.polls, 0)
                        process = manager.process
                    finally: manager.close()
                    self.assertIsNotNone(process.poll())
            finally:
                server.shutdown(); server.server_close()


if __name__ == '__main__': unittest.main()
