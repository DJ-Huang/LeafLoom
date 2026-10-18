"""Managed design API. Browser writes are rooted and revision checked."""
from __future__ import annotations
import asyncio
import uuid
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from vault_rag.local_state import ConflictError


def design_router(studio):
    router = APIRouter(prefix='/api/design')
    documents, workspace = studio.documents, studio.workspace

    def guard(body):
        if not isinstance(body, dict) or body.get('root') != str(studio.config.root):
            raise ConflictError('Connected folder changed; reopen the design project')

    async def run(body, operation, *args, **kwargs):
        def execute():
            # Recheck after the work reaches its worker; the folder can change
            # between receiving a request and acquiring the file transaction.
            with studio.config.lock:
                guard(body)
                value = operation(*args, **kwargs)
                if 'view_page_id' in body and isinstance(value, dict) and 'document' in value:
                    return documents.project_view(value, body.get('view_page_id'))
                return value
        return await asyncio.to_thread(execute)

    @router.get('/templates/{template_id}/preview')
    async def template_preview(template_id: str):
        from vault_rag.design_templates import template_path
        path = template_path(template_id) / 'preview.jpg'
        if not path.is_file():
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail='Template uses an inline preview')
        return FileResponse(path, media_type='image/jpeg')

    @router.get('/document')
    async def read_document(directory: str, page_id: str | None = None, manifest: bool = False, root: str | None = None, view: bool = False):
        if root is not None:
            guard({'root': root})
        operation = documents.manifest if manifest else documents.page_view if view else documents.read
        return await asyncio.to_thread(operation, directory, **({} if manifest else {'page_id': page_id}))

    @router.post('/operations')
    async def operations(request: Request):
        body = await request.json(); guard(body)
        return await run(body, documents.apply, body['directory'], body['commands'], body['expected_revision'],
                                       body['operation_id'], label=body.get('label', ''), workspace_revision=studio.workspace_revision)

    @router.post('/history')
    async def history(request: Request):
        body = await request.json(); guard(body)
        return await run(body, documents.history, body['directory'], body.get('action', 'list'),
                                       expected_revision=body.get('expected_revision'), operation_id=body.get('operation_id'),
                                       offset=body.get('offset', 0), limit=body.get('limit', 50))

    @router.post('/assets')
    async def import_asset(request: Request, directory: str, name: str, root: str, expected_revision: str, operation_id: str, view_page_id: str | None = None):
        guard({'root': root})
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 128 * 1024 * 1024:
                raise ValueError('Design asset exceeds 128 MiB')
            chunks.append(chunk)
        def save():
            with studio.config.lock:
                guard({'root': root})
                value = documents.import_asset(directory, name, b''.join(chunks), expected_revision, operation_id,
                                               request.headers.get('content-type', ''))
                return documents.project_view(value, view_page_id or None) if view_page_id is not None else value
        return await asyncio.to_thread(save)

    @router.post('/session')
    async def session(request: Request):
        body = await request.json(); guard(body)
        return await run(body, workspace.session, body['directory'], body.get('capture', False))

    @router.post('/export')
    async def export(request: Request):
        body = await request.json(); guard(body)
        return await run(body, workspace.export, body['directory'])

    @router.post('/publish/preflight')
    async def publishing_preflight(request: Request):
        body = await request.json(); guard(body)
        return await run(body, workspace.publisher.preflight, body)

    @router.post('/publish')
    async def publish(request: Request):
        body = await request.json(); guard(body)
        return await run(body, workspace.publisher.start, body)

    @router.get('/publish/{job_id}')
    async def publishing_status(job_id: str, root: str):
        body = {'root': root}; guard(body)
        return await run(body, workspace.publisher.get, job_id)

    @router.post('/publish/{job_id}/retry')
    async def publishing_retry(job_id: str, request: Request):
        body = await request.json(); guard(body)
        return await run(body, workspace.publisher.retry, job_id)

    @router.get('/publish/{job_id}/download')
    async def publishing_download(job_id: str, root: str):
        body = {'root': root}; guard(body)
        path, mime, name = await run(body, workspace.publisher.download, job_id)
        return FileResponse(path, media_type=mime, filename=name)

    @router.get('/publish/{job_id}/native-manifest')
    async def publishing_native_manifest(job_id: str):
        return await run({'root': str(studio.config.root)}, workspace.publisher.native_manifest, job_id)

    @router.post('/publish/{job_id}/native-failure')
    async def publishing_native_failure(job_id: str, request: Request):
        body = await request.json()
        return await run({'root': str(studio.config.root)}, workspace.publisher.native_failure, job_id, body.get('error'))

    @router.post('/publish/{job_id}/native-result')
    async def publishing_native_result(job_id: str, request: Request):
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 97 * 1024 * 1024:
                raise ValueError('Publication result exceeds the request limit')
            chunks.append(chunk)
        import json
        body = json.loads(b''.join(chunks))
        return await run({'root': str(studio.config.root)}, workspace.publisher.native_result, job_id, body)

    @router.get('/workspace')
    async def workspace_state():
        return await asyncio.to_thread(workspace.state)

    @router.post('/workspace')
    async def workspace_operation(request: Request):
        body = await request.json(); guard(body)
        return await run(body, workspace.manage, body['directory'], body['action'], body['expected_revision'],
                                       body['operation_id'], **{k: body[k] for k in ('value', 'destination') if k in body})

    @router.post('/workspace/history')
    async def workspace_history(request: Request):
        body = await request.json(); guard(body)
        return await run(body, workspace.history, body['action'], body['expected_revision'])

    @router.post('/workspace/trash')
    async def purge_project_trash(request: Request):
        body = await request.json(); guard(body)
        return await run(body, workspace.purge_trash, body.get('directories'), body['expected_revision'],
                         body['operation_id'], confirm=body.get('confirm', False))

    @router.post('/copy')
    async def copy_project(request: Request):
        body = await request.json(); guard(body)
        return await run(body, workspace.copy_project, body['directory'], body['destination'])

    @router.post('/migrate')
    async def migrate(request: Request):
        body = await request.json(); guard(body)
        return await run(body, workspace.migrate, body['directory'], body['destination'])

    @router.post('/migrate/finish')
    async def finish_migration(request: Request):
        body = await request.json(); guard(body)
        return await run(body, workspace.finish_migration, body['directory'], body['pages'],
                                       body['expected_revision'], body['operation_id'])

    @router.get('/library')
    async def library():
        return await asyncio.to_thread(workspace.library)

    @router.post('/library')
    async def library_operation(request: Request):
        body = await request.json(); guard(body)
        if body['action'] == 'publish':
            for kind in ('component', 'asset', 'style', 'script'):
                key = kind + '_id'
                if key in body:
                    return await run(body, workspace.publish, body['directory'], kind, body[key],
                                                   body.get('expected_workspace_revision'), body.get('operation_id'))
            raise ValueError('Choose a component, asset, style or script to publish')
        if body['action'] != 'import':
            raise ValueError('Expected publish or import')
        return await run(body, workspace.import_library, body['directory'], body['item_id'], body['expected_revision'],
                                       body['operation_id'], body.get('version'))

    return router
