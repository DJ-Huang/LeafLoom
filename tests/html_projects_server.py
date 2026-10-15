"""Disposable browser fixture; --vault serves an existing vault without scanning/writes."""
import argparse
import json
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vault_rag.local_state import LocalConfig
from vault_rag.knowledge import Runtime
from vault_rag.web_server import create_app, create_server

parser=argparse.ArgumentParser()
parser.add_argument('--directory',required=True)
parser.add_argument('--port',type=int,required=True)
parser.add_argument('--vault')
parser.add_argument('--identity',help='Reuse an explicitly configured test DNS namespace, never its service state')
args=parser.parse_args()
base=Path(args.directory).resolve();base.mkdir(parents=True,exist_ok=True)
root=Path(args.vault).resolve() if args.vault else base/'vault'
if not args.vault:
    root.mkdir(exist_ok=True)
    fixtures={
      'site/index.html':'''<!doctype html><meta charset="utf-8"><title>Website fixture</title>
<link rel="stylesheet" href="/assets/site.css"><h1 id="heading">项目网页</h1><p id="result">loading</p>
<iframe id="nested" src="nested.html"></iframe><a id="download" download href="/assets/file.bin">download</a>
<script type="module" src="/assets/app.mjs"></script>''',
      'site/nested.html':'''<!doctype html><button id="child">Nested board</button><script>parent.postMessage({nested:true},location.origin)</script>''',
      'site/assets/site.css':'h1{color:rgb(23, 45, 67)}',
      'site/api/data.json':'{"value":42}',
      'site/assets/app.mjs':'''let nested=false;addEventListener('message',e=>{if(e.origin===location.origin&&e.data.nested)nested=true});
const results=await Promise.all([fetch('/api/data.json').then(r=>r.json()),new Promise(resolve=>{const w=new Worker('/assets/worker.js');w.onmessage=e=>{resolve(e.data);w.terminate()}}),WebAssembly.instantiateStreaming(fetch('/assets/module.wasm')),new Promise((resolve,reject)=>{const r=indexedDB.open('fixture',1);r.onupgradeneeded=()=>r.result.createObjectStore('values');r.onsuccess=()=>{r.result.close();resolve(true)};r.onerror=()=>reject(r.error)})]);
localStorage.setItem('fixture','retained');await navigator.serviceWorker.register('/sw.js');
window.fixture={value:results[0].value,worker:results[1],wasm:!!results[2].instance,storage:localStorage.getItem('fixture'),indexedDB:results[3],secure:isSecureContext};
document.querySelector('#result').textContent='ready';''',
      'site/assets/worker.js':'postMessage(43)',
      'site/assets/file.bin':'download fixture',
      'site/sw.js':'self.addEventListener("install",()=>self.skipWaiting())',
      'notes.md':'# Disposable knowledge\n',
    }
    for name,text in fixtures.items():
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
    (root/'site/assets/module.wasm').write_bytes(b'\0asm\x01\0\0\0')
config=LocalConfig(base/'state');config.save({'root':str(root),'port':args.port})
if args.identity:
    import re
    assert re.fullmatch('[a-f0-9]{32}',args.identity)
    (config.directory/'web-identity').write_text(args.identity)
runtime=Runtime(config)
if not args.vault:runtime.catalog.scan()
if args.vault:
    static=base/'readonly-ui';static.mkdir();(static/'index.html').write_text('<!doctype html><title>Read-only website acceptance</title><body>Read-only host</body>')
else:static=None
app=create_app(config,runtime,start_background=False,static_dir=static)
info={'url':f'http://127.0.0.1:{args.port}','ui':app.state.websites.ui_origin,'root':str(root),'state':str(config.directory),'port':args.port}
(base/'info.json').write_text(json.dumps(info))
logging.getLogger('httpx').setLevel(logging.WARNING)
create_server(app,port=args.port).run()
