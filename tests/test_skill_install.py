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
        self.target = self.home / '.agents/skills/leafloom/SKILL.md'

    def tearDown(self):
        self.home_patch.stop()
        self.temp.cleanup()

    def test_install_and_repeat_preserve_other_files(self):
        self.assertFalse(skill_status()['installed'])
        result = install_skill()
        self.assertEqual(Path(result['path']), self.target)
        self.assertEqual(self.target.read_bytes(), skill_source().read_bytes())
        self.assertEqual(result['retired'], [])
        extra = self.target.parent / 'personal.txt'
        extra.write_text('keep')
        self.assertIsNone(install_skill()['backup'])
        self.assertEqual(extra.read_text(), 'keep')
        self.assertTrue(skill_status()['up_to_date'])

    def test_install_retires_superseded_skills(self):
        skills = self.home / '.agents/skills'
        for name, body in (('wiki-search', 'old wiki'), ('work-hub', 'old hub')):
            folder = skills / name
            folder.mkdir(parents=True)
            (folder / 'SKILL.md').write_text(body)
            (folder / 'notes.md').write_text('keep in backup')
        unrelated = skills / 'other-skill'
        unrelated.mkdir(parents=True)
        (unrelated / 'SKILL.md').write_text('keep')
        decoy = skills / 'work-hub-notes'
        decoy.mkdir(parents=True)
        (decoy / 'readme.txt').write_text('not a skill')
        result = install_skill('leafloom')
        self.assertTrue(self.target.is_file())
        self.assertFalse((skills / 'wiki-search').exists())
        self.assertFalse((skills / 'work-hub').exists())
        self.assertEqual((unrelated / 'SKILL.md').read_text(), 'keep')
        self.assertEqual((decoy / 'readme.txt').read_text(), 'not a skill')
        self.assertEqual(len(result['retired']), 2)
        restored = {Path(path).name.split('.', 1)[0]: Path(path) for path in result['retired']}
        self.assertEqual((restored['wiki-search'] / 'SKILL.md').read_text(), 'old wiki')
        self.assertEqual((restored['work-hub'] / 'notes.md').read_text(), 'keep in backup')
        self.assertEqual(install_skill('leafloom')['retired'], [])

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
        (self.home / '.agents').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            install_skill()
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlink_superseded_skill_is_rejected_after_install(self):
        skills = self.home / '.agents/skills'
        skills.mkdir(parents=True)
        outside = self.home / 'outside-work-hub'
        outside.mkdir()
        (outside / 'SKILL.md').write_text('linked')
        (skills / 'work-hub').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            install_skill('leafloom')
        self.assertTrue(self.target.is_file())
        self.assertTrue((skills / 'work-hub').is_symlink())
        self.assertEqual((outside / 'SKILL.md').read_text(), 'linked')

    def test_install_endpoint_requires_session_and_csrf(self):
        config = LocalConfig(self.home / 'state')
        static = self.home / 'static'
        static.mkdir()
        (static / 'index.html').write_text('<h1>Knowledge</h1>')
        app = create_app(config, start_background=False, static_dir=static)
        with TestClient(app, base_url='http://127.0.0.1:18080') as client:
            endpoint = '/api/skills/leafloom/install'
            self.assertEqual(client.post(endpoint).status_code, 401)
            client.get('/')
            client.cookies.set('vault_session', (config.directory / 'auth-token').read_text().strip())
            self.assertEqual(client.post(endpoint).status_code, 403)
            self.assertFalse(self.target.exists())
            response = client.post(endpoint, headers={'X-Vault-CSRF': app.state.csrf})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.target.read_bytes(), skill_source().read_bytes())
            self.assertTrue(client.get('/api/skills/leafloom').json()['up_to_date'])
            self.assertEqual(client.get('/api/skills/not-registered').status_code, 404)

    def test_work_hub_installs_all_resources_independently(self):
        target = self.home / '.agents/skills/leafloom'
        self.assertFalse(skill_status('leafloom')['installed'])
        result = install_skill('leafloom')
        self.assertEqual(result['path'], str(target / 'SKILL.md'))
        for name in ('references/workspace.md', 'references/imports.md',
                     'references/feishu.md', 'references/gitlab.md', 'references/settings.md',
                     'references/tasks-reports.md', 'references/feishu-sync.md',
                     'assets/workspace.base', 'scripts/leafloom.py', 'scripts/task_sync.py', 'scripts/feishu_sync.py'):
            self.assertEqual((target / name).read_bytes(), (skill_source('leafloom').parent / name).read_bytes())
        personal = target / 'personal.md'; personal.write_text('keep')
        script = target / 'scripts/task_sync.py'; script.write_text('personal script')
        self.assertFalse(skill_status('leafloom')['up_to_date'])
        updated = install_skill('leafloom')
        self.assertEqual(len(updated['backups']), 1)
        self.assertEqual(Path(updated['backup']).read_text(), 'personal script')
        self.assertEqual(personal.read_text(), 'keep')
        self.assertTrue(skill_status('leafloom')['up_to_date'])
        self.assertEqual(install_skill('leafloom')['backups'], [])

    def test_work_hub_preflight_rejects_linked_resource_before_writes(self):
        target = self.home / '.agents/skills/leafloom'
        target.mkdir(parents=True)
        (target / 'SKILL.md').write_text('unchanged')
        outside = self.home / 'outside'; outside.mkdir()
        (target / 'references').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            install_skill('leafloom')
        self.assertEqual((target / 'SKILL.md').read_text(), 'unchanged')
        self.assertEqual(list(outside.iterdir()), [])

    def test_work_hub_missing_resource_is_outdated(self):
        install_skill('leafloom')
        for resource in ('assets/workspace.base', 'references/feishu.md', 'references/gitlab.md'):
            with self.subTest(resource=resource):
                (self.home / '.agents/skills/leafloom' / resource).unlink()
                self.assertTrue(skill_status('leafloom')['installed'])
                self.assertFalse(skill_status('leafloom')['up_to_date'])
                self.assertTrue(install_skill('leafloom')['up_to_date'])

    def test_wheel_declares_every_installable_resource(self):
        manifest = tomllib.loads((Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text())
        includes = manifest['tool']['hatch']['build']['targets']['wheel']['force-include']
        for resource in skill_spec('leafloom')[1]:
            with self.subTest(resource=resource):
                path = f'leafloom/{resource}'
                self.assertEqual(includes[path], f'vault_rag/skills/{path}')

    def test_packaged_resource_links_are_rejected_before_installing(self):
        source = self.home / 'package'; source.mkdir()
        (source / 'SKILL.md').write_text('entry')
        (source / 'references').mkdir()
        outside = self.home / 'outside.md'; outside.write_text('outside')
        (source / 'references/knowledge.md').symlink_to(outside)
        with patch('vault_rag.skill_install.skill_source', return_value=source / 'SKILL.md'):
            with self.assertRaises(ValueError):
                install_skill('leafloom')
        self.assertFalse((self.home / '.agents').exists())

    def test_unknown_skill_never_constructs_user_paths(self):
        with self.assertRaises(ValueError):
            install_skill('../outside')
        self.assertFalse((self.home / '.agents').exists())
