"""Official source parsing is tested with fictional pages; no live store access."""
import io
import copy
import json
import unittest
from unittest.mock import Mock,patch
import ssl

from PIL import Image

from vault_rag.unity_asset_store import (OfficialSourceError, UnityOfficialSource,
    AssetEnrichment,_system_https_proxy,normalized, official_url, package_hint, parse_product)


URL='https://assetstore.unity.com/packages/3d/environments/fictional-room-123456'


def page(**changes):
    product={'@type':'Product','name':'Fictional Room','brand':{'name':'Fictional Studio'},
             'url':URL,'description':'A modular room with furniture and warm lighting.',
             'category':'3D/Environments','keywords':'room, furniture',
             'image':'https://unity-assetstorev2-prd.storage.googleapis.com/fictional.png'}
    product.update(changes)
    return '<script type="application/ld+json">'+json.dumps(product)+'</script>'


class OfficialSourceTests(unittest.TestCase):
    def test_identity_is_structured_and_canonical(self):
        value=parse_product(page(),URL)
        self.assertEqual(value['product_id'],'unity.assetstore:123456')
        self.assertEqual(value['publisher'],'Fictional Studio')
        self.assertEqual(value['categories'],['3D/Environments'])
        self.assertEqual(value['keywords'],['room','furniture'])
        self.assertEqual(value['summary_zh'],'')
        self.assertEqual(value['compatibility'],{})

    def test_login_opengraph_and_wrong_products_never_import(self):
        for html in ('<title>Sign in</title><meta property="og:title" content="Fictional Room">',
                     page(url=URL.replace('123456','999999')),
                     page(brand=None),page()+page()):
            with self.subTest(html=html),self.assertRaises(OfficialSourceError):parse_product(html,URL)

    def test_urls_cannot_escape_official_host(self):
        for url in ('http://assetstore.unity.com/packages/foo-123',
                    'https://assetstore.unity.com.evil.invalid/packages/foo-123',
                    'https://user:secret@assetstore.unity.com/packages/foo-123',
                    'https://assetstore.unity.com:444/packages/foo-123',
                    'https://assetstore.unity.com/account'):
            with self.subTest(url=url),self.assertRaises(ValueError):official_url(url)
        with patch('vault_rag.unity_asset_store.public_target') as resolve:
            with self.assertRaises(OfficialSourceError):
                UnityOfficialSource._fetch('https://127.0.0.1/private',image=True)
            resolve.assert_not_called()

    def test_public_entity_identity_without_jsonld_is_still_verified(self):
        entities={'Product':{'123456':{'id':'123456','name':'Fictional Room',
            'description':'A room with modular walls.','publisher':{'type':'id','id':['ProductPublisher','7']}}},
            'ProductPublisher':{'7':{'id':'7','name':'Fictional Studio'}}}
        def content():
            return '<meta property="og:url" content="'+URL+'"><script>component.ReactDOMrender('+json.dumps({'data':{'ENTITY':entities}})+',document.body)</script>'
        value=parse_product(content(),URL)
        self.assertEqual(value['product_id'],'unity.assetstore:123456')
        self.assertEqual(value['publisher'],'Fictional Studio')
        self.assertEqual(value['source_excerpt'],'A room with modular walls.')
        for change in ('wrong_product','wrong_publisher','missing_publisher'):
            broken=copy.deepcopy(entities)
            if change=='wrong_product':broken['Product']['123456']['id']='999999'
            elif change=='wrong_publisher':broken['ProductPublisher']['7']['id']='8'
            else:broken['ProductPublisher']['7']['name']=''
            html='<script>component.ReactDOMrender('+json.dumps({'data':{'ENTITY':broken}})+',document.body)</script>'
            with self.subTest(change=change),self.assertRaises(OfficialSourceError):parse_product(html,URL)
        with self.assertRaises(OfficialSourceError):parse_product(content().replace(URL,URL.replace('123456','999999')),URL)
        with self.assertRaises(OfficialSourceError):parse_product(page()+page()+content(),URL)
        for state in ({'data':None},{'data':{'ENTITY':{'Product':[]}}}):
            malformed='<script>component.ReactDOMrender('+json.dumps(state)+',document.body)</script>'
            with self.subTest(state=state),self.assertRaises(OfficialSourceError):parse_product(malformed,URL)

    def test_official_cover_is_decoded_and_reencoded(self):
        image=io.BytesIO();Image.new('RGB',(80,40),'red').save(image,'PNG')
        source=UnityOfficialSource(fetch=lambda *a,**k:image.getvalue())
        cover=source.cover('https://unity-assetstorev2-prd.storage.googleapis.com/fictional.png')
        with Image.open(io.BytesIO(cover)) as picture:self.assertEqual(picture.format,'WEBP')
        bad=UnityOfficialSource(fetch=lambda *a,**k:b'<html>Login</html>')
        with self.assertRaises(OfficialSourceError):bad.cover('https://unity-assetstorev2-prd.storage.googleapis.com/fictional.png')

    def test_filename_hints_are_not_product_identity(self):
        title,publisher=package_hint({'path':'Plugins/Asset Store-5.x-2/Asset Store-5.x-2/Fictional Studio/Models/Fictional Room 1.2.3.unitypackage'})
        self.assertEqual((title,publisher),('Fictional Room','Fictional Studio'))
        self.assertEqual(package_hint({'name':'Unknown 1.2.3.unitypackage'}),('Unknown',''))
        self.assertEqual(normalized('Some-Studio'),'somestudio')

    def test_system_proxy_uses_only_local_os_settings_and_validated_https_targets(self):
        with patch('vault_rag.unity_asset_store.sys.platform','darwin'),patch('urllib.request.getproxies',side_effect=AssertionError('Environment proxy must not be read')):
            with patch('urllib.request.getproxies_macosx_sysconf',return_value={'https':'http://127.0.0.1:7897'}):
                self.assertEqual(_system_https_proxy(),('127.0.0.1',7897))
            with patch('urllib.request.getproxies_macosx_sysconf',return_value={}):self.assertIsNone(_system_https_proxy())
            for value in ('http://user:secret@127.0.0.1:7897','http://192.168.0.1:7897','http://proxy.invalid:7897',
                          'https://127.0.0.1:7897','http://127.0.0.1:7897/path','http://127.0.0.1:7897?query=1'):
                with self.subTest(proxy=value),patch('urllib.request.getproxies_macosx_sysconf',return_value={'https':value}),self.assertRaises(OfficialSourceError):_system_https_proxy()
        response=Mock(status=200);response.getheader.side_effect=lambda key,default=None:{'Content-Type':'text/html','Content-Encoding':'identity'}.get(key,default)
        response.read.return_value=b'<html>Public page</html>'
        connection=Mock();connection.getresponse.return_value=response
        with patch('vault_rag.unity_asset_store._system_https_proxy',return_value=('127.0.0.1',7897)),\
             patch('vault_rag.unity_asset_store.public_target',side_effect=AssertionError('Proxy must resolve the fixed tunnel host')),\
             patch('vault_rag.unity_asset_store.http.client.HTTPSConnection',return_value=connection) as create:
            self.assertEqual(UnityOfficialSource._fetch(URL),b'<html>Public page</html>')
            connection.set_tunnel.assert_called_once_with('assetstore.unity.com',443)
            args,kwargs=create.call_args;self.assertEqual(args,('127.0.0.1',7897))
            self.assertTrue(kwargs['context'].check_hostname);self.assertEqual(kwargs['context'].verify_mode,ssl.CERT_REQUIRED)
            headers=connection.request.call_args.kwargs['headers']
            self.assertFalse(any(key.lower() in {'cookie','authorization','proxy-authorization'} for key in headers))
            response.status=302;response.getheader.side_effect=lambda key,default=None:'https://127.0.0.1/private' if key=='Location' else default
            create.reset_mock()
            with self.assertRaises(OfficialSourceError):UnityOfficialSource._fetch(URL)
            self.assertEqual(create.call_count,1,'Redirect must be rejected before connecting to another host')
        response.status=200;response.getheader.side_effect=lambda key,default=None:{'Content-Type':'text/html','Content-Encoding':'identity'}.get(key,default)
        with patch('vault_rag.unity_asset_store._system_https_proxy',return_value=None),\
             patch('vault_rag.unity_asset_store.public_target',return_value=('assetstore.unity.com','1.1.1.1','/public','')) as target,\
             patch('vault_rag.unity_asset_store.PinnedHTTPSConnection',return_value=connection) as direct:
            UnityOfficialSource._fetch(URL);target.assert_called_once_with(URL);direct.assert_called_once_with('assetstore.unity.com','1.1.1.1')

    def test_public_hydration_facts_search_cards_and_numeric_aliases(self):
        alias='https://assetstore.unity.com/packages/package/123456'
        entities={
            'Product':{'123456':{'id':'123456','name':'Fictional Room','description':'<p>A real modular fictional room for games.</p>',
                'publisher':{'type':'id','id':['ProductPublisher','1']},'category':{'type':'id','id':['Category','2']},
                'popularTags':[{'type':'id','id':['ProductTag','3']}],'currentVersion':{'type':'id','id':['ProductVersion','4']},
                'supportedUnityVersions':['2022.3'],'srps':[{'version':'2022.3.1f1','types':['standard','lightweight']}],
                'compatibilityInfo':'<p>Import the supplied render pipeline materials.</p>'}},
            'ProductPublisher':{'1':{'name':'Fictional Studio'}},'Category':{'2':{'name':'Environments'}},
            'ProductTag':{'3':{'name':'furniture'}},'ProductVersion':{'4':{'name':'2.4'}}}
        def content():
            return page(category=[],keywords=[],description='Elevate your workflow with this fictional product.')+\
                '<script>document.addEventListener("DOMContentLoaded",function(){component.ReactDOMrender('+json.dumps({'data':{'ENTITY':entities}})+',document.body);});</script>'
        value=parse_product(content(),alias)
        self.assertEqual(value['url'],URL);self.assertEqual(value['product_id'],'unity.assetstore:123456')
        self.assertEqual(value['source_excerpt'],'A real modular fictional room for games.')
        self.assertEqual(value['categories'],['Environments']);self.assertEqual(value['keywords'],['furniture'])
        self.assertEqual(value['latest_version'],'2.4')
        self.assertEqual(value['compatibility']['unity_versions'],['2022.3'])
        self.assertEqual(value['compatibility']['render_pipelines'][0]['pipelines'],['standard','lightweight'])
        entities['Product']['123456']['description']=''
        self.assertEqual(parse_product(content(),alias)['source_excerpt'],'','A missing real description must not fall back to the SEO template')
        entities['ProductPublisher']['1']['name']='Different Studio'
        with self.assertRaises(OfficialSourceError):parse_product(content(),alias)
        self.assertEqual(parse_product(page(description='Elevate your workflow with this product.'),URL)['source_excerpt'],'')
        navigation=''.join('<a href="/packages/tools/unrelated-'+str(index)+'">Navigation</a>' for index in range(1,21))
        search=navigation+'<h1 data-test="search-page-title">Search</h1><article data-test="search-results-product-card-123456">'+\
            '<a data-test="product-card-name" href="/packages/package/123456">Fictional Room</a></article>'
        fetch=Mock(return_value=search.encode());source=UnityOfficialSource(fetch=fetch)
        self.assertEqual(source.search('Fictional Room','Fictional Studio'),[alias])
        fetch.assert_called_once_with('https://assetstore.unity.com/en-US/search?q=Fictional%20Room')
        with self.assertRaises(OfficialSourceError):UnityOfficialSource(fetch=lambda url:navigation.encode()).search('Room','Studio')

    def test_search_keeps_all_exact_titles_and_caches_duplicate_failed_hint(self):
        def card(identity,title):
            return '<article data-test="search-results-product-card-'+identity+'"><a data-test="product-card-name" href="/packages/package/'+identity+'"><span>'+title+'</span></a></article>'
        html='<h1 data-test="search-page-title">Search</h1>'+card('1','Sponsored Room Pack')+card('2','Fictional Room')+\
            card('3','Fictional Room Deluxe')+card('4','Fictional Room')
        source=UnityOfficialSource(fetch=lambda url:html.encode())
        self.assertEqual(source.search('Fictional Room','Studio A'),[
            'https://assetstore.unity.com/packages/package/2','https://assetstore.unity.com/packages/package/4'])
        library=Mock();library.remote=Mock();source=Mock();source.search.return_value=[]
        enrichment=AssetEnrichment(library,source=source);items=[
            {'id':'candidate:one','files':[{'path':'Packages/Asset Store-5.x/Fictional Studio/Fictional Room.unitypackage'}]},
            {'id':'candidate:two','files':[{'path':'Copies/Asset Store-5.x/Fictional Studio/Fictional Room.unitypackage'}]}]
        job={'state':'running','total':2,'succeeded':0,'needs_review':0,'failed':0,'results':[]}
        with patch.object(enrichment,'_save'),patch.object(enrichment,'_review'),patch.object(enrichment.stopped,'wait',return_value=False):
            enrichment._run('/synthetic',items,job,'local',None)
        source.search.assert_called_once_with('Fictional Room','Fictional Studio');source.product.assert_not_called()
        self.assertEqual(job['needs_review'],2);self.assertEqual(job['state'],'completed')
        self.assertTrue(all(result['reason']=='ambiguous_or_unavailable_product' for result in job['results']))

    def test_crash_resume_preserves_completed_reviews_but_retries_access_blocks_and_failures(self):
        class InlineThread:
            def __init__(self,*,target,args,**kwargs):self.target=target;self.args=args
            def start(self):self.target(*self.args)
            def is_alive(self):return False
        outcomes=[('done','succeeded',''),('review','needs_review','ambiguous_or_unavailable_product'),
                  ('browser','needs_review','browser_origin_permission'),('access','needs_review','official_source_access_required'),
                  ('rate','needs_review','official_source_rate_limited'),('network','needs_review','official_source_unavailable'),
                  ('failed','failed','official_collection_failed')]
        for state in ('interrupted','running','completed','paused'):
            with self.subTest(state=state):
                library=Mock();library.remote=Mock();source=Mock();source.search.return_value=[]
                library.listing.return_value={'items':[{'id':key,'files':[{'path':'Asset Store-5.x/Fictional Studio/'+key+'.unitypackage'}]} for key,_,_ in outcomes if key!='done'],'next_cursor':''}
                enrichment=AssetEnrichment(library,source=source);saved=[]
                old={'job_id':'existing','state':state,'results':[{'id':key,'state':status,'reason':reason} for key,status,reason in outcomes]}
                with patch.object(enrichment,'status',return_value=old),patch.object(enrichment,'_save',side_effect=lambda root,job:saved.append(copy.deepcopy(job))),\
                     patch.object(enrichment,'_review'),patch.object(enrichment.stopped,'wait',return_value=False),\
                     patch('vault_rag.unity_asset_store.threading.Thread',InlineThread):
                    job=enrichment.start('/synthetic')
                recovering=state in {'interrupted','running'}
                self.assertEqual(saved[0]['total'],7);self.assertEqual(saved[0]['succeeded'],1)
                self.assertEqual(saved[0]['needs_review'],1 if recovering else 0)
                self.assertEqual(source.search.call_count,5 if recovering else 6)
                searched={call.args[0] for call in source.search.call_args_list}
                self.assertEqual('review' in searched,not recovering)
                self.assertTrue({'browser','access','rate','network','failed'}<=searched)
                self.assertEqual(job['job_id'],'existing');self.assertEqual(job['state'],'completed')
                self.assertEqual((job['succeeded'],job['needs_review'],job['failed']),(1,6,0))
                self.assertEqual(len({item['id'] for item in job['results']}),7)


if __name__=='__main__':unittest.main()
