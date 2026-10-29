"""Synthetic metadata, no user files or external network."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch
from tests import test_asset_library as library_fixtures
from vault_rag.attachment_groups import AttachmentGroups, encoded, matches
from vault_rag.attachment_presentation import AttachmentPresentation
from vault_rag.attachment_catalog import AttachmentCatalog
from vault_rag.local_state import ConflictError


class AttachmentGroupTests(unittest.TestCase):
    setUp = library_fixtures.AssetLibraryTests.setUp
    tearDown = library_fixtures.AssetLibraryTests.tearDown
    create_client = library_fixtures.AssetLibraryTests.create_client
    scan = library_fixtures.AssetLibraryTests.scan
    initialize = library_fixtures.AssetLibraryTests.initialize

    def manager(self, remote=None, library=None):
        with patch.object(AttachmentGroups, '_loop', return_value=None):
            manager = AttachmentGroups(remote or self.remote, library or self.library)
        self.addCleanup(manager.stop)
        return manager

    def test_manual_rules_and_exclusions_are_independent_of_categories(self):
        manager=self.manager()
        self.dav.files['Artwork/cat.png']=b'not opened'
        self.scan()
        item=self.remote.list(self.root)['items'][0]
        created=manager.update(self.root,'create',{'name':'Pictures','rules':{'formats':['png','jpg'],'tags':['animal','portrait']}})['groups'][0]
        included=manager.update(self.root,'members',{'id':created['id'],'revision':created['revision'],'mode':'include','paths':[item['path']]})['groups'][0]
        _,device=manager.snapshot(self.root)
        identity=manager.identity(self.root,item,device)
        self.assertTrue(matches(included,item,identity))
        excluded=manager.update(self.root,'members',{'id':included['id'],'revision':included['revision'],'mode':'exclude','paths':[item['path']]})['groups'][0]
        self.assertFalse(matches(excluded,{**item,'tags':['animal']},identity))
        reset=manager.update(self.root,'members',{'id':excluded['id'],'revision':excluded['revision'],'mode':'reset','paths':[item['path']]})['groups'][0]
        self.assertTrue(matches(reset,{**item,'tags':['portrait']},identity))
        self.assertFalse(matches(reset,{**item,'tags':['other']},identity))
        self.assertEqual(self.remote.stat(self.root,asset_id=item['asset_id'])['category'],'')
        with self.assertRaises(ConflictError):manager.update(self.root,'update',{'id':created['id'],'revision':created['revision'],'name':'stale'})

    def test_sync_restore_conflict_resolution_and_no_original_mutation(self):
        manager=self.manager()
        self.dav.files['Artwork/cat.png']=b'original'
        self.scan()
        item=self.remote.list(self.root)['items'][0]
        group=manager.update(self.root,'create',{'name':'Saved'})['groups'][0]
        group=manager.update(self.root,'members',{'id':group['id'],'revision':group['revision'],'paths':[item['path']],'mode':'include'})['groups'][0]
        self.dav.offline=True
        with self.assertRaises(Exception):manager.sync(self.root)
        self.assertGreater(manager.listing(self.root)['pending'],0)
        self.dav.offline=False;self.remote._reset_connection(self.root,'a'*32);manager.sync(self.root)
        self.assertEqual(manager.listing(self.root)['pending'],0)
        config2,remote2,library2=self.create_client('two','b'*32)
        self.scan(remote2);second=self.manager(remote2,library2);root2=str(config2.root)
        second.sync(root2)
        restored=second.listing(root2)['groups'][0]
        self.assertEqual(restored['name'],'Saved')
        other=remote2.list(root2)['items'][0]
        _,device=second.snapshot(root2)
        self.assertTrue(matches(restored,other,second.identity(root2,other,device)))
        manager.update(self.root,'update',{'id':group['id'],'revision':group['revision'],'name':'One'})
        second.update(root2,'update',{'id':restored['id'],'revision':restored['revision'],'name':'Two'})
        manager.sync(self.root);second.sync(root2);manager.sync(self.root)
        conflict=manager.listing(self.root)['groups'][0]
        self.assertEqual(len(conflict['conflicts']),2)
        with self.assertRaises(ConflictError):manager.update(self.root,'update',{'id':group['id'],'revision':conflict['revision'],'name':'Lost'})
        resolved=manager.update(self.root,'update',{'id':group['id'],'revision':conflict['revision'],'name':'Resolved','resolve':True})['groups'][0]
        self.assertEqual(resolved['conflicts'],[])
        manager.sync(self.root);second.sync(root2)
        self.assertEqual(second.listing(root2)['groups'][0]['name'],'Resolved')
        self.assertEqual(self.dav.files['Artwork/cat.png'],b'original')
        self.assertFalse(any(method in {'DELETE','MOVE','COPY'} for method,_ in self.dav.calls))

    def test_catalog_inherits_source_metadata_searches_groups_and_keeps_personal(self):
        self.dav.files['Packages/Fictional.unitypackage']=b'original'
        self.scan();self.initialize()
        candidate=self.library.listing(self.root)['items'][0]
        self.library.update(self.root,'official',{'product_id':'123456','official':{'title':'Fictional','publisher':'Studio','summary_zh':'森林场景','categories_zh':['场景'],'keywords':['forest'],'keywords_zh':['森林']}})
        self.library.update(self.root,'bind',{'asset_id':candidate['files'][0]['asset_id'],'product_id':'123456'},expected_revision=candidate['revision'])
        manager=self.manager();presentation=AttachmentPresentation(manager,self.library)
        files=self.remote._files();catalog=AttachmentCatalog(files.attachments,self.remote);catalog.presentation=presentation
        group=manager.update(self.root,'create',{'name':'Forest','rules':{'tags':['森林']}})['groups'][0]
        page=catalog.listing(query='森林',group_id=group['id'],limit=1)
        self.assertEqual(page['total'],1);self.assertEqual(page['summary']['files'],1)
        empty=catalog.listing(query='no-such-attachment',group_id=group['id'])
        self.assertEqual(empty['result_summary']['files'],0)
        self.assertEqual(empty['summary']['files'],1)
        item=page['items'][0];self.assertEqual(item['category'],'场景');self.assertIn('森林',item['tags'])
        detail=presentation.enrich(self.root,self.remote.stat(self.root,asset_id=item['asset_id']))
        self.assertEqual(detail['personal_metadata']['description'],'')
        current=self.remote.stat(self.root,asset_id=item['asset_id'])
        self.remote.update_metadata(self.root,'',{'description':'我的描述','category':'收藏','tags':['私人']},current['metadata_revision'],asset_id=item['asset_id'])
        page=catalog.listing(group_id=group['id'])
        self.assertEqual(page['items'][0]['description'],'我的描述')
        self.assertEqual(page['items'][0]['category'],'收藏')
        self.assertIn('私人',page['items'][0]['tags'])
        with self.assertRaises(ConflictError):catalog.listing(group_id=group['id'],cursor='ac1.invalid')

    def test_local_only_restart_and_delete_preserve_files(self):
        manager=self.manager();path=self.remote._files().config.path_for('_attachments/local.png')
        path.parent.mkdir();path.write_bytes(b'original')
        group=manager.update(self.root,'create',{'name':'Local'})['groups'][0]
        group=manager.update(self.root,'members',{'id':group['id'],'revision':group['revision'],'mode':'include','paths':['_attachments/local.png']})['groups'][0]
        restored=self.manager().listing(self.root)['groups'][0]
        self.assertEqual(restored['included'],group['included'])
        manager.update(self.root,'delete',{'id':group['id'],'revision':group['revision']})
        self.assertEqual(manager.listing(self.root)['groups'],[])
        self.assertEqual(path.read_bytes(),b'original')

    def test_explicit_local_rename_keeps_membership_and_updates_saved_locator(self):
        manager=self.manager();path=self.remote._files().config.path_for('_attachments/local.png')
        path.parent.mkdir();path.write_bytes(b'original')
        group=manager.update(self.root,'create',{'name':'Local'})['groups'][0]
        group=manager.update(self.root,'members',{'id':group['id'],'revision':group['revision'],'mode':'include','paths':['_attachments/local.png']})['groups'][0]
        renamed=path.with_name('renamed.png');path.rename(renamed)
        self.remote.sync_local_paths(self.root,{'_attachments/local.png':'_attachments/renamed.png'})
        current=manager.listing(self.root)['groups'][0]
        self.assertEqual(current['included'][0]['uid'],group['included'][0]['uid'])
        self.assertEqual(current['included'][0]['path'],'_attachments/renamed.png')
        self.assertEqual(renamed.read_bytes(),b'original')

    def test_reject_cross_entity_and_cyclic_event_history(self):
        manager=self.manager();group=manager.update(self.root,'create',{'name':'Valid'})['groups'][0]
        with manager.lock,manager._db(self.root) as db:
            old=json.loads(db.execute('SELECT data FROM events').fetchone()[0]);a=copy.deepcopy(old);a['id']='c'*32;a['parents']=['d'*32]
            manager._accept(db,a,encoded(a),True)
            b=copy.deepcopy(a);b['id']='d'*32;b['parents']=['c'*32]
            with self.assertRaises(ValueError):manager._accept(db,b,encoded(b),True)
