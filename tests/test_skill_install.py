"""Skill installation uses temporary user directories, never the real home."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient
from vault_rag.local_state import LocalConfig
from vault_rag.skill_install import install_skill, skill_source, skill_status
from vault_rag.web_server import create_app


class SkillInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.home_patch = patch('vault_rag.skill_install.Path.home', return_value=self.home)
        self.home_patch.start()
        self.target = self.home / '.agent/skills/wiki-search/SKILL.md'

    def tearDown(self):
        self.home_patch.stop()
        self.temp.cleanup()

    def test_install_and_repeat_preserve_other_files(self):
        self.assertFalse(skill_status()['installed'])
        result = install_skill()
        self.assertEqual(Path(result['path']), self.target)
        self.assertEqual(self.target.read_bytes(), skill_source().read_bytes())
        extra = self.target.parent / 'personal.txt'
        extra.write_text('keep')
        self.assertIsNone(install_skill()['backup'])
        self.assertEqual(extra.read_text(), 'keep')
        self.assertTrue(skill_status()['up_to_date'])

    def test_update_backs_up_modified_content(self):
        install_skill()
        self.target.write_text('my previous skill')
        self.assertFalse(skill_status()['up_to_date'])
        result = install_skill()
        self.assertEqual(Path(result['backup']).read_text(), 'my previous skill')
        self.assertEqual(self.target.read_bytes(), skill_source().read_bytes())

    def test_symlink_destination_is_rejected(self):
        outside = self.home / 'outside'
        outside.mkdir()
        (self.home / '.agent').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            install_skill()
        self.assertEqual(list(outside.iterdir()), [])

    def test_install_endpoint_requires_session_and_csrf(self):
        config = LocalConfig(self.home / 'state')
        static = self.home / 'static'
        static.mkdir()
        (static / 'index.html').write_text('<h1>Knowledge</h1>')
        app = create_app(config, start_background=False, static_dir=static)
        with TestClient(app, base_url='http://127.0.0.1:18080') as client:
            endpoint = '/api/skills/wiki-search/install'
            self.assertEqual(client.post(endpoint).status_code, 401)
            client.get('/')
            self.assertEqual(client.post(endpoint).status_code, 403)
            self.assertFalse(self.target.exists())
            response = client.post(endpoint, headers={'X-Vault-CSRF': app.state.csrf})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.target.read_bytes(), skill_source().read_bytes())
            self.assertTrue(client.get('/api/skills/wiki-search').json()['up_to_date'])
