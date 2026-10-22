"""The unified catalog pages metadata without opening attachment bodies."""
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from vault_rag.attachment_catalog import AttachmentCatalog
from vault_rag.local_state import ConflictError, Files, LocalConfig


SOURCE_A = 'a' * 32
SOURCE_B = 'b' * 32


class Manifest:
    """Small durable schema fixture, deliberately no remote listing method."""
    def __init__(self, files):
        self.files = files
        self.lock = threading.RLock()
        self.settings = {'revision': 'one', 'sources': [
            {'id': SOURCE_A, 'name': 'NAS', 'enabled': True},
            {'id': SOURCE_B, 'name': 'Archive', 'enabled': False}]}

    def manifest_path(self, root):
        assert root == str(self.files.config.root)
        return self.files.state_path('remote-attachments', 'manifest.sqlite')

    def _settings(self, root):
        assert root == str(self.files.config.root)
        return dict(self.settings)

    def initialize(self):
        path = self.manifest_path(str(self.files.config.root))
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.executescript('''
                CREATE TABLE assets(id TEXT PRIMARY KEY,source_id TEXT,path TEXT,name TEXT,size INTEGER,
                    mtime_ns INTEGER,mime TEXT,mtime TEXT,etag TEXT,state TEXT,description TEXT,tags TEXT,
                    category TEXT,metadata_revision TEXT,UNIQUE(source_id,path));
                CREATE TABLE aliases(path TEXT PRIMARY KEY,asset_id TEXT REFERENCES assets(id));
                CREATE TABLE cache(asset_id TEXT PRIMARY KEY,file TEXT,size INTEGER,etag TEXT,mtime TEXT);
                CREATE TABLE ranges(asset_id TEXT,start INTEGER,end INTEGER,object_size INTEGER,etag TEXT,mtime TEXT,
                    PRIMARY KEY(asset_id,start,end));
                CREATE TABLE catalog_state(id INTEGER PRIMARY KEY,generation INTEGER);
                INSERT INTO catalog_state VALUES(1,0);
            ''')
            for table in ('assets', 'aliases', 'cache', 'ranges'):
                for action in ('INSERT', 'UPDATE', 'DELETE'):
                    db.execute(f'CREATE TRIGGER gen_{table}_{action} AFTER {action} ON {table} '
                               'BEGIN UPDATE catalog_state SET generation=generation+1; END')

    @contextmanager
    def db(self):
        with sqlite3.connect(self.manifest_path(str(self.files.config.root))) as db:
            yield db

    def add(self, path, *, source=SOURCE_A, alias=None, size=10, mtime=123000000000,
            tags=(), category='', description='', state='ready', mime='image/png'):
        key = uuid.uuid4().hex
        with self.db() as db:
            db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (key, source, path, Path(path).name, size, mtime, mime, str(mtime), 'v1',
                 state, description, json.dumps(tags), category, uuid.uuid4().hex))
            if alias is not None:
                db.execute('INSERT INTO aliases VALUES(?,?)', (alias, key))
        return key


class AttachmentCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.root = self.home / 'vault'
        self.root.mkdir()
        self.config = LocalConfig(self.home / 'state')
        self.config.save({'root': str(self.root)})
        self.files = Files(self.config)
        self.local = self.files.attachments
        self.remote = Manifest(self.files)
        self.catalog = AttachmentCatalog(self.local, self.remote)
        self.files.attachments = self.catalog

    def tearDown(self):
        self.temp.cleanup()

    def put(self, path, size=1, mtime=100000000000):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'x' * size)
        os.utime(target, ns=(mtime, mtime))
        return target

    def prepare(self):
        self.local.refresh()
        self.remote.initialize()

    def test_local_fast_path_and_transparent_delegation(self):
        self.put('local.png')
        with patch.object(self.remote, 'manifest_path', side_effect=AssertionError('created manifest')):
            self.assertEqual(self.catalog.listing()['total'], 1)
            self.assertEqual(self.catalog.listing()['summary']['by_source'], {'local': {'files': 1, 'bytes': 1}, 'remote': {'files': 0, 'bytes': 0}})
            self.assertEqual(self.catalog.resolve('local.png'), ['local.png'])
            self.assertEqual(self.catalog.listing(tags=['missing'])['total'], 0)
            empty = self.catalog.listing(source='remote')
            self.assertEqual(empty['items'], [])
            self.assertEqual(empty['summary'], {'files': 0, 'bytes': 0, 'kinds': {}, 'by_source': {'local': {'files': 0, 'bytes': 0}, 'remote': {'files': 0, 'bytes': 0}}})
        self.catalog.generation = 50
        self.assertEqual(self.local.generation, 50)
        self.assertIs(self.catalog.lock, self.local.lock)
        self.put('second.png')
        self.catalog.apply(['second.png'])
        self.assertEqual(self.catalog.listing()['total'], 2)

    def test_global_keyset_sorts_and_duplicate_paths_across_sources(self):
        self.put('same.png', 4, 800000000000)
        self.put('z.png', 1, 200000000000)
        self.prepare()
        self.remote.add('incoming/x.png', alias='same.png', size=8)
        # The remote alias supersedes the old local index entry.
        self.remote.add('same.png', source=SOURCE_B, size=2, mtime=900000000000)
        self.remote.add('incoming/a.png', alias='a.png', size=7)
        for sort, field in [('path', 'path'), ('name', 'name'), ('modified', 'mtime'), ('size', 'size')]:
            for order in ('asc', 'desc'):
                with self.subTest(sort=sort, order=order):
                    all_items, cursor = [], ''
                    while True:
                        page = self.catalog.listing(limit=1, sort=sort, order=order, cursor=cursor)
                        all_items.extend(page['items'])
                        cursor = page['cursor']
                        if not cursor:
                            break
                    self.assertEqual(len(all_items), 4)
                    self.assertEqual(len({(i['storage_id'], i['path']) for i in all_items}), 4)
                    values = [i[field] for i in all_items]
                    self.assertEqual(values, sorted(values, reverse=order == 'desc'))
        page = self.catalog.listing(limit=1)
        next_page = self.catalog.listing(limit=1, after=page['next_cursor'])
        self.assertNotEqual(page['items'][0]['asset_id'], next_page['items'][0]['asset_id'])

    def test_same_logical_path_source_tiebreaker_and_alias_deduplication(self):
        self.prepare()
        first = self.remote.add('one.png', alias='b.png')
        with self.remote.db() as db:
            db.execute('INSERT INTO aliases VALUES(?,?)', ('a.png', first))
        # No alias fallback uses the source namespace, keeping unrelated paths distinct.
        self.remote.add('a.png', source=SOURCE_B)
        page = self.catalog.listing(limit=1)
        self.assertEqual(page['total'], 2)
        self.assertEqual(page['items'][0]['path'], '_attachments/_remote/' + SOURCE_B + '/a.png')
        page2 = self.catalog.listing(cursor=page['cursor'])
        self.assertEqual([i['path'] for i in page2['items']], ['a.png'])
        self.assertFalse(page['items'][0]['source_enabled'])

    def test_local_metadata_filters_remote_search_and_cache_states(self):
        self.put('local.png', 3)
        self.prepare()
        self.remote.add('local.png', source='local', tags=['hero', 'red'], category='People', description='portrait')
        complete = self.remote.add('complete.png', alias='complete.png', tags=['hero'], description='100% unique')
        partial = self.remote.add('partial.png', alias='partial.png', tags=['hero', 'red'], category='People')
        with self.remote.db() as db:
            db.execute('INSERT INTO cache VALUES(?,?,?,?,?)', (complete, 'opaque', 10, 'v1', '123000000000'))
            db.execute('INSERT INTO ranges VALUES(?,?,?,?,?,?)', (partial, 0, 2, 10, 'v1', '123000000000'))
        result = self.catalog.listing(tags=['hero', 'red'], category='People')
        self.assertEqual({i['path'] for i in result['items']}, {'local.png', 'partial.png'})
        self.assertEqual(result['summary']['files'], 3)
        self.assertEqual(result['summary']['bytes'], 23)
        self.assertEqual(result['summary']['by_source'], {'local': {'files': 1, 'bytes': 3}, 'remote': {'files': 2, 'bytes': 20}})
        self.assertEqual(self.catalog.listing(query='portrait')['total'], 1)
        self.assertEqual(self.catalog.listing(query='%')['total'], 1)
        self.assertEqual(self.catalog.listing(storage_id='local')['total'], 1)
        self.assertEqual(self.catalog.listing(storage_id=str(uuid.UUID(SOURCE_A)))['total'], 2)
        states = {i['path']: i['cache_state'] for i in self.catalog.listing()['items']}
        self.assertEqual(states, {'local.png': 'complete', 'complete.png': 'complete', 'partial.png': 'partial'})

    def test_migration_pending_local_wins_then_ready_shadows_stale_index(self):
        self.put('old.png', 3)
        self.prepare()
        key = self.remote.add('Incoming/object.png', alias='old.png', size=12, state='migration_pending')
        self.assertEqual([(i['storage_id'], i['size']) for i in self.catalog.listing()['items']], [('local', 3)])
        with self.remote.db() as db:
            db.execute("UPDATE assets SET state='ready' WHERE id=?", (key,))
        self.assertEqual([(i['storage_id'], i['size']) for i in self.catalog.listing()['items']], [(SOURCE_A, 12)])

    def test_missing_remote_is_hidden_without_reviving_its_stale_local_alias(self):
        self.put('old.png', 5)
        self.put('keep.png', 7)
        self.prepare()
        missing = self.remote.add('Incoming/old.png', alias='old.png', size=9, tags=['keep-metadata'])
        self.remote.add('Incoming/active.png', alias='active.png', size=11)
        cursor = self.catalog.listing(limit=1)['cursor']
        with self.remote.db() as db:
            db.execute("UPDATE assets SET state='missing' WHERE id=?", (missing,))
        result = self.catalog.listing()
        self.assertEqual({item['path'] for item in result['items']}, {'keep.png', 'active.png'})
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['summary']['by_source'], {'local': {'files': 1, 'bytes': 7}, 'remote': {'files': 1, 'bytes': 11}})
        self.assertEqual(self.catalog.listing(source='local')['total'], 1)
        self.assertEqual(self.catalog.listing(source='remote')['summary']['bytes'], 11)
        self.assertEqual(self.catalog.listing(tags=['keep-metadata'])['total'], 0)
        with self.remote.db() as db:
            self.assertEqual(json.loads(db.execute('SELECT tags FROM assets WHERE id=?', (missing,)).fetchone()[0]), ['keep-metadata'])
            self.assertEqual(db.execute("SELECT asset_id FROM aliases WHERE path='old.png'").fetchone()[0], missing)
        with self.assertRaises(ConflictError):
            self.catalog.listing(cursor=cursor)

    def test_excluded_remote_keeps_metadata_and_alias_without_local_ghost_or_stats(self):
        self.put('old.png', 5)
        self.put('keep.png', 7)
        self.prepare()
        excluded = self.remote.add('Incoming/old.png', alias='old.png', size=9,
                                   tags=['kept-tag'], description='Kept for old references', state='excluded')
        self.remote.add('Incoming/active.png', alias='active.png', size=11)
        result = self.catalog.listing()
        self.assertEqual({item['path'] for item in result['items']}, {'keep.png', 'active.png'})
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['summary'], {'files': 2, 'bytes': 18, 'kinds': {'image': 2},
            'by_source': {'local': {'files': 1, 'bytes': 7}, 'remote': {'files': 1, 'bytes': 11}}})
        self.assertEqual(self.catalog.listing(source='local')['total'], 1)
        self.assertEqual(self.catalog.listing(source='remote')['summary']['bytes'], 11)
        self.assertEqual(self.catalog.listing(tags=['kept-tag'])['total'], 0)
        with self.remote.db() as db:
            row = db.execute('SELECT tags,description FROM assets WHERE id=?', (excluded,)).fetchone()
            self.assertEqual(json.loads(row[0]), ['kept-tag'])
            self.assertEqual(row[1], 'Kept for old references')
            self.assertEqual(db.execute("SELECT asset_id FROM aliases WHERE path='old.png'").fetchone()[0], excluded)

    def test_source_filters_scope_pages_stats_kind_facets_and_cursor(self):
        self.put('local.png', 3)
        self.put('local.mp4', 5)
        self.prepare()
        self.remote.add('one.png', size=4)
        self.remote.add('two.pdf', size=7, mime='application/pdf')
        self.remote.add('archive.mp4', source=SOURCE_B, size=9, mime='video/mp4')
        self.assertEqual(self.catalog.listing()['summary']['files'], 5)
        self.assertEqual(self.catalog.listing()['summary']['by_source'], {'local': {'files': 2, 'bytes': 8}, 'remote': {'files': 3, 'bytes': 20}})
        local = self.catalog.listing(source='local')
        self.assertEqual(local['total'], 2)
        self.assertEqual(local['summary'], {'files': 2, 'bytes': 8, 'kinds': {'image': 1, 'video': 1}, 'by_source': {'local': {'files': 2, 'bytes': 8}, 'remote': {'files': 0, 'bytes': 0}}})
        self.assertTrue(all(item['storage_id'] == 'local' for item in local['items']))
        first = self.catalog.listing(source='remote', limit=1)
        self.assertEqual(first['total'], 3)
        self.assertEqual(first['summary'], {'files': 3, 'bytes': 20, 'kinds': {'image': 1, 'pdf': 1, 'video': 1}, 'by_source': {'local': {'files': 0, 'bytes': 0}, 'remote': {'files': 3, 'bytes': 20}}})
        items, cursor = first['items'], first['cursor']
        while cursor:
            page = self.catalog.listing(source='remote', cursor=cursor, limit=1)
            self.assertEqual(page['summary'], first['summary'])
            items.extend(page['items'])
            cursor = page['cursor']
        self.assertEqual(len({item['asset_id'] for item in items}), 3)
        self.assertTrue(all(item['source'] == 'remote' for item in items))
        self.assertEqual({item['storage_id'] for item in first['storages']}, {SOURCE_A, SOURCE_B})
        selected = self.catalog.listing(source='remote', storage_id=SOURCE_A, kind='image')
        self.assertEqual(selected['total'], 1)
        self.assertEqual(selected['summary'], {'files': 2, 'bytes': 11, 'kinds': {'image': 1, 'pdf': 1}, 'by_source': {'local': {'files': 0, 'bytes': 0}, 'remote': {'files': 2, 'bytes': 11}}})
        self.assertEqual(self.catalog.listing(source='local', storage_id=SOURCE_A)['summary']['files'], 0)
        with self.assertRaises(ConflictError):
            self.catalog.listing(source='local', cursor=first['cursor'])
        with self.assertRaises(ValueError):
            self.catalog.listing(source='arbitrary')

    def test_cursor_invalidated_by_metadata_alias_settings_and_root(self):
        self.prepare()
        key = self.remote.add('a.png', alias='a.png')
        self.remote.add('b.png', alias='b.png')
        for change in ('metadata', 'alias', 'settings', 'local'):
            cursor = self.catalog.listing(limit=1)['cursor']
            if change == 'metadata':
                with self.remote.db() as db:
                    db.execute("UPDATE assets SET description='new' WHERE id=?", (key,))
            elif change == 'alias':
                with self.remote.db() as db:
                    db.execute('INSERT INTO aliases VALUES(?,?)', ('alternate.png', key))
            elif change == 'settings':
                self.remote.settings['revision'] = 'two'
            else:
                self.put('c.png')
                self.catalog.apply(['c.png'])
            with self.assertRaises(ConflictError):
                self.catalog.listing(cursor=cursor)
        cursor = self.catalog.listing(limit=1)['cursor']
        other = self.home / 'other'
        other.mkdir()
        self.config.save({'root': str(other)})
        with self.assertRaises(ConflictError):
            self.catalog.listing(cursor=cursor)

    def test_resolve_local_then_relative_alias_unique_basename_and_literals(self):
        self.put('local/same.png')
        self.prepare()
        self.remote.add('object.png', alias='notes/remote.png')
        self.remote.add('local-competitor.png', alias='remote/same.png')
        self.remote.add('literal.png', alias='assets/100%25#raw.png')
        self.remote.add('a/duplicate.png')
        self.remote.add('b/duplicate.png', source=SOURCE_B)
        self.assertEqual(self.catalog.resolve('same.png'), ['local/same.png'])
        self.assertEqual(self.catalog.resolve('remote.png', 'notes/doc.md'), ['notes/remote.png'])
        self.assertEqual(self.catalog.resolve('../notes/remote.png', 'other/doc.md'), ['notes/remote.png'])
        self.assertEqual(self.catalog.resolve('100%25#raw.png'), ['assets/100%25#raw.png'])
        self.assertEqual(self.catalog.resolve('100%23raw.png'), [])
        self.assertEqual(self.catalog.resolve('duplicate.png'), [])
        self.assertEqual(self.catalog.resolve('../../escape.png'), [])
        self.assertEqual(self.catalog.resolve('https://example.com/remote.png'), [])

    def test_listing_and_resolving_never_open_attachment_contents(self):
        self.put('local.png')
        self.prepare()
        self.remote.add('very-large.mp4', size=6 * 1024**3)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('attachment body read')):
            result = self.catalog.listing(limit=1, sort='size', order='desc')
            self.assertEqual(result['items'][0]['size'], 6 * 1024**3)
            self.assertEqual(self.catalog.resolve('very-large.mp4'), [
                '_attachments/_remote/' + SOURCE_A + '/very-large.mp4'])
        with self.assertRaises(ValueError):
            self.catalog.listing(tags='hero')
        with self.assertRaises(ConflictError):
            self.catalog.listing(cursor='ac1.invalid')


if __name__ == '__main__':
    unittest.main()
