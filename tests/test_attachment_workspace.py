"""Attachment workspace contracts on disposable roots, including guarded writes."""
import io
import os
from pathlib import Path
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch
from PIL import Image
from starlette.testclient import TestClient
from vault_rag.local_state import LocalConfig
from vault_rag.web_server import create_app


class AttachmentWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name).resolve()
        self.root=self.home/'vault';self.root.mkdir()
        self.config=LocalConfig(self.home/'state');self.config.save({'root':str(self.root)})
        self.app=create_app(self.config,start_background=False)
        self.client=TestClient(self.app,base_url=self.app.state.websites.ui_origin)
        self.client.__enter__();self.client.get('/')
        self.headers={'X-Vault-CSRF':self.client.get('/api/session').json()['csrf']}
        out=io.BytesIO();Image.new('RGB',(48,32),'#75958b').save(out,'PNG');self.png=out.getvalue()

    def tearDown(self):
        self.client.__exit__(None,None,None);self.temp.cleanup()

    def put(self,path,data=None):
        p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(self.png if data is None else data.encode() if isinstance(data,str) else data);return p

    def index(self):self.app.state.runtime.files.attachments.refresh()
    def post(self,path,data):return self.client.post('/api/attachments/'+path,json={'root':str(self.root),**data},headers=self.headers)
    def wait(self,job):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            result=self.client.get('/api/attachments/migrations/'+job['id']).json()
            if result['state'] not in {'planning','running','rolling_back'}:return result
            time.sleep(.01)
        self.fail('attachment job timed out')
    def operation(self,kind,paths,**values):
        response=self.post('operations',{'kind':kind,'paths':paths,**values});self.assertEqual(response.status_code,200,response.text)
        return self.wait(response.json())
    def execute(self,job):
        response=self.post('migrations/'+job['id']+'/execute',{'confirm':True});self.assertEqual(response.status_code,200,response.text)
        return self.wait(job)

    def test_sorted_filter_cursor_and_legacy_pagination(self):
        for name in ['a.png','b.png','c.png']:os.utime(self.put(name),(1700000000,1700000000))
        self.put('manual.pdf',b'%PDF');self.put('private.md','note');self.index()
        params={'root':str(self.root),'kind':'image','sort':'modified','order':'desc','limit':1}
        first=self.client.get('/api/attachments',params=params).json()
        self.assertEqual(first['total'],3);self.assertEqual(first['summary']['files'],4)
        self.assertEqual(first['summary']['kinds']['pdf'],1)
        second=self.client.get('/api/attachments',params={**params,'cursor':first['cursor']}).json()
        self.assertNotEqual(first['items'][0]['path'],second['items'][0]['path'])
        self.assertEqual(self.client.get('/api/attachments',params={**params,'query':'a','cursor':first['cursor']}).status_code,409)
        old=self.client.get('/api/attachments?limit=1').json()
        after=self.client.get('/api/attachments',params={'after':old['next_cursor'],'limit':1}).json()
        self.assertNotEqual(old['items'][0]['path'],after['items'][0]['path'])
        self.put('new.png');self.app.state.runtime.files.attachments.apply(['new.png'])
        self.assertEqual(self.client.get('/api/attachments',params={**params,'cursor':first['cursor']}).status_code,409)
        self.assertEqual(self.client.get('/api/attachments?sort=unknown').status_code,400)
        self.assertEqual(self.client.get('/api/attachments?root=/wrong').status_code,409)

    def test_thumbnail_cache_and_media_root_guard(self):
        self.put('photo.png');before=(self.root/'photo.png').read_bytes()
        params={'root':str(self.root),'path':'photo.png'}
        result=self.client.get('/api/attachments/thumbnail',params=params)
        self.assertEqual(result.status_code,200,result.text if result.status_code!=200 else '')
        with Image.open(io.BytesIO(result.content)) as image:self.assertLessEqual(max(image.size),256)
        self.assertEqual(self.client.get('/api/attachments/thumbnail',params=params,headers={'If-None-Match':result.headers['etag']}).status_code,304)
        self.assertEqual((self.root/'photo.png').read_bytes(),before)
        self.assertEqual(self.client.get('/api/media',params={**params,'root':'/wrong'}).status_code,409)
        self.put('bad.png',b'not an image')
        self.assertEqual(self.client.get('/api/attachments/thumbnail',params={**params,'path':'bad.png'}).status_code,400)
        self.put('unsafe.svg','<svg/>')
        self.assertEqual(self.client.get('/api/attachments/thumbnail',params={**params,'path':'unsafe.svg'}).status_code,400)
        self.assertEqual(self.client.get('/api/attachments/thumbnail',params={**params,'path':'../outside.png'}).status_code,400)

    def test_move_rename_and_undo_preserve_folder_setting(self):
        self.put('assets/a.png');self.put('note.md','![[assets/a.png]]');self.index()
        job=self.operation('move',['assets/a.png'],destination='Photos')
        self.assertEqual(job['state'],'ready',job);self.assertEqual(job['references'],['note.md'])
        self.assertEqual(self.post('migrations/'+job['id']+'/execute',{}).status_code,400)
        self.assertEqual(self.execute(job)['state'],'completed')
        self.assertEqual((self.root/'note.md').read_text(),'![[Photos/a.png]]')
        self.assertEqual(self.config.data['attachment_folder'],'_attachments')
        renamed=self.operation('rename',['Photos/a.png'],name='b.png')
        self.assertEqual(self.execute(renamed)['state'],'completed')
        self.assertEqual((self.root/'note.md').read_text(),'![[Photos/b.png]]')
        self.post('migrations/'+renamed['id']+'/rollback',{'confirm':True})
        self.assertEqual(self.wait(renamed)['state'],'rolled_back')
        self.assertTrue((self.root/'Photos/a.png').exists())

    def test_recycle_referenced_file_and_restore_without_editing_note(self):
        self.put('a.png');self.put('note.md','![[a.png]]');self.index()
        job=self.operation('trash',['a.png']);self.assertEqual(job['state'],'ready',job)
        self.assertEqual(job['summary']['notes'],1)
        self.assertEqual(self.execute(job)['state'],'completed')
        self.assertFalse((self.root/'a.png').exists());self.assertEqual((self.root/'note.md').read_text(),'![[a.png]]')
        records=self.app.state.runtime.files.records('trash');self.assertEqual(len(records),1)
        self.post('migrations/'+job['id']+'/rollback',{'confirm':True})
        self.assertEqual(self.wait(job)['state'],'rolled_back');self.assertTrue((self.root/'a.png').exists())
        self.assertEqual(self.app.state.runtime.files.records('trash'),[])

    def test_project_shared_resource_is_readonly(self):
        self.put('site/index.html','<script src="app.js"></script>')
        self.put('site/app.js','const prefix="../shared/";fetch(prefix+name)')
        self.put('shared/a.png');self.put('loose.png');self.index()
        detail=self.client.get('/api/attachments/details',params={'root':str(self.root),'path':'shared/a.png'}).json()
        self.assertTrue(detail['protected'])
        for kind in ['move','rename','trash']:
            job=self.operation(kind,['shared/a.png'],destination='Photos',name='renamed.png')
            self.assertEqual(job['state'],'blocked',job)
            self.assertEqual(self.post('migrations/'+job['id']+'/execute',{'confirm':True}).status_code,409)
        self.assertTrue((self.root/'shared/a.png').exists())
        self.assertEqual(self.post('operations',{'kind':'trash','paths':['../outside']}).status_code,400)

    def test_recycle_failure_reports_each_file_and_retains_new_content(self):
        self.put('a.png');self.put('b.png');self.index();job=self.operation('trash',['a.png','b.png'])
        from vault_rag.platform_support import move_exclusive
        def change_second(source,destination):
            result=move_exclusive(source,destination)
            if source==self.root/'a.png':(self.root/'b.png').write_bytes(b'new external data')
            return result
        with patch('vault_rag.attachment_migrations.move_exclusive',side_effect=change_second):result=self.execute(job)
        self.assertEqual(result['state'],'conflict',result)
        self.assertTrue((self.root/'a.png').exists());self.assertEqual((self.root/'b.png').read_bytes(),b'new external data')
        self.assertEqual(result['results'][0]['state'],'rolled_back')
        self.assertEqual(result['results'][1]['state'],'failed')

    def test_recycle_external_edit_during_retirement_preserves_latest_bytes(self):
        self.put('a.png');self.index();job=self.operation('trash',['a.png'])
        from vault_rag.platform_support import move_exclusive
        def external_edit(source,destination):
            if source==self.root/'a.png':source.write_bytes(b'latest external edit')
            return move_exclusive(source,destination)
        with patch('vault_rag.attachment_migrations.move_exclusive',side_effect=external_edit):result=self.execute(job)
        self.assertEqual(result['state'],'conflict',result)
        self.assertEqual((self.root/'a.png').read_bytes(),b'latest external edit')
        self.assertEqual(result['results'][0]['state'],'failed')

    def test_zip_download_and_root_scope(self):
        self.put('one/a.png');self.put('two/a.png',b'other')
        response=self.post('downloads',{'paths':['one/a.png','two/a.png']});self.assertEqual(response.status_code,200,response.text)
        key=response.json()['id'];deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            status=self.client.get('/api/attachments/downloads/'+key,params={'root':str(self.root)}).json()
            if status['state']!='running':break
            time.sleep(.01)
        self.assertEqual(status['state'],'completed',status)
        data=self.client.get('/api/attachments/downloads/'+key+'/file',params={'root':str(self.root)})
        with zipfile.ZipFile(io.BytesIO(data.content)) as archive:
            self.assertEqual(archive.namelist(),['one/a.png','two/a.png']);self.assertEqual(archive.read('two/a.png'),b'other')
        self.assertEqual(self.client.get('/api/attachments/downloads/'+key+'/file',params={'root':'/wrong'}).status_code,409)
        self.assertEqual(self.post('downloads',{'paths':['one/a.png']*101}).status_code,400)
        self.config.save({'exclude_roots':['two']})
        self.assertEqual(self.client.get('/api/attachments/downloads/'+key+'/file',params={'root':str(self.root)}).status_code,409)

    def test_upload_same_name_keeps_both(self):
        self.put('_attachments/a.png',b'first');self.index()
        response=self.client.post('/api/upload',params={'root':str(self.root),'name':'a.png','central':'true','unique':'true'},content=b'second',headers=self.headers)
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['path'],'_attachments/a (2).png')
        self.assertEqual((self.root/'_attachments/a.png').read_bytes(),b'first')
        self.assertEqual(self.client.get('/api/attachments').json()['total'],2)

if __name__=='__main__':unittest.main()
