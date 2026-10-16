"""Model-install integrity, offline migration and interrupted-download recovery."""
import hashlib
import json
import queue
import threading
import time
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from vault_rag.embedded_model import EmbeddedModel
from vault_rag.rag_process import RemoteModel


class ModelInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.model=EmbeddedModel(Path(self.temp.name))
        self.payloads={'config.json':b'{}','tokenizer_config.json':b'{}','tokenizer.json':b'{}','model.safetensors':b'fake weights'}
        self.siblings=[SimpleNamespace(rfilename=name,size=len(value),lfs=SimpleNamespace(sha256=hashlib.sha256(value).hexdigest())) for name,value in self.payloads.items()]
        self.info=SimpleNamespace(sha='pinned-revision',siblings=self.siblings)

    def tearDown(self):self.temp.cleanup()

    def files(self,*_,**kwargs):
        self.model.path.mkdir(parents=True,exist_ok=True)
        for name,value in self.payloads.items():(self.model.path/name).write_bytes(value)

    def test_download_checks_files_and_pins_receipt(self):
        with patch('huggingface_hub.HfApi') as api,patch('huggingface_hub.snapshot_download',side_effect=self.files) as download:
            api.return_value.model_info.return_value=self.info
            self.model.prepare()
        self.assertTrue(self.model.ready)
        self.assertEqual(download.call_args.kwargs['revision'],'pinned-revision')
        receipt=json.loads(self.model.manifest.read_text())
        self.assertEqual(receipt['files']['model.safetensors']['size'],len(self.payloads['model.safetensors']))
        self.assertFalse((self.model.directory/'models/model-download.json').exists())

    def test_missing_and_same_size_corrupt_config_are_not_ready(self):
        self.files();self.model._receipt('pinned-revision',self.payloads)
        (self.model.path/'tokenizer.json').write_bytes(b'xx')
        self.assertFalse(self.model.ready)
        self.files();(self.model.path/'model.safetensors').unlink();self.assertFalse(self.model.ready)

    def test_corrupt_download_never_publishes_success_receipt(self):
        def corrupt(*args,**kwargs):
            self.files();(self.model.path/'model.safetensors').write_bytes(b'bad weights!')
        with patch('huggingface_hub.HfApi') as api,patch('huggingface_hub.snapshot_download',side_effect=corrupt),patch('huggingface_hub.hf_hub_download'):
            api.return_value.model_info.return_value=self.info
            with self.assertRaises(RuntimeError):self.model.prepare()
        self.assertFalse(self.model.manifest.exists());self.assertFalse(self.model.ready)

    def test_damaged_cached_file_is_preserved_and_downloaded_again(self):
        self.files();self.model._receipt('pinned-revision',self.payloads)
        (self.model.path/'config.json').write_bytes(b'xx')
        with patch('huggingface_hub.HfApi') as api,patch('huggingface_hub.snapshot_download'),patch('huggingface_hub.hf_hub_download',side_effect=self.files) as download:
            api.return_value.model_info.return_value=self.info
            self.model.prepare()
        self.assertTrue(self.model.ready)
        self.assertTrue(download.call_args.kwargs['force_download'])
        backup=next((self.model.directory/'models').glob('damaged-*/config.json'))
        self.assertEqual(backup.read_bytes(),b'xx')

    def test_interrupted_download_keeps_revision_for_next_attempt(self):
        with patch('huggingface_hub.HfApi') as api,patch('huggingface_hub.snapshot_download',side_effect=ConnectionError('reset')):
            api.return_value.model_info.return_value=self.info
            with self.assertRaises(ConnectionError):self.model.prepare()
        with patch('huggingface_hub.HfApi') as api,patch('huggingface_hub.snapshot_download',side_effect=self.files):
            api.return_value.model_info.return_value=self.info
            self.model.prepare()
            self.assertEqual(api.return_value.model_info.call_args.kwargs['revision'],'pinned-revision')

    def test_complete_legacy_model_is_adopted_without_network_or_new_revision(self):
        self.files();self.model.manifest.write_text(json.dumps({'model':self.model.model_id,'revision':'legacy-revision'}))
        with patch('huggingface_hub.HfApi',side_effect=AssertionError('network called')):
            self.model.prepare();self.model.prepare()
        self.assertTrue(self.model.ready)
        self.assertEqual(json.loads(self.model.manifest.read_text())['revision'],'legacy-revision')

    def test_download_progress_reports_network_bytes_and_transitions_to_verification(self):
        stages=[]
        original=self.model._stage
        def stage(state,**extra):
            original(state,**extra);stages.append(self.model.status()['preparation'])
        def download(*args,**kwargs):
            progress=kwargs['tqdm_class']
            with progress(total=10,unit='B',desc='Downloading bytes') as bar:bar.update(10)
            self.assertEqual(self.model.status()['preparation']['downloaded_bytes'],10)
            # Reconstructing includes reused partial downloads, not network traffic.
            with progress(total=20,unit='B',desc='Reconstructing (incomplete total...)') as bar:bar.update(20)
            self.assertEqual(self.model.status()['preparation']['downloaded_bytes'],10)
            with progress(total=len(self.payloads)) as bar:bar.update(len(self.payloads))
            self.files()
        with patch.object(self.model,'_stage',side_effect=stage),patch('huggingface_hub.HfApi') as api,patch('huggingface_hub.snapshot_download',side_effect=download),patch('hashlib.file_digest',wraps=hashlib.file_digest) as checksum:
            api.return_value.model_info.return_value=self.info
            self.model.prepare()
        self.assertEqual(checksum.call_count,len(self.payloads))
        self.assertEqual(self.model.status()['preparation']['state'],'ready')
        self.assertTrue(any(s['state']=='verifying' and s.get('current_file')=='model.safetensors' for s in stages))
        self.assertTrue(any(s.get('bytes_per_second',0)>0 for s in stages))

    def test_failure_remains_visible_and_retry_discards_stale_progress(self):
        with patch('huggingface_hub.HfApi') as api,patch('huggingface_hub.snapshot_download',side_effect=ConnectionError('offline')):
            api.return_value.model_info.return_value=self.info
            with self.assertRaises(ConnectionError):self.model.prepare()
        self.assertEqual(self.model.status()['preparation']['failed_stage'],'downloading')
        self.assertEqual(self.model.status()['error'],'offline')
        with patch('huggingface_hub.HfApi') as api,patch('huggingface_hub.snapshot_download',side_effect=self.files):
            api.return_value.model_info.return_value=self.info
            self.model.prepare()
        self.assertIsNone(self.model.status()['error'])
        self.assertNotIn('failed_stage',self.model.status()['preparation'])

    def test_remote_reserves_once_and_rejects_stale_worker_failure_on_retry(self):
        process=SimpleNamespace(model_status={'error':'old failure','preparation':{'state':'failed','started_at':1}},request=lambda *_:self.model.prepare())
        remote=RemoteModel(SimpleNamespace(directory=self.model.directory),process)
        self.assertTrue(remote.begin_prepare());self.assertFalse(remote.begin_prepare())
        self.assertEqual(remote.status()['preparation']['state'],'starting')
        self.assertIsNone(remote.status()['error'])
        process.request=lambda *_:(_ for _ in ()).throw(RuntimeError('new failure'))
        with self.assertRaises(RuntimeError):remote.prepare(reserved=True)
        self.assertFalse(remote.preparing)
        self.assertEqual(remote.status()['preparation']['state'],'failed')
        self.assertEqual(remote.status()['error'],'new failure')
        self.assertTrue(remote.begin_prepare())
        self.assertIsNone(remote.status()['error'])

    def test_prepare_wait_has_no_ten_minute_deadline(self):
        from vault_rag.rag_process import RagProcess
        process=RagProcess(SimpleNamespace(data={}))
        process.process=object()
        def send(message):
            process.pending[message['id']][2].put({'result':'ready'})
            return True
        pending=queue.Queue();pending.get=Mock(return_value={'result':'ready'})
        with patch.object(process,'start'),patch.object(process,'send',side_effect=send),patch('vault_rag.rag_process.queue.Queue',return_value=pending):
            # Capture the public wait call without actually waiting or spawning a worker.
            self.assertEqual(process.request('prepare'),'ready')
            pending.get.assert_called_once_with(timeout=None)

    def test_prepare_api_publishes_start_and_deduplicates_until_failure(self):
        from fastapi.testclient import TestClient
        from vault_rag.local_state import LocalConfig
        from vault_rag.knowledge import Runtime
        from vault_rag.web_server import create_app
        config=LocalConfig(self.model.directory/'api-state');runtime=Runtime(config)
        app=create_app(config,runtime,start_background=False)
        started=threading.Event();release=threading.Event()
        def request(*args,**kwargs):
            started.set();release.wait(3);raise ConnectionError('offline fixture')
        try:
            with patch.object(runtime.rag,'request',side_effect=request) as work,patch('logging.exception'),TestClient(app,base_url='http://127.0.0.1:18080') as client:
                client.cookies.set('vault_session',(config.directory/'auth-token').read_text())
                headers={'X-Vault-CSRF':app.state.csrf}
                self.assertEqual(client.post('/api/model-prepare',headers=headers).json()['state'],'模型准备已开始')
                self.assertTrue(started.wait(1))
                self.assertEqual(client.get('/api/status').json()['model']['preparation']['state'],'starting')
                self.assertEqual(client.post('/api/model-prepare',headers=headers).json()['state'],'下载中')
                self.assertEqual(work.call_count,1)
                release.set();deadline=time.monotonic()+2
                while runtime.model.preparing and time.monotonic()<deadline:time.sleep(.01)
                status=client.get('/api/status').json()['model']
                self.assertEqual(status['preparation']['state'],'failed')
                self.assertEqual(status['error'],'offline fixture')
        finally:release.set();runtime.stop()

    def test_model_directory_api_uses_actual_path_and_requires_csrf(self):
        from fastapi.testclient import TestClient
        from vault_rag.local_state import LocalConfig
        from vault_rag.knowledge import Runtime
        from vault_rag.web_server import create_app
        config=LocalConfig(self.model.directory/'custom-state');runtime=Runtime(config)
        app=create_app(config,runtime,start_background=False)
        try:
            with TestClient(app,base_url='http://127.0.0.1:18080') as client,patch('vault_rag.web_server.open_directory') as open_folder:
                client.cookies.set('vault_session',(config.directory/'auth-token').read_text())
                directory=runtime.model.available.path
                self.assertEqual(client.get('/api/status').json()['model']['path'],str(directory.resolve()))
                self.assertEqual(client.post('/api/model-directory/open',json={}).status_code,403)
                open_folder.assert_not_called()
                headers={'X-Vault-CSRF':app.state.csrf}
                response=client.post('/api/model-directory/open',headers=headers,json={'path':'C:/not-the-model-folder'})
                self.assertEqual(response.status_code,200)
                open_folder.assert_called_once_with(directory)
                open_folder.side_effect=OSError('cannot open fixture')
                response=client.post('/api/model-directory/open',headers=headers)
                self.assertEqual(response.status_code,400)
                self.assertEqual(response.json()['error'],'cannot open fixture')
        finally:runtime.stop()

    def test_open_model_directory_creates_empty_folder_without_downloading(self):
        from vault_rag.platform_support import open_directory
        directory=self.model.path
        self.assertFalse(directory.exists())
        with patch('vault_rag.platform_support.is_windows',return_value=True),patch('os.startfile') as startfile:
            open_directory(directory)
        self.assertTrue(directory.is_dir())
        startfile.assert_called_once_with(str(directory.resolve()))
        self.assertEqual(list(directory.iterdir()),[])


if __name__=='__main__':unittest.main()
