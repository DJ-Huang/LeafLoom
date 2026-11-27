"""Local browser sessions for whole-database encrypted storage."""
import json
import mimetypes
from pathlib import Path
from urllib.parse import unquote
import posixpath
import uuid

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

from vault_rag import database_envelope as envelope, locked_photos
from vault_rag.database_memory import DEFINITION, MemoryDatabase
from vault_rag.local_state import ConflictError, digest, relative, split_link
from vault_rag.photo_routes import require_local_browser

SESSION_HEADER = 'x-database-session'


def resolve_asset(names, target, source):
    target = unquote(split_link(target)[0]).strip()
    if not target or target.startswith(('/', '#')) or ':' in target or '\\' in target:
        return None
    parent = source.rpartition('/')[0]
    source_relative = posixpath.normpath('/'.join(filter(None, (parent, target))))
    for possible in (source_relative, target):
        if possible in names:
            return possible
    matches = [name for name in names if name.rsplit('/', 1)[-1] == target.rsplit('/', 1)[-1]]
    return matches[0] if len(matches) == 1 else None


def database_security_router(config, runtime, databases, browser_cookie, csrf):
    router = APIRouter(prefix='/api/database-security')
    sessions = locked_photos.Sessions()

    def path_for(root, path, *, writable=False):
        if root != str(config.root):
            raise ConflictError('db.securityWorkspaceChanged')
        if not isinstance(path, str) or Path(path).suffix.lower() != '.base':
            raise ValueError('db.securityInvalid')
        return config.path_for(path, writable=writable)

    def owner(root, prefix):
        return root, digest(prefix)

    def version(path):
        stat = path.stat()
        return stat.st_ino, stat.st_mtime_ns, stat.st_size

    async def json_body(request, limit=12 * 1024 * 1024):
        data = bytearray()
        async for part in request.stream():
            if len(data) + len(part) > limit:
                raise ValueError('db.securityTooLarge')
            data.extend(part)
        try:
            result = json.loads(data)
        except (ValueError, UnicodeError) as exc:
            raise ValueError('db.securityInvalid') from exc
        if not isinstance(result, dict):
            raise ValueError('db.securityInvalid')
        return result

    def process(request, root, path, operation):
        with config.lock, runtime.files.lock:
            package = path_for(root, path)
            prefix = envelope.header(package)
            secret = sessions.key(owner(root, prefix), request.headers.get(SESSION_HEADER))
            before = version(package)
            state = MemoryDatabase(config.root, config.data['revision'], *envelope.decode(package, secret, prefix))
            result = operation(state)
            if state.mutated:
                encrypted = envelope.encode(secret, prefix, state.files, state.directories, state.catalog.version)
                if version(package) != before:
                    raise ConflictError('db.securityWorkspaceChanged')
                locked_photos.atomic_bytes(package, encrypted)
            return result

    @router.get('')
    async def status(request: Request, root: str, path: str):
        require_local_browser(request, browser_cookie, csrf)
        return {'encrypted': await run_in_threadpool(lambda: envelope.encrypted(path_for(root, path)))}

    @router.post('/unlock')
    async def unlock(request: Request, root: str, path: str):
        require_local_browser(request, browser_cookie, csrf)
        body = await json_body(request, 4096)
        if not isinstance(body.get('password'), str):
            raise ValueError('db.securityInvalid')

        def open_db():
            with config.lock:
                package = path_for(root, path)
                prefix = envelope.header(package)
                database = owner(root, prefix)
                try:
                    token = sessions.unlock(database, prefix[len(envelope.MAGIC):], body['password'])
                except locked_photos.Locked as exc:
                    raise ValueError('db.securityWrongPassword') from exc
                try:
                    envelope.decode(package, sessions.key(database, token), prefix)
                except Exception:
                    sessions.revoke(token)
                    raise
                return {'token': token}

        return await run_in_threadpool(open_db)

    @router.post('/lock')
    async def lock(request: Request):
        require_local_browser(request, browser_cookie, csrf)
        sessions.revoke(request.headers.get(SESSION_HEADER))
        return {'ok': True}

    @router.post('/create')
    async def create(request: Request, root: str, path: str):
        require_local_browser(request, browser_cookie, csrf)
        body = await json_body(request, 4096)

        def create_db():
            with config.lock, runtime.files.lock:
                package = path_for(root, path, writable=True)
                runtime.files.ensure_mutable()
                if package.exists():
                    raise ConflictError('db.securityFileExists')
                if not package.parent.is_dir():
                    raise ValueError('db.securityFileMissing')
                state = MemoryDatabase(config.root, config.data['revision'])
                state.database.command(DEFINITION, {'type': 'create', 'folder': 'Records',
                    'preset': body.get('preset')}, config.data['revision'], operation_id=uuid.uuid4().hex)
                secret, prefix = envelope.new_key(body.get('password'))
                encrypted = envelope.encode(secret, prefix, state.files, state.directories, state.catalog.version)
                session = sessions.unlock(owner(root, prefix), prefix[len(envelope.MAGIC):], body['password'])
                try:
                    if package.exists():
                        raise ConflictError('db.securityFileExists')
                    locked_photos.atomic_bytes(package, encrypted)
                except Exception:
                    sessions.revoke(session)
                    raise
                runtime.files_changed(path)
                runtime.publish('files', [path])
                return {'path': path, 'token': session}

        return await run_in_threadpool(create_db)

    @router.post('/preview')
    async def preview(request: Request, root: str, path: str):
        require_local_browser(request, browser_cookie, csrf)
        from vault_rag.database_conversion import DatabaseConversion
        return await run_in_threadpool(DatabaseConversion(config, runtime, databases, root, path).preview)

    @router.post('/convert')
    async def convert(request: Request, root: str, path: str):
        require_local_browser(request, browser_cookie, csrf)
        from vault_rag.database_conversion import DatabaseConversion
        body = await json_body(request, 8192)
        return await run_in_threadpool(DatabaseConversion(config, runtime, databases, root, path).convert, body)

    @router.get('/config')
    async def private_config(request: Request, root: str, path: str):
        require_local_browser(request, browser_cookie, csrf)

        def config_read(state):
            return {**state.database.config_read(DEFINITION), 'path': path}

        return await run_in_threadpool(process, request, root, path, config_read)

    @router.post('/query')
    async def query(request: Request, root: str, path: str):
        require_local_browser(request, browser_cookie, csrf)
        body = await json_body(request)
        return await run_in_threadpool(process, request, root, path, lambda state: state.database.query(
            DEFINITION, body.get('view_id', ''), body.get('search', ''), body.get('cursor', ''),
            body.get('limit', 100), body.get('group_key'), body.get('anchor_path', ''), body.get('recent_paths')))

    @router.post('/commands')
    async def command(request: Request, root: str, path: str):
        require_local_browser(request, browser_cookie, csrf)
        body = await json_body(request)
        action = body['command']
        if action.get('type') == 'create':
            raise ValueError('db.securityInvalid')

        def run(state):
            result = state.database.command(DEFINITION, action, body['workspace_revision'],
                body.get('expected_revision', ''), body.get('operation_id', ''))
            if result.get('path') == DEFINITION:
                result['path'] = path
            return result

        return await run_in_threadpool(process, request, root, path, run)

    @router.post('/record/read')
    async def record(request: Request, root: str, path: str):
        require_local_browser(request, browser_cookie, csrf)
        body = await json_body(request, 8192)
        return await run_in_threadpool(process, request, root, path, lambda state: state.read(record_path(body['source'])))

    @router.post('/record')
    async def save(request: Request, root: str, path: str):
        require_local_browser(request, browser_cookie, csrf)
        body = await json_body(request)
        return await run_in_threadpool(process, request, root, path, lambda state: state.save(
            record_path(body['source']), body['text'], body['revision'], expected_root=root))

    @router.post('/asset/read')
    async def asset(request: Request, root: str, path: str):
        require_local_browser(request, browser_cookie, csrf)
        body = await json_body(request, 16384)

        def read_asset(state):
            names = [name for name in state.files if not name.startswith('.')]
            found = resolve_asset(names, body['target'], body['source'])
            if found is None:
                raise ValueError('db.securityFileMissing')
            content = state.path_for(found).read_bytes()
            mime = mimetypes.guess_type(found)[0] or 'application/octet-stream'
            if mime not in {'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/avif', 'image/svg+xml',
                            'video/mp4', 'video/quicktime', 'video/webm', 'audio/mpeg', 'audio/wav'}:
                mime = 'application/octet-stream'
            return Response(content, media_type=mime, headers={'Cache-Control': 'no-store'})

        return await run_in_threadpool(process, request, root, path, read_asset)

    @router.post('/asset')
    async def upload(request: Request, root: str, path: str):
        require_local_browser(request, browser_cookie, csrf)
        name = unquote(request.headers.get('x-database-filename', ''))
        if not name or len(name) > 200 or '/' in name or '\\' in name or name.startswith('.'):
            raise ValueError('db.securityInvalid')
        incoming = bytearray()
        async for part in request.stream():
            if len(incoming) + len(part) > envelope.MAX_BYTES:
                raise ValueError('db.securityTooLarge')
            incoming.extend(part)

        def add(state):
            target = f'Attachments/{uuid.uuid4().hex}/{relative(name)}'
            state.write_state(state.path_for(target), bytes(incoming))
            return {'path': target}

        return await run_in_threadpool(process, request, root, path, add)

    return router


def record_path(source):
    path = relative(source)
    if not path.lower().endswith('.md') or any(part.startswith('.') for part in path.split('/')):
        raise ValueError('db.securityInvalid')
    return path
