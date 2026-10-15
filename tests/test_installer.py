"""Installer regressions without networking, models, desktop tasks or application imports."""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

spec = importlib.util.spec_from_file_location('desktop_installer', Path(__file__).resolve().parents[1] / 'scripts/installer.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='VaultRag 中文 安装 ')
        self.home = Path(self.temporary.name)
        self.repo = self.home / 'repository'
        (self.repo / 'scripts').mkdir(parents=True)
        source = Path(__file__).resolve().parents[1]
        (self.repo / 'scripts/runtimes.json').write_bytes((source / 'scripts/runtimes.json').read_bytes())
        for name in ('pyproject.toml', 'uv.lock', 'web/package.json', 'web/package-lock.json', 'web/src/main.tsx'):
            path = self.repo / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(name)
        self.setup = installer.Installer(self.repo, self.home / 'state', key='windows-x64')
        self.calls = []

    def tearDown(self):
        self.temporary.cleanup()

    def web(self):
        root = self.repo / 'vault_rag/static'
        (root / 'assets').mkdir(parents=True, exist_ok=True)
        (root / 'index.html').write_text('<script src="/assets/main.js"></script>')
        (root / 'assets/main.js').write_text('console.log("web")')

    def model(self):
        root = self.setup.state / 'models/bge-m3'; root.mkdir(parents=True, exist_ok=True)
        names = ('config.json', 'tokenizer_config.json', 'tokenizer.json', 'model.safetensors')
        for name in names: (root / name).write_text('model')
        installer.atomic_json(self.setup.state / 'models/model-lock.json', {
            'model': 'BAAI/bge-m3', 'revision': 'pinned', 'files': {name: {'size': 5} for name in names}})

    def run_stage(self, args, **_):
        args = [str(x) for x in args]; self.calls.append(args)
        if 'build' in args: self.web()
        if 'sync' in args:
            self.assertTrue((self.repo / 'vault_rag/static/index.html').exists(), 'Project installed before web build')
            self.setup.python.parent.mkdir(parents=True, exist_ok=True); self.setup.python.touch()
        if 'model-prepare' in args: self.model()

    def install(self):
        with patch.object(self.setup, 'node', return_value=['node', 'npm-cli.js']), patch.object(self.setup, 'stop_owned'), patch.object(self.setup, 'run', side_effect=self.run_stage):
            self.setup.install()

    def test_clean_install_builds_web_before_project_and_only_marks_success_after_verify(self):
        self.assertFalse((self.repo / '.venv').exists())
        self.assertFalse((self.repo / 'vault_rag/static').exists())
        self.assertFalse(self.setup.runtime.exists())
        self.install()
        sync = next(args for args in self.calls if 'sync' in args)
        self.assertIn('--locked', sync); self.assertIn('--no-dev', sync)
        self.assertEqual(self.calls[-1][-1], 'verify')
        self.assertTrue(self.setup.marker.exists())
        self.assertTrue((self.setup.state / 'windows-install.json').exists())

    def test_failed_stage_has_no_success_marker_and_retry_reuses_finished_web(self):
        def fail_sync(args, **kwargs):
            if 'sync' in [str(x) for x in args]: raise RuntimeError('simulated sync failure')
            return self.run_stage(args, **kwargs)
        with patch.object(self.setup, 'node', return_value=['node', 'npm-cli.js']), patch.object(self.setup, 'stop_owned'), patch.object(self.setup, 'run', side_effect=fail_sync):
            with self.assertRaises(RuntimeError): self.setup.install()
        self.assertFalse(self.setup.marker.exists())
        self.assertTrue((self.repo / 'vault_rag/static/index.html').exists())
        self.calls.clear(); self.install()
        self.assertFalse(any('build' in args or 'ci' in args for args in self.calls))

    def test_missing_web_after_build_never_installs_project(self):
        with patch.object(self.setup, 'node', return_value=['node', 'npm-cli.js']), patch.object(self.setup, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'index.html'): self.setup.install()
        self.assertFalse(any('sync' in call.args[0] for call in run.call_args_list))

    def test_backup_preserves_all_files_and_retries_do_not_overwrite(self):
        root = self.repo / '.venv'; root.mkdir(); (root / 'keep').write_bytes(b'old environment')
        data = self.repo / 'config.json'; data.write_bytes(b'keep project data')
        with patch.object(self.setup, 'compatible', return_value=False):
            self.setup.prepare_environment(); self.setup.prepare_environment()
            root.mkdir(); (root / 'other').write_bytes(b'next environment'); self.setup.prepare_environment()
        backups = list(self.repo.glob('.venv-backup-*'))
        self.assertEqual(len(backups), 2)
        self.assertEqual(next(p / 'keep' for p in backups if (p / 'keep').exists()).read_bytes(), b'old environment')
        self.assertEqual(data.read_bytes(), b'keep project data')

    def test_compatible_environment_is_reused(self):
        (self.repo / '.venv').mkdir()
        with patch.object(self.setup, 'compatible', return_value=True),patch.object(self.setup, 'run'): self.setup.prepare_environment()
        self.assertTrue((self.repo / '.venv').exists()); self.assertEqual(list(self.repo.glob('.venv-backup-*')), [])

    def test_compatible_python_with_missing_dependencies_is_preserved_for_sync(self):
        root=self.repo/'.venv';root.mkdir();(root/'keep').write_text('damaged environment')
        with patch.object(self.setup,'compatible',return_value=True),patch.object(self.setup,'run',side_effect=RuntimeError('native DLL missing')):
            self.setup.prepare_environment()
        self.assertEqual((root/'keep').read_text(),'damaged environment')
        self.assertEqual(list(self.repo.glob('.venv-backup-*')), [])

    def test_install_ready_environment_skips_install_and_preserves_marker(self):
        self.install()
        previous = self.setup.marker.read_bytes()
        with patch.object(self.setup, 'ready', return_value=True), patch.object(self.setup, 'run') as run, patch.object(self.setup, 'install') as install:
            self.assertEqual(self.setup.execute('install', no_open=True), 0)
            install.assert_not_called()
            self.assertEqual(run.call_args.args[0][-1], 'check')
        self.assertEqual(self.setup.marker.read_bytes(), previous)

    def test_model_repair_skips_unchanged_web_and_python_dependencies(self):
        self.install()
        (self.setup.state / 'models/bge-m3/model.safetensors').unlink(missing_ok=True)
        self.calls.clear()
        with patch.object(self.setup, 'compatible', return_value=True), patch.object(self.setup, 'node') as node, patch.object(self.setup, 'stop_owned'), patch.object(self.setup, 'run', side_effect=self.run_stage):
            self.setup.install()
            node.assert_not_called()
        self.assertFalse(any('sync' in args or 'build' in args or 'ci' in args for args in self.calls))
        self.assertFalse(any('model-prepare' in args for args in self.calls))
        self.assertFalse(self.setup.model_ready())

    def test_web_update_skips_python_sync_and_model_prepare(self):
        self.install()
        (self.repo / 'web/src/main.tsx').write_text('updated website')
        self.calls.clear()
        with patch.object(self.setup, 'compatible', return_value=True): self.install()
        self.assertTrue(any('build' in args for args in self.calls))
        self.assertFalse(any('sync' in args or 'model-prepare' in args for args in self.calls))

    def test_dependency_update_syncs_without_rebuilding_web_or_model(self):
        self.install()
        (self.repo / 'uv.lock').write_text('updated lock')
        self.calls.clear()
        with patch.object(self.setup, 'compatible', return_value=True): self.install()
        self.assertTrue(any('sync' in args for args in self.calls))
        self.assertFalse(any('build' in args or 'ci' in args or 'model-prepare' in args for args in self.calls))

    def test_legacy_install_model_repair_reuses_verified_dependencies(self):
        self.install()
        (self.setup.state / 'python-install.json').unlink()
        (self.setup.state / 'models/bge-m3/model.safetensors').unlink(missing_ok=True)
        self.calls.clear()
        with patch.object(self.setup, 'compatible', return_value=True): self.install()
        self.assertFalse(any('sync' in args for args in self.calls))
        self.assertFalse(any('model-prepare' in args for args in self.calls))

    def test_missing_packages_sync_without_replacing_compatible_environment(self):
        self.install()
        keep = self.repo / '.venv/keep'; keep.write_text('preserve')
        self.calls.clear()
        synced = False
        def missing(args, **kwargs):
            nonlocal synced
            if 'sync' in args: synced = True
            if args[-1] in ('check', 'check-runtime') and not synced:
                raise RuntimeError('dependency missing')
            return self.run_stage(args, **kwargs)
        with patch.object(self.setup, 'compatible', return_value=True), patch.object(self.setup, 'stop_owned'), patch.object(self.setup, 'run', side_effect=missing):
            self.setup.install()
        sync = next(args for args in self.calls if 'sync' in args)
        self.assertNotIn('--reinstall', sync)
        self.assertEqual(keep.read_text(), 'preserve')

    def test_broken_native_packages_force_repair_and_recheck(self):
        self.install()
        self.calls.clear()
        synced = False
        def damaged(args, **kwargs):
            nonlocal synced
            if 'sync' in args: synced = True
            if args[-1] == 'check' and not synced:
                raise RuntimeError('native library damaged')
            return self.run_stage(args, **kwargs)
        with patch.object(self.setup, 'compatible', return_value=True), patch.object(self.setup, 'stop_owned'), patch.object(self.setup, 'run', side_effect=damaged):
            self.setup.install()
        sync = next(args for args in self.calls if 'sync' in args)
        self.assertIn('--reinstall', sync)
        self.assertTrue(self.setup.marker.exists())

    def test_failed_backup_keeps_original(self):
        root = self.repo / '.venv'; root.mkdir(); (root / 'keep').write_bytes(b'old')
        with patch.object(self.setup, 'compatible', return_value=False), patch.object(Path, 'rename', side_effect=PermissionError('locked')):
            with self.assertRaisesRegex(RuntimeError, '原文件已保留'): self.setup.prepare_environment()
        self.assertEqual((root / 'keep').read_bytes(), b'old')

    def test_ready_checks_dependencies_assets_and_location_but_model_is_optional(self):
        self.install()
        with patch.object(self.setup, 'compatible', return_value=True), patch.object(self.setup, 'run'):
            self.assertTrue(self.setup.ready())
            (self.repo / 'vault_rag/static/assets/main.js').unlink(); self.assertFalse(self.setup.ready())
            self.web(); self.model()
            (self.setup.state / 'models/bge-m3/model.safetensors').write_text('truncated')
            self.assertTrue(self.setup.ready())
            self.assertFalse(self.setup.model_ready())
            with patch.object(self.setup, 'run', side_effect=RuntimeError('dependency missing')): self.assertFalse(self.setup.ready())
            value = json.loads(self.setup.marker.read_text()); value['repository'] = 'old repository'
            installer.atomic_json(self.setup.marker, value); self.assertFalse(self.setup.ready())

    def test_input_changes_invalidate_web_build(self):
        initial = self.setup.input_hash(); (self.repo / 'web/src/main.tsx').write_text('changed')
        self.assertNotEqual(initial, self.setup.input_hash())

    def test_backend_and_launcher_changes_do_not_rebuild_web_or_reinstall(self):
        initial = self.setup.input_hash(); web_hash = self.setup.web_input_hash()
        for name in ('vault_rag/windows_tray.py', 'scripts/windows/launch.ps1'):
            path = self.repo / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('changed')
        self.assertEqual(initial, self.setup.input_hash())
        self.assertEqual(web_hash, self.setup.web_input_hash())
        (self.repo / 'uv.lock').write_text('new dependency lock')
        self.assertNotEqual(initial, self.setup.input_hash())
        self.assertEqual(web_hash, self.setup.web_input_hash())

    def test_stop_failure_preserves_previous_success_and_web_cache(self):
        self.install()
        previous = self.setup.marker.read_bytes(); self.calls.clear()
        with patch.object(self.setup, 'node', return_value=['node', 'npm-cli.js']), patch.object(self.setup, 'run', side_effect=self.run_stage), patch.object(self.setup, 'stop_owned', side_effect=RuntimeError('stop timeout')):
            with self.assertRaisesRegex(RuntimeError, 'stop timeout'): self.setup.install()
        self.assertEqual(previous, self.setup.marker.read_bytes())
        self.assertFalse(any('build' in args or 'ci' in args for args in self.calls))

    def test_open_checks_once_and_requests_setup_without_silent_install(self):
        with patch.object(self.setup, 'ready', return_value=False) as ready, patch.object(self.setup, 'install') as install:
            self.assertEqual(self.setup.execute('open', no_install=True), 3)
            ready.assert_called_once(); install.assert_not_called()
        with patch.object(self.setup, 'ready', return_value=True) as ready, patch.object(self.setup, 'run') as run:
            self.assertEqual(self.setup.execute('open', no_install=True), 0)
            ready.assert_called_once(); self.assertEqual(run.call_args.args[0][-1], 'open')

    def test_download_reuses_verified_archive_and_rejects_corrupt_bytes(self):
        self.setup.runtime.mkdir(parents=True)
        value = b'archive'; checksum = hashlib.sha256(value).hexdigest()
        spec = {'url': 'https://example.invalid/runtime.zip', 'sha256': checksum}
        archive = self.setup.runtime / 'runtime.zip'; archive.write_bytes(value)
        with patch.object(installer.urllib.request, 'urlopen') as fetch:
            self.assertEqual(self.setup.download(spec), archive); fetch.assert_not_called()
        archive.write_bytes(b'old corrupt cache')
        import io
        with patch.object(installer.urllib.request, 'urlopen', return_value=io.BytesIO(b'bad download')):
            with self.assertRaisesRegex(RuntimeError, 'SHA256'): self.setup.download(spec)
        self.assertEqual(archive.read_bytes(), b'old corrupt cache')
        self.assertFalse(archive.with_name(archive.name + '.part').exists())

    def test_command_retries_only_transient_errors_with_full_output(self):
        program = "import pathlib,sys; p=pathlib.Path(sys.argv[1]); n=int(p.read_text()) if p.exists() else 0; p.write_text(str(n+1)); print('temporary connection reset' if n<2 else 'ok'); sys.exit(1 if n<2 else 0)"
        counter = self.home / 'counter'
        with patch.object(installer.time, 'sleep'):
            self.assertEqual(self.setup.run([sys.executable, '-c', program, counter], capture=True, retry=True), 'ok')
        self.assertEqual(counter.read_text(), '3')
        with self.assertRaisesRegex(RuntimeError, 'Forced include not found'):
            self.setup.run([sys.executable, '-c', "import sys; print('Forced include not found'); sys.exit(1)"], retry=True)

    def test_mac_menu_installs_without_bundle_and_preserves_login_preference(self):
        import plistlib
        import runpy
        source = Path(__file__).resolve().parents[1]
        state = self.home / 'state'
        agent = self.home / 'Library/LaunchAgents/com.djhuang.vault-rag.menubar.plist'
        agent.parent.mkdir(parents=True)
        agent.write_bytes(plistlib.dumps({'RunAtLoad': False}))
        with patch('pathlib.Path.home', return_value=self.home), \
             patch('vault_rag.platform_support.state_directory', return_value=state), \
             patch('os.getuid', return_value=501, create=True), \
             patch('subprocess.run') as run:
            runpy.run_path(str(source / 'scripts/macos/install_menu.py'), run_name='__main__')
        data = plistlib.loads(agent.read_bytes())
        self.assertFalse(data['RunAtLoad'])
        self.assertFalse(data['KeepAlive'])
        self.assertEqual(data['ProgramArguments'], ['/bin/bash', str(source / 'scripts/macos/start_menu.sh'), str(source), str(state)])
        self.assertEqual(data['EnvironmentVariables']['VAULT_RAG_HOME'], str(state))
        self.assertTrue((state / 'logs').is_dir())
        self.assertEqual([call.args[0][1] for call in run.call_args_list], ['bootout', 'bootstrap', 'kickstart'])
        self.assertFalse((self.home / 'Applications').exists())

    def test_concurrent_lock_and_release(self):
        path = self.home / 'install.lock'
        with installer.InstallLock(path):
            with self.assertRaises(RuntimeError):
                with installer.InstallLock(path): pass
        with installer.InstallLock(path): pass


if __name__ == '__main__': unittest.main()
