"""Legacy metadata edits preserve authored JavaScript; recovery modifies copies."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from vault_rag.design_literals import declarations, literal_values, marked_screen_data, screen_literals
from vault_rag.design_studio import DesignStudio
from vault_rag.events import Changes
from vault_rag.local_state import Files, LocalConfig


class LegacyMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.root = self.home / 'vault'
        self.root.mkdir()
        self.config = LocalConfig(self.home / 'config')
        self.config.save({'root': str(self.root)})
        runtime = SimpleNamespace(files=Files(self.config), events=Changes(), catalog=SimpleNamespace(version=0))
        websites = SimpleNamespace(register=lambda *a, **kw: {'id': 'project'}, create=lambda *a, **kw: {'id': 'session', 'origin': 'http://localhost:1000'})
        self.studio = DesignStudio(self.config, runtime, websites)
        self.path = self.root / 'screens.js'

    def tearDown(self):
        self.temp.cleanup()

    def test_marked_update_preserves_custom_declarations_functions_exports_and_crlf(self):
        self.studio._write_screens_js(self.path, [{'id': 'home'}], [])
        source = self.path.read_text()
        prefix = 'const gameFrame = {width:720,height:1402,board:{left:72,top:515,width:576,height:552}};\r\n'
        suffix = '\r\nfunction authoredResolver(id) { return id === "alias" ? "home" : id; }\r\nmodule.exports.gameFrame = gameFrame;\r\n'
        self.path.write_bytes((prefix + source + suffix).encode())
        old = self.path.read_bytes()
        self.studio._write_screens_js(self.path, [{'id': 'home'}, {'id': 'new-page'}], [])
        result = self.path.read_bytes()
        self.assertTrue(result.startswith(prefix.encode()))
        self.assertTrue(result.endswith(suffix.encode()))
        self.assertEqual([page['id'] for page in marked_screen_data(result.decode())['screens']], ['home', 'new-page'])
        # Everything outside the owned marker span is retained exactly.
        begin, end = b'/*__LEAFLOOM_SCREENS_JSON__*/', b'/*__END_LEAFLOOM_SCREENS_JSON__*/'
        self.assertEqual(old.split(begin)[0], result.split(begin)[0])
        self.assertEqual(old.split(end)[1], result.split(end)[1])

    def test_raw_literal_update_preserves_custom_resolver_constants_and_other_exports(self):
        frame = "const gameFrame = {width:720,height:1402,board:{left:72,top:515,width:576,height:552}};"
        resolver = "function resolveBoardId(id) { return /^alias[{}]$/.test(id) ? 'home' : id; }"
        exports = 'module.exports = {screens, variants, boards, gameFrame, resolveBoardId, custom:true};'
        source = '\n'.join((frame, "const screens = [{id:'home',width:gameFrame.width,height:gameFrame.height}];", 'const variants = [];', 'const boards = [...screens,...variants];', resolver, exports))
        self.path.write_text(source)
        with patch('subprocess.run', side_effect=AssertionError('Project JavaScript must never execute')):
            self.studio._write_screens_js(self.path, [{'id': 'home'}, {'id': 'new'}], [{'id': 'dialog'}])
            parsed = self.studio._parse_screens_file(self.path)
        result = self.path.read_text()
        for authored in (frame, resolver, exports):
            self.assertIn(authored, result)
        self.assertEqual([page['id'] for page in parsed[2]], ['home', 'new', 'dialog'])

    def test_multiple_bindings_semicolonless_code_and_marker_text_in_string(self):
        source = "const fake = '/*__LEAFLOOM_SCREENS_JSON__*/{}/*__END_LEAFLOOM_SCREENS_JSON__*/';\nconst screens=[{id:'home'}], variants=[], boards=[...screens,...variants];\nfunction keep(){return /[{}]/.test('{}');}"
        self.path.write_text(source)
        self.studio._write_screens_js(self.path, [{'id': 'new'}], [])
        self.assertIn(source.split('\n')[0], self.path.read_text())
        self.assertEqual(screen_literals(self.path.read_text())[0][0]['id'], 'new')
        semicolonless = "const screens=[{id:'home'}]\nconst variants=[]\nconst boards=[...screens,...variants]\nfunction keep(){}"
        self.path.write_text(semicolonless)
        self.studio._write_screens_js(self.path, [{'id': 'updated'}], [])
        self.assertEqual(screen_literals(self.path.read_text())[0][0]['id'], 'updated')
        self.assertIn('function keep(){}', self.path.read_text())
        no_semicolon = "const screens=[{id:'home'}]\nwindow.custom = () => 'preserved'\nconst variants=[]\nmodule.exports.extra = 'preserved'\nconst boards=[...screens,...variants]\n"
        self.path.write_text(no_semicolon)
        self.studio._write_screens_js(self.path, [{'id': 'updated'}], [])
        self.assertIn("window.custom = () => 'preserved'", self.path.read_text())
        self.assertIn("module.exports.extra = 'preserved'", self.path.read_text())

    def test_unsafe_unknown_structure_is_rejected_without_overwriting(self):
        original = b"const {screens}=loadMetadata(); function keep(){return 'keep';}"
        self.path.write_bytes(original)
        with self.assertRaises(ValueError):
            self.studio._write_screens_js(self.path, [{'id': 'new'}], [])
        self.assertEqual(self.path.read_bytes(), original)
        executable = b"const screens=loadCustomScreens(); const variants=[]; const boards=screens; function keep(){return 1;}"
        self.path.write_bytes(executable)
        with self.assertRaises(ValueError):
            self.studio._write_screens_js(self.path, [{'id': 'new'}], [])
        self.assertEqual(self.path.read_bytes(), executable)

    def test_literal_reader_rejects_executable_recovery_candidates(self):
        values = literal_values("const danger=globalThis.sideEffect();const safe={width:720, nested:{left:72}};const alias=safe.nested;const computed=720+1;")
        self.assertNotIn('danger', values)
        self.assertNotIn('computed', values)
        self.assertEqual(values['alias'], {'left': 72})

    def test_native_renderer_rejects_unsupported_page_writes_before_any_file_changes(self):
        self.studio.create_project('Projects/Legacy', 'Pets')
        source = self.root / 'Projects/Legacy'
        runtime = source / 'Design/UI/Site/artboards.js'
        runtime.write_text("function renderBoard(page) { switch(page.kind) {case 'home': return '<p>Home</p>'; default:return '';}}\n// CUSTOM_ARTBOARDS[screen.id] is not a loader when commented out\n")

        def snapshot():
            return {path.relative_to(self.root).as_posix(): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}

        before = snapshot()
        with self.assertRaisesRegex(ValueError, 'managed copy'):
            self.studio.upsert_screen('Projects/Legacy', 'unknown-page', 'New page')
        self.assertEqual(snapshot(), before)
        with self.assertRaisesRegex(ValueError, 'managed copy'):
            self.studio.upsert_screen('Projects/Legacy', 'home', 'Home', html='<p>New override</p>')
        self.assertEqual(snapshot(), before)
        renamed = self.studio.upsert_screen('Projects/Legacy', 'home', 'Renamed home')
        self.assertEqual(renamed['project']['screens'][0]['name'], 'Renamed home')
        migrated = self.studio.workspace.migrate('Projects/Legacy', 'Projects/Converted')
        self.assertEqual(migrated['document']['migration']['status'], 'capture_required')
        self.assertEqual(migrated['document']['migration']['boards'][0]['name'], 'Renamed home')
        self.assertEqual(runtime.read_text().splitlines()[0], "function renderBoard(page) { switch(page.kind) {case 'home': return '<p>Home</p>'; default:return '';}}")

    def test_generated_legacy_renderer_keeps_supporting_custom_pages(self):
        self.studio.create_project('Projects/Template', 'Pets')
        result = self.studio.upsert_screen('Projects/Template', 'custom', 'Custom page', html='<p>Custom</p>')
        self.assertEqual(result['project']['board_count'], 4)
        self.assertIn('<p>Custom</p>', (self.root / 'Projects/Template/Design/UI/Site/custom-screens.js').read_text())

    def test_migration_recovers_missing_frame_only_in_copy_and_keeps_newest_31_boards(self):
        self.studio.create_project('Projects/Legacy', 'Pets')
        source = self.root / 'Projects/Legacy'
        site = source / 'Design/UI/Site'
        boards = [{'id': f'board-{index}', 'name': f'Page {index}', 'width': 720, 'height': 1560} for index in range(31)]
        self.studio._write_screens_js(site / 'screens.js', boards, [])
        source_bytes = (site / 'screens.js').read_bytes()
        (site / 'artboards.js').write_text('const boardStyle = Object.entries(gameFrame.board);\n// never recover danger()\n')
        backup = source / 'Design/Assets/source/screens.js'
        backup.parent.mkdir(parents=True)
        backup.write_text("const gameFrame={width:720,height:1402,board:{left:72,top:515,width:576,height:552}};const unused=123;const danger=sideEffect();const screens=[{id:'old-home'}];const variants=[];const boards=[...screens,...variants];")
        with patch('subprocess.run', side_effect=AssertionError('Recovery must not execute source')):
            migrated = self.studio.workspace.migrate('Projects/Legacy', 'Projects/Converted')
        copied = self.root / 'Projects/Converted'
        repaired = (copied / 'Design/UI/Site/screens.js').read_text()
        self.assertEqual((site / 'screens.js').read_bytes(), source_bytes)
        self.assertEqual(literal_values(repaired)['gameFrame']['board']['top'], 515)
        self.assertNotIn('unused', {item['name'] for item in declarations(repaired)})
        self.assertEqual(len(self.studio._parse_screens_file(copied / 'Design/UI/Site/screens.js')[2]), 31)
        self.assertEqual(migrated['document']['migration']['boards'][-1]['id'], 'board-30')
        self.assertEqual([item['name'] for item in migrated['document']['migration']['recovery']], ['gameFrame'])
        self.assertEqual(self.studio.workspace._recover_legacy_declarations(copied), [])


if __name__ == '__main__':
    unittest.main()
