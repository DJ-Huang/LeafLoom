import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from tests import test_databases as fixtures
from vault_rag import database_envelope
from vault_rag.database_conversion import DatabaseConversion
from vault_rag.web_server import create_app


class DatabaseSecurityTests(unittest.TestCase):
    refresh = fixtures.DatabaseTests.refresh
    password = 'fictional database passphrase'
    endpoint = '/api/database-security'

    def setUp(self):
        fixtures.DatabaseTests.setUp(self)
        app = create_app(self.config, self.runtime, start_background=False)
        token = (self.config.directory / 'auth-token').read_text().strip()
        self.client = TestClient(app, base_url='http://127.0.0.1:18080',
                                 client=('127.0.0.1', 23456), cookies={'vault_session': token})
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.csrf = {'X-Vault-CSRF': self.client.get('/api/session').json()['csrf']}
        self.params = {'root': str(self.config.root), 'path': 'Media.base'}

    def post(self, action, data, headers=None, **params):
        return self.client.post(self.endpoint + '/' + action, params={**self.params, **params},
                                headers=headers or self.csrf, json=data)

    def open_database(self):
        response = self.post('unlock', {'password': self.password})
        self.assertEqual(response.status_code, 200, response.text)
        return {**self.csrf, 'X-Database-Session': response.json()['token']}

    def test_existing_database_moves_records_history_and_attachments_into_ciphertext(self):
        root = self.config.root
        source = 'Media/Fictional.md'
        note = root / source
        note.write_text('---\ntitle: Fictional record\nattachments: ["[[Shared.png]]"]\n---\n\nPrivate body')
        (root / 'Shared.png').write_bytes(b'fictional attachment')
        thumbnail = self.runtime.files.state_path('attachment-thumbnails', 'fixture.webp')
        thumbnail.parent.mkdir(parents=True, exist_ok=True)
        thumbnail.write_bytes(b'old plaintext thumbnail')
        # Creating a history entry must not leave a plaintext copy after conversion.
        self.runtime.files.save(source, note.read_text(), self.runtime.files.read(source)['etag'])
        self.runtime.files.save(source, note.read_text()+' after edit', self.runtime.files.read(source)['etag'])
        self.runtime.catalog.scan()
        preview = self.post('preview', {})
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()['shared'], 1)
        payload = {'revision': preview.json()['revision'], 'password': self.password, 'confirm': True}
        self.assertEqual(self.post('convert', {**payload, 'confirm': False}).status_code, 409)
        converted = self.post('convert', payload)
        self.assertEqual(converted.status_code, 200, converted.text)
        self.assertFalse((root / 'Media').exists())
        self.assertTrue((root / 'Shared.png').exists())
        self.assertFalse(self.runtime.files.records('history', source))
        self.assertFalse(thumbnail.exists())
        self.assertNotIn(source, self.runtime.catalog.entries)
        self.assertFalse(any(b'Private body' in path.read_bytes() for path in (root / '.vault-rag').rglob('catalog*.sqlite')))
        raw = (root / 'Media.base').read_bytes()
        self.assertTrue(raw.startswith(database_envelope.MAGIC))
        self.assertNotIn(b'Private body', raw)
        self.assertNotIn(b'Fictional record', raw)
        self.assertNotIn(b'fictional attachment', raw)
        self.assertEqual(self.client.get('/api/bases/config', params=self.params).status_code, 400)
        self.assertEqual(self.post('query', {}).status_code, 423)
        headers = self.open_database()
        queried = self.post('query', {}, headers)
        self.assertEqual(queried.json()['results'][0]['title'], 'Fictional record')
        data = self.post('record/read', {'source': source}, headers)
        self.assertIn('Private body after edit', data.json()['text'])
        self.assertEqual(data.headers['Cache-Control'], 'no-store')
        edited = self.post('record', {'source': source, 'text': '# New encrypted body',
                                      'revision': data.json()['etag']}, headers)
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertNotIn(b'New encrypted body', (root / 'Media.base').read_bytes())
        self.assertEqual(self.post('record', {'source': source, 'text': 'stale',
                                             'revision': data.json()['etag']}, headers).status_code, 409)
        asset = self.post('asset/read', {'source': source, 'target': 'Shared.png'}, headers)
        self.assertEqual(asset.content, b'fictional attachment')
        self.assertEqual(self.post('lock', {}, headers).status_code, 200)
        self.assertEqual(self.post('query', {}, headers).status_code, 423)
        self.assertEqual(self.post('asset/read', {'source': source, 'target': 'Shared.png'}, headers).status_code, 423)

    def test_new_database_sessions_are_scoped_and_package_can_be_renamed(self):
        self.params['path'] = 'Private.base'
        created = self.post('create', {'password': self.password, 'preset': 'tasks'})
        self.assertEqual(created.status_code, 200, created.text)
        second = self.post('create', {'password': self.password}, path='Other.base')
        self.assertEqual(second.status_code, 200, second.text)
        headers = self.open_database()
        self.assertEqual(self.post('query', {}, headers, path='Other.base').status_code, 423)
        config = self.client.get(self.endpoint+'/config', params=self.params, headers=headers).json()
        table = next(view['id'] for view in config['views'] if view['type'] == 'table')
        command = self.post('commands', {
            'command': {'type': 'record.create', 'title': 'New private note', 'view_id': table},
            'workspace_revision': config['workspace_revision'], 'expected_revision': config['revision'],
            'operation_id': 'private-note',
        }, headers)
        self.assertEqual(command.status_code, 200, command.text)
        self.assertFalse((self.config.root / 'Records').exists())
        upload = self.client.post(self.endpoint+'/asset', params=self.params,
            headers={**headers, 'X-Database-Filename': 'fixture.txt'}, content=b'New private asset')
        self.assertEqual(upload.status_code, 200, upload.text)
        self.assertNotIn(b'New private asset', (self.config.root / self.params['path']).read_bytes())
        self.assertEqual(self.post('asset/read', {'source': command.json()['path'],
            'target': upload.json()['path']}, headers).content, b'New private asset')
        self.runtime.files.move(self.params['path'], 'Renamed.base')
        self.params['path'] = 'Renamed.base'
        new_headers = self.open_database()
        self.assertEqual(self.post('query', {'view_id': table}, new_headers).json()['total'], 1)

    def test_conversion_rechecks_revision_and_leaves_changed_files_untouched(self):
        root = self.config.root
        source = root / 'Media/Changed.md'
        source.write_text('before')
        preview = self.post('preview', {})
        self.assertEqual(preview.status_code, 200, preview.text)
        source.write_text('after')
        response = self.post('convert', {'revision': preview.json()['revision'], 'password': self.password, 'confirm': True})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(source.read_text(), 'after')
        self.assertFalse(database_envelope.encrypted(root / 'Media.base'))

    def test_bearer_cannot_use_browser_unlock_or_read(self):
        self.params['path'] = 'Private.base'
        self.assertEqual(self.post('create', {'password': self.password}).status_code, 200)
        headers = self.open_database()
        bearer = self.client.cookies['vault_session']
        self.client.cookies.clear()
        headers['Authorization'] = 'Bearer '+bearer
        self.assertEqual(self.post('query', {}, headers).status_code, 403)
        self.assertEqual(self.post('unlock', {'password': self.password}, headers).status_code, 403)

    def test_failed_publish_restores_the_plaintext_source(self):
        root = self.config.root
        source = root / 'Media/Retained.md'
        source.write_text('Original record')
        converter = DatabaseConversion(self.config, self.runtime, self.db, str(root), 'Media.base')
        preview = converter.preview()
        with patch.object(converter, 'purge_catalogs', side_effect=OSError('Simulated catalog error')):
            with self.assertRaises(OSError):
                converter.convert({'revision': preview['revision'], 'password': self.password, 'confirm': True})
        self.assertFalse(database_envelope.encrypted(root / 'Media.base'))
        self.assertEqual(source.read_text(), 'Original record')
        self.assertEqual(list((root / '.vault-rag' / 'database-conversions').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
