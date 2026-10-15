"""File-save compatibility for source-preserving rich/source editing."""
import tempfile
import unittest
from pathlib import Path

from vault_rag.local_state import ConflictError, Files, LocalConfig


class RichSourceSaveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='leafloom-source-save-')
        self.home = Path(self.temporary.name).resolve()
        self.root = self.home / 'vault'
        self.root.mkdir()
        self.config = LocalConfig(self.home / 'state')
        self.config.save({'root': str(self.root), 'include_roots': ['']})
        self.files = Files(self.config)
        self.path = self.root / 'Note.md'

    def tearDown(self):
        self.temporary.cleanup()

    def save(self, text):
        note = self.files.read('Note.md')
        return self.files.save('Note.md', text, note['etag'], expected_root=note['root'])

    def test_local_edit_retains_mixed_eols_and_bom(self):
        original = b'\xef\xbb\xbf---\r\ntitle: Original\r\n---\r\n\r\nFirst\n\nChange me\r\n\r\nLast\n'
        self.path.write_bytes(original)
        text = self.files.read('Note.md')['text'].replace('Change me', 'Changed')
        self.save(text)
        self.assertEqual(self.path.read_bytes(), original.replace(b'Change me', b'Changed'))

    def test_removing_last_crlf_region_keeps_remaining_lf_source(self):
        self.path.write_bytes(b'First\n\nRemove\r\n\r\nLast\n')
        self.save('First\n\nLast\n')
        self.assertEqual(self.path.read_bytes(), b'First\n\nLast\n')

    def test_old_lf_client_keeps_uniform_crlf_behavior(self):
        self.path.write_bytes(b'First\r\n\r\nLast\r\n')
        self.save('Changed\n\nLast\n')
        self.assertEqual(self.path.read_bytes(), b'Changed\r\n\r\nLast\r\n')

    def test_conflict_and_root_guards_still_prevent_writes(self):
        self.path.write_bytes(b'First\r\n')
        note = self.files.read('Note.md')
        self.path.write_bytes(b'External\r\n')
        with self.assertRaises(ConflictError):
            self.files.save('Note.md', 'Mine', note['etag'], expected_root=note['root'])
        with self.assertRaises(ConflictError):
            self.files.save('Note.md', 'Mine', self.files.read('Note.md')['etag'], expected_root='different-root')
        self.assertEqual(self.path.read_bytes(), b'External\r\n')


if __name__ == '__main__':
    unittest.main()
