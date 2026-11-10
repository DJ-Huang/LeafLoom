"""HTML project local assets and one-off localization script."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

from vault_rag.attachment_references import discover_project_dependencies
from vault_rag.html_projects import HtmlProjects
from vault_rag.knowledge import Runtime
from vault_rag.local_state import LocalConfig

_SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'localize_html_attachments.py'
_SPEC = importlib.util.spec_from_file_location('localize_html_attachments', _SCRIPT)
_MOD = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_MOD)
plan = _MOD.plan
apply_plan = _MOD.apply_plan


class HtmlAssetApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.root = self.home / 'vault'
        self.root.mkdir()
        self.config = LocalConfig(self.home / 'state')
        self.config.save({'root': str(self.root)})
        self.websites = HtmlProjects(self.config, 8765)

    def tearDown(self):
        self.temp.cleanup()

    def put(self, path, data=b'fixture'):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data if isinstance(data, bytes) else data.encode())
        return target

    def test_html_project_assets_api_writes_under_assets(self):
        self.put('site/index.html', '<html></html>')
        project = self.websites.register(str(self.root), 'site', 'site/index.html')
        result = self.websites.write_asset(str(self.root), project['id'], 'photo.png', b'png-bytes')
        self.assertEqual(result['path'], 'site/assets/photo.png')
        self.assertEqual((self.root / 'site/assets/photo.png').read_bytes(), b'png-bytes')

    def test_project_seeded_discovery_still_finds_central_dependency(self):
        self.put('_attachments/keep.png', b'keep')
        self.put('site/index.html', '<img src="../_attachments/shared.png">')
        self.put('_attachments/shared.png', b'shared')
        runtime = Runtime(self.config)
        try:
            files = runtime.files
            paths = {p.relative_to(self.root).as_posix() for p in files.walk(strict=True)}
            protected = discover_project_dependencies(files, paths, {'site'}, reference_sources=())
            self.assertIn('_attachments/shared.png', protected['protected'])
            self.assertNotIn('_attachments/keep.png', protected['protected'])
        finally:
            runtime.stop()

    def test_script_moves_project_under_attachments_to_web(self):
        self.put('_attachments/mysite/index.html', '<img src="logo.png">')
        self.put('_attachments/mysite/logo.png', b'logo')
        project = self.websites.register(str(self.root), '_attachments/mysite', '_attachments/mysite/index.html')
        planned = plan(self.config, self.websites)
        self.assertFalse(planned['blockers'], planned['blockers'])
        self.assertEqual({m['source'] for m in planned['moves']}, {
            '_attachments/mysite/index.html', '_attachments/mysite/logo.png'})
        apply_plan(self.config, self.websites, planned)
        self.assertTrue((self.root / 'Web/mysite/index.html').is_file())
        self.assertTrue((self.root / 'Web/mysite/logo.png').is_file())
        self.assertFalse((self.root / '_attachments/mysite/index.html').exists())
        updated = next(p for p in self.websites.projects if p['id'] == project['id'])
        self.assertEqual(updated['directory'], 'Web/mysite')
        self.assertEqual(updated['entry'], 'Web/mysite/index.html')

    def test_script_moves_central_dependency_and_rewrites_static_src(self):
        self.put('site/index.html', '<img src="../_attachments/hero.png">')
        self.put('_attachments/hero.png', b'hero-bytes')
        self.websites.register(str(self.root), 'site', 'site/index.html')
        planned = plan(self.config, self.websites)
        self.assertFalse(planned['blockers'], planned['blockers'])
        self.assertEqual([m['source'] for m in planned['moves']], ['_attachments/hero.png'])
        apply_plan(self.config, self.websites, planned)
        self.assertTrue((self.root / 'site/assets/hero.png').is_file())
        self.assertFalse((self.root / '_attachments/hero.png').exists())
        html = (self.root / 'site/index.html').read_text(encoding='utf-8')
        self.assertIn('assets/hero.png', html)
        self.assertNotIn('_attachments/hero.png', html)

    def test_script_reports_script_blockers(self):
        self.put('site/index.html', '<script>fetch("../_attachments/data.json")</script><img src="../_attachments/hero.png">')
        self.put('_attachments/hero.png', b'hero')
        self.put('_attachments/data.json', b'{}')
        self.websites.register(str(self.root), 'site', 'site/index.html')
        planned = plan(self.config, self.websites)
        self.assertTrue(planned['blockers'], planned)


class HtmlLocalizeRemotePlanTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        import httpx
        from vault_rag.attachment_policy import DEFAULT_EXTENSIONS
        from vault_rag.remote_attachments import RemoteAttachments
        from tests.test_remote_attachments import SOURCE, SECRET, FakeDAV
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.root = self.home / 'vault'
        self.root.mkdir()
        self.config = LocalConfig(self.home / 'state')
        self.config.save({'root': str(self.root)})
        self.dav = FakeDAV()
        self.transport = httpx.MockTransport(self.dav)
        with patch.object(RemoteAttachments, '_loop', return_value=None):
            self.manager = RemoteAttachments(self.config)
        self.manager.transports[SOURCE] = self.transport
        self.manager.save(str(self.root), {'allowed_extensions': [*DEFAULT_EXTENSIONS, '.bin'], 'sources': [{
            'id': SOURCE, 'name': 'Fixture', 'type': 'webdav', 'base_url': 'http://127.0.0.1:10000/', 'remote_root': '',
            'username': 'leafloom', 'enabled': True, 'allow_private_http': True, 'upload_directory': 'Incoming',
            'secret_ref': 'fixture-reference', 'connection_hint': 'official-client'}], 'default_source': SOURCE})
        self.manager.set_credentials(SOURCE, 'stale-username', SECRET, revision='stable-revision')
        self.websites = HtmlProjects(self.config, 8765)
        self.manager.runtime = type('Runtime', (), {'websites': self.websites})()

    def tearDown(self):
        self.manager.stop()
        self.temp.cleanup()

    def put(self, path, data=b'fixture-bytes'):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def test_migration_plan_skips_registered_html_project_files(self):
        from tests.test_remote_attachments import SOURCE
        self.put('_attachments/photo.png', b'top')
        self.put('_attachments/webapp/index.html', b'<img src="a.png">')
        self.put('_attachments/webapp/a.png', b'a')
        self.websites.register(str(self.root), '_attachments/webapp', '_attachments/webapp/index.html')
        plan_result = self.manager.migration_plan(str(self.root), SOURCE)
        self.assertEqual([item['path'] for item in plan_result['items']], ['_attachments/photo.png'])
        reasons = {item['path']: item['reason'] for item in plan_result['exclusions']}
        self.assertIn('_attachments/webapp/a.png', reasons)
        self.assertIn('_attachments/webapp/index.html', reasons)


if __name__ == '__main__':
    unittest.main()
