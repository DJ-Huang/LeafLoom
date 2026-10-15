from __future__ import annotations
import json
import plistlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from vault_rag.desktop import LegacyMigration, installed_app, forward
from vault_rag.local_state import LocalConfig


class DesktopMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.config = LocalConfig(self.home / 'state')
        (self.config.directory / 'auth-token').write_text('preserve-existing-token')
        self.config.save({'port': 19321})

    def tearDown(self): self.temp.cleanup()

    def test_missing_or_stale_desktop_marker_leaves_source_launch_usable(self):
        self.assertIsNone(installed_app(self.config.directory))
        (self.config.directory / 'desktop-install.json').write_text(json.dumps({'schema': 1, 'executable': str(self.home / 'gone.exe')}))
        self.assertFalse(forward('open', self.config.directory))

    def test_valid_marker_forwards_without_a_browser_or_shell(self):
        exe = self.home / 'LeafLoom.exe'; exe.touch()
        (self.config.directory / 'desktop-install.json').write_text(json.dumps({'schema': 1, 'executable': str(exe)}))
        with patch('vault_rag.desktop.subprocess.Popen') as spawn:
            self.assertTrue(forward('stop', self.config.directory))
        self.assertEqual(spawn.call_args.args[0], [str(exe), '--quit'])
        self.assertFalse(spawn.call_args.kwargs.get('shell', False))

    def test_windows_disable_is_backed_up_and_stop_failure_restores_task(self):
        from vault_rag import windows_service as service
        xml = b'''<?xml version="1.0"?><Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers><Principals><Principal><UserId>S-1-test</UserId></Principal></Principals></Task>'''
        actions = []
        def scheduler(*args, **kwargs):
            actions.append(args)
            if args[0] == '/Change':
                receipt = json.loads((self.config.directory / 'desktop-migration.json').read_text())
                self.assertEqual(receipt['state'], 'pending')
                self.assertEqual(Path(receipt['agents'][0]['backup']).read_bytes(), xml)
            return SimpleNamespace(returncode=0, stdout=xml)
        migration = LegacyMigration(self.config)
        with patch('vault_rag.desktop.sys.platform', 'win32'), patch.object(service, 'scheduler', side_effect=scheduler), patch.object(service, 'task_name', side_effect=lambda _, role: 'owned-' + role), patch.object(service, 'task_active', return_value=True), patch('vault_rag.platform_support.current_sid', return_value='S-1-test'), patch.object(service, 'wait_stopped', side_effect=RuntimeError('stop failed')):
            with self.assertRaisesRegex(RuntimeError, 'stop failed'): migration.begin()
        self.assertTrue(any(a[0] == '/Create' for a in actions))
        self.assertTrue(any(a[0] == '/Run' for a in actions))
        self.assertEqual((self.config.directory / 'auth-token').read_text(), 'preserve-existing-token')
        self.assertEqual(self.config.data['port'], 19321)
        self.assertEqual(json.loads(migration.receipt.read_text())['state'], 'rolled-back')

    def test_task_owned_by_another_user_is_never_disabled(self):
        from vault_rag import windows_service as service
        result = SimpleNamespace(returncode=0, stdout=b'<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><Principals><Principal><UserId>other-user</UserId></Principal></Principals></Task>')
        with patch('vault_rag.desktop.sys.platform', 'win32'), patch.object(service, 'scheduler', return_value=result) as scheduler, patch.object(service, 'task_name', return_value='known'), patch('vault_rag.platform_support.current_sid', return_value='my-user'):
            with self.assertRaisesRegex(RuntimeError, 'another user'): LegacyMigration(self.config).begin()
        self.assertFalse(any(a.args[0] == '/Change' for a in scheduler.call_args_list))

    def test_windows_piped_utf8_xml_with_utf16_declaration_is_restorable(self):
        from vault_rag import windows_service as service
        import xml.etree.ElementTree as ET
        xml = b'<?xml version="1.0" encoding="UTF-16"?><Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><Principals><Principal><UserId>my-user</UserId></Principal></Principals></Task>'
        migration = LegacyMigration(self.config)
        with patch('vault_rag.desktop.sys.platform', 'win32'), patch.object(service, 'scheduler', return_value=SimpleNamespace(returncode=0, stdout=xml)), patch.object(service, 'task_name', side_effect=lambda _, role: 'owned-' + role), patch.object(service, 'task_active', return_value=True), patch('vault_rag.platform_support.current_sid', return_value='my-user'), patch.object(service, 'wait_stopped'):
            self.assertTrue(migration.begin())
        for agent in migration.data['agents']:
            ET.fromstring(Path(agent['backup']).read_bytes())

    def test_commit_is_persistent_and_not_repeated_on_next_launch(self):
        migration = LegacyMigration(self.config)
        with patch.object(migration, '_windows'), patch.object(migration, '_macos'):
            self.assertFalse(migration.begin()); migration.commit()
        next_launch = LegacyMigration(self.config)
        with patch.object(next_launch, '_windows') as windows, patch.object(next_launch, '_macos') as mac:
            self.assertFalse(next_launch.begin()); next_launch.rollback()
            windows.assert_not_called(); mac.assert_not_called()
        self.assertEqual(json.loads(migration.receipt.read_text())['state'], 'committed')

    def test_rollback_refuses_backup_outside_private_backup_directory(self):
        path = self.home / 'outside.xml'; path.write_text('do not touch')
        migration = LegacyMigration(self.config)
        migration.data = {'state': 'pending', 'agents': [{'kind': 'windows', 'role': 'service', 'backup': str(path), 'active': True}]}
        with self.assertRaisesRegex(RuntimeError, 'Invalid legacy backup'): migration.rollback()
        self.assertEqual(path.read_text(), 'do not touch')

    def test_macos_ignores_other_state_and_restores_owned_agent(self):
        agents = self.home / 'Library/LaunchAgents'; agents.mkdir(parents=True)
        owned = agents / 'com.djhuang.vault-rag.plist'
        foreign = agents / 'com.djhuang.vault-rag.menubar.plist'
        content = plistlib.dumps({'RunAtLoad': True, 'KeepAlive': True, 'EnvironmentVariables': {'VAULT_RAG_HOME': str(self.config.directory)}})
        owned.write_bytes(content)
        foreign_content = plistlib.dumps({'RunAtLoad': True, 'EnvironmentVariables': {'VAULT_RAG_HOME': str(self.home / 'other-state')}})
        foreign.write_bytes(foreign_content)
        migration = LegacyMigration(self.config)
        with patch('vault_rag.desktop.sys.platform', 'darwin'), patch('vault_rag.desktop.Path.home', return_value=self.home), patch('vault_rag.desktop.os.getuid', return_value=501, create=True), patch('vault_rag.desktop.subprocess.run', return_value=SimpleNamespace(returncode=0)), patch('vault_rag.local_state.preserve_file_mode'):
            self.assertTrue(migration.begin())
            self.assertFalse(plistlib.loads(owned.read_bytes())['RunAtLoad'])
            self.assertEqual(foreign.read_bytes(), foreign_content)
            migration.rollback()
        self.assertEqual(owned.read_bytes(), content)
        self.assertEqual(foreign.read_bytes(), foreign_content)


if __name__ == '__main__': unittest.main()
