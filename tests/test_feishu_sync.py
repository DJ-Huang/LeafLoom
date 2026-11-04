"""Mirror behavior with fictional pages and attachment receipts; no live services."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vault_rag.skill_install import skill_source

spec = importlib.util.spec_from_file_location('feishu_sync', skill_source('work-hub').parent / 'scripts/feishu_sync.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class Notes:
    def __init__(self, root):
        self.root = str(root)
        self.files = {}
        self.writes = 0

    def read(self, path):
        text = self.files.get(path)
        return None if text is None else {'text': text, 'etag': sync.digest(text)}

    def write(self, path, text, current):
        self.files[path] = text
        self.writes += 1


class MirrorTests(unittest.TestCase):
    def test_missing_file_compatibility_does_not_mask_other_service_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            api = sync.LeafLoom.__new__(sync.LeafLoom)
            api.root = directory
            api.guard = lambda: None
            api.request = lambda *args, **kwargs: (_ for _ in ()).throw(sync.APIError(400, 'service rejected'))
            self.assertIsNone(api.read('not-created/README.md'))
            (Path(directory) / 'existing.md').write_text('keep')
            with self.assertRaises(sync.APIError):
                api.read('existing.md')

    def test_media_and_structure_render_in_place_without_following_external_links(self):
        text = '# Week\n\n## Project\n\n### Monday\nBefore\n![](https://feishu.cn/file/Img1)\nAfter\n'
        text += '<figure><source token="Vid1" mime="video/mp4" size="546788780" name="demo.mp4"/></figure>\n'
        text += '<figure><source token="Deck1" mime="application/pdf" name="slides.pdf"/></figure>\n'
        text += '<readonly-block type="iframe" href="https://example.com/report"></readonly-block>\n'
        text += '<task task-id="Task1" status="success"></task>\n'
        text += '<sub-page-list><sub-page doc-id="Child" title="Next" file-type="docx"/></sub-page-list>'
        self.assertEqual(set(sync.media(text)), {'Img1', 'Vid1'})
        self.assertGreater(sync.media(text)['Vid1']['size'], 500 * 1024**2)
        rendered = sync.render({'content': text, 'title': 'Week', 'revision_id': 1},
                               {'Child': {'file': 'Next.md', 'title': 'Next'}},
                               {'Img1': {'state': 'completed', 'path': '_attachments/a/img.png'},
                                'Vid1': {'state': 'completed', 'path': '_attachments/b/demo.mp4'}},
                               'https://example.feishu.cn/docx/Root', 'Hub/Work')
        self.assertIn('Before\n![[_attachments/a/img.png]]\nAfter', rendered)
        self.assertIn('![[_attachments/b/demo.mp4]]', rendered)
        self.assertIn('[slides.pdf](https://feishu.cn/file/Deck1)', rendered)
        self.assertIn('[[Hub/Work/Next.md|Next]]', rendered)
        self.assertIn('https://example.com/report', rendered)
        self.assertNotIn('<task', rendered)
        self.assertIn('### Monday', rendered)

    def test_failed_media_keeps_original_reference(self):
        original = '![](https://feishu.cn/file/Img1)'
        result = sync.render({'content': original, 'title': 'Page', 'revision_id': 1}, {},
                             {'Img1': {'state': 'pending', 'path': 'never/use.png'}},
                             'https://example.feishu.cn/docx/Page', 'Hub/Work')
        self.assertIn(original, result)
        self.assertNotIn('never/use.png', result)

    def test_compact_subpage_widget_becomes_separate_index_entries(self):
        original = '# Root\n\n<sub-page-list space-id="Space"><sub-page doc-id="One" title="One" file-type="docx"/>'
        original += '<sub-page doc-id="Two" title="Two" file-type="docx"/></sub-page-list>'
        result = sync.render({'content': original, 'title': 'Root', 'revision_id': 1},
                             {'One': {'file': 'One.md', 'title': 'One'},
                              'Two': {'file': 'Two.md', 'title': 'Two'}}, {},
                             'https://example.feishu.cn/wiki/Root', 'Hub/Work')
        self.assertIn('\n- [[Hub/Work/One.md|One]]\n- [[Hub/Work/Two.md|Two]]\n', result)
        self.assertNotIn('[子页面]', result)

    def test_title_columns_and_linked_video_remain_readable(self):
        original = '<title>Week</title>\n<grid><column>\nBefore\n![](https://feishu.cn/file/Img)\n</column>'
        original += '<column>\n[Screen recording](https://example.feishu.cn/file/Vid)\n</column></grid>'
        result = sync.render({'content': original, 'title': 'Week', 'revision_id': 1}, {},
                             {'Img': {'state': 'completed', 'path': 'a.png'},
                              'Vid': {'state': 'completed', 'path': 'b.mp4'}},
                             'https://example.feishu.cn/docx/Page', 'Hub/Work')
        self.assertTrue(result.startswith('# Week'))
        self.assertNotIn('<column', result)
        self.assertNotIn('<grid', result)
        self.assertLess(result.index('Before'), result.index('![[a.png]]'))
        self.assertLess(result.index('![[a.png]]'), result.index('![[b.mp4]]'))
        self.assertIn('Screen recording', result)
        with_alt = sync.render({'content': '![Camera comparison](https://feishu.cn/file/Img)',
                                'title': 'Week', 'revision_id': 1}, {},
                               {'Img': {'state': 'completed', 'path': '_attachments/a.png'}},
                               'https://example.feishu.cn/docx/Page', 'Hub/Work')
        self.assertIn('![Camera comparison](_attachments/a.png)', with_alt)

    def test_unchanged_update_local_conflict_and_lost_checkpoint(self):
        api = Notes('/fictional')
        old, changed = sync.save_note(api, 'Page.md', 'one', None)
        self.assertTrue(changed)
        self.assertEqual(sync.save_note(api, 'Page.md', 'one', None), (old, False))
        new, changed = sync.save_note(api, 'Page.md', 'two', old)
        self.assertTrue(changed)
        self.assertEqual(api.files['Page.md'], 'two')
        api.files['Page.md'] = 'manual note'
        with self.assertRaises(sync.SyncError):
            sync.save_note(api, 'Page.md', 'three', new)
        self.assertEqual(api.files['Page.md'], 'manual note')
        del api.files['Page.md']
        with self.assertRaises(sync.SyncError):
            sync.save_note(api, 'Page.md', 'three', new)

    def test_receipt_reconciliation_checks_storage_hash_size_and_name(self):
        receipt = {'kind': 'upload', 'source_id': 'nas', 'requested_path': '_attachments/a/file.mp4',
                   'sha256': 'hash', 'size': 550000000, 'job_id': 'remote:1'}
        jobs = [receipt]
        self.assertIs(sync.select_job(jobs, 'nas', 'file.mp4', 'hash', 550000000), receipt)
        self.assertIsNone(sync.select_job(jobs, 'other', 'file.mp4', 'hash', 550000000))
        self.assertIsNone(sync.select_job(jobs, 'nas', 'file.mp4', 'changed', 550000000))
        with self.assertRaises(sync.SyncError):
            sync.select_job(jobs * 2, 'nas', 'file.mp4', 'hash', 550000000)

    def test_tree_additions_and_removals_preserve_local_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            api = Notes(directory)
            mirror = sync.Mirror(api, 'Hub/Work', 'https://example.feishu.cn/wiki/Root')
            first = {'document': {'document_id': 'RootDoc', 'revision_id': 1,
                                 'content': '# Root\n<sub-page doc-id="Child" title="Child" file-type="docx"/>'}}
            child = {'document': {'document_id': 'Child', 'revision_id': 1, 'content': '# Child\nOriginal'}}
            with patch.object(sync, 'cli', side_effect=[copy.deepcopy(first), copy.deepcopy(child)]):
                mirror.discover()
            mirror.write_pages()
            original = dict(api.files)
            second = sync.Mirror(api, 'Hub/Work')
            with patch.object(sync, 'cli', return_value={'document': {'document_id': 'RootDoc',
                      'revision_id': 2, 'content': '# Root\nNo child'}}):
                second.discover()
            second.write_pages()
            child_path = 'Hub/Work/' + mirror.data['pages']['Child']['file']
            self.assertEqual(api.files[child_path], original[child_path])
            self.assertTrue(second.data['pages']['Child']['removed'])
            self.assertIn('来源已移除', api.files['Hub/Work/README.md'])

    def test_incomplete_discovery_never_marks_children_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            mirror = sync.Mirror(Notes(directory), 'Hub/Work', 'https://example.feishu.cn/wiki/Root')
            mirror.data['pages']['Child'] = {'removed': False}
            with patch.object(sync, 'cli', side_effect=sync.SyncError('No access')):
                mirror.discover()
            self.assertFalse(mirror.data['pages']['Child']['removed'])
            self.assertEqual(len(mirror.errors), 1)

    def test_interrupted_note_save_recovers_even_after_another_source_update(self):
        with tempfile.TemporaryDirectory() as directory:
            api = Notes(directory)
            mirror = sync.Mirror(api, 'Hub/Work', 'https://example.feishu.cn/wiki/Root')
            mirror.data['pages']['Root'] = {'file': 'README.md', 'title': 'Root', 'parent': None,
                                          'source': 'https://example.feishu.cn/wiki/Root',
                                          'local_hash': sync.digest('older rendering'),
                                          'pending_hash': sync.digest('interrupted generated rendering')}
            api.files['Hub/Work/README.md'] = 'interrupted generated rendering'
            mirror.documents['Root'] = {'title': 'Root', 'revision_id': 3, 'content': '# Root\nNewest'}
            mirror.write_pages()
            self.assertIn('Newest', api.files['Hub/Work/README.md'])
            self.assertEqual(mirror.errors, [])

    def test_server_failure_does_not_publish_media_or_delete_staged_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            api = Notes(directory)
            api.jobs = lambda: []
            mirror = sync.Mirror(api, 'Hub/Work', 'https://example.feishu.cn/wiki/Root', 'nas')
            path = mirror.state_dir / 'clip.mp4'
            path.write_bytes(b'fictional-video')
            asset = {'token': 'Vid', 'kind': 'video', 'name': 'clip.mp4', 'state': 'pending',
                     'local': str(path), 'size': path.stat().st_size, 'sha256': sync.file_digest(path),
                     'upload_name': 'clip.mp4'}
            mirror.data['assets']['Vid'] = asset
            api.request = lambda *args, **kwargs: (_ for _ in ()).throw(sync.SyncError('connection lost'))
            with self.assertRaisesRegex(sync.SyncError, 'connection lost'):
                mirror.transfer(asset)
            self.assertTrue(path.exists())
            self.assertTrue(asset['upload_started'])
            with self.assertRaisesRegex(sync.SyncError, 'uncertain'):
                mirror.transfer(asset)

            receipt = {'kind': 'upload', 'source_id': 'nas', 'requested_path': 'a/clip.mp4',
                       'path': 'a/clip.mp4', 'sha256': asset['sha256'], 'size': asset['size'],
                       'job_id': 'remote:1', 'remote_saved': True, 'verified': True, 'state': 'completed'}
            api.jobs = lambda: [receipt]
            mirror.transfer(asset)
            self.assertEqual(asset['state'], 'completed')
            self.assertFalse(path.exists())
            self.assertEqual(asset['path'], 'a/clip.mp4')

    def test_paths_reject_traversal_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in ('../outside', '/outside', 'Hub/.private', 'Hub/../../outside'):
                with self.assertRaises(sync.SyncError):
                    sync.safe_path(root, path)
            (root / 'link').symlink_to(root, target_is_directory=True)
            with self.assertRaises(sync.SyncError):
                sync.safe_path(root, 'link/page.md')


if __name__ == '__main__':
    unittest.main()
