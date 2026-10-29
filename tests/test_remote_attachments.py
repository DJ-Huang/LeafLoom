"""Offline synthetic-storage contracts; no user files, services or credentials."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import unquote
import xml.sax.saxutils
import xml.etree.ElementTree as ET

import httpx

from vault_rag.local_state import ConflictError, LocalConfig
from vault_rag.remote_attachments import RemoteAttachments
from vault_rag.remote_webdav import RemoteStorageError, WebDAVSource, validate_source
from vault_rag.remote_ignore import IGNORE_HEADER,IGNORE_NAME,MAX_IGNORE_BYTES,MAX_TOTAL_IGNORE_BYTES,RemoteIgnore,IgnoreRuleError


SOURCE='a'*32
SECRET='fixture-password-never-persist'


class FakeDAV:
    def __init__(self):
        self.files={};self.directories=set();self.calls=[];self.offline=False;self.redirect=False
        self.corrupt=False;self.after_put=None;self.bad_range=False
        self.interrupt_put=False
        self.failure_status=None

    def __call__(self,request):
        self.calls.append((request.method,str(request.url)))
        if self.offline:raise httpx.ConnectError('private diagnostic must not escape',request=request)
        if self.failure_status:return httpx.Response(self.failure_status)
        if self.redirect:return httpx.Response(302,headers={'location':'https://elsewhere.invalid/login'})
        assert request.headers.get('cookie') is None
        expected='Basic '+base64.b64encode(('leafloom:'+SECRET).encode()).decode()
        assert request.headers.get('authorization')==expected
        path=unquote(request.url.path).strip('/')
        if request.method=='PROPFIND':
            assert request.headers['depth']=='1'
            directories={'', *self.directories}
            for name in self.files:
                for parent in Path(name).parents:
                    if str(parent)!='.':directories.add(parent.as_posix())
            prefix=path+'/' if path else ''
            names=[(path,True)]
            names += [(name,True) for name in sorted(directories) if name!=path and name.startswith(prefix) and '/' not in name[len(prefix):]]
            names += [(name,False) for name in sorted(self.files) if name.startswith(prefix) and '/' not in name[len(prefix):]]
            items=[]
            for name,directory in names:
                href='/'+name+('/' if directory and name else '')
                size=0 if directory else len(self.files[name])
                kind='<collection/>' if directory else ''
                items.append('<response><href>'+xml.sax.saxutils.escape(href)+'</href><propstat><prop><resourcetype>'+kind+'</resourcetype><getcontentlength>'+str(size)+'</getcontentlength><getlastmodified>Wed, 21 Oct 2026 00:00:00 GMT</getlastmodified><getetag>"fixture"</getetag><getcontenttype>application/octet-stream</getcontenttype></prop><status>HTTP/1.1 200 OK</status></propstat></response>')
            return httpx.Response(207,content=('<multistatus xmlns="DAV:">'+''.join(items)+'</multistatus>').encode())
        if request.method=='MKCOL':
            if path in self.directories:return httpx.Response(405)
            self.directories.add(path);return httpx.Response(201)
        if request.method=='PUT':
            assert path not in self.files
            assert request.headers['if-none-match']=='*'
            self.files[path]=request.read()
            if self.interrupt_put:
                self.interrupt_put=False;self.files[path]=self.files[path][:3]
                raise httpx.ReadError('fixture interrupted after partial save',request=request)
            if self.after_put:self.after_put()
            return httpx.Response(201)
        if path in self.directories and request.method=='HEAD':return httpx.Response(200,headers={'content-length':'0'})
        if path not in self.files:return httpx.Response(404)
        data=self.files[path]
        headers={'content-length':str(len(data)),'etag':'"fixture"','last-modified':'Wed, 21 Oct 2026 00:00:00 GMT','content-type':'application/octet-stream'}
        if request.method=='HEAD':return httpx.Response(200,headers=headers)
        if request.method=='GET':
            if 'range' in request.headers:
                start,end=map(int,request.headers['range'].removeprefix('bytes=').split('-'))
                content=data[start:end+1];headers['content-length']=str(len(content))
                headers['content-range']=f'bytes {start}-{end}/{len(data)}'
                if self.bad_range:headers['content-range']='bytes 0-0/1'
                return httpx.Response(206,headers=headers,content=content)
            if self.corrupt:data=bytes([data[0]^1])+data[1:] if data else data
            return httpx.Response(200,headers=headers,content=data)
        raise AssertionError('Unexpected mutation '+request.method)


class RemoteAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name).resolve()
        self.root=self.home/'vault';self.root.mkdir()
        self.config=LocalConfig(self.home/'state');self.config.save({'root':str(self.root)})
        self.dav=FakeDAV();self.transport=httpx.MockTransport(self.dav)
        self.managers=[];self.manager=self.manager_for_config()
        self.manager.save(str(self.root),{'sources':[{'id':SOURCE,'name':'Fixture','type':'webdav','base_url':'http://127.0.0.1:10000/','remote_root':'','username':'leafloom','enabled':True,'allow_private_http':True,'upload_directory':'Incoming','secret_ref':'fixture-reference','connection_hint':'official-client'}],'default_source':SOURCE})
        self.manager.set_credentials(SOURCE,'stale-username',SECRET,revision='stable-revision')

    def manager_for_config(self):
        # Exercise workers deterministically; never create a socket/listener.
        with patch.object(RemoteAttachments,'_loop',return_value=None):manager=RemoteAttachments(self.config)
        manager.transports[SOURCE]=self.transport;self.managers.append(manager);return manager

    def tearDown(self):
        for manager in self.managers:manager.stop()
        self.temp.cleanup()

    def put(self,path,data=b'fixture-bytes'):
        target=self.root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);return target

    def test_scope_redirect_range_and_no_ambient_network_state(self):
        source=self.manager._source(SOURCE)
        for bad in ('http://public.invalid/','http://127.0.0.1/../secret','https://user:password@example.invalid/'):
            with self.assertRaises(ValueError):validate_source({**source,'base_url':bad})
        provider=self.manager._provider(SOURCE)
        self.dav.redirect=True
        with self.assertRaises(RemoteStorageError) as caught:provider.test()
        self.assertEqual(caught.exception.code,'redirect_refused')
        self.assertEqual(len(self.dav.calls),1)
        self.dav.redirect=False;self.dav.files['Incoming/a.bin']=b'0123456789'
        self.assertEqual(provider.read_range('Incoming/a.bin',2,5)[0],b'2345')
        self.dav.bad_range=True
        with self.assertRaises(RemoteStorageError):provider.read_range('Incoming/a.bin',2,5)

    def test_shared_vpn_http_addresses_require_opt_in_and_remain_bounded(self):
        source=self.manager._source(SOURCE)
        for host in ('100.64.0.1','100.127.255.254','[fd7a:115c:a1e0::1]'):
            with self.subTest(host=host):
                url='http://'+host+':8068/'
                self.assertEqual(validate_source({**source,'base_url':url})['base_url'],url)
                with self.assertRaises(ValueError):
                    validate_source({**source,'base_url':url,'allow_private_http':False})
        for host in ('100.63.255.255','100.128.0.1','8.8.8.8','0.0.0.0','224.0.0.1','[::]','[ff02::1]','nas.example.invalid'):
            with self.subTest(host=host),self.assertRaises(ValueError):
                validate_source({**source,'base_url':'http://'+host+':8068/'})

    def test_upload_pending_alias_restart_and_streamed_readback(self):
        self.dav.offline=True
        job=self.manager.queue_upload(str(self.root),SOURCE,'_attachments/new/asset.bin',b'hello-outbox')
        data,meta=self.manager.read_range(str(self.root),'_attachments/new/asset.bin',0,4)
        self.assertEqual(data,b'hello');self.assertEqual(meta['state'],'pending')
        self.manager.process_pending()
        self.assertEqual(self.manager.job(str(self.root),job['id'])['state'],'waiting_for_connection')
        self.manager.stop();self.dav.offline=False
        manager=self.manager_for_config();manager.set_credentials(SOURCE,'',SECRET,revision='stable-revision')
        with patch('vault_rag.remote_attachments.time.time',return_value=time.time()+3):manager.process_pending()
        done=manager.job(str(self.root),job['id'])
        self.assertEqual(done['state'],'completed',done);self.assertTrue(done['remote_saved'])
        asset=manager.stat(str(self.root),'_attachments/new/asset.bin')
        self.assertEqual(asset['path'],'_attachments/new/asset.bin');self.assertEqual(asset['name'],'asset.bin')
        self.assertEqual(manager.read_range(str(self.root),asset['path'],2,6)[0],b'llo-o')
        self.assertEqual(manager.status(str(self.root))['outbox']['used_bytes'],0)
        self.assertFalse(any(method=='DELETE' for method,_ in self.dav.calls))
        for file in self.root.rglob('*'):
            if file.is_file():self.assertNotIn(SECRET.encode(),file.read_bytes())

    def test_metadata_and_verified_cache_survive_offline_scan_and_clear_preserves_outbox(self):
        self.dav.files['Incoming/image.png']=b'image-data'
        self.assertTrue(self.manager.scan(str(self.root),SOURCE)['ok'])
        path='_attachments/_remote/'+SOURCE+'/Incoming/image.png'
        asset=self.manager.stat(str(self.root),path)
        self.manager.update_metadata(str(self.root),path,{'tags':['image','image'],'category':'art','description':'Useful fixture'},asset['metadata_revision'])
        cached=self.manager.materialize(str(self.root),path)
        self.assertEqual(cached.read_bytes(),b'image-data')
        self.dav.offline=True
        result=self.manager.scan(str(self.root),SOURCE)
        self.assertFalse(result['ok']);self.assertTrue(result['metadata_preserved'])
        self.assertEqual(self.manager.read_range(str(self.root),path,0,4)[0],b'image')
        self.assertEqual(self.manager.stat(str(self.root),path)['tags'],['image'])
        pending=self.manager.queue_upload(str(self.root),SOURCE,'_attachments/pending.bin',b'durable')
        self.manager.clear_cache(str(self.root))
        self.assertFalse(cached.exists())
        self.assertEqual(self.manager.read_range(str(self.root),'_attachments/pending.bin',0,6)[0],b'durable')
        self.assertEqual(self.manager.job(str(self.root),pending['id'])['state'],'queued')

    def test_per_vault_settings_and_used_source_removal_guard(self):
        self.dav.files['Incoming/x.bin']=b'x';self.manager.scan(str(self.root),SOURCE)
        with self.assertRaises(ConflictError):self.manager.save(str(self.root),{'sources':[],'default_source':'local'})
        second=self.home/'other';second.mkdir();self.config.save({'root':str(second)})
        self.assertEqual(self.manager.status(str(second))['sources'],[])
        self.config.save({'root':str(self.root)})
        self.assertEqual(self.manager.status(str(self.root))['sources'][0]['id'],SOURCE)

    def test_local_metadata_migration_preserves_tags_and_alias_then_releases_original(self):
        source=self.put('_attachments/photo.png',b'original-image')
        self.put('outside.png');self.put('_attachments/readme.md',b'# note')
        local=self.manager.update_metadata(str(self.root),'_attachments/photo.png',{'tags':['photo'],'description':'keep me','category':'art'})
        plan=self.manager.migration_plan(str(self.root),SOURCE)
        self.assertEqual([i['path'] for i in plan['items']],['_attachments/photo.png'])
        self.assertTrue(source.exists());self.assertFalse(any(m=='PUT' for m,_ in self.dav.calls))
        result=self.manager.migrate(str(self.root),plan['id'])
        self.assertEqual(result['state'],'completed',result);self.assertFalse(source.exists())
        asset=self.manager.stat(str(self.root),'_attachments/photo.png')
        self.assertEqual(asset['tags'],['photo']);self.assertEqual(asset['description'],'keep me')
        self.assertEqual(asset['path'],'_attachments/photo.png')
        self.assertEqual(self.manager.read_range(str(self.root),asset['path'],0,7)[0],b'original')
        self.assertEqual(list((self.root/'.vault-rag/remote-attachments/release').glob('*')),[])

    def test_migration_readback_failure_and_source_drift_keep_original(self):
        source=self.put('_attachments/photo.png',b'original-image')
        plan=self.manager.migration_plan(str(self.root),SOURCE)
        self.dav.corrupt=True
        result=self.manager.migrate(str(self.root),plan['id'])
        self.assertEqual(result['state'],'failed',result);self.assertEqual(source.read_bytes(),b'original-image')
        self.dav.corrupt=False
        plan=self.manager.migration_plan(str(self.root),SOURCE)
        self.dav.after_put=lambda:source.write_bytes(b'edited-during-upload')
        result=self.manager.migrate(str(self.root),plan['id'])
        self.assertEqual(result['state'],'conflict',result);self.assertEqual(source.read_bytes(),b'edited-during-upload')
        self.assertEqual(self.manager.stat(str(self.root),'_attachments/photo.png')['source'],'local')

    def test_owner_and_credential_revision_changes_block_queue(self):
        job=self.manager.queue_upload(str(self.root),SOURCE,'_attachments/x.bin',b'private',owner='mcp-fixture')
        self.manager.process_pending()
        self.assertEqual(self.manager.job(str(self.root),job['id'],owner='mcp-fixture')['state'],'waiting_for_authorization')
        self.assertFalse(any(method=='PUT' for method,_ in self.dav.calls))
        self.manager.authorize_owner=lambda root,owner,revision:True
        self.manager.job(str(self.root),job['id'],action='resume',owner='mcp-fixture')
        self.manager.set_credentials(SOURCE,'leafloom',SECRET,revision='rotated-revision')
        self.manager.process_pending()
        self.assertEqual(self.manager.job(str(self.root),job['id'],owner='mcp-fixture')['state'],'waiting_for_authorization')

    def test_cancel_during_readback_never_releases_original(self):
        source=self.put('_attachments/photo.png',b'original-image')
        plan=self.manager.migration_plan(str(self.root),SOURCE)
        self.dav.after_put=lambda:self.manager.job(str(self.root),plan['id'],action='cancel')
        result=self.manager.migrate(str(self.root),plan['id'])
        self.assertEqual(result['state'],'cancelled',result);self.assertTrue(source.exists())

    def test_range_cache_is_bounded_partial_and_available_offline(self):
        settings=self.manager._settings(str(self.root));settings['cache_max_bytes']=8
        self.manager.save(str(self.root),settings)
        self.dav.files['Incoming/large.bin']=b'0123456789abcdef'
        self.manager.scan(str(self.root),SOURCE)
        path='_attachments/_remote/'+SOURCE+'/Incoming/large.bin'
        self.assertEqual(self.manager.read_range(str(self.root),path,2,5)[0],b'2345')
        self.assertEqual(self.manager.stat(str(self.root),path)['cache_state'],'partial')
        self.dav.offline=True;self.manager.cache_ttl=0
        self.assertEqual(self.manager.read_range(str(self.root),path,3,4)[0],b'34')
        self.assertEqual(self.manager.read_range(str(self.root),path,100,110)[0],b'')
        self.dav.offline=False
        self.assertEqual(self.manager.test(str(self.root),SOURCE)['state'],'ready')
        self.assertEqual(self.manager.read_range(str(self.root),path,6,13)[0],b'6789abcd')
        self.assertLessEqual(self.manager.status(str(self.root))['cache']['used_bytes'],8)
        self.manager.clear_cache(str(self.root))
        self.assertEqual(self.manager.stat(str(self.root),path)['cache_state'],'none')

    def test_confirmed_migration_resumes_after_restart_but_plan_does_not(self):
        source=self.put('_attachments/photo.png',b'original-image')
        plan=self.manager.migration_plan(str(self.root),SOURCE)
        self.manager.process_pending()
        self.assertTrue(source.exists());self.assertFalse(any(m=='PUT' for m,_ in self.dav.calls))
        self.dav.offline=True
        failed=self.manager.migrate(str(self.root),plan['id'])
        self.assertEqual(failed['state'],'waiting_for_connection');self.assertTrue(failed['confirmed'])
        self.manager.stop();self.dav.offline=False
        manager=self.manager_for_config();manager.set_credentials(SOURCE,'',SECRET,revision='stable-revision')
        with patch('vault_rag.remote_attachments.time.time',return_value=time.time()+3):manager.process_pending()
        self.assertEqual(manager.job(str(self.root),plan['id'])['state'],'completed')
        self.assertFalse(source.exists())

    def test_idempotent_queue_and_partial_put_retry_keep_same_logical_asset(self):
        job=self.manager.queue_upload(str(self.root),SOURCE,'_attachments/first.bin',b'complete-body',idempotency_key='operation-1',fingerprint='same-intent')
        replay=self.manager.queue_upload(str(self.root),SOURCE,'_attachments/different-random-path.bin','/must/not/be/read',idempotency_key='operation-1',fingerprint='same-intent')
        self.assertEqual(replay['id'],job['id'])
        with self.assertRaises(ConflictError):
            self.manager.queue_upload(str(self.root),SOURCE,'_attachments/other.bin',b'different',idempotency_key='operation-1',fingerprint='changed-intent')
        self.dav.interrupt_put=True;self.manager.process_pending()
        self.assertEqual(self.manager.job(str(self.root),job['id'])['state'],'waiting_for_connection')
        with patch('vault_rag.remote_attachments.time.time',return_value=time.time()+3):self.manager.process_pending()
        done=self.manager.job(str(self.root),job['id'])
        self.assertEqual(done['state'],'completed',done)
        self.assertEqual(len(done['remote_orphans']),1)
        self.assertEqual(self.dav.files[done['remote_orphans'][0]],b'com')
        self.assertEqual(self.manager.stat(str(self.root),'_attachments/first.bin')['asset_id'],job['asset_id'])

    def test_auth_rejection_pauses_same_revision_across_restart_until_explicit_action(self):
        job=self.manager.queue_upload(str(self.root),SOURCE,'_attachments/auth.bin',b'durable-auth-test')
        self.dav.failure_status=401;self.manager.process_pending()
        self.assertEqual(self.manager.job(str(self.root),job['id'])['state'],'waiting_for_auth')
        count=len(self.dav.calls)
        for _ in range(3):self.manager.process_pending();self.manager.poll_connections()
        self.assertEqual(len(self.dav.calls),count)
        self.manager.stop();manager=self.manager_for_config()
        manager.set_credentials(SOURCE,'',SECRET,revision='stable-revision')
        manager.poll_connections();manager.process_pending()
        connection=manager.status(str(self.root))['sources'][0]['connection']
        self.assertTrue(connection['retry_paused']);self.assertIsNone(connection['next_retry_at'])
        self.assertEqual(len(self.dav.calls),count)
        self.assertEqual(manager.read_range(str(self.root),'_attachments/auth.bin',0,6)[0],b'durable')
        self.dav.failure_status=None
        self.assertEqual(manager.test(str(self.root),SOURCE)['state'],'ready')
        manager.process_pending();self.assertEqual(manager.job(str(self.root),job['id'])['state'],'completed')
        second=manager.queue_upload(str(self.root),SOURCE,'_attachments/forbidden.bin',b'keep-me')
        self.dav.failure_status=403;manager.process_pending()
        self.assertTrue(manager.status(str(self.root))['sources'][0]['connection']['retry_paused'])
        self.dav.failure_status=None
        manager.job(str(self.root),second['id'],action='resume');manager.process_pending()
        self.assertEqual(manager.job(str(self.root),second['id'])['state'],'completed')
        self.assertFalse(any(method=='DELETE' for method,_ in self.dav.calls))

    def test_network_and_gateway_backoff_persist_then_health_restores_same_job(self):
        clock=[1000.0]
        with patch('vault_rag.remote_attachments.time.time',side_effect=lambda:clock[0]):
            job=self.manager.queue_upload(str(self.root),SOURCE,'_attachments/retry.bin',b'durable-retry-test')
            self.dav.failure_status=503;self.manager.process_pending()
            connection=self.manager.status(str(self.root))['sources'][0]['connection']
            self.assertEqual((connection['state'],connection['retry_attempts'],connection['next_retry_at']),('unreachable',1,1002.0))
            count=len(self.dav.calls);self.manager.process_pending();self.manager.poll_connections()
            self.assertEqual(len(self.dav.calls),count)
            clock[0]=1002.0;self.dav.offline=True;self.manager.poll_connections()
            connection=self.manager.status(str(self.root))['sources'][0]['connection']
            self.assertEqual((connection['retry_attempts'],connection['next_retry_at']),(2,1006.0))
            self.manager.stop();manager=self.manager_for_config()
            manager.set_credentials(SOURCE,'',SECRET,revision='stable-revision')
            count=len(self.dav.calls);manager.poll_connections();manager.process_pending()
            self.assertEqual(len(self.dav.calls),count)
            clock[0]=1006.0;self.dav.offline=False;self.dav.failure_status=None
            manager.poll_connections();manager.process_pending()
            done=manager.job(str(self.root),job['id'])
            self.assertEqual((done['id'],done['state']),(job['id'],'completed'))
            count=len(self.dav.calls);clock[0]=1065.0;manager.poll_connections()
            self.assertEqual(len(self.dav.calls),count)
            clock[0]=1066.0;manager.poll_connections()
            self.assertEqual(self.dav.calls[count:],[('PROPFIND','http://127.0.0.1:10000/')])
        for status in (502,503,504):
            with self.subTest(status=status):
                self.dav.failure_status=status
                provider=WebDAVSource(self.manager._source(SOURCE),('leafloom',SECRET),transport=self.transport)
                with self.assertRaises(RemoteStorageError) as caught:provider.test()
                self.assertEqual(caught.exception.state,'unreachable')

    def test_health_skips_scanning_disabled_missing_credentials_and_old_context(self):
        self.manager.poll_connections();count=len(self.dav.calls)
        old=self.manager._provider(SOURCE)
        with patch('vault_rag.remote_attachments.time.time',return_value=time.time()+61):
            self.manager.connections[SOURCE]['state']='scanning';self.manager.poll_connections()
            self.assertEqual(len(self.dav.calls),count)
            self.manager.connections[SOURCE]['state']='ready';self.manager.replace_credentials([]);self.manager.poll_connections()
            self.assertEqual(len(self.dav.calls),count)
            self.manager.set_credentials(SOURCE,'',SECRET,revision='stable-revision')
            settings=self.manager._settings(str(self.root));settings['sources'][0]['enabled']=False;settings['default_source']='local'
            self.manager.save(str(self.root),settings);self.manager.poll_connections()
            self.manager._connection_ready(str(self.root),SOURCE,context=old.connection_context)
            self.assertEqual(len(self.dav.calls),count)
            settings=self.manager._settings(str(self.root));settings['sources'][0].update(enabled=True,base_url='http://127.0.0.1:10001/')
            self.manager.save(str(self.root),settings)
            with self.assertRaises(RemoteStorageError):old._failed('authentication_required','auth_required')
            self.manager.poll_connections()
            connection=self.manager.status(str(self.root))['sources'][0]['connection']
            self.assertFalse(connection['retry_paused']);self.assertEqual(connection['state'],'ready')
            self.assertEqual(self.dav.calls[count:],[('PROPFIND','http://127.0.0.1:10001/')])

    def test_late_health_error_does_not_poison_reconfigured_source(self):
        def late_reply(_provider):
            settings=self.manager._settings(str(self.root))
            settings['sources'][0]['base_url']='http://127.0.0.1:10001/'
            self.manager.save(str(self.root),settings)
            raise RemoteStorageError('redirect_refused')
        with patch.object(WebDAVSource,'test',late_reply):self.manager.poll_connections()
        connection=self.manager.status(str(self.root))['sources'][0]['connection']
        self.assertEqual(connection['state'],'unchecked')
        self.assertEqual(connection['next_retry_at'],0)
        self.manager.poll_connections()
        self.assertEqual(self.manager.status(str(self.root))['sources'][0]['connection']['state'],'ready')

    def test_release_crash_recovery_marks_asset_ready(self):
        source=self.put('_attachments/photo.png',b'original-image')
        plan=self.manager.migration_plan(str(self.root),SOURCE)
        with patch.object(self.manager,'_finish_release',side_effect=RuntimeError('fixture process stop')):
            failed=self.manager.migrate(str(self.root),plan['id'])
        self.assertEqual(failed['state'],'failed');self.assertFalse(source.exists())
        self.assertEqual(self.manager.stat(str(self.root),'_attachments/photo.png')['state'],'migration_pending')
        recovered=self.manager.migrate(str(self.root),plan['id'])
        self.assertEqual(recovered['state'],'completed',recovered)
        self.assertEqual(self.manager.stat(str(self.root),'_attachments/photo.png')['state'],'ready')

    def test_failed_staging_is_removed_and_local_identity_move_is_guarded(self):
        source=self.put('original.png',b'original')
        with patch('vault_rag.remote_attachments.os.fsync',side_effect=OSError('fixture full disk')):
            with self.assertRaises(OSError):self.manager.queue_upload(str(self.root),SOURCE,'_attachments/new.bin',source)
        self.assertEqual(self.manager.status(str(self.root))['outbox']['used_bytes'],0)
        asset=self.manager.update_metadata(str(self.root),'original.png',{'tags':['retained']})
        snapshot=self.manager.snapshot_local_metadata(str(self.root),['original.png'])
        target=self.root/'renamed.png';source.rename(target)
        self.manager.sync_local_paths(str(self.root),[{'source':'original.png','destination':'renamed.png','asset_id':snapshot['original.png']}])
        renamed=self.manager.stat(str(self.root),'renamed.png')
        self.assertEqual(renamed['asset_id'],asset['asset_id']);self.assertEqual(renamed['tags'],['retained'])

    def test_concurrent_save_uses_locked_revision_and_credentials_reject_nul(self):
        settings=self.manager._settings(str(self.root));barrier=threading.Barrier(2);results=[]
        def save():
            barrier.wait()
            try:self.manager.save(str(self.root),settings);results.append('saved')
            except ConflictError:results.append('conflict')
        threads=[threading.Thread(target=save) for _ in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(3)
        self.assertEqual(sorted(results),['conflict','saved'])
        with self.assertRaises(ValueError):self.manager.set_credentials(SOURCE,'leafloom','nul\x00password')
        with self.assertRaises(ValueError):self.manager.replace_credentials([{'source_id':SOURCE,'username':'leafloom','password':'nul\x00password','revision':'same'}])

    def test_scan_commits_first_directory_before_later_directory_disconnects(self):
        self.dav.files['first.bin']=b'first'
        self.dav.files['later/second.bin']=b'second'
        def disconnect_later(request):
            if request.method=='PROPFIND' and request.url.path=='/later/':
                self.assertEqual(self.manager.connections[SOURCE]['state'],'scanning')
                self.assertEqual(self.manager.connections[SOURCE]['scanned'],1)
                first='_attachments/_remote/'+SOURCE+'/first.bin'
                self.assertEqual(self.manager.stat(str(self.root),first)['size'],5)
                raise httpx.ConnectError('fixture directory unavailable',request=request)
            return self.dav(request)
        self.manager.transports[SOURCE]=httpx.MockTransport(disconnect_later)
        result=self.manager.scan(str(self.root),SOURCE)
        self.assertFalse(result['ok']);self.assertEqual(result['scanned'],1)
        self.assertTrue(result['metadata_preserved'])
        self.assertEqual(self.manager.stat(str(self.root),'_attachments/_remote/'+SOURCE+'/first.bin')['size'],5)
        self.assertEqual(self.manager.connections[SOURCE]['directories'],1)

    def test_migration_adopts_existing_scan_identity_before_release(self):
        source=self.put('_attachments/photo.png',b'complete-image')
        plan=self.manager.migration_plan(str(self.root),SOURCE)
        discovered=[]
        def discover_during_upload():
            path=next(iter(self.dav.files))
            with self.manager.lock,self.manager._db(str(self.root)) as db:
                discovered.append(self.manager._upsert(db,SOURCE,{'path':path,'size':len(self.dav.files[path]),'mtime':'Wed, 21 Oct 2026 00:00:00 GMT','etag':'"fixture"'}))
        self.dav.after_put=discover_during_upload
        result=self.manager.migrate(str(self.root),plan['id'])
        self.assertEqual(result['state'],'completed',result);self.assertFalse(source.exists())
        self.assertEqual(result['items'][0]['asset_id'],discovered[0])
        asset=self.manager.stat(str(self.root),'_attachments/photo.png')
        self.assertEqual(asset['asset_id'],discovered[0]);self.assertEqual(asset['state'],'ready')
        # A prior process may already have persisted the wrong planned UUID at
        # the releasing boundary. Resuming must adopt the durable asset row.
        with self.manager._db(str(self.root)) as db:
            saved=json.loads(db.execute('SELECT payload FROM jobs WHERE id=?',(plan['id'],)).fetchone()[0])
            saved['state']='waiting_for_connection';saved['items'][0]['state']='releasing';saved['items'][0]['asset_id']='b'*32
            db.execute("UPDATE assets SET state='migration_pending' WHERE id=?",(discovered[0],))
            self.manager._job_save(db,saved)
        recovered=self.manager.migrate(str(self.root),plan['id'])
        self.assertEqual(recovered['state'],'completed',recovered)
        self.assertEqual(recovered['items'][0]['asset_id'],discovered[0])
        self.assertEqual(self.manager.stat(str(self.root),'_attachments/photo.png')['state'],'ready')

    def test_scan_preserves_pending_versions_and_hides_unverified_job_objects(self):
        job=self.manager.queue_upload(str(self.root),SOURCE,'_attachments/pending.bin',b'complete-pending')
        self.dav.files[job['remote_path']]=b'com'
        with self.manager.lock,self.manager._db(str(self.root)) as db:
            migration_id=self.manager._upsert(db,SOURCE,{'path':'Incoming/mapped.bin','size':99,'etag':'verified-etag','mtime':'verified-time'},sha256='a'*64,state='migration_pending')
            value=self.manager._new_job(str(self.root),SOURCE,'local','migration')
            value.update(state='running',items=[{'remote_path':'Incoming/unregistered.bin','state':'planned'}])
            self.manager._job_save(db,value)
        self.dav.files['Incoming/mapped.bin']=b'partial'
        self.dav.files['Incoming/unregistered.bin']=b'partial'
        self.assertTrue(self.manager.scan(str(self.root),SOURCE)['ok'])
        pending=self.manager.stat(str(self.root),'_attachments/pending.bin')
        self.assertEqual(pending['state'],'pending');self.assertEqual(pending['size'],16)
        self.assertEqual(self.manager.materialize(str(self.root),'_attachments/pending.bin').read_bytes(),b'complete-pending')
        mapped=self.manager.stat(str(self.root),asset_id=migration_id)
        self.assertEqual(mapped['state'],'migration_pending');self.assertEqual(mapped['size'],99)
        self.assertEqual(mapped['etag'],'verified-etag');self.assertEqual(mapped['sha256'],'a'*64)
        with self.manager._db(str(self.root)) as db:
            self.assertIsNone(db.execute('SELECT id FROM assets WHERE source_id=? AND path=?',(SOURCE,'Incoming/unregistered.bin')).fetchone())

    def test_successful_scan_marks_confirmed_missing_preserves_identity_and_reappearance(self):
        job=self.manager.queue_upload(str(self.root),SOURCE,'_attachments/removed.bin',b'old-bytes')
        self.manager.process_pending();asset_id=job['asset_id']
        before=self.manager.update_metadata(str(self.root),'_attachments/removed.bin',{'tags':['kept'],'category':'art','description':'retained'})
        self.manager.read_range(str(self.root),asset_id=asset_id,start=0,end=2)
        cached=self.manager.materialize(str(self.root),asset_id=asset_id)
        pending=self.manager.queue_upload(str(self.root),SOURCE,'_attachments/pending-safe.bin',b'outbox-safe')
        local=self.put('_attachments/local-safe.bin',b'original-safe')
        del self.dav.files[job['remote_path']]
        result=self.manager.scan(str(self.root),SOURCE)
        self.assertTrue(result['ok']);self.assertEqual(result['missing'],1)
        item=self.manager.stat(str(self.root),'_attachments/removed.bin')
        self.assertEqual((item['asset_id'],item['state'],item['tags'],item['category'],item['description']),
                         (asset_id,'missing',['kept'],'art','retained'))
        self.assertEqual(item['sha256'],'');self.assertEqual(item['cache_state'],'none');self.assertFalse(cached.exists())
        self.assertEqual(item['content_generation'],before['content_generation']+1)
        count=len(self.dav.calls)
        for read in (lambda:self.manager.materialize(str(self.root),asset_id=asset_id),
                     lambda:self.manager.read_range(str(self.root),asset_id=asset_id,start=0,end=2)):
            with self.assertRaises(RemoteStorageError) as caught:read()
            self.assertEqual((caught.exception.code,caught.exception.state),('remote_asset_missing','missing'))
        self.assertEqual(len(self.dav.calls),count)
        self.assertEqual(self.manager.job(str(self.root),job['id'])['state'],'completed')
        self.assertEqual(self.manager.read_range(str(self.root),asset_id=pending['asset_id'],start=0,end=10)[0],b'outbox-safe')
        self.assertEqual(local.read_bytes(),b'original-safe')
        with self.manager._db(str(self.root)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM cache WHERE asset_id=?',(asset_id,)).fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM ranges WHERE asset_id=?',(asset_id,)).fetchone()[0],0)
        self.dav.files[job['remote_path']]=b'new-bytes'  # Deliberately same size/mtime/ETag.
        self.assertTrue(self.manager.scan(str(self.root),SOURCE)['ok'])
        restored=self.manager.stat(str(self.root),asset_id=asset_id)
        self.assertEqual((restored['state'],restored['tags'],restored['sha256']),('ready',['kept'],''))
        self.assertEqual(restored['metadata_revision'],before['metadata_revision'])
        self.assertEqual(restored['content_generation'],item['content_generation'])
        self.assertEqual(self.manager.materialize(str(self.root),asset_id=asset_id).read_bytes(),b'new-bytes')
        self.assertEqual(self.manager.stat(str(self.root),asset_id=asset_id)['sha256'],hashlib.sha256(b'new-bytes').hexdigest())
        connection=self.manager.status(str(self.root))['sources'][0]['connection']
        self.assertEqual(connection['scan_state'],'completed');self.assertEqual(connection['scan_id'],self.manager.scan_statuses[(str(self.root),SOURCE)]['scan_id'])
        self.assertFalse(any(method=='DELETE' for method,_ in self.dav.calls))

    def test_connection_failure_preserves_sanitized_reason_without_changing_legacy_code(self):
        for failure,reason in [(httpx.ConnectTimeout,'server_connect_timeout'),(httpx.ReadTimeout,'server_read_timeout'),
                               (httpx.ReadError,'server_connection_interrupted'),(httpx.ConnectError,'server_connect_failed'),
                               (httpx.PoolTimeout,'server_connection_busy')]:
            with self.subTest(reason=reason):
                def fail(request):raise failure('sensitive-fixture-diagnostic',request=request)
                self.manager.transports[SOURCE]=httpx.MockTransport(fail)
                result=self.manager.test(str(self.root),SOURCE)
                self.assertEqual(result['code'],'connection_unavailable')
                connection=self.manager.status(str(self.root))['sources'][0]['connection']
                self.assertEqual(connection['reason'],reason);self.assertEqual(connection['operation'],'PROPFIND')
                self.assertNotIn('sensitive-fixture-diagnostic',json.dumps(connection))
                with self.assertRaises(RemoteStorageError) as stopped:self.manager._check_connection(str(self.root),SOURCE)
                self.assertEqual(stopped.exception.reason,reason)

    def test_scan_retries_directory_timeouts_without_losing_existing_records(self):
        self.dav.files['Incoming/kept.bin']=b'kept'
        self.assertTrue(self.manager.scan(str(self.root),SOURCE)['ok'])
        path='_attachments/_remote/'+SOURCE+'/Incoming/kept.bin'
        attempts=[]
        def transient(request):
            if request.method=='PROPFIND' and request.url.path=='/Incoming/':
                attempts.append(1)
                if len(attempts)<3:raise httpx.ReadTimeout('fixture timeout',request=request)
            return self.dav(request)
        self.manager.transports[SOURCE]=httpx.MockTransport(transient)
        with patch('vault_rag.remote_webdav.time.sleep'):
            self.assertTrue(self.manager.scan(str(self.root),SOURCE)['ok'])
        self.assertEqual(len(attempts),3)
        self.assertEqual(self.manager.stat(str(self.root),path)['state'],'ready')

        del self.dav.files['Incoming/kept.bin']
        attempts.clear()
        def persistent(request):
            if request.method=='PROPFIND':
                attempts.append(1)
                raise httpx.ConnectTimeout('fixture timeout',request=request)
            return self.dav(request)
        self.manager.transports[SOURCE]=httpx.MockTransport(persistent)
        with patch('vault_rag.remote_webdav.time.sleep'):
            result=self.manager.scan(str(self.root),SOURCE)
        self.assertEqual(len(attempts),3)
        self.assertEqual((result['ok'],result['code']),(False,'connection_unavailable'))
        self.assertEqual(self.manager.stat(str(self.root),path)['state'],'ready')

    def test_scan_does_not_retry_auth_failure_or_skip_guard_on_retry(self):
        source=self.manager._source(SOURCE)
        attempts=[]
        def unauthorized(request):
            attempts.append(1)
            return httpx.Response(401)
        provider=WebDAVSource(source,('leafloom',SECRET),transport=httpx.MockTransport(unauthorized))
        with self.assertRaises(RemoteStorageError) as caught:provider.scan()
        self.assertEqual(caught.exception.code,'authentication_required')
        self.assertEqual(len(attempts),1)

        attempts.clear();cancelled=[]
        def timed_out(request):
            attempts.append(1)
            raise httpx.ReadTimeout('fixture timeout',request=request)
        def guard():
            if cancelled:raise InterruptedError('cancelled')
        provider=WebDAVSource(source,('leafloom',SECRET),transport=httpx.MockTransport(timed_out),guard=guard)
        with patch('vault_rag.remote_webdav.time.sleep',side_effect=lambda _:cancelled.append(True)):
            with self.assertRaises(InterruptedError):provider.scan()
        self.assertEqual(len(attempts),1)

    def test_partial_207_and_failed_head_never_reconcile_missing(self):
        self.dav.files.update({'Incoming/a.bin':b'aaa','Incoming/b.bin':b'bbb'})
        self.manager.scan(str(self.root),SOURCE)
        paths=['_attachments/_remote/'+SOURCE+'/Incoming/'+name+'.bin' for name in ('a','b')]
        caches=[self.manager.materialize(str(self.root),path) for path in paths]
        root='<response><href>/</href><propstat><prop><resourcetype><collection/></resourcetype></prop><status>HTTP/1.1 200 OK</status></propstat></response>'
        bad_child='<response><href>/hidden/</href><status>HTTP/1.1 {code} Failure</status></response>'
        missing_type='<response><href>/</href><propstat><prop><getcontentlength>0</getcontentlength></prop><status>HTTP/1.1 200 OK</status></propstat></response>'
        bad_file='<response><href>/unknown.bin</href><propstat><prop><resourcetype/></prop><status>HTTP/1.1 200 OK</status></propstat></response>'
        for body in ('',root+bad_child.format(code=403),root+bad_child.format(code=500),missing_type,root+bad_file):
            with self.subTest(body=body):
                self.manager._reset_connection(str(self.root),SOURCE)
                def incomplete(request):
                    if request.method=='PROPFIND':return httpx.Response(207,content=('<multistatus xmlns="DAV:">'+body+'</multistatus>').encode())
                    return self.dav(request)
                self.manager.transports[SOURCE]=httpx.MockTransport(incomplete)
                self.assertFalse(self.manager.scan(str(self.root),SOURCE)['ok'])
                self.assertEqual([self.manager.stat(str(self.root),path)['state'] for path in paths],['ready','ready'])
                self.assertTrue(all(path.exists() for path in caches))
        for failing_status in (401,503):
            with self.subTest(head_status=failing_status):
                self.manager._reset_connection(str(self.root),SOURCE)
                def head_failure(request):
                    if request.method=='PROPFIND':return httpx.Response(207,content=('<multistatus xmlns="DAV:">'+root+'</multistatus>').encode())
                    return httpx.Response(404 if request.url.path.endswith('a.bin') else failing_status)
                self.manager.transports[SOURCE]=httpx.MockTransport(head_failure)
                self.assertFalse(self.manager.scan(str(self.root),SOURCE)['ok'])
                self.assertEqual([self.manager.stat(str(self.root),path)['state'] for path in paths],['ready','ready'])
                self.assertTrue(all(path.exists() for path in caches))
        self.manager._reset_connection(str(self.root),SOURCE)
        def silently_hidden(request):
            if request.method=='PROPFIND':return httpx.Response(207,content=('<multistatus xmlns="DAV:">'+root+'</multistatus>').encode())
            return self.dav(request)
        self.manager.transports[SOURCE]=httpx.MockTransport(silently_hidden)
        result=self.manager.scan(str(self.root),SOURCE)
        self.assertTrue(result['ok']);self.assertEqual(result['missing'],0)
        self.assertEqual([self.manager.stat(str(self.root),path)['state'] for path in paths],['ready','ready'])

    def test_scan_concurrent_metadata_job_and_scan_are_protected(self):
        self.dav.files.update({'Incoming/'+name+'.bin':b'bytes' for name in ('changed','reserved','gone')})
        self.manager.scan(str(self.root),SOURCE)
        paths={name:'_attachments/_remote/'+SOURCE+'/Incoming/'+name+'.bin' for name in ('changed','reserved','gone')}
        self.dav.files.clear();entered=threading.Event();release=threading.Event();results=[];errors=[]
        def blocked(request):
            if request.method=='PROPFIND':entered.set();release.wait(3)
            return self.dav(request)
        self.manager.transports[SOURCE]=httpx.MockTransport(blocked)
        def run():
            try:results.append(self.manager.scan(str(self.root),SOURCE))
            except Exception as error:errors.append(type(error).__name__)
        worker=threading.Thread(target=run);worker.start()
        try:
            self.assertTrue(entered.wait(1))
            duplicate=self.manager.scan(str(self.root),SOURCE)
            self.assertEqual(duplicate['code'],'scan_already_running')
            self.assertEqual(self.manager.start_scan(str(self.root),SOURCE)['scan_id'],duplicate['scan_id'])
            self.manager.update_metadata(str(self.root),paths['changed'],{'tags':['during-scan']})
            with self.manager.lock,self.manager._db(str(self.root)) as db:
                job=self.manager._new_job(str(self.root),SOURCE,'local','migration')
                job.update(state='running',items=[{'remote_path':'Incoming/reserved.bin','state':'planned'}])
                self.manager._job_save(db,job)
            pending=self.manager.queue_upload(str(self.root),SOURCE,'_attachments/during-scan.bin',b'pending')
        finally:release.set();worker.join(3)
        self.assertEqual(errors,[]);self.assertEqual(results[0]['missing'],1)
        self.assertEqual(self.manager.stat(str(self.root),paths['changed'])['state'],'ready')
        self.assertEqual(self.manager.stat(str(self.root),paths['reserved'])['state'],'ready')
        self.assertEqual(self.manager.stat(str(self.root),paths['gone'])['state'],'missing')
        self.assertEqual(self.manager.stat(str(self.root),asset_id=pending['asset_id'])['state'],'pending')

    def test_credential_change_cancels_scan_and_health_cannot_report_scan_completed(self):
        self.dav.files['Incoming/kept.bin']=b'kept';self.manager.scan(str(self.root),SOURCE)
        path='_attachments/_remote/'+SOURCE+'/Incoming/kept.bin';self.dav.files.clear()
        entered=threading.Event();release=threading.Event();errors=[]
        def blocked(request):
            if request.method=='PROPFIND':entered.set();release.wait(3)
            return self.dav(request)
        self.manager.transports[SOURCE]=httpx.MockTransport(blocked)
        def run():
            try:self.manager.scan(str(self.root),SOURCE)
            except Exception as error:errors.append(type(error).__name__)
        worker=threading.Thread(target=run);worker.start()
        try:
            self.assertTrue(entered.wait(1));self.manager.set_credentials(SOURCE,'',SECRET,revision='changed-view')
        finally:release.set();worker.join(3)
        self.assertEqual(errors,['PermissionError']);self.assertEqual(self.manager.stat(str(self.root),path)['state'],'ready')
        self.manager.poll_connections()
        connection=self.manager.status(str(self.root))['sources'][0]['connection']
        self.assertEqual(connection['state'],'ready');self.assertEqual(connection['scan_state'],'cancelled')

    def test_direct_scan_cannot_steal_reserved_background_scan_lifecycle(self):
        entered=threading.Event();release=threading.Event();original=self.manager.scan
        def delayed(*args,**kwargs):
            if kwargs.get('_scan_id'):entered.set();release.wait(3)
            return original(*args,**kwargs)
        with patch.object(self.manager,'scan',side_effect=delayed):
            started=self.manager.start_scan(str(self.root),SOURCE)
            thread=self.manager.scan_threads[(str(self.root),SOURCE)]
            try:
                self.assertTrue(entered.wait(1))
                duplicate=original(str(self.root),SOURCE)
                self.assertEqual(duplicate['code'],'scan_already_running')
                self.assertEqual(duplicate['scan_id'],started['scan_id'])
                self.assertEqual(self.manager.start_scan(str(self.root),SOURCE)['scan_id'],started['scan_id'])
                self.assertEqual(self.dav.calls,[])
            finally:release.set();thread.join(3)
        self.assertFalse(thread.is_alive())
        connection=self.manager.status(str(self.root))['sources'][0]['connection']
        self.assertEqual((connection['scan_id'],connection['scan_state']),(started['scan_id'],'completed'))

    def test_propfind_merges_successful_props_and_allows_optional_etag_404(self):
        self.dav.files['Incoming/a.bin']=b'aaa'
        def split_props(request):
            response=self.dav(request)
            if request.method!='PROPFIND':return response
            tree=ET.fromstring(response.content)
            for item in tree.findall('{DAV:}response'):
                first=item.find('{DAV:}propstat');props=first.find('{DAV:}prop')
                second=ET.SubElement(item,'{DAV:}propstat');second_props=ET.SubElement(second,'{DAV:}prop')
                for prop in list(props):
                    if prop.tag in {'{DAV:}getcontentlength','{DAV:}getlastmodified'}:props.remove(prop);second_props.append(prop)
                ET.SubElement(second,'{DAV:}status').text='HTTP/1.1 200 OK'
                etag=props.find('{DAV:}getetag');props.remove(etag)
                optional=ET.SubElement(item,'{DAV:}propstat');optional_props=ET.SubElement(optional,'{DAV:}prop')
                optional_props.append(etag);ET.SubElement(optional,'{DAV:}status').text='HTTP/1.1 404 Not Found'
            return httpx.Response(207,content=ET.tostring(tree))
        self.manager.transports[SOURCE]=httpx.MockTransport(split_props)
        result=self.manager.scan(str(self.root),SOURCE)
        self.assertTrue(result['ok']);self.assertEqual(result['scanned'],1)

    def test_inflight_download_cannot_publish_after_missing_and_same_version_reappearance(self):
        self.dav.files['Incoming/race.bin']=b'old-bytes'
        self.manager.scan(str(self.root),SOURCE)
        path='_attachments/_remote/'+SOURCE+'/Incoming/race.bin'
        before=self.manager.stat(str(self.root),path);entered=threading.Event();release=threading.Event();errors=[]
        original=WebDAVSource.download
        def blocked_download(provider,*args,**kwargs):
            result=original(provider,*args,**kwargs);entered.set();release.wait(3);return result
        def download():
            try:self.manager.materialize(str(self.root),path)
            except Exception as error:errors.append(type(error).__name__)
        with patch.object(WebDAVSource,'download',blocked_download):
            worker=threading.Thread(target=download);worker.start()
            try:
                self.assertTrue(entered.wait(1))
                del self.dav.files['Incoming/race.bin'];self.assertEqual(self.manager.scan(str(self.root),SOURCE)['missing'],1)
                self.dav.files['Incoming/race.bin']=b'new-bytes';self.manager.scan(str(self.root),SOURCE)
            finally:release.set();worker.join(3)
        self.assertEqual(errors,['ConflictError'])
        restored=self.manager.stat(str(self.root),path)
        self.assertEqual(restored['content_generation'],before['content_generation']+1)
        self.assertEqual(restored['cache_state'],'none');self.assertEqual(restored['sha256'],'')
        self.assertEqual(list(self.manager._state('cache').glob('*.partial')),[])
        self.assertEqual(self.manager.materialize(str(self.root),path).read_bytes(),b'new-bytes')

    def test_hierarchical_ignore_defaults_negation_and_control_files(self):
        self.dav.files.update({
            IGNORE_NAME:(IGNORE_HEADER+'\nblocked/\n!allowed.md\n').encode(),
            'note.md':b'note','page.html':b'<html>','tool.py':b'pass',
            'ordinary.txt':b'text','data.json':b'{}','image.svg':b'<svg/>','allowed.md':b'allowed',
            'blocked/leafloom.ignore':(IGNORE_HEADER+'\n!*.png\n!script.py\n').encode(),
            'blocked/image.png':b'png','blocked/script.py':b'pass','blocked/hidden.zip':b'zip',
            'blocked/deep/leafloom.ignore':(IGNORE_HEADER+'\n*.png\n!keep.html\n').encode(),
            'blocked/deep/image.png':b'png','blocked/deep/keep.html':b'<html>',
        })
        result=self.manager.scan(str(self.root),SOURCE);self.assertTrue(result['ok'])
        expected={'note.md':'excluded','page.html':'excluded','tool.py':'excluded','ordinary.txt':'ready',
                  'data.json':'ready','image.svg':'ready','allowed.md':'ready','blocked/image.png':'ready',
                  'blocked/script.py':'ready','blocked/hidden.zip':'excluded','blocked/deep/image.png':'excluded',
                  'blocked/deep/keep.html':'ready'}
        for path,state in expected.items():
            with self.subTest(path=path):
                self.assertEqual(self.manager.stat(str(self.root),'_attachments/_remote/'+SOURCE+'/'+path)['state'],state)
        with self.manager._db(str(self.root)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM assets WHERE name=?',(IGNORE_NAME,)).fetchone()[0],0)
        listed=self.manager.list(str(self.root),source_id=SOURCE)
        self.assertEqual(listed['total'],sum(state=='ready' for state in expected.values()))
        self.assertTrue(all(item['state']=='ready' for item in listed['items']))
        connection=self.manager.status(str(self.root))['sources'][0]['connection']
        self.assertEqual(connection['scan_excluded'],result['excluded'])
        self.assertFalse(any(method=='GET' and not url.endswith('/'+IGNORE_NAME) for method,url in self.dav.calls))

    def test_ignore_of_absent_old_asset_preserves_cache_reference_and_receipt(self):
        self.dav.files[IGNORE_NAME]=(IGNORE_HEADER+'\n!*.md\n').encode()
        job=self.manager.queue_upload(str(self.root),SOURCE,'_attachments/old.md',b'cached-old-note')
        self.manager.process_pending();self.manager.scan(str(self.root),SOURCE)
        old=self.manager.update_metadata(str(self.root),'_attachments/old.md',{'tags':['kept'],'description':'retained'})
        self.manager.read_range(str(self.root),asset_id=old['asset_id'],start=0,end=5)
        cached=self.manager.materialize(str(self.root),asset_id=old['asset_id'])
        with self.manager._db(str(self.root)) as db:
            counts=tuple(db.execute('SELECT (SELECT COUNT(*) FROM cache),(SELECT COUNT(*) FROM ranges)').fetchone())
        del self.dav.files[job['remote_path']];self.dav.files[IGNORE_NAME]=(IGNORE_HEADER+'\n*.md\n').encode()
        call_count=len(self.dav.calls);result=self.manager.scan(str(self.root),SOURCE)
        self.assertTrue(result['ok']);self.assertEqual(result['missing'],0)
        after=self.manager.stat(str(self.root),'_attachments/old.md')
        self.assertEqual((after['asset_id'],after['state'],after['tags'],after['content_generation']),
                         (old['asset_id'],'excluded',['kept'],old['content_generation']))
        self.assertEqual(after['sha256'],old['sha256']);self.assertTrue(cached.exists())
        self.assertFalse(any(method=='HEAD' and url.endswith('/'+job['remote_path']) for method,url in self.dav.calls[call_count:]))
        self.assertEqual(self.manager.read_range(str(self.root),'_attachments/old.md',0,14)[0],b'cached-old-note')
        self.assertEqual(self.manager.job(str(self.root),job['id'])['state'],'completed')
        with self.manager._db(str(self.root)) as db:
            self.assertEqual(tuple(db.execute('SELECT (SELECT COUNT(*) FROM cache),(SELECT COUNT(*) FROM ranges)').fetchone()),counts)
        self.dav.files[job['remote_path']]=b'cached-old-note';self.dav.files[IGNORE_NAME]=(IGNORE_HEADER+'\n!*.md\n').encode()
        self.assertTrue(self.manager.scan(str(self.root),SOURCE)['ok'])
        restored=self.manager.stat(str(self.root),'_attachments/old.md')
        self.assertEqual((restored['asset_id'],restored['state'],restored['tags']), (old['asset_id'],'ready',['kept']))
        self.assertEqual(restored['content_generation'],old['content_generation']);self.assertTrue(cached.exists())

    def test_ignore_errors_and_midscan_changes_do_not_partially_hide_existing_assets(self):
        self.dav.files.update({IGNORE_NAME:(IGNORE_HEADER+'\n!*.md\n').encode(),'old.md':b'old'})
        self.manager.scan(str(self.root),SOURCE)
        path='_attachments/_remote/'+SOURCE+'/old.md';before=self.manager.stat(str(self.root),path)
        cached=self.manager.materialize(str(self.root),path)
        self.dav.files[IGNORE_NAME]=(IGNORE_HEADER+'\n*.md\n').encode()
        cases=[(b'not-a-control-file','application/octet-stream',200),
               (b'\xff','application/octet-stream',200),
               ((IGNORE_HEADER+'\n\x00').encode(),'application/octet-stream',200),
               ((IGNORE_HEADER+'\n').encode(),'text/html',200),
               (b'<html>sign in</html>','application/octet-stream',200),
               (b'x'*(MAX_IGNORE_BYTES+1),'application/octet-stream',200),
               ((IGNORE_HEADER+'\n').encode(),'application/octet-stream',403)]
        for data,mime,status in cases:
            with self.subTest(mime=mime,status=status,size=len(data)):
                self.manager._reset_connection(str(self.root),SOURCE)
                self.dav.files['child/'+IGNORE_NAME]=data
                def failed_rule(request):
                    if request.method=='GET' and request.url.path=='/child/'+IGNORE_NAME:
                        return httpx.Response(status,headers={'content-length':str(len(data)),'content-type':mime,'etag':'"fixture"'},content=data)
                    return self.dav(request)
                self.manager.transports[SOURCE]=httpx.MockTransport(failed_rule)
                self.assertFalse(self.manager.scan(str(self.root),SOURCE)['ok'])
                current=self.manager.stat(str(self.root),path)
                self.assertEqual((current['asset_id'],current['state'],current['content_generation']),
                                 (before['asset_id'],'ready',before['content_generation']))
                self.assertTrue(cached.exists())
        del self.dav.files['child/'+IGNORE_NAME];self.manager._reset_connection(str(self.root),SOURCE)
        reads=[0]
        def changing_rule(request):
            if request.method=='GET' and request.url.path=='/'+IGNORE_NAME:
                reads[0]+=1
                if reads[0]==2:
                    data=(IGNORE_HEADER+'\n!*.md\n').encode()
                    return httpx.Response(200,headers={'content-length':str(len(data))},content=data)
            return self.dav(request)
        self.manager.transports[SOURCE]=httpx.MockTransport(changing_rule)
        result=self.manager.scan(str(self.root),SOURCE)
        self.assertFalse(result['ok']);self.assertEqual(result['code'],'ignore_rules_changed')
        self.assertEqual(self.manager.stat(str(self.root),path)['state'],'ready');self.assertTrue(cached.exists())

    def test_ignore_bounds_bom_and_missing_child_rule_inherit(self):
        rules=RemoteIgnore();rules.add('',('\ufeff'+IGNORE_HEADER+'\r\n*.md\r\n!keep.md\r\n').encode())
        self.assertTrue(rules.excluded('note.md'));self.assertFalse(rules.excluded('keep.md'))
        for data in ((IGNORE_HEADER+'\n'+'x'*2049).encode(),(IGNORE_HEADER+'\n'+'#\n'*2048).encode(),b'x'*(MAX_IGNORE_BYTES+1)):
            with self.assertRaises(IgnoreRuleError):RemoteIgnore().add('',data)
        budget=RemoteIgnore()
        payload=(IGNORE_HEADER+'\n'+('#'+'x'*1000+'\n')*60).encode()
        accepted=MAX_TOTAL_IGNORE_BYTES//len(payload)
        for index in range(accepted):budget.add(str(index),payload)
        with self.assertRaises(IgnoreRuleError):budget.add('over-budget',payload)
        self.dav.files.update({IGNORE_NAME:(IGNORE_HEADER+'\n*.png\n').encode(),
                               'child/'+IGNORE_NAME:(IGNORE_HEADER+'\n!*.png\n').encode(),'child/image.png':b'png'})
        def absent_child_rule(request):
            if request.method=='GET' and request.url.path=='/child/'+IGNORE_NAME:return httpx.Response(404)
            return self.dav(request)
        self.manager.transports[SOURCE]=httpx.MockTransport(absent_child_rule)
        result=self.manager.scan(str(self.root),SOURCE)
        self.assertTrue(result['ok'])
        self.assertEqual(self.manager.stat(str(self.root),'_attachments/_remote/'+SOURCE+'/child/image.png')['state'],'excluded')

    def test_local_asset_id_redirects_after_release_and_new_path_gets_new_identity(self):
        original=b'old-image'
        source=self.put('_attachments/photo.png',original)
        local=self.manager.update_metadata(str(self.root),'_attachments/photo.png',{'tags':['preserved'],'description':'same asset'})
        old_id=local['asset_id']
        self.assertEqual(self.manager.read_range(str(self.root),asset_id=old_id,start=0,end=8)[0],original)
        plan=self.manager.migration_plan(str(self.root),SOURCE)
        check=self.manager._check_job;observed=[]
        def observe_mapping(value,**kwargs):
            check(value,**kwargs)
            if value['kind']=='migration' and not observed and value['items'][0]['state']=='mapped' and source.exists():
                observed.append(self.manager.read_range(str(self.root),asset_id=old_id,start=0,end=8)[0])
                self.assertEqual(self.manager.stat(str(self.root),asset_id=old_id)['source'],'local')
        with patch.object(self.manager,'_check_job',side_effect=observe_mapping):
            completed=self.manager.migrate(str(self.root),plan['id'])
        self.assertEqual(completed['state'],'completed',completed);self.assertEqual(observed,[original])
        canonical=completed['items'][0]['asset_id']
        after=self.manager.stat(str(self.root),asset_id=old_id)
        self.assertEqual(after['asset_id'],canonical);self.assertEqual(after['tags'],['preserved'])
        self.assertEqual(after['description'],'same asset')
        self.assertEqual(self.manager.read_range(str(self.root),asset_id=old_id,start=0,end=8)[0],original)
        source.write_bytes(b'new-local-file')
        replacement=self.manager.stat(str(self.root),'_attachments/photo.png')
        self.assertEqual(replacement['source'],'local');self.assertNotIn(replacement['asset_id'],{old_id,canonical})
        self.assertEqual(self.manager.read_range(str(self.root),'_attachments/photo.png',0,13)[0],b'new-local-file')
        self.assertEqual(self.manager.stat(str(self.root),asset_id=old_id)['asset_id'],canonical)

    def test_legacy_redirect_backfill_requires_unique_released_journal_proof(self):
        source=self.put('_attachments/photo.png',b'image')
        local=self.manager.update_metadata(str(self.root),'_attachments/photo.png',{'tags':['legacy']})
        plan=self.manager.migration_plan(str(self.root),SOURCE)
        completed=self.manager.migrate(str(self.root),plan['id'])
        self.assertEqual(completed['state'],'completed',completed)
        canonical=completed['items'][0]['asset_id']
        def restore_legacy_row(db):
            db.execute('DELETE FROM asset_redirects WHERE old_id=?',(local['asset_id'],))
            db.execute("UPDATE assets SET path=?,state='ready' WHERE id=?",('_attachments/photo.png',local['asset_id']))
        with self.manager._db(str(self.root)) as db:restore_legacy_row(db)
        self.assertEqual(self.manager.backfill_asset_redirects(str(self.root))['redirected'],1)
        self.assertEqual(self.manager.stat(str(self.root),asset_id=local['asset_id'])['asset_id'],canonical)
        self.assertEqual(self.manager.backfill_asset_redirects(str(self.root))['redirected'],0)
        # Another valid released target for the same historic path makes the
        # previous identity ambiguous even though its alias points at one row.
        with self.manager._db(str(self.root)) as db:
            restore_legacy_row(db)
            prior=json.loads(db.execute('SELECT payload FROM jobs WHERE id=?',(plan['id'],)).fetchone()[0])
            other=self.manager._upsert(db,SOURCE,{'path':'Incoming/another.bin','size':5},sha256=prior['items'][0]['sha256'])
            duplicate=json.loads(json.dumps(prior));duplicate['id']='c'*32
            duplicate['items'][0].update(asset_id=other,remote_path='Incoming/another.bin')
            self.manager._job_save(db,duplicate)
        result=self.manager.backfill_asset_redirects(str(self.root))
        self.assertEqual(result['redirected'],0);self.assertEqual(result['skipped'],1)
        with self.manager._db(str(self.root)) as db:self.assertIsNone(db.execute('SELECT new_id FROM asset_redirects WHERE old_id=?',(local['asset_id'],)).fetchone())

    def test_metadata_query_does_not_wait_for_materialize_network(self):
        self.dav.files['Incoming/image.png']=b'image'
        self.manager.scan(str(self.root),SOURCE)
        path='_attachments/_remote/'+SOURCE+'/Incoming/image.png'
        entered=threading.Event();release=threading.Event();errors=[];results=[]
        def blocked_download(request):
            if request.method=='GET' and not request.headers.get('range'):
                entered.set();release.wait(3)
            return self.dav(request)
        self.manager.transports[SOURCE]=httpx.MockTransport(blocked_download)
        def download():
            try:self.manager.materialize(str(self.root),path)
            except Exception as error:errors.append(type(error).__name__)
        worker=threading.Thread(target=download);worker.start()
        try:
            self.assertTrue(entered.wait(1))
            query=threading.Thread(target=lambda:results.append(self.manager.stat(str(self.root),path)))
            query.start();query.join(.5)
            self.assertFalse(query.is_alive(),'Metadata query waited for download lock')
            self.assertEqual(results[0]['size'],5)
        finally:release.set();worker.join(3)
        self.assertEqual(errors,[])

    def test_propfind_missing_etag_preserves_verified_head_version(self):
        job=self.manager.queue_upload(str(self.root),SOURCE,'_attachments/known.bin',b'verified')
        self.manager.process_pending()
        before=self.manager.stat(str(self.root),asset_id=job['asset_id'])
        self.assertTrue(before['etag']);self.assertTrue(before['sha256'])
        def without_propfind_etag(request):
            response=self.dav(request)
            if request.method=='PROPFIND':
                return httpx.Response(207,content=response.content.replace(b'<getetag>"fixture"</getetag>',b''))
            return response
        self.manager.transports[SOURCE]=httpx.MockTransport(without_propfind_etag)
        self.dav.calls.clear()
        self.assertTrue(self.manager.scan(str(self.root),SOURCE)['ok'])
        after=self.manager.stat(str(self.root),asset_id=job['asset_id'])
        self.assertEqual(after['etag'],before['etag']);self.assertEqual(after['sha256'],before['sha256'])
        self.assertFalse(any(method=='GET' and 'LeafLoomCatalog/' not in url for method,url in self.dav.calls))

    def test_range_head_metadata_replaces_weak_row_before_cache_commit(self):
        self.dav.files['Incoming/new.bin']=b'new!'
        with self.manager._db(str(self.root)) as db:
            key=self.manager._upsert(db,SOURCE,{'path':'Incoming/new.bin','size':4,'mtime':'Tue, 20 Oct 2026 00:00:00 GMT'})
        before=self.manager.stat(str(self.root),asset_id=key)
        self.assertEqual(before['version_state'],'weak_metadata');self.assertEqual(before['sha256'],'')
        data,current=self.manager.read_range(str(self.root),asset_id=key,start=0,end=3)
        self.assertEqual(data,b'new!');self.assertEqual(current['etag'],'"fixture"')
        self.assertEqual(current['mtime'],'Wed, 21 Oct 2026 00:00:00 GMT')
        self.assertEqual(self.manager.stat(str(self.root),asset_id=key)['sha256'],'')
        with self.manager._db(str(self.root)) as db:
            cached=db.execute('SELECT etag,mtime FROM ranges WHERE asset_id=?',(key,)).fetchone()
            self.assertEqual(cached['etag'],current['etag']);self.assertEqual(cached['mtime'],current['mtime'])

    def test_materialize_adopts_head_version_and_hashes_actual_bytes(self):
        self.dav.files['Incoming/image.png']=b'image'
        with self.manager._db(str(self.root)) as db:
            key=self.manager._upsert(db,SOURCE,{'path':'Incoming/image.png','size':5,'mtime':'Tue, 20 Oct 2026 00:00:00 GMT'})
        self.assertEqual(self.manager.stat(str(self.root),asset_id=key)['sha256'],'')
        path=self.manager.materialize(str(self.root),asset_id=key)
        self.assertEqual(path.read_bytes(),b'image')
        current=self.manager.stat(str(self.root),asset_id=key)
        self.assertEqual(current['etag'],'"fixture"');self.assertEqual(current['mtime'],'Wed, 21 Oct 2026 00:00:00 GMT')
        self.assertEqual(current['sha256'],hashlib.sha256(b'image').hexdigest())
        with self.manager._db(str(self.root)) as db:
            cached=db.execute('SELECT etag,mtime FROM cache WHERE asset_id=?',(key,)).fetchone()
            self.assertEqual(cached['etag'],current['etag']);self.assertEqual(cached['mtime'],current['mtime'])


if __name__=='__main__':unittest.main()
