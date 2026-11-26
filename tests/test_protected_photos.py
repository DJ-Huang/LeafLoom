import io
import json
import unittest

from PIL import Image
from starlette.testclient import TestClient

from tests import test_databases as fixtures
from vault_rag import locked_photos as crypto
from vault_rag import protected_media as media
from vault_rag.photo_routes import SCOPES_FILE
from vault_rag.web_server import create_app

PASSWORD = 'synthetic photo passphrase'
SCOPE = 'Fixture/照片'


class ProtectedPhotoRoutes(unittest.TestCase):
    refresh = fixtures.DatabaseTests.refresh

    def setUp(self):
        fixtures.DatabaseTests.setUp(self)
        root = self.config.root
        self.params = {'root': str(root)}
        storage = root / '.vault-rag'
        secret = b'synthetic data key'.ljust(32, b'\0')
        crypto.atomic_bytes(storage / crypto.KEY_FILE, crypto.wrap_key(secret, PASSWORD))
        crypto.atomic_bytes(storage / SCOPES_FILE, json.dumps([SCOPE]).encode())
        self.record = f'{SCOPE}/fixture.md'
        (root / self.record).parent.mkdir(parents=True)
        (root / self.record).write_text('# Fixture\n')
        self.app = create_app(self.config, self.runtime, start_background=False)
        self.client = TestClient(self.app, base_url='http://127.0.0.1:18080', client=('127.0.0.1', 12345))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        token = (self.config.directory / 'auth-token').read_text().strip()
        self.bearer = {'Authorization': 'Bearer ' + token}
        self.client.cookies.set('vault_session', token)
        self.csrf = {'X-Vault-CSRF': self.client.get('/api/session').json()['csrf']}
        with io.BytesIO() as output:
            Image.new('RGB', (12, 8), '#664433').save(output, 'JPEG')
            self.data = output.getvalue()

    def test_local_session_round_trip_and_raw_endpoint_returns_ciphertext(self):
        endpoint = '/api/photo-vault'
        self.assertEqual(self.client.get(endpoint, params=self.params).json()['scopes'], [SCOPE])
        lock = self.client.post(endpoint, params=self.params, json={'password': PASSWORD}, headers=self.csrf)
        self.assertEqual(lock.status_code, 200, lock.text)
        headers = {**self.csrf, 'X-Photo-Session': lock.json()['token']}
        written = self.client.post(endpoint + '/image', params={**self.params, 'source': self.record},
                                   content=self.data, headers=headers)
        self.assertEqual(written.status_code, 200, written.text)
        path = written.json()['path']
        self.assertTrue(path.endswith(crypto.EXTENSION))
        params = {**self.params, 'path': path}
        raw = self.client.get('/api/media', params=params)
        self.assertTrue(raw.content.startswith(crypto.PHOTO_MAGIC), raw.status_code)
        self.assertEqual(self.client.get(endpoint + '/image', params=params).status_code, 423)
        image = self.client.get(endpoint + '/image', params=params, headers=headers)
        self.assertEqual(image.content, self.data)
        self.assertEqual(image.headers['cache-control'], 'no-store')
        self.client.cookies.clear()
        self.assertEqual(self.client.get(endpoint + '/image', params=params, headers={**headers, **self.bearer}).status_code, 403)
        self.client.cookies.set('vault_session', self.bearer['Authorization'].removeprefix('Bearer '))
        self.assertEqual(self.client.post(endpoint, params=self.params, headers=headers, json={'action':'lock'}).status_code, 200)
        self.assertEqual(self.client.get(endpoint + '/image', params=params, headers=headers).status_code, 423)

    def test_caption_unlock_edit_and_lock_keep_note_ciphertext(self):
        root = self.config.root
        note = root / self.record
        note.write_text('---\ntitle: 角色照片\n---\n', encoding='utf-8')
        crypto.atomic_bytes(root / '.vault-rag' / crypto.CAPTION_MARKER, b'1')
        params = {**self.params, 'source': self.record}
        endpoint = '/api/photo-vault/caption'
        self.assertEqual(self.client.get(endpoint, params=params).status_code, 423)
        unlock = self.client.post('/api/photo-vault', params=self.params, json={'password': PASSWORD}, headers=self.csrf)
        headers = {**self.csrf, 'X-Photo-Session': unlock.json()['token']}
        etag = self.client.get(endpoint, params=params, headers=headers).json()['revision']
        edited = self.client.post(endpoint, params=params, headers=headers,
                                  json={'caption': 'Fixture caption example', 'revision': etag})
        self.assertEqual(edited.status_code, 200, edited.text)
        raw = note.read_text(encoding='utf-8')
        self.assertIn(crypto.CAPTION_FIELD, raw)
        self.assertNotIn('Fixture caption example', raw)
        visible = self.client.get(endpoint, params=params, headers=headers)
        self.assertEqual(visible.json()['caption'], 'Fixture caption example')
        self.assertEqual(visible.headers['cache-control'], 'no-store')
        self.client.post('/api/photo-vault', params=self.params, headers=headers, json={'action': 'lock'})
        self.assertEqual(self.client.get(endpoint, params=params, headers=headers).status_code, 423)

    def test_configured_gallery_reuses_key_and_keeps_regular_titles(self):
        root = self.config.root
        folder = 'Travel/2026'
        (root / 'Travel').mkdir()
        self.db.command('Trips.base', {'type': 'create', 'folder': folder}, self.ws, operation_id='create-trips')
        source = f'{folder}/trip.md'
        note = root / source
        note.write_text('---\ntitle: Ordinary title\n---\n\nOrdinary note', encoding='utf-8')
        endpoint = '/api/photo-vault'
        request = {'database': 'Trips.base', 'captions': True}
        self.assertEqual(self.client.post(endpoint + '/gallery', params=self.params,
                                          headers=self.csrf, json=request).status_code, 423)
        unlock = self.client.post(endpoint, params=self.params, json={'password': PASSWORD}, headers=self.csrf)
        headers = {**self.csrf, 'X-Photo-Session': unlock.json()['token']}
        expected_key = self.client.get(endpoint + '/format', params=self.params).json()['key_id']
        result = self.client.post(endpoint + '/gallery', params=self.params, json=request, headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get(endpoint + '/format', params=self.params).json()['key_id'], expected_key)
        self.assertEqual(self.client.get(endpoint, params=self.params).json()['scopes'], [SCOPE, folder])
        self.assertFalse((root / '.vault-rag' / media.KEY_FILE).exists())
        params = {**self.params, 'source': source}
        old = self.client.get(endpoint + '/caption', params=params, headers=headers).json()
        saved = self.client.post(endpoint + '/caption', params=params,
            json={'revision': old['revision'], 'caption': 'Private travel scene'}, headers=headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        raw = note.read_text(encoding='utf-8')
        self.assertIn('Ordinary title', raw)
        self.assertNotIn('Private travel scene', raw)
        with self.assertRaises(ValueError):
            self.runtime.files.properties(source, {crypto.CAPTION_FIELD: 'Clear text'}, saved.json()['revision'])
        self.assertEqual(self.client.get(endpoint + '/caption', params=params, headers=headers).json()['caption'],
                         'Private travel scene')
        written = self.client.post(endpoint + '/image', params=params, content=self.data, headers=headers)
        self.assertEqual(written.status_code, 200, written.text)
        path = written.json()['path']
        self.assertRegex(path, rf'^{folder}/_encrypted-photos/[a-f0-9]{{64}}\.llphoto$')
        image = self.client.get(endpoint + '/image', params={**self.params, 'path': path}, headers=headers)
        self.assertEqual(image.content, self.data)
        self.assertEqual(image.headers['cache-control'], 'no-store')
        legacy_written = self.client.post(endpoint + '/image', params={**self.params, 'source': self.record},
                                          content=self.data, headers=headers).json()['path']
        self.assertTrue(legacy_written.startswith(f'{SCOPE}/图片/'))
        (root / legacy_written).write_bytes((root / path).read_bytes())
        mismatch = self.client.get(endpoint + '/image', params={**self.params, 'path': legacy_written}, headers=headers)
        self.assertEqual(mismatch.status_code, 400)

    def test_first_generic_gallery_initializes_a_vault_key(self):
        storage = self.config.root / '.vault-rag'
        (storage / crypto.KEY_FILE).unlink()
        (storage / SCOPES_FILE).unlink()
        endpoint = '/api/photo-vault'
        self.assertFalse(self.client.get(endpoint, params=self.params).json()['key_ready'])
        request = {'database': 'Media.base', 'captions': False, 'password': PASSWORD}
        self.assertEqual(self.client.post(endpoint + '/gallery', params=self.params, headers=self.csrf,
                                         json={**request, 'password': 'short'}).status_code, 400)
        self.assertFalse((storage / media.KEY_FILE).exists())
        configured = self.client.post(endpoint + '/gallery', params=self.params, headers=self.csrf, json=request)
        self.assertEqual(configured.status_code, 200, configured.text)
        self.assertTrue((storage / media.KEY_FILE).read_bytes().startswith(crypto.KEY_MAGIC))
        self.assertEqual(self.client.get(endpoint, params=self.params).json()['galleries'],
                         [{'folder': 'Media', 'captions': False, 'title': None}])
        unlocked = self.client.post(endpoint, params=self.params, headers=self.csrf, json={'password': PASSWORD})
        self.assertEqual(unlocked.status_code, 200, unlocked.text)


if __name__ == '__main__':
    unittest.main()
