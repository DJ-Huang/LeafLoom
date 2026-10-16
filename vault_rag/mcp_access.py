"""Revocable, MCP-only credentials. Browser/API credentials never grant workspace access."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading

from vault_rag.local_state import atomic_write
from vault_rag.platform_support import private_file_mode

TUNNEL_AUTH_HEADER = 'X-LeafLoom-Tunnel-Authorization'


class McpAccessError(PermissionError):
    def __init__(self, message, **details):
        super().__init__(message)
        self.details = {'error_source': 'leafloom_mcp', **details}


class McpAccess:
    def __init__(self, config):
        self.path = config.directory / 'mcp-access.json'
        self.lock = threading.RLock()
        self.on_change = lambda: None
        self.tunnel_secret = secrets.token_urlsafe(48)
        self.data = {kind: {'enabled': False, 'write': False, 'feishu_read': False, 'feishu_write': False,
                            'feishu_high_risk': False, 'token_hash': ''}
                     for kind in ('local', 'tunnel')}
        if self.path.exists():
            value = json.loads(self.path.read_text(encoding='utf-8'))
            for kind in self.data:
                row = value.get(kind, {})
                self.data[kind] = {'enabled': row.get('enabled') is True,
                                   'write': row.get('write') is True,
                                   'feishu_read': row.get('feishu_read') is True,
                                   'feishu_write': row.get('feishu_write') is True and row.get('feishu_read') is True,
                                   'feishu_high_risk': all(row.get(k) is True for k in ('feishu_read', 'feishu_write', 'feishu_high_risk')),
                                   'token_hash': str(row.get('token_hash', ''))}

    def status(self):
        with self.lock:
            return {kind: {key: row[key] for key in ('enabled', 'write', 'feishu_read', 'feishu_write', 'feishu_high_risk')}
                    for kind, row in self.data.items()}

    @staticmethod
    def active(row):
        return bool(row['enabled'] or row['feishu_read'])

    def configure(self, kind, *, enabled, write, rotate=False, resource='workspace', high_risk=None):
        if not isinstance(kind,str) or kind not in self.data or not all(isinstance(v, bool) for v in (enabled, write, rotate)):
            raise ValueError('Invalid MCP access settings')
        if resource not in ('workspace', 'feishu'):
            raise ValueError('Invalid MCP resource')
        if high_risk is not None and (resource != 'feishu' or type(high_risk) is not bool):
            raise ValueError('high_risk is a Feishu boolean setting')
        with self.lock:
            data = {k: dict(v) for k, v in self.data.items()}
            row = data[kind]
            token = None
            read_key, write_key = ('enabled', 'write') if resource == 'workspace' else ('feishu_read', 'feishu_write')
            row.update({read_key: enabled, write_key: enabled and write})
            if resource == 'feishu':
                row['feishu_high_risk'] = bool(enabled and write and
                    (row['feishu_high_risk'] if high_risk is None else high_risk))
            if kind == 'local' and self.active(row) and (rotate or not row['token_hash']):
                token = secrets.token_urlsafe(48)
                row['token_hash'] = hashlib.sha256(token.encode()).hexdigest()
            if not self.active(row):
                row['token_hash'] = ''
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
            return 'Bearer ' + self.tunnel_secret if self.active(self.data['tunnel']) else ''

    def principal(self, header, legacy_token, *, loopback=False, tunnel_header=''):
        with self.lock:
            # Connector Authorization is per-request and overrides static headers
            # in tunnel-client. Authenticate the owned runtime independently, before
            # considering that bearer. Never downgrade an invalid runtime proof.
            if tunnel_header:
                if (not loopback or not tunnel_header.isascii() or
                        not self.active(self.data['tunnel']) or
                        not hmac.compare_digest(tunnel_header, 'Bearer ' + self.tunnel_secret)):
                    raise McpAccessError('MCP Tunnel credential is invalid or revoked')
                return 'tunnel'
            if not header.isascii():
                raise McpAccessError('MCP credential is invalid or revoked')
            if not header:
                if loopback:
                    return 'legacy'
                raise McpAccessError('MCP authentication required')
            if hmac.compare_digest(header, 'Bearer ' + legacy_token):
                return 'legacy'
            if header.startswith('Bearer '):
                value = header[7:]
                local = self.data['local']
                if self.active(local) and local['token_hash'] and hmac.compare_digest(
                        hashlib.sha256(value.encode()).hexdigest(), local['token_hash']):
                    return 'local'
                if self.active(self.data['tunnel']) and hmac.compare_digest(value, self.tunnel_secret):
                    return 'tunnel'
            raise McpAccessError('MCP credential is invalid or revoked')

    def require(self, principal, *, write=False, resource='workspace', high_risk=False):
        with self.lock:
            if resource not in ('workspace', 'feishu'): raise ValueError('Invalid MCP resource')
            read_key, write_key = ('enabled', 'write') if resource == 'workspace' else ('feishu_read', 'feishu_write')
            if principal not in self.data or not self.data[principal][read_key]:
                raise McpAccessError('LeafLoom MCP access is not authorized for this connection; this is not a Feishu resource permission error',
                                     connection=principal, resource=resource, required_permission=read_key,
                                     hint='Check the active MCP/Tunnel client and its dedicated credential; do not reauthorize Feishu for this error')
            if (write or high_risk) and not self.data[principal][write_key]:
                raise McpAccessError('MCP write access is disabled for this connection',
                                     connection=principal, resource=resource, required_permission=write_key)
            if high_risk and (resource != 'feishu' or not self.data[principal]['feishu_high_risk']):
                raise McpAccessError('High-risk Feishu access is disabled for this connection',
                                     connection=principal, resource=resource, required_permission='feishu_high_risk')

    def file_owner(self, principal):
        """Opaque generation identity: rotation invalidates staged files without storing secrets."""
        self.require(principal, resource='feishu')
        generation = self.data[principal]['token_hash'] if principal == 'local' else self.tunnel_secret
        return hashlib.sha256((principal + ':' + generation).encode()).hexdigest()

    def capabilities(self, principal):
        with self.lock:
            row = self.data.get(principal, {})
            return {'connection': principal, 'read_workspace': row.get('enabled', False),
                    'write_workspace': bool(row.get('enabled') and row.get('write')),
                    'read_feishu': row.get('feishu_read', False),
                    'write_feishu': bool(row.get('feishu_read') and row.get('feishu_write')),
                    'high_risk_feishu': bool(row.get('feishu_read') and row.get('feishu_write') and row.get('feishu_high_risk'))}
