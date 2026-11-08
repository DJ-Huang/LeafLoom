"""Authenticated local calendar routes; desktop delivery also requires the private bearer."""
import asyncio
import hmac
from fastapi import APIRouter, Request, HTTPException


def calendar_router(calendar, token):
    router = APIRouter(prefix='/api/calendar')

    @router.get('/sync')
    async def sync_status():return await asyncio.to_thread(calendar.sync_status)

    @router.post('/sync/resolve')
    async def sync_resolve(request: Request):return await asyncio.to_thread(calendar.resolve_sync,await request.json())

    @router.get('/settings')
    async def settings(): return await asyncio.to_thread(calendar.settings)

    @router.put('/settings')
    async def save_settings(request: Request): return await asyncio.to_thread(calendar.save_settings, await request.json())

    @router.get('/databases')
    async def databases(cursor: str='', limit: int=100):
        return await asyncio.to_thread(calendar.task_databases,cursor,limit)

    @router.get('/tasks')
    async def tasks(database: str, search: str='', cursor: str='', limit: int=100):
        return await asyncio.to_thread(calendar.task_query,database,search,cursor,limit)

    @router.get('/daily')
    async def daily(date: str): return await asyncio.to_thread(calendar.daily, date)

    @router.get('/query')
    async def query(start: str, end: str, cursor: str='', limit: int=100, overdue: bool=False, completed: bool=True):
        return await asyncio.to_thread(calendar.query,start,end,cursor=cursor,limit=limit,overdue=overdue,completed=completed)

    @router.get('/trash')
    async def trash(cursor: str='', limit: int=100): return await asyncio.to_thread(calendar.trash,cursor,limit)

    @router.post('/commands')
    async def command(request: Request): return await asyncio.to_thread(calendar.command, await request.json())

    @router.get('/reminders')
    async def reminders(cursor: str='', limit: int=50): return await asyncio.to_thread(calendar.inbox,cursor,limit)

    @router.post('/reminders/seen')
    async def seen(request: Request):
        body = await request.json(); body['state'] = 'seen'
        return await asyncio.to_thread(calendar.delivery,body)

    def desktop(request):
        if not hmac.compare_digest(request.headers.get('authorization',''), 'Bearer '+token):
            raise HTTPException(403, 'Desktop authentication required')

    @router.get('/reminders/state')
    def desktop_state(request: Request):
        desktop(request)
        with calendar.config.lock:
            return {'config':{'root':calendar.config.data.get('root'),'revision':calendar.notes.workspace_revision}}

    @router.post('/reminders/claim')
    async def claim(request: Request):
        desktop(request)
        await asyncio.to_thread(calendar.tick)
        return await asyncio.to_thread(calendar.delivery, await request.json(),claim=True)

    @router.post('/reminders/ack')
    async def ack(request: Request):
        desktop(request)
        return await asyncio.to_thread(calendar.delivery, await request.json())

    return router
