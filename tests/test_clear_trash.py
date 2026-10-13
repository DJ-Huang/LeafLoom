"""Permanent trash clearing stays inside the confirmed vault."""
import json
import tempfile
import unittest
from pathlib import Path

from vault_rag.local_state import ConflictError, Files, LocalConfig


class ClearTrashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.root = self.home / 'vault'
        self.root.mkdir()
        self.config = LocalConfig(self.home / 'state')
        self.config.save({'root': str(self.root)})
        self.files = Files(self.config)

    def clear(self):
        return self.files.clear_trash(expected_root=str(self.root))

    def test_missing_and_empty_trash(self):
        self.assertEqual(self.clear(), {'deleted': 0})
        (self.root / '.vault-rag/trash').mkdir(parents=True)
        self.assertEqual(self.clear(), {'deleted': 0})

    def test_clears_files_and_directories_preserving_live_files_and_history(self):
        note = self.root / 'note.md'
        note.write_text('original')
        self.files.save('note.md', 'edited', self.files.read('note.md')['etag'])
        self.files.delete('note.md')
        folder = self.root / 'folder'
        folder.mkdir()
        (folder / 'nested.txt').write_text('nested')
        self.files.delete('folder')
        note.write_text('live')
        history = self.files.records('history')
        self.assertEqual(self.clear(), {'deleted': 2})
        self.assertEqual(self.files.records('trash'), [])
        self.assertEqual(list((self.root / '.vault-rag/trash').iterdir()), [])
        self.assertEqual(note.read_text(), 'live')
        self.assertEqual(self.files.records('history'), history)
        self.assertEqual(self.clear(), {'deleted': 0})

    def test_clears_records_beyond_list_limit_and_incomplete_entries(self):
        trash = self.root / '.vault-rag/trash'
        for index in range(201):
            entry = trash / f'{index:032x}'
            entry.mkdir(parents=True)
            (entry / 'record.json').write_text(json.dumps({'id': entry.name, 'path': 'old.md', 'time': index}))
        (trash / 'incomplete').write_text('leftover')
        self.assertEqual(len(self.files.records('trash')), 200)
        self.assertEqual(self.clear(), {'deleted': 202})
        self.assertEqual(list(trash.iterdir()), [])

    def test_root_switch_rejected_without_deletion(self):
        (self.root / 'note.md').write_text('old')
        self.files.delete('note.md')
        other = self.home / 'other'
        other.mkdir()
        self.config.save({'root': str(other)})
        (other / 'note.md').write_text('new')
        self.files.delete('note.md')
        with self.assertRaises(ConflictError):
            self.clear()
        self.assertEqual(len(self.files.records('trash')), 1)
        self.assertEqual(len(list((self.root / '.vault-rag/trash').iterdir())), 1)

    def test_linked_state_trash_or_record_rejected(self):
        outside = self.home / 'outside'
        outside.mkdir()
        sentinel = outside / 'keep.txt'
        sentinel.write_text('keep')
        state = self.root / '.vault-rag'
        for target in (state, state / 'trash', state / 'trash/linked'):
            with self.subTest(target=target):
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    target.symlink_to(outside, target_is_directory=True)
                except OSError as error:
                    self.skipTest(f'Directory symlinks unavailable: {error}')
                with self.assertRaises(ValueError):
                    self.clear()
                self.assertEqual(sentinel.read_text(), 'keep')
                target.unlink()


if __name__ == '__main__':
    unittest.main()
