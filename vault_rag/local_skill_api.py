"""Loopback operations for the bundled LeafLoom skill."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import secrets
from inspect import signature

from fastapi import APIRouter, HTTPException, Request

from vault_rag.local_state import atomic_write
from vault_rag.mcp_access import TUNNEL_AUTH_HEADER
from vault_rag.platform_support import private_file_mode


def local_skill_router(config, runtime, notes, databases, access, feishu):
    credential = config.directory / 'leafloom-skill-token'
    if not credential.exists():
        atomic_write(credential, secrets.token_urlsafe(48).encode())
    private_file_mode(credential)
    token = credential.read_bytes().strip()
    authorization = b'Bearer ' + token
    file_owner = hashlib.sha256(b'leafloom-skill:' + token).hexdigest()
    router = APIRouter(prefix='/api/leafloom')

    def status():
        return {'ok': True, 'vault_root': config.data.get('root'),
                'wiki_roots': config.data.get('wiki_roots', []),
                'write_targets': config.data.get('write_targets', {}),
                'workspace_revision': notes.workspace_revision,
                'capabilities': access.capabilities('local')}

    def search(query, top_k=3, note_type=None, domain=None, mode='hybrid', compact=True):
        return runtime.knowledge.search(query, top_k=top_k, type_=note_type, domain=domain,
                                        mode=mode, compact=compact)

    def rules(query, top_k=3, domain=None, compact=True):
        if domain == 'pcg':
            return {'ok': True, 'no_relevant_hit': True, 'results': []}
        return runtime.knowledge.search(query, top_k=top_k, domain=domain, rules=True, compact=compact)

    reads = {'status': status, 'search': search, 'rules': rules,
             'chunk': runtime.knowledge.get_chunk, 'source': runtime.knowledge.get_note,
             'task-databases': databases.discover, 'task-config': databases.config_read,
             'task-query': databases.query, 'task-record': databases.read_record,
             'directory-list': notes.list_directory, 'note-find': notes.find,
             'note-read': notes.read, 'note-query': notes.query}
    writes = {'task-command': databases.command, 'note-create': notes.create,
              'note-update': notes.update, 'directory-create': notes.create_folder,
              'reindex': notes.reindex}

    def feishu_call(operation, *, write=False):
        return feishu.authorized_call(config, access, lambda: 'local', operation, write=write, owner=file_owner)

    def feishu_read(argv, stdin=None, input_files=None):
        return feishu_call(lambda owner, check, high, _: feishu.execute(
            argv, stdin=stdin, input_files=input_files, owner=owner, source_check=check, require_high_risk=high))

    def feishu_write(argv, stdin=None, input_files=None, confirm=False, expected_revision=None):
        if type(confirm) is not bool:
            raise ValueError('Feishu confirmation must be a boolean')
        return feishu_call(lambda owner, check, high, _: feishu.execute(
            argv, write=True, stdin=stdin, input_files=input_files, confirm=confirm,
            expected_revision=expected_revision, owner=owner, source_check=check, require_high_risk=high), write=True)

    def feishu_files(action, file_id='', name='', offset=0, data_base64='', complete=False, size=None, sha256='', path=''):
        return feishu_call(lambda owner, check, high, _: feishu.files.operation(
            owner, check, action, file_id=file_id, name=name, offset=offset, data_base64=data_base64,
            complete=complete, size=size, sha256=sha256, path=path))

    office = {
        'feishu-inspect': lambda action, argv=None, path='': feishu_call(lambda *_: feishu.inspect(action, argv, path)),
        'feishu-read': feishu_read, 'feishu-write': feishu_write, 'feishu-files': feishu_files,
    }

    @router.post('/{operation}')
    async def invoke(operation: str, arguments: dict, request: Request):
        try:
            local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            local = False
        if (not local or not token or request.headers.get(TUNNEL_AUTH_HEADER) or
                not hmac.compare_digest(request.headers.get('authorization', '').encode(), authorization)):
            raise HTTPException(401, 'Local LeafLoom Skill credential required')
        write = operation in writes
        run = writes.get(operation) if write else reads.get(operation) or office.get(operation)
        if run is None:
            raise HTTPException(404, 'Unknown LeafLoom Skill operation')
        try:
            signature(run).bind(**arguments)
        except TypeError as error:
            raise ValueError(str(error)) from error

        def execute():
            if operation in office:
                try:
                    return run(**arguments)
                except PermissionError as error:
                    raise HTTPException(403, str(error)) from error
            with access.lock:
                try:
                    access.require('local', write=write)
                except PermissionError as error:
                    permission = 'write' if write else 'read'
                    raise HTTPException(403, f'Enable local AI {permission} access in LeafLoom settings') from error
                if write:
                    return run(**arguments)
            return run(**arguments)

        return await asyncio.to_thread(execute)

    return router
