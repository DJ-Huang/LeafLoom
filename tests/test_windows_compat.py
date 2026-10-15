from __future__ import annotations
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
import urllib.error
import xml.etree.ElementTree as ET

from vault_rag.local_state import LocalConfig, Files, atomic_write, relative, under
from vault_rag import platform_support as platform
from vault_rag import service_control as service
from vault_rag import windows_service as windows


class WindowsCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.directory=Path(self.temp.name).resolve()
        self.config=LocalConfig(self.directory/'state')
        self.root=self.directory/'中文 知识库';(self.root/'RAG/Notes').mkdir(parents=True)
        self.config.save({'root':str(self.root)})

    def tearDown(self):self.temp.cleanup()

    def test_existing_file_save_without_posix_permissions_and_crlf_history(self):
        path=self.root/'RAG/Notes/中文 空格.md'
        original='---\r\nname: 中文\r\n---\r\n正文\r\n'.encode('utf-8')
        path.write_bytes(original)
        files=Files(self.config);read=files.read('RAG/Notes/中文 空格.md')
        with patch.object(platform,'is_windows',return_value=True), patch('vault_rag.local_state.is_windows',return_value=True):
            with patch.object(os,'fchmod',side_effect=AssertionError('POSIX permissions called'),create=True):
                files.save(read['path'],'修改\n正文\n',read['etag'])
                self.assertEqual(path.read_bytes(),'修改\r\n正文\r\n'.encode('utf-8'))
                history=files.records('history',read['path'])
                files.restore('history',history[0]['id'])
                self.assertEqual(path.read_bytes(),original)

    def test_failed_atomic_replace_keeps_original_and_cleans_temporary(self):
        path=self.directory/'中文.txt';path.write_bytes(b'original')
        with patch('vault_rag.local_state.os.replace',side_effect=PermissionError('file locked')):
            with self.assertRaises(PermissionError):atomic_write(path,b'new')
        self.assertEqual(path.read_bytes(),b'original')
        self.assertFalse(list(self.directory.glob('.*.tmp')))

    def test_windows_names_and_case_insensitive_scope(self):
        with patch('vault_rag.local_state.is_windows',return_value=True), patch.object(platform,'is_windows',return_value=True):
            for value in ['C:\\outside','C:outside','\\\\server\\share','../x','RAG/CON.md','RAG/NUL',
                          'RAG/com1.txt','RAG/aux.txt','RAG/a.md:secret','RAG/name.','RAG/name ',
                          'RAG/a?.md','RAG/a\x01.md','RAG/a*.md']:
                with self.subTest(path=value),self.assertRaises(ValueError):relative(value)
            self.assertEqual(relative('RAG\\Notes\\中文.md'),'RAG/Notes/中文.md')
            self.assertTrue(under('rag/NOTES/a.md','RAG/Notes'))
            self.assertFalse(under('RAG/Notes-other/a.md','rag/notes'))
            self.assertEqual(Files(self.config).resolve('a','',paths={'RAG/Notes/A.md'}),['RAG/Notes/A.md'])
            self.config.save({'exclude_roots':['rag/notes']})
            self.assertFalse(self.config.selected('RAG/Notes/a.md'))
            with self.assertRaises(ValueError):self.config.path_for('NODE_MODULES/a.txt')

    def test_junction_is_rejected_by_tree_and_path_access(self):
        outside=self.directory/'outside';outside.mkdir()
        fake=self.root/'escape';fake.mkdir()
        def link(path):return path==fake
        with patch('vault_rag.local_state.is_link',side_effect=link):
            with self.assertRaises(ValueError):self.config.path_for('escape/private.md')
            self.assertNotIn('escape',[x['name'] for x in Files(self.config).tree()])
            self.assertFalse(list(Files(self.config).walk()))

    def test_private_home_override_and_default(self):
        with patch.object(platform,'is_windows',return_value=True),patch.dict(os.environ,{'LOCALAPPDATA':str(self.directory)},clear=True):
            self.assertEqual(platform.state_directory(),self.directory/'VaultRag')
            with patch.dict(os.environ,{'VAULT_RAG_HOME':str(self.directory/'custom')}):
                self.assertEqual(platform.state_directory(),self.directory/'custom')

    def test_windows_acl_is_current_user_and_system_not_chmod(self):
        directory=self.directory/'acl'
        with patch.object(platform,'is_windows',return_value=True),patch.object(platform,'powershell',return_value=SimpleNamespace(returncode=0,stdout='')),patch.object(platform,'current_sid',return_value='S-1-5-21-123'),patch.object(platform,'hidden_process_options',return_value={}),patch.object(platform.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            platform.protect_private_directory(directory)
        args=run.call_args.args[0]
        self.assertIn('/inheritance:r',args);self.assertIn('*S-1-5-21-123:(OI)(CI)F',args)
        self.assertIn('*S-1-5-18:(OI)(CI)F',args)

    def test_already_private_directory_does_not_reapply_inheritable_acl(self):
        with patch.object(platform,'is_windows',return_value=True),patch.object(platform,'powershell',return_value=SimpleNamespace(returncode=0,stdout='private\n')),patch.object(platform.subprocess,'run') as run:
            platform.protect_private_directory(self.directory/'private')
            run.assert_not_called()

    def test_msvc_dll_paths_are_app_local_and_handles_are_retained(self):
        prefix=self.directory/'venv';scripts=prefix/'Scripts';scripts.mkdir(parents=True)
        (prefix/'msvcp140.dll').touch();(scripts/'msvcp140.dll').touch()
        handles=[]
        with patch.object(platform,'is_windows',return_value=True),patch.object(platform.sys,'prefix',str(prefix)),patch.object(platform,'_DLL_DIRECTORIES',handles),patch.object(os,'add_dll_directory',side_effect=[Mock(),Mock()],create=True) as add:
            platform.prepare_windows_runtime();platform.prepare_windows_runtime()
            self.assertEqual(add.call_count,2);self.assertEqual(len(handles),2)
            self.assertEqual(add.call_args_list[0].args,(str(scripts),))
            self.assertEqual(add.call_args_list[1].args,(str(prefix),))

    def test_task_xml_least_privilege_infinite_runtime_retry_and_unicode_arguments(self):
        python=self.directory/'中文 环境/python.exe';python.parent.mkdir();python.touch()
        python.with_name('pythonw.exe').touch()
        with patch.object(windows,'current_sid',return_value='S-1-5-21-123'),patch.object(windows.sys,'executable',str(python)):
            root=ET.fromstring(windows.task_xml(self.config,'service',enabled=False))
            ns={'t':windows.NS}
            def text(path):return root.find(path,ns).text
            self.assertEqual(text('t:Principals/t:Principal/t:LogonType'),'InteractiveToken')
            self.assertEqual(text('t:Principals/t:Principal/t:RunLevel'),'LeastPrivilege')
            self.assertEqual(text('t:Settings/t:ExecutionTimeLimit'),'PT0S')
            self.assertEqual(text('t:Settings/t:AllowHardTerminate'),'false')
            self.assertEqual(text('t:Settings/t:StopIfGoingOnBatteries'),'false')
            self.assertEqual(text('t:Settings/t:RestartOnFailure/t:Count'),'3')
            self.assertEqual(text('t:Settings/t:RestartOnFailure/t:Interval'),'PT1M')
            self.assertEqual(text('t:Triggers/t:LogonTrigger/t:Enabled'),'false')
            self.assertIn('中文 环境',text('t:Actions/t:Exec/t:Command'))
            self.assertIn('--home',text('t:Actions/t:Exec/t:Arguments'))
            tray=ET.fromstring(windows.task_xml(self.config,'tray'))
            self.assertIsNone(tray.find('t:Settings/t:RestartOnFailure',ns))

    def test_windows_start_reuses_healthy_service_and_rejects_foreign_port(self):
        with patch.object(windows,'installed',return_value=True),patch.object(service,'health',return_value='ready'),patch.object(service,'ensure_ready') as ready,patch.object(windows,'scheduler') as scheduler:
            windows.control('start',self.config)
            scheduler.assert_not_called();ready.assert_called_once_with(self.config)
        with patch.object(windows,'installed',return_value=True),patch.object(service,'health',return_value='other'),patch.object(windows,'scheduler') as scheduler:
            with self.assertRaises(RuntimeError):windows.control('start',self.config)
            scheduler.assert_not_called()

    def test_repeated_start_does_not_reschedule_an_instance_or_pending_task(self):
        for running, pending in ((True, False), (False, True)):
            with self.subTest(running=running, pending=pending), patch.object(windows,'installed',return_value=True), patch.object(service,'health',return_value='unresponsive'), patch.object(service,'ensure_ready'), patch('vault_rag.windows_native.running',return_value=running), patch.object(windows,'task_active',return_value=pending), patch.object(windows,'scheduler') as scheduler:
                windows.control('start',self.config)
                scheduler.assert_not_called()

    def test_tray_exit_stops_service_and_closes_icon(self):
        from vault_rag.windows_tray import TrayController
        import threading
        with patch('vault_rag.windows_tray.autostart_enabled',return_value=True):
            controller=TrayController(self.config)
        controller.icon=Mock(); done=threading.Event()
        controller.icon.stop.side_effect=done.set
        with patch('vault_rag.windows_tray.control') as control:
            controller.action('exit'); self.assertTrue(done.wait(5))
            control.assert_called_once_with('stop',self.config)
            self.assertTrue(controller.stop.is_set()); controller.icon.stop.assert_called_once()

    def test_tray_stop_is_independent_of_blocked_refresh_and_exit_menu_exists(self):
        # The menu is localized; make this Chinese-label assertion independent
        # of the test machine's language.
        (self.config.directory/'preferences.json').write_text(json.dumps({'locale':'zh-CN'}),encoding='utf-8')
        from vault_rag import windows_tray as tray
        import threading
        refreshing=threading.Event(); release=threading.Event(); signal=threading.Event(); closed=threading.Event()
        menu=Mock(side_effect=lambda *items: items); menu.SEPARATOR=None
        entries=[]
        class FakeInstance:
            primary=True
            def __init__(self,*args):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def wait_for_stop(self,timeout):return signal.wait(timeout/1000)
        class FakeIcon:
            def __init__(self,name,image,title,items):entries.extend(items)
            def run(self,setup):setup(self); closed.wait(5)
            def stop(self):release.set(); closed.set()
        def refresh():refreshing.set(); release.wait(5)
        fake=SimpleNamespace(Menu=menu,MenuItem=lambda text,action,**kwargs:SimpleNamespace(text=text(None) if callable(text) else text,action=action),Icon=FakeIcon)
        with patch.dict(sys.modules,{'pystray':fake}),patch.object(tray,'Instance',FakeInstance),patch.object(tray,'autostart_enabled',return_value=True),patch.object(tray,'tray_image'),patch.object(tray.TrayController,'refresh',side_effect=refresh):
            worker=threading.Thread(target=tray.run,args=(self.config,),daemon=True); worker.start()
            try:
                self.assertTrue(refreshing.wait(3)); signal.set(); worker.join(timeout=3)
                self.assertFalse(worker.is_alive()); self.assertTrue(closed.is_set())
                labels=[entry.text for entry in entries if entry is not None]
                self.assertEqual(labels.count('退出'),1)
                self.assertFalse(any(isinstance(label,str) and label.startswith('退出托盘') for label in labels))
            finally:release.set();signal.set();worker.join(timeout=3)

    def test_stop_signals_owned_service_and_reports_timeout_without_forced_kill(self):
        with patch('vault_rag.windows_native.running',side_effect=[True,False]),patch('vault_rag.windows_native.signal_stop') as stop,patch.object(windows.time,'sleep'),patch.object(windows,'task_active',return_value=False):
            windows.wait_stopped(self.config)
            stop.assert_called_once_with(self.config.directory,'service')
        with patch('vault_rag.windows_native.running',return_value=True),patch('vault_rag.windows_native.signal_stop'),patch.object(windows.time,'monotonic',side_effect=[0,61]),patch.object(windows,'scheduler') as scheduler:
            with self.assertRaises(RuntimeError):windows.wait_stopped(self.config)
            scheduler.assert_not_called()

    def test_stop_waits_for_pending_task_and_completed_process_before_restart(self):
        with patch('vault_rag.windows_native.running',side_effect=[False,True,False,False]),patch('vault_rag.windows_native.signal_stop') as stop,patch.object(windows,'task_active',side_effect=[True,True,False]),patch.object(windows.time,'sleep'):
            windows.wait_stopped(self.config)
            stop.assert_called_once_with(self.config.directory,'service')

    def test_health_authenticates_installation_and_readiness_timeout(self):
        (self.config.directory/'auth-token').write_text('test-token',encoding='utf-8')
        class Response(io.BytesIO):status=200
        opener=Mock();opener.open.side_effect=[Response(b'{"service":"vault-rag"}'),Response(b'{}')]
        with patch('urllib.request.build_opener',return_value=opener):
            self.assertEqual(service.health(self.config),'ready')
        request=opener.open.call_args.args[0]
        self.assertEqual(request.headers['Authorization'],'Bearer test-token')
        opener.open.side_effect=[Response(b'{"service":"vault-rag"}'),urllib.error.HTTPError('url',401,'unauthorized',{},None)]
        with patch('urllib.request.build_opener',return_value=opener):self.assertEqual(service.health(self.config),'other')
        with patch.object(service,'health',return_value='stopped'),patch.object(service.time,'monotonic',side_effect=[0,61]):
            with self.assertRaises(RuntimeError):service.ensure_ready(self.config)

    def test_macos_dispatch_never_calls_windows_controller(self):
        with patch.object(service,'is_windows',return_value=False),patch.object(service.sys,'platform','darwin'),patch.object(service,'macos_control') as mac,patch.object(windows,'control') as win:
            service.control('status',self.config)
            mac.assert_called_once_with('status',self.config);win.assert_not_called()


@unittest.skipUnless(sys.platform=='win32','requires Windows native APIs')
class WindowsNativeTests(unittest.TestCase):
    def test_concurrent_processes_have_only_one_primary_service(self):
        from vault_rag.windows_native import Instance, running
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            program="from pathlib import Path; import sys; from vault_rag.windows_native import Instance; instance=Instance(Path(sys.argv[1]), 'service'); print(int(instance.primary)); instance.close()"
            with Instance(root,'service') as primary:
                self.assertTrue(primary.primary)
                children=[subprocess.Popen([sys.executable,'-X','utf8','-c',program,str(root)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,**platform.hidden_process_options()) for _ in range(4)]
                for child in children:
                    output,error=child.communicate(timeout=15)
                    self.assertEqual(child.returncode,0,error.decode()); self.assertEqual(output.strip(),b'0')
                self.assertTrue(running(root))
            self.assertFalse(running(root))

    def test_named_mutex_and_cooperative_stop(self):
        from vault_rag.windows_native import Instance,running,signal_stop
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with Instance(root,'service') as first:
                self.assertTrue(first.primary);self.assertTrue(running(root))
                with Instance(root,'service') as second:self.assertFalse(second.primary)
                self.assertTrue(signal_stop(root));self.assertTrue(first.wait_for_stop(1000))
            self.assertFalse(running(root));self.assertFalse(signal_stop(root))

    def test_real_junction_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);root=home/'vault';root.mkdir();outside=home/'outside';outside.mkdir()
            (outside/'secret.md').write_text('private',encoding='utf-8')
            junction=root/'escape'
            subprocess.run(['cmd.exe','/c','mklink','/J',str(junction),str(outside)],check=True,capture_output=True)
            try:
                config=LocalConfig(home/'state');config.save({'root':str(root)})
                with self.assertRaises(ValueError):config.path_for('escape/secret.md')
                self.assertFalse(list(Files(config).walk()))
            finally:junction.rmdir()


if __name__=='__main__':unittest.main()
