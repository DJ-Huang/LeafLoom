"""One-click onboarding API and presentation contracts on a disposable vault."""
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from starlette.testclient import TestClient
from vault_rag.local_state import LocalConfig
from vault_rag.web_server import create_app

ROOT=Path(__file__).resolve().parents[1]

class AttachmentInitializationUIContracts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name).resolve()
        self.root=self.home/'vault';self.root.mkdir();(self.root/'a.png').write_bytes(b'fixture')
        self.config=LocalConfig(self.home/'state');self.config.save({'root':str(self.root)})
        self.app=create_app(self.config,start_background=False);self.client=TestClient(self.app,base_url=self.app.state.websites.ui_origin)
        self.client.__enter__();self.client.get('/');self.headers={'X-Vault-CSRF':self.client.get('/api/session').json()['csrf']}
    def tearDown(self):self.client.__exit__(None,None,None);self.temp.cleanup()
    def wait(self,key):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            job=self.client.get('/api/attachments/migrations/'+key).json()
            if job['state'] not in {'planning','running'}:return job
            time.sleep(.01)
        self.fail('initialization timed out')
    def test_opening_status_and_history_does_not_scan_or_initialize(self):
        with patch.object(self.app.state.runtime.files.attachments._local_index,'refresh') as scan:
            self.assertFalse(self.client.get('/api/attachments/status').json()['usable'])
            self.assertEqual(self.client.get('/api/attachments/migrations').json()['jobs'],[])
            self.assertEqual(self.client.get('/api/attachments').status_code,409)
            scan.assert_not_called()
        self.assertFalse((self.root/'.vault-rag/attachments.sqlite').exists())
    def test_one_setup_request_initializes_and_prepares_without_moving(self):
        index=self.app.state.runtime.files.attachments._local_index
        with patch.object(index,'refresh',wraps=index.refresh) as scan:
            response=self.client.post('/api/attachments/migrations',json={'root':str(self.root),'destination':'_attachments'},headers=self.headers)
            self.assertEqual(response.status_code,200,response.text)
            job=self.wait(response.json()['id']);self.assertEqual(job['state'],'ready',job);self.assertEqual(scan.call_count,1)
        self.assertTrue(self.client.get('/api/attachments/status').json()['usable'])
        self.assertTrue((self.root/'a.png').exists());self.assertFalse((self.root/'_attachments/a.png').exists())
        endpoint='/api/attachments/migrations/'+job['id']+'/execute'
        self.assertEqual(self.client.post(endpoint,json={'root':str(self.root)},headers=self.headers).status_code,400)
        self.assertEqual(self.client.post(endpoint,json={'root':str(self.root),'confirm':True},headers=self.headers).status_code,200)
        self.assertEqual(self.wait(job['id'])['state'],'completed')
    def test_unknown_database_version_is_preserved(self):
        path=self.app.state.runtime.files.state_path('attachments.sqlite')
        with sqlite3.connect(path) as db:db.execute('PRAGMA user_version=20')
        response=self.client.post('/api/attachments/initialize',json={'root':str(self.root)},headers=self.headers)
        self.assertEqual(response.status_code,400)
        with sqlite3.connect(path) as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],20)
    def test_workflow_stages_have_authored_translations(self):
        for language in ['en','zh-CN','ja']:
            values=json.loads((ROOT/f'vault_rag/locales/{language}.json').read_text())
            for stage in ['index','discover','dependencies','hashing','references','snapshot','ready']:
                self.assertTrue(values['aw.stage.'+stage])
            for key in ['aw.initialize','aw.previewOnly','aw.stale','aw.ready']:self.assertTrue(values[key])

    def test_server_mode_lists_without_local_initialization_or_plan(self):
        from test_remote_attachments import FakeDAV, SOURCE, SECRET
        import httpx
        remote=self.app.state.remote_attachments
        remote.save(str(self.root),{'sources':[{'id':SOURCE,'type':'webdav','base_url':'http://127.0.0.1:10000/',
            'allow_private_http':True,'username':'leafloom','enabled':True,'upload_directory':'Incoming'}], 'default_source':SOURCE})
        remote.transports[SOURCE]=httpx.MockTransport(FakeDAV())
        remote.set_credentials(SOURCE,'leafloom',SECRET)
        with patch.object(self.app.state.runtime.files.attachments._local_index,'refresh',side_effect=AssertionError('local scan')):
            status=self.client.get('/api/attachments/status').json()
            self.assertTrue(status['usable']);self.assertEqual(status['storage_mode'],'server')
            response=self.client.get('/api/attachments')
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['items'],[])
            self.assertEqual(self.client.get('/api/attachments/migrations').json()['jobs'],[])

if __name__=='__main__':unittest.main()
