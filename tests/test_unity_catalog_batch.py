"""Batch selection and metadata writes use fictional inventory and store data."""
from contextlib import redirect_stdout,redirect_stderr
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch

from PIL import Image

from scripts import collect_unity_catalog as cli
from tests import test_asset_library_api as api_fixtures
from vault_rag.attachment_presentation import AttachmentPresentation
from vault_rag.local_state import ConflictError
from vault_rag.unity_asset_store import AssetEnrichment,OfficialSourceError,UnityOfficialSource,_refresh_official


URL='https://assetstore.unity.com/packages/tools/fictional-room-123456'
PRODUCT='unity.assetstore:123456'
CANDIDATE='candidate:'+'a'*32
FACTS={'product_id':PRODUCT,'url':URL,'title':'Fictional Room','publisher':'Fictional Studio',
       'source_excerpt':'A modular room for games.','keywords':['room'],'categories':['3D/Environments']}


class InlineThread:
    def __init__(self,*,target,args,**kwargs):self.target=target;self.args=args
    def start(self):self.target(*self.args)
    def is_alive(self):return False


class BatchSelectionTests(unittest.TestCase):
    def setUp(self):
        self.library=Mock();self.source=Mock()
        self.service=AssetEnrichment(self.library,source=self.source)
        self.file={'asset_id':'file-1','path':'Asset Store-5.x/Fictional Studio/Fictional Room.unitypackage'}

    def test_preview_includes_incomplete_products_respects_empty_scope_and_never_fetches(self):
        complete={'id':PRODUCT,'product_id':'123456','official':{**FACTS,'cover':{'sha256':'test'}},'files':[self.file]}
        incomplete={**complete,'id':'unity.assetstore:2','product_id':'2','official':{}}
        candidate={'id':CANDIDATE,'files':[self.file]}
        conflict={**incomplete,'id':'unity.assetstore:3','conflicts':['conflict']}
        self.library._items.return_value=[complete,incomplete,candidate,conflict]
        with patch.object(self.service,'_save') as save:
            preview=self.service.plan('/synthetic')
            self.assertEqual((preview['total'],preview['products'],preview['candidates']),(2,1,1))
            self.assertEqual(preview['items'][0]['missing_fields'],['cover','tags','description'])
            self.assertEqual(self.service.plan('/synthetic',item_ids=[])['total'],0)
            self.assertEqual(self.service.plan('/synthetic',asset_ids=[])['total'],0)
            self.assertEqual(self.service.plan('/synthetic',asset_ids=['file-1'])['total'],2)
            self.assertEqual(self.service.plan('/synthetic',refresh=True,limit=1)['items'][0]['id'],PRODUCT)
            save.assert_not_called()
        self.assertEqual(self.source.mock_calls,[])
        self.library.update.assert_not_called()
        for options in ({'limit':True},{'delay':float('nan')},{'item_ids':['invalid']},{'refresh':1}):
            with self.subTest(options=options),self.assertRaises(ValueError):self.service.plan('/synthetic',**options)

    def test_partial_products_retry_and_different_running_scope_is_rejected(self):
        item={'id':PRODUCT,'product_id':'123456','official':{},'files':[self.file]}
        self.library._items.return_value=[item]
        old={'state':'completed','job_id':'old','results':[{'id':PRODUCT,'state':'succeeded'}]}
        with patch.object(self.service,'status',return_value=old),patch.object(self.service,'_save'),\
             patch.object(self.service,'_run') as run,patch('vault_rag.unity_asset_store.CollectionThread',InlineThread):
            self.service.start('/synthetic')
            self.assertEqual(run.call_args.args[1],[item])
        self.service.threads['/synthetic']=Mock()
        self.service.threads['/synthetic'].is_alive.return_value=True
        with patch.object(self.service,'status',return_value=old),self.assertRaises(ConflictError):
            self.service.start('/synthetic',item_ids=[])

    def test_interrupted_collection_can_change_pacing_without_losing_results(self):
        item={'id':PRODUCT,'product_id':'123456','official':{},'files':[self.file]}
        self.library._items.return_value=[item]
        previous={'id':CANDIDATE,'state':'needs_review','product_id':PRODUCT,'reason':'official_metadata_incomplete','missing_fields':['tags']}
        old={'state':'interrupted','job_id':'existing','scope':self.service._scope(None,0,False,1),
             'total':2,'inputs':[{'id':CANDIDATE,'file_uid':'a'*32},{'id':PRODUCT,'file_uid':''}],
             'results':[previous]}
        with patch.object(self.service,'status',return_value=old),patch.object(self.service,'_save'),\
             patch.object(self.service,'_run') as run,patch('vault_rag.unity_asset_store.CollectionThread',InlineThread):
            job=self.service.start('/synthetic',delay=.5)
        self.assertEqual((job['job_id'],job['total'],job['needs_review']),('existing',2,1))
        self.assertEqual(job['results'],[previous]);self.assertEqual(job['delay_seconds'],.5)
        self.assertEqual(run.call_args.args[1],[item])
        old.update(state='paused',error='official_source_rate_limited')
        with patch.object(self.service,'status',return_value=old),patch.object(self.service,'_save'),\
             patch.object(self.service,'_run') as run,patch('vault_rag.unity_asset_store.CollectionThread',InlineThread):
            job=self.service.start('/synthetic',delay=.5)
        self.assertEqual((job['job_id'],job['total'],job['needs_review']),('existing',2,1))
        self.assertEqual(job['results'],[previous]);self.assertEqual(run.call_args.args[1],[item])

    def test_known_product_uses_id_and_reports_partial_cover_and_rate_limit(self):
        item={'id':PRODUCT,'product_id':'123456','revision':'r','files':[self.file]}
        self.source.product.return_value=FACTS
        for warnings,expected_state in (([],'completed'),(['official_source_rate_limited'],'paused')):
            job={'state':'running','total':1,'succeeded':0,'needs_review':0,'failed':0,'results':[]}
            with patch.object(self.service,'_save'),patch.object(self.service,'_review'),\
                 patch.object(self.service.stopped,'wait',return_value=False),\
                 patch.object(self.service,'official_url',return_value={'official':FACTS,'collection_warnings':warnings}) as update:
                self.service._run('/synthetic',[item],job,'local',None)
            self.assertEqual(job['state'],expected_state)
            self.assertEqual((job['succeeded'],job['needs_review']),(0,1))
            self.assertEqual(update.call_args.kwargs['asset_id'],'')
            self.assertEqual(update.call_args.kwargs['expected_revision'],'r')
            if not warnings:self.assertEqual(job['results'][0]['missing_fields'],['cover'])
        self.source.search.assert_not_called()
        self.source.product.assert_called_with('https://assetstore.unity.com/packages/package/123456')

    def test_title_only_match_proposes_product_without_binding(self):
        item={'id':CANDIDATE,'files':[{'asset_id':'file-1','path':'Packages/Fictional Room.unitypackage'}]}
        self.source.search.return_value=[URL];self.source.product.return_value=FACTS
        job={'state':'running','succeeded':0,'needs_review':0,'failed':0,'results':[]}
        with patch.object(self.service,'_save'),patch.object(self.service,'_review') as review,\
             patch.object(self.service,'official_url') as update,patch.object(self.service.stopped,'wait',return_value=False):
            self.service._run('/synthetic',[item],job,'local',None)
        self.assertEqual(job['results'][0]['reason'],'publisher_requires_confirmation')
        self.assertEqual(review.call_args.kwargs['proposed_product_id'],'123456')
        update.assert_not_called()

    def test_official_lookups_are_bounded_and_writes_are_serial(self):
        gate=threading.Barrier(3);lock=threading.Lock();running=0;maximum=0;write_threads=[]
        def search(title,publisher):
            nonlocal running,maximum
            with lock:running+=1;maximum=max(maximum,running)
            try:gate.wait(timeout=3);return []
            finally:
                with lock:running-=1
        self.source.search.side_effect=search
        items=[{'id':'candidate:'+format(index,'032x'),'files':[{'asset_id':str(index),'path':'Asset Store-5.x/Fictional Studio/Item '+str(index)+'.unitypackage'}]} for index in range(3)]
        job={'state':'running','total':3,'succeeded':0,'needs_review':0,'failed':0,'results':[]}
        with patch.object(self.service,'_save'),patch.object(self.service,'_review',side_effect=lambda *a,**k:write_threads.append(threading.current_thread().name)),\
             patch.object(self.service.stopped,'wait',return_value=False):
            self.service._run('/synthetic',items,job,'local',None)
        self.assertEqual((maximum,job['state'],job['needs_review']),(3,'completed',3))
        self.assertEqual(write_threads,[threading.current_thread().name]*3)

    def test_slow_lookup_does_not_block_other_results(self):
        started=threading.Event();release=threading.Event();fast_reviewed=threading.Event()
        def search(title,publisher):
            if title=='Slow':
                started.set()
                if not release.wait(3):raise AssertionError('Slow lookup was not released')
            return []
        self.source.search.side_effect=search
        items=[{'id':'candidate:'+format(index,'032x'),'files':[{'asset_id':str(index),'path':'Asset Store-5.x/Fictional Studio/'+title+'.unitypackage'}]} for index,title in enumerate(('Slow','Fast'))]
        job={'state':'running','total':2,'succeeded':0,'needs_review':0,'failed':0,'results':[]}
        def review(root,identity,*args,**kwargs):
            if identity==items[1]['id']:fast_reviewed.set()
        with patch.object(self.service,'_save'),patch.object(self.service,'_review',side_effect=review),\
             patch.object(self.service.stopped,'wait',return_value=False):
            thread=threading.Thread(target=self.service._run,args=('/synthetic',items,job,'local',None));thread.start()
            try:self.assertTrue(started.wait(2));self.assertTrue(fast_reviewed.wait(2))
            finally:release.set();thread.join(timeout=5)
        self.assertFalse(thread.is_alive());self.assertEqual((job['state'],job['needs_review']),('completed',2))

    def test_rate_limit_stops_new_requests_and_preserves_unfinished_inputs(self):
        gate=threading.Barrier(3);lock=threading.Lock();calls=[];finished=threading.Event();completed=[]
        def fetch(url):
            with lock:calls.append(url)
            gate.wait(timeout=3)
            if 'q=Limit' in url:raise OfficialSourceError('official_source_rate_limited')
            raise OSError('temporary outage')
        class TrackedSource(UnityOfficialSource):
            def search(self,*args,**kwargs):
                try:return super().search(*args,**kwargs)
                finally:
                    with lock:
                        completed.append(True)
                        if len(completed)==3:finished.set()
        self.service.source=TrackedSource(fetch=fetch)
        items=[{'id':'candidate:'+format(index,'032x'),'files':[{'asset_id':str(index),'path':'Asset Store-5.x/Fictional Studio/'+title+'.unitypackage'}]} for index,title in enumerate(('Limit','One','Two'))]
        job={'state':'running','total':3,'succeeded':0,'needs_review':0,'failed':0,'results':[]}
        with patch.object(self.service,'_save'),patch.object(self.service,'_review') as review,patch.object(self.service,'official_url') as update:
            self.service._run('/synthetic',items,job,'local',None)
        self.assertTrue(finished.wait(3))
        self.assertEqual((job['state'],job.get('error')),('paused','official_source_rate_limited'))
        self.assertEqual(job['results'],[]);self.assertEqual(len(calls),3)
        review.assert_not_called();update.assert_not_called()

    def test_cover_rate_limit_keeps_active_checkpoint_for_recovery(self):
        item={'id':CANDIDATE,'files':[self.file]};self.source.search.return_value=[URL];self.source.product.return_value=FACTS
        self.source.cover.side_effect=OfficialSourceError('official_source_rate_limited')
        def update(*args,**kwargs):
            try:kwargs['_cover_request']('https://example.invalid/cover')
            except OfficialSourceError:return {'official':FACTS,'collection_warnings':['official_source_rate_limited']}
        job={'state':'running','total':1,'succeeded':0,'needs_review':0,'failed':0,'results':[]}
        with patch.object(self.service,'_save'),patch.object(self.service,'_review') as review,patch.object(self.service,'official_url',side_effect=update):
            self.service._run('/synthetic',[item],job,'local',None)
        self.assertEqual((job['state'],job.get('error')),('paused','official_source_rate_limited'))
        self.assertEqual(job['results'],[]);self.assertEqual(job['active']['id'],CANDIDATE)
        review.assert_not_called()

    def test_empty_refresh_preserves_known_facts_and_attachment_excerpt_respects_personal_metadata(self):
        previous={**FACTS,'summary_zh':'已有中文简介。'}
        refreshed=_refresh_official({'keywords':[],'source_excerpt':'','summary_zh':'','summary_status':'needs_summary'},previous)
        self.assertNotIn('keywords',refreshed);self.assertNotIn('source_excerpt',refreshed)
        self.assertNotIn('summary_zh',refreshed)
        self.library._items.return_value=[{'official':FACTS,'personal':{},'files':[self.file],'product_id':'123456'}]
        presentation=AttachmentPresentation(Mock(),self.library)
        self.assertEqual(presentation.enrich('/synthetic',{'asset_id':'file-1'})['description'],FACTS['source_excerpt'])
        own=presentation.enrich('/synthetic',{'asset_id':'file-1','description':'My note','tags':['mine']})
        self.assertEqual(own['description'],'My note');self.assertEqual(own['tags'],['mine','room'])


class BatchCliTests(unittest.TestCase):
    def test_group_pagination_and_preview_only_use_local_api_without_starting(self):
        requests=[]
        class API:
            def __init__(self,*args,**kwargs):pass
            def request(self,method,path,body=None):
                requests.append((method,path,body))
                if path.startswith('/api/attachment-groups?'):return {'groups':[{'id':'group-1','name':'Unity Asset'}]}
                if path.startswith('/api/attachments?'):
                    if 'cursor=next' in path:return {'items':[{'asset_id':'file-2'}]}
                    return {'items':[{'asset_id':'file-1'}],'next_cursor':'next'}
                if path.startswith('/api/asset-library?'):
                    return {'items':[{'id':PRODUCT,'files':[{'asset_id':'file-2'}]},
                        {'id':CANDIDATE,'files':[{'asset_id':'other-group'}]}]}
                if path=='/api/asset-library/enrichment/plan':
                    return {'state':'preview','total':1,'products':1,'candidates':0,
                        'items':[{'id':PRODUCT,'missing_fields':['cover']}],'token':'must-not-leak'}
                raise AssertionError('Preview must not start a collection: '+path)
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);token=directory/'token';token.write_text('synthetic-token')
            report=directory/'report.json';output=io.StringIO()
            with patch.object(cli,'LocalAPI',API),redirect_stdout(output),redirect_stderr(output):
                self.assertEqual(cli.main(['--root',str(directory/'vault'),'--token-file',str(token),'--dry-run',
                    '--group','Unity Asset','--limit','10','--report',str(report)]),0)
            self.assertEqual(requests[-1][2]['asset_ids'],['file-1','file-2'])
            saved=report.read_text()
            self.assertNotIn('must-not-leak',saved);self.assertNotIn(str(directory/'vault'),saved)
            self.assertEqual(json.loads(saved)['results'][0]['missing_fields'],['cover'])


class BatchApiTests(unittest.TestCase):
    setUp=api_fixtures.AssetLibraryApiTests.setUp
    request=api_fixtures.AssetLibraryApiTests.request
    settings=api_fixtures.AssetLibraryApiTests.settings
    configure=api_fixtures.AssetLibraryApiTests.configure
    setup_library=api_fixtures.AssetLibraryApiTests.setup_library

    def test_plan_does_not_write_and_start_fills_bound_product_without_touching_original(self):
        candidate=self.setup_library();root=str(self.root);library=self.app.state.asset_library
        library.update(root,'official',{'product_id':'123456','official':{'title':'Old title'}})
        bound=library.update(root,'bind',{'product_id':'123456','asset_id':self.asset_id},expected_revision=candidate['revision'])
        library.update(root,'personal',{'product_id':'123456','personal':{'tags':['mine'],'description':'My note'}},expected_revision=bound['revision'])
        before=copy.deepcopy(library.detail(root,PRODUCT));original=self.dav.files[self.package]
        source=self.app.state.asset_enrichment.source
        with patch.object(source,'product') as product,patch.object(source,'search') as search:
            preview=self.request('POST','/api/asset-library/enrichment/plan',json={'root':root}).json()
        self.assertEqual(preview['items'][0]['missing_fields'],['cover','tags','description'])
        self.assertEqual(library.detail(root,PRODUCT),before)
        product.assert_not_called();search.assert_not_called()
        self.request('POST','/api/asset-library/enrichment/plan',json={'root':root,'item_ids':[]})
        self.assertEqual(self.app.state.asset_enrichment.status(root)['state'],'idle')
        image=io.BytesIO();Image.new('RGB',(20,10),'green').save(image,'WEBP')
        data={**FACTS,'cover_source_url':'https://unity-assetstorev2-prd.storage.googleapis.com/fictional.webp'}
        with patch.object(source,'product',return_value=data),patch.object(source,'cover',return_value=image.getvalue()),\
             patch.object(source,'search',side_effect=AssertionError('Known IDs must bypass search')),\
             patch.object(self.app.state.asset_enrichment.stopped,'wait',return_value=False):
            self.request('POST','/api/asset-library/enrichment/start',json={'root':root,'item_ids':[PRODUCT]})
            self.app.state.asset_enrichment.threads[root].join(timeout=5)
            result=self.app.state.asset_enrichment.status(root)
        self.assertEqual((result['state'],result['succeeded']),("completed",1),result)
        updated=library.detail(root,PRODUCT)
        self.assertEqual(updated['official']['keywords'],['room'])
        self.assertTrue(updated['official']['cover'])
        self.assertEqual(updated['personal'],before['personal'])
        self.assertEqual(updated['files'],before['files'])
        self.assertEqual(self.dav.files[self.package],original)
        self.assertEqual(self.request('POST','/api/asset-library/enrichment/plan',json={'root':root}).json()['total'],0)


if __name__=='__main__':unittest.main()
