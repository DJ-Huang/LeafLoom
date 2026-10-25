"""Attachment storage through authenticated UI APIs and production HTTP MCP.

All roots, credentials and bytes are fictional. MockTransport is the only DAV
transport, and the outbox worker is driven explicitly rather than by timers.
"""
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

import httpx
from starlette.testclient import TestClient

from tests.test_remote_attachments import FakeDAV, SECRET, SOURCE
from vault_rag.local_state import LocalConfig
from vault_rag.remote_attachments import RemoteAttachments
from vault_rag.web_server import create_app


BASE_URL = 'https://files.example.invalid/'
CREDENTIAL_REVISION = 'fixture-credential-v1'


class AttachmentStorageApiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.root = self.home / 'vault'
        self.root.mkdir()
        self.config = LocalConfig(self.home / 'state')
        self.config.save({'root': str(self.root)})
        self.dav = FakeDAV()
        self.transport = httpx.MockTransport(self.dav)
        with patch.object(RemoteAttachments, '_loop', return_value=None):
            self.app = create_app(self.config, start_background=False)
        self.remote = self.app.state.remote_attachments
        self.remote.transports[SOURCE] = self.transport
        self.manager = TestClient(self.app, base_url=self.app.state.websites.ui_origin,
                                  client=('127.0.0.1', 2345))
        self.client = self.manager.__enter__()
        self.addCleanup(self.manager.__exit__, None, None, None)
        self.client.get('/')
        session = self.client.get('/api/session')
        self.assertEqual(session.status_code, 200, session.text)
        self.headers = {'X-Vault-CSRF': session.json()['csrf']}

    def request(self, method, endpoint, *, expected=200, **values):
        headers = values.pop('headers', self.headers if method != 'GET' else {})
        response = self.client.request(method, endpoint, headers=headers, **values)
        self.assertEqual(response.status_code, expected, response.text)
        return response

    def settings(self):
        return self.request('GET', '/api/attachments/storage',
                            params={'root': str(self.root)}).json()

    def configure(self, *, default='local'):
        current = self.settings()
        value = {
            'root': str(self.root), 'revision': current['revision'],
            'storages': [{
                'storage_id': SOURCE, 'name': 'Fictional generic WebDAV',
                'base_url': BASE_URL, 'remote_root': '',
                'upload_directory': 'Incoming', 'username': 'leafloom',
                'connection_hint': 'direct', 'enabled': True,
            }],
            'default_storage_id': default,
            'cache_limit_bytes': 2 * 1024**2,
            'outbox_limit_bytes': 8 * 1024**2,
        }
        saved = self.request('PUT', '/api/attachments/storage', json=value).json()
        self.request('POST', '/api/attachments/storage/credentials', json={
            'entries': {SOURCE: {'password': SECRET, 'revision': CREDENTIAL_REVISION}},
        })
        return saved

    def put(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())
        return target

    def initialize(self):
        self.request('POST', '/api/attachments/initialize', json={'root': str(self.root)})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = self.request('GET', '/api/attachments/status',
                                  params={'root': str(self.root)}).json()
            if status['usable']:
                return
            if status['state'] in {'failed', 'unsupported', 'cancelled'}:
                self.fail(f'Fixture index failed: {status}')
            time.sleep(.01)
        self.fail('Fixture index did not finish')

    def scan(self):
        result = self.request('POST', '/api/attachments/storage/scan', json={
            'root': str(self.root), 'storage_id': SOURCE,
        }).json()
        self.assertTrue(result['ok'], result)
        deadline=time.monotonic()+5
        while self.settings()['storages'][0].get('connection',{}).get('state')=='scanning':
            if time.monotonic()>deadline:self.fail('Fixture remote scan did not finish')
            time.sleep(.01)
        self.initialize()

    def details(self, path):
        return self.request('GET', '/api/attachments/details',
                            params={'root': str(self.root), 'path': path}).json()

    def metadata(self, item, **values):
        return self.request('PATCH', '/api/attachments/metadata', json={
            'root': str(self.root), 'asset_id': item['asset_id'],
            'metadata_revision': item['metadata_revision'], **values,
        }).json()

    def mcp(self, action, expect_error=False, **values):
        access = self.app.state.mcp_access
        if not hasattr(self, 'mcp_token'):
            self.mcp_token = access.configure('local', enabled=True, write=True)['token']
        # FastMCP accepts the production loopback origin, separately from the
        # management UI's per-installation hostname and host-only cookie.
        response = self.client.post(f"http://127.0.0.1:{self.config.data.get('port', 18080)}/mcp", headers={
            'Accept': 'application/json, text/event-stream',
            'Authorization': 'Bearer ' + self.mcp_token,
        }, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': 'vault_files', 'arguments': {
                'request': {'action': action, **values},
                'workspace_revision': self.config.data['revision'],
            }},
        })
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()['result']
        self.assertEqual(bool(result.get('isError')),expect_error,result)
        value = result['structuredContent']
        self.assertEqual(json.loads(result['content'][0]['text']), value)
        self.assertNotIn(SECRET, json.dumps(value))
        self.assertNotIn(BASE_URL, json.dumps(value))
        return value

    def job(self, key):
        return self.request('GET', '/api/attachments/storage/jobs/' + key,
                            params={'root': str(self.root)}).json()

    def wait_job(self, key):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.job(key)
            if result['state'] not in {'planned', 'queued', 'running', 'uploading', 'verifying'}:
                return result
            time.sleep(.01)
        self.fail('Fixture storage task did not finish')

    def test_legacy_settings_can_change_address_without_metadata_directory(self):
        self.configure(default=SOURCE)
        path = self.remote._state('settings.json')
        legacy = json.loads(path.read_text())
        legacy['sources'][0].pop('metadata_directory')
        path.write_text(json.dumps(legacy))
        original_credentials = dict(self.remote.credentials)
        current = self.settings()
        profile = current['storages'][0]
        profile.pop('metadata_directory')  # Older clients omit this field too.
        profile.pop('password_saved')
        profile.pop('connection')
        profile['base_url'] = 'http://192.168.1.20:8068/'
        saved = self.request('PUT', '/api/attachments/storage', json={
            key: value for key, value in current.items() if key not in {'cache', 'outbox'}
        }).json()
        self.assertEqual(saved['storages'][0]['base_url'], profile['base_url'])
        self.assertEqual(saved['storages'][0]['metadata_directory'], 'Incoming/LeafLoomCatalog/v1')
        self.assertEqual(saved['default_storage_id'], SOURCE)
        self.assertEqual(self.remote.credentials, original_credentials)
        self.assertEqual(json.loads(path.read_text())['sources'][0]['id'], SOURCE)

    def test_tailnet_address_can_be_saved_but_public_http_still_rejected(self):
        self.configure(default=SOURCE)
        current=self.settings()
        allowed={'storage_id','name','base_url','remote_root','upload_directory','metadata_directory','username','enabled','connection_hint'}
        current['storages']=[{k:v for k,v in profile.items() if k in allowed} for profile in current['storages']]
        body={k:v for k,v in current.items() if k not in {'cache','outbox'}}
        body['storages'][0]['base_url']='http://100.100.1.20:8068/'
        saved=self.request('PUT','/api/attachments/storage',json=body).json()
        self.assertEqual(saved['storages'][0]['base_url'],body['storages'][0]['base_url'])
        self.assertTrue(saved['storages'][0]['password_saved'])
        body['revision']=saved['revision']
        body['storages'][0]['base_url']='http://100.128.0.1:8068/'
        self.request('PUT','/api/attachments/storage',json=body,expected=400)
        self.assertEqual(self.settings()['storages'][0]['base_url'],'http://100.100.1.20:8068/')

    def test_settings_credentials_are_private_csrf_guarded_and_atomically_replaced(self):
        saved = self.configure()
        self.assertEqual(saved['storages'][0]['base_url'], BASE_URL)
        self.assertEqual(saved['storages'][0]['connection_hint'], 'direct')
        self.assertTrue(self.settings()['storages'][0]['password_saved'])
        checked = self.request('POST', '/api/attachments/storage/test', json={
            'root': str(self.root), 'storage_id': SOURCE,
        }).json()
        self.assertEqual(checked['state'], 'ready')
        self.assertTrue(checked['read_verified'])

        original = dict(self.remote.credentials)
        credentials = {'entries': {SOURCE: {'password': SECRET, 'revision': 'replacement'}}}
        self.request('POST', '/api/attachments/storage/credentials', json=credentials,
                     headers={}, expected=403)
        self.request('POST', '/api/attachments/storage/credentials', json=credentials,
                     headers={**self.headers, 'Origin': 'https://hostile.example.invalid'}, expected=403)
        # Even a replace operation with a valid first deletion is all-or-nothing
        # when a later entry is invalid.
        self.request('POST', '/api/attachments/storage/credentials', expected=400, json={
            'replace': True,
            'entries': {SOURCE: None, 'invalid-id': {'password': SECRET, 'revision': 'invalid'}},
        })
        self.assertEqual(self.remote.credentials, original)
        self.assertTrue(self.settings()['storages'][0]['password_saved'])
        for endpoint in ('/api/session', '/api/config', '/api/attachments/storage',
                         '/api/attachments/storage/jobs?root=' + str(self.root)):
            response = self.client.get(endpoint)
            self.assertNotIn(SECRET, response.text, endpoint)
            self.assertNotIn('credential_revision', response.text, endpoint)
        for file in self.home.rglob('*'):
            if file.is_file():
                self.assertNotIn(SECRET.encode(), file.read_bytes(), str(file))
        self.assertTrue(self.dav.calls)
        self.assertTrue(all(url.startswith(BASE_URL) for _, url in self.dav.calls))

    def test_late_desktop_snapshot_cannot_restore_a_superseded_password_or_clear(self):
        self.configure()
        endpoint='/api/attachments/storage/credentials'
        newer={'replace':True,'sync_sequence':2,'entries':{SOURCE:{'password':SECRET,'revision':'newer'}}}
        self.request('POST',endpoint,json=newer)
        late={**newer,'sync_sequence':1,'entries':{SOURCE:{'password':'old fixture','revision':'older'}}}
        response=self.request('POST',endpoint,json=late).json()
        self.assertTrue(response['superseded'])
        self.assertEqual(self.remote.credentials[SOURCE][2],'newer')
        self.request('POST',endpoint,json={'replace':True,'sync_sequence':3,'entries':{}})
        self.request('POST',endpoint,json=newer)
        self.assertEqual(self.remote.credentials,{})
        for sequence in (True,0,-1,2**53,'4'):
            self.request('POST',endpoint,expected=400,json={**newer,'sync_sequence':sequence})
        self.request('POST',endpoint,expected=400,json={**newer,'replace':False,'sync_sequence':4})
        self.assertEqual(self.remote.credentials,{})

    def test_scan_metadata_conflict_and_mcp_asset_id_reads_and_tag_queries(self):
        self.configure()
        content = b'fixture-image-original\x00\xff'
        self.dav.files['Incoming/texture.png'] = content
        self.scan()
        page = self.request('GET', '/api/attachments', params={
            'root': str(self.root), 'storage_id': SOURCE,
        }).json()
        self.assertEqual(page['total'], 1)
        item = page['items'][0]
        self.assertEqual(item['source'], 'remote')
        self.assertEqual(item['storage_id'], SOURCE)
        self.assertEqual(item['name'], 'texture.png')
        self.assertEqual(item['capabilities'], {'rename': False, 'move': False, 'trash': False})
        original = self.details(item['path'])
        updated = self.metadata(original, tags=['texture', 'wood'], category='Materials',
                                description='Fictional wood texture')
        self.assertEqual(updated['tags'], ['texture', 'wood'])
        self.assertNotEqual(updated['metadata_revision'], original['metadata_revision'])
        self.request('PATCH', '/api/attachments/metadata', expected=409, json={
            'root': str(self.root), 'asset_id': item['asset_id'],
            'metadata_revision': original['metadata_revision'], 'tags': ['stale-overwrite'],
        })
        self.assertEqual(self.details(item['path'])['tags'], ['texture', 'wood'])
        queried = self.mcp('list', tags=['texture'], category='Materials', storage_id=SOURCE)
        self.assertEqual([value['asset_id'] for value in queried['items']], [item['asset_id']])
        stat = self.mcp('stat', asset_id=item['asset_id'])
        self.assertEqual(stat['path'], item['path'])
        self.assertEqual(stat['description'], 'Fictional wood texture')
        read = self.mcp('read', asset_id=item['asset_id'], expected_revision=stat['revision'],
                        offset=2, limit=8)
        self.assertEqual(base64.b64decode(read['data_base64']), content[2:10])
        self.assertFalse((self.root / item['path']).exists())

    def test_source_filter_http_and_mcp_scope_totals_facets_and_pagination(self):
        self.configure()
        self.put('local.png', b'png')
        self.put('local.pdf', b'pdf12')
        self.dav.files.update({'Incoming/one.bin': b'1234', 'Incoming/two.bin': b'1234567'})
        self.scan()
        params = {'root': str(self.root), 'sort': 'path', 'order': 'asc'}
        local = self.request('GET', '/api/attachments', params={**params, 'source': 'local'}).json()
        self.assertEqual(local['total'], 2)
        self.assertEqual(local['summary'], {'files': 2, 'bytes': 8, 'kinds': {'image': 1, 'pdf': 1}, 'by_source': {'local': {'files': 2, 'bytes': 8}, 'remote': {'files': 0, 'bytes': 0}}})
        remote = self.request('GET', '/api/attachments', params={**params, 'source': 'remote', 'limit': 1}).json()
        self.assertEqual(remote['total'], 2)
        self.assertEqual(remote['summary'], {'files': 2, 'bytes': 11, 'kinds': {'other': 2}, 'by_source': {'local': {'files': 0, 'bytes': 0}, 'remote': {'files': 2, 'bytes': 11}}})
        self.assertEqual(remote['storages'], [{'storage_id': SOURCE, 'name': 'Fictional generic WebDAV', 'enabled': True}])
        self.assertTrue(remote['cursor'])
        next_page = self.request('GET', '/api/attachments', params={
            **params, 'source': 'remote', 'cursor': remote['cursor'], 'limit': 1,
        }).json()
        self.assertEqual(next_page['summary'], remote['summary'])
        self.assertEqual(len(next_page['items']), 1)
        self.assertNotEqual(next_page['items'][0]['asset_id'], remote['items'][0]['asset_id'])
        self.request('GET', '/api/attachments', expected=409, params={
            **params, 'source': 'local', 'cursor': remote['cursor'],
        })
        listed = self.mcp('list', source='remote', storage_id=SOURCE, limit=1)
        self.assertEqual(listed['total'], 2)
        self.assertEqual(listed['summary'], remote['summary'])
        self.assertTrue(all(item['source'] == 'remote' for item in listed['items']))
        self.assertEqual(self.mcp('list', source='local')['summary'], local['summary'])

    def test_full_server_refresh_hides_deleted_assets_from_mcp_but_preserves_identity(self):
        self.configure()
        self.dav.files.update({'Incoming/deleted.bin': b'deleted-original', 'Incoming/retained.bin': b'retained'})
        self.scan()
        before = self.mcp('list', source='remote')
        deleted = next(item for item in before['items'] if item['name'] == 'deleted.bin')
        self.metadata(self.details(deleted['path']), tags=['preserve-on-missing'], category='Reference')
        del self.dav.files['Incoming/deleted.bin']
        self.scan()
        after = self.mcp('list', source='remote')
        self.assertEqual([item['name'] for item in after['items']], ['retained.bin'])
        self.assertEqual(after['total'], 1)
        self.assertEqual(after['summary']['by_source']['remote'], {'files': 1, 'bytes': len(b'retained')})
        self.assertEqual(self.mcp('list', tags=['preserve-on-missing'])['total'], 0)
        kept = self.remote.stat(str(self.root), asset_id=deleted['asset_id'])
        self.assertEqual(kept['state'], 'missing')
        self.assertEqual(kept['path'], deleted['path'])
        self.assertEqual(kept['tags'], ['preserve-on-missing'])

    def test_media_range_populates_verified_cache_and_reuses_it_offline(self):
        self.configure()
        content = b'0123456789-small-server-file'
        self.dav.files['Incoming/preview.bin'] = content
        self.scan()
        item = self.request('GET', '/api/attachments', params={'root': str(self.root)}).json()['items'][0]
        params = {'root': str(self.root), 'path': item['path']}
        ranged = self.request('GET', '/api/media', params=params,
                             headers={'Range': 'bytes=2-7'}, expected=206)
        self.assertEqual(ranged.content, content[2:8])
        self.assertEqual(ranged.headers['content-range'], f'bytes 2-7/{len(content)}')
        self.assertEqual(self.details(item['path'])['cache_state'], 'complete')
        self.dav.offline = True
        calls = len(self.dav.calls)
        self.assertEqual(self.request('GET', '/api/media', params=params).content, content)
        self.assertEqual(len(self.dav.calls), calls)
        self.assertFalse((self.root / item['path']).exists())

    def test_offline_upload_is_durable_pending_then_reconnects_without_local_original(self):
        self.configure(default=SOURCE)
        self.dav.offline = True
        name, content = '原图 #1.png', b'queued-upload-original\x00\xff'
        result = self.request('POST', '/api/upload', params={
            'root': str(self.root), 'name': name, 'central': 'true', 'unique': 'true',
        }, content=content).json()
        self.assertTrue(result['pending'])
        self.assertFalse(result['remote_saved'])
        self.assertEqual(Path(result['path']).name, name)
        self.assertFalse((self.root / result['path']).exists())
        self.remote.process_pending()
        self.assertEqual(self.job(result['job_id'])['state'], 'waiting_for_connection')
        self.assertEqual(self.settings()['outbox']['used_bytes'], len(content))
        self.request('POST', '/api/attachments/cache/clear', json={'root': str(self.root)})
        self.assertEqual(self.settings()['outbox']['used_bytes'], len(content))
        params = {'root': str(self.root), 'path': result['path']}
        self.assertEqual(self.request('GET', '/api/media', params=params).content, content)

        # A fresh manager sees the persisted queue but has no credentials until
        # the desktop/memory-credential bootstrap restores them.
        with patch.object(RemoteAttachments, '_loop', return_value=None):
            restarted = RemoteAttachments(self.config)
        self.addCleanup(restarted.stop)
        restarted.transports[SOURCE] = self.transport
        self.assertEqual(restarted.credentials, {})
        key = result['job_id'].removeprefix('remote:')
        self.assertEqual(restarted.job(str(self.root), key)['state'], 'waiting_for_connection')
        restarted.set_credentials(SOURCE, 'leafloom', SECRET, revision=CREDENTIAL_REVISION)
        self.dav.offline = False
        retry_at = restarted.job(str(self.root), key)['next_retry_at']
        # Reconnection preserves the journaled source backoff across restart.
        with patch('vault_rag.remote_attachments.time.time', return_value=max(time.time(), retry_at) + 1):
            restarted.process_pending()
        done = self.job(result['job_id'])
        self.assertEqual(done['state'], 'completed', done)
        self.assertTrue(done['remote_saved'])
        self.assertFalse(done['pending'])
        self.assertEqual(done['path'], result['path'])
        self.assertEqual(self.details(result['path'])['name'], name)
        self.assertEqual(list(self.dav.files.values()), [content])
        self.assertTrue(next(iter(self.dav.files)).endswith('-' + name))
        self.assertEqual(self.settings()['outbox']['used_bytes'], 0)
        self.assertFalse((self.root / result['path']).exists())
        self.assertFalse(any(path.is_file() for path in (self.root / '_attachments').rglob('*')))
        self.assertFalse(any(method == 'DELETE' for method, _ in self.dav.calls))

    def test_migration_preview_confirm_preserves_tags_and_old_references_then_releases(self):
        self.configure()
        path = '_attachments/photo.png'
        original = self.put(path, b'original-migration-image')
        self.put('outside.png', b'outside-default-attachment-folder')
        self.put('_attachments/readme.md', '# Keep this note')
        self.put('_attachments/project/index.html', '<img src="texture.png">')
        protected = self.put('_attachments/project/texture.png', b'project-dependency')
        text = '![photo](../_attachments/photo.png)\n'
        note = self.put('Notes/scene.md', text)
        self.initialize()
        self.metadata(self.details(path), tags=['photo'], category='References', description='Keep these tags')
        plan = self.request('POST', '/api/attachments/storage/migrations', json={
            'root': str(self.root), 'storage_id': SOURCE,
        }).json()
        self.assertEqual(plan['state'], 'planned')
        self.assertEqual([item['path'] for item in plan['items']], [path])
        self.assertEqual(plan['summary']['files'], 1)
        self.assertIn('_attachments/project/texture.png', [item['path'] for item in plan['exclusions']])
        self.assertTrue(original.exists())
        self.assertFalse(any(method == 'PUT' for method, _ in self.dav.calls))
        endpoint = '/api/attachments/storage/jobs/' + plan['job_id'] + '/execute'
        self.request('POST', endpoint, json={'root': str(self.root)}, expected=400)
        self.assertTrue(original.exists())
        self.request('POST', endpoint, json={'root': str(self.root), 'confirm': True})
        result = self.wait_job(plan['job_id'])
        self.assertEqual(result['state'], 'completed', result)
        self.assertFalse(original.exists())
        self.assertTrue(protected.exists())
        self.assertTrue((self.root / 'outside.png').exists())
        self.assertEqual(note.read_text(), text)
        item = self.details(path)
        self.assertEqual(item['source'], 'remote')
        self.assertEqual(item['path'], path)
        self.assertEqual(item['tags'], ['photo'])
        self.assertEqual(item['description'], 'Keep these tags')
        resolved = self.request('GET', '/api/resolve', params={
            'target': '../' + path, 'source': 'Notes/scene.md',
        }).json()
        self.assertEqual(resolved['candidates'], [path])
        self.assertEqual(self.request('GET', '/api/media', params={
            'root': str(self.root), 'path': path,
        }).content, b'original-migration-image')
        self.assertFalse(list((self.root / '.vault-rag/attachment-migrations').glob('*/originals/*')))
        self.assertFalse(list((self.root / '.vault-rag/remote-attachments/release').glob('*')))

    def test_failed_readback_hash_never_releases_migration_original(self):
        self.configure()
        path, content = '_attachments/photo.png', b'original-must-survive-bad-readback'
        original = self.put(path, content)
        self.initialize()
        plan = self.request('POST', '/api/attachments/storage/migrations', json={
            'root': str(self.root), 'storage_id': SOURCE,
        }).json()
        self.dav.corrupt = True
        self.request('POST', '/api/attachments/storage/jobs/' + plan['job_id'] + '/execute',
                     json={'root': str(self.root), 'confirm': True})
        result = self.wait_job(plan['job_id'])
        self.assertEqual(result['state'], 'failed', result)
        self.assertEqual(original.read_bytes(), content)
        self.assertEqual(self.details(path)['source'], 'local')
        self.assertFalse(list((self.root / '.vault-rag/remote-attachments/release').glob('*')))

    def test_missing_server_asset_blocks_old_thumbnail_media_and_mcp_cache_then_reappears(self):
        import io
        from PIL import Image
        def png(color):
            output=io.BytesIO();Image.new('RGB',(16,16),color).save(output,'PNG');return output.getvalue()
        self.configure()
        physical='Incoming/deleted-preview.png'
        original=png('red');replacement=png('blue')
        length=max(len(original),len(replacement))
        original=original.ljust(length,b'\0');replacement=replacement.ljust(length,b'\0')
        self.assertEqual(len(original),len(replacement))
        self.dav.files[physical]=original;self.scan()
        item=self.mcp('list',source='remote')['items'][0]
        self.metadata(item,tags=['retain-after-server-delete'],category='Saved category',description='Saved description')
        original_info=self.mcp('stat',asset_id=item['asset_id'])
        params={'root':str(self.root),'path':item['path']}
        before=self.request('GET','/api/attachments/thumbnail',params=params)
        media=self.request('GET','/api/media',params=params)
        self.assertEqual(media.content,original)
        del self.dav.files[physical];self.scan()
        scan_status=self.mcp('status')['attachment_storage']['sources'][0]['connection']
        self.assertEqual(scan_status['scan_state'],'completed')
        self.assertEqual(scan_status['scan_missing'],1)
        self.assertTrue(scan_status['scan_id'])
        missing=self.mcp('stat',asset_id=item['asset_id'])
        self.assertEqual(missing['state'],'missing')
        self.assertEqual(missing['tags'],['retain-after-server-delete'])
        self.assertEqual(missing['cache_state'],'none')
        for endpoint,etag in (('/api/attachments/thumbnail',before.headers['etag']),('/api/media',media.headers['etag'])):
            for headers in ({},{'If-None-Match':etag}):
                error=self.request('GET',endpoint,params=params,headers=headers,expected=404).json()
                self.assertEqual(error['error_code'],'remote_asset_missing')
                self.assertEqual(error['state'],'missing')
        error=self.mcp('read',asset_id=item['asset_id'],expected_revision=missing['revision'],expect_error=True)
        self.assertEqual(error['error_code'],'remote_asset_missing')
        self.assertEqual(error['state'],'missing')
        self.assertFalse(error['retryable'])
        self.dav.files[physical]=replacement;self.scan()
        restored=self.mcp('stat',asset_id=item['asset_id'])
        self.assertEqual(restored['state'],'ready')
        self.assertEqual(restored['tags'],missing['tags'])
        self.assertEqual(restored['category'],'Saved category')
        self.assertNotEqual(restored['revision'],original_info['revision'])
        after=self.request('GET','/api/attachments/thumbnail',params=params,headers={'If-None-Match':before.headers['etag']})
        self.assertNotEqual(after.content,before.content)
        self.assertNotEqual(after.headers['etag'],before.headers['etag'])
        self.assertEqual(self.request('GET','/api/media',params=params).content,replacement)
        self.assertFalse(any(method=='DELETE' for method,_ in self.dav.calls))

    def test_ignore_hides_mcp_discovery_but_preserves_old_reference_and_cache(self):
        self.configure()
        rules='leafloom.ignore'
        physical='Incoming/old-reference.py'
        content=b'print("existing-reference")\n'
        self.dav.files[rules]=b'# leafloom-ignore v1\n!*.py\n'
        self.dav.files[physical]=content
        self.scan()
        item=self.mcp('list',source='remote')['items'][0]
        self.metadata(item,tags=['keep-reference'],description='Existing source attachment')
        params={'root':str(self.root),'path':item['path']}
        self.assertEqual(self.request('GET','/api/media',params=params).content,content)
        before=self.mcp('stat',asset_id=item['asset_id'])
        self.assertEqual(before['cache_state'],'complete')
        self.dav.files[rules]=b'# leafloom-ignore v1\n# Use default exclusions\n'
        self.scan()
        self.assertEqual(self.mcp('list',source='remote')['total'],0)
        status=self.mcp('status')['attachment_storage']['sources'][0]['connection']
        self.assertEqual(status['scan_state'],'completed')
        self.assertEqual(status['scan_missing'],0)
        self.assertEqual(status['scan_excluded'],2)  # Source and control file.
        excluded=self.mcp('stat',asset_id=item['asset_id'])
        self.assertEqual(excluded['state'],'excluded')
        self.assertEqual(excluded['tags'],['keep-reference'])
        self.assertEqual(excluded['metadata_revision'],before['metadata_revision'])
        self.assertEqual(excluded['cache_state'],'complete')
        self.dav.offline=True
        self.assertEqual(self.request('GET','/api/media',params=params).content,content)
        read=self.mcp('read',asset_id=item['asset_id'],expected_revision=excluded['revision'])
        self.assertEqual(base64.b64decode(read['data_base64']),content)
        self.assertFalse(any(method in {'PUT','DELETE'} for method,_ in self.dav.calls))

    def test_remote_html_mime_with_png_name_is_sandboxed_and_nosniff(self):
        self.configure()
        content = b'<html><script>window.fixture=true</script></html>'
        self.dav.files['Incoming/mislabeled.png'] = content

        def poisoned_metadata(request):
            response = self.dav(request)
            if request.method == 'PROPFIND':
                # A DAV listing controls MIME independently of the filename.
                # Bytes arrive as octet-stream; the stored metadata is HTML.
                return httpx.Response(response.status_code, content=response.content.replace(
                    b'<getcontenttype>application/octet-stream</getcontenttype>',
                    b'<getcontenttype>text/html</getcontenttype>'))
            return response

        self.remote.transports[SOURCE] = httpx.MockTransport(poisoned_metadata)
        self.scan()
        item = self.request('GET', '/api/attachments',
                            params={'root': str(self.root)}).json()['items'][0]
        self.assertEqual(item['name'], 'mislabeled.png')
        self.assertEqual(item['mime'], 'text/html')
        response = self.request('GET', '/api/media', params={
            'root': str(self.root), 'path': item['path'],
        })
        self.assertEqual(response.content, content)
        self.assertTrue(response.headers['content-type'].startswith('text/html'))
        directives = response.headers['content-security-policy'].split(';')
        self.assertIn('sandbox', [value.strip() for value in directives])
        self.assertNotIn('allow-scripts', response.headers['content-security-policy'])
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')

    def test_cancelled_executed_migration_resumes_without_duplicate_remote_object(self):
        self.configure()
        path, content = '_attachments/resumable.png', b'cancel-after-put-keep-original'
        original = self.put(path, content)
        self.initialize()
        plan = self.request('POST', '/api/attachments/storage/migrations', json={
            'root': str(self.root), 'storage_id': SOURCE,
        }).json()
        entered, release, workers = threading.Event(), threading.Event(), []
        self.addCleanup(release.set)

        def pause_after_put():
            workers.append(threading.current_thread())
            entered.set()
            if not release.wait(3):
                raise AssertionError('Fixture PUT was not released')

        self.dav.after_put = pause_after_put
        endpoint = '/api/attachments/storage/jobs/' + plan['job_id']
        self.request('POST', endpoint + '/execute',
                     json={'root': str(self.root), 'confirm': True})
        self.assertTrue(entered.wait(3), 'Fixture migration never reached PUT')
        cancelled = self.request('POST', endpoint + '/cancel',
                                 json={'root': str(self.root), 'confirm': True}).json()
        self.assertEqual(cancelled['state'], 'cancelled')
        release.set()
        # Wait for the interrupted execution to leave its safe boundary before
        # submitting a new explicit resume request.
        workers[0].join(3)
        self.assertFalse(workers[0].is_alive())
        self.assertEqual(self.job(plan['job_id'])['state'], 'cancelled')
        self.assertEqual(original.read_bytes(), content)
        self.assertEqual(len(self.dav.files), 1)

        self.dav.after_put = None
        self.request('POST', endpoint + '/resume',
                     json={'root': str(self.root), 'confirm': True})
        result = self.wait_job(plan['job_id'])
        self.assertEqual(result['state'], 'completed', result)
        self.assertFalse(original.exists())
        self.assertEqual(list(self.dav.files.values()), [content])
        self.assertEqual(sum(method == 'PUT' for method, _ in self.dav.calls), 1)
        self.assertFalse(any(method == 'DELETE' for method, _ in self.dav.calls))

    def test_mcp_remote_upload_retries_durable_queue_after_receipt_failure_once(self):
        self.configure(default=SOURCE)
        self.dav.offline = True
        self.mcp_token = self.app.state.mcp_access.configure('local', enabled=True, write=True)['token']
        content, name = b'inline-remote-receipt-recovery\x00\xff', 'receipt recovery.png'
        operation_id = 'b' * 32
        arguments = {
            'request': {
                'action': 'upload', 'source': 'base64', 'name': name,
                'data_base64': base64.b64encode(content).decode(),
                'sha256': hashlib.sha256(content).hexdigest(),
            },
            'workspace_revision': self.config.data['revision'],
            'operation_id': operation_id,
        }

        def upload(*, error=False):
            response = self.client.post(
                f"http://127.0.0.1:{self.config.data.get('port', 18080)}/mcp",
                headers={'Accept': 'application/json, text/event-stream',
                         'Authorization': 'Bearer ' + self.mcp_token},
                json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
                    'name': 'vault_files_update', 'arguments': arguments,
                }})
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()['result']
            self.assertEqual(bool(result.get('isError')), error, result)
            value = result['structuredContent']
            self.assertNotIn(SECRET, json.dumps(value))
            if error:
                self.assertEqual(value['error_code'], 'operation_failed')
            return value

        durable, queue = [], self.remote.queue_upload

        def record_durable_queue(*args, **values):
            job = queue(*args, **values)
            durable.append(job)
            return job

        # The durable outbox transaction succeeds; the caller's separate receipt
        # write then fails before MCP can acknowledge its result.
        with patch.object(self.remote, 'queue_upload', side_effect=record_durable_queue), \
                patch.object(self.app.state.file_operations, '_save_receipt',
                             side_effect=OSError('fictional receipt persistence failure')):
            upload(error=True)
        self.assertEqual(len(durable), 1)
        first = durable[0]
        self.assertEqual(first['state'], 'queued')
        self.assertFalse(first['remote_saved'])
        self.assertEqual(self.settings()['outbox']['used_bytes'], len(content))

        replay = upload()
        self.assertEqual(replay['job_id'], first['job_id'])
        self.assertEqual(replay['asset_id'], first['asset_id'])
        self.assertEqual(replay['path'], first['path'])
        self.assertFalse(replay['remote_saved'])
        self.assertNotEqual(replay['state'], 'completed')
        jobs = self.remote.jobs(str(self.root), owner=first['owner'])
        self.assertEqual([job['id'] for job in jobs], [first['id']])
        self.remote.process_pending()
        pending = self.mcp('status', job_id=first['job_id'])
        self.assertEqual(pending['state'], 'waiting_for_connection')
        self.assertFalse(pending['remote_saved'])
        self.assertEqual(self.dav.files, {})

        self.dav.offline = False
        # The failed attempt schedules a retry; becoming reachable does not
        # bypass that deadline or create a second upload/receipt identity.
        with patch('vault_rag.remote_attachments.time.time', return_value=max(time.time(), pending['next_retry_at']) + 1):
            self.remote.process_pending()
        completed = self.mcp('status', job_id=first['job_id'])
        self.assertEqual(completed['state'], 'completed', completed)
        self.assertTrue(completed['remote_saved'])
        self.assertEqual(completed['asset_id'], first['asset_id'])
        self.assertIn(completed['path'], unquote(completed['markdown_link']))
        self.assertTrue(completed['revision'])
        confirmed = upload()
        self.assertTrue(confirmed['replayed'])
        self.assertTrue(confirmed['remote_saved'])
        self.assertEqual(confirmed['asset_id'], first['asset_id'])
        self.assertEqual(confirmed['job_id'], first['job_id'])
        self.assertEqual(confirmed['path'], first['path'])
        self.assertEqual(len(self.remote.jobs(str(self.root), owner=first['owner'])), 1)
        self.assertEqual(list(self.dav.files.values()), [content])
        self.assertEqual(sum(method == 'PUT' for method, _ in self.dav.calls), 1)
        self.assertFalse((self.root / first['path']).exists())


    def test_large_media_range_fetches_only_requested_bytes(self):
        class SparseFixture:
            def __len__(self):
                return 65 * 1024**2

            def __getitem__(self, selected):
                self.assert_slice(selected)
                return b'x' * (selected.stop - selected.start)

            @staticmethod
            def assert_slice(selected):
                if not isinstance(selected, slice):
                    raise AssertionError('Expected a bounded byte range')

        self.configure()
        self.dav.files['Incoming/large.mp4'] = SparseFixture()
        self.remote.save(str(self.root), {
            'cache_max_bytes': 128 * 1024**2,
            **{key: value for key, value in self.remote._settings(str(self.root)).items()
               if key not in {'cache_max_bytes', 'revision'}},
        })
        self.scan()
        item = self.remote.list(str(self.root))['items'][0]
        with patch.object(self.remote, 'materialize', side_effect=AssertionError('Do not download the whole video')):
            response = self.request('GET', '/api/media', expected=206,
                params={'root': str(self.root), 'path': item['path']},
                headers={'Range': 'bytes=2-9'})
        self.assertEqual(response.content, b'x' * 8)
        self.assertEqual(response.headers['content-range'], f'bytes 2-9/{65 * 1024**2}')
        self.assertEqual(self.remote.status(str(self.root))['cache']['used_bytes'], 8)

    def test_large_media_reappearance_invalidates_old_etag_and_if_range(self):
        # A tiny cache budget selects the same streaming path as large media,
        # keeping a full response to a stale If-Range inexpensive in this test.
        self.configure()
        self.remote.save(str(self.root), {
            'cache_max_bytes': 8,
            **{key: value for key, value in self.remote._settings(str(self.root)).items()
               if key not in {'cache_max_bytes', 'revision'}},
        })
        physical = 'Incoming/recreated.mp4'
        original, replacement = b'a' * 64, b'b' * 64
        self.dav.files[physical] = original
        self.scan()
        item = self.remote.list(str(self.root))['items'][0]
        params = {'root': str(self.root), 'path': item['path']}
        with patch.object(self.remote, 'materialize', side_effect=AssertionError('Use streamed media')):
            before = self.request('GET', '/api/media', expected=206, params=params,
                                  headers={'Range': 'bytes=2-9'})
            self.assertEqual(before.content, original[2:10])
            version = json.dumps([str(self.root), item['asset_id'], item.get('etag'),
                                  item.get('mtime'), item['size']], sort_keys=True)
            self.assertEqual(before.headers['etag'], '"' + hashlib.sha256(version.encode()).hexdigest() + '"')

            del self.dav.files[physical]
            self.scan()
            self.assertEqual(self.remote.stat(str(self.root), asset_id=item['asset_id'])['state'], 'missing')
            self.dav.files[physical] = replacement
            self.scan()
            restored = self.remote.stat(str(self.root), asset_id=item['asset_id'])
            self.assertEqual(restored['asset_id'], item['asset_id'])
            self.assertEqual([restored[key] for key in ('etag', 'mtime', 'size', 'mime')],
                             [item[key] for key in ('etag', 'mtime', 'size', 'mime')])
            self.assertGreater(restored['content_generation'], item.get('content_generation', 0))

            after = self.request('GET', '/api/media', expected=206, params=params,
                                 headers={'Range': 'bytes=2-9', 'If-None-Match': before.headers['etag']})
            self.assertEqual(after.content, replacement[2:10])
            self.assertNotEqual(after.headers['etag'], before.headers['etag'])
            full = self.request('GET', '/api/media', params=params,
                                headers={'Range': 'bytes=2-9', 'If-Range': before.headers['etag']})
            self.assertEqual(full.content, replacement)
            self.assertNotIn('content-range', full.headers)
            self.assertEqual(full.headers['etag'], after.headers['etag'])
            self.request('GET', '/api/media', expected=304, params=params,
                         headers={'Range': 'bytes=2-9', 'If-None-Match': after.headers['etag']})
            current = self.request('GET', '/api/media', expected=206, params=params,
                                   headers={'Range': 'bytes=2-9', 'If-Range': after.headers['etag']})
            self.assertEqual(current.content, replacement[2:10])

    def test_large_media_refreshes_weak_metadata_before_conditional_response(self):
        class SparseFixture:
            def __len__(self):return 65 * 1024**2
            def __getitem__(self,selected):
                if not isinstance(selected,slice):raise AssertionError('Expected bounded range')
                return b'x' * (selected.stop-selected.start)

        self.configure()
        self.dav.files['Incoming/large.mp4']=SparseFixture()
        self.scan()
        item=self.remote.list(str(self.root))['items'][0]
        # Older listings can omit ETag while HEAD supplies it. A conditional
        # browser request must not get a 304 from that stale manifest alone.
        with self.remote.lock,self.remote._db(str(self.root)) as db:
            db.execute("UPDATE assets SET etag='' WHERE id=?",(item['asset_id'],))
        item=self.remote.stat(str(self.root),asset_id=item['asset_id'])
        version=json.dumps([str(self.root),item['asset_id'],item.get('etag'),item.get('mtime'),item['size']],sort_keys=True)
        old_etag='"'+hashlib.sha256(version.encode()).hexdigest()+'"'
        params={'root':str(self.root),'path':item['path']}
        with patch.object(self.remote,'materialize',side_effect=AssertionError('Do not download the whole video')):
            response=self.request('GET','/api/media',expected=206,params=params,
                headers={'Range':'bytes=2-9','If-None-Match':old_etag})
            self.assertEqual(response.content,b'x'*8)
            self.assertNotEqual(response.headers['etag'],old_etag)
            self.request('GET','/api/media',expected=304,params=params,
                headers={'Range':'bytes=2-9','If-None-Match':response.headers['etag']})


if __name__ == '__main__':
    unittest.main()
