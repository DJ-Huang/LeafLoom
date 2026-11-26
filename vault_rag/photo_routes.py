"""Local, session-authorized access to protected database cover images."""
from hashlib import sha256
import re
import secrets

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from . import locked_photos as crypto
from . import protected_media as media

SCOPES_FILE = media.LEGACY_SCOPES
PHOTO_HEADER = 'X-Photo-Session'
PHOTO_ID = re.compile(r'[a-f0-9]{32}|[a-f0-9]{64}')
MIME = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}


def photo_router(config, runtime, databases, browser_cookie, csrf):
    router = APIRouter(prefix='/api/photo-vault')
    sessions = crypto.Sessions()

    def workspace(root):
        active = config.root
        if str(active) != root:
            raise ValueError('Connected folder changed')
        storage = active / '.vault-rag'
        if storage.is_symlink():
            raise ValueError('Protected media storage cannot be a link')
        if any((storage / name).exists() for name in (crypto.MIGRATING, crypto.CAPTION_PENDING)):
            raise crypto.Locked('Photo migration is in progress')
        return active, storage

    def browser(request):
        from hmac import compare_digest
        from ipaddress import ip_address

        if (not request.client or not ip_address(request.client.host).is_loopback
                or not compare_digest(request.cookies.get('vault_session', '').encode(), browser_cookie.encode())
                or (request.method == 'POST' and not compare_digest(
                    request.headers.get('x-vault-csrf', '').encode(), csrf.encode()))):
            raise PermissionError()

    def key(request, storage):
        return sessions.key(storage, request.headers.get(PHOTO_HEADER))

    def asset_path(active, relative):
        gallery = media.asset_gallery(active, relative)
        if not gallery or not crypto.ASSET.fullmatch(relative.rsplit('/', 1)[-1]):
            raise FileNotFoundError('Encrypted photo is outside the gallery')
        return gallery.folder, config.path_for(relative)

    def mime(data):
        from io import BytesIO

        from PIL import Image

        with Image.open(BytesIO(data)) as picture:
            kind = MIME.get(picture.format)
            if not kind or picture.width * picture.height > 24_000_000 or getattr(picture, 'n_frames', 1) != 1:
                raise ValueError('Unsupported photo')
            picture.verify()
        return kind

    def error(exc):
        code = 423 if isinstance(exc, crypto.Locked) else 429 if isinstance(exc, crypto.Busy) else 400
        return JSONResponse({'error': str(exc)}, status_code=code)

    @router.get('/format')
    async def format_version(root: str):
        try:
            _, storage = workspace(root)
            key_file = media.envelope_path(storage)
            return {'version': 1, 'caption_encryption': True,
                    'key_id': sha256(key_file.read_bytes()).hexdigest() if key_file.is_file() else ''}
        except (crypto.Locked, ValueError, OSError) as exc:
            return error(exc)

    @router.get('')
    async def photo_status(request: Request, root: str):
        browser(request)
        try:
            active, storage = workspace(root)
            ready = media.envelope_path(storage).is_file()
            profiles = media.galleries(active)
            return {'scopes': list(profiles), 'key_ready': ready,
                    'protected_captions': (storage / crypto.CAPTION_MARKER).is_file(),
                    'galleries': [{'folder': g.folder, 'captions': g.captions,
                                   'title': crypto.CAPTION_TITLE if g.legacy else None}
                                  for g in profiles.values()]}
        except (crypto.Locked, ValueError, OSError) as exc:
            return error(exc)

    @router.post('')
    async def photo_session(request: Request, root: str):
        browser(request)
        try:
            _, storage = workspace(root)
            length = int(request.headers.get('content-length', '0'))
            if not 0 < length <= 2048 or request.headers.get('content-type', '').split(';')[0] != 'application/json':
                raise ValueError('Invalid photo session request')
            body = await request.json()
            if body == {'action': 'lock'}:
                sessions.revoke(request.headers.get(PHOTO_HEADER))
                return {'unlocked': False}
            if not isinstance(body, dict) or set(body) != {'password'}:
                raise ValueError('Invalid photo session request')
            token = await run_in_threadpool(sessions.unlock, storage, media.envelope_path(storage).read_bytes(),
                                            body['password'])
            sessions.revoke(request.headers.get(PHOTO_HEADER))
            return {'token': token}
        except (crypto.Locked, crypto.Busy, ValueError, OSError) as exc:
            return error(exc)

    @router.post('/gallery')
    async def enable_gallery(request: Request, root: str):
        browser(request)
        try:
            if (not 0 < int(request.headers.get('content-length', '0')) <= 4096
                    or request.headers.get('content-type', '').split(';')[0] != 'application/json'):
                raise ValueError('Invalid protected gallery request')
            body = await request.json()
            if (not isinstance(body, dict) or set(body) not in ({'database', 'captions'}, {'database', 'captions', 'password'})
                    or type(body['captions']) is not bool):
                raise ValueError('Invalid protected gallery request')

            def enable():
                with config.lock, runtime.files.lock:
                    active, storage = workspace(root)
                    database = media.relative(body['database'])
                    if not database.endswith('.base') or not config.path_for(database, writable=True).is_file():
                        raise ValueError('Select a database')
                    folder = media.relative(databases.config_read(database)['folder'], root_allowed=True)
                    if not config.path_for(folder).is_dir():
                        raise ValueError('Select a database with an existing record folder')
                    profiles = media.galleries(active)
                    if folder in profiles:
                        raise ValueError('Protected gallery is already configured')
                    assets = config.path_for(media.child(folder, media.ASSET_DIR), writable=True)
                    if assets.exists() and not assets.is_dir():
                        raise ValueError('Protected photo storage must be a folder')
                    envelope = media.envelope_path(storage)
                    if envelope.is_file():
                        key(request, storage)
                    else:
                        if profiles:
                            raise ValueError('Restore the vault photo key before adding a gallery')
                        password = body.get('password')
                        if not isinstance(password, str) or len(password) < 12:
                            raise ValueError('Use a photo passphrase of at least 12 characters')
                        crypto.atomic_bytes(envelope, crypto.wrap_key(secrets.token_bytes(32), password))
                    media.add_gallery(active, folder, body['captions'])
                return {'folder': folder}

            return JSONResponse(await run_in_threadpool(enable), headers={'Cache-Control': 'no-store'})
        except (crypto.Locked, crypto.Busy, ValueError, OSError) as exc:
            return error(exc)

    @router.get('/image')
    async def photo_image(request: Request, root: str, path: str):
        browser(request)

        def view():
            active, storage = workspace(root)
            secret = key(request, storage)
            scope, asset = asset_path(active, path)
            data = crypto.open_payload(secret, scope, asset.name, crypto.read_encrypted(asset))
            return Response(data, media_type=mime(data), headers={'Cache-Control': 'no-store'})

        if not sessions.readers.acquire(blocking=False):
            return error(crypto.Busy('Photo readers are busy'))
        try:
            return await run_in_threadpool(view)
        except (crypto.Locked, ValueError, OSError) as exc:
            return error(exc)
        finally:
            sessions.readers.release()

    def caption_note(request, root, source):
        active, storage = workspace(root)
        secret = key(request, storage)
        gallery = media.galleries(active).get(media.parent(source))
        if not gallery or not gallery.captions or not source.endswith('.md') or not config.path_for(source).is_file():
            raise ValueError('Record is outside the encrypted photo gallery')
        note = runtime.files.read(source)
        ident = note['metadata'].get('photo_id') or sha256(source.encode()).hexdigest()
        if not isinstance(ident, str) or not PHOTO_ID.fullmatch(ident):
            raise ValueError('Invalid photo identifier')
        return secret, gallery, note, ident

    @router.get('/caption')
    async def read_caption(request: Request, root: str, source: str):
        browser(request)
        try:
            secret, gallery, note, ident = await run_in_threadpool(caption_note, request, root, source)
            value = note['metadata'].get(crypto.CAPTION_FIELD)
            caption = crypto.open_caption(secret, gallery.folder, ident, value) if value else ''
            return JSONResponse({'caption': caption, 'revision': note['etag']}, headers={'Cache-Control': 'no-store'})
        except (crypto.Locked, ValueError, OSError) as exc:
            return error(exc)

    @router.post('/caption')
    async def write_caption(request: Request, root: str, source: str):
        browser(request)
        try:
            if not 0 < int(request.headers.get('content-length', '0')) <= 4096:
                raise ValueError('Invalid photo caption request')
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {'caption', 'revision'}:
                raise ValueError('Invalid photo caption request')

            def store():
                secret, gallery, note, ident = caption_note(request, root, source)
                meta = note['metadata']
                if gallery.legacy and meta.get('title') not in (None, crypto.CAPTION_TITLE):
                    raise ValueError('Migrate the existing photo caption before editing')
                updates = {'photo_id': ident,
                           crypto.CAPTION_FIELD: crypto.seal_caption(secret, gallery.folder, ident, body['caption'])}
                if gallery.legacy:
                    updates['title'] = crypto.CAPTION_TITLE
                result = runtime.files.properties(source, updates, body['revision'], expected_root=root)
                return {'revision': result['etag']}

            return JSONResponse(await run_in_threadpool(store), headers={'Cache-Control': 'no-store'})
        except (crypto.Locked, ValueError, OSError) as exc:
            return error(exc)

    @router.post('/image')
    async def photo_upload(request: Request, root: str, source: str):
        browser(request)
        try:
            active, storage = workspace(root)
            secret = key(request, storage)
            gallery = media.galleries(active).get(media.parent(source))
            if not gallery or not source.endswith('.md') or not config.path_for(source).is_file():
                raise ValueError('Select a record in the encrypted photo gallery')
            incoming = bytearray()
            async for part in request.stream():
                if len(incoming) + len(part) > crypto.MAX_IMAGE:
                    raise ValueError('Photo is too large')
                incoming.extend(part)
            data = bytes(incoming)

            def store():
                mime(data)
                with config.lock, runtime.files.lock:
                    workspace(root)
                    name = crypto.asset_name(secret, gallery.folder, data)
                    relative = media.child(gallery.assets, name)
                    path = config.path_for(relative, writable=True)
                    if path.exists() or path.is_symlink():
                        if crypto.open_payload(secret, gallery.folder, name, crypto.read_encrypted(path)) != data:
                            raise ValueError('Encrypted photo failed verification')
                    else:
                        crypto.atomic_bytes(path, crypto.seal(secret, gallery.folder, name, data))
                        runtime.files_changed(relative)
                return {'path': relative}

            return await run_in_threadpool(store)
        except (crypto.Locked, ValueError, OSError) as exc:
            return error(exc)

    return router
