"""Focused release regressions: identity, safe migration and resource locations."""
import io
import json
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from vault_rag.local_state import LocalConfig
from vault_rag.web_server import create_app
from vault_rag.desktop_runtime import build_info, service_instance
from vault_rag.desktop_migration import inspect_legacy, migrate_legacy, LABELS


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.config = LocalConfig(self.home / 'state')

    def tearDown(self):
        self.temp.cleanup()

    def test_status_identity_is_additive_and_still_authenticated(self):
        info = {'app_version': '0.2.0-beta.1', 'desktop_protocol_version': 1, 'distribution': 'desktop'}
        app = create_app(self.config, start_background=False, desktop_info=info)
        token = (self.config.directory / 'auth-token').read_text()
        with TestClient(app, base_url='http://127.0.0.1:18080') as client:
            self.assertEqual(client.get('/api/status').status_code, 401)
            status = client.get('/api/status', headers={'Authorization': 'Bearer ' + token}).json()
            self.assertEqual(status['app_version'], info['app_version'])
            self.assertIn('model', status)
            self.assertEqual(client.get('/api/status', headers={'Host': 'attacker'}).status_code, 403)

    def agent(self, label, home=None):
        path = self.home / 'Library/LaunchAgents' / (label + '.plist')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plistlib.dumps({'Label': label, 'EnvironmentVariables': {
            'VAULT_RAG_HOME': str(home or self.config.directory)}, 'RunAtLoad': True}))
        return path

    def test_foreign_legacy_home_is_never_modified(self):
        path = self.agent(LABELS[0], self.home / 'other')
        original = path.read_bytes()
        with patch('vault_rag.desktop_migration.sys.platform', 'darwin'), patch('pathlib.Path.home', return_value=self.home):
            with self.assertRaisesRegex(RuntimeError, '其他配置目录'):
                migrate_legacy(self.config)
        self.assertEqual(path.read_bytes(), original)

    def test_successful_takeover_backs_up_and_preserves_login_choice(self):
        path = self.agent(LABELS[0])
        original = path.read_bytes()
        response = type('Result', (), {'returncode': 1})()
        with patch('vault_rag.desktop_migration.sys.platform', 'darwin'), patch('pathlib.Path.home', return_value=self.home), patch('vault_rag.service_control.health', return_value='stopped'), patch('vault_rag.desktop_migration.launchctl', return_value=response), patch('vault_rag.desktop_migration.port_open', return_value=False):
            result = migrate_legacy(self.config)
        self.assertTrue(result['autostart']); self.assertFalse(path.exists())
        self.assertEqual((Path(result['backup']) / '0.plist').read_bytes(), original)

    def test_failed_takeover_restores_registration(self):
        path = self.agent(LABELS[0]); original = path.read_bytes()
        response = type('Result', (), {'returncode': 0})()
        with patch('vault_rag.desktop_migration.sys.platform', 'darwin'), patch('pathlib.Path.home', return_value=self.home), patch('vault_rag.service_control.health', return_value='ready'), patch('vault_rag.desktop_migration.launchctl', return_value=response):
            with self.assertRaisesRegex(RuntimeError, '迁移未完成'):
                migrate_legacy(self.config)
        self.assertEqual(path.read_bytes(), original)

    @unittest.skipIf(os.name == 'nt', 'POSIX lock; Windows uses the existing service mutex')
    def test_backend_singleton_is_scoped_to_home(self):
        with service_instance(self.config.directory):
            with self.assertRaisesRegex(RuntimeError, '已运行'):
                with service_instance(self.config.directory):
                    pass


if __name__ == '__main__':
    unittest.main()
