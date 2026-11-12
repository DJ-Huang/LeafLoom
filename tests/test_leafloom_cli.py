"""Exercise the Windows skill entry point against an isolated loopback service."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


SCRIPTS = Path(__file__).resolve().parents[1] / 'leafloom/scripts'
SHELLS = [path for name in ('powershell', 'pwsh') if (path := shutil.which(name))]


def ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(sys.platform == 'win32' and SHELLS, 'Requires Windows PowerShell')
class LeafLoomWindowsCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scripts = self.root / "技能 user's scripts"
        self.scripts.mkdir()
        for name in ('leafloom.py', 'leafloom.ps1'):
            shutil.copyfile(SCRIPTS / name, self.scripts / name)
        self.requests = []
        self.status = 200
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                arguments = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fixture.requests.append((self.path, self.headers['Authorization'], arguments))
                result = {'ok': fixture.status == 200, 'echo': arguments, 'message': '中文回执 🌿'}
                payload = json.dumps(result, ensure_ascii=False).encode('utf-8')
                self.send_response(fixture.status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        state = self.root / 'state'
        state.mkdir()
        (state / 'leafloom-skill-token').write_text('fictional-token', encoding='utf-8')
        (state / 'config.json').write_text(json.dumps({'port': self.server.server_port}), encoding='utf-8')
        self.env = {**os.environ, 'VAULT_RAG_HOME': str(state)}
        self.env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + self.env.get('PATH', '')

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def call(self, shell, operation, arguments='', *, path=None):
        # Simulate PS 5.1's ASCII native-input default and capture Unicode output.
        driver = self.root / 'invoke.ps1'
        driver.write_text(
            '[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)\n'
            '$OutputEncoding = [System.Text.ASCIIEncoding]::new()\n'
            '$PSNativeCommandUseErrorActionPreference = $true\n'
            f'$response = & {ps_literal(self.scripts / "leafloom.ps1")} {operation} {arguments}\n'
            '$code = $LASTEXITCODE\n'
            'if ($OutputEncoding.WebName -ne "us-ascii") { throw "Encoding was not restored" }\n'
            '$response\nexit $code\n', encoding='utf-8-sig')
        env = dict(self.env)
        if path is not None:
            env['PATH'] = path
        result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                 '-File', str(driver)], env=env, capture_output=True, timeout=30)
        self.assertFalse(result.stderr, result.stderr.decode('utf-8', errors='replace'))
        return result.returncode, json.loads(result.stdout.decode('utf-8'))

    def test_unicode_quotes_paths_and_nested_objects_survive_store_alias(self):
        # A Store-style alias must never be invoked, even when it precedes Python.
        alias = self.root / 'Microsoft/WindowsApps'
        alias.mkdir(parents=True)
        marker = self.root / 'alias-invoked.txt'
        (alias / 'python.cmd').write_text(f'@echo off\necho invoked>"{marker}"\nexit /b 0\n')
        path = str(alias) + os.pathsep + self.env['PATH']
        query = '本周 "进度" \\路径 🌿 $(literal)'
        arguments = "@{ query = " + ps_literal(query) + "; folder = '工作中枢\\工作目录'; " + (
            "top_k = 3; nested = @{ a = @{ b = @{ c = @{ values = @($true, $null, '日本語') } } } } }")
        expected = {'query': query, 'folder': '工作中枢\\工作目录', 'top_k': 3,
                    'nested': {'a': {'b': {'c': {'values': [True, None, '日本語']}}}}}
        for shell in SHELLS:
            with self.subTest(shell=shell):
                self.requests.clear()
                code, result = self.call(shell, 'search', arguments, path=path)
                self.assertEqual(code, 0, result)
                self.assertEqual(result['echo'], expected)
                self.assertEqual(result['message'], '中文回执 🌿')
                self.assertEqual(self.requests, [('/api/leafloom/search', 'Bearer fictional-token', expected)])
                self.assertFalse(marker.exists())

    def test_service_write_error_keeps_exit_code_and_never_retries(self):
        self.status = 409
        for shell in SHELLS:
            with self.subTest(shell=shell):
                self.requests.clear()
                code, result = self.call(shell, 'note-update', "@{ path = '记录.md'; text = \"第一行`n第二行\" }")
                self.assertEqual(code, 1, result)
                self.assertFalse(result['ok'])
                self.assertEqual(result['http_status'], 409)
                self.assertEqual(len(self.requests), 1)
                self.assertEqual(self.requests[0][2]['text'], '第一行\n第二行')

    @unittest.skipUnless(shutil.which('py'), 'Requires the Windows Python launcher')
    def test_py_launcher_fallback_and_default_empty_arguments(self):
        path = str(Path(shutil.which('py')).parent)
        for shell in SHELLS:
            with self.subTest(shell=shell):
                self.requests.clear()
                code, result = self.call(shell, 'status', path=path)
                self.assertEqual(code, 0, result)
                self.assertEqual(self.requests, [('/api/leafloom/status', 'Bearer fictional-token', {})])

    def test_missing_python_returns_actionable_json_without_service_request(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                code, result = self.call(shell, 'status', path=str(self.root))
                self.assertEqual(code, 1)
                self.assertFalse(result['ok'])
                self.assertIn('Python 3.11+', result['error'])
                self.assertEqual(self.requests, [])
