"""Authenticated background migration and central ingestion integration."""
import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from starlette.testclient import TestClient
from vault_rag.local_state import LocalConfig, ConflictError
from vault_rag.web_server import create_app

class AttachmentMigrationApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name).resolve()
        self.root=self.home/'vault';self.root.mkdir()
        self.config=LocalConfig(self.home/'state');self.config.save({'root':str(self.root)})
        self.app=create_app(self.config,start_background=False)
        self.client=TestClient(self.app,base_url=self.app.state.websites.ui_origin)
        self.client.__enter__();self.client.get('/')
        self.headers={'X-Vault-CSRF':self.client.get('/api/session').json()['csrf']}
    def tearDown(self):
        self.client.__exit__(None,None,None);self.temp.cleanup()
    def wait(self,key):
        until=time.monotonic()+5
        while time.monotonic()<until:
            result=self.client.get('/api/attachments/migrations/'+key).json()
            if result['state'] not in ('planning','running','rolling_back'):return result
            time.sleep(.01)
        self.fail('job timeout')
    def test_preview_execute_confirm_rollback_and_root_guard(self):
        (self.root/'a.png').write_bytes(b'asset');(self.root/'n.md').write_text('![[a.png]]')
        self.assertEqual(self.client.get('/api/attachments/status').json()['state'],'uninitialized')
        data={'root':str(self.root),'destination':'Assets'}
        self.assertEqual(self.client.post('/api/attachments/migrations',json=data).status_code,403)
        response=self.client.post('/api/attachments/migrations',json=data,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        key=response.json()['id'];self.assertEqual(self.wait(key)['state'],'ready')
        self.assertTrue(self.client.get('/api/attachments/status').json()['usable'])
        self.assertTrue((self.root/'a.png').exists())
        action='/api/attachments/migrations/'+key+'/execute'
        self.assertEqual(self.client.post(action,json={'root':str(self.root)},headers=self.headers).status_code,400)
        self.assertEqual(self.client.post(action,json={'root':'wrong','confirm':True},headers=self.headers).status_code,409)
        self.assertEqual(self.client.post(action,json={'root':str(self.root),'confirm':True},headers=self.headers).status_code,200)
        self.assertEqual(self.wait(key)['state'],'completed')
        self.assertEqual(self.client.get('/api/attachments').json()['items'][0]['path'],'Assets/a.png')
        self.assertEqual((self.root/'n.md').read_text(),'![[Assets/a.png]]')
        self.assertEqual(self.client.get('/api/attachments/migrations').json()['jobs'][0]['id'],key)
        self.assertEqual(self.client.post('/api/attachments/migrations/'+key+'/rollback',json={'root':str(self.root),'confirm':True},headers=self.headers).status_code,200)
        self.assertEqual(self.wait(key)['state'],'rolled_back')
        self.assertEqual(self.client.get('/api/attachments').json()['items'][0]['path'],'a.png')
    def test_central_upload_custom_folder_and_no_overwrite(self):
        params={'name':'图片 (1).png','root':str(self.root),'central':'true'}
        result=self.client.post('/api/upload',params=params,content=b'original',headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['path'],'_attachments/图片 (1).png')
        self.assertEqual(self.client.post('/api/upload',params=params,content=b'other',headers=self.headers).status_code,409)
        self.config.save({'attachment_folder':'Resources/Files'})
        result=self.client.post('/api/upload',params={**params,'name':'next.pdf'},content=b'pdf',headers=self.headers)
        self.assertEqual(result.json()['path'],'Resources/Files/next.pdf')
        self.assertFalse(list(self.root.rglob('.upload-*')))
    def test_central_stream_root_switch_never_publishes(self):
        endpoint=next(r.endpoint for r in self.app.routes if getattr(r,'path',None)=='/api/upload')
        other=self.home/'other';other.mkdir();config=self.config
        class Request:
            async def stream(self):
                yield b'part';config.save({'root':str(other)});yield b'end'
        with self.assertRaises(ConflictError):
            asyncio.run(endpoint(Request(),name='a.png',root=str(self.root),central=True))
        self.assertFalse(list(self.home.rglob('a.png')))
    def test_destination_guards(self):
        for destination in ('','.vault-rag/x','../outside'):
            result=self.client.post('/api/attachments/migrations',json={'root':str(self.root),'destination':destination},headers=self.headers)
            self.assertEqual(result.status_code,400,result.text)
        with self.assertRaises(ValueError):self.config.save({'attachment_folder':'.vault-rag'})

if __name__=='__main__':unittest.main()
