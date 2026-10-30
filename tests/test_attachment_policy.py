"""Extension policies on disposable roots and mock DAV; never use user data."""
import base64
import hashlib
import json
import unittest
from unittest.mock import patch

from tests import test_attachment_index as index_fixtures
from tests import test_attachment_catalog as catalog_fixtures
from tests import test_attachment_storage_api as api_fixtures
from tests import test_attachment_workspace as workspace_fixtures
from tests import test_remote_attachments as remote_fixtures
from vault_rag.attachment_policy import DEFAULT_EXTENSIONS, allows, normalize_extensions
from vault_rag.attachment_storage_routes import save_settings
from vault_rag.attachment_catalog import AttachmentCatalog
from vault_rag.local_state import ConflictError, Files
from vault_rag.remote_ignore import RemoteIgnore, IGNORE_HEADER


class PolicyIndexTests(unittest.TestCase):
    setUp = index_fixtures.AttachmentIndexTests.setUp
    tearDown = index_fixtures.AttachmentIndexTests.tearDown
    put = index_fixtures.AttachmentIndexTests.put

    def policy(self, extensions):
        path = self.files.state_path('remote-attachments', 'settings.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'root': str(self.root), 'allowed_extensions': extensions}))

    def test_normalization_and_literal_matching(self):
        self.assertEqual(normalize_extensions([' PNG ', '.png', 'TAR.GZ']), ['.png', '.tar.gz'])
        self.assertTrue(allows('folder/ARCHIVE.TAR.GZ', ['.tar.gz']))
        self.assertFalse(allows('folder/png', ['.png']))
        for value in [['*'], ['*.png'], ['../png'], ['a/b'], ['.'], ['a..b'], [None], None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_extensions(value)

    def test_default_filters_existing_index_without_reading_originals(self):
        for name in ['app.js', 'index.html', 'style.css', 'data.json', 'a.png', 'b.pdf', 'c.unitypackage', 'd.svg']:
            self.put(name)
        self.index.refresh()
        with patch.object(Files, 'walk', side_effect=AssertionError('rebuild')), patch.object(type(self.root), 'read_bytes', side_effect=AssertionError('body read')):
            page = self.index.listing()
        self.assertEqual({i['name'] for i in page['items']}, {'a.png', 'b.pdf', 'c.unitypackage', 'd.svg'})
        self.assertEqual(page['summary']['files'], 4)
        self.assertEqual(self.files.resolve('app.js'), ['app.js'])

    def test_policy_change_updates_counts_empty_list_and_cursor_without_rebuild(self):
        self.put('a.png'); self.put('b.png'); self.put('source.js')
        first = self.index.listing(limit=1)
        self.policy(['.js'])
        with patch.object(Files, 'walk', side_effect=AssertionError('rebuild')):
            page = self.index.listing()
            self.assertEqual([i['name'] for i in page['items']], ['source.js'])
            self.assertEqual(page['summary']['files'], 1)
            with self.assertRaises(ConflictError):
                self.index.listing(limit=1, cursor=first['cursor'])
            self.policy([])
            self.assertEqual(self.index.listing()['summary']['bytes'], 0)
            self.assertEqual(self.files.resolve('a.png'), ['a.png'])

    def test_ignore_negation_cannot_override_types_but_custom_types_work(self):
        rule = (IGNORE_HEADER + '\n!*.js\n*.png\n!keep.png\n').encode()
        ignore = RemoteIgnore(); ignore.add('', rule)
        self.assertTrue(ignore.excluded('app.js'))
        self.assertTrue(ignore.excluded('hide.png'))
        self.assertFalse(ignore.excluded('keep.png'))
        custom = RemoteIgnore(allowed_extensions=['.js']); custom.add('', rule)
        self.assertFalse(custom.excluded('app.js'))
        self.assertTrue(custom.excluded('keep.png'))


class PolicyCatalogTests(unittest.TestCase):
    setUp = catalog_fixtures.AttachmentCatalogTests.setUp
    tearDown = catalog_fixtures.AttachmentCatalogTests.tearDown
    put = catalog_fixtures.AttachmentCatalogTests.put
    prepare = catalog_fixtures.AttachmentCatalogTests.prepare
    policy = PolicyIndexTests.policy

    def test_local_remote_facets_and_old_aliases_use_same_policy(self):
        self.put('local.png', size=5); self.put('local.js', size=7)
        self.prepare()
        key = self.remote.add('remote.js', alias='old/remote.js', tags=['kept'])
        self.remote.add('remote.png', size=11)
        page = self.catalog.listing(limit=1)
        self.assertEqual(page['total'], 2)
        self.assertEqual(page['summary']['bytes'], 16)
        self.policy(['.js'])
        self.remote.settings['allowed_extensions'] = ['.js']
        result = self.catalog.listing()
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['summary']['by_source']['remote']['files'], 1)
        with self.assertRaises(ConflictError):
            self.catalog.listing(limit=1, cursor=page['cursor'])
        self.policy([]); self.remote.settings['allowed_extensions'] = []
        self.assertEqual(self.catalog.listing()['total'], 0)
        self.assertEqual(self.catalog.resolve('old/remote.js'), ['old/remote.js'])
        with self.remote.db() as db:
            self.assertEqual(db.execute('SELECT tags FROM assets WHERE id=?', (key,)).fetchone()[0], '["kept"]')


class PolicyRemoteTests(unittest.TestCase):
    setUp = remote_fixtures.RemoteAttachmentTests.setUp
    tearDown = remote_fixtures.RemoteAttachmentTests.tearDown
    manager_for_config = remote_fixtures.RemoteAttachmentTests.manager_for_config
    put = remote_fixtures.RemoteAttachmentTests.put

    def policy(self, extensions):
        settings = self.manager._settings()
        settings['allowed_extensions'] = extensions
        self.manager.save(str(self.root), settings, settings['revision'])

    def test_cached_scan_reclassifies_without_downloading_or_changing_identity(self):
        source = remote_fixtures.SOURCE
        self.policy(list(DEFAULT_EXTENSIONS))
        self.dav.files.update({'image.png': b'image', 'source.js': b'code'})
        self.manager.scan(str(self.root), source, _incremental=True)
        old = self.manager.stat(str(self.root), '_attachments/_remote/' + source + '/source.js')
        self.assertEqual(old['state'], 'excluded')
        files = Files(self.config); catalog = AttachmentCatalog(files.attachments, self.manager)
        self.assertEqual(catalog.listing()['total'], 1)
        self.dav.calls.clear(); self.policy(['.js'])
        self.assertEqual(catalog.listing()['total'], 0)
        self.assertEqual(self.manager.list(str(self.root))['total'], 0)
        self.manager.scan(str(self.root), source, _incremental=True)
        self.assertEqual(catalog.listing()['items'][0]['asset_id'], old['asset_id'])
        self.assertFalse(any(method in {'GET', 'PROPFIND'} for method, url in self.dav.calls))
        self.policy([])
        self.assertEqual(catalog.listing()['total'], 0)
        self.assertEqual(self.manager.stat(str(self.root), asset_id=old['asset_id'])['size'], 4)

    def test_pending_upload_retains_bytes_and_completed_receipts_replay(self):
        source = remote_fixtures.SOURCE
        self.policy(['.png'])
        with self.assertRaises(ValueError):
            self.manager.queue_upload(str(self.root), source, 'bad.js', b'code')
        job = self.manager.queue_upload(str(self.root), source, 'ok.png', b'body', idempotency_key='one', fingerprint='same')
        self.policy([]); self.manager.process_pending()
        result = next(j for j in self.manager.jobs(str(self.root)) if j['id'] == job['id'])
        self.assertEqual(result['error'], 'attachment_file_type_not_allowed')
        self.assertEqual(self.manager._state('outbox', job['id'] + '.blob').read_bytes(), b'body')
        self.assertFalse(any(method == 'PUT' for method, _ in self.dav.calls))
        self.policy(['.png'])
        self.manager.job(str(self.root), job['id'], 'resume')
        self.manager.process_pending()
        self.assertEqual(next(j for j in self.manager.jobs(str(self.root)) if j['id'] == job['id'])['state'], 'completed')
        self.policy([])
        replay = self.manager.queue_upload(str(self.root), source, 'ok.png', '/never/read', idempotency_key='one', fingerprint='same')
        self.assertEqual(replay['state'], 'completed')

    def test_migration_intersects_policy_and_never_moves_source_resources(self):
        self.put('_attachments/a.png'); self.put('_attachments/b.pdf'); self.put('_attachments/script.js')
        self.policy(['.pdf', '.js'])
        plan = self.manager.migration_plan(str(self.root), remote_fixtures.SOURCE)
        self.assertEqual(len(plan['items']), 0)  # Script owns its project directory.
        self.assertTrue((self.root / '_attachments/a.png').is_file())
        self.assertFalse(any(method == 'PUT' for method, _ in self.dav.calls))


class PolicyApiTests(unittest.TestCase):
    setUp = api_fixtures.AttachmentStorageApiTests.setUp
    request = api_fixtures.AttachmentStorageApiTests.request
    settings = api_fixtures.AttachmentStorageApiTests.settings
    configure = api_fixtures.AttachmentStorageApiTests.configure
    put = api_fixtures.AttachmentStorageApiTests.put
    wait = workspace_fixtures.AttachmentWorkspaceTests.wait

    def policy(self, value):
        current = self.settings()
        payload = {key: current[key] for key in ['root','revision','storages','default_storage_id','cache_limit_bytes','outbox_limit_bytes']}
        for storage in payload['storages']:
            for key in ['password_saved', 'connection']:
                storage.pop(key, None)
        if value is not None:
            payload['allowed_extensions'] = value
        return self.request('PUT', '/api/attachments/storage', json=payload).json()

    def test_settings_defaults_legacy_preservation_validation_and_status(self):
        self.assertEqual(self.settings()['allowed_extensions'], list(DEFAULT_EXTENSIONS))
        saved = self.policy([' PNG ', '.png', 'TAR.GZ'])
        self.assertEqual(saved['allowed_extensions'], ['.png', '.tar.gz'])
        self.assertEqual(self.policy(None)['allowed_extensions'], saved['allowed_extensions'])
        status = self.request('GET', '/api/attachments/status', params={'root': str(self.root)}).json()
        self.assertEqual(status['allowed_extensions'], saved['allowed_extensions'])
        self.assertEqual(self.policy([])['allowed_extensions'], [])
        self.assertIn('.unitypackage', self.settings()['default_extensions'])
        with self.assertRaises(ValueError):
            save_settings(self.remote, {'root': str(self.root), 'storages': [], 'allowed_extensions': ['*.js']})
        # General workspace revision stays valid for existing references/transfers.
        self.assertEqual(self.config.data['revision'], self.client.get('/api/session').json()['config']['revision'])

    def test_local_upload_types_and_ordinary_import_compound_duplicates(self):
        self.policy(['.tar.gz'])
        params = {'root': str(self.root), 'name': 'code.js', 'central': 'true'}
        self.request('POST', '/api/upload', params=params, content=b'code', expected=400)
        params.update(central='false', folder='')
        imported = self.request('POST', '/api/upload', params=params, content=b'code').json()
        self.assertEqual((self.root / imported['path']).read_bytes(), b'code')
        params.update(name='Archive.TAR.GZ', central='true', unique='true')
        first = self.request('POST', '/api/upload', params=params, content=b'one').json()
        second = self.request('POST', '/api/upload', params=params, content=b'two').json()
        self.assertTrue(second['path'].endswith(' (2).TAR.GZ'))
        self.assertEqual((self.root / first['path']).read_bytes(), b'one')

    def test_remote_ordinary_import_and_attachment_upload_remain_distinct(self):
        self.configure(default=remote_fixtures.SOURCE); self.policy([])
        params = {'root': str(self.root), 'name': 'code.js', 'central': 'true'}
        self.request('POST', '/api/upload', params=params, content=b'code', expected=400)
        params['central'] = 'false'
        imported = self.request('POST', '/api/upload', params=params, content=b'code').json()
        self.remote.process_pending()
        job = next(j for j in self.remote.jobs(str(self.root)) if j['id'] == imported['id'])
        self.assertEqual(job['state'], 'completed')
        self.assertEqual(self.remote.list(str(self.root))['total'], 0)

    def test_groups_and_ai_projection_follow_type_changes_without_reindexing(self):
        self.put('a.png', b'image'); self.put('b.pdf', b'pdf')
        self.app.state.runtime.files.attachments.refresh()
        groups = self.app.state.attachment_groups
        group = groups.update(str(self.root), 'create', {'name': 'All', 'search_enabled': True, 'rules': {'formats':['png','pdf']}})['groups'][0]
        search = self.app.state.file_operations.asset_search
        before = search.scope()['scope_revision']
        self.assertEqual(len(search.snapshot()), 2)
        self.policy(['.pdf'])
        self.assertNotEqual(search.scope()['scope_revision'], before)
        documents = search.snapshot()
        self.assertEqual([r['name'] for d in documents for r in d['files']], ['b.pdf'])
        page = self.request('GET', '/api/attachments', params={'root': str(self.root), 'group_id': group['id']}).json()
        self.assertEqual(page['result_summary']['files'], 1)
        self.policy([])
        self.assertEqual(search.snapshot(), [])

    def test_local_migration_policy_changes_block_execution_and_keep_rollback_available(self):
        self.put('loose/a.png', b'image')
        manager = self.app.state.attachment_migrations
        planned = self.wait(manager.create(str(self.root), '_attachments'))
        self.assertEqual(planned['summary']['files'], 1)
        self.policy([])
        blocked = self.wait(manager.action(planned['id'], 'execute', str(self.root), confirm=True))
        self.assertIn(blocked['state'], {'rolled_back','conflict'}, blocked)
        self.assertIn('file types changed', blocked['error'])
        self.assertTrue((self.root / 'loose/a.png').is_file())
        self.policy(['.png'])
        planned = self.wait(manager.create(str(self.root), '_attachments'))
        completed = self.wait(manager.action(planned['id'], 'execute', str(self.root), confirm=True))
        self.assertEqual(completed['state'], 'completed', completed)
        self.policy([])
        restored = self.wait(manager.action(planned['id'], 'rollback', str(self.root), confirm=True))
        self.assertEqual(restored['state'], 'rolled_back', restored)
        self.assertTrue((self.root / 'loose/a.png').is_file())

    def test_mcp_upload_rejects_types_and_replays_completed_operation(self):
        token = self.app.state.mcp_access.configure('local', enabled=True, write=True)['token']
        def upload(name, operation):
            response = self.client.post(f'http://127.0.0.1:{self.config.data.get("port",18080)}/mcp', headers={
                'Accept': 'application/json, text/event-stream', 'Authorization': 'Bearer ' + token}, json={
                'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'vault_files_update','arguments':{
                    'workspace_revision':self.config.data['revision'],'operation_id':operation,
                    'request':{'action':'upload','source':'base64','name':name,'data_base64':base64.b64encode(b'body').decode(),
                               'sha256':hashlib.sha256(b'body').hexdigest()}}}})
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()['result']
        self.assertTrue(upload('code.js', 'a' * 32)['isError'])
        first = upload('image.png', 'b' * 32)
        self.assertFalse(first.get('isError'), first)
        self.policy([])
        replay = upload('image.png', 'b' * 32)
        self.assertFalse(replay.get('isError'), replay)
        self.assertEqual(replay['structuredContent']['path'], first['structuredContent']['path'])
