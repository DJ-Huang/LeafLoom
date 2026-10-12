"""One ASGI application serving the local UI, file API and shared HTTP MCP."""
from __future__ import annotations
import asyncio, contextlib, hashlib, hmac, json, logging, mimetypes, os, secrets, subprocess, threading
from pathlib import Path
from fastapi import FastAPI, Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.middleware.gzip import GZipMiddleware
from mcp.server.fastmcp import FastMCP
from vault_rag.local_state import LocalConfig,ConflictError,atomic_write
from vault_rag.knowledge import Runtime
from vault_rag.html_preview import HtmlPreviews
from vault_rag.platform_support import choose_directory, private_file_mode, is_windows
from vault_rag.http_cache import conditional_file

def json_response(value,status=200):return JSONResponse(json.loads(json.dumps(value,ensure_ascii=False,default=str)),status_code=status)

class StaticCompression:
    """Compress app bundles without buffering SSE or changing media Range bodies."""
    def __init__(self,app):
        self.app=app;self.compressed=GZipMiddleware(app,minimum_size=1024,compresslevel=6)
    async def __call__(self,scope,receive,send):
        app=self.compressed if scope['type']=='http' and scope.get('path','').startswith('/assets/') else self.app
        await app(scope,receive,send)

def create_app(config=None,runtime=None,*,start_background=True,static_dir=None):
    config=config or LocalConfig();runtime=runtime or Runtime(config);port=config.data.get('port',18080)
    previews=HtmlPreviews(config)
    secret_file=config.directory/'auth-token'
    if not secret_file.exists():atomic_write(secret_file,secrets.token_hex(32).encode());private_file_mode(secret_file)
    token=secret_file.read_text(encoding='utf-8').strip();csrf=hmac.new(token.encode(),b'browser-write-v1',hashlib.sha256).hexdigest()
    mcp=FastMCP('vault-rag',host='127.0.0.1',port=port,stateless_http=True,json_response=True)
    def result(fn,*args,**kwargs):
        try:return json.dumps(fn(*args,**kwargs),ensure_ascii=False,default=str)
        except Exception as e:return json.dumps({'ok':False,'error':str(e)},ensure_ascii=False)
    @mcp.tool()
    def vault_search(query:str,top_k:int=3,note_type:str|None=None,domain:str|None=None,compact:bool=True,mode:str='hybrid')->str:
        """Search selected knowledge directories with Wiki, keywords and local BGE-M3.
        mode=hybrid|wiki|rag|keyword. Use domain=estimation for cost-estimation cards.
        Excludes rules; sources retain verification limits. Fetch full notes for formulas.
        """
        return result(runtime.knowledge.search,query,top_k=top_k,type_=note_type,domain=domain,compact=compact,mode=mode)
    @mcp.tool()
    def rule_search(query:str,top_k:int=3,domain:str|None=None,compact:bool=True)->str:
        """Search selected rule directories only. Use for missing relevant rules."""
        if domain=='pcg':return json.dumps({'ok':True,'no_relevant_hit':True,'results':[]})
        return result(runtime.knowledge.search,query,top_k=top_k,domain=domain,rules=True,compact=compact)
    @mcp.tool()
    def vault_get_chunk(chunk_id:str)->str:
        """Read a complete retrieved evidence chunk. Withdrawn sources are unavailable."""
        return result(runtime.knowledge.get_chunk,chunk_id)
    @mcp.tool()
    def vault_get_note(note_id:str)->str:
        """Read a full currently eligible note by ID or relative path, including formulas."""
        return result(runtime.knowledge.get_note,note_id)
    @mcp.tool()
    def vault_index_status()->str:
        """Report configured directory, indexed roots, write targets, model and sync state."""
        return result(runtime.status)
    mcp_app=mcp.streamable_http_app()
    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            if start_background:runtime.start()
            yield
            runtime.stop()
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None)
    app.add_middleware(StaticCompression)
    app.state.runtime=runtime;app.state.csrf=csrf
    @app.middleware('http')
    async def local_security(request,call_next):
        allowed={f'127.0.0.1:{port}',f'localhost:{port}'}
        if request.headers.get('host') not in allowed:return json_response({'error':'仅允许本机访问'},403)
        path=request.url.path
        preview_read=path.startswith('/html-preview/') and request.method in ('GET','HEAD')
        origin=request.headers.get('origin')
        if origin and origin not in {f'http://{h}' for h in allowed} and not (preview_read and origin=='null'):return json_response({'error':'来源不允许'},403)
        is_api=path.startswith('/api/') or path=='/mcp'
        bearer=hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+token)
        session=hmac.compare_digest(request.cookies.get('vault_session',''),token)
        if is_api and not (bearer or (session and path!='/mcp')):return json_response({'error':'请从本机网页入口打开，或配置 MCP 本机令牌'},401)
        if path.startswith('/api/') and request.method not in ('GET','HEAD') and not bearer:
            if not hmac.compare_digest(request.headers.get('x-vault-csrf',''),csrf):return json_response({'error':'写入请求校验失败'},403)
        if path in ('/api/search-files','/api/graph','/api/related','/api/query','/api/base','/api/templates') and runtime.catalog.root!=config.data.get('root'):
            return json_response({'error':'目录信息正在更新，请稍后重试'},503)
        try:response=await call_next(request)
        except ConflictError as e:return json_response({'error':str(e),'conflict':True},409)
        except (ValueError,FileNotFoundError,UnicodeDecodeError) as e:return json_response({'error':str(e)},400)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        if path.startswith('/api/') and path!='/api/media':response.headers.setdefault('Cache-Control','no-store')
        response.headers.setdefault('Content-Security-Policy',"default-src 'self'; script-src 'self'; worker-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' data:; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'self'")
        return response
    @app.get('/healthz')
    async def health():return {'ok':True,'service':'vault-rag'}
    def session_data():
        return {'config':config.data,'csrf':csrf,'suggested_root':str(Path.home()/'DJKnowledges'),
                'service_instance_id':runtime.events.instance,'catalog_version':runtime.catalog.version}
    @app.get('/api/session')
    async def session():return json_response(session_data())
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
    async def bootstrap():return json_response({'config':config.data,'status':runtime.status(),'csrf':csrf,'suggested_root':str(Path.home()/'DJKnowledges')})
    @app.get('/api/status')
    async def status():return json_response(runtime.status())
    @app.post('/api/config')
    async def configure(request:Request):
        body=await request.json();value=await asyncio.to_thread(config.save,body);runtime.configuration_changed();return json_response(value)
    @app.post('/api/choose-directory')
    async def choose_current_directory():
        # Triggered only by an explicit click in the local webpage, not at login.
        return json_response(await asyncio.to_thread(choose_directory))
    @app.get('/api/tree')
    async def tree(path:str=''):return await asyncio.to_thread(runtime.catalog.tree,path)
    @app.get('/api/file')
    async def read_file(request:Request,path:str):
        value=await asyncio.to_thread(runtime.files.read,path)
        etag='"'+hashlib.sha256((str(value['root'])+str(config.data.get('revision'))+str(value['mtime'])+value['etag']).encode()).hexdigest()+'"'
        if any(tag.strip().removeprefix('W/') in ('*',etag) for tag in request.headers.get('if-none-match','').split(',')):
            return Response(status_code=304,headers={'ETag':etag,'Cache-Control':'private, no-cache'})
        response=json_response(value);response.headers['ETag']=etag;response.headers['Cache-Control']='private, no-cache';return response
    @app.post('/api/html-preview')
    async def html_preview(request:Request):
        body=await request.json()
        if not isinstance(body,dict) or any(not isinstance(body.get(key),str) for key in ('path','root','text')):
            raise ValueError('网页预览需要文件路径、关联根目录和 HTML 内容')
        return json_response(await asyncio.to_thread(previews.create,body['path'],body['root'],body['text']))
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
    @app.post('/api/restore')
    async def restore(request:Request):
        body=await request.json();return await asyncio.to_thread(runtime.files.restore,body['kind'],body['id'])
    @app.post('/api/upload')
    async def upload(request:Request,folder:str='',name:str=''):
        # Stream to a staging file, then atomically publish without overwriting.
        import uuid
        dest=config.path_for('/'.join(x for x in (folder,name) if x),writable=True)
        if '/' in name or '\\' in name or not name:raise ValueError('文件名无效')
        if dest.exists():raise ConflictError('同名文件已存在')
        temp=dest.with_name('.upload-'+uuid.uuid4().hex)
        try:
            with temp.open('xb') as f:
                async for part in request.stream():f.write(part)
                f.flush();os.fsync(f.fileno())
            with runtime.files.lock:
                if dest.exists():raise ConflictError('同名文件已存在')
                os.link(temp,dest);temp.unlink()
        finally:temp.unlink(missing_ok=True)
        rel=dest.relative_to(config.root).as_posix();runtime.files_changed(rel);return {'path':rel}
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
    async def search_files(query:str):return await asyncio.to_thread(runtime.catalog.search,query)
    @app.get('/api/resolve')
    async def resolve(target:str,source:str=''):return {'candidates':await asyncio.to_thread(runtime.catalog.resolve,target,source)}
    @app.get('/api/graph')
    async def graph(path:str|None=None):return await asyncio.to_thread(runtime.catalog.graph,path)
    @app.get('/api/related')
    async def related(path:str):
        entry=runtime.catalog.entries.get(path,{})
        links=runtime.catalog.links
        return {'incoming':sorted(set(x['source'] for x in links if x['target']==path)),'outgoing':sorted(set(x['target'] for x in links if x['source']==path)),'metadata':entry.get('metadata',{})}
    @app.post('/api/query')
    async def query(request:Request):return json_response(await asyncio.to_thread(runtime.catalog.query,(await request.json())['query']))
    @app.get('/api/base')
    async def base(path:str,view:int|None=None):return json_response(await asyncio.to_thread(runtime.catalog.base,path,view))
    @app.get('/api/templates')
    async def templates():return [{'path':p,'title':e['title']} for p,e in runtime.catalog.entries.items() if p.startswith(config.data['templates']+'/') and p.endswith('.md')]
    @app.post('/api/template')
    async def template(request:Request):
        from vault_rag.catalog import render_template
        body=await request.json();rendered=render_template(runtime.files.read(body['template'])['text']);runtime.files.create(body['path'],text=rendered['text']);return {'path':body['path'],'cursor':rendered['cursor']}
    @app.post('/api/daily')
    async def daily():
        from vault_rag.catalog import render_template
        import datetime
        folder=config.data['daily_folder'];config.path_for(folder).mkdir(exist_ok=True)
        path=folder+'/'+datetime.date.today().isoformat()+'.md'
        created=not config.path_for(path).exists()
        if created:
            template_path=config.data['templates']+'/tpl-daily-note.md'
            text=runtime.files.read(template_path)['text'] if config.path_for(template_path).is_file() else '# {{date}}\n\n'
            runtime.files.create(path,text=render_template(text)['text'])
        return {'path':path,'created':created}
    @app.post('/api/knowledge-search')
    async def knowledge_search(request:Request):
        body=await request.json();return json_response(await asyncio.to_thread(runtime.knowledge.search,body.get('query',''),top_k=body.get('top_k',3),type_=body.get('note_type'),mode=body.get('mode','hybrid'),domain=body.get('domain')))
    @app.post('/api/reindex')
    async def reindex():
        runtime.request_index(force=True);return {'ok':True,'state':'已排队'}
    @app.post('/api/model-prepare')
    async def prepare():
        if runtime.model.download_state=='下载模型中':return {'state':'下载中'}
        def download():
            try:runtime.model.prepare();runtime.request_index(force=True)
            except Exception:logging.exception('Model preparation failed')
        threading.Thread(target=download,daemon=True,name='model-download').start();return {'state':'模型准备已开始'}
    # The SDK owns /mcp; share its single session manager in the root lifespan.
    app.router.routes.extend(mcp_app.routes)
    static=Path(static_dir) if static_dir else Path(__file__).parent/'static'
    @app.get('/assets/{path:path}')
    async def asset(path:str):
        p=(static/'assets'/path).resolve()
        if not p.is_relative_to(static/'assets') or not p.is_file():return Response(status_code=404)
        # Windows registry MIME associations can label .js as text/plain.
        media_type={'.js':'text/javascript','.mjs':'text/javascript','.css':'text/css'}.get(p.suffix.lower())
        return FileResponse(p,media_type=media_type,headers={'Cache-Control':'public, max-age=31536000, immutable'})
    @app.get('/')
    async def index():
        if not (static/'index.html').is_file():return HTMLResponse('网页尚未构建，请运行前端构建',status_code=503)
        response=HTMLResponse((static/'index.html').read_text(encoding='utf-8'),headers={'Cache-Control':'no-store'});response.set_cookie('vault_session',token,httponly=True,samesite='strict',max_age=365*86400);return response
    return app

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
            server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=config.data.get('port',18080),workers=1,access_log=False,
                                                loop='asyncio:SelectorEventLoop',timeout_graceful_shutdown=20))
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
        uvicorn.run(create_app(config),host='127.0.0.1',port=config.data.get('port',18080),workers=1,access_log=False)
