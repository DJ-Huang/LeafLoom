"""One-way, top-level storage migration with bounded, one-use local handoffs.

A hidden cross-site iframe would import into partitioned storage in some
browsers. Import at the new top-level origin instead; retain the originals.
"""
from collections import OrderedDict
import html
import hashlib
import json
import secrets
import sys
import threading
import time
from starlette.responses import HTMLResponse, Response
from vault_rag.local_state import atomic_write

MAX_BYTES = 32 * 1024 * 1024
OWNED = ('draft:', 'workspace:', 'view:', 'edit:', 'jump:', 'cursor:', 'ai-', 'leafloom-', 'leafloom:')


class BrowserStorageMigration:
    def __init__(self, ui_origin, port, directory):
        self.ui_origin = ui_origin
        self.legacy = {f'http://127.0.0.1:{port}', f'http://localhost:{port}'}
        self.pending = OrderedDict()
        self.lock = threading.RLock()
        self.receipts_file = directory / 'browser-migration-receipts.json'
        self.receipts = json.loads(self.receipts_file.read_text()) if self.receipts_file.exists() else []

    def completed(self, receipt):
        with self.lock:
            return hashlib.sha256((self.ui_origin + receipt).encode()).hexdigest() in self.receipts

    def _prune(self):
        for key, value in list(self.pending.items()):
            if time.monotonic() - value['time'] > 300:
                self.pending.pop(key)
        while len(self.pending) > 8:
            self.pending.popitem(last=False)

    def page(self, collector=False, ticket=''):
        with self.lock:
            self._prune()
            nonce = secrets.token_urlsafe(32)
            if not collector:
                self.pending[nonce] = {'time': time.monotonic(), 'data': None}
            settings = {'target': self.ui_origin, 'collector': collector, 'nonce': nonce, 'ticket': ticket, 'resolver': sys.platform=='darwin'}
            encoded = html.escape(json.dumps(settings), quote=True)
            return HTMLResponse('<!doctype html><meta charset="utf-8"><title>LeafLoom</title>'
                '<style>body{font:16px/1.7 system-ui;max-width:660px;margin:10vh auto;padding:24px}</style>'
                f'<body data-settings="{encoded}"><h1>LeafLoom</h1>'
                '<p id="status">正在保留本地草稿与阅读状态… / Preserving local drafts and reading state…</p>'
                '<p><a href="">重试 / Retry</a></p><script src="/__leafloom__/storage.js"></script>',
                headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'Content-Security-Policy':
                         f"default-src 'none'; script-src 'self'; connect-src 'self' {self.ui_origin}; style-src 'unsafe-inline'; frame-ancestors 'none'"})

    def authorize_resolver(self, nonce, origin):
        with self.lock:
            self._prune()
            value = self.pending.get(nonce)
            if origin not in self.legacy or not value or value['data'] is not None or value.get('resolver_used'):
                raise ValueError('解析配置凭证已失效，请刷新页面重试')
            value['resolver_used'] = True

    def submit(self, nonce, data, origin):
        with self.lock:
            self._prune()
            previous = self.pending.get(nonce)
            if origin not in self.legacy or not previous or previous['data'] is not None:
                raise ValueError('存储迁移凭证已失效，请回到原入口重试')
            if not isinstance(data, dict) or len(json.dumps(data).encode()) > MAX_BYTES:
                raise ValueError('迁移数据无效或过大；原草稿仍保留')
            for kind in ('local', 'session'):
                if not isinstance(data.get(kind), list) or len(data[kind]) > 10000:
                    raise ValueError('迁移数据无效')
                for item in data[kind]:
                    if not isinstance(item, list) or len(item) != 2 or not all(isinstance(v, str) for v in item) or not item[0].startswith(OWNED):
                        raise ValueError('迁移数据无效')
            target = data.get('returnTo', '')
            if not isinstance(target, str) or len(target) > 8192 or (target and target[0] not in ('?', '#')):
                raise ValueError('迁移返回地址无效')
            if sum(len(json.dumps(v['data']).encode()) for v in self.pending.values() if v['data']) + len(json.dumps(data).encode()) > MAX_BYTES:
                raise ValueError('迁移暂存已满，请稍后重试；原草稿仍保留')
            ticket = secrets.token_urlsafe(32)
            self.pending.pop(nonce)
            self.pending[ticket] = {'time': time.monotonic(), 'data': {**data, 'origin': origin}}
            return {'url': self.ui_origin + '/__leafloom__/migrate?ticket=' + ticket}

    def read(self, ticket, acknowledge=False):
        with self.lock:
            self._prune()
            value = self.pending.get(ticket)
            if not value or value['data'] is None:
                raise ValueError('存储迁移凭证已失效，请回到原入口重试')
            if acknowledge:
                receipt = hashlib.sha256((self.ui_origin + ticket).encode()).hexdigest()
                receipts = (self.receipts + [receipt])[-128:]
                atomic_write(self.receipts_file, json.dumps(receipts).encode())
                self.receipts = receipts
                self.pending.pop(ticket)
                return {'acknowledged': True}
            return value['data']


def migration_script():
    return Response(SCRIPT, media_type='text/javascript', headers={'Cache-Control': 'no-store'})


SCRIPT = r"""
(async()=>{
 const cfg=JSON.parse(document.body.dataset.settings),status=document.querySelector('#status');
 const owned=key=>/^(draft:|workspace:|view:|edit:|jump:|cursor:|ai-|leafloom-|leafloom:)/.test(key)&&!key.startsWith('leafloom:migration-');
 const read=store=>{const items=[];for(let i=0;i<store.length;i++){const k=store.key(i);if(owned(k))items.push([k,store.getItem(k)]);}return items;};
 const request=async(url,options)=>{const response=await fetch(url,options);const value=await response.json();if(!response.ok)throw new Error(value.error||'Migration failed');return value;};
 try{
  if(!cfg.collector){
   // Check the new origin before moving any state or leaving the working entrance.
   // Older Apple networking frameworks do not resolve wildcard localhost names.
   try{await fetch(cfg.target+'/healthz',{mode:'no-cors',cache:'no-store',signal:AbortSignal.timeout(5000)});}
   catch{
    if(cfg.resolver){
     const button=document.createElement('button');button.textContent='启用 Safari 兼容 / Enable Safari compatibility';
     button.onclick=async()=>{button.disabled=true;try{status.textContent='请在 macOS 系统窗口授权本应用的专属域名解析。 / Authorize scoped local name resolution in macOS.';await request('/__leafloom__/local-resolver',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nonce:cfg.nonce})});location.reload();}catch(error){status.textContent=String(error)+' 请刷新重试。 / Reload to retry.';}};
     document.body.append(button);
    }
    throw new Error('本机项目地址解析不可用。macOS 14/15 Safari 需要启用本机解析兼容；只添加本应用专属域名，可在设置中移除。 / Local website resolution is unavailable. Enable scoped Safari compatibility; it can be removed in Settings.');
   }
   const local=read(localStorage).sort(),session=read(sessionStorage).sort();
   const digest=async items=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(items))))).map(v=>v.toString(16).padStart(2,'0')).join('');
   const localHash=await digest(local),sessionHash=await digest(session),receiptKey='leafloom:migration-receipt:'+cfg.target;
   let previous=null;try{previous=JSON.parse(localStorage.getItem(receiptKey)||'null');}catch{}
   if(previous?.localHash===localHash&&(!session.length||previous.sessionHash===sessionHash)){
    const state=await request('/__leafloom__/migration-state?receipt='+encodeURIComponent(previous.ticket));
    if(state.completed){location.replace(cfg.target+'/'+location.search+location.hash);return;}
   }
   const value=await request('/__leafloom__/transfer?nonce='+encodeURIComponent(cfg.nonce),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({local,session,returnTo:location.search+location.hash})});
   localStorage.setItem(receiptKey,JSON.stringify({ticket:new URL(value.url).searchParams.get('ticket'),localHash,sessionHash}));
   location.replace(value.url);
  }else{
   const data=await request('/__leafloom__/transfer?ticket='+encodeURIComponent(cfg.ticket));
   // Save a complete recovery copy first. Never overwrite a newer destination draft.
   if(data.local.length||data.session.length)localStorage.setItem('leafloom:migration-backup:'+data.origin,JSON.stringify(data));
   let conflicts=0;
   for(const [kind,store] of [['local',localStorage],['session',sessionStorage]])for(const [key,value] of data[kind]){
    const existing=store.getItem(key);if(existing===null)store.setItem(key,value);else if(existing!==value)conflicts++;
   }
   if(conflicts)localStorage.setItem('leafloom:migration-conflicts','true');
   await request('/__leafloom__/transfer?ticket='+encodeURIComponent(cfg.ticket),{method:'DELETE'});
   location.replace(cfg.target+'/'+(data.returnTo||''));
  }
 }catch(error){status.textContent='迁移未完成，原草稿仍保留。请重试。 / Migration incomplete; original drafts are retained. '+String(error);}
})();
"""
