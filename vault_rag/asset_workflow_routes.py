"""Management-session-only asset settings; MCP cannot choose output directories."""
import asyncio
from fastapi import APIRouter, Request


def asset_workflow_router(files):
    router = APIRouter()

    def validate(root):
        files.workspace.files(root)

    @router.get('/api/asset-workflows/settings')
    async def settings(root:str):
        def read():
            validate(root)
            return {'delivery':files.asset_deliveries.settings(), 'search':files.asset_search.settings(),
                    'index':files.asset_search.status()}
        return await asyncio.to_thread(read)

    @router.put('/api/asset-workflows/delivery-settings')
    async def delivery_settings(request:Request):
        body = await request.json()
        if set(body)!={'root','directory','revision'}:
            raise ValueError('Unsupported delivery setting')
        def save():
            validate(body['root'])
            return files.asset_deliveries.configure(body['directory'],body['revision'],root=body['root'])
        return await asyncio.to_thread(save)

    @router.put('/api/asset-workflows/search-settings')
    async def search_settings(request:Request):
        body = await request.json()
        if set(body)!={'root','enabled','revision'}:
            raise ValueError('Unsupported asset search setting')
        def save():
            validate(body['root'])
            return files.asset_search.configure(body['enabled'],body['revision'],root=body['root'])
        return await asyncio.to_thread(save)

    @router.post('/api/asset-workflows/rebuild')
    async def rebuild(request:Request):
        body = await request.json()
        if set(body)!={'root','revision'}:
            raise ValueError('Unsupported asset index rebuild request')
        def run():
            validate(body['root'])
            return files.asset_search.rebuild(body['root'],body['revision'])
        return await asyncio.to_thread(run)

    return router
