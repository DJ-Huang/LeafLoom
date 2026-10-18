import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vault_rag.attachment_references import MAX_TEXT_BYTES, discover_project_dependencies, plan_references
from vault_rag.local_state import Files, LocalConfig


class AttachmentReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.root = self.home / 'vault'
        self.root.mkdir()
        config = LocalConfig(self.home / 'state')
        config.save({'root': str(self.root)})
        self.files = Files(config)
        self.paths = set()

    def tearDown(self):
        self.temp.cleanup()

    def put(self, path, content=b''):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode() if isinstance(content, str) else content)
        self.paths.add(path)
        return p

    def plan(self, mapping):
        return plan_references(self.files, mapping, self.paths)

    def test_markdown_destinations_keep_alias_fragment_title_and_bytes(self):
        self.put('media/a (b).png')
        original = (b'\xef\xbb\xbf![[media/a (b).png#part|Alias]]\r\n'
                    b'![x](media/a%20(b).png?q=1#part "Title")\r\n'
                    b'[x][asset]\r\n[asset]: <media/a (b).png> \'Title\'\r\n')
        note = self.put('note.md', original)
        result = self.plan({'media/a (b).png': 'attachments/a (b).png'})
        self.assertEqual(result['blockers'], [])
        self.assertEqual(result['references'], 3)
        after = result['edits']['note.md']['after']
        self.assertIn(b'[[attachments/a (b).png#part|Alias]]', after)
        self.assertIn(b'(attachments/a%20%28b%29.png?q=1#part "Title")', after)
        self.assertIn(b'<attachments/a%20%28b%29.png> \'Title\'', after)
        self.assertTrue(after.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(after.count(b'\r\n'), 4)
        self.assertEqual(note.read_bytes(), original)

    def test_code_and_external_urls_are_not_rewritten(self):
        self.put('a.png')
        text = '```md\n![[a.png]]\n```\n`![a](a.png)`\n    ![[a.png]]\n![x](https://site/a.png)\n![[a.png]]'
        self.put('note.md', text)
        result = self.plan({'a.png': 'attachments/a.png'})
        self.assertFalse(result['blockers'])
        self.assertEqual(result['references'], 1)
        self.assertTrue(result['edits']['note.md']['after'].decode().endswith('![[attachments/a.png]]'))

    def test_resolution_precedence_and_ambiguity(self):
        self.put('a/x.png')
        self.put('b/x.png')
        self.put('a/n.md', '![[x.png]]')
        self.put('c/n.md', '![[x.png]]')
        result = self.plan({'a/x.png': 'attachments/x.png'})
        self.assertIn('a/n.md', result['edits'])
        self.assertEqual(result['blockers'][0]['path'], 'c/n.md')
        self.assertIn('Ambiguous', result['blockers'][0]['reason'])

    def test_url_decode_exactly_once(self):
        self.put('a%20b.png')
        self.put('a b.png')
        self.put('note.md', '![x](a%2520b.png)')
        result = self.plan({'a%20b.png': 'attachments/a%20b.png'})
        self.assertEqual(result['edits']['note.md']['after'], b'![x](attachments/a%2520b.png)')

    def test_html_css_and_srcset_preserve_layout(self):
        self.put('site/a.png')
        self.put('site/b.png')
        self.put('site/theme.css', 'body { background: url("a.png?q=1#x") }')
        self.put('site/page.html', '<img src="a.png" srcset="a.png 1x, b.png 2x"><video poster=\'b.png\'></video><link href="theme.css"><style>@import "theme.css";</style>')
        result = self.plan({'site/a.png': 'attachments/a.png', 'site/b.png': 'attachments/b.png', 'site/theme.css': 'attachments/theme.css'})
        self.assertEqual(result['blockers'], [])
        after = result['edits']['site/page.html']['after'].decode()
        self.assertIn('srcset="../attachments/a.png 1x, ../attachments/b.png 2x"', after)
        self.assertIn('poster=\'../attachments/b.png\'', after)

    def test_moved_source_updates_unmoved_dependency(self):
        self.put('site/theme.css', 'a { background:url(a.png) }')
        self.put('site/a.png')
        result = self.plan({'site/theme.css': 'attachments/theme.css'})
        self.assertEqual(result['edits']['site/theme.css']['after'], b'a { background:url(../site/a.png) }')

    def test_scripts_unknown_sources_block_but_packaged_assets_are_opaque(self):
        self.put('a.png')
        self.put('code.js', 'fetch("assets/" + name)')
        self.put('app.html', '<script>image.src = prefix + file;</script>')
        self.put('data.json', '{"image":"a.png"}')
        self.put('report.docx', b'PK')
        result = self.plan({'a.png': 'attachments/a.png'})
        self.assertEqual({v['path'] for v in result['blockers']}, {'code.js', 'app.html', 'data.json'})

    def test_large_text_and_encoding_are_explicit_blockers(self):
        self.put('a.png')
        p = self.put('large.md')
        with p.open('wb') as out:
            out.truncate(MAX_TEXT_BYTES + 1)
        self.put('legacy.txt', b'\xff')
        result = self.plan({'a.png': 'attachments/a.png'})
        self.assertEqual({v['path'] for v in result['blockers']}, {'large.md', 'legacy.txt'})

    def test_html_base_and_computed_script_dependencies_block(self):
        self.put('a.png')
        self.put('page.html', '<base href="/static/"><img src="a.png">')
        self.put('script.js', 'window[method](prefix + variable)')
        result = self.plan({'a.png': 'attachments/a.png'})
        self.assertEqual({v['path'] for v in result['blockers']}, {'page.html', 'script.js'})

    def test_css_escape_requires_review(self):
        self.put('a.png')
        self.put('style.css', r'body { background: url(\61.png) }')
        result = self.plan({'a.png': 'attachments/a.png'})
        self.assertTrue(result['blockers'])
        self.assertFalse(result['edits'])

    def test_guard_rejects_symlink_source(self):
        self.put('a.png')
        outside = self.home / 'outside.md'
        outside.write_text('![[a.png]]')
        (self.root / 'link.md').symlink_to(outside)
        self.paths.add('link.md')
        result = self.plan({'a.png': 'attachments/a.png'})
        self.assertEqual(result['blockers'][0]['path'], 'link.md')
        self.assertFalse(result['edits'])

    def test_project_dependencies_protect_shared_assets_transitively(self):
        original = '<link href="../shared/theme.css"><img src="../shared/photo.png"><script src="imports.js"></script>'
        page = self.put('site/index.html', original)
        self.put('site/imports.js', 'import "../shared/static.js";')
        self.put('shared/static.js', 'import "./empty.js";')
        self.put('shared/empty.js', '')
        self.put('shared/theme.css', '@import "colors.css"; a {background:url(photo.png)}')
        self.put('shared/colors.css', 'a {background:url(../fonts/a.woff)}')
        self.put('shared/photo.png')
        self.put('fonts/a.woff')
        self.put('unrelated.png')
        result = discover_project_dependencies(self.files, self.paths, {'site'})
        self.assertEqual(result['protected'], self.paths - {'unrelated.png'})
        self.assertEqual(result['blockers'], [])
        self.assertEqual(page.read_text(), original)

    def test_dynamic_project_stays_in_place_and_retains_shared_directory(self):
        self.put('site/index.html', '<script src="app.js"></script>')
        self.put('site/app.js', 'fetch("../shared/a.png"); const prefix="../shared/"; fetch(prefix + name); console.log("\\n");')
        self.put('shared/a.png')
        self.put('shared/b.png')
        self.put('loose/photo.png')
        result = discover_project_dependencies(self.files, self.paths, {'site'})
        self.assertIn('shared/a.png', result['protected'])
        self.assertIn('shared/b.png', result['protected'])
        self.assertNotIn('loose/photo.png', result['protected'])
        self.assertEqual(result['blockers'], [])

    def test_scan_paths_keeps_full_resolution_and_opaque_assets(self):
        self.put('notes/n.md', '![[a.png]] [doc](../report.docx)')
        self.put('site/app.js', 'fetch(dynamic)')
        self.put('assets/a.png')
        self.put('report.docx', b'PK\xff')
        result = plan_references(self.files,
                                 {'assets/a.png': 'attachments/a.png',
                                  'report.docx': 'attachments/report.docx'},
                                 self.paths, scan_paths={'notes/n.md'})
        self.assertEqual(result['blockers'], [])
        self.assertEqual(result['references'], 2)
        self.assertEqual(set(result['edits']), {'notes/n.md'})

    def test_root_navigation_and_embedded_markup_do_not_preserve_entire_vault(self):
        self.put('site/index.html','<a href="/">Home</a><script>const markup="\\u003cimg src=\\\"../shared/a.png\\\">";</script>')
        self.put('shared/a.png');self.put('loose/photo.png')
        result=discover_project_dependencies(self.files,self.paths,{'site'})
        self.assertEqual(result['blockers'],[])
        self.assertIn('shared/a.png',result['protected'])
        self.assertNotIn('loose/photo.png',result['protected'])

    def test_retained_config_and_template_prefix_protect_external_resources(self):
        self.put('site/index.html','<script src="app.js"></script>')
        self.put('site/app.js','const url=`../shared/${name}.png`;')
        self.put('shared/a.png');self.put('settings.cfg','image=art/icon.png')
        self.put('art/icon.png');self.put('loose/photo.png')
        result=discover_project_dependencies(self.files,self.paths,{'site'},reference_sources={'settings.cfg'})
        self.assertEqual(result['blockers'],[])
        self.assertTrue({'shared/a.png','art/icon.png'}<=result['protected'])
        self.assertNotIn('loose/photo.png',result['protected'])

    def test_unreadable_project_source_still_blocks(self):
        self.put('site/index.html','<script src="app.js"></script>')
        self.put('site/app.js',b'\xff\xfe')
        self.put('loose/photo.png')
        result=discover_project_dependencies(self.files,self.paths,{'site'})
        self.assertEqual(result['blockers'][0]['path'],'site/app.js')

    def test_unrelated_escaped_navigation_does_not_block_attachment_moves(self):
        self.put('a.png')
        self.put('note.md','<a href="chapters\\">read</a>\n![[a.png]]')
        result=self.plan({'a.png':'attachments/a.png'})
        self.assertEqual(result['blockers'],[])
        self.assertIn(b'![[attachments/a.png]]',result['edits']['note.md']['after'])
        self.assertIn(b'href="chapters\\"',result['edits']['note.md']['after'])

    def test_escaped_destination_of_moved_attachment_still_blocks(self):
        self.put('assets/a.png')
        self.put('note.md','<img src="assets\\a.png">')
        result=self.plan({'assets/a.png':'attachments/a.png'})
        self.assertTrue(result['blockers'])
        self.assertEqual(result['blockers'][0]['reason'],'Unsupported escaped attachment destination')

    def test_dynamic_markup_and_mixed_srcset_retain_external_resources(self):
        self.put('site/index.html','<img srcset="data:image/png;base64,AAAA 1x, ../shared/a.png 2x" onload="fetch(\'../shared/data.json\')"><iframe srcdoc="&lt;img src=&quot;../shared/b.png&quot;&gt;"></iframe>')
        self.put('shared/a.png');self.put('shared/b.png')
        self.put('shared/data.json','{"image":"../art/icon.png"}')
        self.put('art/icon.png');self.put('loose/photo.png')
        result=discover_project_dependencies(self.files,self.paths,{'site'})
        self.assertEqual(result['blockers'],[])
        self.assertTrue({'shared/a.png','shared/b.png','shared/data.json','art/icon.png'}<=result['protected'])
        self.assertNotIn('loose/photo.png',result['protected'])

    def test_css_escaped_dependency_is_retained_without_rewriting(self):
        self.put('site/theme.css',r'body {background:url(../shared/a\2e png)}')
        self.put('shared/a.png');self.put('loose/photo.png')
        result=discover_project_dependencies(self.files,self.paths,{'site'})
        self.assertEqual(result['blockers'],[])
        self.assertIn('shared/a.png',result['protected'])
        self.assertNotIn('loose/photo.png',result['protected'])

    def test_indented_list_attachment_is_not_silently_treated_as_code(self):
        self.put('assets/a.png')
        original = '- item\n    ![photo](assets/a.png)\n'
        self.put('note.md', original)
        result = self.plan({'assets/a.png': 'attachments/a.png'})
        self.assertEqual([v['path'] for v in result['blockers']], ['note.md'])
        self.assertIn('Indented Markdown list', result['blockers'][0]['reason'])
        self.assertEqual((self.root / 'note.md').read_text(), original)

    def test_standalone_indented_code_stays_unchanged(self):
        self.put('assets/a.png')
        self.put('note.md', 'Code example:\n\n    ![photo](assets/a.png)\n')
        result = self.plan({'assets/a.png': 'attachments/a.png'})
        self.assertEqual(result['blockers'], [])
        self.assertEqual(result['edits'], {})

    def test_wiki_reserved_filename_characters_remain_encoded(self):
        self.put('assets/photo#1%|].png')
        self.put('note.md', '![[assets/photo%231%25%7C%5D.png#section|Alias]]')
        result = self.plan({'assets/photo#1%|].png': 'attachments/photo#1%|].png'})
        self.assertEqual(result['blockers'], [])
        self.assertEqual(result['edits']['note.md']['after'],
                         b'![[attachments/photo%231%25%7C%5D.png#section|Alias]]')

    def test_windows_casefold_resolution_and_unknown_reference_detection(self):
        self.put('Assets/Photo.PNG')
        self.put('notes/n.md', '![[assets/photo.png]] ![x](PHOTO.png)')
        self.put('data.base', 'file: PHOTO.png')
        with patch('vault_rag.attachment_references.path_key', side_effect=str.casefold):
            result = self.plan({'Assets/Photo.PNG': 'attachments/Photo.PNG'})
        self.assertEqual(result['references'], 2)
        self.assertEqual(result['edits']['notes/n.md']['after'],
                         b'![[attachments/Photo.PNG]] ![x](../attachments/Photo.PNG)')
        self.assertEqual([v['path'] for v in result['blockers']], ['data.base'])

    def test_windows_casefold_shared_project_dependency(self):
        self.put('Site/index.html', '<img src="../shared/photo.png">')
        self.put('Shared/Photo.PNG')
        with patch('vault_rag.attachment_references.path_key', side_effect=str.casefold):
            result = discover_project_dependencies(self.files, self.paths, {'site'})
        self.assertEqual(result['protected'], self.paths)
        self.assertEqual(result['blockers'], [])

    def test_svg_href_and_css(self):
        self.put('a.png')
        self.put('drawing.svg', '<svg><image xlink:href="a.png"/><image href="a.png"/></svg>')
        result = self.plan({'a.png': 'attachments/a.png'})
        self.assertEqual(result['blockers'], [])
        self.assertEqual(result['references'], 2)
        self.assertIn(b'xlink:href="attachments/a.png"', result['edits']['drawing.svg']['after'])


if __name__ == '__main__':
    unittest.main()
