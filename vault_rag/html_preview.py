"""Read-only, opaque-origin browsing of local HTML and its companion files."""
from __future__ import annotations

from collections import OrderedDict
import re
import secrets
import threading
from urllib.parse import quote

from starlette.responses import FileResponse, HTMLResponse

from vault_rag.local_state import ConflictError
from vault_rag.http_cache import conditional_file


SANDBOX = 'allow-scripts allow-modals allow-downloads allow-popups allow-popups-to-escape-sandbox'
MAX_PREVIEWS = 32
MAX_HTML_BYTES = 10 * 1024 * 1024
MAX_PREVIEW_BYTES = 32 * 1024 * 1024

# Only report navigation and Escape. Never expose a bridge to the file/write API.
BRIDGE = """<script>
(()=>{
 const report=()=>parent.postMessage({type:'vault-html-preview-location',url:location.href},'*');
 addEventListener('hashchange',report);addEventListener('pageshow',report);
 document.addEventListener('keydown',e=>{if(e.key==='Escape')parent.postMessage({type:'vault-html-preview-exit'},'*')});
 document.addEventListener('click',e=>{
  const a=e.target.closest?.('a[href]');if(!a)return;
  const u=new URL(a.href,location.href);
  if(/^https?:$/.test(u.protocol)&&!u.href.startsWith(location.origin+location.pathname.split('/').slice(0,3).join('/')+'/')){
   a.target='_blank';a.rel='noopener noreferrer';
  }
 });
})();
</script>"""


def with_bridge(text: str) -> str:
    # Insert before the document ends, without rewriting any original markup.
    ends = list(re.finditer(r'</body\s*>', text, re.IGNORECASE))
    pos = ends[-1].start() if ends else len(text)
    return text[:pos] + BRIDGE + text[pos:]


class HtmlPreviews:
    def __init__(self, config):
        self.config = config
        self.entries = OrderedDict()
        self.lock = threading.RLock()

    def create(self, path: str, root: str, text: str) -> dict:
        with self.config.lock, self.lock:
            return self._create(path, root, text)

    def _create(self, path: str, root: str, text: str) -> dict:
        if root != str(self.config.root):
            raise ConflictError('关联目录已切换，请重新打开网页；原草稿仍保留')
        p = self.config.path_for(path)
        if not p.is_file() or p.suffix.lower() not in ('.html', '.htm'):
            raise ValueError('请选择本地 HTML 文件')
        if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_HTML_BYTES:
            raise ValueError('HTML 内容无效或超过 10 MiB')
        path = p.relative_to(self.config.root).as_posix()
        key = secrets.token_urlsafe(32)
        self.entries[key] = (root, self.config.data.get('revision'), path, text)
        while len(self.entries) > MAX_PREVIEWS or sum(len(entry[3].encode('utf-8')) for entry in self.entries.values()) > MAX_PREVIEW_BYTES:
            self.entries.popitem(last=False)
        return {'url': f'/html-preview/{key}/files/{quote(path, safe="/")}'}

    def response(self, key: str, path: str, origin: str, download: bool = False, request=None):
        with self.config.lock, self.lock:
            return self._response(key, path, origin, download, request)

    def _response(self, key: str, path: str, origin: str, download: bool = False, request=None):
        entry = self.entries.get(key)
        valid = entry and entry[0] == self.config.data.get('root') and entry[1] == self.config.data.get('revision')
        # Never interpolate an untrusted route segment into CSP source expressions.
        policy_key = key if re.fullmatch(r'[A-Za-z0-9_-]{43}', key) else 'expired'
        base = f'{origin}/html-preview/{policy_key}/files/'
        policy = (
            f"sandbox {SANDBOX}; default-src 'none'; "
            f"script-src 'unsafe-inline' {base}; style-src 'unsafe-inline' {base}; "
            f"img-src {base} data: blob:; media-src {base} blob:; font-src {base} data:; "
            f"connect-src {base}; frame-src {base}; base-uri {base}; "
            "form-action 'none'; object-src 'none'; frame-ancestors 'self'"
        )
        if not valid:
            self.entries.pop(key, None)
            response = HTMLResponse(
                '<!doctype html><meta charset="utf-8"><title>预览已失效</title>'
                '<p>网页预览已失效，请回到知识库点击“刷新”。</p>'
                "<script>parent.postMessage({type:'vault-html-preview-expired'},'*')</script>",
                status_code=410,
            )
        else:
            p = self.config.path_for(path)
            if not p.is_file():
                raise FileNotFoundError(path)
            self.entries.move_to_end(key)
            if p.suffix.lower() in ('.html', '.htm') and not download:
                if path != entry[2] and p.stat().st_size > MAX_HTML_BYTES:
                    raise ValueError('HTML 内容超过 10 MiB')
                text = entry[3] if path == entry[2] else p.read_text(encoding='utf-8-sig')
                if len(text.encode('utf-8')) > MAX_HTML_BYTES:
                    raise ValueError('HTML 内容超过 10 MiB')
                response = HTMLResponse(with_bridge(text))
            else:
                attachment = download or p.suffix.lower() in ('.md', '.txt', '.base')
                response = conditional_file(p,request,filename=p.name if attachment else None,
                                            content_disposition_type='attachment' if attachment else 'inline')
            # Sandboxed module scripts, fonts and local fetches have Origin: null.
            # The unguessable URL grants only rooted file reads, never credentials.
            response.headers['Access-Control-Allow-Origin'] = 'null'
        response.headers['Content-Security-Policy'] = policy
        response.headers.setdefault('Cache-Control','no-store')
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
