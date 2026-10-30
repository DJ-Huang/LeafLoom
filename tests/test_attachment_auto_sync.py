"""Automatic discovery is driven with a clock; no live services or credentials."""
import tempfile
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch
import httpx
from tests.test_remote_attachments import FakeDAV, SOURCE, SECRET
from vault_rag.local_state import LocalConfig
from vault_rag.remote_attachments import RemoteAttachments
from vault_rag.attachment_scan_policy import SCAN_INTERVAL
from vault_rag.attachment_storage_routes import save_settings, public_settings

class AutoSyncTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()/'vault';self.root.mkdir()
        config=LocalConfig(Path(self.temp.name)/'config');config.save({'root':str(self.root)})
        with patch.object(RemoteAttachments,'_loop',return_value=None):self.remote=RemoteAttachments(config)
        self.addCleanup(self.remote.stop)
        self.dav=FakeDAV();self.remote.transports[SOURCE]=httpx.MockTransport(self.dav)
        self.remote.save(str(self.root),{'sources':[{'id':SOURCE,'base_url':'https://fixture.invalid/','username':'leafloom'}]})
        self.remote.set_credentials(SOURCE,'leafloom',SECRET)
        self.remote.poll_connections()
        # Most scheduler tests start after the startup grace; dedicated tests cover launch deferral.
        self.remote.poll_scans()
        for state in self.remote.auto_scans.values():state['next_scan_at']=0

    def finish(self):
        for thread in list(self.remote.scan_threads.values()):thread.join(3)
        self.assertFalse(any(thread.is_alive() for thread in self.remote.scan_threads.values()))

    def test_initial_scan_then_regular_interval_and_metadata_callback(self):
        self.dav.files['Incoming/a.bin']=b'a';callback=Mock();self.remote.on_scan_completed=callback
        self.remote.poll_scans();self.finish();self.remote.poll_scans()
        callback.assert_called_once_with(str(self.root),SOURCE)
        state=public_settings(self.remote,str(self.root))['storages'][0]['connection']
        self.assertEqual(state['next_scan_at']-state['last_success_at'],SCAN_INTERVAL)
        with patch.object(self.remote,'start_scan') as start:self.remote.poll_scans();start.assert_not_called()
        with patch('vault_rag.remote_attachments.time.time',return_value=state['next_scan_at']+1),patch.object(self.remote,'start_scan') as start:
            self.remote.poll_scans();start.assert_called_once()
        self.remote.auto_scans.clear()
        self.assertEqual(public_settings(self.remote,str(self.root))['storages'][0]['connection']['last_success_at'],state['last_success_at'])

    def test_auth_pause_and_disabled_source_do_not_start_scans(self):
        self.dav.failure_status=401;self.remote.test(str(self.root),SOURCE)
        with patch.object(self.remote,'start_scan') as start:self.remote.poll_scans();start.assert_not_called()
        self.remote.set_credentials(SOURCE,'leafloom',SECRET)
        values=self.remote._settings();values['sources'][0]['enabled']=False
        self.remote.save(str(self.root),values)
        with patch.object(self.remote,'start_scan') as start:self.remote.poll_scans();start.assert_not_called()

    def test_automatic_scans_are_serial_and_manual_scan_is_reused(self):
        self.remote.scan_threads[('fictional','other')]=Mock(is_alive=Mock(return_value=True))
        with patch.object(self.remote,'start_scan') as start:self.remote.poll_scans();start.assert_not_called()
        self.remote.scan_threads.clear()
        self.remote.poll_scans();self.finish()
        self.assertEqual(self.remote.status()['sources'][0]['connection']['scan_state'],'completed')

    def test_reconnection_wakes_scan_before_regular_interval(self):
        self.remote.poll_scans();self.finish();self.remote.poll_scans()
        self.remote._connection_failed(str(self.root),SOURCE,__import__('vault_rag.remote_webdav',fromlist=['RemoteStorageError']).RemoteStorageError('connection_unavailable','unreachable'))
        self.remote.poll_scans()
        self.remote._connection_ready(str(self.root),SOURCE)
        with patch.object(self.remote,'start_scan') as start:self.remote.poll_scans();start.assert_called_once()

    def test_generic_api_preserves_hidden_settings_and_infers_smb(self):
        current=public_settings(self.remote,str(self.root))
        saved=save_settings(self.remote,{'root':str(self.root),'revision':current['revision'],'storages':[{'storage_id':SOURCE,'base_url':'smb://nas/share/Folder','username':'user'}]})
        item=saved['storages'][0]
        self.assertEqual((item['type'],item['base_url'],item['remote_root']),('smb','smb://nas/share/','Folder'))
        self.assertNotIn('password',item)
        again=save_settings(self.remote,{'root':str(self.root),'revision':saved['revision'],'storages':[{'storage_id':SOURCE,'base_url':item['base_url'],'username':'user'}]})
        self.assertEqual(again['storages'][0]['remote_root'],'Folder')

    def test_connection_recovery_notifies_metadata_once_and_rejects_old_context(self):
        callback=Mock();self.remote.on_connection_ready=callback
        original=self.remote._provider(SOURCE,str(self.root)).connection_context
        self.remote._connection_ready(str(self.root),SOURCE);callback.assert_not_called()
        from vault_rag.remote_webdav import RemoteStorageError
        self.remote._connection_failed(str(self.root),SOURCE,RemoteStorageError('connection_unavailable','unreachable'))
        self.remote._connection_ready(str(self.root),SOURCE)
        callback.assert_called_once_with(str(self.root),SOURCE)
        self.remote._connection_ready(str(self.root),SOURCE);self.assertEqual(callback.call_count,1)
        self.remote.set_credentials(SOURCE,'leafloom',SECRET,revision='replacement')
        self.remote._connection_ready(str(self.root),SOURCE,context=original);self.assertEqual(callback.call_count,1)
