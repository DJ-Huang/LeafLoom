"""Attachment discovery never consumes file contents or changes original paths."""
import concurrent.futures
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vault_rag.catalog import Catalog
from vault_rag.local_state import Files, LocalConfig, ConflictError


class AttachmentIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.root = self.home / 'vault'
        self.root.mkdir()
        self.config = LocalConfig(self.home / 'state')
        self.config.save({'root': str(self.root)})
        self.files = Files(self.config)
        self.index = self.files.attachments

    def tearDown(self):
        self.temp.cleanup()

    def put(self, rel, data=b'asset'):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_scattered_links_single_discovery_and_persistent_restart(self):
        self.put('a/image (1).png')
        self.put('b/image (1).png')
        self.put('notes/doc.md', b'![[image (1).png]]')
        calls = []
        walk = Files.walk
        def counted(files, *args, **kwargs):
            calls.append(1)
            yield from walk(files, *args, **kwargs)
        with patch.object(Files, 'walk', counted), patch.object(Path, 'read_bytes', side_effect=AssertionError('contents read')):
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: self.files.resolve('image%20(1).png#section|label', 'notes/doc.md'), range(20)))
            self.assertTrue(all(result == ['a/image (1).png', 'b/image (1).png'] for result in results))
            self.assertEqual(self.files.resolve('missing.png'), [])
        self.assertEqual(len(calls), 1)
        with patch.object(Files, 'walk', side_effect=AssertionError('restart scan')):
            self.assertEqual(Files(self.config).resolve('image (1).png'), results[0])

    def test_lazy_nonempty_catalog_and_path_precedence(self):
        self.put('notes/a.md', b'# A')
        self.put('elsewhere/photo.png')
        catalog = Catalog(self.files, lazy=True)
        catalog.apply(['notes/a.md'])
        self.assertTrue(catalog.entries)
        self.assertEqual(catalog.resolve('photo.png', 'notes/a.md'), ['elsewhere/photo.png'])
        self.put('notes/photo.png')
        self.index.apply(['notes/photo.png'])
        self.assertEqual(catalog.resolve('photo.png', 'notes/a.md'), ['notes/photo.png'])
        self.assertEqual(catalog.resolve('../elsewhere/photo.png', 'notes/a.md'), ['elsewhere/photo.png'])

    def test_sparse_large_asset_hidden_paths_and_html(self):
        large = self.put('media/large.mp4')
        with large.open('wb') as stream:
            stream.truncate(3 * 1024**3)
        self.put('.hidden/secret.png')
        self.put('node_modules/private.png')
        self.put('website/index.html', b'<html>Hello</html>')
        self.put('website/style.css')
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('binary read')):
            page = self.index.listing()
        self.assertEqual(page['total'], 3)
        self.assertEqual(page['items'][0]['size'], 3 * 1024**3)
        self.assertEqual((self.root / 'website/index.html').read_bytes(), b'<html>Hello</html>')
        self.assertEqual(self.files.resolve('secret.png'), [])

    def test_incremental_subtrees_rename_delete_and_restart_events(self):
        self.index.refresh()
        self.put('new/deep/a.png')
        self.put('new/b.pdf')
        self.index.apply(['new'])
        self.assertEqual(self.index.listing()['total'], 2)
        (self.root / 'new').rename(self.root / 'moved')
        self.index.apply(['new', 'moved'])
        self.assertEqual(self.files.resolve('a.png'), ['moved/deep/a.png'])
        (self.root / 'moved/deep/a.png').unlink()
        # A new process may receive a watcher event before first index lookup.
        restarted = Files(self.config).attachments
        restarted.apply(['moved/deep/a.png'])
        self.assertEqual(restarted.resolve('a.png'), [])
        self.assertEqual(restarted.listing()['total'], 1)

    def test_pagination_search_limits_and_literal_wildcards(self):
        for name in ('a.png', 'b.png', 'c.png', '100%.png', 'x_y.png'):
            self.put('assets/' + name)
        first = self.index.listing(limit=2)
        second = self.index.listing(after=first['next_cursor'], limit=2)
        third = self.index.listing(after=second['next_cursor'], limit=2)
        paths = [r['path'] for page in (first, second, third) for r in page['items']]
        self.assertEqual(paths, sorted(set(paths)))
        self.assertEqual(len(paths), 5)
        self.assertIsNone(third['next_cursor'])
        self.assertEqual(self.index.listing(query='%')['total'], 1)
        self.assertEqual(self.index.listing(query='_')['total'], 1)
        self.assertEqual(len(self.index.listing(limit=0)['items']), 1)

    def test_failed_refresh_keeps_previous_generation(self):
        self.put('before.png')
        self.index.refresh()
        (self.root / 'before.png').unlink()
        self.put('after.png')
        walk = Files.walk
        def interrupted(files, *args, **kwargs):
            yield from walk(files, *args, **kwargs)
            raise PermissionError('fixture traversal denied')
        with patch.object(Files, 'walk', interrupted):
            with self.assertRaises(PermissionError):
                self.index.refresh()
        with sqlite3.connect(self.root / '.vault-rag/attachments.sqlite') as db:
            self.assertEqual(db.execute('SELECT path FROM assets').fetchall(), [('before.png',)])
        self.index.refresh()
        self.assertEqual(self.files.resolve('after.png'), ['after.png'])

    def test_root_switch_during_scan_rolls_back(self):
        self.put('first.png')
        other = self.home / 'other'
        other.mkdir()
        walk = Files.walk
        def switched(files, *args, **kwargs):
            yield from walk(files, *args, **kwargs)
            self.config.save({'root': str(other)})
        with patch.object(Files, 'walk', switched):
            with self.assertRaises(ConflictError):
                self.index.refresh()
        self.assertIsNone(self.index.ready_root)
        self.assertEqual(self.index.listing()['total'], 0)

    @unittest.skipIf(os.name == 'nt', 'POSIX symlink fixture')
    def test_symlink_substitution_and_database_link_rejected(self):
        asset = self.put('safe/a.png')
        self.index.refresh()
        outside = self.home / 'outside.png'
        outside.write_bytes(b'secret')
        asset.unlink()
        asset.symlink_to(outside)
        self.assertEqual(self.files.resolve('a.png'), [])
        self.index.apply(['safe/a.png'])
        self.assertEqual(self.index.listing()['total'], 0)
        dbpath = self.root / '.vault-rag/attachments.sqlite'
        dbpath.unlink()
        dbpath.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.index.refresh()
        self.assertEqual(outside.read_bytes(), b'secret')

    def test_root_event_reconciles_removed_files(self):
        self.put('old.png')
        self.index.refresh()
        (self.root / 'old.png').unlink()
        self.put('new.png')
        self.index.apply([''])
        self.assertEqual([r['path'] for r in self.index.listing()['items']], ['new.png'])

    def test_http_auth_refresh_and_media_preserved(self):
        from starlette.testclient import TestClient
        from vault_rag.web_server import create_app
        self.put('assets/a.png', b'0123456789')
        app = create_app(self.config, start_background=False)
        with TestClient(app, base_url=app.state.websites.ui_origin) as client:
            self.assertEqual(client.get('/api/attachments').status_code, 401)
            client.get('/')
            session = client.get('/api/session').json()
            self.assertEqual(client.get('/api/attachments/status').json()['state'], 'uninitialized')
            self.assertEqual(client.get('/api/attachments').status_code, 409)
            self.assertEqual(client.post('/api/attachments/initialize', json={'root':str(self.root)}, headers={'X-Vault-CSRF':session['csrf']}).status_code,200)
            app.state.attachment_index_jobs.thread.join(5)
            response = client.get('/api/attachments?limit=1')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['items'][0]['path'], 'assets/a.png')
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(client.post('/api/attachments/refresh').status_code, 403)
            self.put('new/b.pdf')
            self.assertEqual(client.post('/api/attachments/refresh', json={'root':str(self.root)}, headers={'X-Vault-CSRF': session['csrf']}).status_code, 200)
            app.state.attachment_index_jobs.thread.join(5)
            self.assertEqual(client.get('/api/attachments').json()['total'], 2)
            media = client.get('/api/media?path=assets/a.png', headers={'Range': 'bytes=2-5'})
            self.assertEqual(media.status_code, 206)
            self.assertEqual(media.content, b'2345')

    def test_encoded_literal_percent_and_anchor_characters(self):
        self.put('assets/photo%20.png')
        self.put('assets/photo#1.png')
        self.assertEqual(self.files.resolve('photo%2520.png'), ['assets/photo%20.png'])
        self.assertEqual(self.files.resolve('photo%231.png'), ['assets/photo#1.png'])

    def test_explicit_refresh_resolves_after_full_catalog_snapshot(self):
        self.put('a.md', b'# A')
        catalog = Catalog(self.files)
        catalog.scan()
        self.put('new/scattered.png')
        self.index.refresh()
        self.assertEqual(catalog.resolve('scattered.png'), ['new/scattered.png'])

    def test_listing_revalidates_cached_paths_and_reports_scan_time(self):
        self.put('visible.png')
        self.index.refresh()
        with sqlite3.connect(self.root / '.vault-rag/attachments.sqlite') as db:
            db.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?)",
                       ('../outside.png', '../outside.png', 'outside.png', 'outside.png', 1, 0, 'image/png', 1))
        result = self.index.listing()
        self.assertEqual([r['path'] for r in result['items']], ['visible.png'])
        self.assertIsInstance(result['last_scanned_at'], float)

    def test_optional_index_failure_does_not_block_note_updates_or_resolution(self):
        self.put('notes/a.md', b'# Before')
        self.put('assets/image.png')
        catalog = Catalog(self.files)
        catalog.scan()
        self.index.refresh()
        with sqlite3.connect(self.root / '.vault-rag/attachments.sqlite') as db:
            db.execute('PRAGMA user_version=99')
        self.put('notes/a.md', b'# After')
        with self.assertLogs('vault_rag.catalog', level='WARNING'):
            catalog.apply(['notes/a.md'])
        self.assertEqual(catalog.entries['notes/a.md']['text'], '# After')
        with self.assertLogs('vault_rag.local_state', level='WARNING'):
            self.assertEqual(self.files.resolve('image.png'), ['assets/image.png'])
        with sqlite3.connect(self.root / '.vault-rag/attachments.sqlite') as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 99)

    def test_future_schema_is_preserved(self):
        self.index.refresh()
        path = self.root / '.vault-rag/attachments.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('PRAGMA user_version=99')
        with self.assertRaises(ValueError):
            self.index.refresh()
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 99)


if __name__ == '__main__':
    unittest.main()
