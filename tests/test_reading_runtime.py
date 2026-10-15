"""Startup/cache/process-isolation contracts. All filesystem writes are fixtures."""
from __future__ import annotations
import asyncio,json,os,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from starlette.testclient import TestClient
from vault_rag.local_state import LocalConfig,Files
from vault_rag.catalog import Catalog
from vault_rag.knowledge import Runtime
from vault_rag.rag_process import RagProcess
from vault_rag.web_server import create_app

class ReadingRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name).resolve()
        self.root=self.home/'vault';self.root.mkdir();(self.root/'RAG').mkdir()
        self.config=LocalConfig(self.home/'state');self.config.save({'root':str(self.root),'include_roots':['RAG']})
        self.runtimes=[]
    def tearDown(self):
        for runtime in self.runtimes:runtime.stop()
        self.temp.cleanup()
    def runtime(self):
        runtime=Runtime(self.config);self.runtimes.append(runtime);return runtime
    def put(self,path,text):
        p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8');return p
    def wait(self,condition):
        deadline=time.monotonic()+4
        while not condition() and time.monotonic()<deadline:time.sleep(.02)
        self.assertTrue(condition())

    def test_no_heavy_imports_when_starting_file_service(self):
        script="import sys;from pathlib import Path;from vault_rag.local_state import LocalConfig;from vault_rag.web_server import create_app;from starlette.testclient import TestClient;a=create_app(LocalConfig(Path(sys.argv[1])),start_background=False);\nwith TestClient(a,base_url='http://127.0.0.1:18080') as c:c.get('/healthz')\nassert not any(n==p or n.startswith(p+'.') for n in sys.modules for p in ('torch','scipy','sentence_transformers','lancedb','llama_index'))"
        result=subprocess.run([sys.executable,'-X','utf8','-c',script,str(self.home/'import-state')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_restart_restores_cache_without_reading_non_rag_notes(self):
        self.put('RAG/a.md','# A\n[[outside]]');self.put('outside.md','# Outside\n[[RAG/a]]')
        catalog=Catalog(Files(self.config));catalog.scan()
        raw_read=Path.read_bytes;reads=[]
        def read(path):
            if path.is_relative_to(self.root) and path.suffix in ('.md','.txt'):reads.append(path)
            return raw_read(path)
        with patch.object(Path,'read_bytes',read):
            for _ in range(2):
                runtime=self.runtime();runtime.catalog.restore();runtime.knowledge.load();runtime.catalog.refresh_scopes()
                self.assertIn('outside.md',runtime.catalog.entries)
                self.assertFalse(runtime.catalog.entries['outside.md']['_hydrated'])
                self.assertIsNone(runtime.rag.process)
        self.assertEqual(reads,[])

    def test_legacy_cache_is_backed_up_and_migrated_without_note_reads(self):
        import sqlite3
        self.put('old.md','# Original')
        directory=self.root/'.vault-rag';directory.mkdir()
        db=sqlite3.connect(directory/'catalog.sqlite')
        db.execute('CREATE TABLE files(path TEXT PRIMARY KEY,title TEXT,metadata TEXT,sha256 TEXT,mtime REAL)')
        db.execute('INSERT INTO files VALUES(?,?,?,?,?)',('old.md','Old','{}','old-hash',0));db.commit();db.close()
        runtime=self.runtime()
        with patch.object(Path,'read_bytes',side_effect=AssertionError('note read during restore')):runtime.catalog.restore()
        self.assertIn('old.md',runtime.catalog.entries)
        self.assertTrue(list(directory.glob('catalog-before-v2-*.sqlite')))
        self.assertEqual((self.root/'old.md').read_text(),'# Original')

    def test_idle_gate_and_non_rag_changes_do_not_start_model(self):
        self.put('RAG/a.md','# A');self.put('outside.md','# Outside')
        runtime=self.runtime();runtime.catalog.restore();runtime.catalog.refresh_scopes()
        runtime.last_activity=time.monotonic()-4.9;self.assertFalse(runtime.idle())
        runtime.last_activity=time.monotonic()-5.1;self.assertTrue(runtime.idle())
        runtime.foreground_begin();self.assertFalse(runtime.idle());runtime.foreground_end();self.assertFalse(runtime.idle())
        self.put('outside.md','# Changed');runtime.catalog.apply(['outside.md'])
        self.assertFalse(runtime._needs_index(['outside.md']))
        self.assertEqual(runtime.files.read('outside.md')['text'],'# Changed')
        self.assertIsNone(runtime.rag.process)

    def test_pending_index_waits_without_busy_spinning_during_foreground_work(self):
        runtime=self.runtime()
        with patch.object(runtime,'idle',return_value=False) as idle:
            runtime.index_event.set();thread=threading.Thread(target=runtime._index_loop);thread.start()
            try:time.sleep(.35)
            finally:runtime.stop_event.set();thread.join(1)
            self.assertLessEqual(idle.call_count,5)

    def test_metadata_is_on_demand_cached_and_invalidated(self):
        self.put('RAG/a.md','# A');self.put('outside.md','---\naliases: [Alias]\n---\n[[RAG/a]]')
        runtime=self.runtime();runtime.catalog.restore()
        self.assertFalse(runtime.catalog.metadata_ready)
        self.assertFalse(runtime.ensure_metadata());self.wait(lambda:runtime.catalog.metadata_ready)
        self.assertEqual(runtime.catalog.resolve('Alias'),['outside.md'])
        with patch.object(Path,'read_bytes',side_effect=AssertionError('unchanged note read')):
            self.assertTrue(runtime.ensure_metadata());runtime.catalog.prepare_metadata()
        self.put('outside.md','---\naliases: [NewAlias]\n---\n# Changed');runtime.catalog.apply(['outside.md'])
        self.assertFalse(runtime.catalog.metadata_ready)
        runtime.ensure_metadata();self.wait(lambda:runtime.catalog.metadata_ready)
        self.assertEqual(runtime.catalog.resolve('NewAlias'),['outside.md'])
        self.assertFalse(runtime.catalog.resolve('Alias'))

    def test_blocked_or_crashed_worker_does_not_block_file_status_tree_or_save(self):
        self.put('README.md','# Read me')
        worker=self.home/'blocked.py'
        worker.write_text("import sys,json,time\nfor line in sys.stdin:\n v=json.loads(line)\n if v.get('type')=='request':\n  print(json.dumps({'type':'status','state':'dense','model':{'loading':True},'progress':{}}),flush=True)\n  time.sleep(60)\n",encoding='utf-8')
        runtime=self.runtime();runtime.rag=RagProcess(self.config,runtime._worker_status,[sys.executable,'-u',str(worker)]);runtime.model.process=runtime.rag
        errors=[]
        def blocked():
            try:runtime.rag.request('dense')
            except Exception as error:errors.append(str(error))
        thread=threading.Thread(target=blocked);thread.start()
        self.wait(lambda:runtime.rag.state.get('state')=='dense')
        app=create_app(self.config,runtime,start_background=False);token=(self.config.directory/'auth-token').read_text()
        with TestClient(app,base_url='http://127.0.0.1:18080',headers={'Authorization':'Bearer '+token}) as client:
            for route in ('/api/status','/api/tree','/api/file?path=README.md'):
                start=time.perf_counter();result=client.get(route);self.assertEqual(result.status_code,200);self.assertLess(time.perf_counter()-start,.5)
            note=client.get('/api/file?path=README.md').json();start=time.perf_counter()
            saved=client.put('/api/file',json={**note,'text':'# Saved while model loads'})
            self.assertEqual(saved.status_code,200);self.assertLess(time.perf_counter()-start,.5)
            runtime.rag.process.kill();runtime.rag.process.wait();thread.join(3)
            self.assertTrue(errors);self.assertEqual(client.get('/api/file?path=README.md').status_code,200)
        self.assertEqual((self.root/'README.md').read_text(),'# Saved while model loads')

    def test_real_worker_protocol_and_eof_cleanup(self):
        process=RagProcess(self.config)
        try:
            result=process.request('build')
            self.assertIn('generation',result);self.assertEqual(process.model_status.get('load_count',0),0)
            child=process.process;child.stdin.close();child.wait(timeout=3)
        finally:process.stop()

    def test_changed_policy_cannot_replace_foreground_snapshot(self):
        self.put('RAG/a.md','# A');runtime=self.runtime();runtime.catalog.refresh_scopes()
        runtime.model.available._prepared=True;runtime.model.available._status_fingerprint='test'
        snapshot={'nodes':[],'docs':[],'root':str(self.root)};runtime.knowledge.snapshot=snapshot
        other=self.home/'other';other.mkdir()
        def changed(*args,**kwargs):
            self.config.save({'root':str(other)});return {'progress':{'state':'已同步'}}
        with patch.object(runtime.rag,'request',side_effect=changed):runtime.knowledge.build()
        self.assertIs(runtime.knowledge.snapshot,snapshot)
        self.assertEqual(runtime.knowledge.progress['state'],'等待空闲更新')

    def test_owned_worker_dies_if_service_parent_crashes(self):
        script="import os,sys;from pathlib import Path;from vault_rag.local_state import LocalConfig;from vault_rag.rag_process import RagProcess;p=RagProcess(LocalConfig(Path(sys.argv[1])));p.start();print(p.process.pid,flush=True);os._exit(7)"
        result=subprocess.run([sys.executable,'-X','utf8','-c',script,str(self.home/'crash-state')],capture_output=True,text=True)
        self.assertEqual(result.returncode,7,result.stderr);pid=int(result.stdout.strip())
        if os.name=='nt':
            import ctypes
            from ctypes import wintypes as w
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
            kernel.GetExitCodeProcess.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)];kernel.CloseHandle.argtypes=[w.HANDLE]
            def dead():
                handle=kernel.OpenProcess(0x1000,False,pid)
                if not handle:return True
                code=w.DWORD();kernel.GetExitCodeProcess(handle,ctypes.byref(code));kernel.CloseHandle(handle)
                return code.value!=259
        else:
            def dead():
                try:os.kill(pid,0);return False
                except ProcessLookupError:return True
        self.wait(dead)

    def test_native_import_with_open_control_pipe_does_not_block(self):
        script="import sys,threading;from vault_rag.control_pipe import ControlPipe;c=ControlPipe(sys.stdin);threading.Thread(target=lambda:list(c.lines()),daemon=True).start();import numpy;print('native-ok',flush=True)"
        child=subprocess.Popen([sys.executable,'-X','utf8','-c',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}))
        messages=[];reader=threading.Thread(target=lambda:messages.append(child.stdout.readline()),daemon=True);reader.start()
        try:
            reader.join(8);self.assertEqual([line.strip() for line in messages],[b'native-ok'])
        finally:
            child.stdin.close()
            try:child.wait(timeout=2)
            except subprocess.TimeoutExpired:child.kill();child.wait()
            child.stdout.close();child.stderr.close()

if __name__=='__main__':unittest.main()
