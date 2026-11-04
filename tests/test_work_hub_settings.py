"""Shared office preferences, using fictional notes and no office connections."""
import tempfile
import unittest
from pathlib import Path

from starlette.testclient import TestClient

from vault_rag.knowledge import Runtime
from vault_rag.local_state import ConflictError, LocalConfig
from vault_rag.note_operations import NoteOperations
from vault_rag.web_server import create_app
from vault_rag.work_hub import WorkHubSettings


class WorkHubSettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.root = self.home / 'vault'; self.root.mkdir()
        self.config = LocalConfig(self.home / 'state')
        self.config.save({'root': str(self.root), 'include_roots': []})
        runtime = Runtime(self.config); self.addCleanup(runtime.stop)
        self.notes = NoteOperations(self.config, runtime)
        self.settings = WorkHubSettings(self.notes)

    def save(self, provider, snapshot=None):
        before = snapshot or self.settings.read()
        selection = {'office_providers': provider} if isinstance(provider, list) else {'office_provider': provider}
        return self.settings.write(root=before['root'], workspace_revision=before['workspace_revision'],
                                   revision=before['revision'], **selection)

    def test_unconfigured_read_does_not_create_notes(self):
        result = self.settings.read()
        self.assertEqual(result['office_provider'], 'auto')
        self.assertFalse(result['configured'])
        self.assertFalse((self.root / '工作中枢').exists())

    def test_save_preferences_without_granting_access_or_initializing_database(self):
        for provider in ('feishu', 'local', 'dingtalk', 'wecom', 'notion', 'future-office'):
            with self.subTest(provider=provider):
                result = self.save(provider)
                note = self.notes.files.read(result['path'])
                self.assertEqual(note['metadata']['work_hub']['office_providers'], [provider])
                self.assertEqual(result['implemented'], provider in ('local', 'feishu'))
        self.assertEqual(self.config.data['include_roots'], [])
        self.assertNotIn('feishu', self.config.data)
        self.assertFalse((self.root / '工作中枢/工作台.base').exists())

    def test_ui_and_note_edits_share_configuration_and_preserve_personal_content(self):
        saved = self.save('feishu')
        path = self.root / saved['path']
        path.write_text('''---
personal_flag: keep
work_hub:
  schema_version: 1
  # Personal configuration comment
  office_provider: feishu
  future_option: keep
---

# Personal instructions
Keep my notes unchanged.
''')
        saved = self.save('local')
        text = path.read_text()
        self.assertIn('# Personal configuration comment', text)
        self.assertIn('future_option: keep', text)
        self.assertIn('personal_flag: keep', text)
        self.assertTrue(text.endswith('# Personal instructions\nKeep my notes unchanged.\n'))
        # A conversational client uses the existing version-checked note tool.
        note = self.notes.files.read(saved['path'])
        preferences = {**note['metadata']['work_hub'], 'office_providers': ['feishu', 'notion']}
        self.notes.properties(saved['path'], saved['workspace_revision'], note['etag'],
                              {'work_hub': preferences})
        self.assertEqual(self.settings.read()['office_providers'], ['feishu', 'notion'])

    def test_multi_select_round_trip_and_legacy_read_is_non_mutating(self):
        saved = self.save(['feishu', 'notion', 'feishu'])
        self.assertEqual(saved['office_providers'], ['feishu', 'notion'])
        self.assertIsNone(saved['office_provider'])
        self.assertFalse(saved['implemented'])
        note = self.notes.files.read(saved['path'])
        self.assertEqual(note['metadata']['work_hub']['office_providers'], ['feishu', 'notion'])
        self.assertNotIn('office_provider', note['metadata']['work_hub'])
        with self.assertRaises(ConflictError):
            self.save('feishu')  # An old client cannot silently collapse a multi-selection.
        self.assertEqual(self.settings.read()['office_providers'], ['feishu', 'notion'])
        self.assertEqual(self.save(['feishu'])['office_providers'], ['feishu'])

        path = self.root / saved['path']
        legacy = '---\nwork_hub:\n  schema_version: 1\n  office_provider: wecom\n---\n\nPersonal notes\n'
        path.write_text(legacy)
        self.assertEqual(self.settings.read()['office_providers'], ['wecom'])
        self.assertEqual(path.read_text(), legacy)
        self.save(['wecom', 'feishu'])
        self.assertIn('Personal notes', path.read_text())
        self.assertEqual(self.settings.read()['office_providers'], ['wecom', 'feishu'])

    def test_modes_are_exclusive_and_empty_or_invalid_lists_preserve_selection(self):
        self.save(['feishu', 'notion'])
        for providers in ([], ['auto', 'feishu'], ['local', 'notion'], ['auto', 'local'],
                          ['feishu', None], ['Bad ID']):
            with self.subTest(providers=providers), self.assertRaises(ValueError):
                self.save(providers)
            self.assertEqual(self.settings.read()['office_providers'], ['feishu', 'notion'])
        self.assertEqual(self.save(['local'])['office_providers'], ['local'])
        self.assertEqual(self.save(['auto'])['office_providers'], ['auto'])

    def test_stale_snapshot_never_overwrites_concurrent_edits_or_creation(self):
        empty = self.settings.read()
        original = self.save('feishu')
        for snapshot in (empty, original):
            self.save('notion')
            with self.assertRaises(ConflictError):
                self.save('local', snapshot)
            self.assertEqual(self.settings.read()['office_provider'], 'notion')

    def test_workspace_switch_rejects_old_snapshot_and_isolates_preferences(self):
        previous = self.save('feishu')
        other = self.home / 'other-vault'; other.mkdir()
        self.config.save({'root': str(other)})
        with self.assertRaises(ConflictError):
            self.save('local', previous)
        self.assertEqual(self.settings.read()['office_provider'], 'auto')
        self.assertFalse((other / '工作中枢').exists())
        with self.assertRaises(ConflictError):
            self.settings.read(root=str(self.root))

    def test_custom_hub_directory_uses_existing_write_target(self):
        self.config.save({'write_targets': {**self.config.data['write_targets'], 'work_hub': 'Projects/Hub'}})
        saved = self.save('feishu')
        self.assertEqual(saved['path'], 'Projects/Hub/配置.md')
        self.assertFalse((self.root / '工作中枢').exists())

    def test_invalid_or_unrelated_configuration_is_preserved(self):
        path = self.root / '工作中枢/配置.md'; path.parent.mkdir()
        for text in ('My unrelated note\n', '---\nwork_hub: [broken\n---\n',
                     '---\nwork_hub:\n  schema_version: 2\n---\n',
                     '---\nwork_hub:\n  office_provider: []\n---\n'):
            with self.subTest(text=text):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    self.settings.read()
                self.assertEqual(path.read_text(), text)

    def test_invalid_destinations_and_provider_values_do_not_create_notes(self):
        for value in ('', '../escape', 'Notion', [], None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.save(value)
        self.assertFalse((self.root / '工作中枢').exists())
        outside = self.home / 'outside'; outside.mkdir()
        (self.root / 'Linked').symlink_to(outside, target_is_directory=True)
        self.config.save({'write_targets': {'work_hub': 'Linked'}})
        with self.assertRaises(ValueError):
            self.settings.read()
        self.assertEqual(list(outside.iterdir()), [])
        (self.root / 'File').write_text('keep')
        self.config.save({'write_targets': {'work_hub': 'File/Subfolder'}})
        with self.assertRaises(ValueError):
            self.settings.read()


class WorkHubSettingsApiTests(unittest.TestCase):
    def test_authenticated_read_write_and_conflict_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); root = home / 'vault'; root.mkdir()
            config = LocalConfig(home / 'state'); config.save({'root': str(root)})
            static = home / 'static'; static.mkdir(); (static / 'index.html').write_text('Test')
            app = create_app(config, start_background=False, static_dir=static)
            with TestClient(app, base_url='http://127.0.0.1:18080') as client:
                endpoint = '/api/work-hub/settings'
                self.assertEqual(client.get(endpoint).status_code, 401)
                client.cookies.set('vault_session', (config.directory / 'auth-token').read_text().strip())
                response = client.get(endpoint)
                self.assertEqual(response.status_code, 200)
                current = response.json()
                body = {key: current[key] for key in ('root', 'workspace_revision', 'revision')}
                body['office_provider'] = 'feishu'
                self.assertEqual(client.put(endpoint, json=body).status_code, 403)
                headers = {'X-Vault-CSRF': app.state.csrf}
                response = client.put(endpoint, json=body, headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertTrue(response.json()['saved'])
                self.assertEqual(client.get(endpoint).json()['office_provider'], 'feishu')
                self.assertEqual(client.put(endpoint, json=body, headers=headers).status_code, 409)
                multi = {key: response.json()[key] for key in ('root', 'workspace_revision', 'revision')}
                multi['office_providers'] = ['feishu', 'notion']
                response = client.put(endpoint, json=multi, headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(client.get(endpoint).json()['office_providers'], ['feishu', 'notion'])
                legacy = {key: response.json()[key] for key in ('root', 'workspace_revision', 'revision')}
                self.assertEqual(client.put(endpoint, json={**legacy, 'office_provider': 'feishu'}, headers=headers).status_code, 409)
                self.assertEqual(client.get(endpoint, params={'root': str(home / 'other')}).status_code, 409)
                body = {**body, 'revision': response.json()['revision'], 'root': None}
                self.assertEqual(client.put(endpoint, json=body, headers=headers).status_code, 409)
