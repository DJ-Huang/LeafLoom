"""Project-scoped HTTP websites, separate from the workspace's authority.

All origins share the existing loopback listener. Host dispatch must happen
before the workspace router: project requests never reach APIs or MCP.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import hmac
import html
import json
import mimetypes
from pathlib import Path, PurePosixPath
import re
import secrets
import threading
from urllib.parse import quote, urlencode, urlsplit

from starlette.responses import HTMLResponse, Response, RedirectResponse

from vault_rag.http_cache import conditional_file
from vault_rag.local_state import ConflictError, atomic_write, relative
from vault_rag.platform_support import is_link

MAX_SESSIONS = 32
MAX_DRAFT_BYTES = 10 * 1024 * 1024
MAX_TOTAL_DRAFT_BYTES = 32 * 1024 * 1024
PRIVATE_PARTS = {'.git', '.obsidian', '.vault-rag', '.rag-layout-backups'}
COOKIE = 'leafloom_web'
INTERNAL = '/__leafloom__/'
MIME = {'.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css',
        '.wasm': 'application/wasm', '.json': 'application/json', '.svg': 'image/svg+xml',
        '.html': 'text/html', '.htm': 'text/html', '.woff2': 'font/woff2'}


class HtmlProjects:
    def __init__(self, config, port):
        self.config = config
        self.port = port
        self.lock = threading.RLock()
        identity = config.directory / 'web-identity'
        if not identity.exists():
            atomic_write(identity, secrets.token_hex(16).encode())
        self.install_id = identity.read_text().strip()
        if not re.fullmatch('[a-f0-9]{32}', self.install_id):
            raise ValueError('Invalid local website identity')
        self.suffix = f'.{self.install_id}.localhost'
        self.ui_host = 'app' + self.suffix
        self.ui_origin = f'http://{self.ui_host}:{port}'
        self.boot_secret = secrets.token_bytes(32)
        self.registry_file = config.directory / 'html-projects.json'
        self.projects = json.loads(self.registry_file.read_text()) if self.registry_file.exists() else []
        self.sessions = OrderedDict()
        self.tickets = {}

    def is_project_host(self, host):
        return bool(re.fullmatch(r'[pd]-[a-f0-9]{32}' + re.escape(self.suffix) + f':{self.port}', host))

    def _check_root(self, expected):
        if expected != str(self.config.root):
            raise ConflictError('关联目录已切换，请重新打开网页；原草稿仍保留')

    def _directory(self, root):
        root = relative(root)
        p = self.config.path_for(root)
        if not p.is_dir():
            raise ValueError('请选择项目文件夹')
        if (p / INTERNAL.strip('/')).exists():
            raise ValueError('项目使用了保留目录 __leafloom__，请选择其他项目目录')
        return p

    def list(self, root, path=''):
        with self.config.lock, self.lock:
            self._check_root(root)
            path = relative(path)
            projects = [dict(p) for p in self.projects if p['vault'] == root]
            matches = [p for p in projects if not p['directory'] or path == p['directory'] or path.startswith(p['directory'] + '/')]
            selected = max(matches, key=lambda p: len(p['directory']), default=None)
            return {'projects': projects, 'selected': selected,
                    'suggested_directory': '' if str(PurePosixPath(path).parent) == '.' else str(PurePosixPath(path).parent)}

    def register(self, root, directory, entry, spa=False, project_id=None):
        with self.config.lock, self.lock:
            self._check_root(root)
            if not isinstance(spa, bool):
                raise ValueError('SPA 设置必须是布尔值')
            directory = relative(directory)
            p = self._directory(directory)
            entry = relative(entry)
            if not self.config.path_for(entry).is_file() or not self.config.path_for(entry).is_relative_to(p):
                raise ValueError('入口文件必须位于项目文件夹内')
            previous = next((p for p in self.projects if p['vault'] == root and
                             (p['id'] == project_id if project_id else p['directory'] == directory)), None)
            if project_id and previous is None:
                raise ValueError('网页项目不存在')
            project = {'id': previous['id'] if previous else secrets.token_hex(16), 'vault': root,
                       'directory': directory, 'entry': entry, 'spa': spa}
            updated = [p for p in self.projects if p['id'] != project['id']] + [project]
            atomic_write(self.registry_file, json.dumps(updated, ensure_ascii=False).encode())
            self.projects = updated
            if previous and previous != project:
                for sid, session in list(self.sessions.items()):
                    if session.get('project_id') == project['id']:
                        self._release(sid)
            return project

    def create(self, root, path='', project_id=None, draft=None, url=None):
        with self.config.lock, self.lock:
            self._check_root(root)
            if url is not None:
                if not isinstance(url, str) or len(url) > 8192:
                    raise ValueError('请输入 HTTP 或 HTTPS 网站地址')
                target = urlsplit(url)
                if target.scheme not in ('http', 'https') or not target.hostname or target.username or target.password:
                    raise ValueError('请输入 HTTP 或 HTTPS 网站地址')
                if target.port == self.port and (target.hostname in ('127.0.0.1', 'localhost', self.ui_host) or target.hostname.endswith(self.suffix)):
                    raise ValueError('请通过项目入口打开本应用的网页')
                return {'id': None, 'url': url, 'mode': 'external'}
            project = next((p for p in self.projects if p['id'] == project_id and p['vault'] == root), None)
            if project is None:
                raise ValueError('请先确认 HTML 项目的根目录')
            path = relative(path)
            base = self._directory(project['directory'])
            entry = self.config.path_for(path)
            if not entry.is_file() or not entry.is_relative_to(base) or entry.suffix.lower() not in ('.html', '.htm'):
                raise ValueError('请选择项目内的 HTML 文件')
            if draft is not None and (not isinstance(draft, str) or len(draft.encode()) > MAX_DRAFT_BYTES):
                raise ValueError('HTML 草稿超过 10 MiB 或格式无效')
            sid = secrets.token_hex(16)
            host = ('d-' + sid if draft is not None else 'p-' + project['id']) + self.suffix
            entry_path = entry.relative_to(base).as_posix()
            session = {'id': sid, 'host': host, 'project_id': project['id'], 'vault': root,
                       'revision': self.config.data.get('revision'), 'entry': entry_path, 'draft': draft}
            self.sessions[sid] = session
            ticket = secrets.token_urlsafe(32)
            self.tickets[ticket] = sid
            while len(self.sessions) > MAX_SESSIONS or sum(len((s['draft'] or '').encode()) for s in self.sessions.values()) > MAX_TOTAL_DRAFT_BYTES:
                self._release(next(iter(self.sessions)))
            origin = f'http://{host}:{self.port}'
            return {'id': sid, 'url': origin + INTERNAL + 'open?' + urlencode({'ticket': ticket}),
                    'origin': origin, 'entry': '/' + quote(entry_path, safe='/'),
                    'mode': 'draft' if draft is not None else 'saved'}

    def _release(self, sid):
        self.sessions.pop(sid, None)
        self.tickets = {ticket: value for ticket, value in self.tickets.items() if value != sid}

    def release(self, sid):
        with self.lock:
            self._release(sid)

    def _signature(self, host):
        value = host + '\n' + str(self.config.data.get('root')) + '\n' + str(self.config.data.get('revision'))
        return hmac.new(self.boot_secret, value.encode(), hashlib.sha256).hexdigest()

    def _active(self, session):
        return session['vault'] == self.config.data.get('root') and session['revision'] == self.config.data.get('revision')

    def _headers(self):
        return {'Content-Security-Policy': f"frame-ancestors 'self' {self.ui_origin}",
                'Referrer-Policy': 'strict-origin-when-cross-origin', 'X-Content-Type-Options': 'nosniff',
                'Cross-Origin-Resource-Policy': 'same-origin'}

    def response(self, request):
        with self.config.lock, self.lock:
            return self._response(request)

    def _response(self, request):
        host = request.url.hostname
        path = request.url.path
        headers = self._headers()
        if request.method not in ('GET', 'HEAD'):
            return Response(status_code=405, headers={**headers, 'Allow': 'GET, HEAD'})
        if path == INTERNAL + 'open':
            sid = self.tickets.get(request.query_params.get('ticket', ''))
            session = self.sessions.get(sid)
            if not session or session['host'] != host or not self._active(session):
                return HTMLResponse('网页会话已失效，请回到知识库重新打开。', status_code=410, headers=headers)
            self.tickets.pop(request.query_params['ticket'])
            response = RedirectResponse(INTERNAL + 'viewer?' + urlencode({'session': sid}), status_code=303, headers={**headers, 'Referrer-Policy': 'no-referrer'})
            response.set_cookie(COOKIE, self._signature(host), httponly=True, samesite='strict', path='/')
            response.headers['Cache-Control'] = 'no-store'
            return response
        candidates = [s for s in self.sessions.values() if s['host'] == host and self._active(s)]
        cookie = hmac.compare_digest(request.cookies.get(COOKIE, ''), self._signature(host))
        origin = f'http://{host}:{self.port}'
        # Cocoa treats distinct .localhost hosts as cross-site and can reject
        # their embedded cookies. A private session capability authorizes the
        # viewer document; its resources then carry browser-controlled same-
        # origin provenance. Never accept cross-site resource requests merely
        # because the project has another active viewer.
        referer = request.headers.get('referer', '')
        try:
            source = urlsplit(referer)
            referred = f'{source.scheme}://{source.netloc}' == origin
        except ValueError:
            referred = False
        same_origin = (request.headers.get('sec-fetch-site') == 'same-origin' or
                       request.headers.get('origin') == origin or referred)
        sid = request.query_params.get('session')
        capability = path in {INTERNAL + name for name in ('viewer', 'viewer.js', 'status')} and any(s['id'] == sid for s in candidates)
        if not candidates or not (cookie or capability or same_origin):
            return HTMLResponse('网页会话已失效，请回到知识库重新打开。', status_code=410, headers={**headers, 'Cache-Control': 'no-store'})
        session = candidates[-1]
        if path.startswith(INTERNAL):
            sid = request.query_params.get('session')
            session = self.sessions.get(sid)
            if not session or session not in candidates:
                return Response(status_code=410, headers=headers)
            if path == INTERNAL + 'status':
                return Response('ok', headers={**headers, 'Cache-Control': 'no-store'})
            if path == INTERNAL + 'viewer.js':
                return Response(VIEWER_JS, media_type='text/javascript', headers={**headers, 'Cache-Control': 'no-store'})
            if path == INTERNAL + 'viewer':
                entry = request.query_params.get('path', '/' + quote(session['entry'], safe='/'))
                if len(entry) > 8192 or not entry.startswith('/') or entry.startswith('//') or '\\' in entry or any(ord(c)<32 for c in entry):
                    return Response(status_code=400, headers=headers)
                settings = html.escape(json.dumps({'session': session['id'], 'parent': self.ui_origin,
                                                   'entry': entry}, ensure_ascii=False), quote=True)
                response = HTMLResponse('<!doctype html><meta charset="utf-8"><title>LeafLoom Web</title>'
                    '<style>html,body,iframe{width:100%;height:100%;margin:0;border:0;display:block;overflow:hidden}</style>'
                    f'<body data-settings="{settings}"><iframe title="项目网页" allow="fullscreen; clipboard-read; clipboard-write; autoplay; camera; microphone; geolocation; display-capture" allowfullscreen></iframe>'
                    f'<script src="viewer.js?session={session["id"]}"></script>',
                    headers={**headers, 'Cache-Control': 'no-store'})
                # An explicit standalone visit can establish an ordinary
                # first-party cookie, even when the embedded visit could not.
                response.set_cookie(COOKIE, self._signature(host), httponly=True, samesite='strict', path='/')
                return response
            return Response(status_code=404, headers=headers)
        project = next((p for p in self.projects if p['id'] == session['project_id']), None)
        if project is None:
            return Response(status_code=410, headers=headers)
        try:
            rel = relative(path.lstrip('/'))
            if any(part.lower() in PRIVATE_PARTS for part in PurePosixPath(rel).parts):
                raise ValueError('私有目录不可浏览')
            base = self._directory(project['directory'])
            p = base / rel
            current = base
            for part in PurePosixPath(rel).parts:
                current = current / part
                if is_link(current):
                    raise ValueError('不允许通过链接读取网页资源')
            if not p.resolve().is_relative_to(base):
                raise ValueError('资源路径越出项目目录')
            if p.is_dir():
                if not path.endswith('/'):
                    return RedirectResponse(path + '/' + ('?' + request.url.query if request.url.query else ''), headers=headers)
                p = p / 'index.html'
                if is_link(p):
                    raise ValueError('不允许通过链接读取网页资源')
            if not p.is_file() and project['spa'] and 'text/html' in request.headers.get('accept', '') and not p.suffix:
                p = self.config.path_for(project['entry'])
            if not p.is_file():
                return Response(status_code=404, headers=headers)
            if session['draft'] is not None and p == base / session['entry']:
                return HTMLResponse(session['draft'], headers={**headers, 'Cache-Control': 'no-store'})
            # No decoding or charset injection: BOM/meta/@charset retain their usual meaning.
            media_type = MIME.get(p.suffix.lower(), mimetypes.guess_type(p.name)[0] or 'application/octet-stream')
            response = conditional_file(p, request, headers=headers, identity=session['vault'] + str(session['revision']), media_type=media_type)
            response.headers['Content-Type'] = media_type
            return response
        except (ValueError, FileNotFoundError):
            return Response(status_code=404, headers=headers)


VIEWER_JS = r"""
(()=>{
 const settings=JSON.parse(document.body.dataset.settings),frame=document.querySelector('iframe');
 const send=(type,extra={})=>parent.postMessage({type,session:settings.session,...extra},settings.parent);
 let current='',started=false;
 function report(){try{const url=frame.contentWindow.location.href;if(url==='about:blank')return;if(url!==current){current=url;send('leafloom-web-location',{url});}}catch{send('leafloom-web-external');}}
 frame.addEventListener('load',()=>{started=true;report();send('leafloom-web-ready');});
 addEventListener('message',event=>{
  if(event.source!==parent||event.origin!==settings.parent||event.data?.session!==settings.session)return;
  try{if(event.data.command==='reload')frame.contentWindow.location.reload();
   if(event.data.command==='entry')frame.src=settings.entry;
   if(event.data.command==='back')frame.contentWindow.history.back();
   if(event.data.command==='forward')frame.contentWindow.history.forward();
  }catch{if(event.data.command==='reload')frame.src=settings.entry;}
 });
 frame.src=settings.entry;
 const timer=setInterval(()=>{if(started)report();fetch('status?session='+settings.session,{cache:'no-store'}).then(r=>{if(r.status===410)send('leafloom-web-expired');}).catch(()=>{});},1500);
 addEventListener('pagehide',()=>clearInterval(timer));
})();
"""
