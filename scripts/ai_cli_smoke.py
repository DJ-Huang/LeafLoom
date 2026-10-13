"""Live CLI acceptance in a disposable vault; reuse the user's existing CLI login.

Run with the app's Python: python scripts/ai_cli_smoke.py --provider both
Creates native CLI test conversations but never modifies the user's linked vault.
"""
from __future__ import annotations

import argparse
import json
import logging
import socket
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import uvicorn

from vault_rag.local_state import LocalConfig, Files
from vault_rag.web_server import create_app, create_server


class SmokeKnowledge:
    def __init__(self, files):
        self.files = files

    def get_note(self, path):
        return {'ok': True, **self.files.read(path)} if path == 'RAG/a.md' else {'ok': False}

    def search(self, query, **kwargs):
        return {'results': [{'file_path': 'RAG/a.md', 'text': self.files.read('RAG/a.md')['text']}]}


class Server:
    def __init__(self, config):
        files = Files(config)
        runtime = SimpleNamespace(files=files, knowledge=SmokeKnowledge(files),
            catalog=SimpleNamespace(root=str(config.root), version=1),
            events=SimpleNamespace(instance='ai-cli-smoke'), start=lambda: None, stop=lambda: None)
        self.app = create_app(config, runtime, start_background=False)
        self.tool_reads = 0
        original_read = self.app.state.ai.read_note
        def read_note(*args, **kwargs):
            self.tool_reads += 1
            return original_read(*args, **kwargs)
        self.app.state.ai.read_note = read_note
        self.server = create_server(self.app,port=config.data['port'],log_level='warning',loop='asyncio:SelectorEventLoop')
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.url = f"http://127.0.0.1:{config.data['port']}"
        self.token = (config.directory / 'auth-token').read_text().strip()

    def __enter__(self):
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() > deadline or not self.thread.is_alive():
                raise RuntimeError('临时服务未能启动')
            time.sleep(.1)
        self.client = httpx.Client(base_url=self.url, headers={'Authorization': 'Bearer ' + self.token}, timeout=15)
        return self

    def request(self, method, path, body=None):
        response = self.client.request(method, '/api/ai/' + path, json=body)
        if response.status_code >= 400:
            raise RuntimeError('临时接口请求失败：' + str(response.status_code))
        return response.json()

    def turn(self, key, root, question, context):
        self.request('POST', f'conversations/{key}/messages', {'root': root, 'request_id': uuid.uuid4().hex,
            'question': question, 'references': [], 'context': context})
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            detail = self.request('GET', 'conversations/' + key)
            if detail['conversation']['state'] != 'running':
                if detail['turns'][-1]['state'] != 'completed':
                    print(json.dumps({'protocol_failure': self.app.state.ai.last_failure.get(key)}, ensure_ascii=False), flush=True)
                    raise RuntimeError(detail['conversation']['error'] or 'CLI 本轮未完成')
                return detail
            time.sleep(.3)
        self.request('POST', f'conversations/{key}/stop', {'root': root})
        raise RuntimeError('CLI 验收本轮超时，已停止')

    def __exit__(self, *args):
        self.client.close()
        self.server.should_exit = True
        self.thread.join(20)
        if self.thread.is_alive():
            raise RuntimeError('临时服务未正常退出')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=['codex', 'codely', 'both'], default='both')
    args = parser.parse_args()
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('mcp').setLevel(logging.WARNING)
    results = []
    base = Path(__file__).resolve().parents[1] / '.cache/ai-cli-smoke'
    base.mkdir(parents=True, exist_ok=True)
    for provider in (['codex', 'codely'] if args.provider == 'both' else [args.provider]):
        with tempfile.TemporaryDirectory(dir=base) as temp:
            home = Path(temp)
            root = home / '中文知识库'
            (root / 'RAG').mkdir(parents=True)
            (root / 'RAG/a.md').write_bytes('# 验收笔记\n这是用于验证知识工具的临时正文。\n'.encode('utf-8'))
            config = LocalConfig(home / 'state')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            config.save({'root': str(root), 'port': port, 'include_roots': ['RAG']})
            keyword = 'vault-ai-' + uuid.uuid4().hex[:10]
            (root / 'RAG/a.md').write_bytes(('# 验收笔记\n本次校验词：' + keyword + '\n').encode('utf-8'))
            try:
                with Server(config) as server:
                    topic = server.request('POST', 'conversations', {'root': str(root), 'provider': provider})
                    disk = server.app.state.runtime.files.read('RAG/a.md')
                    context = {'root': str(root), 'path': 'RAG/a.md', 'text': disk['text'], 'etag': disk['etag']}
                    first = server.turn(topic['id'], str(root), '请调用 read_note 读取 RAG/a.md，记住里面的校验词。只回复校验词。', None)
                    if not server.tool_reads or keyword not in first['turns'][-1]['answer']:
                        print(json.dumps({'server_request_methods': list(server.app.state.ai.request_methods)}, ensure_ascii=False), flush=True)
                        raise RuntimeError('CLI 未通过知识工具读取校验词')
                    native = first['conversation']['native_id']
                    second = server.turn(topic['id'], str(root), '上一条消息要求记住的校验词是什么？只回复校验词。', context)
                    if keyword not in second['turns'][-1]['answer']:
                        raise RuntimeError('第二轮未正确保留上下文')
                    if second['conversation']['native_id'] != native:
                        raise RuntimeError('连续对话更换了原生会话')
                with Server(config) as server:
                    third = server.turn(topic['id'], str(root), '我们之前记住的校验词是什么？只回复校验词。', context)
                    if keyword not in third['turns'][-1]['answer'] or third['conversation']['native_id'] != native:
                        raise RuntimeError('重启后未恢复同一原生会话上下文')
                result = {'provider': provider, 'passed': True, 'tool_read': True, 'multi_turn': True, 'restart_resume': True}
            except Exception as error:
                result = {'provider': provider, 'passed': False, 'reason': str(error)}
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    (base / 'result.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if all(result['passed'] for result in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
