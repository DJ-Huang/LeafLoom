"""Skill installation uses temporary user directories, never the real home."""
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient
from vault_rag.local_state import LocalConfig
from vault_rag.skill_install import install_skill, skill_source, skill_spec, skill_status
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
            client.cookies.set('vault_session', (config.directory / 'auth-token').read_text().strip())
            self.assertEqual(client.post(endpoint).status_code, 403)
            self.assertFalse(self.target.exists())
            response = client.post(endpoint, headers={'X-Vault-CSRF': app.state.csrf})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.target.read_bytes(), skill_source().read_bytes())
            self.assertTrue(client.get('/api/skills/wiki-search').json()['up_to_date'])

    def test_work_hub_installs_all_resources_independently(self):
        target = self.home / '.agents/skills/work-hub'
        self.assertFalse(skill_status('work-hub')['installed'])
        result = install_skill('work-hub')
        self.assertEqual(result['path'], str(target / 'SKILL.md'))
        for name in ('references/workspace.md', 'references/imports.md',
                     'references/feishu.md', 'references/gitlab.md', 'references/settings.md',
                     'references/tasks-reports.md', 'references/feishu-sync.md',
                     'assets/workspace.base', 'scripts/task_sync.py', 'scripts/feishu_sync.py'):
            self.assertEqual((target / name).read_bytes(), (skill_source('work-hub').parent / name).read_bytes())
        personal = target / 'personal.md'; personal.write_text('keep')
        script = target / 'scripts/task_sync.py'; script.write_text('personal script')
        self.assertFalse(skill_status('work-hub')['up_to_date'])
        updated = install_skill('work-hub')
        self.assertEqual(len(updated['backups']), 1)
        self.assertEqual(Path(updated['backup']).read_text(), 'personal script')
        self.assertEqual(personal.read_text(), 'keep')
        self.assertTrue(skill_status('work-hub')['up_to_date'])
        self.assertEqual(install_skill('work-hub')['backups'], [])
        self.assertFalse(skill_status()['installed'])

    def test_work_hub_preflight_rejects_linked_resource_before_writes(self):
        target = self.home / '.agents/skills/work-hub'
        target.mkdir(parents=True)
        (target / 'SKILL.md').write_text('unchanged')
        outside = self.home / 'outside'; outside.mkdir()
        (target / 'references').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            install_skill('work-hub')
        self.assertEqual((target / 'SKILL.md').read_text(), 'unchanged')
        self.assertEqual(list(outside.iterdir()), [])

    def test_work_hub_missing_resource_is_outdated(self):
        install_skill('work-hub')
        for resource in ('assets/workspace.base', 'references/feishu.md', 'references/gitlab.md'):
            with self.subTest(resource=resource):
                (self.home / '.agents/skills/work-hub' / resource).unlink()
                self.assertTrue(skill_status('work-hub')['installed'])
                self.assertFalse(skill_status('work-hub')['up_to_date'])
                self.assertTrue(install_skill('work-hub')['up_to_date'])

    def test_work_hub_wheel_declares_every_installable_resource(self):
        manifest = tomllib.loads((Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text())
        includes = manifest['tool']['hatch']['build']['targets']['wheel']['force-include']
        for resource in skill_spec('work-hub')[1]:
            with self.subTest(resource=resource):
                self.assertEqual(includes['work-hub/' + resource], 'vault_rag/skills/work-hub/' + resource)

    def test_packaged_resource_links_are_rejected_before_installing(self):
        source = self.home / 'package'; source.mkdir()
        (source / 'SKILL.md').write_text('entry')
        (source / 'references').mkdir()
        outside = self.home / 'outside.md'; outside.write_text('outside')
        (source / 'references/workspace.md').symlink_to(outside)
        with patch('vault_rag.skill_install.skill_source', return_value=source / 'SKILL.md'):
            with self.assertRaises(ValueError):
                install_skill('work-hub')
        self.assertFalse((self.home / '.agents').exists())

    def test_unknown_skill_never_constructs_user_paths(self):
        with self.assertRaises(ValueError):
            install_skill('../outside')
        self.assertFalse((self.home / '.agents').exists())

    def test_work_hub_endpoint_auth_and_unknown_names(self):
        config = LocalConfig(self.home / 'state')
        static = self.home / 'static'; static.mkdir()
        (static / 'index.html').write_text('<h1>Knowledge</h1>')
        app = create_app(config, start_background=False, static_dir=static)
        with TestClient(app, base_url='http://127.0.0.1:18080') as client:
            endpoint = '/api/skills/work-hub/install'
            self.assertEqual(client.post(endpoint).status_code, 401)
            client.get('/')
            client.cookies.set('vault_session', (config.directory / 'auth-token').read_text().strip())
            self.assertEqual(client.post(endpoint).status_code, 403)
            self.assertFalse((self.home / '.agents').exists())
            headers = {'X-Vault-CSRF': app.state.csrf}
            response = client.post(endpoint, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(client.get('/api/skills/work-hub').json()['up_to_date'])
            self.assertEqual(client.post('/api/skills/not-registered/install', headers=headers).status_code, 404)
            self.assertEqual(client.get('/api/skills/not-registered').status_code, 404)
