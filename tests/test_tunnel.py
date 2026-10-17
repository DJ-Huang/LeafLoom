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
from vault_rag.mcp_access import TUNNEL_AUTH_HEADER

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

    def test_tunnel_identity_ignores_chat_bearers_and_checks_live_permissions(self):
        access = self.app.state.mcp_access
        access.configure('tunnel', enabled=False, write=False, resource='workspace')
        access.configure('tunnel', enabled=True, write=False, resource='feishu')
        legacy = 'Bearer ' + (self.config.directory / 'auth-token').read_text().strip()
        proof = access.tunnel_authorization()
        status = {'jsonrpc': '2.0', 'id': 7, 'method': 'tools/call',
                  'params': {'name': 'vault_index_status', 'arguments': {}}}
        read = {'jsonrpc': '2.0', 'id': 8, 'method': 'tools/call',
                'params': {'name': 'feishu_cli_read', 'arguments': {'argv': ['base', '+url-resolve', '--url=https://example.feishu.cn/wiki/test']}}}
        with self.client() as client, patch.object(self.app.state.feishu, 'execute', return_value={'ok': True}) as adapter:
            # Different chats retain different connector bearers. Neither bearer
            # may override the private, authenticated runtime identity.
            for bearer in ('', legacy, 'Bearer stale-connector-token'):
                headers = {**HEADERS, TUNNEL_AUTH_HEADER: proof}
                if bearer: headers['Authorization'] = bearer
                result = client.post('/mcp', json=status, headers=headers).json()['result']['structuredContent']
                self.assertEqual(result['capabilities'], {'connection': 'tunnel', 'read_workspace': False,
                    'write_workspace': False, 'read_feishu': True, 'write_feishu': False, 'high_risk_feishu': False})
                self.assertTrue(client.post('/mcp', json=read, headers=headers).json()['result']['structuredContent']['ok'])
            self.assertEqual(adapter.call_count, 3)
            # A forged proof cannot downgrade to otherwise-valid legacy auth.
            headers = {**HEADERS, 'Authorization': legacy, TUNNEL_AUTH_HEADER: 'Bearer forged'}
            self.assertEqual(client.post('/mcp', json=status, headers=headers).status_code, 401)
            remote = self.client('203.0.113.5')
            self.assertEqual(remote.post('/mcp', json=status, headers={**HEADERS,
                TUNNEL_AUTH_HEADER: proof, 'X-Forwarded-For': '127.0.0.1'}).status_code, 401)
            # Retaining note access must not retain revoked Feishu access.
            access.configure('tunnel', enabled=True, write=False)
            access.configure('tunnel', enabled=False, write=False, resource='feishu')
            headers[TUNNEL_AUTH_HEADER] = proof
            self.assertEqual(client.post('/mcp', json=read, headers=headers).status_code, 401)
            headers[TUNNEL_AUTH_HEADER] = access.tunnel_authorization()
            denied = client.post('/mcp', json=read, headers=headers).json()['result']['structuredContent']
            self.assertEqual(denied['error_code'], 'permission_denied')
            self.assertEqual(denied['error_source'], 'leafloom_mcp')
            self.assertEqual(denied['connection'], 'tunnel')
            self.assertEqual(denied['resource'], 'feishu')
            self.assertEqual(client.get('/api/status', headers={TUNNEL_AUTH_HEADER: access.tunnel_authorization()}).status_code, 401)
            self.assertEqual(adapter.call_count, 3)


RUNNER = r'''
import http.server,json,socketserver,sys
from pathlib import Path
class Handler(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200);self.end_headers()
  self.wfile.write(json.dumps({'components':{'control-plane':{'status':'ok'}}}).encode())
 def log_message(self,*args):pass
class LoopbackServer(http.server.HTTPServer):
 def server_bind(self):
  # HTTPServer normally reverse-resolves 127.0.0.1 with getfqdn(). Hosted
  # macOS DNS can block that lookup past the lifecycle readiness deadline.
  # This fixture has a known loopback identity and must not depend on DNS.
  socketserver.TCPServer.server_bind(self)
  self.server_name='localhost'
  self.server_port=self.server_address[1]
server=LoopbackServer(('127.0.0.1',0),Handler)
Path(sys.argv[1]).write_text('http://127.0.0.1:'+str(server.server_port))
print('OAuth discovery failed: 404 metadata missing resource',flush=True)
server.serve_forever()
'''


class TunnelLifecycleTests(unittest.TestCase):
    def wait(self, predicate):
        deadline = time.monotonic() + 8
        while not predicate() and time.monotonic() < deadline: time.sleep(.03)
        self.assertTrue(predicate())

    def test_shared_home_allows_one_owner_and_quit_releases_it(self):
        with tempfile.TemporaryDirectory() as temp:
            children, managers = [], []
            popen = subprocess.Popen
            def launch(args, **kwargs):
                health = args[args.index('--health.url-file') + 1]
                child = popen([sys.executable, '-u', '-c', RUNNER, health], **kwargs)
                children.append(child)
                return child
            def local_request(url, payload=None, **kwargs):
                return (200, {'result': {}}) if payload else request(url)
            settings = {'enabled': True, 'binary': sys.executable, 'tunnelId': 'tunnel_'+'a'*32, 'apiKey': 'fictional-key'}
            with patch('vault_rag.tunnel.subprocess.Popen', side_effect=launch), patch('vault_rag.tunnel.request', side_effect=local_request):
                try:
                    first = TunnelManager(temp, 19234, lambda *a, **k: None); managers.append(first)
                    first.configure(settings); self.wait(lambda: first.last_state == ('ready', ''))
                    second = TunnelManager(temp, 19234, lambda *a, **k: None); managers.append(second)
                    second.configure(settings); self.wait(lambda: second.last_state == ('failed', 'tunnel.error.process'))
                    self.assertEqual(len(children), 1)
                    first.close(); self.assertIsNotNone(children[0].poll())
                    third = TunnelManager(temp, 19234, lambda *a, **k: None); managers.append(third)
                    third.configure(settings); self.wait(lambda: third.last_state == ('ready', ''))
                    self.assertEqual(len(children), 2)
                finally:
                    for manager in managers: manager.close()
                self.assertTrue(all(child.poll() is not None for child in children))

    @unittest.skipUnless(os.name == 'nt', 'Windows kill-on-close job validation')
    def test_abnormal_backend_exit_kills_its_owned_runtime(self):
        import ctypes
        from ctypes import wintypes
        code = "import subprocess,sys,time; from vault_rag.worker_lifetime import WorkerJob; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); job=WorkerJob(p); print(p.pid,flush=True); time.sleep(60)"
        owner = subprocess.Popen([sys.executable, '-u', '-c', code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        handle = None
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]; kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]; kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        try:
            child_pid = int(owner.stdout.readline())
            handle = kernel.OpenProcess(0x00100000, False, child_pid)
            self.assertTrue(handle)
            owner.kill(); owner.wait(timeout=5)
            self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0)
        finally:
            if owner.poll() is None: owner.kill(); owner.wait(timeout=5)
            if handle: kernel.CloseHandle(handle)
            owner.stdout.close(); owner.stderr.close()

    def test_workspace_discovery_and_calls_receive_private_revocable_credential(self):
        from vault_rag.mcp_access import McpAccess
        with tempfile.TemporaryDirectory() as temp:
            access = McpAccess(LocalConfig(Path(temp) / 'state'))
            access.configure('tunnel', enabled=True, write=True)
            launches, probes = [], []
            popen = subprocess.Popen
            def launch(args, **kwargs):
                launches.append((args, dict(kwargs['env'])))
                health = args[args.index('--health.url-file') + 1]
                return popen([sys.executable, '-u', '-c', RUNNER, health], **kwargs)
            def local_request(url, payload=None, *, headers=None):
                if payload:
                    probes.append(headers)
                    return 200, {'result': {}}
                return request(url)
            with patch('vault_rag.tunnel.subprocess.Popen', side_effect=launch), patch('vault_rag.tunnel.request', side_effect=local_request):
                manager = TunnelManager(temp, 19234, lambda *a, **k: None, mcp_access=access)
                try:
                    manager.configure({'enabled': True, 'binary': sys.executable,
                                       'tunnelId': 'tunnel_' + 'a' * 32, 'apiKey': 'fictional-control-key'})
                    self.wait(lambda: len(launches) == 1 and manager.last_state == ('ready', ''))
                    args, env = launches[0]
                    authorization = env['LEAFLOOM_TUNNEL_MCP_AUTHORIZATION']
                    self.assertEqual(probes[0], {TUNNEL_AUTH_HEADER: authorization})
                    self.assertEqual(access.principal(authorization, 'legacy'), 'tunnel')
                    for flag in ('--mcp.extra-headers', '--mcp.discovery-extra-headers'):
                        self.assertEqual(args[args.index(flag) + 1], f'{TUNNEL_AUTH_HEADER}: env:LEAFLOOM_TUNNEL_MCP_AUTHORIZATION')
                    self.assertNotIn(authorization, repr(args))
                    access.configure('tunnel', enabled=True, write=False)
                    with self.assertRaises(PermissionError):access.principal(authorization, 'legacy', loopback=True)
                    self.wait(lambda: len(launches) == 2 and manager.last_state == ('ready', ''))
                    manager.configure({'enabled': False})
                    self.wait(lambda: manager.last_state == ('disabled', ''))
                    with self.assertRaises(PermissionError):
                        access.principal(launches[1][1]['LEAFLOOM_TUNNEL_MCP_AUTHORIZATION'], 'legacy', loopback=True)
                finally:manager.close()

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
        from vault_rag.mcp_access import McpAccess
        import datetime
        access_home = tempfile.TemporaryDirectory()
        self.addCleanup(access_home.cleanup)
        access = McpAccess(LocalConfig(Path(access_home.name) / 'state'))
        access.configure('tunnel', enabled=True, write=False, resource='feishu')
        pending, responses, seen = [], [], []
        guard = threading.Lock()
        class LocalServer(http.server.BaseHTTPRequestHandler):
            polls = 0
            def log_message(self, *args): pass
            def do_GET(self):
                if '/v1/tunnels/' in self.path and '/poll' in self.path:
                    LocalServer.polls += 1
                    with guard:
                        commands = pending[:]
                        pending.clear()
                    if commands:
                        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
                        self.wfile.write(json.dumps({'commands': commands}).encode()); return
                    time.sleep(.05)
                    self.send_response(204); self.end_headers()
                else:
                    self.send_response(404); self.end_headers(); self.wfile.write(b'{"detail":"Not Found"}')
            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                if not raw:
                    self.send_response(400); self.end_headers(); return
                payload = json.loads(raw)
                if self.path.endswith('/response'):
                    with guard: responses.append(payload)
                    self.send_response(200); self.end_headers(); self.wfile.write(b'{}'); return
                method = payload.get('method')
                if method == 'notifications/initialized':
                    self.send_response(202); self.end_headers(); return
                result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'fixture', 'version': '1'}} if method == 'initialize' else {'tools': []}
                if method == 'tools/call':
                    bearer = self.headers.get('Authorization', '')
                    proof = self.headers.get(TUNNEL_AUTH_HEADER, '')
                    try: who = access.principal(bearer, 'legacy-chat-token', loopback=True, tunnel_header=proof)
                    except PermissionError: who = 'invalid'
                    with guard: seen.append((bearer, who))
                    result = {'content': [{'type': 'text', 'text': who}]}
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
                    manager = TunnelManager(temp, server.server_port, lambda kind, **value: states.append(value), mcp_access=access)
                    try:
                        manager.configure({'enabled': True, 'binary': str(binary), 'tunnelId': 'tunnel_'+'a'*32, 'apiKey': 'sk-test-local-fixture-only'})
                        self.wait(lambda: any(s['state'] == 'ready' for s in states))
                        self.assertGreater(LocalServer.polls, 0)
                        # Reproduce the old Authorization collision in the actual
                        # bundled executable, then exercise the fix without a
                        # refresh/reconnect between different chat credentials.
                        for header_name, expected in (('Authorization', ['tunnel', 'legacy', 'invalid']),
                                                       (TUNNEL_AUTH_HEADER, ['tunnel', 'tunnel', 'tunnel'])):
                            if header_name == 'Authorization':
                                # Start the old configuration only for the regression fixture.
                                manager.close()
                                with patch('vault_rag.tunnel.TUNNEL_AUTH_HEADER', 'Authorization'):
                                    manager = TunnelManager(temp, server.server_port, lambda *a, **k: None, mcp_access=access)
                                    manager.configure({'enabled': True, 'binary': str(binary), 'tunnelId': 'tunnel_'+'a'*32, 'apiKey': 'sk-test-local-fixture-only'})
                                    self.wait(lambda: manager.last_state == ('ready', ''))
                            else:
                                manager.close()
                                manager = TunnelManager(temp, server.server_port, lambda *a, **k: None, mcp_access=access)
                                manager.configure({'enabled': True, 'binary': str(binary), 'tunnelId': 'tunnel_'+'a'*32, 'apiKey': 'sk-test-local-fixture-only'})
                                self.wait(lambda: manager.last_state == ('ready', ''))
                            for i, bearer in enumerate(('', 'Bearer legacy-chat-token', 'Bearer stale-chat-token')):
                                request_id = f'{header_name}-{i}'
                                command = {'command_type': 'jsonrpc', 'request_id': request_id, 'shard_token': request_id,
                                           'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                           'jsonrpc': {'jsonrpc': '2.0', 'id': i + 10, 'method': 'tools/call',
                                                       'params': {'name': 'identity', 'arguments': {}}},
                                           'headers': {'Authorization': [bearer]} if bearer else {}}
                                with guard: pending.append(command)
                                self.wait(lambda: any(r.get('request_id') == request_id for r in responses))
                                response = next(r for r in responses if r.get('request_id') == request_id)
                                self.assertEqual(response['resp_json']['result']['content'][0]['text'], expected[i])
                        self.assertEqual([who for _, who in seen], ['tunnel', 'legacy', 'invalid', 'tunnel', 'tunnel', 'tunnel'])
                        process = manager.process
                    finally: manager.close()
                    self.assertIsNotNone(process.poll())
            finally:
                server.shutdown(); server.server_close()


if __name__ == '__main__': unittest.main()
