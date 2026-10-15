"""Attachment API contracts. All files and configuration are temporary."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from starlette.testclient import TestClient
from vault_rag.local_state import LocalConfig, ConflictError
from vault_rag.knowledge import Runtime
from vault_rag.web_server import create_app


class EditorUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.root = self.home / 'vault'
        (self.root / 'Notes').mkdir(parents=True)
        self.config = LocalConfig(self.home / 'state')
        self.config.save({'root': str(self.root), 'include_roots': ['']})
        self.runtime = Runtime(self.config)
        static = self.home / 'static'
        static.mkdir()
        (static / 'index.html').write_text('fixture')
        self.app = create_app(self.config, self.runtime, start_background=False, static_dir=static)
        self.client = TestClient(self.app, base_url='http://127.0.0.1:18080')
        self.client.__enter__()
        self.client.get('/')
        self.headers = {'X-Vault-CSRF': self.client.get('/api/session').json()['csrf']}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.runtime.stop()
        self.temp.cleanup()

    def upload(self, **params):
        return self.client.post('/api/upload', params=params, content=b'original-bytes', headers=self.headers)

    def test_create_folder_unicode_name_and_no_overwrite(self):
        params = dict(folder='Notes/attachments', name='图片 (1).png', root=str(self.root), create_folder=True)
        response = self.upload(**params)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['path'], 'Notes/attachments/图片 (1).png')
        self.assertEqual((self.root / response.json()['path']).read_bytes(), b'original-bytes')
        self.assertEqual(self.upload(**params).status_code, 409)
        self.assertFalse(list(self.root.rglob('.upload-*')))

    def test_legacy_upload_and_default_folder_behavior(self):
        self.assertEqual(self.upload(folder='Notes', name='old.png').status_code, 200)
        self.assertNotEqual(self.upload(folder='missing', name='old.png').status_code, 200)
        self.assertFalse((self.root / 'missing').exists())

    def test_wrong_root_and_unsafe_paths(self):
        self.assertEqual(self.upload(folder='Notes/attachments', name='a.png', root='wrong', create_folder=True).status_code, 409)
        self.assertFalse((self.root / 'Notes/attachments').exists())
        for folder, name in [('..', 'a.png'), ('.vault-rag', 'a.png'), ('Notes', '../a.png')]:
            self.assertEqual(self.upload(folder=folder, name=name, root=str(self.root), create_folder=True).status_code, 400)
        self.assertEqual(self.upload(folder='Notes/new', name='a.png', create_folder=True).status_code, 400)

    def test_root_switch_during_stream_cancels_publish(self):
        endpoint = next(route.endpoint for route in self.app.routes if getattr(route, 'path', None) == '/api/upload')
        other = self.home / 'other'
        other.mkdir()
        config = self.config

        class StreamingRequest:
            async def stream(self):
                yield b'first'
                config.save({'root': str(other)})
                yield b'last'

        with self.assertRaises(ConflictError):
            asyncio.run(endpoint(StreamingRequest(), folder='Notes/attachments', name='a.png', root=str(self.root), create_folder=True))
        self.assertFalse(list(self.home.rglob('a.png')))
        self.assertFalse(list(self.home.rglob('.upload-*')))


if __name__ == '__main__':
    unittest.main()
