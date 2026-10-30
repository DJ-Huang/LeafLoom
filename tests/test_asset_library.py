"""Synthetic WebDAV product metadata: no real services, files or credentials."""
import hashlib
import copy
import json
from pathlib import Path,PurePosixPath
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock,patch
from urllib.parse import unquote,urlsplit
import xml.sax.saxutils

import httpx

from tests import test_remote_attachments as fixtures
from vault_rag.asset_library import AssetLibrary, BACKGROUND_PULL_INTERVAL
from vault_rag.local_state import LocalConfig,ConflictError
from vault_rag.remote_attachments import RemoteAttachments
from vault_rag.remote_webdav import RemoteStorageError,WebDAVSource
from vault_rag.unity_asset_store import AssetEnrichment


class LibraryDAV(fixtures.FakeDAV):
    def __init__(self):
        super().__init__();self.directories={'','Incoming'};self.bad_event_readback=False;self.request_lock=threading.RLock()

    def __call__(self,request):
        with self.request_lock:return self._handle(request)

    def _handle(self,request):
        path=unquote(request.url.path).strip('/')
        if request.method in {'MKCOL','PROPFIND'}:
            self.calls.append((request.method,str(request.url)))
            if self.offline:raise httpx.ConnectError('fixture offline',request=request)
            if self.failure_status:return httpx.Response(self.failure_status)
            assert request.headers.get('cookie') is None
            directories=set(self.directories)
            for name in self.files:
                directories.update(parent.as_posix() for parent in PurePosixPath(name).parents if parent.as_posix()!='.')
            if request.method=='MKCOL':
                if path in directories:return httpx.Response(405)
                parent=str(PurePosixPath(path).parent)
                if parent=='.':parent=''
                if parent not in directories:return httpx.Response(409)
                self.directories.add(path);return httpx.Response(201)
            if path not in directories:return httpx.Response(404)
            prefix=path+'/' if path else '';names=[(path,True)]
            names.extend((name,True) for name in sorted(directories) if name!=path and name.startswith(prefix) and '/' not in name[len(prefix):])
            names.extend((name,False) for name in sorted(self.files) if name.startswith(prefix) and '/' not in name[len(prefix):])
            entries=[]
            for name,directory in names:
                href='/'+name+('/' if directory and name else '')
                entries.append('<response><href>'+xml.sax.saxutils.escape(href)+'</href><propstat><prop><resourcetype>'+('<collection/>' if directory else '')+'</resourcetype><getcontentlength>'+str(0 if directory else len(self.files[name]))+'</getcontentlength><getlastmodified>Wed, 21 Oct 2026 00:00:00 GMT</getlastmodified><getetag>"fixture"</getetag><getcontenttype>application/octet-stream</getcontenttype></prop><status>HTTP/1.1 200 OK</status></propstat></response>')
            return httpx.Response(207,content=('<multistatus xmlns="DAV:">'+''.join(entries)+'</multistatus>').encode())
        if request.method=='PUT' and path in self.files:
            self.calls.append((request.method,str(request.url)));return httpx.Response(412)
        response=super().__call__(request)
        if self.bad_event_readback and request.method=='GET' and '/events/' in path and response.status_code==200:
            data=response.content
            return httpx.Response(200,headers=dict(response.headers),content=bytes([data[0]^1])+data[1:])
        return response


class AssetLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name).resolve()
        self.dav=LibraryDAV();self.transport=httpx.MockTransport(self.dav)
        self.remotes=[];self.libraries=[]
        self.config,self.remote,self.library=self.create_client('one','a'*32)
        self.root=str(self.config.root)

    def create_client(self,name,source_id):
        root=self.home/name;root.mkdir()
        config=LocalConfig(self.home/(name+'-state'));config.save({'root':str(root)})
        with patch.object(RemoteAttachments,'_loop',return_value=None):remote=RemoteAttachments(config)
        remote.save(str(root),{'sources':[{'id':source_id,'name':'Fixture','type':'webdav','base_url':'http://127.0.0.1:10000/',
                    'username':'leafloom','upload_directory':'Incoming','enabled':True,'allow_private_http':True}],'default_source':source_id})
        remote.set_credentials(source_id,'leafloom',fixtures.SECRET,revision='stable')
        remote.transports[source_id]=self.transport
        with patch.object(AssetLibrary,'_loop',return_value=None):library=AssetLibrary(remote)
        self.remotes.append(remote);self.libraries.append(library);return config,remote,library

    def tearDown(self):
        for library in self.libraries:library.stop()
        for remote in self.remotes:remote.stop()
        self.temp.cleanup()

    def scan(self,remote=None):
        remote=remote or self.remote;root=str(remote.config.root)
        source=remote._settings(root)['default_source']
        self.assertTrue(remote.scan(root,source)['ok'])

    def initialize(self,library=None,root=None):
        library=library or self.library;root=root or self.root
        self.assertEqual(library.initialize(root)['state'],'queued')
        result=library.sync(root)
        self.assertTrue(result['initialized'],result);self.assertEqual(result['pending'],0,result)
        return result

    def test_candidates_are_not_grouped_by_name_and_initial_identities_are_batched(self):
        self.dav.files.update({'Packages/Publisher_SGSR1.2.6_'+str(index)+'.unitypackage':b'package' for index in range(1187)})
        self.scan();before=dict(self.dav.files)
        discovered=self.library.listing(self.root,limit=500)
        self.assertEqual(discovered['total'],1187)
        self.assertTrue(all(item['kind']=='candidate' and item['product_id']=='' for item in discovered['items']))
        self.assertEqual(discovered['items'][0]['files'][0]['version'],'1.2.6')
        self.assertEqual(discovered['items'][0]['files'][0]['version_source'],'filename')
        count=len(self.dav.calls);self.library.initialize(self.root)
        self.assertEqual(len(self.dav.calls),count,'Initialization must queue, not upload every candidate synchronously')
        result=self.library.sync(self.root)
        self.assertEqual((result['initialized'],result['files'],result['pending']),(True,1187,0))
        events=[name for name in self.dav.files if '/events/' in name]
        self.assertEqual(len(events),24)
        self.assertTrue(all(json.loads(self.dav.files[name])['kind']=='file_batch' for name in events))
        self.assertTrue(all(self.dav.files[path]==data for path,data in before.items()))
        with patch.object(self.remote,'stat',side_effect=AssertionError('Must use a batch manifest read')):
            self.assertEqual(self.library.listing(self.root,limit=10)['total'],1187)
        self.assertFalse(any(method=='DELETE' for method,_ in self.dav.calls))

    def test_sync_preserves_safe_transport_reason_for_status_ui(self):
        error=RemoteStorageError('connection_unavailable','unreachable',reason='server_connect_timeout',operation='GET')
        with patch.object(self.library,'_provider',side_effect=error):result=self.library.sync(self.root)
        self.assertEqual(result['code'],'connection_unavailable')
        self.assertEqual(result['reason'],'server_connect_timeout');self.assertEqual(result['operation'],'GET')
        self.assertIn('checked_at',result)

    def test_retry_status_replaces_old_failure_before_full_sync_finishes(self):
        self.initialize()
        with self.library._read_db(self.root) as db:last_success=self.library._get(db,'sync')['last_synced_at']
        failure=RemoteStorageError('connection_unavailable','unreachable',reason='server_connect_timeout',operation='GET')
        with patch.object(self.library,'_provider',side_effect=failure):failed=self.library.sync(self.root)
        self.assertEqual(failed['last_synced_at'],last_success)
        connecting=threading.Event();continue_connect=threading.Event();syncing=threading.Event();continue_sync=threading.Event()
        original_bootstrap=self.library._bootstrap;original_pull=self.library._pull;results=[];errors=[]
        def bootstrap(*args):
            connecting.set()
            if not continue_connect.wait(5):raise AssertionError('test connection was not released')
            return original_bootstrap(*args)
        def pull(*args):
            syncing.set()
            if not continue_sync.wait(5):raise AssertionError('test sync was not released')
            return original_pull(*args)
        def retry():
            try:results.append(self.library.sync(self.root))
            except BaseException as error:errors.append(error)
        with patch.object(self.library,'_bootstrap',side_effect=bootstrap),patch.object(self.library,'_pull',side_effect=pull):
            thread=threading.Thread(target=retry);thread.start()
            try:
                self.assertTrue(connecting.wait(3));state=self.library.status(self.root)
                self.assertEqual((state['state'],state['phase'],state['retrying']),('syncing','connecting',True))
                self.assertNotIn('code',state);self.assertNotIn('reason',state);self.assertEqual(state['last_synced_at'],last_success)
                # A duplicate request observes the same in-flight attempt.
                self.assertEqual(self.library.sync(self.root)['sync_started_at'],state['sync_started_at'])
                continue_connect.set();self.assertTrue(syncing.wait(3));state=self.library.status(self.root)
                self.assertEqual((state['state'],state['phase']),('syncing','syncing'))
                self.assertNotIn('code',state)
                with self.library._read_db(self.root) as db:durable=self.library._get(db,'sync')
                self.assertEqual(durable['state'],'queued');self.assertNotIn('code',durable)
                self.assertEqual(durable['last_synced_at'],last_success)
                # Runtime activity must not survive as a fictitious running flag.
                with patch.object(AssetLibrary,'_loop',return_value=None):restarted=AssetLibrary(self.remote)
                self.libraries.append(restarted);self.assertEqual(restarted.status(self.root)['state'],'queued')
            finally:
                continue_connect.set();continue_sync.set();thread.join(5)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.assertEqual(results[0]['state'],'ready');self.assertNotIn('code',results[0]);self.assertIsNone(self.library.active_sync)
        self.assertGreaterEqual(results[0]['last_synced_at'],last_success)

    def test_retry_failure_reports_current_reason_and_retains_last_success(self):
        self.initialize()
        with self.library._read_db(self.root) as db:last_success=self.library._get(db,'sync')['last_synced_at']
        for failure in (RemoteStorageError('connection_unavailable','unreachable',reason='server_read_timeout',operation='PROPFIND'),
                        RemoteStorageError('authentication_required','auth_required')):
            with self.subTest(state=failure.state),patch.object(self.library,'_pull',side_effect=failure):
                state=self.library.sync(self.root)
                self.assertEqual((state['state'],state['code']),(failure.state,failure.code))
                self.assertEqual(state['last_synced_at'],last_success);self.assertIsNone(self.library.active_sync)
                self.assertNotIn('phase',state)

    def test_active_retry_is_not_reported_for_replaced_credentials(self):
        self.initialize();context=self.library._context(self.root)
        self.library.active_sync={'context':context,'phase':'connecting','retrying':True,'started_at':1}
        self.remote.set_credentials('a'*32,'leafloom',fixtures.SECRET,revision='replaced')
        self.assertEqual(self.library.status(self.root)['state'],'ready')
        self.assertNotIn('sync_started_at',self.library.status(self.root));self.library.active_sync=None

    def test_noop_sync_does_not_notify_or_interrupt_attachment_browsing(self):
        self.scan();self.initialize()
        notices=[];self.library.on_changed=notices.append
        self.library.sync(self.root)
        self.assertEqual(notices,[])
        self.library.update(self.root,'official',{'product_id':'123','official':{'title':'Fixture product'}})
        self.library.sync(self.root)
        self.assertEqual(notices,[self.root])
        self.library.sync(self.root)
        self.assertEqual(notices,[self.root])

    def test_local_snapshot_queries_and_batched_background_pulls(self):
        self.dav.files['Packages/Tool.unitypackage']=b'original package'
        self.scan();self.initialize()
        directory=self.library.settings(self.root)['metadata_directory']+'/events'
        self.dav.directories.update(directory+'/'+format(index,'02x') for index in range(256))
        with patch('vault_rag.asset_library.time.monotonic',return_value=100) as clock, \
                patch.object(self.library,'_pull',wraps=self.library._pull) as pull:
            self.library.sync(self.root)
            self.assertEqual(pull.call_count,1)
            for index in range(3):
                self.library.update(self.root,'official',{'product_id':str(100+index),'official':{'title':'Product '+str(index)}})
                result=self.library.sync(self.root,_background=True)
                self.assertEqual(result['pending'],0)
            self.assertEqual(pull.call_count,1,'A burst of edits must flush verified events without rescanning 256 shards per product')
            self.library.sync(self.root)
            self.assertEqual(pull.call_count,2,'Explicit synchronization must always pull the entire event history')
            clock.return_value=100+BACKGROUND_PULL_INTERVAL
            self.library.sync(self.root,_background=True)
            self.assertEqual(pull.call_count,3,'Background synchronization must still periodically discover concurrent changes')
            self.remote.set_credentials('a'*32,'leafloom',fixtures.SECRET,revision='replacement')
            self.library.sync(self.root,_background=True)
            self.assertEqual(pull.call_count,4,'A changed credential context must not reuse a previous pull checkpoint')
        self.dav.files['Packages/Another.unitypackage']=b'another original'
        self.scan()  # Leave a newer local manifest for the next projection.
        held=threading.Event();release=threading.Event();done=threading.Event();values={};errors=[]
        def hold_mutations():
            with self.library.lock,self.remote.lock:
                held.set();release.wait(5)
        def read_snapshots():
            try:
                values['status']=self.library.status(self.root)
                values['listing']=self.library.listing(self.root)
                values['detail']=self.library.detail(self.root,'100')
            except Exception as error:errors.append(error)
            finally:done.set()
        holder=threading.Thread(target=hold_mutations,daemon=True);holder.start()
        self.assertTrue(held.wait(1))
        reader=threading.Thread(target=read_snapshots,daemon=True);reader.start()
        try:self.assertTrue(done.wait(1),'Local reads must not queue behind library or attachment mutation locks')
        finally:release.set();holder.join(2);reader.join(2)
        self.assertEqual(errors,[])
        self.assertEqual(values['status']['files'],1)
        self.assertEqual(values['listing']['summary']['files'],1)
        self.assertEqual(values['detail']['official']['title'],'Product 0')
        self.assertEqual(self.library.listing(self.root)['summary']['files'],2,'The newer manifest must be projected after the writer is available')
        self.assertEqual(self.dav.files['Packages/Tool.unitypackage'],b'original package')
        self.assertEqual(self.dav.files['Packages/Another.unitypackage'],b'another original')

    def test_pull_batches_known_identities_and_guards_unverified_events(self):
        import sqlite3
        self.initialize();context=self.library._context(self.root)
        directory=context['metadata_directory']+'/events'
        with self.library._read_db(self.root) as db:library_id=self.library._get(db,'library_id')
        def event(index):
            identity=format(index,'032x')
            value={'schema':'leafloom.asset-library.event.v1','library_id':library_id,'event_id':identity,
                   'kind':'file_batch','entity':'files','parents':[],'payload':{'files':[]},'created_at':1}
            data=json.dumps(value,sort_keys=True,separators=(',',':')).encode();sha=hashlib.sha256(data).hexdigest()
            return value,data,{'path':directory+'/'+identity[:2]+'/'+identity+'-'+sha+'.json','size':len(data)}
        events=[event(index) for index in range(5000)]
        with self.library._db(self.root) as db:
            db.executemany('INSERT INTO events VALUES(?,?,?,?,?,?,?,1)',
                          [(value['event_id'],'file_batch','files','[]','{"files":[]}',data,hashlib.sha256(data).hexdigest())
                           for value,data,item in events])
        provider=Mock();provider.scan.return_value=[item for value,data,item in events]
        provider.read_bytes.side_effect=AssertionError('Known verified events must not be downloaded again')
        connect=sqlite3.connect
        with patch.object(self.library,'_db',wraps=self.library._db) as writes, \
                patch.object(self.library,'_read_db',wraps=self.library._read_db) as reads, \
                patch('vault_rag.asset_library.sqlite3.connect',wraps=connect) as connections:
            self.assertEqual(self.library._pull(self.root,provider,context),0)
            self.assertEqual(writes.call_count,1,'Only the final projection may open a writer, not 5000 identity checks')
            self.assertLess(reads.call_count,64,'Known-only authorization checks must be bounded batches')
            self.assertLess(connections.call_count,128,'Do not open databases per known event')
        provider.read_bytes.assert_not_called()
        provider.scan.assert_called_once_with(directory,max_files=20000,max_depth=2,prune_reserved=False,read_ignore=False)
        value,data,item=event(6000);provider.reset_mock();provider.scan.return_value=[item]
        provider.read_bytes.side_effect=None;provider.read_bytes.return_value=data
        self.assertEqual(self.library._pull(self.root,provider,context),1)
        with self.library._read_db(self.root) as db:
            self.assertEqual(tuple(db.execute('SELECT synced,sha256 FROM events WHERE id=?',(value['event_id'],)).fetchone()),
                             (1,hashlib.sha256(data).hexdigest()))
        corrupt_value,corrupt_data,corrupt_item=event(6001)
        provider.scan.return_value=[corrupt_item];provider.read_bytes.return_value=b'wrong bytes'
        with self.assertRaises(RemoteStorageError) as raised:self.library._pull(self.root,provider,context)
        self.assertEqual(raised.exception.code,'asset_library_event_checksum_mismatch')
        known=dict(events[0][2]);known['path']=known['path'][:-69]+'0'*64+'.json'
        for bad,code in ((known,'immutable_asset_library_event_changed'),
                         ({**events[0][2],'size':256*1024+1},'invalid_asset_library_event_path'),
                         ({**events[0][2],'path':directory+'/ff/'+events[0][2]['path'].rsplit('/',1)[1]},'invalid_asset_library_event_path')):
            with self.subTest(code=code):
                provider.reset_mock();provider.scan.return_value=[bad]
                with self.assertRaises(RemoteStorageError) as raised:self.library._pull(self.root,provider,context)
                self.assertEqual(raised.exception.code,code);provider.read_bytes.assert_not_called()
        original_check=self.library._check
        for length,revoke_at in ((5000,4),(1,4)):
            # The first case revokes between known batches; the second at the
            # final guard, after the only known event has been skipped.
            with self.subTest(revocation='known',length=length):
                checks=[0];provider.reset_mock();provider.scan.return_value=[entry[2] for entry in events[:length]]
                def revoke(value,**kwargs):
                    checks[0]+=1
                    if checks[0]==revoke_at:self.remote.set_credentials('a'*32,'leafloom',fixtures.SECRET,revision='changed')
                    return original_check(value,**kwargs)
                with patch.object(self.library,'_check',side_effect=revoke),patch.object(self.library,'_db',wraps=self.library._db) as writes:
                    with self.assertRaises(PermissionError):self.library._pull(self.root,provider,context)
                    self.assertEqual(writes.call_count,0)
                provider.read_bytes.assert_not_called()
                self.remote.set_credentials('a'*32,'leafloom',fixtures.SECRET,revision='stable')
        provider.scan.return_value=[corrupt_item]
        def revoke_during_read(*args,**kwargs):
            self.remote.set_credentials('a'*32,'leafloom',fixtures.SECRET,revision='changed');return corrupt_data
        provider.read_bytes.side_effect=revoke_during_read
        with self.assertRaises(PermissionError):self.library._pull(self.root,provider,context)
        with self.library._read_db(self.root) as db:
            self.assertIsNone(db.execute('SELECT 1 FROM events WHERE id=?',(corrupt_value['event_id'],)).fetchone())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],5001)

    def test_large_product_projection_reuses_transaction_guard_and_rolls_back_on_revocation(self):
        self.initialize();context=self.library._context(self.root)
        directory=context['metadata_directory']+'/events'
        with self.library._read_db(self.root) as db:library_id=self.library._get(db,'library_id')
        def product_event(index,product_id,description,parents=()):
            identity=format(index,'032x');entity='product:'+str(product_id)
            state=self.library._default(entity);state['official'].update(title='Product '+str(product_id),description=description)
            value={'schema':'leafloom.asset-library.event.v1','library_id':library_id,'event_id':identity,
                   'kind':'state','entity':entity,'parents':list(parents),'payload':state,'created_at':1}
            data=json.dumps(value,sort_keys=True,separators=(',',':')).encode();sha=hashlib.sha256(data).hexdigest()
            item={'path':directory+'/'+identity[:2]+'/'+identity+'-'+sha+'.json','size':len(data)}
            return value,data,sha,item
        # About 12 MiB of actual product states exceeds SQLite's default 2 MiB
        # page cache. The final INSERTs spill, acquiring an EXCLUSIVE lock that
        # cannot be read by a second connection in the pre-commit guard.
        events=[product_event(index,index+1,'synthetic product facts '*400) for index in range(1200)]
        with self.library._db(self.root) as db:
            db.executemany('INSERT INTO events VALUES(?,?,?,?,?,?,?,1)',
                          [(value['event_id'],'state',value['entity'],'[]',json.dumps(value['payload']),data,sha)
                           for value,data,sha,item in events])
        provider=Mock();provider.scan.return_value=[item for value,data,sha,item in events]
        provider.read_bytes.side_effect=AssertionError('Known product events must not be downloaded again')
        self.assertEqual(self.library._pull(self.root,provider,context),0)
        with self.library._read_db(self.root) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM entities').fetchone()[0],1200)
            before=db.execute("SELECT state FROM entities WHERE id='product:1'").fetchone()[0]
        value,data,sha,item=product_event(5000,1,'changed projection',[events[0][0]['event_id']])
        provider.scan.return_value=[item];provider.read_bytes.side_effect=None;provider.read_bytes.return_value=data
        original_project=self.library._project
        def revoke_after_projection(db):
            original_project(db)
            self.remote.set_credentials('a'*32,'leafloom',fixtures.SECRET,revision='revoked-before-commit')
        with patch.object(self.library,'_project',side_effect=revoke_after_projection):
            with self.assertRaises(PermissionError):self.library._pull(self.root,provider,context)
        with self.library._read_db(self.root) as db:
            self.assertEqual(db.execute("SELECT state FROM entities WHERE id='product:1'").fetchone()[0],before,
                             'A changed live authorization must still roll back the large projection')
            self.assertEqual(tuple(db.execute('SELECT synced,sha256 FROM events WHERE id=?',(value['event_id'],)).fetchone()),(1,sha),
                             'The previously verified incoming event remains durable for a later authorized projection')

    def test_normal_shutdown_interrupt_preserves_ready_but_real_errors_remain_visible(self):
        self.initialize()
        for stopping,error_type,expected in (('library',InterruptedError,'ready'),('remote',InterruptedError,'ready'),
                                              ('none',InterruptedError,'invalid_service'),('library',RuntimeError,'invalid_service')):
            with self.subTest(stopping=stopping,error=error_type.__name__):
                self.library.stopped.clear();self.remote.stopped.clear();waits=[0]
                with self.library._db(self.root) as db:self.library._set(db,'sync',{'state':'ready','last_synced_at':123})
                def wait_once(*args):
                    waits[0]+=1
                    if waits[0]>1:self.library.stopped.set()
                def interrupt(context,**kwargs):
                    if stopping=='library':self.library.stopped.set()
                    elif stopping=='remote':self.remote.stopped.set()
                    raise error_type('synthetic interruption')
                with patch.object(self.library.wake,'wait',side_effect=wait_once),patch.object(self.library,'_check',side_effect=interrupt), \
                        patch('vault_rag.asset_library.logger.warning') as log:
                    self.library._loop()
                state=self.library.status(self.root)
                self.assertEqual(state['state'],expected)
                if expected=='ready':
                    self.assertEqual(state['last_synced_at'],123);log.assert_not_called()
                else:
                    self.assertEqual(state['code'],'asset_library_operation_failed');log.assert_called_once()
                    args,kwargs=log.call_args
                    self.assertEqual(args[1],error_type.__name__);self.assertRegex(args[2],r'^_loop:\d+$')
                    self.assertNotIn('synthetic interruption',str(args));self.assertEqual(kwargs,{})
        self.library.stopped.clear();self.remote.stopped.clear()

    def test_sync_reuses_context_directory_checks_and_recovers_deleted_parent(self):
        self.dav.files['Packages/Tool.unitypackage']=b'original package'
        self.scan();self.initialize()
        directory=self.library.settings(self.root)['metadata_directory'];created=[];fault={'status':0,'remaining':0}
        original_client=WebDAVSource._client
        def make_client(provider):
            created.append(provider);return original_client(provider)
        def server(request):
            self.assertIsNone(request.headers.get('cookie'))
            path=unquote(request.url.path).strip('/')
            if request.method=='PUT' and '/events/' in path and fault['remaining']:
                fault['remaining']-=1
                self.dav.directories.discard(str(PurePosixPath(path).parent))
                self.dav.calls.append((request.method,str(request.url)))
                return httpx.Response(fault['status'],headers={'Set-Cookie':'must-not-be-reused=1; Path=/'})
            response=self.dav(request)
            response.headers['Set-Cookie']='must-not-be-reused=1; Path=/'
            return response
        self.remote.transports['a'*32]=httpx.MockTransport(server)
        def queue(first,count):
            for index in range(first,first+count):
                self.library.update(self.root,'official',{'product_id':str(index),'official':{'title':'Product '+str(index)}})
        with patch.object(WebDAVSource,'_client',new=make_client),patch('vault_rag.asset_library.METADATA_WORKERS',1):
            queue(100,12);self.dav.calls.clear()
            result=self.library.sync(self.root)
            self.assertEqual(result['pending'],0);self.assertEqual(len(created),2)
            parents=[directory.rsplit('/',1)[0],directory,directory+'/events']
            for parent in parents:
                self.assertEqual(sum(method=='MKCOL' and unquote(urlsplit(url).path).strip('/')==parent for method,url in self.dav.calls),1)
            self.assertEqual(sum(method=='PUT' for method,url in self.dav.calls),12)
            self.assertLess(sum(method=='MKCOL' for method,url in self.dav.calls),24,'Common ancestors must be validated once, rather than four times per event')
            for status in (404,409):
                before=len(created);queue(status,3);fault.update(status=status,remaining=1);self.dav.calls.clear()
                result=self.library.sync(self.root)
                self.assertEqual(result['pending'],0,'A deleted parent must invalidate the batch cache and be recreated once')
                self.assertEqual(len(created),before+2,'Each sync needs fresh control/worker clients, not one client per object')
                self.assertEqual(sum(method=='PUT' for method,url in self.dav.calls),4)
                for parent in parents:
                    self.assertEqual(sum(method=='MKCOL' and unquote(urlsplit(url).path).strip('/')==parent for method,url in self.dav.calls),2)
            queue(900,1);fault.update(status=409,remaining=2)
            failed=self.library.sync(self.root)
            self.assertEqual(failed['pending'],1)
            with self.library._read_db(self.root) as db:
                self.assertEqual(db.execute('SELECT error FROM outbox').fetchone()[0],'metadata_parent_missing')
            self.dav.bad_event_readback=True
            failed=self.library.sync(self.root)
            self.assertEqual(failed['pending'],1,'A transport optimization must not acknowledge corrupt readback')
            self.dav.bad_event_readback=False
            self.assertEqual(self.library.sync(self.root)['pending'],0)
        self.assertTrue(all(provider._session_client is None for provider in created))
        self.assertEqual(self.dav.files['Packages/Tool.unitypackage'],b'original package')

    def test_background_retry_flushes_before_due_pull_but_explicit_and_new_context_pull_first(self):
        self.dav.files['Packages/Tool.unitypackage']=b'original package'
        self.scan();self.initialize();order=[];fail_once={'value':True}
        original_pull=self.library._pull
        def pull(*args,**kwargs):
            order.append('pull');return original_pull(*args,**kwargs)
        def server(request):
            if request.method=='PUT' and '/events/' in unquote(request.url.path):
                order.append('put')
                if fail_once['value']:
                    fail_once['value']=False
                    raise httpx.ReadError('PRIVATE exception and fixture password must not escape',request=request)
            return self.dav(request)
        def queue(product):self.library.update(self.root,'official',{'product_id':str(product),'official':{'title':'Product '+str(product)}})
        self.remote.transports['a'*32]=httpx.MockTransport(server)
        with patch('vault_rag.asset_library.time.monotonic',return_value=100) as clock,patch.object(self.library,'_pull',side_effect=pull):
            self.library.sync(self.root);order.clear();clock.return_value=101+BACKGROUND_PULL_INTERVAL;queue(100)
            with self.assertLogs('vault_rag.remote_webdav',level='WARNING') as captured:
                failed=self.library.sync(self.root,_background=True)
            self.assertEqual((failed['state'],failed['pending']),('unreachable',1))
            self.assertEqual(order,['put'],'A due directory walk must not precede an existing authorized queue')
            diagnostic='\n'.join(captured.output)
            self.assertIn('method=PUT type=ReadError',diagnostic)
            self.assertNotIn('PRIVATE',diagnostic);self.assertNotIn('127.0.0.1',diagnostic);self.assertNotIn(fixtures.SECRET,diagnostic)
            with patch('vault_rag.remote_attachments.time.time',return_value=time.time()+120):
                order.clear();done=self.library.sync(self.root,_background=True)
                self.assertEqual(done['pending'],0)
                self.assertEqual(order,['put','pull'],'Recovery must flush first and then catch up remote conflict history')
                order.clear();queue(101);self.library.sync(self.root)
                self.assertEqual(order,['pull','put'],'Explicit synchronization must retain pull-before-flush semantics')
                self.remote.set_credentials('a'*32,'leafloom',fixtures.SECRET,revision='replacement')
                order.clear();queue(102);done=self.library.sync(self.root,_background=True)
                self.assertEqual(done['pending'],0)
                self.assertEqual(order,['pull','put'],'A new authorization context needs a complete pull before upload')
        self.assertEqual(self.dav.files['Packages/Tool.unitypackage'],b'original package')

    def test_only_official_metadata_session_disables_keepalive_and_still_verifies_readback(self):
        source=self.remote._source('a'*32,self.root)
        official=WebDAVSource({**source,'connection_hint':'official-client'},('leafloom',fixtures.SECRET),transport=self.transport)
        direct=WebDAVSource({**source,'connection_hint':'direct'},('leafloom',fixtures.SECRET),transport=self.transport)
        path=source['metadata_directory']+'/events/aa/fixture.json';data=b'{"fixture":"metadata"}'
        original_client=httpx.Client
        with patch('vault_rag.remote_webdav.httpx.Client',wraps=original_client) as factory:
            with official.session():
                self.assertEqual(official.put_immutable(path,data,verified_directories=set()),hashlib.sha256(data).hexdigest())
            self.assertEqual(factory.call_count,1)
            self.assertEqual(factory.call_args.kwargs['limits'].max_keepalive_connections,0)
            self.assertFalse(factory.call_args.kwargs['trust_env'])
            self.assertFalse(factory.call_args.kwargs['follow_redirects'])
        self.dav.bad_event_readback=True
        with patch('vault_rag.remote_webdav.httpx.Client',wraps=original_client) as factory:
            with direct.session():
                with self.assertRaisesRegex(RemoteStorageError,'immutable_object_conflict'):direct.put_immutable(path,data)
            self.assertEqual(factory.call_count,1)
            self.assertNotIn('limits',factory.call_args.kwargs,'Direct batch sessions retain the default connection pool')
        with patch('vault_rag.remote_webdav.httpx.Client',wraps=original_client) as factory:
            with self.assertRaisesRegex(RemoteStorageError,'immutable_object_conflict'):official.put_immutable(path,data)
            self.assertEqual(factory.call_count,2)
            self.assertTrue(all('limits' not in call.kwargs for call in factory.call_args_list),'Ordinary official-client calls do not opt into batch socket policy')
        self.assertEqual(self.dav.files[path],data)

    def test_bounded_metadata_workers_isolate_clients_dependencies_and_failed_ack(self):
        from PIL import Image
        png=self.home/'parallel-cover.png';Image.new('RGB',(4,4),'blue').save(png)
        self.dav.files['Packages/Tool.unitypackage']=b'original package'
        self.scan();self.initialize()
        for index in range(100,112):self.library.update(self.root,'official',{'product_id':str(index),'official':{'title':str(index)}})
        covered=self.library.store_cover(self.root,'123',png,'https://cdn.example.invalid/cover.png')
        cover_id='cover:'+covered['official']['cover']['sha256'];cover_path=covered['official']['cover']['path']
        gate=threading.Event();lock=threading.Lock();stats={'active':0,'maximum':0,'puts':0};worker_clients={};clients=[]
        original_client=WebDAVSource._client
        def make_client(provider,**kwargs):
            client=original_client(provider,**kwargs);clients.append(client)
            if threading.current_thread().name.startswith('asset-metadata'):
                worker_clients.setdefault(threading.get_ident(),[]).append(client)
            return client
        def server(request):
            self.assertIsNone(request.headers.get('cookie'))
            path=unquote(request.url.path).strip('/')
            with lock:stats['active']+=1;stats['maximum']=max(stats['maximum'],stats['active'])
            try:
                if request.method=='PUT':
                    with lock:
                        stats['puts']+=1;number=stats['puts']
                        if number==4:gate.set()
                    if number<=4:self.assertTrue(gate.wait(3),'Four independent metadata objects should be in flight')
                    if path!=cover_path and '/events/' in path:
                        event=json.loads(request.content)
                        if event['payload'].get('official',{}).get('cover'):
                            with self.library._read_db(self.root) as db:
                                self.assertIsNone(db.execute('SELECT 1 FROM outbox WHERE id=?',(cover_id,)).fetchone(),'A dependent event must wait for durable, checksum-verified cover ACK')
                response=self.dav(request);response.headers['Set-Cookie']='never-forward=1; Path=/'
                return response
            finally:
                with lock:stats['active']-=1
        self.remote.transports['a'*32]=httpx.MockTransport(server)
        with patch.object(WebDAVSource,'_client',new=make_client):result=self.library.sync(self.root)
        self.assertEqual(result['pending'],0);self.assertEqual(stats['maximum'],4)
        self.assertEqual(len(worker_clients),4)
        self.assertTrue(all(len(values)==1 for values in worker_clients.values()),'Each worker reuses only its own client')
        self.assertEqual(len({id(client.cookies) for values in worker_clients.values() for client in values}),4)
        self.assertTrue(all(client.is_closed for client in clients))
        self.assertEqual(self.dav.files['Packages/Tool.unitypackage'],b'original package')

        for scenario in ('transport','source','permission','sha'):
            with self.subTest(scenario=scenario):
                self.dav=LibraryDAV();self.transport=httpx.MockTransport(self.dav)
                config,manager,library=self.create_client('parallel-'+scenario,{'transport':'b','source':'c','permission':'d','sha':'e'}[scenario]*32)
                root=str(config.root);self.initialize(library,root);allowed={'value':True};count={'puts':0};gate=threading.Event();guarded=threading.Lock()
                if scenario=='sha':
                    covered=library.store_cover(root,'800',png,'https://cdn.example.invalid/cover.png')
                    expected_pending=2
                else:
                    expected_pending=8 if scenario=='transport' else 1
                    for index in range(expected_pending):library.update(root,'official',{'product_id':str(900+index),'official':{'title':str(index)}})
                def faulty(request):
                    path=unquote(request.url.path).strip('/')
                    if request.method=='PUT':
                        with guarded:
                            count['puts']+=1;number=count['puts']
                            if number==4:gate.set()
                        if scenario=='transport':
                            self.assertTrue(gate.wait(3))
                            if number==1:raise httpx.ReadError('fixture failure',request=request)
                        if scenario=='source':
                            settings=manager._settings(root);settings['sources'][0]['name']='Replacement source'
                            manager.save(root,settings,settings['revision'])
                        if scenario=='permission':allowed['value']=False
                    response=self.dav(request)
                    if scenario=='sha' and request.method=='GET' and '/media/' in path and response.status_code==200:
                        response=httpx.Response(200,headers=dict(response.headers),content=bytes([response.content[0]^1])+response.content[1:])
                    return response
                manager.transports[manager._settings(root)['default_source']]=httpx.MockTransport(faulty)
                if scenario=='transport':
                    with self.assertLogs('vault_rag.remote_webdav',level='WARNING'):result=library.sync(root)
                    self.assertEqual(count['puts'],4,'A failed worker stops further dispatch while successful in-flight objects finish')
                    self.assertEqual(result['pending'],5)
                else:
                    result=library.sync(root,guard=lambda:allowed['value'])
                    self.assertEqual(result['pending'],expected_pending)
                    self.assertEqual(count['puts'],1,'Failed covers must not release their dependent event')
                    self.assertEqual(result['state'],'authorization_required' if scenario in {'source','permission'} else 'invalid_service')
                with library._read_db(root) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM events WHERE synced=0').fetchone()[0],5 if scenario=='transport' else 1)

    def test_explicit_binding_personal_fields_review_and_second_computer_rebuild(self):
        self.dav.files.update({'Packages/Publisher_Tool1.2.6.unitypackage':b'one','Copies/Publisher_Tool1.2.6.unitypackage':b'two'})
        self.scan();self.initialize()
        candidates=self.library.listing(self.root)['items'];first=candidates[0]
        first=self.library.update(self.root,'review',{'id':first['id'],'status':'needs_review','reason':'official_identity_requires_confirmation',
                        'proposed_product_id':'unity.assetstore:358372','proposed_url':'https://assetstore.unity.com/packages/tools/game-toolkits/boardgame-358372'},expected_revision=first['revision'])
        self.assertEqual(first['review']['proposed_product_id'],'358372')
        proposed=self.library.update(self.root,'official_url',{'id':first['id'],'product_id':'358372',
                           'url':'https://assetstore.unity.com/packages/tools/game-toolkits/boardgame-358372'},expected_revision=first['revision'])
        self.assertEqual(proposed['kind'],'candidate');self.assertEqual(proposed['review']['proposed_product_id'],'358372')
        self.assertEqual(self.library.listing(self.root,status='product')['total'],0)
        for candidate in self.library.listing(self.root)['items']:
            self.library.update(self.root,'bind',{'asset_id':candidate['files'][0]['asset_id'],'product_id':'358372',
                    'evidence':{'method':'user_confirmed','url':'https://assetstore.unity.com/packages/tools/game-toolkits/boardgame-358372'}},expected_revision=candidate['revision'])
        self.library.update(self.root,'official',{'product_id':'358372','official':{'product_id':'358372','title':'BoardGame',
                    'publisher':'Switchboard Studios','categories':['Tools'],'categories_zh':['工具'],'keywords':['board'],'keywords_zh':['桌游'],
                    'summary_zh':'桌游工具','summary_status':'provided','url':'https://assetstore.unity.com/packages/tools/game-toolkits/boardgame-358372'}})
        official=self.library.detail(self.root,'358372')
        self.assertEqual(len(official['files']),2)
        self.assertTrue(all(file['version']=='1.2.6' and file['version_source']=='filename' for file in official['files']))
        self.library.update(self.root,'personal',{'product_id':'358372','personal':{'tags':['owned'],'category':'游戏开发','description':'my note'}},expected_revision=official['revision'])
        self.library.sync(self.root)
        config2,remote2,library2=self.create_client('two','b'*32);self.scan(remote2);self.initialize(library2,str(config2.root))
        rebuilt=library2.detail(str(config2.root),'358372')
        self.assertEqual(rebuilt['personal']['tags'],['owned']);self.assertEqual(rebuilt['official']['summary_zh'],'桌游工具')
        self.assertEqual(rebuilt['official']['keywords_zh'],['桌游'])
        self.assertEqual({file['file_uid'] for file in rebuilt['files']},{file['file_uid'] for file in self.library.detail(self.root,'358372')['files']})
        self.assertNotEqual({file['asset_id'] for file in rebuilt['files']},{file['asset_id'] for file in self.library.detail(self.root,'358372')['files']})
        self.assertEqual(library2.rebuild(str(config2.root))['pending'],0)

    def test_offline_outbox_restart_and_failed_readback_do_not_claim_synced(self):
        self.dav.files['Packages/tool.unitypackage']=b'original';self.scan();self.initialize()
        self.library.update(self.root,'official',{'product_id':'123','official':{'title':'Tool'}})
        self.dav.offline=True
        offline=self.library.sync(self.root);self.assertGreater(offline['pending'],0)
        self.assertEqual(self.library.detail(self.root,'123')['sync_state'],'pending')
        self.library.stop()
        with patch.object(AssetLibrary,'_loop',return_value=None):restarted=AssetLibrary(self.remote)
        self.libraries.append(restarted);self.dav.offline=False;self.remote._reset_connection(self.root,'a'*32)
        self.dav.bad_event_readback=True
        failed=restarted.sync(self.root);self.assertGreater(failed['pending'],0)
        puts=sum(method=='PUT' and '/events/' in path for method,path in self.dav.calls)
        self.dav.bad_event_readback=False;done=restarted.sync(self.root)
        self.assertEqual(done['pending'],0);self.assertEqual(restarted.detail(self.root,'123')['sync_state'],'synced')
        self.assertEqual(sum(method=='PUT' and '/events/' in path for method,path in self.dav.calls),puts,'Readback recovery must recognize the prior immutable event')

    def test_file_batch_readback_controls_candidate_and_product_sync_and_filtered_summary(self):
        originals={'Packages/one.unitypackage':b'first','Copies/one.unitypackage':b'second','Packages/other.unitypackage':b'other'}
        self.dav.files.update(originals);self.scan();self.library.initialize(self.root)
        self.dav.bad_event_readback=True
        self.assertGreater(self.library.sync(self.root)['pending'],0)
        candidates=self.library.listing(self.root)['items']
        self.assertTrue(all(item['sync_state']=='pending' for item in candidates))
        with self.library._db(self.root) as db:
            self.assertEqual(db.execute('SELECT SUM(exported) FROM files').fetchone()[0],3,'Queued identities are not verified identities')
        self.dav.bad_event_readback=False;self.assertEqual(self.library.sync(self.root)['pending'],0)
        self.assertTrue(all(item['sync_state']=='synced' for item in self.library.listing(self.root)['items']))
        for candidate in candidates:
            if candidate['title']=='one.unitypackage':
                self.library.update(self.root,'bind',{'asset_id':candidate['files'][0]['asset_id'],'product_id':'123'},expected_revision=candidate['revision'])
        self.assertEqual(self.library.sync(self.root)['pending'],0)
        product=self.library.detail(self.root,'123');self.assertEqual(len(product['files']),2)
        with self.library._db(self.root) as db:
            row=dict(db.execute('SELECT * FROM files WHERE file_uid=?',(product['files'][0]['file_uid'],)).fetchone())
            identity={key:row[key] for key in ('file_uid','path','name','size','mtime','etag','sha256')}
            self.library._queue(db,self.root,'file_batch','files',{'files':[identity]},[],self.library._context(self.root,'local'))
        self.assertEqual(self.library.detail(self.root,'123')['sync_state'],'pending','Every related file identity must be verified')
        result=self.library.listing(self.root,limit=1)
        self.assertEqual(result['summary'],{'products':1,'candidates':1,'files':3,'bytes':16,'metadata_known':0})
        filtered=self.library.listing(self.root,status='product')
        self.assertEqual(filtered['summary'],{'products':1,'candidates':0,'files':2,'bytes':11,'metadata_known':0})
        self.assertEqual(self.library.sync(self.root)['pending'],0)
        self.assertEqual(self.library.detail(self.root,'123')['sync_state'],'synced')
        self.assertTrue(all(self.dav.files[path]==data for path,data in originals.items()))

    def test_missing_and_excluded_packages_hide_available_files_preserve_history_and_do_not_confuse_unindexed(self):
        originals={'Packages/bound.unitypackage':b'bound','Packages/unmatched.unitypackage':b'unmatched'}
        self.dav.files.update(originals);self.scan();self.initialize()
        candidates={item['title']:item for item in self.library.listing(self.root)['items']}
        bound=candidates['bound.unitypackage'];unmatched=candidates['unmatched.unitypackage']
        self.library.update(self.root,'bind',{'asset_id':bound['files'][0]['asset_id'],'product_id':'123'},expected_revision=bound['revision'])
        self.library.update(self.root,'personal',{'id':unmatched['id'],'personal':{'tags':['keep history']}},expected_revision=unmatched['revision'])
        self.library.update(self.root,'personal',{'product_id':'123','personal':{'description':'owned product'}})
        self.library.sync(self.root)
        before={file['file_uid'] for item in self.library.listing(self.root)['items'] for file in item['files']}
        for path in originals:del self.dav.files[path]
        self.scan()
        with self.remote._db(self.root) as db:
            db.execute("UPDATE assets SET state='excluded' WHERE id=?",(unmatched['files'][0]['asset_id'],))
        hidden=self.library.listing(self.root)
        self.assertEqual(hidden['summary'],{'products':1,'candidates':0,'files':0,'bytes':0,'metadata_known':0})
        self.assertEqual(self.library.detail(self.root,'123')['files'],[])
        self.assertEqual(self.library.detail(self.root,'123')['personal']['description'],'owned product')
        historical=self.library.detail(self.root,unmatched['id'])
        self.assertEqual(historical['files'],[]);self.assertEqual(historical['personal']['tags'],['keep history'])
        with self.library._db(self.root) as db:
            self.assertEqual({row['availability'] for row in db.execute('SELECT availability FROM files')},{'missing','excluded'})
            self.assertEqual({row['file_uid'] for row in db.execute('SELECT file_uid FROM files')},before)
        config2,remote2,library2=self.create_client('two','b'*32)
        self.initialize(library2,str(config2.root))  # Catalog identities are known; this computer has not scanned original packages.
        unknown=library2.listing(str(config2.root))
        self.assertEqual(unknown['summary'],{'products':1,'candidates':1,'files':0,'bytes':0,'metadata_known':2})
        self.assertTrue(all(file['availability']=='unindexed' for item in unknown['items'] for file in item['files']))
        self.dav.files.update(originals);self.scan()
        restored=self.library.listing(self.root)
        self.assertEqual(restored['summary'],{'products':1,'candidates':1,'files':2,'bytes':14,'metadata_known':0})
        self.assertEqual({file['file_uid'] for item in restored['items'] for file in item['files']},before)
        self.assertEqual(self.library.detail(self.root,unmatched['id'])['personal']['tags'],['keep history'])

    def test_official_refresh_preserves_chinese_and_marks_changed_facts_for_summary(self):
        self.dav.files['Packages/tool.unitypackage']=b'original';self.scan();self.initialize()
        url='https://assetstore.unity.com/packages/tools/fictional-tool-123'
        facts={'product_id':'unity.assetstore:123','url':url,'title':'Fictional Tool','publisher':'Fictional Studio',
               'source_excerpt':'A fictional development tool.','categories':['Tools'],'keywords':['utility'],
               'latest_version':'1.0','compatibility':{},'summary_zh':'','summary_status':'needs_summary',
               'categories_zh':[],'keywords_zh':[],'fetched_at':2}
        self.library.update(self.root,'official',{'product_id':'123','official':{
            **facts,'summary_zh':'虚构的开发工具。','summary_status':'provided','categories_zh':['工具'],'keywords_zh':['实用工具'],'fetched_at':1}})
        self.library.update(self.root,'personal',{'product_id':'123','personal':{'tags':['保留'],'description':'个人备注'}})
        source=Mock();source.product.return_value=facts
        enrichment=AssetEnrichment(self.library,source=source)
        unchanged=enrichment.official_url(self.root,url)
        self.assertEqual(unchanged['official']['summary_zh'],'虚构的开发工具。')
        self.assertEqual(unchanged['official']['summary_status'],'provided')
        self.assertEqual(unchanged['official']['categories_zh'],['工具'])
        self.assertEqual(unchanged['official']['keywords_zh'],['实用工具'])
        self.assertEqual(unchanged['official']['fetched_at'],2)
        source.product.return_value={**facts,'source_excerpt':'Updated fictional tool facts.','latest_version':'2.0','fetched_at':3}
        changed=enrichment.official_url(self.root,url)
        self.assertEqual(changed['official']['summary_zh'],'虚构的开发工具。')
        self.assertEqual(changed['official']['summary_status'],'needs_summary')
        self.assertEqual(changed['official']['categories_zh'],['工具'])
        self.assertEqual(changed['official']['keywords_zh'],['实用工具'])
        self.assertEqual(changed['personal']['description'],'个人备注')
        self.assertEqual(changed['personal']['tags'],['保留'])
        source.product.return_value={**facts,'summary_zh':'新提供的中文摘要。','summary_status':'provided','categories_zh':['开发工具']}
        translated=enrichment.official_url(self.root,url)
        self.assertEqual(translated['official']['summary_zh'],'新提供的中文摘要。')
        self.assertEqual(translated['official']['summary_status'],'provided')
        self.assertEqual(translated['official']['categories_zh'],['开发工具'])

    def test_collector_recovers_binding_checkpoint_without_network_and_preserves_rebound_or_missing_inputs(self):
        class InlineThread:
            def __init__(self,*,target,args,**kwargs):self.target=target;self.args=args
            def start(self):self.target(*self.args)
            def is_alive(self):return False
        path='Packages/Asset Store-5.x/Fictional Studio/Fictional Room.unitypackage'
        self.dav.files[path]=b'original';self.scan();self.initialize()
        candidate=self.library.listing(self.root)['items'][0];file=candidate['files'][0]
        url='https://assetstore.unity.com/packages/tools/fictional-room-123'
        facts={'product_id':'unity.assetstore:123','url':url,'title':'Fictional Room','publisher':'Fictional Studio'}
        source=Mock();source.search.return_value=[url];source.product.return_value=facts
        enrichment=AssetEnrichment(self.library,source=source);real=enrichment.official_url
        def crash_after_binding(*args,**kwargs):
            checkpoint=enrichment.status(self.root)
            self.assertEqual(checkpoint['inputs'][0]['id'],candidate['id'])
            self.assertEqual(checkpoint['active']['file_uid'],file['file_uid'])
            real(*args,**kwargs);raise SystemExit('synthetic process exit before result checkpoint')
        with patch('vault_rag.unity_asset_store.threading.Thread',InlineThread),patch.object(enrichment,'official_url',side_effect=crash_after_binding):
            with self.assertRaises(SystemExit):enrichment.start(self.root)
        crash=copy.deepcopy(enrichment.status(self.root))
        self.assertEqual(crash['results'],[]);self.assertEqual(crash['state'],'running')
        identity=self.library.collection_identity(self.root,file['file_uid'])
        self.assertEqual(identity['product_id'],'123');self.assertNotIn('path',identity);self.assertNotIn('storage_id',identity)
        source=Mock();source.search.side_effect=AssertionError('Recovery must not repeat the official request')
        source.product.side_effect=AssertionError('Recovery must not repeat the official request')
        restarted=AssetEnrichment(self.library,source=source)
        with patch('vault_rag.unity_asset_store.threading.Thread',InlineThread):recovered=restarted.start(self.root)
        self.assertEqual((recovered['total'],recovered['succeeded'],recovered['needs_review']),(1,1,0))
        self.assertEqual(recovered['results'][0]['reason'],'checkpoint_recovered');self.assertNotIn('active',recovered)
        source.search.assert_not_called();source.product.assert_not_called()
        self.library.update(self.root,'official',{'product_id':'456','official':{'title':'Different Product','publisher':'Other Studio',
            'url':'https://assetstore.unity.com/packages/tools/different-product-456'}})
        self.library.update(self.root,'bind',{'asset_id':file['asset_id'],'product_id':'456','evidence':{'method':'user_confirmed'}})
        restarted._save(self.root,crash)
        with patch('vault_rag.unity_asset_store.threading.Thread',InlineThread):changed=restarted.start(self.root)
        self.assertEqual((changed['total'],changed['succeeded'],changed['needs_review']),(1,0,1))
        self.assertEqual(changed['results'][0]['reason'],'candidate_binding_changed')
        self.assertEqual(self.library.collection_identity(self.root,file['file_uid'])['product_id'],'456')
        with self.remote._db(self.root) as db:db.execute("UPDATE assets SET state='missing' WHERE id=?",(file['asset_id'],))
        restarted._save(self.root,crash)
        with patch('vault_rag.unity_asset_store.threading.Thread',InlineThread):missing=restarted.start(self.root)
        self.assertEqual((missing['total'],missing['succeeded'],missing['needs_review']),(1,0,1))
        self.assertEqual(missing['results'][0]['reason'],'candidate_unavailable');source.search.assert_not_called()
        # An active item that was never bound must still execute its normal retry.
        second='Copies/Asset Store-5.x/Fictional Studio/Fictional Room.unitypackage'
        self.dav.files[second]=b'another package';self.scan()
        other=next(item for item in self.library.listing(self.root)['items'] if item['kind']=='candidate')
        retry=copy.deepcopy(crash);retry['inputs']=[{'id':other['id'],'file_uid':other['files'][0]['file_uid']}]
        retry['active'].update(id=other['id'],file_uid=other['files'][0]['file_uid'])
        restarted._save(self.root,retry);source.search.side_effect=None;source.search.return_value=[url]
        source.product.side_effect=None;source.product.return_value=facts
        with patch('vault_rag.unity_asset_store.threading.Thread',InlineThread),patch.object(restarted.stopped,'wait',return_value=False):retried=restarted.start(self.root)
        self.assertEqual((retried['total'],retried['succeeded'],retried['needs_review']),(1,1,0))
        source.search.assert_called_once();source.product.assert_called_once();self.assertNotIn('active',retried)
        # No historical input ID means no invented success, even with bound files present.
        restarted._save(self.root,{'job_id':'legacy','state':'running','total':7,'results':[]})
        source.reset_mock()
        with patch('vault_rag.unity_asset_store.threading.Thread',InlineThread):legacy=restarted.start(self.root)
        self.assertEqual((legacy['total'],legacy['succeeded'],legacy['needs_review']),(7,0,0))
        self.assertEqual(legacy['legacy_unresolved'],7);source.search.assert_not_called()

    def test_two_computers_preserve_conflicting_heads_and_resolve_explicitly(self):
        self.dav.files['Packages/tool.unitypackage']=b'original';self.scan();self.initialize()
        self.library.update(self.root,'official',{'product_id':'123','official':{'title':'Tool'}});self.library.sync(self.root)
        config2,remote2,library2=self.create_client('two','b'*32);root2=str(config2.root);self.scan(remote2);self.initialize(library2,root2)
        one=self.library.detail(self.root,'123');two=library2.detail(root2,'123')
        self.assertEqual(one['revision'],two['revision'])
        self.library.update(self.root,'personal',{'product_id':'123','personal':{'tags':['one']}},expected_revision=one['revision'])
        library2.update(root2,'personal',{'product_id':'123','personal':{'tags':['two']}},expected_revision=two['revision'])
        self.library.sync(self.root);library2.sync(root2);self.library.sync(self.root)
        conflict=self.library.detail(self.root,'123')
        self.assertEqual(conflict['sync_state'],'conflict');self.assertEqual(len(conflict['conflicts']),2)
        self.assertEqual({tuple(head['state']['personal']['tags']) for head in conflict['conflicts']},{('one',),('two',)})
        chosen=next(head['revision'] for head in conflict['conflicts'] if head['state']['personal']['tags']==['two'])
        resolved=self.library.update(self.root,'resolve',{'product_id':'123','revision':chosen},expected_revision=conflict['revision'])
        self.assertEqual(resolved['personal']['tags'],['two']);self.assertEqual(resolved['conflicts'],[])
        self.library.sync(self.root);library2.sync(root2)
        self.assertEqual(library2.detail(root2,'123')['personal']['tags'],['two'])

    def test_owner_revocation_credentials_generation_and_background_context_are_guarded(self):
        self.dav.files['Packages/tool.unitypackage']=b'original';self.scan();self.initialize()
        allowed=[True];self.remote.authorize_owner=lambda root,owner,revision:allowed[0]
        calls=[0]
        def guard():calls[0]+=1;return allowed[0]
        self.library.initialize(self.root,owner='mcp-owner',guard=guard)
        with self.library.lock,self.library._db(self.root) as db:requested=self.library._get(db,'requested')
        self.library.sync(self.root,owner='mcp-owner',_saved_context=requested)
        self.assertIs(self.library.guards[(self.root,'mcp-owner',requested['workspace_revision'])],guard)
        self.assertGreater(calls[0],0)
        self.library.update(self.root,'official',{'product_id':'123','official':{'title':'Guarded'}},owner='mcp-owner')
        allowed[0]=False;count=len(self.dav.calls)
        rejected=self.library.sync(self.root,owner='mcp-owner',_saved_context=requested)
        self.assertEqual(rejected['state'],'authorization_required');self.assertEqual(len(self.dav.calls),count)
        self.library.sync(self.root)
        self.assertIn('authorization_required',self.library.status(self.root)['outbox'])
        allowed[0]=True;self.remote.set_credentials('a'*32,'leafloom',fixtures.SECRET,revision='rotated')
        self.library.sync(self.root,resume=True)
        self.assertGreater(self.library.status(self.root)['pending'],0,'Local owner cannot claim MCP work')
        resumed=self.library.sync(self.root,owner='mcp-owner',resume=True)
        self.assertEqual(resumed['pending'],0)

    def test_metadata_namespace_is_pruned_and_cover_uses_verified_object(self):
        from PIL import Image
        self.dav.files['Packages/tool.unitypackage']=b'original';self.scan();self.initialize()
        source_before=dict(self.dav.files)
        self.library.update(self.root,'official',{'product_id':'123','official':{'title':'Tool'}})
        png=self.home/'cover.png';Image.new('RGB',(4,4),'blue').save(png);original=png.read_bytes()
        covered=self.library.store_cover(self.root,'123',png,'https://cdn.example.invalid/product.png')
        self.assertEqual(png.read_bytes(),original)
        local=self.library.cover(self.root,'123');self.assertEqual(hashlib.sha256(local.read_bytes()).hexdigest(),covered['official']['cover']['sha256'])
        self.assertEqual(self.library.sync(self.root)['pending'],0)
        local.unlink();self.assertTrue(self.library.cover(self.root,'123').is_file())
        self.scan()
        with self.remote._db(self.root) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM assets WHERE path LIKE 'Incoming/LeafLoomCatalog/v1/%'").fetchone()[0],0)
        self.assertFalse(any(method=='DELETE' for method,_ in self.dav.calls))
        self.assertEqual(self.dav.files['Packages/tool.unitypackage'],source_before['Packages/tool.unitypackage'])
        with self.assertRaises(ConflictError):self.library.save_settings(self.root,{'metadata_directory':'Incoming/Other'})

    def test_explicit_local_resume_refreshes_background_request_context(self):
        self.dav.files['Packages/tool.unitypackage']=b'original';self.scan();self.initialize()
        self.remote.set_credentials('a'*32,'leafloom',fixtures.SECRET,revision='rotated')
        self.library.sync(self.root,resume=True)
        with self.library.lock,self.library._db(self.root) as db:requested=self.library._get(db,'requested')
        self.assertEqual(requested['credential_revision'],'rotated')
        self.library.update(self.root,'official',{'product_id':'123','official':{'title':'After rotation'}})
        self.assertGreater(self.library.status(self.root)['pending'],0)
        self.library.sync(self.root,_saved_context=requested)
        self.assertEqual(self.library.status(self.root)['pending'],0)

    def test_library_keeps_attachment_aliases_tags_and_migration_receipts(self):
        self.dav.files['Packages/legacy.unitypackage']=b'original-package';self.scan()
        physical='Packages/legacy.unitypackage';logical='_attachments/_remote/'+'a'*32+'/'+physical
        item=self.remote.update_metadata(self.root,logical,{'tags':['attachment-tag'],'category':'legacy','description':'original attachment metadata'})
        with self.remote.lock,self.remote._db(self.root) as db:
            db.execute('INSERT INTO aliases VALUES(?,?)',('_attachments/legacy.unitypackage',item['asset_id']))
            job=self.remote._new_job(self.root,'a'*32,'local','migration')
            job.update(state='completed',confirmed=True,items=[{'state':'released','path':'_attachments/legacy.unitypackage','remote_path':physical,
                       'asset_id':item['asset_id'],'size':item['size'],'sha256':item['sha256']}])
            self.remote._job_save(db,job)
            aliases=[tuple(row) for row in db.execute('SELECT * FROM aliases ORDER BY path')]
            receipt=db.execute('SELECT payload FROM jobs WHERE id=?',(job['id'],)).fetchone()[0]
        self.initialize();candidate=self.library.listing(self.root)['items'][0]
        self.library.update(self.root,'bind',{'asset_id':candidate['files'][0]['asset_id'],'product_id':'123'},expected_revision=candidate['revision'])
        self.library.update(self.root,'personal',{'product_id':'123','personal':{'tags':['product-tag']}})
        self.library.sync(self.root)
        after=self.remote.stat(self.root,'_attachments/legacy.unitypackage')
        self.assertEqual((after['asset_id'],after['tags'],after['category'],after['description']),
                         (item['asset_id'],['attachment-tag'],'legacy','original attachment metadata'))
        with self.remote._db(self.root) as db:
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM aliases ORDER BY path')],aliases)
            self.assertEqual(db.execute('SELECT payload FROM jobs WHERE id=?',(job['id'],)).fetchone()[0],receipt)
        self.assertEqual(self.dav.files[physical],b'original-package')
