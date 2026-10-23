"""Opt-in asset search boundaries and independent, cross-client NAS scope events."""
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from tests import test_attachment_groups as group_tests
from tests import test_file_tools as file_tests
from tests import test_asset_workflows as workflow_tests
from vault_rag.local_state import ConflictError


class GroupSearchScopeSyncTests(unittest.TestCase):
    setUp = group_tests.AttachmentGroupTests.setUp
    tearDown = group_tests.AttachmentGroupTests.tearDown
    create_client = group_tests.AttachmentGroupTests.create_client
    scan = group_tests.AttachmentGroupTests.scan
    initialize = group_tests.AttachmentGroupTests.initialize
    manager = group_tests.AttachmentGroupTests.manager

    def test_default_off_legacy_edit_preserves_choice_and_transaction_rolls_back(self):
        groups = self.manager()
        group = groups.update(self.root,'create',{'name':'Materials'})['groups'][0]
        self.assertFalse(group['search_enabled'])
        enabled = groups.update(self.root,'update',{'id':group['id'],'revision':group['revision'],
            'search_scope_revision':group['search_scope_revision'],'search_enabled':True})['groups'][0]
        legacy = groups.update(self.root,'update',{'id':enabled['id'],'revision':enabled['revision'],'name':'Renamed'})['groups'][0]
        self.assertTrue(legacy['search_enabled'])
        with self.assertRaises(ConflictError):
            groups.update(self.root,'update',{'id':legacy['id'],'revision':legacy['revision'],'name':'Must roll back',
                'search_enabled':False,'search_scope_revision':group['search_scope_revision']})
        self.assertEqual(groups.listing(self.root)['groups'][0]['name'],'Renamed')
        with groups._db(self.root) as db:
            for row in db.execute('SELECT payload FROM events'):
                self.assertNotIn('search_enabled',json.loads(row[0]))
        groups.update(self.root,'delete',{'id':legacy['id'],'revision':legacy['revision']})
        fresh = groups.update(self.root,'create',{'name':'Renamed'})['groups'][0]
        self.assertFalse(fresh['search_enabled'])
        self.assertEqual(groups.search_scope(self.root)['group_ids'],[])

    def test_two_clients_offline_conflict_and_explicit_resolution(self):
        first = self.manager()
        self.dav.files['Materials/rock.png']=b'original'
        self.scan()
        group = first.update(self.root,'create',{'name':'Materials','rules':{'formats':['png']},'search_enabled':True})['groups'][0]
        first.sync(self.root)
        self.assertEqual(first.listing(self.root)['pending'],0)
        config2,remote2,library2 = self.create_client('scope-two','b'*32)
        self.scan(remote2)
        second = self.manager(remote2,library2)
        root2 = str(config2.root)
        second.sync(root2)
        restored = second.listing(root2)['groups'][0]
        self.assertTrue(restored['search_enabled'])
        self.assertEqual(second.search_scope(root2)['group_ids'],[group['id']])
        self.dav.offline=True
        one = first.update(self.root,'update',{'id':group['id'],'revision':group['revision'],
            'search_scope_revision':group['search_scope_revision'],'search_enabled':False})['groups'][0]
        self.assertEqual(first.search_scope(self.root)['group_ids'],[])
        with self.assertRaises(Exception):first.sync(self.root)
        self.assertGreater(first.listing(self.root)['pending'],0)
        second.update(root2,'update',{'id':restored['id'],'revision':restored['revision'],
            'search_scope_revision':restored['search_scope_revision'],'search_enabled':True})
        self.dav.offline=False
        self.remote._reset_connection(self.root,'a'*32)
        first.sync(self.root);second.sync(root2);first.sync(self.root)
        conflict = first.listing(self.root)['groups'][0]
        self.assertEqual(len(conflict['search_scope_conflicts']),2)
        self.assertFalse(conflict['search_enabled'])
        self.assertEqual(first.search_scope(self.root)['scope_state'],'scope_conflict')
        with self.assertRaises(ConflictError):
            first.update(self.root,'update',{'id':group['id'],'revision':conflict['revision'],
                'resolve':True,'search_enabled':True,'search_scope_revision':conflict['search_scope_revision']})
        resolved = first.update(self.root,'update',{'id':group['id'],'revision':conflict['revision'],'resolve':True,
            'resolve_search_scope':True,'search_enabled':True,'search_scope_revision':conflict['search_scope_revision']})['groups'][0]
        first.sync(self.root);second.sync(root2)
        self.assertEqual(second.listing(root2)['groups'][0]['search_scope_conflicts'],[])
        self.assertTrue(second.listing(root2)['groups'][0]['search_enabled'])
        scope_paths = [p for p in self.dav.files if '/search-scope/events/' in p]
        self.assertTrue(scope_paths)
        for path in self.dav.files:
            if '/attachment-groups/events/' in path:
                self.assertNotIn('search_enabled',json.loads(self.dav.files[path])['payload'])
        self.assertEqual(self.dav.files['Materials/rock.png'],b'original')
        self.assertFalse(any(method in {'DELETE','MOVE','COPY'} for method,_ in self.dav.calls))


class AssetSearchScopeTests(unittest.TestCase):
    setUp = file_tests.FileToolsTests.setUp
    rpc = file_tests.FileToolsTests.rpc
    call = file_tests.FileToolsTests.call
    put = file_tests.FileToolsTests.put
    prepare = workflow_tests.AssetWorkflowTests.prepare

    def toggle(self, group, enabled):
        return self.app.state.attachment_groups.update(str(self.root),'update',{
            'id':group['id'],'revision':group['revision'],'search_enabled':enabled,
            'search_scope_revision':group['search_scope_revision']})['groups'][0]

    def test_no_scope_skips_catalog_and_model_and_discards_legacy_projection(self):
        files = self.app.state.file_operations
        self.put('Notes/reference.png',b'ordinary note attachment')
        directory = files.asset_search.directory();directory.mkdir(parents=True)
        for name in ('catalog.json','current.json'):(directory/name).write_text('{"documents":["old full corpus"]}')
        with patch.object(files.asset_search,'_attachments') as catalog, patch.object(files.runtime.rag,'request') as model:
            value = self.call('search_assets',query='reference')
            self.assertEqual(value['results'],[])
            self.assertEqual(value['degraded_reason'],'scope_not_configured')
            catalog.assert_not_called();model.assert_not_called()
        self.assertFalse((directory/'current.json').exists())
        self.assertFalse((directory/'catalog.json').exists())
        self.assertEqual((self.root/'Notes/reference.png').read_bytes(),b'ordinary note attachment')

    def test_union_overlap_manual_exclusion_and_group_filter_cannot_expand(self):
        self.prepare()
        files = self.files
        groups = files.attachment_groups
        first = groups.listing(str(self.root))['groups'][0]
        self.put('Notes/reference.png',b'note image')
        files.runtime.files.attachments.refresh()
        ignored = groups.update(str(self.root),'create',{'name':'Notes','rules':{'directories':['Notes']}})['groups'][-1]
        second = groups.update(str(self.root),'create',{'name':'Also rocks','search_enabled':True,
            'rules':{'formats':['fbx']}})['groups'][-1]
        all_results = self.call('search_assets',query='rock',mode='keyword')['results']
        self.assertEqual(len(all_results),1)
        self.assertEqual(self.call('search_assets',query='reference',mode='keyword')['results'],[])
        self.assertEqual(self.call('search_assets',query='rock',mode='keyword',group_id=ignored['id'])['results'],[])
        # Remove it from one selected group; the other group's membership still contributes.
        changed = groups.update(str(self.root),'members',{'id':first['id'],'revision':first['revision'],
            'mode':'exclude','paths':['Models/rock.fbx']})['groups'][0]
        self.assertEqual(len(self.call('search_assets',query='rock',mode='keyword')['results']),1)
        self.toggle(second,False)
        self.assertEqual(self.call('search_assets',query='rock',mode='keyword')['results'],[])
        self.assertTrue(any(r['path']=='Notes/reference.png' for r in files.asset_search._attachments()))

    def test_disabling_rejects_old_details_and_preview(self):
        result = self.prepare()
        groups = self.files.attachment_groups
        group = groups.listing(str(self.root))['groups'][0]
        self.toggle(group,False)
        self.call('asset_details',result_id=result['result_id'],error='not_found')
        self.call('asset_preview',result_id=result['result_id'],expected_revision=result['revision'],error='not_found')
        self.assertEqual(self.call('search_assets',query='苔藓')['degraded_reason'],'scope_not_configured')

    def test_scope_change_during_semantic_query_returns_no_stale_results(self):
        from types import SimpleNamespace
        result = self.prepare()
        search = self.files.asset_search
        group = self.files.attachment_groups.listing(str(self.root))['groups'][0]
        scope = search.scope()
        (search.directory()/'current.json').write_text(json.dumps({'scope_version':1,
            'scope_revision':scope['scope_revision'],'fingerprint':'fake'}))
        def query(*args,**kwargs):
            self.toggle(group,False)
            return [{'id':result['result_id'],'similarity':0.9}]
        with patch.object(self.files.runtime,'model',SimpleNamespace(ready=True,fingerprint='fake')), \
             patch.object(search,'settings',return_value={'enabled':True,'revision':'fake'}), \
             patch.object(search,'schedule'), \
             patch.object(self.files.runtime.rag,'request',side_effect=query):
            self.call('search_assets',query='苔藓',error='write_conflict')

    def test_scope_change_during_build_cannot_publish_old_entries(self):
        from types import SimpleNamespace
        self.prepare()
        search = self.files.asset_search
        group = self.files.attachment_groups.listing(str(self.root))['groups'][0]
        def batch(*args,**kwargs):self.toggle(group,False)
        with patch.object(self.files.runtime,'model',SimpleNamespace(ready=True,fingerprint='fake')),\
             patch.object(search,'settings',return_value={'enabled':True,'revision':'fake'}),\
             patch.object(self.files.runtime.rag,'request',side_effect=batch):
            search.schedule(search.snapshot())
            for thread in list(search.threads):thread.join(timeout=3)
        self.assertFalse((search.directory()/'current.json').exists())
