"""One ASGI application serving the local UI, file API and shared HTTP MCP."""
from __future__ import annotations
import asyncio, contextlib, hashlib, hmac, ipaddress, json, logging, mimetypes, os, secrets, subprocess, threading, time
from pathlib import Path
from fastapi import FastAPI, Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.middleware.gzip import GZipMiddleware
from vault_rag.local_state import LocalConfig,ConflictError,atomic_write
from vault_rag.html_preview import HtmlPreviews
from vault_rag.html_projects import HtmlProjects
from vault_rag.browser_storage import BrowserStorageMigration, migration_script
from vault_rag.local_dns import LocalDns
from vault_rag.platform_support import choose_directory, open_directory, private_file_mode, is_windows
from vault_rag.http_cache import conditional_file
from vault_rag.skill_install import install_skill, skill_status
from vault_rag.ai_service import AiService
from vault_rag.ai_routes import ai_router, ai_mcp_server
from vault_rag.preferences import Preferences
from vault_rag.demo import create_demo
from vault_rag.i18n import error_code
from vault_rag.mcp_access import McpAccess, TUNNEL_AUTH_HEADER
from vault_rag.mcp_tools import build_workspace_mcp
from vault_rag.note_operations import NoteOperations
from vault_rag.feishu import Feishu

def json_response(value,status=200):
    if isinstance(value,dict) and isinstance(value.get('error'),str):
        value={**value,'error_code':value.get('error_code',error_code(value['error']))}
    return Response(json.dumps(value,ensure_ascii=False,default=str,allow_nan=False,separators=(',',':')).encode('utf-8'),status_code=status,media_type='application/json')

class StaticCompression:
    """Compress app bundles without buffering SSE or changing media Range bodies."""
    def __init__(self,app):
        self.app=app;self.compressed=GZipMiddleware(app,minimum_size=1024,compresslevel=6)
    async def __call__(self,scope,receive,send):
        ranged=any(key==b'range' for key,_ in scope.get('headers',[]))
        app=self.compressed if scope['type']=='http' and not ranged and scope.get('path','').startswith('/assets/') else self.app
        await app(scope,receive,send)

def create_app(config=None,runtime=None,*,start_background=True,static_dir=None,dev_server=None,dev_ui_loopback=False):
    from vault_rag.dev_frontend import DevFrontend
    dev = DevFrontend(dev_server) if dev_server else None
    if dev_ui_loopback and dev is None:
        raise ValueError('Loopback UI is only available with an explicit development frontend')
    config=config or LocalConfig()
    if runtime is None:
        from vault_rag.knowledge import Runtime
        runtime=Runtime(config)
    port=config.data.get('port',18080)
    previews=HtmlPreviews(config)
    websites=HtmlProjects(config,port)
    from vault_rag.attachment_migrations import AttachmentMigrations
    migrations=AttachmentMigrations(runtime,websites)
    from vault_rag.attachment_index_jobs import AttachmentIndexJobs
    index_jobs=AttachmentIndexJobs(runtime)
    if dev_ui_loopback:
        # Explicit browser-development workaround, never inferred from the OS or
        # environment. Keep project hosts separate and Vite on 127.0.0.1 so its
        # WebSocket does not receive the management UI's host-only cookie.
        websites.ui_host='localhost'
        websites.ui_origin=f'http://localhost:{port}'
    local_dns=LocalDns(websites.install_id,port)
    storage_migration=BrowserStorageMigration(websites.ui_origin,port,config.directory)
    preferences=Preferences(config.directory)
    secret_file=config.directory/'auth-token'
    if not secret_file.exists():atomic_write(secret_file,secrets.token_hex(32).encode());private_file_mode(secret_file)
    token=secret_file.read_text(encoding='utf-8').strip();csrf=hmac.new(token.encode(),b'browser-write-v1',hashlib.sha256).hexdigest()
    ai=AiService(config,runtime)
    ai_mcp=ai_mcp_server(ai)
    ai_app=ai_mcp.streamable_http_app()
    mcp_access=McpAccess(config)
    notes=NoteOperations(config,runtime)
    feishu=Feishu(config)
    mcp=build_workspace_mcp(config,runtime,notes,mcp_access,token,feishu)
    mcp_app=mcp.streamable_http_app()
    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run(),ai_mcp.session_manager.run():
            ai.loop=asyncio.get_running_loop()
            if start_background:runtime.start()
            try:yield
            finally:
                await ai.close()
                await asyncio.to_thread(migrations.stop)
                await asyncio.to_thread(index_jobs.stop)
                runtime.stop()
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None)
    app.add_middleware(StaticCompression)
    app.state.runtime=runtime;app.state.csrf=csrf
    app.state.mcp_access=mcp_access;app.state.note_operations=notes
    app.state.ai=ai
    app.state.feishu=feishu
    app.state.websites=websites
    app.state.attachment_migrations=migrations
    app.state.attachment_index_jobs=index_jobs
    app.state.local_dns=local_dns
    app.include_router(ai_router(ai))
    @app.middleware('http')
    async def local_security(request,call_next):
        host=request.headers.get('host','')
        if websites.is_project_host(host):
            return await asyncio.to_thread(websites.response,request)
        allowed={f'127.0.0.1:{port}',f'localhost:{port}',f'{websites.ui_host}:{port}'}
        if host not in allowed:return json_response({'error':'仅允许本机访问'},403)
        path=request.url.path
        if path=='/ai-mcp':
            try:ai.authorized(request.headers.get('authorization',''))
            except (ValueError,KeyError):return json_response({'error':'知识助手连接未授权或会话已停止'},401)
        preview_read=path.startswith('/html-preview/') and request.method in ('GET','HEAD')
        origin=request.headers.get('origin')
        if origin and origin not in {f'http://{h}' for h in allowed} and not (preview_read and origin=='null'):return json_response({'error':'来源不允许'},403)
        is_mcp=path.rstrip('/')=='/mcp'
        is_api=path.startswith('/api/') or is_mcp
        # Only the transport peer is authoritative; never trust forwarded IPs.
        try:local_mcp=is_mcp and request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:local_mcp=False
        bearer=hmac.compare_digest(request.headers.get('authorization','').encode('utf-8'),('Bearer '+token).encode('utf-8'))
        session=hmac.compare_digest(request.cookies.get('vault_session','').encode('utf-8'),token.encode('utf-8'))
        if is_mcp:
            try:
                who=mcp_access.principal(request.headers.get('authorization',''),token,loopback=local_mcp,
                                         tunnel_header=request.headers.get(TUNNEL_AUTH_HEADER,''))
                logging.getLogger(__name__).debug('MCP connection=%s runtime_proof=%s bearer=%s', who,
                    bool(request.headers.get(TUNNEL_AUTH_HEADER,'')),bool(request.headers.get('authorization','')))
            except PermissionError:return json_response({'error':'MCP credential is missing, invalid or revoked','error_code':'permission_denied'},401)
        elif is_api and not (bearer or session):return json_response({'error':'请从本机网页入口打开，或配置 MCP 本机令牌'},401)
        if path.startswith('/api/') and request.method not in ('GET','HEAD') and not bearer:
            if not hmac.compare_digest(request.headers.get('x-vault-csrf',''),csrf):return json_response({'error':'写入请求校验失败'},403)
        if path in ('/api/search-files','/api/graph','/api/related','/api/query','/api/base','/api/templates') and runtime.catalog.root!=config.data.get('root'):
            return json_response({'error':'目录信息正在更新，请稍后重试'},503)
        foreground=path.startswith('/api/') and path not in ('/api/events','/api/status','/api/activity')
        if foreground:runtime.foreground_begin()
        try:
            if dev and request.url.hostname==websites.ui_host and request.method in ('GET','HEAD') and dev.asset(path):
                response=await dev.response(path,request.url.query)
            else:response=await call_next(request)
        except ConflictError as e:return json_response({'error':str(e),'error_code':'write_conflict','conflict':True},409)
        except FileNotFoundError as e:return json_response({'error':str(e),'error_code':'not_found'},400)
        except UnicodeDecodeError as e:return json_response({'error':str(e),'error_code':'invalid_text_encoding'},400)
        except ValueError as e:return json_response({'error':str(e),'error_code':'invalid_request'},400)
        finally:
            if foreground:runtime.foreground_end()
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        if path.startswith('/api/') and path!='/api/media':response.headers.setdefault('Cache-Control','no-store')
        response.headers.setdefault('Content-Security-Policy',"default-src 'self'; script-src 'self'; worker-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' data:; connect-src 'self'; frame-src 'self' blob: http: https:; object-src 'none'; base-uri 'self'; frame-ancestors 'self'")
        if dev and request.url.hostname==websites.ui_host:
            response.headers['Content-Security-Policy']=response.headers['Content-Security-Policy'].replace("script-src 'self'", "script-src 'self' 'unsafe-inline'").replace("connect-src 'self'", "connect-src 'self' " + dev.websocket)
        return response
    @app.get('/healthz')
    async def health():return {'ok':True,'service':'vault-rag'}
    def session_data():
        return {'config':config.data,'csrf':csrf,'suggested_root':'','demo':getattr(app.state,'demo',False),
                'service_instance_id':runtime.events.instance,'catalog_version':runtime.catalog.version,'ui_url':websites.ui_origin+'/'}
    @app.get('/api/session')
    async def session():return json_response(session_data())
    @app.get('/api/local-resolver')
    async def resolver_status():return json_response(local_dns.status())
    @app.post('/api/local-resolver')
    async def resolver_configure(request:Request):
        body=await request.json()
        if not isinstance(body,dict) or not isinstance(body.get('enabled'),bool):raise ValueError('Invalid resolver request')
        if body['enabled'] and local_dns.socket is None:raise ValueError('本机解析服务尚未运行，请重新启动本地服务后重试')
        return json_response(await asyncio.to_thread(local_dns.configure,body['enabled']))
    @app.get('/api/preferences')
    async def read_preferences():
        return json_response(await asyncio.to_thread(preferences.for_root,config.data.get('root')))
    @app.put('/api/preferences')
    async def save_preferences(request:Request):
        await asyncio.to_thread(preferences.save,await request.json(),config.data.get('root'))
        return json_response(preferences.for_root(config.data.get('root')))
    @app.post('/api/demo')
    async def demo(request:Request):
        body=await request.json()
        if not isinstance(body,dict):raise ValueError('Invalid demo request')
        return json_response(await asyncio.to_thread(create_demo,config.directory,body.get('locale','en')))
    @app.get('/api/events')
    async def events(request:Request):
        async def stream():
            async with runtime.events.listen() as (queue,after):
                initial={'type':'reset','sequence':after,**session_data()}
                yield 'data: '+json.dumps(initial,ensure_ascii=False)+'\n\n'
                while not runtime.stop_event.is_set():
                    try:message=await asyncio.wait_for(queue.get(),timeout=15)
                    except asyncio.TimeoutError:
                        yield ': keepalive\n\n';continue
                    if message is None:break
                    if message['sequence']<=after:continue
                    after=message['sequence']
                    yield 'id: '+str(after)+'\ndata: '+json.dumps(message,ensure_ascii=False,default=str)+'\n\n'
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
    @app.get('/api/bootstrap')
    async def bootstrap():return json_response({'config':config.data,'status':runtime.status(),'csrf':csrf,'suggested_root':''})
    @app.get('/api/status')
    async def status():return json_response(runtime.status())
    @app.get('/api/mcp-access')
    async def mcp_access_status():return json_response(mcp_access.status())
    @app.post('/api/mcp-access')
    async def mcp_access_settings(request:Request):
        body=await request.json()
        if not isinstance(body,dict):raise ValueError('Invalid MCP access settings')
        return json_response(await asyncio.to_thread(mcp_access.configure,body.get('kind'),
            enabled=body.get('enabled'),write=body.get('write'),rotate=body.get('rotate',False),
            resource=body.get('resource','workspace'),high_risk=body.get('high_risk')))
    @app.get('/api/feishu')
    async def feishu_settings():return json_response(feishu.status())
    @app.post('/api/feishu')
    async def save_feishu_settings(request:Request):
        return json_response(await asyncio.to_thread(feishu.configure,await request.json()))
    @app.post('/api/feishu/verify')
    async def verify_feishu():return json_response(await asyncio.to_thread(feishu.verify))
    @app.post('/api/activity')
    async def activity():runtime.activity();return {'ok':True}

    def metadata_pending():
        if runtime.catalog.metadata_ready:return None
        if runtime.metadata.get('state')=='failed':
            error=runtime.metadata['error'];runtime.metadata['state']='idle'
            return json_response({'error':error},503)
        if runtime.ensure_metadata():return None
        return json_response({'error':'正在准备目录元数据，阅读与编辑不受影响','pending':True,'retry_after_ms':600},503)
    @app.post('/api/config')
    async def configure(request:Request):
        body=await request.json()
        if 'root' in body and body['root']!=config.data.get('root'):
            for key in list(ai.tasks):await ai.stop(key)
        value=await asyncio.to_thread(config.save,body);runtime.configuration_changed();return json_response(value)
    @app.post('/api/choose-directory')
    async def choose_current_directory():
        # Triggered only by an explicit click in the local webpage, not at login.
        return json_response(await asyncio.to_thread(choose_directory))
    @app.get('/api/skills/wiki-search')
    async def installed_search_skill():
        try:return json_response(await asyncio.to_thread(skill_status))
        except OSError as e:return json_response({'error':f'无法读取技能安装状态：{e}'},400)
    @app.post('/api/skills/wiki-search/install')
    async def install_search_skill():
        try:return json_response(await asyncio.to_thread(install_skill))
        except OSError as e:return json_response({'error':f'无法安装 wiki-search：{e}'},400)
    @app.get('/api/attachments/migrations')
    async def list_attachment_migrations():
        return await asyncio.to_thread(migrations.list)
    @app.post('/api/attachments/migrations')
    async def plan_attachment_migration(request:Request):
        body=await request.json()
        return await asyncio.to_thread(migrations.create,body['root'],body.get('destination','_attachments'))
    @app.get('/api/attachments/migrations/{key}')
    async def get_attachment_migration(key:str):
        return await asyncio.to_thread(migrations.get,key)
    @app.post('/api/attachments/migrations/{key}/{action}')
    async def act_attachment_migration(key:str,action:str,request:Request):
        body=await request.json()
        return await asyncio.to_thread(migrations.action,key,action,body['root'],body.get('confirm',False))
    @app.get('/api/attachments/status')
    async def attachment_status(root:str=''):
        return await asyncio.to_thread(index_jobs.status,root)
    @app.post('/api/attachments/initialize')
    @app.post('/api/attachments/rebuild')
    @app.post('/api/attachments/refresh')
    async def initialize_attachments(request:Request):
        body=await request.json()
        return await asyncio.to_thread(index_jobs.start,body['root'])
    @app.post('/api/attachments/index-cancel')
    async def cancel_attachment_index(request:Request):
        body=await request.json()
        return await asyncio.to_thread(index_jobs.cancel_job,body['root'])
    @app.get('/api/attachments')
    async def attachments(query:str='',after:str='',limit:int=100,root:str=''):
        status=await asyncio.to_thread(index_jobs.status,root)
        if not status['usable']:
            return json_response({'error':'Initialize the attachment index first','initialization_required':True},409)
        return await asyncio.to_thread(runtime.files.attachments.listing,query,after,limit)
    @app.get('/api/tree')
    async def tree(path:str=''):return await asyncio.to_thread(runtime.catalog.tree,path)
    @app.get('/api/file')
    async def read_file(request:Request,path:str):
        started=time.perf_counter()
        value=await asyncio.to_thread(runtime.files.read,path)
        etag='"'+hashlib.sha256((str(value['root'])+str(config.data.get('revision'))+str(value['mtime'])+value['etag']).encode()).hexdigest()+'"'
        if any(tag.strip().removeprefix('W/') in ('*',etag) for tag in request.headers.get('if-none-match','').split(',')):
            return Response(status_code=304,headers={'ETag':etag,'Cache-Control':'private, no-cache'})
        response=json_response(value);response.headers['ETag']=etag;response.headers['Cache-Control']='private, no-cache'
        response.headers['Server-Timing']='file;dur='+str(round((time.perf_counter()-started)*1000,2))
        return response
    @app.post('/api/html-preview')
    async def html_preview(request:Request):
        body=await request.json()
        if not isinstance(body,dict) or any(not isinstance(body.get(key),str) for key in ('path','root','text')):
            raise ValueError('网页预览需要文件路径、关联根目录和 HTML 内容')
        return json_response(await asyncio.to_thread(previews.create,body['path'],body['root'],body['text']))
    @app.get('/api/html-projects')
    async def html_projects(root:str,path:str=''):
        return json_response(await asyncio.to_thread(websites.list,root,path))
    @app.post('/api/html-projects')
    async def register_html_project(request:Request):
        body=await request.json()
        if not isinstance(body,dict) or any(not isinstance(body.get(key),str) for key in ('root','directory','entry')):raise ValueError('项目需要关联目录、项目文件夹和入口路径')
        return json_response(await asyncio.to_thread(websites.register,body['root'],body['directory'],body['entry'],body.get('spa',False),body.get('id')))
    @app.post('/api/html-sessions')
    async def create_html_session(request:Request):
        body=await request.json()
        if not isinstance(body,dict) or not isinstance(body.get('root'),str) or not isinstance(body.get('path',''),str):raise ValueError('网页会话参数无效')
        return json_response(await asyncio.to_thread(websites.create,body['root'],body.get('path',''),body.get('project_id'),body.get('draft'),body.get('url')))
    @app.delete('/api/html-sessions/{sid}')
    async def release_html_session(sid:str):
        websites.release(sid)
        return {'released':True}
    @app.api_route('/html-preview/{key}/files/{path:path}',methods=['GET','HEAD'])
    async def html_resource(request:Request,key:str,path:str,download:bool=False):
        return await asyncio.to_thread(previews.response,key,path,str(request.base_url).rstrip('/'),download,request)
    @app.put('/api/file')
    async def save_file(request:Request):
        body=await request.json();return json_response(await asyncio.to_thread(runtime.files.save,body['path'],body['text'],body['etag'],expected_root=body.get('root')))
    @app.patch('/api/properties')
    async def properties(request:Request):
        body=await request.json();return json_response(await asyncio.to_thread(runtime.files.properties,body['path'],body['updates'],body['etag'],expected_root=body.get('root')))
    @app.post('/api/create')
    async def create(request:Request):
        body=await request.json();return await asyncio.to_thread(runtime.files.create,body['path'],directory=bool(body.get('directory')),text=body.get('text',''))
    @app.post('/api/move')
    async def move(request:Request):
        body=await request.json();return await asyncio.to_thread(runtime.files.move,body['source'],body['destination'])
    @app.post('/api/delete')
    async def delete(request:Request):return await asyncio.to_thread(runtime.files.delete,(await request.json())['path'])
    @app.get('/api/records')
    async def records(kind:str='history',path:str|None=None):return runtime.files.records(kind,path)
    @app.post('/api/trash/clear')
    async def clear_trash(request:Request):
        body=await request.json()
        if not isinstance(body,dict) or body.get('confirm') is not True or not isinstance(body.get('root'),str):
            raise ValueError('清空回收区需要确认并指定关联目录')
        try:return await asyncio.to_thread(runtime.files.clear_trash,expected_root=body['root'])
        except OSError as e:return json_response({'error':f'清空未完成，部分内容可能已删除，请重新打开回收区：{e}'},400)
    @app.post('/api/restore')
    async def restore(request:Request):
        body=await request.json();return await asyncio.to_thread(runtime.files.restore,body['kind'],body['id'])
    @app.post('/api/upload')
    async def upload(request:Request,folder:str='',name:str='',root:str|None=None,create_folder:bool=False,central:bool=False):
        # Stream to a staging file, then atomically publish without overwriting.
        import uuid
        if '/' in name or '\\' in name or not name:raise ValueError('文件名无效')
        if (create_folder or central) and root is None:raise ValueError('创建附件目录需要指定关联目录')
        with config.lock:
            runtime.files.ensure_mutable()
            if central:folder=config.data.get('attachment_folder','_attachments')
            rel='/'.join(x for x in (folder,name) if x)
            expected_root=str(config.root);revision=config.data.get('revision')
            if root is not None and root!=expected_root:raise ConflictError('关联目录已切换，附件未写入')
            dest=config.path_for(rel,writable=True)
            if dest.exists():raise ConflictError('同名文件已存在')
            if create_folder or central:dest.parent.mkdir(parents=True,exist_ok=True)
            # Revalidate newly created directories before opening a staging file.
            dest=config.path_for(rel,writable=True)
            temp=dest.with_name('.upload-'+uuid.uuid4().hex)
            stream=temp.open('xb')
        try:
            with stream as f:
                async for part in request.stream():f.write(part)
                f.flush();os.fsync(f.fileno())
            with config.lock,runtime.files.lock:
                runtime.files.ensure_mutable()
                if str(config.root)!=expected_root or config.data.get('revision')!=revision:
                    raise ConflictError('关联目录已切换，附件未写入')
                if config.path_for(rel,writable=True)!=dest:raise ConflictError('附件目录已变化，未写入')
                if dest.exists():raise ConflictError('同名文件已存在')
                os.link(temp,dest);temp.unlink()
                rel=dest.relative_to(config.root).as_posix();runtime.files_changed(rel)
        finally:temp.unlink(missing_ok=True)
        return {'path':rel}
    @app.get('/api/media')
    async def media(request:Request,path:str,download:bool=False):
        def response():
            with config.lock:
                p=config.path_for(path)
                if not p.is_file():raise FileNotFoundError(path)
                headers={'Content-Security-Policy':"sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:;"} if p.suffix.lower() in ('.html','.htm','.svg') else None
                return conditional_file(p,request,headers=headers,identity=str(config.root)+str(config.data.get('revision')),filename=p.name if download else None,content_disposition_type='attachment' if download else 'inline')
        return await asyncio.to_thread(response)
    @app.get('/api/search-files')
    async def search_files(query:str):
        pending=metadata_pending()
        return pending if pending is not None else await asyncio.to_thread(runtime.catalog.search,query)
    @app.get('/api/resolve')
    async def resolve(target:str,source:str=''):return {'candidates':await asyncio.to_thread(runtime.catalog.resolve,target,source)}
    @app.get('/api/graph')
    async def graph(path:str|None=None):
        pending=metadata_pending()
        return pending if pending is not None else await asyncio.to_thread(runtime.catalog.graph,path)
    @app.get('/api/related')
    async def related(path:str):
        pending=metadata_pending()
        if pending is not None:return pending
        entry=runtime.catalog.entries.get(path,{})
        links=runtime.catalog.links
        return {'incoming':sorted(set(x['source'] for x in links if x['target']==path)),'outgoing':sorted(set(x['target'] for x in links if x['source']==path)),'metadata':entry.get('metadata',{})}
    @app.post('/api/query')
    async def query(request:Request):
        pending=metadata_pending()
        return pending if pending is not None else json_response(await asyncio.to_thread(runtime.catalog.query,(await request.json())['query']))
    @app.get('/api/base')
    async def base(path:str,view:int|None=None):
        pending=metadata_pending()
        return pending if pending is not None else json_response(await asyncio.to_thread(runtime.catalog.base,path,view))
    @app.get('/api/templates')
    async def templates():
        folder=config.data['templates']
        if not config.path_for(folder).is_dir():return []
        return [{'path':row['path'],'title':runtime.catalog.entries.get(row['path'],{}).get('title') or Path(row['name']).stem} for row in await asyncio.to_thread(runtime.catalog.tree,folder) if not row['directory'] and row['path'].endswith('.md')]
    @app.post('/api/template')
    async def template(request:Request):
        body=await request.json()
        return json_response(await asyncio.to_thread(notes.create,body['path'],notes.workspace_revision,template=body['template']))
    @app.post('/api/daily')
    async def daily():
        return json_response(await asyncio.to_thread(notes.daily,notes.workspace_revision))
    @app.post('/api/knowledge-search')
    async def knowledge_search(request:Request):
        body=await request.json();return json_response(await asyncio.to_thread(runtime.knowledge.search,body.get('query',''),top_k=body.get('top_k',3),type_=body.get('note_type'),mode=body.get('mode','hybrid'),domain=body.get('domain')))
    @app.post('/api/reindex')
    async def reindex():
        runtime.request_index(force=True);return {'ok':True,'state':'已排队'}
    @app.post('/api/model-prepare')
    async def prepare():
        if not runtime.model.begin_prepare():return {'state':'下载中'}
        runtime.publish('status',status=runtime.status())
        def download():
            try:runtime.model.prepare(reserved=True);runtime.request_index(force=True)
            except Exception:logging.exception('Model preparation failed')
            finally:runtime.publish('status',status=runtime.status())
        threading.Thread(target=download,daemon=True,name='model-download').start();return {'state':'模型准备已开始'}
    @app.post('/api/model-directory/open')
    async def open_model_directory():
        # The client cannot select an arbitrary local path through this action.
        directory=runtime.model.available.path
        try:await asyncio.to_thread(open_directory,directory)
        except (OSError,subprocess.SubprocessError) as error:return json_response({'error':str(error)},400)
        return {'ok':True}
    # The SDK owns /mcp; share its single session manager in the root lifespan.
    app.router.routes.extend(mcp_app.routes)
    app.router.routes.extend(ai_app.routes)
    static=Path(static_dir) if static_dir else Path(__file__).parent/'static'
    @app.get('/favicon.svg')
    async def favicon():return FileResponse(static/'favicon.svg',media_type='image/svg+xml')
    @app.get('/assets/{path:path}')
    async def asset(path:str):
        p=(static/'assets'/path).resolve()
        if not p.is_relative_to(static/'assets') or not p.is_file():return Response(status_code=404)
        # Windows registry MIME associations can label .js as text/plain.
        media_type={'.js':'text/javascript','.mjs':'text/javascript','.css':'text/css'}.get(p.suffix.lower())
        return FileResponse(p,media_type=media_type,headers={'Cache-Control':'public, max-age=31536000, immutable'})
    @app.get('/__leafloom__/storage.js')
    async def storage_migration_script():return migration_script()
    @app.get('/__leafloom__/migrate')
    async def storage_migration_receiver(request:Request,ticket:str=''):
        if request.url.hostname!=websites.ui_host:return Response(status_code=404)
        return storage_migration.page(collector=True,ticket=ticket)
    @app.api_route('/__leafloom__/transfer',methods=['GET','POST','DELETE'])
    async def storage_transfer(request:Request,nonce:str='',ticket:str=''):
        if request.method=='POST':
            if request.url.hostname==websites.ui_host:raise ValueError('迁移来源无效')
            raw=await request.body()
            if len(raw)>32*1024*1024:raise ValueError('迁移数据过大；原草稿仍保留')
            return json_response(storage_migration.submit(nonce,json.loads(raw),request.headers.get('origin','')))
        if request.url.hostname!=websites.ui_host:return Response(status_code=403)
        return json_response(storage_migration.read(ticket,acknowledge=request.method=='DELETE'))
    @app.get('/__leafloom__/migration-state')
    async def migration_state(receipt:str=''):
        return json_response({'completed':storage_migration.completed(receipt)})
    @app.post('/__leafloom__/local-resolver')
    async def legacy_resolver(request:Request):
        # Safari cannot reach the new UI until resolution is installed. This
        # one-use capability is issued by the old entrance; no ambient privilege.
        storage_migration.authorize_resolver((await request.json()).get('nonce',''),request.headers.get('origin',''))
        if local_dns.socket is None:raise ValueError('本机解析服务尚未运行，请重新启动本地服务后重试')
        return json_response(await asyncio.to_thread(local_dns.configure,True))
    @app.get('/')
    async def index(request:Request):
        if not dev and not (static/'index.html').is_file():return HTMLResponse('网页尚未构建，请运行前端构建',status_code=503)
        if request.url.hostname!=websites.ui_host:
            return storage_migration.page()
        response=await dev.response('/') if dev else HTMLResponse((static/'index.html').read_text(encoding='utf-8'),headers={'Cache-Control':'no-store'})
        response.set_cookie('vault_session',token,httponly=True,samesite='strict',max_age=365*86400);return response
    return app

def create_server(app, **options):
    import uvicorn
    class LocalServer(uvicorn.Server):
        async def startup(self, sockets=None):
            import sys
            if sys.platform=='darwin':app.state.local_dns.start()
            try:await super().startup(sockets)
            except BaseException:
                app.state.local_dns.stop();raise
        async def shutdown(self, sockets=None):
            # CLI HTTP MCP clients keep SSE connections open. Close workers BEFORE
            # uvicorn waits for those connections, not only in ASGI lifespan cleanup.
            runtime=app.state.runtime
            if hasattr(runtime,'request_stop'):runtime.request_stop()
            await app.state.ai.close()
            try:await super().shutdown(sockets)
            finally:app.state.local_dns.stop()
    options['proxy_headers']=False
    return LocalServer(uvicorn.Config(app,host='127.0.0.1',workers=1,access_log=False,
                                    timeout_graceful_shutdown=20,**options))


def serve(*, instance=None):
    import uvicorn
    config=LocalConfig();logging.basicConfig(level=logging.INFO)
    if is_windows():
        from vault_rag.windows_native import Instance
        import socket
        with (contextlib.nullcontext(instance) if instance is not None else Instance(config.directory, 'service')) as instance:
            if not instance.primary:return
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                try:probe.bind(('127.0.0.1', config.data.get('port',18080)))
                except OSError as e:raise RuntimeError('配置端口已被其他程序占用') from e
            # Python 3.12's Proactor transport can leave reset loopback sockets
            # awaiting closure indefinitely. HTTP MCP needs TCP, not async pipes.
            app=create_app(config)
            server=create_server(app,port=config.data.get('port',18080),loop='asyncio:SelectorEventLoop')
            finished=threading.Event()
            def watch():
                while not finished.is_set():
                    if instance.wait_for_stop(200):
                        app.state.runtime.request_stop()
                        server.should_exit=True;return
            watcher=threading.Thread(target=watch,daemon=True);watcher.start()
            try:server.run()
            finally:finished.set();watcher.join()
    else:
        create_server(create_app(config),port=config.data.get('port',18080)).run()
