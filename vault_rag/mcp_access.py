"""Revocable, MCP-only credentials. Browser/API credentials never grant workspace access."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading

from vault_rag.local_state import atomic_write
from vault_rag.platform_support import private_file_mode


class McpAccess:
    def __init__(self, config):
        self.path = config.directory / 'mcp-access.json'
        self.lock = threading.RLock()
        self.on_change = lambda: None
        self.tunnel_secret = secrets.token_urlsafe(48)
        self.data = {kind: {'enabled': False, 'write': False, 'token_hash': ''}
                     for kind in ('local', 'tunnel')}
        if self.path.exists():
            value = json.loads(self.path.read_text(encoding='utf-8'))
            for kind in self.data:
                row = value.get(kind, {})
                self.data[kind] = {'enabled': row.get('enabled') is True,
                                   'write': row.get('write') is True,
                                   'token_hash': str(row.get('token_hash', ''))}

    def status(self):
        with self.lock:
            return {kind: {key: row[key] for key in ('enabled', 'write')}
                    for kind, row in self.data.items()}

    def configure(self, kind, *, enabled, write, rotate=False):
        if not isinstance(kind,str) or kind not in self.data or not all(isinstance(v, bool) for v in (enabled, write, rotate)):
            raise ValueError('Invalid MCP access settings')
        with self.lock:
            data = {k: dict(v) for k, v in self.data.items()}
            row = data[kind]
            token = None
            if kind == 'local' and enabled and (rotate or not row['token_hash']):
                token = secrets.token_urlsafe(48)
                row['token_hash'] = hashlib.sha256(token.encode()).hexdigest()
            if not enabled:
                row['token_hash'] = ''
            row.update(enabled=enabled, write=enabled and write)
            atomic_write(self.path, json.dumps(data).encode())
            private_file_mode(self.path)
            self.data = data
            if kind == 'tunnel':
                self.tunnel_secret = secrets.token_urlsafe(48)
            result = self.status()
            if token:
                result['token'] = token  # Returned once, only to the authenticated settings API.
        if kind == 'tunnel':
            self.on_change()
        return result

    def rotate_tunnel_secret(self):
        with self.lock:
            self.tunnel_secret = secrets.token_urlsafe(48)

    def tunnel_authorization(self):
        with self.lock:
            return 'Bearer ' + self.tunnel_secret if self.data['tunnel']['enabled'] else ''

    def principal(self, header, legacy_token, *, loopback=False):
        with self.lock:
            if not header.isascii():
                raise PermissionError('MCP credential is invalid or revoked')
            if not header:
                if loopback:
                    return 'legacy'
                raise PermissionError('MCP authentication required')
            if hmac.compare_digest(header, 'Bearer ' + legacy_token):
                return 'legacy'
            if header.startswith('Bearer '):
                value = header[7:]
                local = self.data['local']
                if local['enabled'] and local['token_hash'] and hmac.compare_digest(
                        hashlib.sha256(value.encode()).hexdigest(), local['token_hash']):
                    return 'local'
                if self.data['tunnel']['enabled'] and hmac.compare_digest(value, self.tunnel_secret):
                    return 'tunnel'
            raise PermissionError('MCP credential is invalid or revoked')

    def require(self, principal, *, write=False):
        with self.lock:
            if principal not in self.data or not self.data[principal]['enabled']:
                raise PermissionError('Enable full MCP access and configure its dedicated credential')
            if write and not self.data[principal]['write']:
                raise PermissionError('MCP write access is disabled for this connection')

    def capabilities(self, principal):
        with self.lock:
            row = self.data.get(principal, {})
            return {'connection': principal, 'read_workspace': row.get('enabled', False),
                    'write_workspace': bool(row.get('enabled') and row.get('write'))}
