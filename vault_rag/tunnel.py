"""Desktop-owned OpenAI Tunnel runtime. Credentials only arrive on the private pipe."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request

from vault_rag.worker_lifetime import WorkerJob


class TunnelError(Exception):
    def __init__(self, code):
        self.code = code


def request(url, payload=None):
    headers = {'Accept': 'application/json, text/event-stream'}
    if payload is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
    # Loopback requests must never traverse a user's system proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        response = opener.open(req, timeout=2)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read(256 * 1024)
        try: value = json.loads(raw)
        except (ValueError, UnicodeDecodeError): value = {}
        return response.code, value if isinstance(value, dict) else {}


def failure_code(value):
    """Map runtime diagnostics to fixed UI messages without exporting raw data."""
    text = json.dumps(value, default=str).lower()
    if any(word in text for word in ('unauthorized', 'invalid_api_key', 'invalid api key')) or re.search(r'\b401\b', text):
        return 'tunnel.error.key'
    if any(word in text for word in ('forbidden', 'permission_denied', 'permission denied')) or re.search(r'\b403\b', text):
        return 'tunnel.error.permission'
    if any(word in text for word in ('tunnel_not_found', 'tunnel not found')) or re.search(r'\b404\b', text):
        return 'tunnel.error.tunnel'
    return ''


class TunnelManager:
    def __init__(self, directory, port, emit):
        self.directory = Path(directory) / 'tunnel'
        self.port = port
        self.emit = emit
        self.condition = threading.Condition()
        self.desired = None
        self.revision = 0
        self.closed = False
        self.process = None
        self.job = None
        self.last_state = None
        self.thread = threading.Thread(target=self._run, name='desktop-tunnel', daemon=True)
        self.thread.start()

    def configure(self, values):
        # Do not retain arbitrary pipe fields or log malformed input containing keys.
        enabled = values.get('enabled') is True
        desired = None
        if enabled:
            tunnel_id, key, binary = values.get('tunnelId'), values.get('apiKey'), values.get('binary')
            if not isinstance(tunnel_id, str) or not re.fullmatch(r'tunnel_[A-Za-z0-9_-]{1,120}', tunnel_id):
                self._state('failed', 'tunnel.error.config')
                return
            if not isinstance(key, str) or not key or len(key) > 4096 or any(c in key for c in '\r\n\0'):
                self._state('failed', 'tunnel.error.key')
                return
            if not isinstance(binary, str) or not Path(binary).is_absolute():
                self._state('failed', 'tunnel.error.binary')
                return
            desired = (binary, tunnel_id, key)
        with self.condition:
            if self.closed: return
            self.desired = desired
            self.revision += 1
            self.condition.notify_all()

    def _state(self, state, error=''):
        value = (state, error)
        if value != self.last_state:
            self.last_state = value
            logging.getLogger(__name__).info('Tunnel state=%s reason=%s', state, error)
            self.emit('tunnel-state', state=state, error=error)

    def _launch(self, binary, tunnel_id, key):
        if not Path(binary).is_file(): raise TunnelError('tunnel.error.binary')
        payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-06-18', 'capabilities': {},
            'clientInfo': {'name': 'LeafLoom Tunnel', 'version': '1'}}}
        try: code, value = request(f'http://127.0.0.1:{self.port}/mcp', payload)
        except (OSError, ValueError): raise TunnelError('tunnel.error.mcp') from None
        if code != 200 or 'result' not in value: raise TunnelError('tunnel.error.mcp')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.health_file = self.directory / 'health-url'
        self.health_file.unlink(missing_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(
            ('CONTROL_PLANE_', 'MCP_', 'TUNNEL_CLIENT_', 'HARPOON_', 'HEALTH_', 'LOG_'))
            and k.upper() not in ('OPENAI_API_KEY', 'OPENAI_ADMIN_KEY')}
        env['CONTROL_PLANE_API_KEY'] = key
        env['NO_PROXY'] = env['no_proxy'] = '127.0.0.1,localhost,::1'
        args = [binary, 'run', '--control-plane.tunnel-id', tunnel_id,
                '--control-plane.api-key', 'env:CONTROL_PLANE_API_KEY',
                '--mcp.server-url', f'http://127.0.0.1:{self.port}/mcp',
                '--health.listen-addr', '127.0.0.1:0', '--health.url-file', str(self.health_file),
                '--log.format', 'json', '--log.level', 'info']
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        self.process = subprocess.Popen(args, env=env, cwd=self.directory, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **options)
        try: self.job = WorkerJob(self.process)
        except OSError:
            self.process.stdout.close()
            self.process = None
            raise TunnelError('tunnel.error.process') from None
        # Read continuously so a full log pipe cannot block the runtime. Only fixed
        # reason codes are kept; runtime output can include request-specific secrets.
        self.runtime_error = ''
        def consume(process):
            with process.stdout:
                while raw := process.stdout.readline(16384):
                    if process is self.process:
                        line = raw.decode('utf-8', errors='replace').lower()
                        reason = failure_code(line) if any(term in line for term in ('control-plane', 'control_plane', 'poll')) else ''
                        if 'configure tunnel-client' in line: reason = 'tunnel.error.config'
                        if reason: self.runtime_error = reason
        threading.Thread(target=consume, args=(self.process,), name='tunnel-output', daemon=True).start()

    def _stop_process(self):
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            try:
                if os.name == 'nt': process.terminate()
                else: os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == 'nt': process.kill()
                else: os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            except ProcessLookupError: pass
        if self.job: self.job.close(); self.job = None

    def _health(self):
        self.health_degraded = False
        if not self.health_file.exists(): return False
        url = self.health_file.read_text(encoding='utf-8').strip()
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port or parsed.username or parsed.password:
            raise TunnelError('tunnel.error.process')
        base = f'http://127.0.0.1:{parsed.port}'
        code, _ = request(base + '/readyz')
        _, detail = request(base + '/health?details=true')
        control = detail.get('components', {}).get('control-plane', {})
        reason = failure_code(control)
        if reason: raise TunnelError(reason)
        self.health_degraded = control.get('status') == 'degraded'
        return code == 200 and control.get('status') == 'ok'

    def _run(self):
        seen, desired, blocked, retry_at, attempts = -1, None, False, 0, 0
        try:
            while True:
                with self.condition:
                    if self.closed: return
                    if self.revision == seen: self.condition.wait(timeout=1)
                    changed = self.revision != seen
                    if changed:
                        seen, desired = self.revision, self.desired
                    if self.closed: return
                if changed:
                    self._stop_process()
                    blocked, retry_at, attempts = False, 0, 0
                    self._state('starting' if desired else 'disabled')
                if not desired or blocked or time.monotonic() < retry_at: continue
                try:
                    if self.process is None:
                        self._state('starting' if not attempts else 'reconnecting')
                        self._launch(*desired)
                    if self.runtime_error: raise TunnelError(self.runtime_error)
                    if self.process.poll() is not None: raise TunnelError('tunnel.error.process')
                    if self._health():
                        self._state('ready'); attempts = 0
                    elif self.health_degraded or (self.last_state and self.last_state[0] == 'ready'):
                        self._state('reconnecting', 'tunnel.error.network')
                except TunnelError as error:
                    self._stop_process()
                    blocked = error.code in ('tunnel.error.key', 'tunnel.error.permission', 'tunnel.error.tunnel', 'tunnel.error.config', 'tunnel.error.binary')
                    self._state('failed' if blocked else 'reconnecting', error.code)
                    retry_at = time.monotonic() + (2, 5, 15, 30)[min(attempts, 3)]
                    attempts += 1
                except (OSError, ValueError, TypeError):
                    # Startup/network errors must not stop the file service.
                    self._stop_process()
                    self._state('reconnecting', 'tunnel.error.network')
                    retry_at = time.monotonic() + 5
        finally:
            self._stop_process()

    def close(self):
        with self.condition:
            self.closed = True
            self.desired = None
            self.condition.notify_all()
        self.thread.join(timeout=18)
