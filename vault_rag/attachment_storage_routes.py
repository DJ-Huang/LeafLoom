"""Authenticated local UI routes for configured attachment sources.

Only this management interface accepts storage configuration. MCP file tools
receive asset identities and byte ranges, never server credentials or URLs.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import ipaddress
import json
import re
import threading
import uuid
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Request
from starlette.responses import Response, StreamingResponse

from vault_rag.local_state import ConflictError
from vault_rag.remote_webdav import RemoteStorageError
from vault_rag.http_cache import conditional_file


def storage_id(value):
    try:
        return uuid.UUID(str(value)).hex
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Invalid attachment storage ID') from None


def public_settings(remote, root=None):
    result = remote.status(root)
    profiles = []
    for source in result['sources']:
        profiles.append({
            'storage_id':source['id'], 'name':source.get('name',''),
            'base_url':source['base_url'], 'remote_root':source.get('remote_root',''),
            'upload_directory':source.get('upload_directory','Incoming'),
            'metadata_directory':source.get('metadata_directory','Incoming/LeafLoomCatalog/v1'),
            'username':source.get('username',''), 'enabled':source.get('enabled',True),
            'connection_hint':source.get('connection_hint','direct'),
            'password_saved':source.get('password_saved',False),
            'connection':source.get('connection',{'state':'unconfigured'}),
        })
    pending = sum(count for state,count in result.get('jobs',{}).items()
                  if state not in {'completed','cancelled','planned'})
    return dict(root=result['root'], revision=result['revision'], storages=profiles,
                default_storage_id=result['default_source'], cache_limit_bytes=result['cache_max_bytes'],
                outbox_limit_bytes=result['outbox_max_bytes'], cache=result['cache'],
                outbox={**result['outbox'],'pending':pending})


def save_settings(remote, body):
    if not isinstance(body,dict) or set(body)-{'root','revision','storages','default_storage_id','cache_limit_bytes','outbox_limit_bytes'}:
        raise ValueError('Unsupported attachment storage setting')
    root = body.get('root')
    if not isinstance(root,str) or not root:raise ValueError('Select a connected folder')
    profiles = body.get('storages')
    if not isinstance(profiles,list) or len(profiles)>32:raise ValueError('Invalid attachment sources')
    sources = []
    allowed = {'storage_id','name','base_url','remote_root','upload_directory','metadata_directory','username','connection_hint','enabled'}
    existing={source['id']:source for source in remote._settings(root)['sources']}
    for source in profiles:
        if not isinstance(source,dict) or set(source)-allowed:raise ValueError('Unsupported attachment source setting')
        key = storage_id(source.get('storage_id'))
        value = {key:value for key,value in source.items() if key!='storage_id'}
        if 'metadata_directory' not in value and key in existing:
            value['metadata_directory']=existing[key]['metadata_directory']
        value.update(id=key,type='webdav',secret_ref='attachment:'+key)
        try:
            address = urlsplit(value.get('base_url',''))
            value['allow_private_http'] = address.scheme=='http' and ipaddress.ip_address(address.hostname).is_private
        except (ValueError, TypeError):
            value['allow_private_http'] = False
        sources.append(value)
    default = body.get('default_storage_id','local')
    if default!='local':default=storage_id(default)
    remote.save(root,dict(sources=sources,default_source=default,
        cache_max_bytes=body.get('cache_limit_bytes',2*1024**3),
        outbox_max_bytes=body.get('outbox_limit_bytes',10*1024**3)),body.get('revision'))
    return public_settings(remote,root)


def replace_credentials(remote, body):
    """Validate the complete update before changing the in-memory credential map."""
    if not isinstance(body,dict) or set(body)-{'replace','entries','sync_sequence'} or not isinstance(body.get('entries'),dict):
        raise ValueError('Invalid attachment credentials')
    if type(body.get('replace',False)) is not bool or len(body['entries'])>1024:
        raise ValueError('Invalid attachment credentials')
    sequence=body.get('sync_sequence')
    if sequence is not None and (type(sequence)is not int or not 1<=sequence<=2**53-1 or body.get('replace')is not True):
        raise ValueError('Invalid attachment credential sequence')
    try:
        names={source['id']:source.get('username','') for source in remote._settings()['sources']}
    except (ValueError,FileNotFoundError):
        names={}
    with remote.lock:
        # A timed-out desktop POST can still reach this lock after a newer save
        # or clear. Never let that late snapshot restore a superseded password.
        if sequence is not None and sequence<=getattr(remote,'desktop_credential_sequence',0):
            return {'ok':True,'password_saved':bool(remote.credentials),'superseded':True}
        current={} if body.get('replace') else copy.copy(remote.credentials)
        for key,value in body['entries'].items():
            key=storage_id(key)
            if value is None:
                current.pop(key,None);continue
            if (not isinstance(value,dict) or set(value)-{'password','revision'} or
                    not isinstance(value.get('password'),str) or not value['password'] or
                    '\0' in value['password'] or
                    len(value['password'].encode('utf-8'))>4096 or
                    not isinstance(value.get('revision'),str) or
                    not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',value['revision'])):
                raise ValueError('Invalid attachment credentials')
            current[key]=(names.get(key,''),value['password'],value['revision'],'local')
        entries=[dict(source_id=key,username=value[0],password=value[1],revision=value[2],owner=value[3])
                 for key,value in current.items()]
        remote.replace_credentials(entries)
        if sequence is not None:remote.desktop_credential_sequence=sequence
    return {'ok':True,'password_saved':bool(current)}


def public_job(value):
    result=dict(value)
    result['job_id']='remote:'+result['id']
    if result.get('kind')=='upload':
        result['remote_saved']=result.get('state')=='completed'
        result['pending']=not result['remote_saved']
        if result.get('requested_path'):result['path']=result['requested_path']
    if result.get('kind')=='migration':
        result['summary']={'files':len(result.get('items',[])), 'bytes':result.get('total_bytes',0)}
        result['progress']={'done':result.get('completed',0),'total':len(result.get('items',[]))}
    return result


async def remote_media(remote, request, item, root, download=False, _retried=False):
    """Serve existing LeafLoom URLs without exposing a NAS URL to the browser."""
    if item.get('state')=='missing':raise RemoteStorageError('remote_asset_missing','missing')
    settings=remote._settings(root)
    name=item.get('name') or item['path'].rsplit('/',1)[-1]
    # A remote server controls both names and MIME metadata. All remote inline
    # responses receive a sandbox so mislabeled active content cannot inherit
    # the management interface's origin or run scripts.
    sandbox={'Content-Security-Policy':"sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:;",
             'X-Content-Type-Options':'nosniff'}
    mime=item.get('mime') or 'application/octet-stream'
    if not re.fullmatch(r'[\w.+-]+/[\w.+-]+',mime):mime='application/octet-stream'
    size=int(item['size'])
    if size<=min(settings['cache_max_bytes'],64*1024*1024) or item.get('state')=='pending':
        target=await asyncio.to_thread(remote.materialize,root,asset_id=item['asset_id'])
        return conditional_file(target,request,headers=sandbox,identity=root+item['asset_id'],
            filename=name,media_type=mime,
            content_disposition_type='attachment' if download else 'inline')
    identity=[root,item['asset_id'],item.get('etag'),item.get('mtime'),size]
    # Preserve existing validators until the first confirmed missing transition.
    # A recreated object can reuse size/time/ETag while containing new bytes.
    if item.get('content_generation',0):identity.append(item['content_generation'])
    version=json.dumps(identity,sort_keys=True)
    etag='"'+hashlib.sha256(version.encode()).hexdigest()+'"'
    headers={'ETag':etag,'Accept-Ranges':'bytes','Cache-Control':'private, no-cache',**sandbox}
    headers['Content-Disposition']=('attachment' if download else 'inline')+"; filename*=utf-8''"+quote(name,safe='')
    start,end,status=0,max(0,size-1),200
    selected=request.headers.get('range','')
    if selected and request.headers.get('if-range',etag)==etag:
        match=re.fullmatch(r'bytes=(\d*)-(\d*)',selected)
        try:
            if not match or not any(match.groups()) or not size:raise ValueError()
            first,last=match.groups()
            if first:
                start=int(first);end=min(size-1,int(last)) if last else size-1
            else:
                suffix=int(last)
                if suffix<=0:raise ValueError()
                start=max(0,size-suffix);end=size-1
            if start>=size or start>end:raise ValueError()
        except ValueError:
            return Response(status_code=416,headers={**headers,'Content-Range':'bytes */'+str(size)})
        status=206;headers['Content-Range']=f'bytes {start}-{end}/{size}'
    headers['Content-Length']=str(end-start+1 if size else 0)
    block=8*1024*1024
    first_end=min(end,start+block-1)
    first,current=await asyncio.to_thread(remote.read_range,root,asset_id=item['asset_id'],start=start,end=first_end)
    # A listing may omit ETag or lag behind the server. read_range revalidates
    # uncached bytes before returning them; build browser validators and Range
    # headers from that same version, including when returning a 304.
    if (any(current.get(key)!=item.get(key) for key in ('size','etag','mtime','mime')) or
            current.get('content_generation',0)!=item.get('content_generation',0)):
        if _retried:raise ConflictError('Attachment changed while opening')
        return await remote_media(remote,request,current,root,download,_retried=True)
    if len(first)!=(first_end-start+1 if size else 0) or current['size']!=size:
        raise ConflictError('Attachment changed while opening')
    if etag in [tag.strip() for tag in request.headers.get('if-none-match','').split(',')]:
        return Response(status_code=304,headers=headers)
    def stream():
        yield first
        position=first_end+1
        while position<=end:
            last=min(end,position+block-1)
            chunk,metadata=remote.read_range(root,asset_id=item['asset_id'],start=position,end=last)
            if (len(chunk)!=last-position+1 or metadata['size']!=size or
                    metadata.get('etag')!=current.get('etag') or metadata.get('mtime')!=current.get('mtime') or
                    metadata.get('content_generation',0)!=current.get('content_generation',0)):
                raise ConflictError('Attachment changed while reading')
            yield chunk;position=last+1
    return StreamingResponse(stream(),status_code=status,headers=headers,media_type=mime)


def attachment_storage_router(remote, runtime, workspace):
    router=APIRouter()
    workers={}

    @router.get('/api/attachments/storage')
    async def settings(root:str=''):
        return await asyncio.to_thread(public_settings,remote,root or None)

    @router.put('/api/attachments/storage')
    async def save(request:Request):
        return await asyncio.to_thread(save_settings,remote,await request.json())

    @router.post('/api/attachments/storage/credentials')
    async def credentials(request:Request):
        try:return await asyncio.to_thread(replace_credentials,remote,await request.json())
        except (ValueError,TypeError):raise ValueError('Invalid attachment credentials') from None

    @router.post('/api/attachments/storage/test')
    async def test(request:Request):
        body=await request.json()
        return await asyncio.to_thread(remote.test,body['root'],storage_id(body['storage_id']))

    @router.post('/api/attachments/storage/scan')
    async def scan(request:Request):
        body=await request.json()
        return await asyncio.to_thread(remote.start_scan,body['root'],storage_id(body['storage_id']))

    @router.post('/api/attachments/cache/clear')
    async def clear(request:Request):
        body=await request.json()
        await asyncio.to_thread(remote.clear_cache,body['root'])
        return await asyncio.to_thread(public_settings,remote,body['root'])

    @router.patch('/api/attachments/metadata')
    async def metadata(request:Request):
        body=await request.json()
        root=body['root'];path=body.get('path','');asset_id=body.get('asset_id','')
        if bool(path)==bool(asset_id):raise ValueError('Select exactly one attachment path or asset ID')
        if not body.get('metadata_revision'):raise ConflictError('Read the current attachment metadata before updating')
        patch={key:body[key] for key in ('tags','category','description') if key in body}
        value=await asyncio.to_thread(remote.update_metadata,root,path,patch,body['metadata_revision'],asset_id=asset_id)
        runtime.publish('files',[value['path']])
        return await asyncio.to_thread(workspace.details,root,value['path'])

    @router.get('/api/attachments/storage/jobs')
    async def jobs(root:str):
        return {'jobs':[public_job(job) for job in await asyncio.to_thread(remote.jobs,root,owner='local')]}

    @router.get('/api/attachments/storage/jobs/{key}')
    async def job(key:str,root:str):
        if key.startswith('remote:'):key=key[7:]
        return public_job(await asyncio.to_thread(remote.job,root,key))

    @router.post('/api/attachments/storage/migrations')
    async def migration(request:Request):
        body=await request.json()
        value=await asyncio.to_thread(remote.migration_plan,body['root'],storage_id(body['storage_id']),body.get('paths'))
        return public_job(value)

    @router.post('/api/attachments/storage/jobs/{key}/{action}')
    async def operation(request:Request,key:str,action:str):
        if key.startswith('remote:'):key=key[7:]
        body=await request.json();root=body['root']
        value=await asyncio.to_thread(remote.job,root,key)
        if action not in {'execute','resume','cancel'}:raise ValueError('Invalid attachment job action')
        if action!='cancel' and body.get('confirm') is not True:raise ValueError('Confirm the reviewed attachment operation')
        if value['kind']=='migration' and action!='cancel':
            remote._root(root)
            if value.get('blockers'):raise ConflictError('Resolve project dependency blockers before migration')
            if key in workers and workers[key].is_alive():return public_job(value)
            value=await asyncio.to_thread(remote.job,root,key,'resume')
            def run():
                try:remote.migrate(root,key)
                finally:runtime.publish('files',[])
            thread=threading.Thread(target=run,daemon=True,name='attachment-migration-'+key[:8])
            workers[key]=thread;thread.start()
            return public_job({**value,'state':'queued'})
        return public_job(await asyncio.to_thread(remote.job,root,key,'resume' if action=='execute' else action))

    return router
