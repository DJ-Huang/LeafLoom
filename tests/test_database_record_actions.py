"""Record context actions preserve source notes, boundaries and retry identity."""
import json
import unittest
from tests import test_databases as fixture
from vault_rag.local_state import ConflictError


class DatabaseRecordActionTests(unittest.TestCase):
    setUp = fixture.DatabaseTests.setUp
    refresh = fixture.DatabaseTests.refresh
    command = fixture.DatabaseTests.command
    record = fixture.DatabaseTests.record

    def test_duplicate_preserves_body_unknown_properties_and_relative_media(self):
        (self.root/'Media/Sub').mkdir()
        source = self.root/'Media/Sub/Original.md'
        body = '\r\n# Original body\r\n\r\nLiteral `code` and [[../Related]] stay unchanged.\r\n'
        original = '---\r\n# Keep this comment\r\nname: Original title\r\nid: stable-original-id\r\ncategory: Demo\r\nattachments: ["[[../../Assets/cover.png]]"]\r\nvendor: {enabled: true}\r\n---\r\n' + body
        source.write_bytes(original.encode())
        self.refresh(); note = self.runtime.files.read('Media/Sub/Original.md')
        command = {'type': 'record.duplicate', 'path': note['path'], 'record_revision': note['etag'], 'title': 'Copied note'}
        result = self.command(command, operation_id='duplicate-full-note')
        copied = self.runtime.files.read(result['path'])
        self.assertEqual(result['path'], 'Media/Sub/Copied note.md')
        self.assertEqual(source.read_bytes(), original.encode())
        self.assertTrue(copied['text'].endswith(body))
        self.assertIn('# Keep this comment', copied['text'])
        self.assertEqual(copied['metadata']['vendor'], {'enabled': True})
        self.assertEqual(copied['metadata']['attachments'], note['metadata']['attachments'])
        self.assertEqual(copied['metadata']['name'], 'Copied note')
        self.assertEqual(copied['metadata']['title'], 'Copied note')
        self.assertNotEqual(copied['metadata']['id'], note['metadata']['id'])
        self.assertTrue(result['visible'])
        self.assertEqual(self.config.data['include_roots'], [])

    def test_duplicate_retry_crash_receipt_and_name_collision(self):
        source = self.record('Source', category='Demo')
        command = {'type': 'record.duplicate', 'path': source['path'], 'record_revision': source['revision'], 'title': 'A copy'}
        a = self.command(command, operation_id='copy-once')
        self.assertEqual(self.db.command('Media.base', command, self.ws, 'old', 'copy-once'), a)
        receipt = next(p for p in (self.root/'.vault-rag/database-receipts').glob('*.json') if json.loads(p.read_text()).get('result') == a)
        pending = json.loads(receipt.read_text()); pending.pop('result'); receipt.write_text(json.dumps(pending))
        self.assertEqual(self.db.command('Media.base', command, self.ws, 'old', 'copy-once'), a)
        b = self.command(command, operation_id='another-copy')
        self.assertNotEqual(a['path'], b['path'])
        self.assertEqual(len(list((self.root/'Media').glob('*.md'))), 3)
        with self.assertRaises(ConflictError):
            self.command({**command, 'title': 'Changed'}, operation_id='copy-once')

    def test_duplicate_rejects_stale_versions_and_outside_records(self):
        source = self.record('Source')
        command = {'type': 'record.duplicate', 'path': source['path'], 'record_revision': source['revision']}
        (self.root/source['path']).write_text('# External replacement\n')
        with self.assertRaises(ConflictError): self.command(command, operation_id='stale-source')
        (self.root/'Outside.md').write_text('# Outside\n')
        outside = self.runtime.files.read('Outside.md')
        with self.assertRaises(ValueError): self.command({**command, 'path': outside['path'], 'record_revision': outside['etag']}, operation_id='outside-source')
        with self.assertRaises(ConflictError): self.db.command('Media.base', command, 'old-workspace', self.c['revision'], 'wrong-workspace')
        with self.assertRaises(ConflictError): self.db.command('Media.base', command, self.ws, 'old-config', 'wrong-config')
        self.assertEqual(len(list((self.root/'Media').glob('*.md'))), 1)
        self.assertEqual((self.root/source['path']).read_text(), '# External replacement\n')

    def test_context_trash_checks_the_record_revision_and_keeps_recovery(self):
        source = self.record('Recycle')
        command = {'type': 'record.trash', 'path': source['path'], 'record_revision': 'stale'}
        with self.assertRaises(ConflictError): self.command(command)
        command['record_revision'] = source['revision']
        preview = self.command(command)
        self.assertTrue((self.root/source['path']).exists())
        self.command({**command, 'dry_run': False, 'operation_token': preview['operation_token']})
        self.assertFalse((self.root/source['path']).exists())
        self.assertEqual(len(self.runtime.files.records('trash')), 1)


if __name__ == '__main__': unittest.main()
