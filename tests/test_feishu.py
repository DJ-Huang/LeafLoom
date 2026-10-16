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
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config = SimpleNamespace(directory=Path(temp.name))
        self.service = Feishu(self.config)
        self.addCleanup(self.service.files.temp.cleanup)
        self.service.configure({'enabled': True, 'binary': sys.executable, 'profile': 'work'})
        self.calls = []
        self.status = {'appId': 'fictional-app', 'identities': {'user': {'available': True, 'verified': True,
                       'userName': 'Example', 'openId': 'ou_example', 'access_token': 'never-save'}}}
        self.result = envelope({'document': {'revision_id': 12}, 'has_more': True, 'page_token': 'next'})
        self.risks = {'+fetch': 'read', '+future': 'read', '+update': 'write', '+create': 'write', '+delete': 'high-risk-write'}
        self.runner = patch('vault_rag.feishu.run_cli', side_effect=self.fake)
        self.runner.start(); self.addCleanup(self.runner.stop)

    def fake(self, binary, args, **kwargs):
        self.calls.append((list(args), kwargs))
        if args == ['--help']:
            return 0, 'Lark domains:\n  docs  Documents\n  calendar  Calendars\n  base  Base\nAgent tooling:\n  schema  Schema\n  skills  Skills', ''
        if '--help' in args:
            risk = self.risks.get(args[1] if len(args) > 1 else '', 'read')
            return 0, '\n'.join(['Risk: ' + risk] + ['  ' + flag + '  description' for flag in (
                '--as string', '--format string', '--json', '--verify', '--doc string', '--content string',
                '--command string', '--block-id string', '--doc-format string', '--revision-id int', '--query string',
                '--file string', '--output string', '--params string', '--data string', '--yes', '--dry-run') if not (args[0] == 'api' and flag == '--yes')]), ''
        if args == ['--version']: return 0, 'lark-cli version 1.0.66', ''
        if args[:2] == ['auth', 'status']: return 0, json.dumps(self.status), ''
        if args[0] == 'schema': return 0, json.dumps({'_meta': {'risk': 'read'}}), ''
        if args[:2] == ['skills', 'read']: return 0, '# Installed skill\nUse block_replace', ''
        return self.result

    def execute(self, argv, **kwargs):
        return self.service.execute(argv, owner='local-generation', source_check=lambda source: None,
                                    require_high_risk=lambda: None, **kwargs)

    def test_verify_and_configuration_preserve_cli_credentials(self):
        self.assertEqual(self.service.verify()['verification']['state'], 'connected')
        self.assertNotIn('never-save', self.service.path.read_text())
        self.assertTrue(self.service.account_status()['bridge_available'])
        self.service.configure({'profile': 'personal'})
        self.assertEqual(self.service.status()['verification'], {'state': 'unchecked'})
        for profile in ('../other', '--as=bot', 'name/other'):
            with self.assertRaises(ValueError): self.service.configure({'profile': profile})
        self.service.configure({'binary': str(self.config.directory / 'lark-cli.cmd')})
        with self.assertRaises(FeishuError): self.service._binary()

    def test_discovery_plaintext_schema_and_new_command_without_adapter(self):
        self.assertIn('Installed skill', self.service.inspect('skills_read', path='lark-doc')['text'])
        self.assertEqual(self.service.inspect('schema', path='calendar.calendars.list')['data']['_meta']['risk'], 'read')
        result = self.execute(['docs', '+future', '--query', '--as=bot'])
        self.assertEqual(result['data']['data']['page_token'], 'next')
        self.assertIn('--query=--as=bot', self.calls[-1][0])
        self.assertIn('--as=user', self.calls[-1][0])
        self.execute(['calendar', 'calendars', 'list'])
        self.assertTrue(any(args == ['schema', 'calendar.calendars.list'] for args, _ in self.calls))
        count = sum('--help' in args for args, _ in self.calls)
        self.execute(['docs', '+future'])
        self.assertEqual(count, sum('--help' in args for args, _ in self.calls))
        self.service.configure({'profile': 'new'})
        self.execute(['docs', '+future'])
        self.assertGreater(sum('--help' in args for args, _ in self.calls), count)

    def test_unknown_risk_and_read_write_boundaries_fail_closed(self):
        self.risks['+future'] = 'unknown'
        for argv in (['docs', '+future'], ['docs', '+create']):
            with self.assertRaises(FeishuError): self.execute(argv)
        for argv in (['auth', 'status'], ['docs', 'watch'], ['config', 'init']):
            with self.assertRaises(FeishuError): self.execute(argv)
        for flag in ('--as=bot', '--profile=other', '--format=table', '--yes', '--revision-id=1', '--help'):
            with self.assertRaises(ValueError): self.execute(['docs', '+fetch', flag])
        self.assertFalse(any('--as=user' in args for args, _ in self.calls))

    def test_raw_api_paths_and_confirmation(self):
        for path in ('https://evil/open-apis/im/v1/messages', '/open-apis/auth/v3/token',
                     '/open-apis/x/../auth/token', '/open-apis/%61uth/token', '/open-apis/im/v1/messages?x=1'):
            with self.assertRaises(ValueError): self.execute(['api', 'GET', path], write=True, confirm=True)
        with self.assertRaises(FeishuError) as confirm:
            self.execute(['api', 'GET', '/open-apis/im/v1/messages'], write=True)
        self.assertEqual(confirm.exception.code, 'confirmation_required')
        self.execute(['api', 'GET', '/open-apis/im/v1/messages'], write=True, confirm=True)
        self.assertNotIn('--yes', self.calls[-1][0])
        self.execute(['docs', '+delete'], write=True, confirm=True)
        self.assertIn('--yes', self.calls[-1][0])

    def test_stdin_xml_and_revision_preflight(self):
        body = '<h4>中文 &amp; literal</h4>'
        self.execute(['docs', '+update', '--doc=example', '--command=block_replace', '--content=-', '--block-id=block'],
                     write=True, stdin=body, expected_revision=12)
        args, options = self.calls[-1]
        self.assertEqual(options['content'], body)
        self.assertEqual(options['profile'], 'work')
        self.assertIn('--revision-id=12', args)
        self.assertNotIn('--doc-format=markdown', args)
        for revision in (None, 0, True, 11):
            before = len(self.calls)
            with self.assertRaises((FeishuError, ValueError)):
                self.execute(['docs', '+update', '--doc=example'], write=True, expected_revision=revision)
            self.assertFalse(any(args[:2] == ['docs', '+update'] and '--as=user' in args for args, _ in self.calls[before:]))
        with self.assertRaises(FeishuError):
            self.execute(['api', 'PATCH', '/open-apis/docx/v1/documents/example/blocks/a'],
                         write=True, confirm=True, expected_revision=11)

    def test_results_preserve_shapes_partial_success_and_errors_without_retry(self):
        for value in ([{'title': 'a'}], 42, 'hello', None):
            self.result = (0, json.dumps(value), '')
            self.assertEqual(self.execute(['docs', '+fetch'])['data'], value)
        self.result = envelope({'result': 'partial_success', 'ignored_fields': ['Title']})
        self.assertEqual(self.execute(['docs', '+create'], write=True)['error_code'], 'partial_write')
        self.result = (1, '', json.dumps({'ok': False, 'error': {'type': 'authorization',
            'subtype': 'missing_scope', 'message': 'access_token=secret-value', 'hint': 'Read the scope docs',
            'missing_scopes': ['docs:read'], 'access_token': 'secret-value'}}))
        before = len(self.calls)
        result = self.execute(['docs', '+fetch'])
        self.assertNotIn('secret-value', json.dumps(result))
        self.assertEqual(result['data']['error']['hint'], 'Read the scope docs')
        self.assertEqual(result['error_source'], 'feishu_cli')
        self.assertEqual(sum('--as=user' in args for args, _ in self.calls[before:]), 1)

    def test_input_and_output_file_transport(self):
        import base64, hashlib
        data = b'attachment bytes'
        file = self.service.files.operation('local-generation', lambda source: None, 'put', name='a.txt',
            data_base64=base64.b64encode(data).decode(), complete=True, size=len(data), sha256=hashlib.sha256(data).hexdigest())
        original = self.fake
        def download(binary, args, **kwargs):
            if '--output=out/result.txt' in args:
                job = Path(kwargs['cwd'])
                self.assertEqual((job / 'in/a.txt').read_bytes(), data)
                (job / 'out/result.txt').write_bytes(data)
            return original(binary, args, **kwargs)
        with patch('vault_rag.feishu.run_cli', side_effect=download):
            result = self.execute(['docs', '+fetch', '--output=out/result.txt'], input_files={'in/a.txt': file['file_id']})
        self.assertEqual(result['files'][0]['sha256'], file['sha256'])
        self.assertNotIn(str(self.config.directory), json.dumps(result))
        for value in ('../outside', 'C:/outside', '/outside'):
            with self.assertRaises(ValueError): self.execute(['docs', '+fetch', '--output=' + value])
        with self.assertRaises(ValueError): self.execute(['docs', '+fetch', '--content=@missing.txt'])


class FileTests(unittest.TestCase):
    def test_chunks_ownership_expiry_integrity_and_quota(self):
        import base64, hashlib, time
        from vault_rag.feishu_files import FeishuFiles
        with tempfile.TemporaryDirectory() as directory:
            store = FeishuFiles(SimpleNamespace(directory=Path(directory)))
            self.addCleanup(store.temp.cleanup)
            check = lambda source: None
            first = store.operation('a', check, 'put', name='test.txt', data_base64=base64.b64encode(b'abc').decode())
            key = first['file_id']
            with self.assertRaises(FileNotFoundError): store.operation('b', check, 'stat', file_id=key)
            with self.assertRaises(ValueError): store.operation('a', check, 'put', file_id=key, offset=0)
            done = store.operation('a', check, 'put', file_id=key, offset=3, complete=True,
                                   size=3, sha256=hashlib.sha256(b'abc').hexdigest())
            self.assertTrue(done['complete'])
            self.assertTrue(store.operation('a', check, 'get', file_id=key)['eof'])
            with self.assertRaises(ValueError): store.operation('a', check, 'put', name='bad.txt', complete=True, size=0, sha256='0'*64)
            with patch.object(store, 'MAX_FILE', 1):
                with self.assertRaises(ValueError): store.operation('a', check, 'put', name='large.txt', data_base64='YWJj')
            store.entries[key]['expires_at'] = time.time() - 1
            with self.assertRaises(FileNotFoundError): store.operation('a', check, 'stat', file_id=key)
            self.assertFalse((store.root / key).exists())

    def test_provenance_and_output_links(self):
        from vault_rag.feishu_files import FeishuFiles
        with tempfile.TemporaryDirectory() as directory:
            store = FeishuFiles(SimpleNamespace(directory=Path(directory)))
            self.addCleanup(store.temp.cleanup)
            source = Path(directory) / 'source.txt'
            source.write_bytes(b'example')
            item = store.register('a', source, [{'root': 'old', 'path': 'source.txt'}])
            def revoked(source): raise PermissionError('revoked')
            with self.assertRaises(PermissionError): store.get('a', item['file_id'], revoked)
            with tempfile.TemporaryDirectory(dir=store.root) as jobdir:
                job = Path(jobdir)
                for rel in ('../outside', '/absolute', 'C:/absolute', 'a\\b'):
                    with self.assertRaises(ValueError): store.job_path(job, rel)
                with patch('vault_rag.feishu_files.is_link', return_value=True):
                    (job / 'link').write_text('x')
                    with self.assertRaises(ValueError): store.scan('a', job, set())


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
