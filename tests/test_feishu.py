"""Feishu adapter contracts using a fictional CLI; no cloud documents are touched."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from vault_rag.feishu import Feishu, FeishuError, run_cli
from vault_rag.mcp_access import McpAccess


def envelope(data):
    return 0, json.dumps({'ok': True, 'identity': 'user', 'data': data}), ''


class FeishuTests(unittest.TestCase):
    def test_document_block_table_reference_is_not_an_auth_error(self):
        error = Feishu._failure({'error': {'type': 'api', 'subtype': 'unknown', 'code': 800010116,
                                           'message': 'invalid_request: reference resolves to a docx block'}})
        self.assertEqual(error.code, 'invalid_request')
        self.assertEqual(error.details['error_source'], 'feishu_cli')
        self.assertEqual(error.details['missing_scopes'], [])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config = SimpleNamespace(directory=Path(temp.name))
        self.service = Feishu(self.config)
        self.service.configure({'enabled': True, 'binary': sys.executable, 'profile': 'work'})
        self.calls = []
        self.status = {'appId': 'fictional-app', 'identity': 'bot', 'verified': True,
                       'identities': {'user': {'available': True, 'verified': True, 'userName': 'Example',
                                              'openId': 'ou_example', 'access_token': 'never-save'}}}
        self.result = envelope({'document': {'revision_id': 12}, 'has_more': True, 'page_token': 'next'})
        self.schema = [{'id': 'fld_title', 'name': 'Title', 'type': 'text'},
                       {'id': 'fld_formula', 'name': 'Computed', 'type': 'formula'},
                       {'id': 'fld_status', 'name': 'Status', 'type': 'select', 'options': [{'name': 'Done'}]}]
        self.runner = patch('vault_rag.feishu.run_cli', side_effect=self.fake)
        self.runner.start(); self.addCleanup(self.runner.stop)

    def fake(self, binary, args, **kwargs):
        self.calls.append((list(args), kwargs))
        if '--help' in args:
            return 0, ' '.join(flag for flags in Feishu.COMMANDS.values() for flag in flags) + ' --as --format', ''
        if args == ['--version']: return 0, 'lark-cli version 1.0.66', ''
        if args[:2] == ['auth', 'status']: return 0, json.dumps(self.status), ''
        if args[:2] == ['base', '+field-list']:
            return envelope({'fields': self.schema, 'total': len(self.schema)})
        return self.result

    def test_verify_user_not_bot_and_persist_only_allowlisted_status(self):
        self.assertEqual(self.service.verify()['verification']['state'], 'connected')
        saved = self.service.path.read_text()
        self.assertNotIn('never-save', saved)
        self.assertNotIn('access_token', saved)
        self.assertEqual(Feishu(self.config).status()['verification']['user_name'], 'Example')
        self.service.configure({'profile': 'personal'})
        self.assertEqual(self.service.status()['verification'], {'state': 'unchecked'})
        self.status['identities']['user']['available'] = False
        self.assertEqual(self.service.verify()['verification']['state'], 'not_logged_in')

    def test_verification_states(self):
        for status, expected in [({'identities': {}}, 'not_configured'),
                                 ({'appId': 'app', 'identities': {'user': {'available': True, 'verified': False}}}, 'login_expired')]:
            self.status = status
            self.assertEqual(self.service.verify()['verification']['state'], expected)
        for code, expected in [('cli_not_installed', 'not_installed'), ('cli_incompatible', 'incompatible'),
                               ('cli_timeout', 'network_error'), ('network_error', 'network_error'),
                               ('not_configured', 'not_configured')]:
            with patch.object(self.service, '_compatible', side_effect=FeishuError(code, 'fixture')):
                self.assertEqual(self.service.verify()['verification']['state'], expected)

    def test_incompatible_command_does_not_run_auth(self):
        with patch('vault_rag.feishu.run_cli', return_value=(0, 'missing flags', '')):
            self.assertEqual(self.service.verify()['verification']['state'], 'incompatible')
        self.assertFalse(any(args[:2] == ['auth', 'status'] for args, _ in self.calls))

    def test_document_arguments_stdin_revision_and_profile(self):
        body = '@private-file\n中文 & $(do-not-execute) `literal`'
        self.service.docs_write('append', body, 'https://example.feishu.cn/wiki/example', expected_revision=12)
        args, options = self.calls[-1]
        self.assertEqual(options['content'], body)
        self.assertEqual(options['profile'], 'work')
        self.assertNotIn(body, args)
        self.assertIn('--content=-', args)
        self.assertIn('--revision-id=12', args)
        self.assertIn('--as=user', args)
        for revision in (None, -1, 0, True):
            with self.assertRaises(ValueError): self.service.docs_write('append', body, 'example', expected_revision=revision)
        self.service.docs_read('search', query='--as=bot', page_token='next', limit=20)
        self.assertIn('--query=--as=bot', self.calls[-1][0])
        self.assertIn('--page-token=next', self.calls[-1][0])

    def test_errors_do_not_echo_cli_credentials_and_never_retry(self):
        self.result = (1, '', json.dumps({'ok': False, 'error': {'type': 'auth', 'subtype': 'permission_denied',
                        'message': 'scope missing: never-echo', 'missing_scopes': ['base:record:update']}}))
        with self.assertRaises(FeishuError) as raised:
            self.service.docs_read('fetch', document='example')
        self.assertEqual(raised.exception.code, 'permission_denied')
        self.assertEqual(raised.exception.details['missing_scopes'], ['base:record:update'])
        self.assertNotIn('never-echo', str(raised.exception))
        self.assertEqual(sum(args[:2] == ['docs', '+fetch'] and '--help' not in args for args, _ in self.calls), 1)
        self.result = envelope({'result': 'partial_success'})
        with self.assertRaises(FeishuError) as partial:
            self.service.docs_write('create', 'body', title='Title')
        self.assertEqual(partial.exception.code, 'partial_write')
        self.result = envelope({'record': {'ignored_fields': ['Title']}})
        with self.assertRaises(FeishuError) as ignored:
            self.service.base_write('update_record', 'base_example', 'tbl_example', {'Title': 'New'}, 'rec_example')
        self.assertEqual(ignored.exception.code, 'partial_write')

    def test_invalid_json_and_identity_are_errors(self):
        for response, code in [((0, 'not json', ''), 'invalid_cli_response'),
                               ((0, '{"identity":"user","data":{}}', ''), 'invalid_cli_response'),
                               ((0, '{"ok":true,"identity":"bot","data":{}}', ''), 'identity_mismatch')]:
            self.result = response
            with self.assertRaises(FeishuError) as raised: self.service.docs_read('fetch', document='example')
            self.assertEqual(raised.exception.code, code)

    def test_stale_document_revision_never_submits_a_write(self):
        with self.assertRaises(FeishuError) as stale:
            self.service.docs_write('append', 'must not write', document='example', expected_revision=11)
        self.assertEqual(stale.exception.code, 'write_conflict')
        self.assertEqual(stale.exception.details['current_revision'], 12)
        self.assertFalse(any(args[:2] == ['docs', '+update'] and '--help' not in args for args, _ in self.calls))

    def test_base_schema_and_exact_patch(self):
        self.service.base_write('update_record', 'base_example', 'tbl_example', {'Title': 'Updated'}, 'rec_example')
        args, _ = self.calls[-1]
        self.assertIn('--record-id=rec_example', args)
        payload = json.loads(next(a.removeprefix('--json=') for a in args if a.startswith('--json=')))
        self.assertEqual(payload, {'Title': 'Updated'})
        for fields in ({'Computed': 'bad'}, {'Missing': 1}, {'Status': 'New option'}, {'Title': 'a', 'fld_title': 'b'}):
            with self.assertRaises(ValueError): self.service.base_write('create_record', 'base_example', 'tbl_example', fields)

    def test_base_schema_pagination_uses_total(self):
        pages = [envelope({'fields': self.schema[:1], 'total': 2}), envelope({'fields': self.schema[1:2], 'total': 2})]
        original = self.fake
        def runner(binary, args, **kwargs):
            if args[:2] == ['base', '+field-list'] and '--help' not in args:
                self.calls.append((args, kwargs)); return pages.pop(0)
            return original(binary, args, **kwargs)
        with patch('vault_rag.feishu.run_cli', side_effect=runner):
            with self.assertRaises(ValueError):
                self.service.base_write('update_record', 'base_example', 'tbl_example', {'Computed': 1}, 'rec_example')
        self.assertFalse(pages)
        self.assertTrue(any('--offset=1' in args for args, _ in self.calls))

    def test_base_queries_preserve_pagination_and_server_filters(self):
        self.result = envelope({'records': [{'record_id': 'rec_example'}], 'total': 4})
        result = self.service.base_read('records', 'base_example', 'tbl_example', limit=1, offset=2,
                                        filter={'logic': 'and'}, sort=[{'field': 'Title', 'desc': True}], fields=['Title'])
        self.assertEqual(result['data']['next_offset'], 3)
        self.assertTrue(result['data']['has_more'])
        args = self.calls[-1][0]
        self.assertIn('--field-id=Title', args)
        self.assertTrue(any(a.startswith('--filter-json={') for a in args))
        self.result = envelope({'data': [['Example', 1]], 'fields': ['Title', 'Count'],
                                'record_id_list': ['rec_example'], 'has_more': True})
        matrix = self.service.base_read('records', 'base_example', 'tbl_example', limit=1, offset=2)
        self.assertEqual(matrix['data']['next_offset'], 3)
        self.assertEqual(matrix['data']['data'], [['Example', 1]])

    def test_native_executable_selection_and_configuration_validation(self):
        for profile in ('../other', '--as=bot', 'name/other'):
            with self.assertRaises(ValueError): self.service.configure({'profile': profile})
        self.service.configure({'binary': str(self.config.directory / 'lark-cli.cmd')})
        with self.assertRaises(FeishuError): self.service._binary()
        self.service.configure({'enabled': False})
        with self.assertRaises(FeishuError) as raised: self.service.docs_read('fetch', document='example')
        self.assertEqual(raised.exception.code, 'integration_disabled')


class AccessTests(unittest.TestCase):
    def test_old_config_and_independent_capabilities(self):
        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(directory=Path(directory))
            (config.directory / 'mcp-access.json').write_text(json.dumps({'local': {'enabled': True, 'write': True, 'token_hash': 'old'}}))
            access = McpAccess(config)
            self.assertFalse(access.status()['local']['feishu_read'])
            token = access.configure('local', enabled=True, write=True, rotate=True, resource='feishu')['token']
            access.configure('local', enabled=False, write=False)
            self.assertEqual(access.principal('Bearer ' + token, 'legacy'), 'local')
            access.require('local', write=True, resource='feishu')
            with self.assertRaises(PermissionError): access.require('local')
            with self.assertRaises(PermissionError): access.require('legacy', resource='feishu')
            with self.assertRaises(PermissionError): access.require('tunnel', resource='feishu')
            access.configure('local', enabled=False, write=False, resource='feishu')
            with self.assertRaises(PermissionError): access.principal('Bearer ' + token, 'legacy')


class RunnerTests(unittest.TestCase):
    def test_stdin_and_argument_array(self):
        body = '@file\n中文 & `literal`'
        code, out, err = run_cli(sys.executable, ['-c', 'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read()); print(sys.argv[1])', '--as=bot'], content=body)
        self.assertEqual(code, 0, err)
        self.assertIn(body, out)
        self.assertIn('--as=bot', out)

    def test_timeout_and_output_bound(self):
        with self.assertRaises(FeishuError) as timeout:
            run_cli(sys.executable, ['-c', 'import time; time.sleep(3)'], timeout=.1)
        self.assertEqual(timeout.exception.code, 'cli_timeout')
        with self.assertRaises(FeishuError) as output:
            run_cli(sys.executable, ['-c', 'print("x" * 100000)'], output_limit=1000)
        self.assertEqual(output.exception.code, 'output_limit')


if __name__ == '__main__': unittest.main()
