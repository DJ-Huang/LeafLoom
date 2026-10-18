"""Threaded JSON-RPC pipes work with Windows' Selector ASGI event loop."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
import platform
from pathlib import Path

from vault_rag import __version__
from vault_rag.platform_support import hidden_process_options
from vault_rag.ai_process import ProcessTree
from vault_rag.local_state import atomic_write

SCOPED_TOOLS = ('knowledge_search', 'read_note', 'propose_note', 'design_list_projects',
                'design_get_project', 'design_document', 'design_operations')


class RpcError(RuntimeError):
    def __init__(self, message, *, code=None, method=None):
        super().__init__(message)
        self.code, self.method = code, method


def cli_command(provider: str) -> list[str] | None:
    """Resolve npm launchers without a shell or interpolated command string."""
    executable = shutil.which(provider)
    if not executable:
        return None
    path = Path(executable)
    if path.suffix.lower() in ('.cmd', '.ps1', '.bat'):
        package = {'codex': '@openai/codex/bin/codex.js',
                   'codely': '@unity-china/codely-cli/bundle/gemini.js'}[provider]
        script = path.parent / 'node_modules' / package
        node = shutil.which('node')
        if provider == 'codex':
            target = 'aarch64-pc-windows-msvc' if platform.machine().lower() in ('arm64', 'aarch64') else 'x86_64-pc-windows-msvc'
            platform_package = 'codex-win32-arm64' if target.startswith('aarch64') else 'codex-win32-x64'
            package_root = script.parent.parent
            for vendor in (package_root / 'node_modules/@openai' / platform_package / 'vendor',
                           path.parent / 'node_modules/@openai' / platform_package / 'vendor', package_root / 'vendor'):
                native = vendor / target / 'bin/codex.exe'
                if native.is_file():
                    return [str(native)]
        if node and script.is_file():
            return [node, str(script)]
        return None
    return [executable]


class RpcProcess:
    def __init__(self, command, cwd, notify, server_request, exited, *, env=None):
        self.loop = asyncio.get_running_loop()
        self.notify = notify
        self.server_request = server_request
        self.exited = exited
        self.pending = {}
        self.sequence = 0
        self.lock = threading.Lock()
        self.closed = False
        self.callback_tasks = set()
        self.process = subprocess.Popen(
            command, cwd=cwd, env=env or os.environ.copy(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace', bufsize=1,
            start_new_session=os.name != 'nt',
            **hidden_process_options(),
        )
        try:
            self.tree = ProcessTree(self.process)
        except OSError:
            self.process.terminate()
            self.process.wait(timeout=5)
            for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
                pipe.close()
            raise RpcError('无法安全管理 CLI 子进程，请检查本机进程权限')
        self.reader = threading.Thread(target=self._read, daemon=True, name='ai-rpc')
        self.stderr_reader = threading.Thread(target=self._drain_errors, daemon=True, name='ai-stderr')
        self.reader.start()
        self.stderr_reader.start()

    def _read(self):
        try:
            while not self.closed:
                line = self.process.stdout.readline(32 * 1024 * 1024 + 1)
                if not line:
                    break
                if len(line) > 32 * 1024 * 1024:
                    break
                try:
                    message = json.loads(line)
                except (ValueError, TypeError):
                    continue  # Some CLI versions print startup notices to stdout.
                if isinstance(message, dict):
                    self.loop.call_soon_threadsafe(self._dispatch, message)
        finally:
            try:
                self.loop.call_soon_threadsafe(self._eof)
            except RuntimeError:
                pass

    def _drain_errors(self):
        # Authentication/config output can contain credentials. Never forward it.
        while self.process.stderr.read(4096):
            pass

    def _task(self, coroutine):
        task = self.loop.create_task(coroutine)
        self.callback_tasks.add(task)
        task.add_done_callback(self.callback_tasks.discard)
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    def _dispatch(self, message):
        if self.closed:
            return
        if 'method' in message:
            if 'id' in message:
                self._task(self._reply(message))
            else:
                self._task(self.notify(message['method'], message.get('params') or {}))
        elif message.get('id') in self.pending:
            future = self.pending.pop(message['id'])
            if future.done():
                return
            if 'error' in message:
                future.set_exception(RpcError(str(message['error'].get('message', 'CLI 请求失败')), code=message['error'].get('code')))
            else:
                future.set_result(message.get('result') or {})

    async def _reply(self, message):
        try:
            result = await self.server_request(message['method'], message.get('params') or {})
            self.send({'jsonrpc': '2.0', 'id': message['id'], 'result': result})
        except Exception:
            try:
                self.send({'jsonrpc': '2.0', 'id': message['id'],
                           'error': {'code': -32601, 'message': '此知识助手不允许该操作'}})
            except RpcError:
                pass

    def send(self, message):
        if self.closed:
            raise RpcError('CLI 连接已关闭，请重新连接原会话')
        try:
            with self.lock:
                self.process.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
                self.process.stdin.flush()
        except (OSError, ValueError) as error:
            raise RpcError('CLI 连接中断，原会话记录仍保留') from error

    async def request(self, method, params, timeout=60):
        self.sequence += 1
        request_id = self.sequence
        future = self.loop.create_future()
        self.pending[request_id] = future
        try:
            self.send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params})
            return await asyncio.wait_for(future, timeout)
        except RpcError as error:
            error.method = method
            raise
        finally:
            self.pending.pop(request_id, None)

    def notification(self, method, params=None):
        self.send({'jsonrpc': '2.0', 'method': method, 'params': params or {}})

    def _eof(self):
        if self.closed:
            return
        self.closed = True
        for future in self.pending.values():
            if not future.done():
                future.set_exception(RpcError('CLI 已退出；请检查 CLI 登录与配置后重试原会话'))
        self.pending.clear()
        self._task(self.exited())

    async def close(self):
        self.closed = True
        for future in self.pending.values():
            if not future.done():
                future.set_exception(RpcError('CLI 已停止'))
        self.pending.clear()
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                await asyncio.to_thread(self.process.wait, timeout=3)
            except subprocess.TimeoutExpired:
                self.tree.close()
                await asyncio.to_thread(self.process.wait, timeout=5)
        self.tree.close()
        if not self.process.stdin.closed:
            self.process.stdin.close()
        await asyncio.to_thread(self.reader.join, 1)
        await asyncio.to_thread(self.stderr_reader.join, 1)
        for pipe in (self.process.stdout, self.process.stderr):
            pipe.close()
        callbacks = [task for task in self.callback_tasks if task is not asyncio.current_task()]
        for task in callbacks:
            task.cancel()
        await asyncio.gather(*callbacks, return_exceptions=True)


class CliAdapter:
    """One live process per provider, with native sessions bound to topics."""
    def __init__(self, provider, service, *, process_factory=RpcProcess):
        self.provider = provider
        self.service = service
        self.process_factory = process_factory
        self.peer = None
        self.loaded = set()
        self.capabilities = {}
        self.version = ''
        self.active = None
        self.turn_id = None
        self.turn_done = None
        self.snapshots = {}
        self.lock = asyncio.Lock()

    async def start(self):
        if self.peer and not self.peer.closed:
            return
        if self.peer:
            await self.peer.close()
        self.loaded.clear()
        command = cli_command(self.provider)
        if not command:
            raise RpcError(f'未找到 {self.provider} CLI，请先安装并在终端完成登录')
        if self.provider == 'codex':
            command += ['app-server', '--listen', 'stdio://',
                        '-c', 'features.shell_tool=false', '-c', 'features.unified_exec=false',
                        '-c', 'features.multi_agent=false', '-c', 'features.apply_patch_freeform=false']
        else:
            # Disable arbitrary built-ins as well as unrelated inherited MCP servers.
            command += ['--experimental-acp', '--no-upm', '--agents=false',
                        '--disable-next-speaker-check',
                        '--path-policy=strict', '--approval-mode=default',
                        '--allowed-mcp-server-names=vault-ai',
                        '--exclude-tools', 'run_shell_command', 'write_file', 'replace', 'apply_patch',
                        'save_memory', 'web_fetch', 'web_search', 'enter_plan_mode', 'exit_plan_mode',
                        'create_goal', 'update_goal', 'lsp', 'analyze_multimedia']
        cwd = self.service.directory / 'workers' / self.provider
        cwd.mkdir(parents=True, exist_ok=True)
        if self.provider == 'codely':
            # An empty coreTools allowlist disables ALL built-ins. Auth/model defaults
            # still come from the user's CLI profile; only our MCP supplies tools.
            atomic_write(cwd / '.codely/settings.json', json.dumps({
                'coreTools': [], 'toolDiscoveryCommand': '', 'toolCallCommand': '',
                'mcpServerCommand': '',
            }).encode('utf-8'))
        child_env = os.environ.copy()
        child_env.setdefault('HOME', str(Path.home()))
        if self.provider == 'codex' and not child_env.get('CODEX_HOME'):
            child_env['CODEX_HOME'] = str(Path.home() / '.codex')
        self.peer = self.process_factory(command, cwd, self.notify, self.server_request, self.exited, env=child_env)
        try:
            if self.provider == 'codex':
                await self.peer.request('initialize', {'clientInfo': {'name': 'vault_rag', 'title': '本地知识库', 'version': __version__}})
                self.peer.notification('initialized')
            else:
                reply = await self.peer.request('initialize', {'protocolVersion': 1,
                    'clientInfo': {'name': 'vault-rag', 'version': __version__},
                    'clientCapabilities': {'fs': {'readTextFile': False, 'writeTextFile': False}, 'terminal': False}})
                self.capabilities = reply.get('agentCapabilities') or {}
                self.version = (reply.get('agentInfo') or {}).get('version', '')
        except BaseException:
            await self.peer.close()
            self.peer = None
            raise

    async def session(self, conversation):
        await self.start()
        key = conversation['id']
        if key in self.loaded:
            return conversation['native_id']
        native = conversation['native_id']
        cwd = conversation['cwd']
        mcp = {'name': 'vault-ai', 'type': 'http', 'url': self.service.mcp_url,
               'headers': [{'name': 'Authorization', 'value': 'Bearer ' + conversation['capability']}]}
        if self.provider == 'codex':
            config = self.service.codex_mcp_overrides()
            config.setdefault('mcp_servers', {})['vault-ai'] = {'url': self.service.mcp_url, 'enabled': True,
                'required': True, 'http_headers': {'Authorization': 'Bearer ' + conversation['capability']},
                'enabled_tools': list(SCOPED_TOOLS),
                'default_tools_approval_mode': 'auto'}
            # Disable inherited MCP tools: only the scoped knowledge server is allowed.
            params = {'cwd': cwd, 'sandbox': 'read-only', 'approvalPolicy': 'on-request', 'approvalsReviewer': 'user',
                      'config': config, 'developerInstructions': self.service.instructions,
                      'ephemeral': False}
            if native:
                params['threadId'] = native
            reply = await self.peer.request('thread/resume' if native else 'thread/start', params)
            restored = (reply.get('thread') or {}).get('id')
        else:
            standard_resume = (self.capabilities.get('sessionCapabilities') or {}).get('resume') is not None
            if not self.capabilities.get('loadSession') and not standard_resume and self.version not in ('1.0.0-rc.60', '1.0.0-nightly.67'):
                raise RpcError('此 Codely 版本未确认支持持久会话恢复；请使用已支持的版本')
            params = {'cwd': cwd, 'mcpServers': [mcp]}
            if native and self.capabilities.get('loadSession'):
                params['sessionId'] = native
                reply = await self.peer.request('session/load', params)
                restored = reply.get('sessionId', native)
            elif native and standard_resume:
                params['sessionId'] = native
                reply = await self.peer.request('session/resume', params)
                restored = reply.get('sessionId', native)
            else:
                if native:
                    # This is a Codely extension, NOT standard ACP session/new behavior.
                    if self.version not in ('1.0.0-rc.60', '1.0.0-nightly.67'):
                        raise RpcError('此 Codely 版本未确认支持原会话恢复；请使用已支持的版本')
                    params['_meta'] = {'codely': {'resumeSessionId': native}}
                    self.snapshots.pop(native, None)
                reply = await self.peer.request('session/new', params)
                restored = reply.get('sessionId')
                if native:
                    snapshot = self.snapshots.get(native)
                    if not snapshot or not any(snapshot.get(field) for field in ('messages', 'feed')):
                        raise RpcError('CLI 未恢复原会话历史；已停止发送，原记录仍保留')
        if not restored or (native and restored != native):
            raise RpcError('原会话被占用或 CLI 返回了新会话；不会切换到替代会话')
        self.service.bind_native(key, restored)
        conversation['native_id'] = restored
        self.loaded.add(key)
        return restored

    async def run(self, conversation, prompt):
        self.active = conversation
        self.turn_id = None
        self.turn_done = asyncio.get_running_loop().create_future()
        try:
            native = await self.session(conversation)
            if self.provider == 'codex':
                reply = await self.peer.request('turn/start', {'threadId': native,
                    'input': [{'type': 'text', 'text': prompt}], 'approvalPolicy': 'on-request',
                    'sandboxPolicy': {'type': 'readOnly'}})
                self.turn_id = (reply.get('turn') or {}).get('id')
                return await asyncio.wait_for(self.turn_done, timeout=1800)
            reply = await self.peer.request('session/prompt', {'sessionId': native,
                'prompt': [{'type': 'text', 'text': self.service.instructions + '\n\n' + prompt}]}, timeout=1800)
            if reply.get('stopReason') == 'cancelled':
                return 'interrupted'
            if reply.get('stopReason') not in ('end_turn', 'max_tokens'):
                raise RpcError('CLI 未正常结束本轮，请查看已保留的回答后重试')
            return 'completed'
        finally:
            self.active = None
            if self.turn_done:
                if self.turn_done.done() and not self.turn_done.cancelled():
                    self.turn_done.exception()
                elif not self.turn_done.done():
                    self.turn_done.cancel()
            self.turn_done = None

    async def notify(self, method, params):
        if method == 'session/update':
            update = params.get('update') or {}
            if update.get('sessionUpdate') == 'replace_history':
                self.snapshots[params.get('sessionId')] = update
                return
        if not self.active:
            return
        native = self.active.get('native_id')
        if method == 'session/update' and params.get('sessionId') == native:
            update = params.get('update') or {}
            if update.get('sessionUpdate') == 'agent_message_chunk':
                content = update.get('content') or {}
                if content.get('type') == 'text':
                    self.service.delta(self.active['id'], content.get('text', ''))
        elif params.get('threadId') == native:
            if method == 'item/agentMessage/delta':
                self.service.delta(self.active['id'], params.get('delta', ''))
            elif method == 'turn/started':
                self.turn_id = (params.get('turn') or {}).get('id')
            elif method == 'turn/completed' and self.turn_done and not self.turn_done.done():
                turn = params.get('turn') or {}
                if turn.get('status') == 'failed':
                    self.turn_done.set_exception(RpcError('CLI 本轮失败；请检查 CLI 登录、模型与配置后重试'))
                else:
                    self.turn_done.set_result('completed' if turn.get('status') == 'completed' else 'interrupted')

    async def server_request(self, method, params):
        if hasattr(self.service, 'request_methods'):
            self.service.request_methods.append(method)
        # Approval and filesystem/terminal callbacks never write or execute commands.
        if method == 'session/request_permission':
            safe = set(SCOPED_TOOLS)
            safe |= {'vault-ai__' + name for name in safe}
            tool = params.get('toolCall') or {}
            if (self.active and params.get('sessionId') == self.active.get('native_id')
                    and tool.get('name') in safe):
                option = next((o for o in params.get('options', []) if o.get('kind') == 'allow_once'), None)
                if option:
                    return {'outcome': {'outcome': 'selected', 'optionId': option['optionId']}}
            return {'outcome': {'outcome': 'cancelled'}}
        if method.endswith('/requestApproval'):
            return {'decision': 'decline'}
        raise RpcError('操作不允许')

    async def exited(self):
        self.loaded.clear()
        if self.turn_done and not self.turn_done.done():
            self.turn_done.set_exception(RpcError('CLI 已退出，原对话仍保留'))

    async def interrupt(self):
        if not self.active or not self.peer or self.peer.closed:
            return
        native = self.active.get('native_id')
        if self.provider == 'codex' and native and self.turn_id:
            await self.peer.request('turn/interrupt', {'threadId': native, 'turnId': self.turn_id}, timeout=10)
        elif self.provider == 'codely' and native:
            self.peer.notification('session/cancel', {'sessionId': native})

    async def close(self):
        if self.peer:
            await self.peer.close()
        self.loaded.clear()
