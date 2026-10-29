"""Local metadata follows journaled moves using disposable fixture files."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from vault_rag.attachment_metadata_hooks import install_attachment_metadata_hooks
from vault_rag.attachment_migrations import AttachmentMigrations
from vault_rag.local_state import Files, LocalConfig
from vault_rag.remote_attachments import RemoteAttachments


class AttachmentMetadataHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.root = self.home / 'vault'
        self.root.mkdir()
        self.config = LocalConfig(self.home / 'state')
        self.config.save({'root': str(self.root)})
        self.files = Files(self.config)
        self.events = []
        self.files.annotation_changed = lambda action, **fields: self.events.append((action, fields))
        self.runtime = SimpleNamespace(config=self.config, files=self.files,
            files_changed=lambda *paths: None, publish=lambda *args, **kwargs: None)
        self.remote = RemoteAttachments(self.config)
        self.hooks = install_attachment_metadata_hooks(self.runtime, self.remote)
        self.manager = AttachmentMigrations(self.runtime)

    def tearDown(self):
        self.manager.stop()
        self.remote.stop()
        self.temp.cleanup()

    def put(self, rel, data=b'fixture'):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def label(self, rel):
        item = self.remote.stat(str(self.root), rel)
        return self.remote.update_metadata(str(self.root), rel,
            {'tags': ['hero'], 'category': 'People', 'description': 'Keep this description'},
            item['metadata_revision'])

    def check(self, original, path):
        item = self.remote.stat(str(self.root), asset_id=original['asset_id'])
        self.assertEqual(item['path'], path)
        self.assertEqual(item['tags'], ['hero'])
        self.assertEqual(item['category'], 'People')
        self.assertEqual(item['description'], 'Keep this description')
        return item

    def wait(self, key):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = self.manager.get(key)
            if job['state'] not in {'planning', 'running', 'rolling_back'}:
                return job
            time.sleep(.01)
        self.fail('Fixture migration did not finish')

    def test_file_directory_move_rename_and_undo_preserve_identity_and_callbacks(self):
        self.put('folder/a.png')
        item = self.label('folder/a.png')
        moved = self.files.move('folder', 'renamed')
        self.check(item, 'renamed/a.png')
        renamed = self.files.move('renamed/a.png', 'renamed/b.png')
        self.check(item, 'renamed/b.png')
        self.files.restore('operations', renamed['operation_id'])
        self.check(item, 'renamed/a.png')
        self.files.restore('operations', moved['operation_id'])
        self.check(item, 'folder/a.png')
        self.assertEqual([event[0] for event in self.events], ['move'] * 4)
        self.assertIs(install_attachment_metadata_hooks(self.runtime, self.remote), self.hooks)

    def test_organize_and_rollback_use_saved_identities(self):
        self.put('loose/a.png')
        item = self.label('loose/a.png')
        created = self.manager.create(str(self.root))
        planned = self.wait(created['id'])
        self.assertEqual(planned['state'], 'ready', planned)
        self.manager.action(created['id'], 'execute', str(self.root), True)
        completed = self.wait(created['id'])
        self.assertEqual(completed['state'], 'completed', completed)
        self.check(item, '_attachments/loose/a.png')
        journal = self.root / '.vault-rag/attachment-migrations' / created['id'] / 'manifest.json'
        recorded = json.loads(journal.read_text())
        self.assertEqual(recorded['local_metadata_moves'][0]['asset_id'], item['asset_id'])
        self.assertEqual(self.hooks.sync_migration(recorded), {'updated': 0})
        self.manager.action(created['id'], 'rollback', str(self.root), True)
        rolled = self.wait(created['id'])
        self.assertEqual(rolled['state'], 'rolled_back', rolled)
        self.check(item, 'loose/a.png')
        self.assertEqual(self.hooks.sync_migration(recorded, reverse=True), {'updated': 0})
        self.assertEqual((self.root / 'loose/a.png').read_bytes(), b'fixture')

    def test_original_annotation_failure_is_preserved_and_old_journals_do_not_claim_metadata(self):
        self.put('a.png')
        item = self.label('a.png')
        (self.root / 'a.png').rename(self.root / 'b.png')
        class AnnotationFailure(Exception):
            pass
        def failed(*args, **kwargs):
            raise AnnotationFailure('original callback')
        self.hooks.previous = failed
        with self.assertRaisesRegex(AnnotationFailure, 'original callback'):
            self.files.annotation_changed('move', source='a.png', destination='b.png')
        self.check(item, 'b.png')
        old_journal = dict(root=str(self.root), moves=[dict(source='a.png', destination='b.png')])
        self.assertEqual(self.hooks.sync_migration(old_journal, reverse=True), {'updated': 0})
        self.check(item, 'b.png')
        with patch.object(self.remote, 'sync_local_paths', side_effect=ValueError('metadata conflict')):
            with self.assertLogs('vault_rag.attachment_metadata_hooks', level='WARNING'):
                with self.assertRaisesRegex(AnnotationFailure, 'original callback'):
                    self.files.annotation_changed('move', source='b.png', destination='c.png')


if __name__ == '__main__':
    unittest.main()
