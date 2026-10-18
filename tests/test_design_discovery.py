"""Incremental Design Studio project discovery without running project code."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from vault_rag.design_studio import DesignStudio
from vault_rag.events import Changes
from vault_rag.local_state import Files, LocalConfig


class DesignDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = (Path(self.temp.name) / 'vault').resolve()
        self.root.mkdir()
        self.config = LocalConfig(Path(self.temp.name) / 'config')
        self.config.save({'root': str(self.root)})
        self.runtime = SimpleNamespace(files=Files(self.config), events=Changes(), catalog=SimpleNamespace(version=1))
        websites = SimpleNamespace(register=lambda *args, **kwargs: {'id': 'test-project'})
        self.studio = DesignStudio(self.config, self.runtime, websites)

    def tearDown(self):
        self.temp.cleanup()

    def project(self, directory, name='Pets'):
        target = self.root / directory
        (target / 'Design').mkdir(parents=True, exist_ok=True)
        (target / 'Design/project-spec.json').write_text(json.dumps({'project': {'id': directory, 'name': name}}))
        return target

    def test_unchanged_lists_use_summary_cache_and_do_not_walk_directories(self):
        self.project('Projects/Pets')
        (self.root / 'Notes/Deep/Unrelated').mkdir(parents=True)
        first = self.studio.list_projects()
        with patch.object(self.studio, '_project_summary', wraps=self.studio._project_summary) as summary:
            with patch.object(Path, 'iterdir', side_effect=AssertionError('An unchanged directory was walked')):
                second = self.studio.list_projects()
            self.assertEqual(summary.call_count, 0)
        self.assertEqual(first['projects'], second['projects'])

    def test_source_stat_refreshes_summary_and_workspace_override_does_not_pollute_cache(self):
        target = self.project('Projects/Pets')
        self.studio.list_projects()
        (target / 'Design/project-spec.json').write_text(json.dumps({'project': {'id': 'pets', 'name': 'New source name'}}))
        self.assertEqual(self.studio.list_projects()['projects'][0]['name'], 'New source name')
        self.studio.workspace.manage('Projects/Pets', 'rename', self.studio.workspace.state()['revision'], 'rename-project', value='Display name')
        self.assertEqual(self.studio.list_projects()['projects'][0]['name'], 'Display name')
        self.studio.workspace.history('undo', self.studio.workspace.state()['revision'])
        self.assertEqual(self.studio.list_projects()['projects'][0]['name'], 'New source name')

    def test_new_branch_scan_preserves_unrelated_directory_index(self):
        self.project('Projects/Pets')
        (self.root / 'Notes/Deep/Unrelated').mkdir(parents=True)
        self.studio.list_projects()
        self.project('Projects/Dogs', 'Dogs')
        walked = []
        original = Path.iterdir

        def iterdir(path):
            walked.append(path.relative_to(self.root).as_posix())
            return original(path)

        with patch.object(Path, 'iterdir', iterdir):
            projects = self.studio.list_projects()['projects']
        self.assertEqual({project['name'] for project in projects}, {'Pets', 'Dogs'})
        self.assertFalse(any(path.startswith('Notes') for path in walked))

    def test_spec_created_in_existing_design_directory_and_project_removed(self):
        (self.root / 'Projects/Pets/Design').mkdir(parents=True)
        self.assertEqual(self.studio.list_projects()['projects'], [])
        target = self.project('Projects/Pets')
        self.assertEqual(len(self.studio.list_projects()['projects']), 1)
        (target / 'Design/project-spec.json').unlink()
        nested = self.project('Projects/Pets/Subproject', 'Nested')
        self.assertEqual(self.studio.list_projects()['projects'][0]['directory'], nested.relative_to(self.root).as_posix())


if __name__ == '__main__':
    unittest.main()
