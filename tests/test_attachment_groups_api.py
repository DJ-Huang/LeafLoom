"""Group and download UI endpoints share rooted MCP authorization."""
import json
import time
import unittest
from unittest.mock import patch
from tests import test_attachment_storage_api as api_fixtures
from vault_rag.attachment_groups import AttachmentGroups


class AttachmentGroupsApiTests(unittest.TestCase):
    request=api_fixtures.AttachmentStorageApiTests.request
    mcp=api_fixtures.AttachmentStorageApiTests.mcp
    def setUp(self):
        with patch.object(AttachmentGroups,'_loop',return_value=None):
            api_fixtures.AttachmentStorageApiTests.setUp(self)

    def test_local_group_roundtrip_listing_and_readonly_mcp(self):
        path=self.root/'_attachments'/'fictional.png';path.parent.mkdir();path.write_bytes(b'fixture')
        self.app.state.runtime.files.attachments.refresh()
        group=self.request('POST','/api/attachment-groups',json={'root':str(self.root),'operation':'create','payload':{'name':'Pictures','rules':{'formats':['png']}}}).json()['groups'][0]
        index=self.app.state.attachment_index_jobs
        with patch.object(index,'status',return_value={'usable':True}):
            result=self.request('GET','/api/attachments',params={'root':str(self.root),'group_id':group['id']}).json()
            self.assertEqual(result['total'],1,result)
        group=self.request('POST','/api/attachment-groups',json={'root':str(self.root),'operation':'members','payload':{'id':group['id'],'revision':group['revision'],'mode':'exclude','paths':['_attachments/fictional.png']}}).json()['groups'][0]
        self.request('POST','/api/attachment-groups',expected=409,json={'root':str(self.root),'operation':'update','payload':{'id':group['id'],'revision':'stale','name':'Bad'}})
        self.mcp_token=self.app.state.mcp_access.configure('local',enabled=True,write=False)['token']
        self.assertEqual(self.mcp('groups')['groups'][0]['name'],'Pictures')
        response=self.client.post(f'http://127.0.0.1:{self.config.data.get("port",18080)}/mcp',headers={'Accept':'application/json, text/event-stream','Authorization':'Bearer '+self.mcp_token},json={'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'vault_files_update','arguments':{'request':{'action':'group_update','operation':'delete','payload':{'id':group['id'],'revision':group['revision']}},'workspace_revision':self.config.data['revision'],'operation_id':'readonly-group'}}})
        self.assertTrue(response.json()['result']['isError'])
        self.assertEqual(len(self.app.state.attachment_groups.listing(str(self.root))['groups']),1)
        self.request('POST','/api/attachment-groups',json={'root':str(self.root),'operation':'delete','payload':{'id':group['id'],'revision':group['revision']}})
        self.assertEqual(path.read_bytes(),b'fixture')

    def test_downloads_recover_archive_and_capacity_cas(self):
        path=self.root/'_attachments'/'fictional.png';path.parent.mkdir();path.write_bytes(b'fixture')
        job=self.request('POST','/api/attachments/downloads',json={'root':str(self.root),'paths':['_attachments/fictional.png']}).json()
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            current=self.request('GET','/api/attachments/downloads/'+job['id'],params={'root':str(self.root)}).json()
            if current['state']!='running':break
            time.sleep(.01)
        self.assertEqual(current['state'],'completed')
        result=self.request('GET','/api/attachment-downloads',params={'root':str(self.root)}).json()
        self.assertEqual(result['archives'][0]['id'],job['id'])
        self.assertNotIn('root',result['archives'][0])
        settings=self.request('GET','/api/attachment-downloads/settings',params={'root':str(self.root)}).json()
        self.request('PUT','/api/attachment-downloads/settings',json={'root':str(self.root),'revision':settings['revision'],'max_bytes':1024**3})
        self.request('PUT','/api/attachment-downloads/settings',expected=409,json={'root':str(self.root),'revision':settings['revision'],'max_bytes':2*1024**3})
        self.request('GET','/api/attachments/downloads/'+job['id']+'/file',params={'root':str(self.root)})
        record=self.app.state.attachments_workspace._download_path(self.app.state.runtime.files,job['id'],'job.json')
        saved=json.loads(record.read_text());saved['created_at']-=7200;record.write_text(json.dumps(saved))
        expired=self.request('GET','/api/attachment-downloads',params={'root':str(self.root)}).json()['archives'][0]
        self.assertEqual(expired['state'],'expired')
        self.request('DELETE','/api/attachments/downloads/'+job['id'],params={'root':str(self.root)})
        self.assertEqual(path.read_bytes(),b'fixture')
