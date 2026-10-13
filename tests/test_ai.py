"""AI state/protocol/file-boundary tests; no model downloads or production vault writes."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from vault_rag.ai_service import AiService
from vault_rag.ai_rpc import CliAdapter, RpcError, RpcProcess
from vault_rag.ai_routes import ai_router, ai_mcp_server
from vault_rag.local_state import LocalConfig, Files, ConflictError, digest


class FakeKnowledge:
    def __init__(self, files):
        self.files = files

    def get_note(self, path):
        if not path.startswith('RAG/'):
            return {'ok': False}
        return {'ok': True, **self.files.read(path)}

    def search(self, query, **kwargs):
        return {'query': query, 'results': []}


class FakeAdapter:
    def __init__(self, provider, service):
        self.provider, self.service = provider, service
        self.lock = asyncio.Lock()
        self.peer = None
        self.loaded = set()
        self.requests = []
        self.gate = asyncio.Event()

    async def run(self, conversation, prompt):
        native = conversation['native_id'] or 'native-' + conversation['id']
        self.service.bind_native(conversation['id'], native)
        conversation['native_id'] = native
        self.loaded.add(conversation['id'])
        self.requests.append((native, prompt))
        self.service.delta(conversation['id'], '第一段')
        await self.gate.wait()
        self.service.delta(conversation['id'], '，第二段')
        return 'completed'

    async def interrupt(self):
        self.gate.set()

    async def close(self):
        pass


class AiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        home = Path(self.temp.name)
        root = home / '中文 vault'
        (root / 'RAG').mkdir(parents=True)
        (root / 'RAG/a.md').write_bytes('原文\n'.encode('utf-8'))
        with patch('vault_rag.local_state.protect_private_directory', side_effect=lambda p: p.mkdir(parents=True, exist_ok=True)):
            self.config = LocalConfig(home / 'state')
            self.config.save({'root': str(root), 'include_roots': ['RAG']})
        self.files = Files(self.config)
        self.runtime = SimpleNamespace(files=self.files, knowledge=FakeKnowledge(self.files))
        self.ai = AiService(self.config, self.runtime, adapter_factory=FakeAdapter)

    async def asyncTearDown(self):
        await self.ai.close()
        self.temp.cleanup()

    def payload(self, request='request-1', text='原文\n'):
        disk = self.files.read('RAG/a.md')
        return {'root': str(self.config.root), 'request_id': request, 'question': '请总结',
                'references': [{'root': str(self.config.root), 'path': 'RAG/a.md', 'text': '原文'}],
                'context': {'root': str(self.config.root), 'path': 'RAG/a.md', 'text': text, 'etag': disk['etag']}}

    async def begin(self, provider='codex'):
        topic = self.ai.create(provider)
        await self.ai.send(topic['id'], self.payload())
        await asyncio.sleep(0)
        return topic

    async def test_multi_turn_native_identity_and_duplicate_requests(self):
        topic = await self.begin()
        duplicate = await self.ai.send(topic['id'], self.payload())
        self.assertTrue(duplicate['duplicate'])
        with self.assertRaises(ConflictError):
            await self.ai.send(topic['id'], {**self.payload(), 'question': '不同问题'})
        adapter = self.ai.adapters['codex']
        adapter.gate.set()
        await self.ai.tasks[topic['id']]
        native = self.ai.conversation(topic['id'])['native_id']
        await self.ai.send(topic['id'], self.payload('request-2'))
        await self.ai.tasks[topic['id']]
        detail = self.ai.detail(topic['id'])
        self.assertEqual(len(detail['turns']), 2)
        self.assertEqual(detail['turns'][0]['answer'], '第一段，第二段')
        self.assertEqual(adapter.requests[0][0], adapter.requests[1][0])
        self.assertEqual(detail['conversation']['native_id'], native)
        self.assertNotIn('capability', detail['conversation'])

    async def test_new_topic_creation_is_idempotent_without_native_session(self):
        topic = self.ai.create('codely', client_id='a' * 32)
        same = self.ai.create('codely', client_id='a' * 32)
        self.assertEqual(topic['id'], same['id'])
        self.assertIsNone(topic['native_id'])
        with self.assertRaises(ConflictError):
            self.ai.create('codex', client_id='a' * 32)

    async def test_concurrent_turns_root_isolation_and_stop(self):
        topic = await self.begin('codely')
        other = self.ai.create('codely')
        with self.assertRaises(ConflictError):
            await self.ai.send(other['id'], self.payload('other'))
        await self.ai.stop(topic['id'])
        self.assertEqual(self.ai.detail(topic['id'])['turns'][0]['state'], 'interrupted')
        second_root = Path(self.temp.name) / 'second'
        second_root.mkdir()
        self.config.save({'root': str(second_root)})
        self.assertEqual(self.ai.conversations(), [])
        with self.assertRaises(ValueError):
            self.ai.detail(topic['id'])

    async def test_restart_preserves_native_binding_and_does_not_resend(self):
        topic = await self.begin()
        self.ai.tasks[topic['id']].cancel()
        await asyncio.gather(self.ai.tasks[topic['id']], return_exceptions=True)
        native = self.ai.conversation(topic['id'])['native_id']
        await self.ai.close()
        self.ai = AiService(self.config, self.runtime, adapter_factory=FakeAdapter)
        self.assertEqual(self.ai.conversation(topic['id'])['native_id'], native)
        self.assertEqual(self.ai.adapters['codex'].requests, [])
        self.ai.adapters['codex'].gate.set()
        await self.ai.send(topic['id'], self.payload('second'))
        await self.ai.tasks[topic['id']]
        self.assertEqual(self.ai.adapters['codex'].requests[0][0], native)

    async def test_proposals_use_draft_snapshot_never_write_existing_notes(self):
        topic = self.ai.create('codex')
        await self.ai.send(topic['id'], self.payload(text='未保存草稿'))
        await asyncio.sleep(0)
        conversation = self.ai.conversation(topic['id'], private=True)
        note = self.ai.read_note(conversation, 'RAG/a.md')
        self.assertEqual(note['text'], '未保存草稿')
        proposal = self.ai.propose(conversation, 'RAG/a.md', 'AI 改写', note['base_hash'])
        self.assertEqual(self.files.read('RAG/a.md')['text'], '原文\n')
        result = self.ai.accept(topic['id'], proposal['proposal_id'], {'root': str(self.config.root)})
        self.assertEqual(result['text'], 'AI 改写')
        self.assertEqual(self.files.read('RAG/a.md')['text'], '原文\n')
        self.assertEqual(self.ai.proposal(topic['id'], proposal['proposal_id'])['state'], 'pending')
        self.ai.applied(topic['id'], proposal['proposal_id'])
        self.assertEqual(self.ai.proposal(topic['id'], proposal['proposal_id'])['state'], 'accepted')

    async def test_external_change_and_invalid_base_block_acceptance(self):
        topic = await self.begin()
        conversation = self.ai.conversation(topic['id'], private=True)
        with self.assertRaises(ConflictError):
            self.ai.propose(conversation, 'RAG/a.md', '改写', 'wrong')
        proposal = self.ai.propose(conversation, 'RAG/a.md', '改写', digest('原文\n'))
        (self.config.root / 'RAG/a.md').write_text('外部修改', encoding='utf-8')
        with self.assertRaises(ConflictError):
            self.ai.accept(topic['id'], proposal['proposal_id'], {'root': str(self.config.root)})
        self.assertEqual(self.ai.proposal(topic['id'], proposal['proposal_id'])['state'], 'pending')

    async def test_new_note_confirmation_and_scope_boundaries(self):
        topic = await self.begin()
        conversation = self.ai.conversation(topic['id'], private=True)
        proposal = self.ai.propose(conversation, 'RAG/new.md', '新笔记', create=True)
        self.assertFalse((self.config.root / 'RAG/new.md').exists())
        self.ai.accept(topic['id'], proposal['proposal_id'], {'root': str(self.config.root), 'path': 'RAG/confirmed.md'})
        self.assertEqual(self.files.read('RAG/confirmed.md')['text'], '新笔记')
        with self.assertRaises(ValueError):
            self.ai.propose(conversation, '../escape.md', '内容', create=True)
        (self.config.root / 'Outside.md').write_text('不在检索范围', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.ai.read_note(conversation, 'Outside.md')
        with self.assertRaises(ValueError):
            self.ai.authorized('Bearer wrong')
        self.assertEqual(self.ai.authorized('Bearer ' + conversation['capability'])['id'], topic['id'])

    async def test_prompt_truncation_is_reported_and_full_snapshot_retained(self):
        payload = self.payload(text='草稿' * 20_000)
        _, contexts = self.ai.validate_contexts(payload)
        prompt, truncated = self.ai.prompt('问题', [], contexts)
        self.assertTrue(truncated)
        self.assertIn('上下文已截取', prompt)
        self.assertEqual(len(contexts['RAG/a.md']['text']), 40_000)

    async def test_withdrawn_retrieved_note_is_not_read_from_cached_context(self):
        (self.config.root / 'RAG/b.md').write_text('检索笔记', encoding='utf-8')
        topic = await self.begin()
        conversation = self.ai.conversation(topic['id'], private=True)
        self.assertEqual(self.ai.read_note(conversation, 'RAG/b.md')['text'], '检索笔记')
        self.config.save({'include_roots': []})
        with self.assertRaises(ValueError):
            self.ai.read_note(conversation, 'RAG/b.md')
        with self.assertRaises(ValueError):
            self.ai.propose(conversation, 'RAG/b.md', '不应产生的建议', digest('检索笔记'))
        # The current page was explicitly attached by the user, so it remains readable.
        self.assertEqual(self.ai.read_note(conversation, 'RAG/a.md')['text'], '原文\n')

    async def test_mcp_http_context_and_proposal_tools(self):
        # Calls the real FastMCP HTTP stack and Context, not a fake tool dispatcher.
        topic = await self.begin()
        conversation = self.ai.conversation(topic['id'], private=True)
        server = ai_mcp_server(self.ai)
        app = server.streamable_http_app()
        def exchange():
            with TestClient(app, base_url='http://127.0.0.1:18080') as client:
                response = client.post('/ai-mcp', headers={
                    'Authorization': 'Bearer ' + conversation['capability'],
                    'Accept': 'application/json, text/event-stream'}, json={
                        'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                        'params': {'name': 'read_note', 'arguments': {'path': 'RAG/a.md'}}})
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()['result']
                self.assertFalse(result.get('isError'), result)
                data = json.loads(result['content'][0]['text'])
                self.assertEqual(data['text'], '原文\n')
                self.assertEqual(data['base_hash'], digest('原文\n'))
        await asyncio.to_thread(exchange)

    async def test_real_app_auth_csrf_and_root_checks(self):
        from vault_rag.web_server import create_app
        runtime = SimpleNamespace(files=self.files, knowledge=self.runtime.knowledge,
            catalog=SimpleNamespace(root=str(self.config.root), version=1),
            events=SimpleNamespace(instance='test-ai'), start=lambda: None, stop=lambda: None)
        app = create_app(self.config, runtime, start_background=False)
        def exchange():
            with TestClient(app, base_url='http://127.0.0.1:18080') as client:
                client.cookies.set('vault_session', (self.config.directory / 'auth-token').read_text())
                body = {'root': str(self.config.root), 'provider': 'codex'}
                self.assertEqual(client.post('/api/ai/conversations', json=body).status_code, 403)
                headers = {'X-Vault-CSRF': app.state.csrf}
                topic = client.post('/api/ai/conversations', json=body, headers=headers)
                self.assertEqual(topic.status_code, 200, topic.text)
                self.assertNotIn('capability', topic.json())
                wrong = client.post('/api/ai/conversations', json={**body, 'root': 'another-root'}, headers=headers)
                self.assertEqual(wrong.status_code, 409)
                response = client.post('/ai-mcp', json={}, headers={'Authorization': 'Bearer not-the-session-capability'})
                self.assertEqual(response.status_code, 401)
        await asyncio.to_thread(exchange)


class FakePeer:
    replies = {}

    def __init__(self, command, cwd, notify, server_request, exited, **kwargs):
        self.notify = notify
        self.closed = False
        self.calls = []

    async def request(self, method, params, **kwargs):
        self.calls.append((method, params))
        if method == 'initialize':
            return {'agentCapabilities': {'loadSession': False}, 'agentInfo': {'version': '1.0.0-rc.60'}}
        if method in self.replies:
            value = self.replies[method]
            if method == 'session/new' and params.get('_meta'):
                old = params['_meta']['codely']['resumeSessionId']
                await self.notify('session/update', {'sessionId': old, 'update': {'sessionUpdate': 'replace_history', **value.get('snapshot', {})}})
            return value
        if method in ('thread/start', 'thread/resume'):
            return {'thread': {'id': params.get('threadId', 'native')}}
        return {'sessionId': 'native'}

    def notification(self, *args):
        pass

    async def close(self):
        self.closed = True


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bound = []
        self.service = SimpleNamespace(directory=Path(self.temp.name), mcp_url='http://127.0.0.1:18080/ai-mcp',
            instructions='知识助手', codex_mcp_overrides=lambda: {},
            bind_native=lambda key, native: self.bound.append((key, native)),
            has_completed_turn=lambda key: True, delta=lambda *args: None)
        self.conversation = {'id': 'topic', 'native_id': 'original', 'cwd': self.temp.name, 'capability': 'private'}
        FakePeer.replies = {}

    def tearDown(self):
        self.temp.cleanup()

    async def test_codex_resumes_exact_native_id(self):
        adapter = CliAdapter('codex', self.service, process_factory=FakePeer)
        with patch('vault_rag.ai_rpc.cli_command', return_value=['fake']):
            self.assertEqual(await adapter.session(self.conversation), 'original')
        call = adapter.peer.calls[-1]
        self.assertEqual(call[0], 'thread/resume')
        self.assertEqual(call[1]['threadId'], 'original')
        self.assertEqual(call[1]['sandbox'], 'read-only')
        self.assertIn('vault-ai', call[1]['config']['mcp_servers'])

    async def test_codely_extension_checks_history_and_never_calls_unsupported_load(self):
        FakePeer.replies = {'session/new': {'sessionId': 'original', 'snapshot': {'messages': [{'text': '历史'}]}}}
        adapter = CliAdapter('codely', self.service, process_factory=FakePeer)
        with patch('vault_rag.ai_rpc.cli_command', return_value=['fake']):
            self.assertEqual(await adapter.session(self.conversation), 'original')
        self.assertEqual(adapter.peer.calls[-1][0], 'session/new')
        self.assertEqual(adapter.peer.calls[-1][1]['_meta']['codely']['resumeSessionId'], 'original')
        self.assertFalse(any(method == 'session/load' for method, _ in adapter.peer.calls))

    async def test_codely_missing_history_and_fork_are_rejected(self):
        for response in ({'sessionId': 'original', 'snapshot': {}},
                         {'sessionId': 'forked', 'snapshot': {'messages': [{'text': '历史'}]}}):
            FakePeer.replies = {'session/new': response}
            adapter = CliAdapter('codely', self.service, process_factory=FakePeer)
            with patch('vault_rag.ai_rpc.cli_command', return_value=['fake']):
                with self.assertRaises(RpcError):
                    await adapter.session(self.conversation)
        self.assertEqual(self.bound, [])

    async def test_permissions_allow_only_scoped_knowledge_tools(self):
        adapter = CliAdapter('codely', self.service)
        adapter.active = self.conversation
        params = {'sessionId': 'original', 'options': [{'kind': 'allow_once', 'optionId': 'yes'}],
                  'toolCall': {'name': 'vault-ai__propose_note'}}
        self.assertEqual((await adapter.server_request('session/request_permission', params))['outcome']['outcome'], 'selected')
        params['toolCall']['name'] = 'run_shell_command'
        self.assertEqual((await adapter.server_request('session/request_permission', params))['outcome']['outcome'], 'cancelled')
        with self.assertRaises(RpcError):
            await adapter.server_request('fs/write_text_file', {})

    async def test_real_stdio_pipe_and_eof_fail_pending_requests(self):
        script = Path(self.temp.name) / 'fake_cli.py'
        script.write_text('import sys,json\nfor line in sys.stdin:\n m=json.loads(line)\n if m["method"]=="exit": break\n print(json.dumps({"id":m["id"],"result":{"echo":m["params"]}}),flush=True)\n', encoding='utf-8')
        async def noop(*args):
            pass
        peer = RpcProcess([sys.executable, '-X', 'utf8', str(script)], self.temp.name, noop, noop, noop)
        try:
            self.assertEqual(await peer.request('echo', {'text': '中文'}), {'echo': {'text': '中文'}})
            with self.assertRaises(RpcError):
                await peer.request('exit', {}, timeout=5)
        finally:
            await peer.close()
        self.assertIsNotNone(peer.process.poll())

    async def test_closing_owned_tree_releases_descendant_pipe_handles(self):
        script = Path(self.temp.name) / 'with_child.py'
        script.write_text('import sys,json,subprocess\nchild=subprocess.Popen([sys.executable,"-X","utf8","-c","import time; time.sleep(60)"])\nfor line in sys.stdin:\n m=json.loads(line)\n print(json.dumps({"id":m["id"],"result":{"child":child.pid}}),flush=True)\n', encoding='utf-8')
        async def noop(*args):
            pass
        peer = RpcProcess([sys.executable, '-X', 'utf8', str(script)], self.temp.name, noop, noop, noop)
        try:
            await peer.request('echo', {})
        finally:
            await asyncio.wait_for(peer.close(), 10)
        self.assertFalse(peer.reader.is_alive())
        self.assertFalse(peer.stderr_reader.is_alive())


if __name__ == '__main__':
    unittest.main()
