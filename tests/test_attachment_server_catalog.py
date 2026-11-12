"""Server membership catalog: app-only mode, import, promote-to-cache, durable retry."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from tests.test_remote_attachments import FakeDAV, SOURCE, SECRET
from vault_rag.attachment_catalog import AttachmentCatalog
from vault_rag.attachment_index import AttachmentIndex
from vault_rag.attachment_server_catalog import import_filesystem, sync_catalog
from vault_rag.local_state import Files, LocalConfig
from vault_rag.remote_attachments import RemoteAttachments


class ServerCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'vault'
        self.root.mkdir()
        self.config = LocalConfig(Path(self.temp.name) / 'config')
        self.config.save({'root': str(self.root), 'attachment_folder': '_attachments'})
        with patch.object(RemoteAttachments, '_loop', return_value=None):
            self.remote = RemoteAttachments(self.config)
        self.addCleanup(self.remote.stop)
        self.dav = FakeDAV()
        self.remote.transports[SOURCE] = httpx.MockTransport(self.dav)
        self.remote.save(str(self.root), {'allowed_extensions': ['.png', '.mp4', '.bin'], 'sources': [
            {'id': SOURCE, 'base_url': 'https://fixture.invalid/', 'username': 'leafloom',
             'upload_directory': 'Incoming', 'metadata_directory': 'Incoming/LeafLoomCatalog/v1'}]})
        self.remote.set_credentials(SOURCE, 'leafloom', SECRET)
        self.remote.poll_connections()

    def test_import_sets_app_only_and_poll_skips_discovery(self):
        self.dav.files['Incoming/a.bin'] = b'alpha'
        self.dav.files['Incoming/nested/b.png'] = b'beta'
        result = import_filesystem(self.remote, str(self.root), SOURCE, force_app_only=True)
        self.assertEqual(result['imported'], 2)
        self.assertEqual(result['membership_mode'], 'app_only')
        source = self.remote._source(SOURCE, str(self.root))
        self.assertEqual(source['membership_mode'], 'app_only')
        members = [name for name in self.dav.files if '/attachments/v1/members/' in name]
        self.assertEqual(len(members), 2)
        with patch.object(self.remote, 'start_scan') as discovery, patch.object(self.remote, 'start_catalog_sync') as catalog:
            self.remote.auto_scans.clear()
            self.remote.poll_scans()
            for state in self.remote.auto_scans.values():
                state['next_scan_at'] = 0
            with patch('vault_rag.remote_attachments.time.time', return_value=time.time() + 10_000):
                self.remote.poll_scans()
            discovery.assert_not_called()
            catalog.assert_called_once()

    def test_pull_projects_members_without_directory_discovery(self):
        self.dav.files['Incoming/only-on-server.bin'] = b'bytes'
        import_filesystem(self.remote, str(self.root), SOURCE, force_app_only=True)
        peer_config = LocalConfig(Path(self.temp.name) / 'peer')
        peer_config.save({'root': str(self.root), 'attachment_folder': '_attachments'})
        with patch.object(RemoteAttachments, '_loop', return_value=None):
            other = RemoteAttachments(peer_config)
        self.addCleanup(other.stop)
        other.transports[SOURCE] = httpx.MockTransport(self.dav)
        other.save(str(self.root), {'allowed_extensions': ['.png', '.mp4', '.bin'], 'sources': [
            {'id': SOURCE, 'base_url': 'https://fixture.invalid/', 'username': 'leafloom',
             'upload_directory': 'Incoming', 'metadata_directory': 'Incoming/LeafLoomCatalog/v1',
             'membership_mode': 'app_only'}]})
        other.set_credentials(SOURCE, 'leafloom', SECRET)
        other.poll_connections()
        pulled = sync_catalog(other, str(self.root), SOURCE, publish_local=False)
        self.assertGreaterEqual(pulled['members'], 1)
        with other.lock, other._db(str(self.root)) as db:
            rows = db.execute("SELECT path FROM assets WHERE source_id=? AND state='ready'", (SOURCE,)).fetchall()
        self.assertTrue(any(row[0].endswith('only-on-server.bin') for row in rows))

    def test_promote_drops_local_original_keeps_membership(self):
        folder = self.root / '_attachments' / 'deadbeefdeadbeefdeadbeefdeadbeef'
        folder.mkdir(parents=True)
        local = folder / 'clip.mp4'
        local.write_bytes(b'video-bytes')
        logical = '_attachments/deadbeefdeadbeefdeadbeefdeadbeef/clip.mp4'
        job = self.remote.queue_upload(str(self.root), SOURCE, logical, local, attachment=True)
        self.assertEqual(job['state'], 'queued')
        self.assertTrue(local.is_file())
        self.remote.process_pending()
        with self.remote.lock, self.remote._db(str(self.root)) as db:
            asset = db.execute('SELECT state FROM assets WHERE id=?', (job['asset_id'],)).fetchone()
            self.assertEqual(asset[0], 'ready')
            cache = db.execute('SELECT file FROM cache WHERE asset_id=?', (job['asset_id'],)).fetchone()
            self.assertIsNone(cache)
        self.assertFalse(local.is_file())
        members = [name for name in self.dav.files if '/attachments/v1/members/' in name]
        self.assertTrue(members)

    def test_promote_keeps_note_image_as_vault_cache(self):
        folder = self.root / '_attachments' / 'cafecafecafecafecafecafecafecafe'
        folder.mkdir(parents=True)
        local = folder / 'clip.png'
        local.write_bytes(b'png-bytes-for-note')
        logical = '_attachments/cafecafecafecafecafecafecafecafe/clip.png'
        job = self.remote.queue_upload(str(self.root), SOURCE, logical, local, attachment=True)
        self.remote.process_pending()
        with self.remote.lock, self.remote._db(str(self.root)) as db:
            asset = db.execute('SELECT state FROM assets WHERE id=?', (job['asset_id'],)).fetchone()
            self.assertEqual(asset[0], 'ready')
            cache = db.execute('SELECT file FROM cache WHERE asset_id=?', (job['asset_id'],)).fetchone()
            self.assertIsNotNone(cache)
            self.assertTrue(str(cache[0]).startswith('vault:'))
        self.assertTrue(local.is_file())
        self.assertEqual(local.read_bytes(), b'png-bytes-for-note')

    def test_unreachable_upload_stays_retryable(self):
        local = self.root / '_attachments' / 'x' / 'a.bin'
        local.parent.mkdir(parents=True)
        local.write_bytes(b'data')
        logical = '_attachments/x/a.bin'
        job = self.remote.queue_upload(str(self.root), SOURCE, logical, local, attachment=True)
        self.dav.offline = True
        self.remote.process_pending()
        with self.remote.lock, self.remote._db(str(self.root)) as db:
            payload = json.loads(db.execute('SELECT payload FROM jobs WHERE id=?', (job['id'],)).fetchone()[0])
        self.assertEqual(payload['state'], 'waiting_for_connection')
        self.assertIn('next_retry_at', payload)
        self.assertNotEqual(payload['state'], 'failed')

    def test_import_while_paused_exposes_progress_phase(self):
        self.dav.files['Incoming/a.bin'] = b'alpha'
        self.dav.files['Incoming/nested/b.png'] = b'beta'
        with self.remote.config.lock, self.remote.lock:
            settings = self.remote._settings(str(self.root))
            settings['sources'][0]['scan_paused'] = True
            self.remote.save(str(self.root), settings, settings['revision'])
        started = self.remote.start_catalog_import(str(self.root), SOURCE)
        self.assertEqual(started['phase'], 'import')
        self.assertEqual(self.remote.connections[SOURCE]['phase'], 'import')
        self.assertEqual(self.remote.connections[SOURCE]['state'], 'scanning')
        deadline = time.time() + 5
        while time.time() < deadline:
            status = self.remote.status(str(self.root))['sources'][0]
            if status.get('membership_mode') == 'app_only' and status['connection'].get('scan_state') == 'completed':
                break
            time.sleep(0.05)
        else:
            self.fail('catalog import did not finish while directory checks were paused')
        source = self.remote._source(SOURCE, str(self.root))
        self.assertTrue(source.get('scan_paused'))
        self.assertEqual(source.get('membership_mode'), 'app_only')
        status = self.remote.status(str(self.root))['sources'][0]
        self.assertEqual(status['connection']['scan_paused'], True)
        self.assertGreaterEqual(status['connection'].get('scan_scanned', 0), 2)

    def test_listing_prefers_remote_pending_over_local_duplicate(self):
        local = self.root / '_attachments' / 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' / 'shot.png'
        local.parent.mkdir(parents=True)
        local.write_bytes(b'png')
        logical = '_attachments/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/shot.png'
        index = AttachmentIndex(Files(self.config))
        index.refresh()
        index.apply([logical])
        job = self.remote.queue_upload(str(self.root), SOURCE, logical, local, attachment=True)
        catalog = AttachmentCatalog(index, self.remote)
        page = catalog.listing(source='all', limit=50)
        paths = [item['path'] for item in page['items']]
        self.assertIn(logical, paths)
        self.assertEqual(paths.count(logical), 1)
        match = next(item for item in page['items'] if item['path'] == logical)
        self.assertEqual(match['storage_id'], SOURCE)
        self.assertEqual(match['state'], 'pending')
        self.assertEqual(match['asset_id'], job['asset_id'])


if __name__ == '__main__':
    unittest.main()
