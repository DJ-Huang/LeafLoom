"""Product APIs and the existing two MCP tools share real authorization boundaries."""
import hashlib
import json
import time
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

from tests import test_attachment_storage_api as attachment_api
from tests.test_remote_attachments import SOURCE, SECRET
from vault_rag.unity_asset_store import OfficialSourceError


class AssetLibraryApiTests(unittest.TestCase):
    setUp=attachment_api.AttachmentStorageApiTests.setUp
    request=attachment_api.AttachmentStorageApiTests.request
    settings=attachment_api.AttachmentStorageApiTests.settings
    configure=attachment_api.AttachmentStorageApiTests.configure
    mcp=attachment_api.AttachmentStorageApiTests.mcp

    def setup_library(self):
        self.configure(default=SOURCE)
        base=self.dav
        def server(request):
            if request.method=='MKCOL':return httpx.Response(201)
            return base(request)
        self.remote.transports[SOURCE]=httpx.MockTransport(server)
        self.package='Plugins/Asset Store-5.x/Fictional Studio/Models/Fictional Room.unitypackage'
        self.dav.files[self.package]=b'fictional package bytes'
        with self.remote.lock,self.remote._db(str(self.root)) as db:
            self.asset_id=self.remote._upsert(db,SOURCE,{'path':self.package,'size':len(self.dav.files[self.package]),
                'etag':'"fixture"','mtime':'Wed, 21 Oct 2026 00:00:00 GMT'})
        value=self.request('POST','/api/asset-library/actions',json={
            'root':str(self.root),'action':'discover','storage_id':SOURCE}).json()
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            state=self.app.state.asset_library.sync(str(self.root))
            if state.get('initialized') and not state.get('pending'):break
            time.sleep(.01)
        self.assertTrue(state.get('initialized'),state)
        self.assertEqual(state['pending'],0,state)
        return self.request('GET','/api/asset-library',params={'root':str(self.root)}).json()['items'][0]

    def test_product_roundtrip_settings_and_existing_mcp_schema(self):
        candidate=self.setup_library()
        self.assertEqual(candidate['kind'],'candidate')
        official=self.request('POST','/api/asset-library/actions',json={
            'root':str(self.root),'action':'official','product_id':'123456',
            'official':{'title':'Fictional Room','publisher':'Fictional Studio','summary_zh':'虚构测试资源。',
                        'url':'https://assetstore.unity.com/packages/3d/environments/fictional-room-123456'}}).json()
        linked=self.request('POST','/api/asset-library/actions',json={
            'root':str(self.root),'action':'bind','product_id':'123456','asset_id':self.asset_id,
            'expected_revision':candidate['revision']}).json()
        edited=self.request('POST','/api/asset-library/actions',json={
            'root':str(self.root),'action':'metadata','id':linked['id'],'expected_revision':linked['revision'],
            'personal':{'tags':['我的标签'],'category':'场景','description':'测试备注'}}).json()
        self.assertEqual(edited['personal']['tags'],['我的标签'])
        self.request('POST','/api/asset-library/actions',expected=409,json={
            'root':str(self.root),'action':'metadata','id':linked['id'],'expected_revision':linked['revision'],
            'personal':{'tags':['stale']}})
        current=self.request('GET','/api/asset-library/settings',params={'root':str(self.root)}).json()
        self.request('PUT','/api/asset-library/settings',json={
            'root':str(self.root),'storage_id':SOURCE,'metadata_directory':current['metadata_directory'],
            'revision':current['revision'],'download_limit_bytes':1024**3})
        self.request('PUT','/api/asset-library/settings',expected=409,json={
            'root':str(self.root),'storage_id':SOURCE,'metadata_directory':current['metadata_directory'],
            'revision':current['revision'],'download_limit_bytes':2*1024**3})
        result=self.mcp('products',query='我的标签')
        self.assertEqual(result['total'],1)
        self.assertEqual(self.mcp('product',product_id='123456')['files'][0]['asset_id'],self.asset_id)
        self.assertEqual(self.dav.files[self.package],b'fictional package bytes')
        self.assertFalse(any(method in {'DELETE','MOVE','COPY'} for method,_ in self.dav.calls))

    def test_read_only_mcp_prepares_download_but_cannot_write_metadata(self):
        self.setup_library()
        self.mcp_token=self.app.state.mcp_access.configure('local',enabled=True,write=False)['token']
        job=self.mcp('prepare_download',asset_id=self.asset_id)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            state=self.mcp('download_status',job_id=job['job_id'])
            if state['state'] in {'ready','failed','paused'}:break
            time.sleep(.02)
        self.assertEqual(state['state'],'ready',state)
        self.assertEqual(state['sha256'],hashlib.sha256(self.dav.files[self.package]).hexdigest())
        response=self.request('GET','/api/asset-downloads/file/'+state['handle'],params={'root':str(self.root)})
        self.assertEqual(response.content,self.dav.files[self.package])
        self.assertIn('Fictional%20Room.unitypackage',response.headers['content-disposition'])
        response=self.client.post(f'http://127.0.0.1:{self.config.data.get("port",18080)}/mcp',headers={
            'Accept':'application/json, text/event-stream','Authorization':'Bearer '+self.mcp_token},json={
            'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'vault_files_update','arguments':{
                'request':{'action':'product_update','operation':'official','product_id':'999999','payload':{'official':{'title':'Denied'}}},
                'workspace_revision':self.config.data['revision'],'operation_id':'readonly-cannot-edit'}}})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['result']['isError'])
        self.assertEqual(self.app.state.asset_library.listing(str(self.root),query='Denied')['total'],0)
        self.assertNotIn(SECRET,json.dumps(state))
        self.request('DELETE','/api/asset-downloads/'+job['job_id'],params={'root':str(self.root)})
        self.request('GET','/api/asset-downloads/file/'+state['handle'],params={'root':str(self.root)},expected=400)

    def test_official_url_requires_exact_identity_or_explicit_confirmation(self):
        candidate=self.setup_library()
        source=self.app.state.asset_enrichment.source
        url='https://assetstore.unity.com/packages/3d/environments/different-room-123456'
        with patch.object(source,'product',return_value={'product_id':'unity.assetstore:123456',
                'url':url,'title':'Different Room','publisher':'Another Studio','summary_zh':'','fetched_at':1}):
            pending=self.request('POST','/api/asset-library/actions',json={
                'root':str(self.root),'action':'official_url','id':candidate['id'],'asset_id':self.asset_id,
                'url':url,'expected_revision':candidate['revision']}).json()
        self.assertEqual(pending['files'],[])
        self.assertEqual(pending['pending_match']['asset_id'],self.asset_id)
        reviewed=self.app.state.asset_library.detail(str(self.root),candidate['id'])
        self.assertEqual(reviewed['review']['proposed_product_id'],'123456')
        self.assertEqual(reviewed['review']['proposed_url'],url)
        self.assertEqual(reviewed['review']['status'],'needs_review')
        self.request('POST','/api/asset-library/actions',expected=409,json={
            'root':str(self.root),'action':'bind','asset_id':self.asset_id,'product_id':'123456',
            'expected_revision':candidate['revision']})
        linked=self.request('POST','/api/asset-library/actions',json={
            'root':str(self.root),'action':'bind','asset_id':self.asset_id,'product_id':'123456',
            'expected_revision':reviewed['revision'],'evidence':{'method':'user_confirmed','url':url}}).json()
        self.assertEqual(len(linked['files']),1)

    def test_duplicate_candidates_reuse_verified_search_but_keep_both_packages(self):
        self.setup_library()
        second=self.package.replace('Asset Store-5.x/','Asset Store-5.x-2/Asset Store-5.x-2/')
        self.dav.files[second]=b'another preserved version'
        with self.remote.lock,self.remote._db(str(self.root)) as db:
            self.remote._upsert(db,SOURCE,{'path':second,'size':len(self.dav.files[second]),'etag':'"fixture"'})
        service=self.app.state.asset_enrichment
        items=self.app.state.asset_library.listing(str(self.root))['items']
        job={'state':'running','total':2,'succeeded':0,'needs_review':0,'failed':0,'results':[]}
        url='https://assetstore.unity.com/packages/3d/environments/fictional-room-123456'
        data={'product_id':'unity.assetstore:123456','url':url,'title':'Fictional Room','publisher':'Fictional Studio',
              'summary_zh':'','fetched_at':1,'summary_status':'needs_summary'}
        with patch.object(service.source,'search',return_value=[url]) as search,patch.object(service.source,'product',return_value=data) as product:
            service._run(str(self.root),items,job,'local',None)
        self.assertEqual(job['state'],'completed',job)
        self.assertEqual(job['succeeded'],2,job)
        self.assertEqual(search.call_count,1)
        self.assertEqual(product.call_count,1)
        result=self.app.state.asset_library.detail(str(self.root),'123456')
        self.assertEqual(len(result['files']),2)
        self.assertEqual(self.dav.files[self.package],b'fictional package bytes')
        self.assertEqual(self.dav.files[second],b'another preserved version')

    def test_failed_cover_refresh_preserves_image_and_its_real_source(self):
        self.setup_library()
        library=self.app.state.asset_library
        url='https://assetstore.unity.com/packages/3d/environments/fictional-room-123456'
        library.update(str(self.root),'official',{'product_id':'123456','official':{
            'title':'Fictional Room','publisher':'Fictional Studio','url':url}})
        image=self.home/'cover.png';Image.new('RGB',(10,10),'blue').save(image)
        old='https://unity-assetstorev2-prd.storage.googleapis.com/original.png'
        library.store_cover(str(self.root),'123456',image,old)
        before=library.detail(str(self.root),'123456')['official']['cover']
        source=self.app.state.asset_enrichment.source
        with patch.object(source,'product',return_value={'product_id':'unity.assetstore:123456',
                'url':url,'title':'Fictional Room','publisher':'Fictional Studio',
                'cover_source_url':'https://unity-assetstorev2-prd.storage.googleapis.com/broken.png'}),\
             patch.object(source,'cover',side_effect=OfficialSourceError('official_cover_invalid')):
            refreshed=self.request('POST','/api/asset-library/actions',json={
                'root':str(self.root),'action':'official_url','id':'unity.assetstore:123456','url':url}).json()
        self.assertEqual(refreshed['official']['cover'],before)
        self.assertEqual(refreshed['official']['cover_source_url'],old)


if __name__=='__main__':unittest.main()
