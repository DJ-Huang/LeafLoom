"""Product de-duplication, NAS delivery and authorization without a live NAS."""
import hashlib
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from tests import test_asset_library_api as library_tests
from tests import test_file_tools as file_tests
from tests import test_asset_workflows as workflow_tests
from tests.test_remote_attachments import SOURCE
from vault_rag.asset_deliveries import AssetDeliveries


class RemoteAssetWorkflowTests(unittest.TestCase):
    setUp = library_tests.AssetLibraryApiTests.setUp
    request = library_tests.AssetLibraryApiTests.request
    settings = library_tests.AssetLibraryApiTests.settings
    configure = library_tests.AssetLibraryApiTests.configure
    setup_library = library_tests.AssetLibraryApiTests.setup_library
    def rpc(self, method, params=None, *, tunnel=False, token=None):
        from vault_rag.mcp_access import TUNNEL_AUTH_HEADER
        headers = {'Accept':'application/json, text/event-stream','Authorization':'Bearer '+(token or self.token)}
        if tunnel:headers[TUNNEL_AUTH_HEADER]=self.access.tunnel_authorization()
        return self.client.post('http://127.0.0.1:18080/mcp',headers=headers,
            json={'jsonrpc':'2.0','id':1,'method':method,'params':params or {}})
    call = file_tests.FileToolsTests.call
    wait_delivery = workflow_tests.AssetWorkflowTests.wait_delivery

    def prepare(self):
        try:
            candidate = self.setup_library()
        except IndexError:
            # Background sync may temporarily hold the catalog's nonblocking discovery lock.
            library = self.app.state.asset_library
            with library.lock:
                library._discover(str(self.root))
                candidate = library.listing(str(self.root))['items'][0]
        self.files = self.app.state.file_operations
        self.files.runtime.files.attachments.refresh()
        self.files.attachment_groups.update(str(self.root),'create',{'name':'Packages','search_enabled':True,'rules':{'formats':['unitypackage']}})
        self.access = self.app.state.mcp_access
        self.token = self.access.configure('local',enabled=True,write=True)['token']
        self.ws = self.config.data['revision']
        self.files.asset_deliveries.configure(str(self.home/'output'),'initial')
        return candidate

    def test_product_dedup_filters_and_actual_versions(self):
        candidate = self.prepare()
        self.request('POST','/api/asset-library/actions',json={'root':str(self.root),'action':'official','product_id':'123456',
            'official':{'title':'Mossy Ruins','publisher':'Fictional Studio','summary_zh':'潮湿苔藓废墟岩石',
                        'url':'https://assetstore.unity.com/packages/3d/mossy-ruins-123456',
                        'compatibility':{'render_pipelines':[{'pipelines':['lightweight'],'unity_version':'2022.3'}]}}})
        self.request('POST','/api/asset-library/actions',json={'root':str(self.root),'action':'bind','product_id':'123456',
            'asset_id':self.asset_id,'expected_revision':candidate['revision']})
        result = self.call('search_assets',query='苔藓',mode='keyword',pipeline='urp',source='remote')['results']
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['kind'],'product')
        self.assertEqual(result[0]['file_count'],1)
        detail = self.call('asset_details',result_id=result[0]['result_id'])
        self.assertEqual(detail['revision'],result[0]['revision'])
        self.assertEqual(detail['files'][0]['asset_id'],self.asset_id)
        self.assertIn('version',detail['files'][0])
        self.assertEqual(self.call('search_assets',query='苔藓',mode='keyword',source='local')['results'],[])
        self.assertEqual(self.call('search_assets',query='苔藓',mode='keyword',pipeline='hdrp')['results'],[])
        self.assertEqual(self.call('search_assets',query='苔藓',mode='keyword',formats=['png'])['results'],[])
        with self.remote.lock,self.remote._db(str(self.root)) as db:
            db.execute("UPDATE assets SET state='missing' WHERE id=?",(self.asset_id,))
        self.assertEqual(self.call('search_assets',query='苔藓',mode='keyword')['results'],[])
        self.call('asset_details',result_id=result[0]['result_id'],error='not_found')

    def test_product_details_do_not_include_other_package_copies(self):
        candidate = self.prepare()
        library = self.app.state.asset_library
        other_path = self.package.replace('Plugins/','Other/',1)
        self.dav.files[other_path]=b'another copy'
        with self.remote.lock,self.remote._db(str(self.root)) as db:
            other_id = self.remote._upsert(db,SOURCE,{'path':other_path,'size':len(self.dav.files[other_path]),'etag':'"fixture"'})
        with library.lock:
            library._discover(str(self.root))
            other = next(item for item in library.listing(str(self.root))['items'] if item['files'][0]['asset_id']==other_id)
        library.update(str(self.root),'official',{'product_id':'123456','official':{'title':'Scoped Room','publisher':'Fictional Studio'}})
        library.update(str(self.root),'bind',{'product_id':'123456','asset_id':self.asset_id},expected_revision=candidate['revision'])
        library.update(str(self.root),'bind',{'product_id':'123456','asset_id':other_id},expected_revision=other['revision'])
        groups = self.files.attachment_groups
        broad = groups.listing(str(self.root))['groups'][0]
        groups.update(str(self.root),'update',{'id':broad['id'],'revision':broad['revision'],
            'search_scope_revision':broad['search_scope_revision'],'search_enabled':False})
        restricted = groups.update(str(self.root),'create',{'name':'One copy','search_enabled':True})['groups'][-1]
        groups.update(str(self.root),'members',{'id':restricted['id'],'revision':restricted['revision'],
            'mode':'include','paths':[candidate['files'][0]['path']]})
        result = self.call('search_assets',query='Scoped Room',mode='keyword')['results'][0]
        self.assertEqual(result['file_count'],1)
        details = self.call('asset_details',result_id=result['result_id'])
        self.assertEqual([f['asset_id'] for f in details['files']],[self.asset_id])
        self.assertEqual([f['asset_id'] for f in details['product']['files']],[self.asset_id])

    def test_nas_delivery_cache_release_and_rotated_credential(self):
        candidate = self.prepare()
        detail = self.call('asset_details',result_id=candidate['id'])
        source = detail['files'][0]
        job = self.call('deliver_asset',write=True,path=source['path'],expected_revision=source['revision'])
        ready = self.wait_delivery(job['job_id'])
        self.assertEqual(ready['state'],'completed',ready)
        target = Path(ready['local_path'])
        self.assertEqual(target.read_bytes(),self.dav.files[self.package])
        self.assertEqual(ready['sha256'],hashlib.sha256(target.read_bytes()).hexdigest())
        staged = self.app.state.asset_downloads.list(str(self.root))['jobs']
        self.assertEqual(len(staged),1)
        self.app.state.asset_downloads.release(str(self.root),staged[0]['job_id'])
        self.assertEqual(target.read_bytes(),self.dav.files[self.package])
        self.token = self.access.configure('local',enabled=True,write=True,rotate=True)['token']
        self.call('delivery_status',job_id=job['job_id'],error='not_found')
        self.assertTrue(target.exists())

    def test_pending_delivery_restores_from_journal(self):
        candidate = self.prepare()
        source = self.call('asset_details',result_id=candidate['id'])['files'][0]
        old = self.files.asset_deliveries
        with patch.object(old,'_start'):
            job = self.call('deliver_asset',write=True,path=source['path'],expected_revision=source['revision'])
        old.stop()
        self.files.asset_deliveries = AssetDeliveries(self.files)
        ready = self.wait_delivery(job['job_id'])
        self.assertEqual(ready['state'],'completed',ready)
        self.assertEqual(Path(ready['local_path']).read_bytes(),self.dav.files[self.package])
