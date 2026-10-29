"""Asset retrieval and durable delivery against fictional isolated files and HTTP MCP."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image
from tests import test_file_tools as file_tests
from vault_rag.file_commands import SearchAssets
from vault_rag.asset_vectors import execute
from vault_rag.asset_search import signature


class AssetWorkflowTests(unittest.TestCase):
    setUp = file_tests.FileToolsTests.setUp
    rpc = file_tests.FileToolsTests.rpc
    call = file_tests.FileToolsTests.call
    put = file_tests.FileToolsTests.put

    def prepare(self):
        picture = io.BytesIO()
        Image.new('RGB',(16,12),'green').save(picture,'PNG')
        self.data = picture.getvalue()
        self.put('Materials/苔藓岩石.png',self.data)
        self.put('Models/rock.fbx',b'fictional-model')
        self.app.state.runtime.files.attachments.refresh()
        self.files = self.app.state.file_operations
        self.files.attachment_groups.update(str(self.root),'create',{'name':'Asset fixtures','search_enabled':True,'rules':{'directories':['Materials','Models']}})
        self.files.asset_deliveries.configure(str(self.home/'delivered'),'initial')
        return self.call('search_assets',query='苔藓',mode='keyword')['results'][0]

    def wait_delivery(self, key):
        deadline = time.monotonic()+8
        while time.monotonic()<deadline:
            value = self.call('delivery_status',job_id=key)
            if value['state'] not in {'queued','downloading','copying','verifying'}:
                return value
            time.sleep(.01)
        self.fail('Delivery did not finish')

    def test_keyword_details_native_preview_and_semantic_degradation(self):
        result = self.prepare()
        self.assertEqual(result['preview_kind'],'file_thumbnail')
        details = self.call('asset_details',result_id=result['result_id'])
        self.assertEqual(details['revision'],result['revision'])
        self.assertEqual(details['files'][0]['selection']['path'],'Materials/苔藓岩石.png')
        response = self.rpc('tools/call',{'name':'vault_files','arguments':{'workspace_revision':self.ws,
            'request':{'action':'asset_preview','result_id':result['result_id'],'expected_revision':result['revision']}}}).json()['result']
        self.assertFalse(response.get('isError'),response)
        self.assertEqual(response['structuredContent']['preview_kind'],'file_thumbnail')
        self.assertNotIn('_image',response['structuredContent'])
        self.assertEqual(response['content'][1]['type'],'image')
        with Image.open(io.BytesIO(base64.b64decode(response['content'][1]['data']))) as image:
            self.assertEqual(image.size,(16,12))
        hybrid = self.call('search_assets',query='苔藓')
        self.assertEqual(hybrid['mode'],'keyword')
        self.assertEqual(hybrid['degraded_reason'],'semantic_index_disabled')
        empty = self.call('search_assets',query='苔藓',mode='keyword',formats=['fbx'])
        self.assertEqual(empty['results'],[])
        unknown = self.call('search_assets',query='rock',mode='keyword',pipeline='unknown')['results'][0]
        self.assertEqual(unknown['pipelines'],[])
        self.assertEqual(self.call('asset_preview',result_id=unknown['result_id'],expected_revision=unknown['revision'])['preview_kind'],'unsupported')
        self.put('Materials/苔藓岩石.png',b'changed')
        self.files.runtime.files.attachments.refresh()
        self.call('asset_preview',result_id=result['result_id'],expected_revision=result['revision'],error='write_conflict')

    def test_delivery_bytes_persistence_idempotency_and_source_revisions(self):
        result = self.prepare()
        details = self.call('asset_details',result_id=result['result_id'])
        source = details['files'][0]
        args = {'path':source['path'],'expected_revision':source['revision']}
        job = self.call('deliver_asset',write=True,operation_id='deliver-once',**args)
        ready = self.wait_delivery(job['job_id'])
        self.assertEqual(ready['state'],'completed',ready)
        target = Path(ready['local_path'])
        self.assertEqual(target.read_bytes(),self.data)
        self.assertEqual(ready['sha256'],hashlib.sha256(self.data).hexdigest())
        replay = self.call('deliver_asset',write=True,operation_id='deliver-once',**args)
        self.assertEqual(replay['local_path'],str(target))
        self.assertEqual(len(list((self.home/'delivered').iterdir())),1)
        self.assertEqual(ready['device']['path_location'],'service_host')
        self.app.state.asset_downloads.configure(str(self.root),1024**3)
        self.assertEqual(target.read_bytes(),self.data)
        self.put(source['path'],b'new source')
        self.call('deliver_asset',write=True,**args,error='write_conflict')
        self.files.asset_deliveries.configure(str(self.home/'elsewhere'),self.files.asset_deliveries.settings()['revision'])
        self.call('deliver_asset',write=True,operation_id='deliver-once',**args,error='write_conflict')
        target.unlink()
        self.assertEqual(self.call('delivery_status',job_id=job['job_id'])['state'],'unavailable')

    def test_permissions_no_arbitrary_destination_and_link_rejection(self):
        result = self.prepare()
        source = self.call('asset_details',result_id=result['result_id'])['files'][0]
        self.call('deliver_asset',write=True,path=source['path'],expected_revision=source['revision'],destination='/tmp/no',error='validation')
        self.access.configure('local',enabled=True,write=False)
        self.call('deliver_asset',write=True,path=source['path'],expected_revision=source['revision'],error='permission_denied')
        link = self.home/'linked'
        link.symlink_to(self.home/'delivered',target_is_directory=True)
        with self.assertRaises(ValueError):
            self.files.asset_deliveries.configure(str(link),'anything')

    def test_no_matching_words_and_exact_name_priority(self):
        self.prepare()
        self.assertEqual(self.call('search_assets',query='不存在',mode='keyword')['results'],[])
        self.assertEqual(self.call('search_assets',query='rock.fbx',mode='keyword')['results'][0]['title'],'rock.fbx')

    def test_semantic_only_matches_and_timeout_fallback(self):
        from types import SimpleNamespace
        result = self.prepare()
        search = self.files.asset_search
        directory = search.directory()
        directory.mkdir(parents=True,exist_ok=True)
        (directory/'current.json').write_text(json.dumps({'scope_version':1,'scope_revision':search.scope()['scope_revision'],'fingerprint':'synthetic'}))
        with patch.object(self.files.runtime,'model',SimpleNamespace(ready=True,fingerprint='synthetic')), \
             patch.object(search,'settings',return_value={'enabled':True,'revision':'synthetic'}), \
             patch.object(search,'schedule'), \
             patch.object(self.files.runtime.rag,'request',return_value=[{'id':result['result_id'],'similarity':0.8}]):
            value = self.call('search_assets',query='damp overgrown ruins')
            self.assertEqual(value['mode'],'hybrid')
            self.assertEqual(value['results'][0]['match_channel'],'semantic')
        with patch.object(self.files.runtime,'model',SimpleNamespace(ready=True,fingerprint='synthetic')), \
             patch.object(search,'settings',return_value={'enabled':True,'revision':'synthetic'}), \
             patch.object(search,'schedule'), \
             patch.object(self.files.runtime.rag,'request',side_effect=TimeoutError):
            value = self.call('search_assets',query='rock')
            self.assertEqual(value['degraded_reason'],'semantic_query_timeout')
            self.assertEqual(value['results'][0]['title'],'rock.fbx')

    def test_rebuild_invalidates_asset_manifest_without_touching_note_snapshot(self):
        self.prepare()
        search = self.files.asset_search
        settings = search.configure(True,'initial')
        manifest = search.directory()/'current.json'
        manifest.write_text('{}')
        note_snapshot = self.files.runtime.knowledge.snapshot
        with patch.object(search,'schedule') as schedule:
            search.rebuild(str(self.root),settings['revision'])
            schedule.assert_called_once()
        self.assertFalse(manifest.exists())
        self.assertIs(self.files.runtime.knowledge.snapshot,note_snapshot)

    def test_disk_failure_and_retry_then_cancelled_output_is_preserved(self):
        from types import SimpleNamespace
        result = self.prepare()
        source = self.call('asset_details',result_id=result['result_id'])['files'][0]
        args = {'path':source['path'],'expected_revision':source['revision']}
        with patch('vault_rag.asset_deliveries.shutil.disk_usage',return_value=SimpleNamespace(free=0)):
            job = self.call('deliver_asset',write=True,**args)
            failed = self.wait_delivery(job['job_id'])
        self.assertEqual(failed['state'],'failed',failed)
        self.assertNotIn('local_path',failed)
        self.call('delivery_control',write=True,job_id=job['job_id'],command='retry',expected_revision=failed['revision'])
        ready = self.wait_delivery(job['job_id'])
        self.assertEqual(ready['state'],'completed',ready)
        cancelled = self.call('delivery_control',write=True,job_id=job['job_id'],command='cancel',expected_revision=ready['revision'])
        self.assertEqual(cancelled['state'],'completed')
        self.assertEqual(Path(cancelled['local_path']).read_bytes(),self.data)

    def test_revocation_and_cross_connection_cannot_deliver_or_read_path(self):
        result = self.prepare()
        source = self.call('asset_details',result_id=result['result_id'])['files'][0]
        deliveries = self.files.asset_deliveries
        deliveries.copy_lock.acquire()
        try:
            job = self.call('deliver_asset',write=True,path=source['path'],expected_revision=source['revision'])
            self.access.configure('local',enabled=True,write=False)
        finally:
            deliveries.copy_lock.release()
        paused = self.wait_delivery(job['job_id'])
        self.assertEqual(paused['state'],'paused',paused)
        self.assertNotIn('local_path',paused)
        self.access.configure('tunnel',enabled=True,write=True)
        self.call('delivery_status',job_id=job['job_id'],tunnel=True,error='not_found')
        self.access.configure('local',enabled=True,write=True)
        self.call('delivery_control',write=True,job_id=job['job_id'],command='retry',expected_revision=paused['revision'])
        ready = self.wait_delivery(job['job_id'])
        self.assertEqual(ready['state'],'completed',ready)


class AssetVectorsTests(unittest.TestCase):
    def test_incremental_vectors_published_ids_and_updated_hashes(self):
        import numpy as np
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            directory = root/'.vault-rag'/'asset-search'
            config = SimpleNamespace(root=root)
            class Model:
                ready, fingerprint = True, 'synthetic-model'
                calls = 0
                def encode(self,texts):
                    self.calls += 1
                    return np.asarray([[1.,0.] if 'moss' in t else [0.,1.] for t in texts])
            model = Model()
            entries = [{'id':'one','text':'moss rock','hash':signature('moss rock')},
                       {'id':'two','text':'smoke','hash':signature('smoke')}]
            value = {'operation':'asset_build','directory':str(directory),'entries':entries,'fingerprint':model.fingerprint}
            execute(config,model,value)
            execute(config,model,value)
            self.assertEqual(model.calls,1)
            (directory/'current.json').write_text(json.dumps({'fingerprint':model.fingerprint,'entries':entries}))
            hits = execute(config,model,{**value,'operation':'asset_dense','query':'moss','entries':[entries[0],{'id':'two','hash':'changed'}]})
            self.assertEqual([h['id'] for h in hits],['one'])
            with self.assertRaises(ValueError):
                execute(config,model,{**value,'directory':str(root)})
