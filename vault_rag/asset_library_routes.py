"""Authenticated local UI routes for the NAS product catalog and prepared files.

The application security middleware supplies the same session/CSRF boundary as
attachment APIs. No route accepts arbitrary local paths or exposes storage URLs.
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import uuid
import threading

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response

from vault_rag.local_state import ConflictError


class PreparedFileResponse(FileResponse):
    """Keep the staging reservation until an entire HTTP response closes."""
    def __init__(self,*args,downloads,root,job_id,**kwargs):
        super().__init__(*args,**kwargs)
        self.downloads,self.root,self.job_id=downloads,root,job_id

    async def __call__(self,scope,receive,send):
        try:await super().__call__(scope,receive,send)
        finally:
            # This short, local-only cleanup is intentionally synchronous: an
            # already cancelled ASGI task must still drop its reader reference.
            self.downloads.release_handle(self.root,self.job_id)


def asset_library_router(library,downloads,enrichment):
    router=APIRouter()
    settings_lock=threading.RLock()

    def settings(root,storage_id=''):
        value=library.settings(root)
        usage=downloads.usage(root)
        download_settings=downloads.settings(root)
        revision=hashlib.sha256((value['revision']+':'+download_settings['revision']).encode()).hexdigest()
        return {**value,'revision':revision,'download_limit_bytes':download_settings['max_bytes'],
                'downloads':{'used_bytes':usage.get('used_bytes',0),'files':usage.get('ready_jobs',0),**usage},
                'status':library.status(root)}

    @router.get('/api/asset-library/settings')
    async def get_settings(root:str,storage_id:str=''):
        return await asyncio.to_thread(settings,root,storage_id)

    @router.put('/api/asset-library/settings')
    async def save_settings(request:Request):
        body=await request.json()
        if set(body)-{'root','storage_id','revision','metadata_directory','download_limit_bytes'}:
            raise ValueError('Unknown product catalog setting')
        root=body['root']
        # Validate the independent budget before changing either setting.
        size=body.get('download_limit_bytes',downloads.settings(root)['max_bytes'])
        if isinstance(size,bool) or not isinstance(size,int) or not 1024**3<=size<=1024**5:
            raise ValueError('Download staging capacity must be between 1 GiB and 1 PiB')
        def save():
            with settings_lock:
                if body.get('revision')!=settings(root)['revision']:raise ConflictError('Product catalog settings changed; reload before saving')
                # A pending full-file reservation cannot be silently displaced.
                if downloads.usage(root)['reserved_bytes']>size:
                    raise ValueError('Release staged downloads before reducing the capacity')
                current=library.settings(root)
                changes={k:body[k] for k in ('storage_id','metadata_directory') if k in body}
                if any(current.get(k)!=v for k,v in changes.items()):
                    library.save_settings(root,changes,expected_revision=current['revision'])
                if 'download_limit_bytes' in body:downloads.configure(root,size)
        await asyncio.to_thread(save)
        return await asyncio.to_thread(settings,root)

    @router.get('/api/asset-library/status')
    async def status(root:str,storage_id:str=''):
        value=await asyncio.to_thread(library.status,root)
        value['enrichment']=await asyncio.to_thread(enrichment.status,root)
        return value

    @router.get('/api/asset-library')
    async def listing(root:str,query:str='',status:str='',limit:int=100,cursor:str=''):
        if not 1<=limit<=200:raise ValueError('Use a page size between 1 and 200')
        return await asyncio.to_thread(library.listing,root,query=query,status=status,limit=limit,cursor=cursor)

    @router.get('/api/asset-library/products/{product_id}')
    async def detail(product_id:str,root:str):
        return await asyncio.to_thread(library.detail,root,product_id)

    @router.get('/api/asset-library/covers/{product_id}')
    async def cover(product_id:str,root:str):
        try:path=await asyncio.to_thread(library.cover,root,product_id)
        except FileNotFoundError:return Response(status_code=404)
        return FileResponse(path,media_type='image/webp',headers={
            'Cache-Control':'private, no-cache','X-Content-Type-Options':'nosniff',
            'Content-Security-Policy':"default-src 'none'; sandbox"})

    @router.post('/api/asset-library/enrichment/{mode}')
    async def batch_enrichment(mode:str,request:Request):
        body=await request.json()
        if mode not in {'plan','start'}:raise ValueError('Unknown batch collection mode')
        if not isinstance(body,dict) or set(body)-{'root','item_ids','limit','refresh','delay'}:
            raise ValueError('Unknown batch collection option')
        options={key:value for key,value in body.items() if key!='root'}
        method=enrichment.plan if mode=='plan' else enrichment.start
        return await asyncio.to_thread(method,body['root'],**options)

    @router.post('/api/asset-library/actions')
    async def action(request:Request):
        body=await request.json()
        root=body['root'];kind=body.get('action','')
        if kind in {'discover','initialize'}:return await asyncio.to_thread(library.initialize,root,body.get('storage_id',''))
        if kind=='sync':return await asyncio.to_thread(library.sync,root,body.get('storage_id',''),resume=True)
        if kind=='rebuild':return await asyncio.to_thread(library.rebuild,root)
        if kind=='enrich':return await asyncio.to_thread(enrichment.start,root)
        if kind=='defer_enrichment':
            if body.get('reason')!='browser_origin_permission':raise ValueError('Unknown collection pause reason')
            return await asyncio.to_thread(enrichment.record_blocked,root,body['reason'])
        if kind=='official_url':
            return await asyncio.to_thread(enrichment.official_url,root,body.get('url',''),
                item_id=body.get('id',body.get('product_id','')),asset_id=body.get('asset_id',''),
                operation_id=body.get('operation_id') or uuid.uuid4().hex,
                expected_revision=body.get('expected_revision',''))
        operation={'metadata':'personal','confirm_match':'bind'}.get(kind,kind)
        if operation not in {'official','bind','personal','review','resolve'}:raise ValueError('Unknown product catalog action')
        payload={k:v for k,v in body.items() if k not in {'root','action','expected_revision','operation_id'}}
        return await asyncio.to_thread(library.update,root,operation,payload,
            operation_id=body.get('operation_id') or uuid.uuid4().hex,
            expected_revision=body.get('expected_revision',''))

    @router.get('/api/asset-downloads')
    async def download_list(root:str):return await asyncio.to_thread(downloads.list,root)

    @router.post('/api/asset-downloads')
    async def prepare(request:Request):
        body=await request.json()
        if set(body)-{'root','asset_id'}:raise ValueError('Unknown download option')
        return await asyncio.to_thread(downloads.prepare,body['root'],body['asset_id'])

    # Register the literal file prefix before the job route.
    @router.get('/api/asset-downloads/file/{handle}')
    async def prepared_file(handle:str,root:str):
        # Acquire contains local journal/path checks only. Keep it in this task
        # so cancellation cannot lose a lease created by a detached worker.
        lease=downloads.acquire_handle(root,handle)
        try:
            return PreparedFileResponse(lease['path'],media_type='application/octet-stream',filename=Path(lease['name']).name,
                downloads=downloads,root=root,job_id=lease['job_id'],
                headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff',
                         'Content-Security-Policy':"default-src 'none'; sandbox"})
        except BaseException:
            downloads.release_handle(root,lease['job_id'])
            raise

    @router.get('/api/asset-downloads/{job_id}')
    async def download_status(job_id:str,root:str):
        return await asyncio.to_thread(downloads.status,root,job_id)

    @router.delete('/api/asset-downloads/{job_id}')
    async def release(job_id:str,root:str):return await asyncio.to_thread(downloads.release,root,job_id)

    @router.post('/api/asset-downloads/{job_id}/retry')
    async def retry(job_id:str,request:Request):
        body=await request.json()
        return await asyncio.to_thread(downloads.retry,body['root'],job_id)

    return router
