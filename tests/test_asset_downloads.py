"""Synthetic download streams only: no live services or user credentials."""
import hashlib
import errno
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

import httpx

from vault_rag.asset_downloads import AssetDownloads
from vault_rag.local_state import ConflictError, LocalConfig
from vault_rag.remote_attachments import RemoteAttachments


SOURCE = 'c' * 32
SECRET = 'synthetic-download-password'
MIB = 1024 * 1024
DATE = 'Wed, 21 Oct 2026 00:00:00 GMT'


class Stream(httpx.SyncByteStream):
    def __init__(self, dav, request, start, length):
        self.dav, self.request, self.start, self.length = dav, request, start, length

    def __iter__(self):
        remaining, sent = self.length, 0
        while remaining:
            size = min(64 * 1024, remaining)
            yield b'a' * size
            remaining -= size
            sent += size
            if self.dav.on_chunk:
                self.dav.on_chunk()
            if self.dav.interrupt and sent >= MIB:
                self.dav.interrupt = False
                raise httpx.ReadError('private diagnostic ' + SECRET, request=self.request)


class DAV:
    def __init__(self, size=2 * MIB + 7):
        self.size, self.etag = size, '"version-1"'
        self.calls, self.interrupt = [], False
        self.on_chunk, self.on_final_head = None, None
        self.range_behavior, self.heads = 'normal', 0

    def __call__(self, request):
        self.calls.append((request.method, dict(request.headers)))
        assert request.headers.get('cookie') is None
        assert request.headers.get('authorization', '').startswith('Basic ')
        headers = {'content-length': str(self.size), 'etag': self.etag,
                   'last-modified': DATE, 'content-type': 'application/zip'}
        if request.method == 'HEAD':
            self.heads += 1
            if self.on_final_head and self.heads > 1:
                self.on_final_head()
                headers['etag'] = self.etag
            return httpx.Response(200, headers=headers)
        assert request.method == 'GET'
        start = 0
        status = 200
        if 'range' in request.headers and self.range_behavior != 'ignore':
            start = int(request.headers['range'].removeprefix('bytes=').split('-')[0])
            status = 206
            headers['content-length'] = str(self.size - start)
            headers['content-range'] = f'bytes {start}-{self.size - 1}/{self.size}'
            if self.range_behavior == 'invalid':
                headers['content-range'] = 'bytes 0-1/2'
        return httpx.Response(status, headers=headers, stream=Stream(self, request, start, self.size - start))


def digest(size):
    value = hashlib.sha256()
    while size:
        count = min(MIB, size)
        value.update(b'a' * count)
        size -= count
    return value.hexdigest()


class AssetDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.root = self.home / 'vault'
        self.root.mkdir()
        self.config = LocalConfig(self.home / 'state')
        self.config.save({'root': str(self.root)})
        with patch.object(RemoteAttachments, '_loop', return_value=None):
            self.remote = RemoteAttachments(self.config)
        self.remote.save(str(self.root), {'sources': [{'id': SOURCE, 'name': 'Synthetic', 'base_url': 'http://127.0.0.1:10000/',
                         'username': 'fixture', 'allow_private_http': True}], 'default_source': SOURCE})
        self.remote.set_credentials(SOURCE, '', SECRET, revision='fixture-revision')
        self.dav = DAV()
        self.remote.transports[SOURCE] = httpx.MockTransport(self.dav)
        self.now, self.free = 1000.0, 100 * MIB
        self.services = []
        self.downloads = self.service()
        self.asset = self.register()

    def tearDown(self):
        for service in self.services:
            service.stop()
        self.remote.stop()
        self.temp.cleanup()

    def service(self):
        service = AssetDownloads(self.remote, max_bytes=20 * MIB, reserve_bytes=5 * MIB,
                                 clock=lambda: self.now, disk_usage=lambda _: SimpleNamespace(free=self.free), start_worker=False)
        self.services.append(service)
        return service

    def register(self, **changes):
        value = {'path': 'Packages/large.zip', 'size': self.dav.size, 'etag': self.dav.etag,
                 'mtime': DATE, 'mime': 'application/zip', **changes}
        with self.remote.lock, self.remote._db(str(self.root)) as db:
            return self.remote._upsert(db, SOURCE, value, sha256=changes.get('sha256', ''))

    def prepare(self, **kwargs):
        return self.downloads.prepare(str(self.root), self.asset, **kwargs)

    def status(self, job):
        return self.downloads.status(str(self.root), job['job_id'])

    def next(self):
        self.now += 64
        self.remote._reset_connection(str(self.root), SOURCE)
        self.downloads.process_pending(str(self.root))

    def test_streamed_verified_download_is_separate_from_preview_cache_and_has_opaque_handle(self):
        self.dav.size = 8 * MIB + 7
        self.asset = self.register(sha256=digest(self.dav.size))
        job = self.prepare()
        self.assertEqual(job['state'], 'queued')
        self.downloads.process_pending(str(self.root))
        ready = self.status(job)
        self.assertEqual(ready['state'], 'ready', ready)
        self.assertEqual(ready['downloaded'], self.dav.size)
        self.assertEqual(ready['sha256'], digest(self.dav.size))
        file = self.downloads.resolve_handle(str(self.root), ready['handle'])
        self.assertEqual(file.parent.name, 'asset-downloads')
        with file.open('rb') as content:
            self.assertEqual(hashlib.file_digest(content, 'sha256').hexdigest(), ready['sha256'])
        self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        with self.remote._db(str(self.root)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM cache').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM ranges').fetchone()[0], 0)
        self.assertFalse({'path', 'source_id', 'snapshot', 'owner'} & ready.keys())
        self.assertNotIn(SECRET, json.dumps(self.downloads.list(str(self.root))))
        self.assertEqual(self.downloads.usage(str(self.root))['used_bytes'], self.dav.size)

    def test_strong_etag_resume_survives_restart_and_waits_for_restored_credentials(self):
        self.dav.interrupt = True
        job = self.prepare()
        self.downloads.process_pending(str(self.root))
        paused = self.status(job)
        self.assertEqual(paused['state'], 'paused', paused)
        self.assertGreaterEqual(paused['downloaded'], MIB)
        self.now += 7 * 24 * 3600
        self.assertEqual(self.downloads.usage(str(self.root))['used_bytes'], paused['downloaded'])
        self.assertEqual(self.status(job)['state'], 'paused')
        self.free = self.dav.size - paused['downloaded'] + 5 * MIB
        self.downloads.stop()
        self.downloads = self.service()
        self.remote.credentials.clear()
        before = len(self.dav.calls)
        self.next()
        self.assertEqual(self.status(job)['error'], 'credentials_required')
        self.assertEqual(len(self.dav.calls), before)
        self.remote.set_credentials(SOURCE, '', SECRET, revision='fixture-revision')
        self.next()
        ready = self.status(job)
        self.assertEqual(ready['state'], 'ready', ready)
        requests = [headers for method, headers in self.dav.calls if method == 'GET']
        self.assertEqual(requests[-1]['range'], f"bytes={paused['downloaded']}-")
        self.assertEqual(requests[-1]['if-match'], '"version-1"')
        self.assertEqual(requests[-1]['if-range'], '"version-1"')
        self.assertEqual(ready['sha256'], digest(self.dav.size))

    def test_disk_full_preserves_only_strong_partial_and_explicit_retry_resumes(self):
        self.dav.interrupt = True
        job = self.prepare()
        self.downloads.process_pending(str(self.root))
        partial = self.status(job)['downloaded']
        self.assertGreaterEqual(partial, MIB)
        self.now += 64
        self.remote._reset_connection(str(self.root), SOURCE)
        with patch.object(self.downloads, '_stream', side_effect=OSError(errno.ENOSPC, 'private ' + SECRET)):
            self.downloads.process_pending(str(self.root))
        result = self.status(job)
        self.assertEqual(result['state'], 'paused', result)
        self.assertEqual(result['error'], 'insufficient_disk_space')
        self.assertEqual(result['downloaded'], partial)
        self.assertIsNone(result['retry_at'])
        self.downloads.retry(str(self.root), job['job_id'])
        self.downloads.process_pending(str(self.root))
        self.assertEqual(self.status(job)['state'], 'ready')

    def test_weak_etag_interruption_restarts_from_zero(self):
        self.dav.etag = 'W/"version-1"'
        self.asset = self.register()
        self.dav.interrupt = True
        job = self.prepare()
        self.downloads.process_pending(str(self.root))
        self.assertEqual(self.status(job)['downloaded'], 0)
        self.next()
        ready = self.status(job)
        self.assertEqual(ready['state'], 'ready', ready)
        self.assertTrue(all('range' not in headers for method, headers in self.dav.calls if method == 'GET'))
        self.assertEqual(ready['sha256'], digest(self.dav.size))

    def test_ignored_range_restarts_full_stream_and_bad_content_range_never_becomes_ready(self):
        for behavior in ('ignore', 'invalid'):
            with self.subTest(behavior=behavior):
                self.dav.interrupt = True
                job = self.prepare()
                self.downloads.process_pending(str(self.root))
                self.dav.range_behavior = behavior
                self.next()
                result = self.status(job)
                self.assertEqual(result['state'], 'ready' if behavior == 'ignore' else 'failed', result)
                if behavior == 'ignore':
                    self.assertEqual(result['sha256'], digest(self.dav.size))
                else:
                    self.assertEqual(result['error'], 'invalid_range_response')
                self.downloads.release(str(self.root), job['job_id'])
                self.dav.range_behavior = 'normal'

    def test_budget_settings_disk_reserve_and_explicit_release_are_persistent(self):
        settings = self.downloads.settings(str(self.root))
        configured = self.downloads.configure(str(self.root), self.dav.size, settings['revision'])
        self.assertNotEqual(configured['revision'], settings['revision'])
        with self.assertRaises(ConflictError):
            self.downloads.configure(str(self.root), self.dav.size, settings['revision'])
        job = self.prepare()
        with self.assertRaises(ValueError):
            self.downloads.configure(str(self.root), self.dav.size - 1)
        self.free = self.dav.size + 5 * MIB - 1
        self.downloads.process_pending(str(self.root))
        result = self.status(job)
        self.assertEqual(result['error'], 'insufficient_disk_space')
        self.assertFalse(any(method == 'GET' for method, _ in self.dav.calls))
        self.assertEqual(self.downloads.release(str(self.root), job['job_id']), {'released': True})
        self.assertEqual(self.downloads.usage(str(self.root))['reserved_bytes'], 0)
        self.assertEqual(self.service().settings(str(self.root))['max_bytes'], self.dav.size)

    def test_checksum_and_final_version_failures_clear_staging_without_exposing_private_errors(self):
        self.asset = self.register(sha256='0' * 64)
        job = self.prepare()
        self.downloads.process_pending(str(self.root))
        failed = self.status(job)
        self.assertEqual(failed['error'], 'checksum_mismatch', failed)
        self.assertNotIn('handle', failed)
        self.assertEqual(self.downloads.usage(str(self.root))['used_bytes'], 0)
        self.dav.heads = 0
        self.asset = self.register(path='Packages/version.zip')
        self.dav.on_final_head = lambda: setattr(self.dav, 'etag', '"changed"')
        job = self.prepare()
        self.downloads.process_pending(str(self.root))
        self.assertEqual(self.status(job)['error'], 'remote_version_changed')
        self.assertEqual(self.downloads.usage(str(self.root))['used_bytes'], 0)
        self.assertNotIn(SECRET, json.dumps(self.downloads.list(str(self.root))))

    def test_handle_expiration_retention_and_lru_budget_eviction(self):
        job = self.prepare()
        self.downloads.process_pending(str(self.root))
        ready = self.status(job)
        self.now += 24 * 3600
        with self.assertRaises(FileNotFoundError):
            self.downloads.resolve_handle(str(self.root), ready['handle'])
        renewed = self.prepare()
        self.assertEqual(renewed['job_id'], job['job_id'])
        self.assertNotEqual(renewed['handle'], ready['handle'])
        self.downloads.configure(str(self.root), self.dav.size - 1)
        self.assertEqual(self.status(job)['state'], 'evicted')
        self.downloads.configure(str(self.root), 20 * MIB)
        later = self.prepare()
        self.downloads.process_pending(str(self.root))
        self.now += 7 * 24 * 3600
        self.assertEqual(self.downloads.usage(str(self.root))['used_bytes'], 0)
        self.assertEqual(self.status(later)['state'], 'evicted')

    def test_prepare_is_idempotent_until_handle_expiry_and_switched_root_download_recovers(self):
        job = self.prepare()
        self.downloads.process_pending(str(self.root))
        ready = self.status(job)
        again = self.prepare()
        self.assertEqual(again['job_id'], ready['job_id'])
        self.assertEqual(again['handle'], ready['handle'])
        self.assertEqual(again['expires_at'], ready['expires_at'])
        self.downloads.release(str(self.root), job['job_id'])
        other = self.home / 'switched'
        other.mkdir()
        sentinel = self.root / 'original.zip'
        sentinel.write_bytes(b'original remains untouched')
        def switch():
            self.dav.on_chunk = None
            self.config.save({'root': str(other)})
        self.dav.on_chunk = switch
        job = self.prepare()
        self.downloads.process_pending(str(self.root))
        self.assertEqual(sentinel.read_bytes(), b'original remains untouched')
        self.assertFalse((other / '.vault-rag' / 'asset-downloads').exists())
        self.config.save({'root': str(self.root)})
        self.downloads.process_pending(str(self.root))
        self.assertEqual(self.status(job)['state'], 'ready')

    def test_consumer_leases_pin_lru_and_budget_until_final_reader_releases(self):
        self.downloads.configure(str(self.root), self.dav.size)
        job = self.prepare()
        self.downloads.process_pending(str(self.root))
        ready = self.status(job)
        first = self.downloads.acquire_handle(str(self.root), ready['handle'])
        second = self.downloads.acquire_handle(str(self.root), ready['handle'])
        self.assertEqual(set(first), {'path', 'job_id', 'name', 'mime'})
        self.assertEqual(first['name'], 'large.zip')
        self.assertEqual(first['path'], second['path'])
        self.now += 7 * 24 * 3600 + 1
        self.assertEqual(self.downloads.usage(str(self.root))['used_bytes'], self.dav.size)
        self.assertEqual(self.status(job)['state'], 'ready')
        other = self.register(path='Packages/second.zip')
        with self.assertRaises(ValueError):
            self.downloads.prepare(str(self.root), other)
        renewed = self.prepare()
        self.downloads.release(str(self.root), job['job_id'])
        with self.assertRaises(FileNotFoundError):
            self.downloads.acquire_handle(str(self.root), renewed['handle'])
        self.assertTrue(first['path'].is_file())
        self.assertEqual(self.downloads.usage(str(self.root))['used_bytes'], self.dav.size)
        self.downloads.release_handle(str(self.root), first['job_id'])
        self.assertTrue(first['path'].is_file())
        self.downloads.release_handle(str(self.root), second['job_id'])
        self.assertFalse(first['path'].exists())
        self.assertEqual(self.downloads.usage(str(self.root))['used_bytes'], 0)
        self.downloads.release_handle(str(self.root), first['job_id'])  # Safe repeated cleanup.
        self.assertEqual(self.downloads.prepare(str(self.root), other)['state'], 'queued')

    def test_read_only_owner_scope_and_explicit_guards_survive_restart(self):
        self.remote.authorize_owner = lambda *_: False
        allowed = {'reader'}
        self.remote.authorize_reader = lambda _root, owner, _revision: owner in allowed
        job = self.prepare(owner='reader')
        self.downloads.process_pending(str(self.root))
        ready = self.downloads.status(str(self.root), job['job_id'], owner='reader')
        self.assertEqual(ready['state'], 'ready', ready)
        with self.assertRaises(PermissionError):
            self.downloads.status(str(self.root), job['job_id'], owner='other', guard=lambda: True)
        allowed.clear()
        with self.assertRaises(PermissionError):
            self.downloads.resolve_handle(str(self.root), ready['handle'], owner='reader')
        allowed.add('reader')
        self.remote.credentials[SOURCE] = ('fixture', SECRET, 'fixture-revision', 'different-client')
        other = self.register(path='Packages/other.zip')
        job = self.downloads.prepare(str(self.root), other, owner='reader')
        self.downloads.process_pending(str(self.root))
        self.assertEqual(self.downloads.status(str(self.root), job['job_id'], owner='reader')['error'], 'authorization_changed')

    def test_single_active_download_release_stops_writer_and_root_switch_never_serves_old_handle(self):
        entered, resume = threading.Event(), threading.Event()
        def block():
            if not entered.is_set():
                entered.set()
                resume.wait(3)
        self.dav.on_chunk = block
        job = self.prepare()
        worker = threading.Thread(target=self.downloads.process_pending, args=(str(self.root),))
        worker.start()
        self.assertTrue(entered.wait(2))
        self.downloads.process_pending(str(self.root))
        self.assertEqual(sum(method == 'GET' for method, _ in self.dav.calls), 1)
        self.downloads.release(str(self.root), job['job_id'])
        resume.set()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.status(job)['state'], 'released')
        self.assertEqual(self.downloads.usage(str(self.root))['used_bytes'], 0)
        self.dav.on_chunk = None
        job = self.prepare()
        self.downloads.process_pending(str(self.root))
        ready = self.status(job)
        other = self.home / 'other-vault'
        other.mkdir()
        self.config.save({'root': str(other)})
        with self.assertRaises(ConflictError):
            self.downloads.resolve_handle(str(self.root), ready['handle'])
        with self.assertRaises(FileNotFoundError):
            self.downloads.resolve_handle(str(other), ready['handle'])


if __name__ == '__main__':
    unittest.main()
