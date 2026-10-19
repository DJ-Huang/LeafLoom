"""Two-tool file contracts through production HTTP MCP, on fictional isolated roots."""
import base64
import hashlib
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock
import uuid
import zipfile

from starlette.testclient import TestClient
from vault_rag.local_state import LocalConfig
from vault_rag.web_server import create_app
from vault_rag.mcp_access import TUNNEL_AUTH_HEADER
from vault_rag.file_downloads import public_target, download_file, PinnedHTTPSConnection


class FileToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.root = self.home / 'vault'
        self.root.mkdir()
        self.config = LocalConfig(self.home / 'state')
        self.config.save({'root': str(self.root)})
        self.app = create_app(self.config, start_background=False)
        self.manager = TestClient(self.app, base_url='http://127.0.0.1:18080', client=('127.0.0.1', 2345))
        self.client = self.manager.__enter__()
        self.addCleanup(self.manager.__exit__, None, None, None)
        self.access = self.app.state.mcp_access
        self.token = self.access.configure('local', enabled=True, write=True)['token']
        self.ws = self.config.data['revision']

    def rpc(self, method, params=None, *, tunnel=False, token=None):
        headers = {'Accept':'application/json, text/event-stream', 'Authorization':'Bearer ' + (token or self.token)}
        if tunnel:
            headers[TUNNEL_AUTH_HEADER] = self.access.tunnel_authorization()
        return self.client.post('/mcp', headers=headers, json={'jsonrpc':'2.0', 'id':1, 'method':method, 'params':params or {}})

    def call(self, action, *, write=False, error=None, files=None, operation_id=None, revision=None, tunnel=False, **values):
        args = dict(request={'action':action, **values}, workspace_revision=revision or self.ws)
        if write:
            args['operation_id'] = operation_id or uuid.uuid4().hex
        if files is not None:
            args['files'] = files
        response = self.rpc('tools/call', {'name':'vault_files_update' if write else 'vault_files', 'arguments':args}, tunnel=tunnel)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()['result']
        value = result.get('structuredContent')
        if error == 'validation':
            self.assertTrue(result.get('isError'), result)
            return result
        self.assertIsNotNone(value, result)
        self.assertEqual(json.loads(result['content'][0]['text']), value)
        if error:
            self.assertTrue(result.get('isError'), value)
            self.assertEqual(value['error_code'], error, value)
        else:
            self.assertFalse(result.get('isError'), value)
        return value

    def put(self, path, data):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
        return p

    def begin(self, name='image.png', data=b'original binary bytes', **values):
        return self.call('upload', write=True, source='begin', name=name, size=len(data),
            sha256=hashlib.sha256(data).hexdigest(), **values)

    def upload(self, name='image.png', data=b'original binary bytes', **values):
        job = self.begin(name, data, **values)
        self.call('upload', write=True, source='chunk', job_id=job['job_id'], offset=0,
            data_base64=base64.b64encode(data).decode())
        return self.call('upload', write=True, source='commit', job_id=job['job_id'])

    def wait(self, job_id):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = self.call('status', job_id=job_id)
            if result['state'] not in {'running','planning','rolling_back','building'}:
                return result
            time.sleep(.01)
        self.fail('File task did not finish')

    def apply(self, job, command='execute', **values):
        return self.call('job', write=True, job_id=job['job_id'], command=command,
            expected_revision=job['revision'], confirm=True, **values)

    def test_two_tools_file_metadata_and_typed_actions(self):
        tools = {t['name']:t for t in self.rpc('tools/list').json()['result']['tools']}
        self.assertIn('vault_files', tools)
        self.assertIn('vault_files_update', tools)
        self.assertFalse(any(n.startswith('vault_upload_') or n.startswith('vault_attachment_') for n in tools))
        self.assertTrue(tools['vault_files']['annotations']['readOnlyHint'])
        self.assertTrue(tools['vault_files_update']['annotations']['destructiveHint'])
        self.assertEqual(tools['vault_files_update']['_meta']['openai/fileParams'], ['files'])
        schema = tools['vault_files_update']['inputSchema']
        file_schema = schema['$defs']['ChatFile']
        self.assertEqual(set(file_schema['properties']), {'download_url','file_id','mime_type','file_name'})
        self.assertEqual(set(file_schema['required']), {'download_url','file_id'})
        self.access.configure('tunnel', enabled=True, write=True)
        tunnel_tools = {t['name']:t for t in self.rpc('tools/list', tunnel=True).json()['result']['tools']}
        self.assertEqual(tunnel_tools['vault_files_update'], tools['vault_files_update'])
        self.call('stat', path='a.png', arbitrary_command='rm', error='validation')
        self.call('shell', write=True, error='validation')

    def test_chunk_round_trip_versions_and_duplicate_uploads(self):
        data = bytes(range(256)) + b'\x00original\xff'
        job = self.begin('图片 #1.png', data)
        first, second = data[:100], data[100:]
        chunk = dict(source='chunk', job_id=job['job_id'], offset=0, data_base64=base64.b64encode(first).decode())
        self.call('upload', write=True, **chunk)
        self.call('upload', write=True, **chunk)
        self.call('upload', write=True, source='chunk', job_id=job['job_id'], offset=100, data_base64=base64.b64encode(second).decode())
        operation_id = uuid.uuid4().hex
        saved = self.call('upload', write=True, source='commit', job_id=job['job_id'], operation_id=operation_id)
        replay = self.call('upload', write=True, source='commit', job_id=job['job_id'], operation_id=operation_id)
        self.assertEqual(saved['path'], replay['path'])
        self.assertTrue(replay['replayed'])
        self.assertEqual((self.root / saved['path']).read_bytes(), data)
        direct = self.call('read', path=saved['path'], expected_revision=saved['revision'])
        self.assertEqual(base64.b64decode(direct['data_base64']), data)
        self.put('Notes/note.md', '# Note')
        info = self.call('stat', path=saved['path'], source_note='Notes/note.md')
        self.assertIn('../_attachments/', info['markdown_link'])
        self.assertIn('%23', info['markdown_link'])
        read = self.call('read', path=saved['path'], expected_revision=info['revision'])
        self.assertEqual(base64.b64decode(read['data_base64']), data)
        self.assertTrue(read['eof'])
        duplicate = self.upload('图片 #1.png', data)
        self.assertNotEqual(saved['path'], duplicate['path'])
        (self.root / saved['path']).write_bytes(b'new version')
        self.call('read', path=saved['path'], expected_revision=info['revision'], error='write_conflict')

    def test_hash_offset_quota_and_paths(self):
        job = self.begin(data=b'ab')
        self.call('upload', write=True, source='chunk', job_id=job['job_id'], offset=1, data_base64='YQ==', error='invalid_request')
        self.call('upload', write=True, source='chunk', job_id=job['job_id'], offset=0, data_base64='eHg=')
        self.call('upload', write=True, source='commit', job_id=job['job_id'], error='invalid_request')
        self.assertFalse((self.root / '_attachments/image.png').exists())
        for name in ('../a.png', '.hidden.png', 'note.md'):
            self.begin(name, error='invalid_request')
        self.begin(folder='../outside', error='invalid_request')
        self.call('read', path='../outside', expected_revision='x', error='invalid_request')
        with patch.object(self.app.state.file_operations, 'MAX_TOTAL', 1):
            self.begin(data=b'ab', error='invalid_request')

    def test_read_write_legacy_and_workspace_boundary(self):
        self.put('a.png', b'image')
        self.access.configure('local', enabled=True, write=False)
        self.call('stat', path='a.png')
        self.begin(error='permission_denied')
        args = {'request':{'action':'stat','path':'a.png'}, 'workspace_revision':self.ws}
        legacy = (self.config.directory / 'auth-token').read_text().strip()
        result = self.rpc('tools/call', {'name':'vault_files','arguments':args}, token=legacy).json()['result']
        self.assertEqual(result['structuredContent']['error_code'], 'permission_denied')
        self.access.configure('local', enabled=True, write=True)
        job = self.begin()
        self.access.configure('tunnel', enabled=True, write=True)
        self.call('stat', path='a.png', tunnel=True)
        self.call('status', job_id=job['job_id'], tunnel=True, error='not_found')
        other = self.home / 'other'
        other.mkdir()
        self.config.save({'root':str(other)})
        self.call('upload', write=True, source='chunk', job_id=job['job_id'], offset=0, data_base64='', error='write_conflict')
        self.assertFalse(list(other.glob('*')))

    def test_uninitialized_index_and_search(self):
        self.put('nested/report.pdf', b'%PDF original')
        self.call('list', error='initialization_required')
        job = self.call('reindex', write=True)
        self.assertEqual(self.wait(job['job_id'])['state'], 'ready')
        listing = self.call('list', query='report', kind='pdf', limit=1)
        self.assertEqual(listing['total'], 1)
        self.assertEqual(listing['items'][0]['path'], 'nested/report.pdf')
        self.assertEqual(self.call('status')['limits']['file_bytes'], 256 * 1024 * 1024)

    def test_rotated_credentials_cannot_read_staging_and_expired_transfers(self):
        job = self.begin()
        with patch('vault_rag.file_operations.time.time', return_value=time.time()+86401):
            self.call('status', job_id=job['job_id'], error='transfer_expired')
        self.token = self.access.configure('local', enabled=True, write=True, rotate=True)['token']
        self.call('status', job_id=job['job_id'], error='not_found')

    def test_publication_receipt_recovers_without_duplicate_file(self):
        data = b'original'
        job = self.begin(data=data)
        self.call('upload', write=True, source='chunk', job_id=job['job_id'], offset=0, data_base64=base64.b64encode(data).decode())
        service = self.app.state.file_operations
        save = service._save_receipt
        def fail_after_link(owner, operation_id, fingerprint, result, **extra):
            if result.get('saved') and 'sha256' in result:
                raise OSError('fictional receipt failure')
            return save(owner, operation_id, fingerprint, result, **extra)
        operation_id = uuid.uuid4().hex
        with patch.object(service, '_save_receipt', side_effect=fail_after_link):
            self.call('upload', write=True, source='commit', job_id=job['job_id'], operation_id=operation_id, error='operation_failed')
        replay = self.call('upload', write=True, source='commit', job_id=job['job_id'], operation_id=operation_id)
        self.assertEqual((self.root / replay['path']).read_bytes(), data)
        self.assertEqual(len(list((self.root / '_attachments').glob('*.png'))), 1)
        self.assertFalse(list((self.root / '_attachments').glob('.upload-*')))
        self.assertEqual(self.call('status', job_id=job['job_id'])['state'], 'completed')

    def test_browser_action_reauthorizes_a_previously_mcp_planned_task(self):
        self.put('a.png', b'image')
        job = self.wait(self.call('move', write=True, paths=['a.png'], destination='Photos')['job_id'])
        self.access.configure('local', enabled=True, write=False)
        migrations = self.app.state.attachment_migrations
        migrations.action(job['id'], 'execute', str(self.root), True)
        completed = self.wait(job['job_id'])
        self.assertEqual(completed['state'], 'completed', completed)
        self.assertEqual((self.root / 'Photos/a.png').read_bytes(), b'image')

    def test_move_preview_execute_restore_and_conflicts(self):
        self.put('assets/a.png', b'image')
        self.put('note.md', '![[assets/a.png]]')
        plan = self.call('move', write=True, paths=['assets/a.png'], destination='Photos/b.png', destination_kind='path')
        job = self.wait(plan['job_id'])
        self.assertEqual(job['state'], 'ready', job)
        self.assertTrue((self.root / 'assets/a.png').exists())
        self.apply({**job, 'revision':'stale'}, error='write_conflict')
        self.call('job', write=True, job_id=job['job_id'], command='execute', expected_revision=job['revision'], error='invalid_request')
        self.apply(job)
        completed = self.wait(job['job_id'])
        self.assertEqual(completed['state'], 'completed', completed)
        self.assertEqual((self.root / 'note.md').read_text(), '![[Photos/b.png]]')
        self.assertEqual(self.config.data['attachment_folder'], '_attachments')
        self.apply(completed, 'undo')
        restored = self.wait(job['job_id'])
        self.assertEqual(restored['state'], 'rolled_back', restored)
        self.assertEqual((self.root / 'note.md').read_text(), '![[assets/a.png]]')

    def test_trash_keeps_links_and_undo_refuses_new_edits(self):
        self.put('a.png', b'image')
        self.put('note.md', '![[a.png]]')
        job = self.wait(self.call('trash', write=True, paths=['a.png'])['job_id'])
        page = self.call('status', job_id=job['job_id'], section='references', limit=1)
        self.assertEqual(page['page']['results'], ['note.md'])
        self.apply(job)
        completed = self.wait(job['job_id'])
        self.assertEqual(completed['state'], 'completed', completed)
        self.assertEqual((self.root / 'note.md').read_text(), '![[a.png]]')
        self.put('a.png', b'new external file')
        self.apply(completed, 'undo')
        conflict = self.wait(job['job_id'])
        self.assertEqual(conflict['state'], 'conflict', conflict)
        self.assertEqual((self.root / 'a.png').read_bytes(), b'new external file')

    def test_export_binary_zip_and_expiry(self):
        self.put('a.png', b'image')
        self.put('b.pdf', b'%PDF')
        job = self.call('export', paths=['a.png','b.pdf'])
        complete = self.wait(job['job_id'])
        data = self.call('read', job_id=job['job_id'], expected_revision=complete['revision'])
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(data['data_base64']))) as archive:
            self.assertEqual(archive.read('a.png'), b'image')
            self.assertEqual(archive.read('b.pdf'), b'%PDF')
        with patch('vault_rag.attachment_workspace.time.time', return_value=time.time()+3601):
            self.call('status', job_id=job['job_id'], error='invalid_request')

    def test_chat_upload_native_file_input_and_partial_batch(self):
        calls = []
        def fetch(url, stream, *, check, progress, **values):
            check()
            calls.append(url)
            if len(calls) == 2:
                raise ValueError('expired secret URL')
            progress(5)
            stream.write(b'image')
            return 5
        files = [dict(file_id='file-one', file_name='one.png', download_url='https://files.example/secret-one'),
                 dict(file_id='file-two', file_name='two.png', download_url='https://files.example/secret-two')]
        operation_id = uuid.uuid4().hex
        with patch('vault_rag.file_operations.download_file', side_effect=fetch):
            job = self.call('upload', write=True, source='files', files=files, operation_id=operation_id)
            result = self.wait(job['job_id'])
            self.assertEqual(result['state'], 'failed', result)
            self.assertEqual(len(result['results']), 1)
            self.assertEqual((self.root / '_attachments/one.png').read_bytes(), b'image')
            replay = self.call('upload', write=True, source='files', files=files, operation_id=operation_id)
            self.assertEqual(replay['state'], 'failed')
            self.assertEqual(len(calls), 2)
            self.assertNotIn('secret', json.dumps(result))
            self.call('upload', write=True, source='files', files=files[:1], operation_id=operation_id, error='write_conflict')

    def test_chat_upload_revocation_before_publish_and_optional_filename(self):
        started, release = threading.Event(), threading.Event()
        def fetch(url, stream, *, check, progress, **values):
            started.set()
            release.wait(5)
            check()
            progress(1)
            stream.write(b'x')
        with patch('vault_rag.file_operations.download_file', side_effect=fetch):
            job = self.call('upload', write=True, source='files', files=[dict(file_id='file-x', download_url='https://files.example/signed')])
            self.assertTrue(started.wait(2))
            self.access.configure('local', enabled=True, write=False)
            release.set()
            result = self.wait(job['job_id'])
            self.assertEqual(result['state'], 'failed', result)
            self.assertEqual(result['error_code'], 'permission_denied')
            self.assertFalse((self.root / '_attachments').exists())

    def test_successful_native_file_without_filename_returns_readable_version(self):
        def fetch(url, stream, *, check, progress, **values):
            check()
            progress(5)
            stream.write(b'image')
        with patch('vault_rag.file_operations.download_file', side_effect=fetch):
            job = self.call('upload', write=True, source='files', files=[dict(file_id='file-image',
                mime_type='image/png', download_url='https://files.example/signed')])
            complete = self.wait(job['job_id'])
        self.assertEqual(complete['state'], 'completed', complete)
        result = complete['results'][0]
        self.assertTrue(result['path'].endswith('.png'))
        self.assertEqual(result['sha256'], hashlib.sha256(b'image').hexdigest())
        read = self.call('read', path=result['path'], expected_revision=result['revision'])
        self.assertEqual(base64.b64decode(read['data_base64']), b'image')

    def test_consolidation_changes_workspace_revision_and_remains_undoable(self):
        self.put('loose/a.png', b'image')
        self.put('note.md', '![[loose/a.png]]')
        job = self.wait(self.call('organize', write=True, destination='Assets')['job_id'])
        self.assertEqual(job['state'], 'ready', job)
        self.apply(job)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            value = self.app.state.attachment_migrations.get(job['id'])
            if value['state'] not in {'running','rolling_back'}:
                break
            time.sleep(.01)
        self.assertEqual(value['state'], 'completed', value)
        self.assertEqual(self.config.data['attachment_folder'], 'Assets')
        self.assertNotEqual(self.ws, self.config.data['revision'])
        self.call('status', job_id=job['job_id'], error='write_conflict')
        self.ws = self.config.data['revision']
        completed = self.call('status', job_id=job['job_id'])
        self.apply(completed, 'undo')
        while time.monotonic() < deadline:
            value = self.app.state.attachment_migrations.get(job['id'])
            if value['state'] not in {'running','rolling_back'}:
                break
            time.sleep(.01)
        self.assertEqual(value['state'], 'rolled_back', value)
        self.assertEqual(self.config.data['attachment_folder'], '_attachments')
        self.assertEqual((self.root / 'loose/a.png').read_bytes(), b'image')

    def test_protected_resource_and_symlink_access(self):
        self.put('site/index.html', '<img src="photo.png">')
        self.put('site/photo.png', b'project image')
        self.assertTrue(self.call('stat', path='site/photo.png')['protected'])
        job = self.wait(self.call('trash', write=True, paths=['site/photo.png'])['job_id'])
        self.assertEqual(job['state'], 'blocked', job)
        self.apply(job, error='write_conflict')
        outside = self.home / 'outside.png'
        outside.write_bytes(b'outside')
        (self.root / 'link.png').symlink_to(outside)
        self.call('stat', path='link.png', error='invalid_request')


class FileDownloadSecurityTests(unittest.TestCase):
    def addresses(self, address):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))]

    def test_public_https_validation(self):
        for url in ('http://example.com/a', 'file:///a', 'https://user:pass@example.com/a', 'https://example.com:8080/a'):
            with self.assertRaises(ValueError):
                public_target(url)
        for address in ('127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', '::ffff:127.0.0.1',
                        '224.0.0.1', '64:ff9b::7f00:1', '2002:7f00:1::1'):
            with patch('socket.getaddrinfo', return_value=self.addresses(address)), self.assertRaises(ValueError):
                public_target('https://files.example/a')

    def test_redirect_is_revalidated_and_no_ambient_headers(self):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 302
        response.getheader.return_value = 'https://private.example/secret'
        def resolve(host, *args, **values):
            return self.addresses('8.8.8.8' if host == 'files.example' else '127.0.0.1')
        with patch('socket.getaddrinfo', side_effect=resolve), patch('vault_rag.file_downloads.PinnedHTTPSConnection', return_value=connection) as factory:
            with self.assertRaises(ValueError):
                download_file('https://files.example/a', io.BytesIO(), check=lambda:None, progress=lambda size:None, max_size=10)
            factory.assert_called_once_with('files.example', '8.8.8.8')
            self.assertEqual(connection.request.call_args.kwargs['headers'], {'Accept-Encoding':'identity'})

    def test_pinned_address_keeps_original_tls_server_name(self):
        connection = PinnedHTTPSConnection('files.example', '8.8.8.8')
        connection._context = Mock()
        with patch('socket.create_connection') as connect:
            connection.connect()
            connect.assert_called_once_with(('8.8.8.8',443), 30)
            connection._context.wrap_socket.assert_called_once_with(connect.return_value, server_hostname='files.example')


if __name__ == '__main__':
    unittest.main()
