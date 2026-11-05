"""Work-hub template and task merge contracts in isolated fictional workspaces."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from vault_rag.databases import Databases
from vault_rag.knowledge import Runtime
from vault_rag.local_state import ConflictError, LocalConfig
from vault_rag.skill_install import skill_source


SKILL = skill_source('leafloom').parent
spec = importlib.util.spec_from_file_location('work_hub_task_sync', SKILL / 'scripts/task_sync.py')
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)


class TaskSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.base = {'summary': 'Review', 'description': 'External text', 'assignees': ['u1'],
                     'due': {'timestamp': '1793433600000', 'is_all_day': False}, 'status': 'todo'}

    def test_independent_edits_pull_push_without_losing_local_changes(self):
        local, remote = copy.deepcopy(self.base), copy.deepcopy(self.base)
        local['summary'] = 'Local title'; remote['description'] = 'Remote description'
        result = merge.compare(self.base, local, remote)
        self.assertEqual(result['push'], {'summary': 'Local title'})
        self.assertEqual(result['pull'], {'description': 'Remote description'})
        self.assertEqual(result['conflicts'], {})
        self.assertEqual(result['agreed']['due'], self.base['due'])

    def test_same_field_conflict_and_same_new_value(self):
        local, remote = copy.deepcopy(self.base), copy.deepcopy(self.base)
        local['summary'] = 'Mine'; remote['summary'] = 'Theirs'
        self.assertEqual(merge.compare(self.base, local, remote)['conflicts']['summary']['remote'], 'Theirs')
        remote['summary'] = 'Mine'
        result = merge.compare(self.base, local, remote)
        self.assertEqual(result['conflicts'], {})
        self.assertEqual(result['agreed']['summary'], 'Mine')

    def test_missing_data_never_clears_remote_and_member_order_is_irrelevant(self):
        local, remote = copy.deepcopy(self.base), copy.deepcopy(self.base)
        del local['description']
        local['assignees'] = ['u2', 'u1']; remote['assignees'] = ['u1', 'u2']
        result = merge.compare(self.base, local, remote)
        self.assertIn('description', result['incomplete'])
        self.assertNotIn('description', result['push'])
        self.assertEqual(result['agreed']['assignees'], ['u1', 'u2'])

    def test_clearing_due_is_explicit_and_malformed_due_is_rejected(self):
        local = copy.deepcopy(self.base); local['due'] = None
        self.assertEqual(merge.compare(self.base, local, self.base)['push']['due'], None)
        local['due'] = {'timestamp': '1793433600000'}
        with self.assertRaises(ValueError):
            merge.compare(self.base, local, self.base)

    def test_cli_returns_machine_readable_error(self):
        result = subprocess.run([sys.executable, str(SKILL / 'scripts/task_sync.py')],
                                input='{}', text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)['ok'])

    def test_generic_due_preserves_provider_fields_and_detects_conflicts(self):
        base = copy.deepcopy(self.base)
        base['due'] = {'dateTime': '2026-11-02T17:30:00+09:00',
                       'timeZone': 'Asia/Tokyo', 'extra': {'allDay': False}}
        local, remote = copy.deepcopy(base), copy.deepcopy(base)
        local['summary'] = 'Local title'
        remote['due']['dateTime'] = '2026-11-03T17:30:00+09:00'
        result = merge.compare(base, local, remote, schema_version=2)
        self.assertEqual(result['push'], {'summary': 'Local title'})
        self.assertEqual(result['pull'], {'due': remote['due']})
        local['due']['dateTime'] = '2026-11-04T17:30:00+09:00'
        before = copy.deepcopy((base, local, remote))
        conflict = merge.compare(base, local, remote, schema_version=2)['conflicts']['due']
        self.assertEqual(conflict, {'baseline': base['due'], 'local': local['due'], 'remote': remote['due']})
        self.assertEqual((base, local, remote), before)

    def test_generic_missing_due_is_unknown_and_null_is_explicit_clear(self):
        base = {**self.base, 'due': {'date': '2026-11-02'}}
        local = {**base, 'due': None}
        self.assertEqual(merge.compare(base, local, base, 2)['push'], {'due': None})
        del local['due']
        result = merge.compare(base, local, base, 2)
        self.assertIn('due', result['incomplete'])
        self.assertEqual(result['push'], {})
        self.assertEqual(result['pull'], {})

    def test_generic_json_equality_preserves_types_and_ignores_key_order(self):
        base = {**self.base, 'due': {'flag': False, 'date': '2026-11-02'}}
        remote = {**base, 'due': {'date': '2026-11-02', 'flag': False}}
        self.assertIn('due', merge.compare(base, base, remote, 2)['agreed'])
        remote['due']['flag'] = 0
        self.assertEqual(merge.compare(base, base, remote, 2)['pull']['due']['flag'], 0)
        self.assertNotIn('due', merge.compare(base, base, remote, 2)['agreed'])

    def test_generic_cli_and_invalid_protocol_inputs(self):
        base = {**self.base, 'due': {'date': '2026-11-02', 'zone': 'Asia/Shanghai'}}
        result = subprocess.run([sys.executable, str(SKILL / 'scripts/task_sync.py')],
                                input=json.dumps({'schema_version': 2, 'baseline': base,
                                                  'local': base, 'remote': base}),
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(result.stdout)['agreed']['due'], base['due'])
        for version in (0, 3, '2', True, None):
            with self.subTest(version=version), self.assertRaises(ValueError):
                merge.compare(base, base, base, version)
        for due in ('2026-11-02', [], {'value': float('nan')}, {1: 'not a JSON key'}):
            invalid = {**base, 'due': due}
            with self.subTest(due=due), self.assertRaises(ValueError):
                merge.compare(invalid, invalid, invalid, 2)


class WorkHubDatabaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name); self.root = self.home / 'vault'; self.root.mkdir()
        folder = self.root / '工作中枢'; (folder / '数据').mkdir(parents=True)
        self.path = '工作中枢/工作台.base'
        (self.root / self.path).write_bytes((SKILL / 'assets/workspace.base').read_bytes())
        self.config = LocalConfig(self.home / 'state')
        self.config.save({'root': str(self.root), 'include_roots': []})
        self.runtime = Runtime(self.config); self.addCleanup(self.runtime.stop)
        self.db = Databases(self.config, self.runtime); self.ws = self.config.data['revision']
        self.runtime.catalog.scan()
        self.c = self.db.config_read(self.path)
        self.db.validate_config(copy.deepcopy(self.c['config']))

    def command(self, command, operation=''):
        result = self.db.command(self.path, command, self.ws, self.c['revision'], operation)
        self.runtime.catalog.scan(); self.c = self.db.config_read(self.path)
        return result

    def test_multi_project_one_activity_and_view_isolation(self):
        for key in ('projects', 'candidate_projects'):
            self.command({'type': 'field.set', 'key': key, 'field': {'options': ['p1', 'p2'],
                          'optionMeta': {'p1': {'label': 'HMIRP'}, 'p2': {'label': 'HMI Harness'}}}})
        command = {'type': 'record.create', 'title': '定位性能问题', 'view_id': 'activities',
                   'values': {'record_id': 'a1', 'record_key': 'capture-1', 'projects': ['p1', 'p2'],
                              'actual_hours': 2, 'work_date': '2026-10-31', 'work_end_date': '2026-10-31',
                              'review_state': 'ready'}}
        first = self.command(command, 'capture-1')
        self.assertEqual(self.command(command, 'capture-1')['path'], first['path'])
        self.command({'type': 'record.create', 'title': 'Project', 'view_id': 'projects',
                      'values': {'project_id': 'p1'}}, 'project-1')
        rows = self.db.query(self.path, 'activities')['results']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['metadata']['projects'], ['p1', 'p2'])
        self.assertEqual(sum(r['metadata'].get('actual_hours', 0) for r in rows), 2)
        self.assertEqual(self.db.query(self.path, 'projects')['total'], 1)
        self.assertEqual(self.db.query(self.path, 'tasks')['total'], 0)
        self.assertEqual(self.config.data['include_roots'], [])

    def test_stale_correction_preserves_personal_body(self):
        result = self.command({'type': 'record.create', 'title': 'Draft', 'view_id': 'activities',
                               'values': {'review_state': 'needs_review'}}, 'draft')
        path = self.root / result['path']; path.write_text(path.read_text() + '\n原话与个人笔记\n')
        self.runtime.catalog.scan()
        with self.assertRaises(ConflictError):
            self.command({'type': 'record.update', 'path': result['path'],
                          'record_revision': result['revision'], 'values': {'review_state': 'ready'}})
        self.assertIn('原话与个人笔记', path.read_text())
        self.assertEqual(self.db.query(self.path, 'review')['total'], 1)

    def test_generic_task_round_trip_preserves_exact_due_and_sync_metadata(self):
        exact_due = json.dumps({'timestamp': '1793433600000', 'is_all_day': False})
        self.command({'type': 'record.create', 'title': 'Review', 'view_id': 'tasks', 'values': {
            'record_id': 't1', 'record_key': 'feishu:task:guid-1', 'tags': ['task'],
            'source_provider': 'feishu', 'source_kind': 'task', 'source_id': 'guid-1',
            'due': '2026-10-31', 'external_due': exact_due,
            'sync_baseline': '{}', 'sync_state': 'synced', 'status': 'open'}}, 'task-1')
        row = self.db.query(self.path, 'tasks')['results'][0]
        self.assertEqual(row['metadata']['external_due'], exact_due)
        self.assertIn('task', row['metadata']['tags'])
        self.assertEqual(self.db.query(self.path, 'activities')['total'], 0)

    def test_local_task_needs_no_external_identity_or_connection(self):
        self.command({'type': 'record.create', 'title': 'Prepare weekly report', 'view_id': 'tasks',
                      'values': {'record_id': 'local-1', 'record_key': 'manual:task:local-1',
                                 'tags': ['task'], 'status': 'open', 'due': '2026-11-02'}}, 'local-task')
        row = self.db.query(self.path, 'tasks')['results'][0]
        self.command({'type': 'record.update', 'path': row['file']['path'],
                      'record_revision': self.db.files.read(row['file']['path'])['etag'],
                      'values': {'status': 'done'}})
        saved = self.db.query(self.path, 'tasks')['results'][0]['metadata']
        self.assertEqual(saved['status'], 'done')
        self.assertNotIn('source_id', saved)
        self.assertNotIn('sync_state', saved)
        self.assertEqual(self.config.data['include_roots'], [])

    def test_same_remote_id_is_separate_for_different_providers(self):
        for provider in ('feishu', 'fictional-office'):
            self.command({'type': 'record.create', 'title': 'Review', 'view_id': 'tasks', 'values': {
                'record_id': provider + '-1', 'record_key': provider + ':task:shared-id',
                'source_provider': provider, 'source_kind': 'task', 'source_id': 'shared-id',
                'tags': ['task'], 'status': 'open'}}, provider + '-capture')
        rows = self.db.query(self.path, 'tasks')['results']
        self.assertEqual(len(rows), 2)
        self.assertEqual({r['metadata']['source_provider'] for r in rows}, {'feishu', 'fictional-office'})
        for provider in ('feishu', 'fictional-office'):
            self.command({'type': 'view.add', 'view': {'type': 'table', 'name': provider,
                'order': ['title', 'source_provider', 'source_id'], 'leafloom': {
                    'id': 'only-' + provider, 'conditions': [
                        {'field': 'record_type', 'operator': 'eq', 'value': 'task'},
                        {'field': 'source_provider', 'operator': 'eq', 'value': provider},
                        {'field': 'source_id', 'operator': 'eq', 'value': 'shared-id'}]}}})
            selected = self.db.query(self.path, 'only-' + provider)
            self.assertEqual(selected['total'], 1)
            self.assertEqual(selected['results'][0]['metadata']['record_id'], provider + '-1')

    def test_legacy_workspace_additive_upgrade_preserves_notes_and_custom_config(self):
        # Reconstruct a v1 workspace with provider fields and a personal layout.
        original = copy.deepcopy(self.c['config'])
        fields = original['leafloom']['fields']
        for key in ('source_provider', 'external_due', 'external_updated_at', 'external_description'):
            fields.pop(key)
            original['properties'].pop(key)
        for key in ('feishu_guid', 'feishu_due', 'feishu_updated_at', 'feishu_description'):
            fields[key] = {'type': 'text'}
        fields['personal_flag'] = {'type': 'text'}
        fields['source_kind']['options'] = ['manual', 'feishu_doc', 'feishu_chat',
                                            'feishu_meeting', 'feishu_task', 'gitlab']
        fields['source_kind']['optionMeta'] = {'feishu_task': {'label': 'My tasks'}}
        original['leafloom']['workHubVersion'] = 1
        for view in original['views']:
            view['order'] = [key for key in view['order'] if key != 'source_provider']
            if 'detailFields' in view.get('leafloom', {}):
                view['leafloom']['detailFields'] = [key for key in view['leafloom']['detailFields']
                                                   if key != 'source_provider']
        original['views'][2]['name'] = 'Personal task layout'
        (self.root / self.path).write_text(yaml.safe_dump(original, allow_unicode=True, sort_keys=False))
        self.runtime.catalog.scan(); self.c = self.db.config_read(self.path)
        due = json.dumps({'timestamp': '1793433600000', 'is_all_day': False})
        baseline = json.dumps({
            'summary': 'Review', 'description': 'Remote', 'assignees': [],
            'due': json.loads(due), 'status': 'todo'})
        created = self.command({'type': 'record.create', 'title': 'Review', 'view_id': 'tasks', 'values': {
            'record_id': 'legacy-1', 'record_key': 'feishu:task:guid-1', 'tags': ['task'],
            'source_kind': 'feishu_task', 'feishu_guid': 'guid-1', 'feishu_due': due,
            'feishu_description': 'Remote', 'actual_hours': 2, 'sync_baseline': baseline,
            'status': 'open', 'personal_flag': 'keep'}}, 'legacy-create')
        note_path = self.root / created['path']
        note_path.write_text(note_path.read_text() + '\n原文与个人笔记\n')
        self.runtime.catalog.scan()
        for key in ('source_provider', 'external_due', 'external_updated_at', 'external_description'):
            self.command({'type': 'field.set', 'key': key, 'field': {'type': 'text'}})
        kind = copy.deepcopy(self.c['config']['leafloom']['fields']['source_kind'])
        kind['options'].append('task')
        self.command({'type': 'field.set', 'key': 'source_kind', 'field': kind})
        self.command({'type': 'record.update', 'path': created['path'],
                      'record_revision': self.db.files.read(created['path'])['etag'], 'values': {
                          'source_provider': 'feishu', 'source_id': 'guid-1',
                          'external_due': due, 'external_description': 'Remote'}})
        rows = self.db.query(self.path, 'tasks')['results']
        self.assertEqual(len(rows), 1)
        saved = rows[0]['metadata']
        for key, value in {'record_id': 'legacy-1', 'record_key': 'feishu:task:guid-1',
                           'sync_baseline': baseline, 'actual_hours': 2, 'personal_flag': 'keep',
                           'feishu_due': due, 'external_due': due}.items():
            self.assertEqual(saved[key], value)
        self.assertIn('原文与个人笔记', note_path.read_text())
        self.assertEqual(self.c['config']['views'], original['views'])
        self.assertEqual(self.c['config']['leafloom']['fields']['source_kind']['optionMeta'],
                         kind['optionMeta'])
        self.assertEqual(merge.compare(json.loads(baseline), json.loads(baseline),
                                       json.loads(baseline), 2)['agreed']['due'], json.loads(due))
