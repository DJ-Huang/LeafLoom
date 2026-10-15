"""Exercise the installed sidecar in an isolated vault; never uses real user data."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request


async def mcp_check(url, token):
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + token}, trust_env=False) as http:
        async with streamable_http_client(url + '/mcp', http_client=http) as (read, write, _):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = await client.list_tools()
                assert {'vault_search', 'vault_index_status', 'vault_get_note'} <= {t.name for t in tools.tools}
                response = await client.call_tool('vault_search', {'query': 'leafloom desktop acceptance', 'mode': 'keyword'})
                assert not response.isError
                assert json.loads(response.content[0].text)['results']


def exercise(python, workspace, *, commit=True):
    workspace = workspace.resolve()
    state = workspace / 'state'
    vault = workspace / '中文 Knowledge'
    state.mkdir(); vault.mkdir()
    note = vault / 'Acceptance.md'
    note.write_text('---\nname: Acceptance\n---\nleafloom desktop acceptance original\n', encoding='utf-8')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    config = {'root': str(vault), 'include_roots': [''], 'exclude_roots': [], 'rules_roots': [], 'wiki_roots': [], 'estimation_roots': [], 'write_targets': {'notes': 'Notes'}, 'homepage': '', 'templates': 'Templates', 'daily_folder': 'Daily', 'port': port}
    (state / 'config.json').write_text(json.dumps(config), encoding='utf-8')
    events = queue.Queue()
    log = (workspace / 'backend.log').open('w', encoding='utf-8')
    child = subprocess.Popen([str(python), '-I', '-B', '-X', 'utf8', '-m', 'vault_rag.desktop_entry'], cwd=workspace,
        env=dict(os.environ, VAULT_RAG_HOME=str(state), PYTHONDONTWRITEBYTECODE='1'),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, encoding='utf-8',
        **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
    def read():
        for line in child.stdout:
            try: events.put(json.loads(line))
            except ValueError: pass
        events.put({'type': 'exit', 'code': child.wait()})
    threading.Thread(target=read, daemon=True).start()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        ready = events.get(timeout=100)
        if ready['type'] != 'ready': raise RuntimeError(str(ready))
        url = ready['url']; token = (state / 'auth-token').read_text().strip()
        def request(route, data=None, method=None, authorized=True):
            headers = {'Content-Type': 'application/json'}
            if authorized: headers['Authorization'] = 'Bearer ' + token
            req = urllib.request.Request(url + route, data=None if data is None else json.dumps(data).encode(), headers=headers, method=method)
            try:
                with opener.open(req, timeout=15) as response:
                    content = response.read()
                    return json.loads(content) if response.headers.get_content_type() == 'application/json' else content
            except urllib.error.HTTPError as error:
                if error.code != 401:
                    raise RuntimeError(f'{route}: HTTP {error.code}: {error.read().decode("utf-8")}') from error
                raise
        assert b'<html' in request('/').lower()
        status = request('/api/status')
        assert not status['model']['prepared'] and status['model']['load_count'] == 0
        deadline = time.monotonic() + 20
        while True:
            tree = request('/api/tree')
            if any(item['path'] == 'Acceptance.md' for item in tree): break
            if time.monotonic() > deadline: raise RuntimeError('Catalogue did not become ready')
            time.sleep(.2)
        original = request('/api/file?path=Acceptance.md')
        result = request('/api/file', {'path': 'Acceptance.md', 'root': str(vault), 'text': original['text'] + '\nsaved in desktop\n', 'etag': original['etag']}, 'PUT')
        assert 'saved in desktop' in note.read_text(encoding='utf-8')
        assert result['etag'] != original['etag']
        # Confirm the sandboxed preview cannot simply call editor APIs anonymously.
        try: request('/api/status', authorized=False)
        except urllib.error.HTTPError as error: assert error.code == 401
        else: raise AssertionError('Unauthenticated API was accepted')
        deadline = time.monotonic() + 10
        while True:
            found = request('/api/knowledge-search', {'query': 'leafloom desktop acceptance', 'mode': 'keyword'})
            if found['results']: break
            if time.monotonic() > deadline: raise AssertionError('Keyword retrieval without model failed')
            time.sleep(.2)
        asyncio.run(mcp_check(url, token))
        assert not (state / 'models/bge-m3').exists(), 'Startup downloaded a model'
        if commit:
            child.stdin.write('{"type":"commit"}\n'); child.stdin.flush()
            assert events.get(timeout=5)['type'] == 'committed'
            child.stdin.write('{"type":"shutdown"}\n'); child.stdin.flush()
        child.stdin.close()  # Exercise EOF ownership cleanup too.
        assert child.wait(timeout=35) == 0
        receipt = json.loads((state / 'desktop-migration.json').read_text())
        assert receipt['state'] == ('committed' if commit else 'rolled-back')
        # The owned listener must be gone after shutdown.
        with socket.socket() as probe:
            assert probe.connect_ex(('127.0.0.1', port)) != 0
        return {'offline_edit': True, 'keyword_without_model': True, 'mcp': True, 'shutdown': True, 'commit': commit}
    finally:
        if child.poll() is None:
            if not child.stdin.closed: child.stdin.close()
            try: child.wait(timeout=35)
            except subprocess.TimeoutExpired: child.kill(); child.wait()
        log.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', type=Path, required=True)
    args = parser.parse_args()
    python = args.python.resolve()
    with tempfile.TemporaryDirectory(prefix='LeafLoom 中文 acceptance ') as temporary:
        root = Path(temporary)
        results = []
        for commit in (True, False):
            work = root / ('commit' if commit else 'parent-eof'); work.mkdir()
            results.append(exercise(python, work, commit=commit))
        print(json.dumps({'platform': os.name, 'checks': results}, ensure_ascii=False))


if __name__ == '__main__': main()
