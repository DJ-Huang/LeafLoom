"""Bounded, immutable static publication jobs in an offline Chromium context.

No authored script runs. Only snapshotted, registered design assets are served;
all other browser requests are aborted, including localhost and file URLs.
"""
from __future__ import annotations

import copy
import base64
import struct
import importlib.util
import io
import json
import math
import re
import mimetypes
import shutil
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, unquote, unquote_to_bytes, urlsplit

from vault_rag.local_state import ConflictError, atomic_write, relative

ORIGIN = 'https://studio-export.invalid'
MAX_ITEMS = 64
MAX_PIXELS = 128_000_000
MAX_ITEM_PIXELS = 32_000_000
MAX_ASSETS = 128 * 1024 * 1024
MAX_ITEM_OUTPUT = 32 * 1024 * 1024
MAX_JOB_OUTPUT = 256 * 1024 * 1024
MAX_SESSION_OUTPUT = 512 * 1024 * 1024
RUNTIME = Path(__file__).parent / 'design_assets' / 'studio'
SETUP = 'Static publishing requires the publish extra (pip install "vault-rag[publish]") and Chromium (python -m playwright install chromium).'


def validate_static_media(data, name='image'):
    """Reject media with independent clocks; CSS pause cannot freeze these."""
    animated = (data.startswith((b'GIF87a', b'GIF89a')) or
                data.startswith(b'\x89PNG\r\n\x1a\n') and b'acTL' in data or
                data.startswith(b'RIFF') and data[8:12] == b'WEBP' and (b'ANIM' in data or b'ANMF' in data))
    if animated:
        raise ValueError(f'{name}: GIF, animated PNG and animated WebP require a static PNG/JPEG replacement for deterministic publication')
    svg_like = name == 'Inline SVG' or name.lower().endswith('.svg') or b'<svg' in data[:4096].lower()
    if svg_like and re.search(br'<(?:[A-Za-z_][\w.-]*:)?(?:animate(?:Motion|Transform|Color)?|set)\b', data, re.I):
        raise ValueError(f'{name}: animated SVG requires a static SVG/PNG replacement for deterministic publication')


def validate_inline_media(value, key=''):
    if isinstance(value, dict):
        for name, child in value.items():
            if name not in ('script','scripts','source'):
                validate_inline_media(child, name)
    elif isinstance(value, list):
        for child in value:
            validate_inline_media(child, key)
    elif isinstance(value, str):
        if key in ('html','svg'):
            validate_static_media(value.encode(), 'Inline SVG')
        for match in re.finditer(r'data:image/[a-zA-Z0-9.+-]+(?:;[a-zA-Z0-9=.+-]+)*,[^\s\"\'<>)]*', value):
            header, encoded = match.group().split(',',1)
            try:
                decoded = base64.b64decode(encoded, validate=True) if ';base64' in header.lower() else unquote_to_bytes(encoded)
            except Exception as error:
                raise ValueError('Malformed inline image data') from error
            validate_static_media(decoded, 'inline.svg' if 'svg' in header.lower() else 'Inline image')


def renderer_available(format='png'):
    if importlib.util.find_spec('playwright') is None or format == 'pdf' and importlib.util.find_spec('pypdf') is None:
        return False
    if shutil.which('chromium') or shutil.which('chromium-browser') or shutil.which('google-chrome'):
        return True
    # Playwright's bundled browser path can be inspected without launching it.
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as driver:
            return Path(driver.chromium.executable_path).is_file()
    except Exception:
        return False


def plan(document, page_ids, variant_ids=None, scale=1, format='png'):
    validate_inline_media(document)
    if format not in ('png', 'pdf'):
        raise ValueError('Choose PNG or PDF')
    if isinstance(scale, bool) or not isinstance(scale, (float, int)) or not math.isfinite(scale) or not 1 <= scale <= 4:
        raise ValueError('Export scale must be between 1 and 4')
    if not isinstance(page_ids, list) or not page_ids or any(not isinstance(v, str) for v in page_ids) or len(set(page_ids)) != len(page_ids):
        raise ValueError('Choose distinct pages to publish')
    variants = [None] if variant_ids is None else variant_ids
    if not isinstance(variants, list) or not variants or any(v is not None and not isinstance(v, str) for v in variants) or len(set(variants)) != len(variants):
        raise ValueError('Choose distinct variants to publish')
    if len(page_ids) * len(variants) > MAX_ITEMS:
        raise ValueError('Publish at most 64 page/variant combinations at a time')
    if len(json.dumps(document, ensure_ascii=False).encode()) * len(page_ids) * len(variants) > 32 * 1024 * 1024:
        raise ValueError('Publication document snapshot exceeds 32 MiB; choose fewer combinations')
    pages = {page['id']: page for page in document['pages']}
    items, pixels, snapshot_bytes = [], 0, 0
    for variant in variants:
        # The resolver always copies; base and selected variants cannot mutate
        # the interactive source or each other.
        from vault_rag.design_bindings import resolve_document
        resolved = resolve_document(document, variant)
        if isinstance(resolved, tuple):
            resolved = resolved[0]
        snapshot_bytes += len(json.dumps(resolved, ensure_ascii=False).encode()) * len(page_ids)
        if snapshot_bytes > 32 * 1024 * 1024:
            raise ValueError('Publication document snapshot exceeds 32 MiB; choose fewer combinations')
        selected = {page['id']: page for page in resolved['pages']}
        warnings = []
        if variant is not None:
            from vault_rag.design_bindings import binding_status
            status = binding_status(document, variant)
            if status['missing']:
                warnings.append(f"Variant {variant}: {len(status['missing'])} missing values use source content")
            if status['stale']:
                warnings.append(f"Variant {variant}: {len(status['stale'])} values need review after source changes")
        for page_id in page_ids:
            if page_id not in pages or page_id not in selected:
                raise ValueError('Selected page does not exist')
            page = selected[page_id]
            width, height = page.get('width'), page.get('height')
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 1 <= v <= 8192 for v in (width, height)):
                raise ValueError('Pages need explicit dimensions between 1 and 8192 pixels')
            width, height = math.ceil(width), math.ceil(height)
            count = math.ceil(width * scale) * math.ceil(height * scale)
            if count > MAX_ITEM_PIXELS:
                raise ValueError('Each output must fit within 32 million pixels')
            pixels += count
            items.append({'id': str(len(items) + 1), 'page_id': page_id, 'variant_id': variant,
                          'width': width, 'height': height, 'status': 'queued', 'warnings': warnings, '_document': resolved})
    if pixels > MAX_PIXELS:
        raise ValueError('Batch exceeds 128 million pixels; reduce pages or scale')
    return items, pixels


def render_item(item, assets, format, scale):
    """Render one page in a fresh browser context with fail-closed networking."""
    from playwright.sync_api import sync_playwright
    width, height = item['width'], item['height']
    css = (RUNTIME / 'runtime.css').read_text() + '\n' + f'''
html,body,#studio-root,.studio-viewport {{ margin:0!important; padding:0!important; width:{width}px!important; height:{height}px!important; overflow:hidden!important; }}
.studio-stage {{left:0!important;top:0!important;transform:none!important;box-shadow:none!important;}}
.studio-canvas-chrome {{display:none!important;}}
*,*::before,*::after {{animation:none!important;transition:none!important;caret-color:transparent!important;}}
@page {{size:{width}px {height}px;margin:0;}}
'''
    # CSP permits only our trusted runtime. Authored scripts, frames, objects,
    # forms, connections and external resources remain prohibited.
    policy = "default-src 'none'; script-src 'none'; style-src 'unsafe-inline' https://studio-export.invalid; img-src https://studio-export.invalid data:; font-src https://studio-export.invalid data:; media-src 'none'; frame-src 'none'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
    entry = '<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' + policy + '"><div id="studio-root"></div>'
    blocked, failed = set(), set()
    with sync_playwright() as driver:
        executable = shutil.which('chromium') or shutil.which('chromium-browser') or shutil.which('google-chrome')
        browser = driver.chromium.launch(**({'executable_path': executable} if executable else {}))
        try:
            context = browser.new_context(viewport={'width': width, 'height': height}, device_scale_factor=scale,
                                          service_workers='block', reduced_motion='reduce', locale='en-US', timezone_id='UTC')
            def route(request):
                url = urlsplit(request.request.url)
                path = unquote(url.path).lstrip('/')
                if request.request.url == ORIGIN + '/':
                    request.fulfill(status=200, content_type='text/html', body=entry)
                elif url.scheme == 'https' and url.netloc == 'studio-export.invalid' and path in assets:
                    data, mime = assets[path]
                    request.fulfill(status=200, content_type=mime, body=data)
                else:
                    blocked.add(request.request.url)
                    request.abort()
            context.route('**/*', route)
            page = context.new_page()
            page.on('requestfailed', lambda request: failed.add(request.url))
            page.goto(ORIGIN + '/', wait_until='load', timeout=15000)
            page.evaluate("window.__blockedResources=[]; document.addEventListener('securitypolicyviolation',e=>window.__blockedResources.push(e.blockedURI))")
            page.add_style_tag(content=css)
            # evaluate is DevTools execution, not an authored script CSP bypass.
            page.evaluate((RUNTIME / 'runtime.js').read_text())
            page.evaluate('''({document,pageId,base}) => {
                window.__publishErrors=[];
                window.__publishInstance=LeafLoomStudio.mount(window.document.querySelector('#studio-root'),document,
                  {mode:'static',alreadyResolved:true,pageId,assetBase:base,onMessage:m=>{if(m.type==='studio-error')__publishErrors.push(m.message)}});
            }''', {'document': item['_document'], 'pageId': item['page_id'], 'base': ORIGIN + '/'})
            page.evaluate('''async () => {
                const ready=async()=>{await document.fonts.ready;
                  await Promise.all([...document.images].map(async image=>{
                    if(!image.complete) await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(Error('Image failed to load'))});
                    if(!image.naturalWidth) throw Error('Image failed to load');
                    if(image.decode) await image.decode();
                  }));
                  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
                };
                await Promise.race([ready(),new Promise((_,reject)=>setTimeout(()=>reject(Error('Fonts/images did not become ready within 15 seconds')),15000))]);
                for(const font of document.fonts) if(font.status==='error') throw Error('Font failed to load');
                if(window.__publishErrors.length) throw Error(window.__publishErrors.join('; '));
            }''')
            page.evaluate('async()=>{if(window.__publishInstance.readyForStatic) await window.__publishInstance.readyForStatic({timeoutMs:15000,maxResources:512})}')
            item['preflight'] = page.evaluate('async()=>window.__publishInstance.preflight ? await window.__publishInstance.preflight() : {issues:[],limitations:[]}')
            if blocked or failed or page.evaluate('window.__blockedResources.length'):
                raise ValueError('A resource was blocked or missing. Import remote images/fonts as project assets before publishing.')
            if page.locator('iframe,.studio-missing').count():
                raise ValueError('Embedded HTML frames or missing references cannot be published statically; convert them to native layers first.')
            if format == 'png':
                return page.screenshot(type='png', animations='disabled', clip={'x': 0, 'y': 0, 'width': width, 'height': height}, timeout=15000)
            page.emulate_media(media='screen')
            return page.pdf(width=f'{width}px', height=f'{height}px', print_background=True,
                            prefer_css_page_size=True, margin={'top':'0','right':'0','bottom':'0','left':'0'})
        finally:
            browser.close()


class DesignPublisher:
    def __init__(self, workspace):
        self.workspace = workspace
        self.config, self.files = workspace.config, workspace.files
        self.jobs = {}
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='design-publish')

    def _snapshot(self, body):
        value = self.workspace.documents.read(body['directory'])
        if body.get('expected_revision') != value['revision']:
            raise ConflictError('Design revision changed; refresh before publishing')
        items, pixels = plan(value['document'], body.get('page_ids'), body.get('variant_ids'), body.get('scale', 1), body.get('format', 'png'))
        return value, items, pixels

    def preflight(self, body):
        _, items, pixels = self._snapshot(body)
        available = self._native(body) or renderer_available(body.get('format', 'png'))
        return {'ok': available, 'renderer_available': available, 'total': len(items), 'total_pixels': pixels,
                'items': [self._item(item) for item in items], 'warnings': list(dict.fromkeys(warning for item in items for warning in item['warnings'])) + ([] if available else [SETUP])}

    @staticmethod
    def _native(body):
        return body.get('renderer') == 'native' or body.get('engine') == 'desktop'

    @staticmethod
    def _item(item):
        return {key: value for key, value in item.items() if not key.startswith('_')}

    def start(self, body):
        with self.lock, self.files.lock:
            value, items, _ = self._snapshot(body)
            if not self._native(body) and not renderer_available(body.get('format', 'png')):
                raise ValueError(SETUP)
            if sum(job['status'] in ('queued', 'running') for job in self.jobs.values()) >= 4:
                raise ValueError('Four publication jobs are already queued; wait for one to finish')
            if len(self.jobs) >= 32:
                raise ValueError('Publication job limit reached; restart the service to start a new session')
            if len(value['document'].get('assets', {})) > 2000:
                raise ValueError('Publish projects with at most 2000 registered assets')
            assets, size = {}, 0
            # Explicit registry only, never broad project-tree or URL reads.
            for asset in value['document'].get('assets', {}).values():
                if not asset.get('path'):
                    continue
                name = relative(asset['path'])
                path = self.config.path_for(body['directory'] + '/' + name)
                if not path.is_file():
                    continue  # Referenced missing resources fail their own item.
                size += path.stat().st_size
                if size > MAX_ASSETS:
                    raise ValueError('Registered project assets exceed the 128 MiB publication limit')
                with path.open('rb') as stream:
                    data = stream.read(MAX_ASSETS + 1)
                if len(data) > MAX_ASSETS or sum(len(data) for data, _ in assets.values()) + len(data) > MAX_ASSETS:
                    raise ValueError('Registered project assets exceed the 128 MiB publication limit')
                validate_static_media(data, name)
                if name.lower().endswith(('.svg', '.css')):
                    validate_inline_media(data.decode('utf-8', errors='replace'), 'svg' if name.lower().endswith('.svg') else 'css')
                assets[name] = (data, mimetypes.guess_type(name)[0] or 'application/octet-stream')
            snapshot_size = sum(len(json.dumps(item['_document'], ensure_ascii=False).encode()) for item in items)
            if sum(job.get('_snapshot_bytes', 0) for job in self.jobs.values()) + snapshot_size > 64 * 1024 * 1024:
                raise ValueError('Publication session document limit reached; restart the service to release old snapshots')
            retained = sum(sum(len(data) for data, _ in job['_assets'].values()) for job in self.jobs.values())
            if retained + size > 256 * 1024 * 1024:
                raise ValueError('Publication session asset limit reached; restart the service to release old snapshots')
            job_id = uuid.uuid4().hex
            job = {'job_id':job_id,'status':'queued','items':items,'completed':0,'total':len(items),
                   'format':body.get('format','png'),'revision':value['revision'], '_root':str(self.config.root),
                   '_scale':body.get('scale',1),'_assets':assets,'_outputs':{}, '_native': self._native(body), '_snapshot_bytes':snapshot_size, '_last_progress':time.monotonic(), '_native_claimed':False}
            self.jobs[job_id] = job
            if not job['_native']:
                self.pool.submit(self._run, job_id)
            return self.get(job_id)

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job['_root'] != str(self.config.root):
                raise ValueError('Publication job not found in this connected folder')
            if job['_native'] and job['status'] in ('queued','running') and time.monotonic()-job['_last_progress']>180:
                for item in job['items']:
                    if item['status'] in ('queued','running'):
                        item['status']='failed'; item['error']='Desktop renderer stopped responding; retry this frozen publication'
                self._assemble(job)
            return {**{key:copy.deepcopy(value) for key,value in job.items() if not key.startswith('_') and key!='items'},
                    'items':[self._item(item) for item in job['items']]}

    def retry(self, job_id):
        with self.lock:
            self.get(job_id)
            job = self.jobs[job_id]
            if job['status'] in ('running','queued') and not job['_native']:
                raise ConflictError('Publication is still running')
            failed = [item for item in job['items'] if item['status']=='failed' or job['_native'] and item['status'] in ('queued','running')]
            if not failed:
                if job['status']=='failed' and job['completed']:
                    self._assemble(job)
                    return self.get(job_id)
                raise ValueError('There are no failed items to retry')
            for item in failed:
                item['status']='queued'; item.pop('error',None)
            job['_native_claimed']=False; job['_last_progress']=time.monotonic()
            job['status']='queued'; job.pop('error',None); job.pop('url',None)
            if not job['_native']:
                self.pool.submit(self._run,job_id)
            return self.get(job_id)

    def download(self, job_id):
        with self.lock:
            self.get(job_id)
            job = self.jobs[job_id]
            if job['status'] not in ('completed','partial') or not job.get('_path'):
                raise ValueError('Publication download is not ready')
            return job['_path'], ('application/pdf' if job['format']=='pdf' else 'application/zip'), 'publication.'+('pdf' if job['format']=='pdf' else 'zip')

    def native_manifest(self, job_id):
        with self.lock:
            self.get(job_id)
            job = self.jobs[job_id]
            if not job['_native'] or job['status'] not in ('queued', 'running'):
                raise ConflictError('Native publication is not pending')
            if job['_native_claimed']:
                raise ConflictError('A desktop renderer already claimed this publication')
            job['_native_claimed']=True; job['_last_progress']=time.monotonic()
            job['status'] = 'running'
            return {'job_id':job_id, 'format':job['format'], 'scale':job['_scale'],
                    'pages':[{'id':i['id'],'page_id':i['page_id'],'variant_id':i['variant_id'],'width':i['width'],'height':i['height'],
                              'document':copy.deepcopy(i['_document'])} for i in job['items'] if i['status']=='queued'],
                    'resources':[{'path':path,'mime':mime,'data_base64':base64.b64encode(data).decode()} for path,(data,mime) in job['_assets'].items()],
                    'runtime_js':(RUNTIME/'runtime.js').read_text(), 'runtime_css':(RUNTIME/'runtime.css').read_text()}

    def native_failure(self, job_id, error):
        with self.lock:
            self.get(job_id)
            job = self.jobs[job_id]
            if not job['_native']:
                raise ValueError('This is not a desktop publication')
            if job['status'] not in ('queued','running'):
                return self.get(job_id)
            for item in job['items']:
                if item['status'] in ('queued','running'):
                    item['status']='failed'; item['error']=str(error or 'Desktop publication stopped')[:1000]
            self._assemble(job)
            return self.get(job_id)

    def native_result(self, job_id, body):
        with self.lock:
            self.get(job_id)
            job = self.jobs[job_id]
            if not job['_native'] or job['status'] not in ('queued','running'):
                raise ConflictError('Native publication is not pending')
            item = next((item for item in job['items'] if item['id']==body.get('item_id')),None)
            if item is None or item['status'] not in ('queued','running'):
                raise ConflictError('Native publication item is not pending')
            job['_last_progress']=time.monotonic()
            report = body.get('preflight')
            if report is not None:
                if not isinstance(report, dict) or len(json.dumps(report).encode()) > 256 * 1024:
                    raise ValueError('Invalid or oversized publication preflight report')
                item['preflight'] = copy.deepcopy(report)
            if body.get('error'):
                item['error']=str(body['error'])[:1000]; item['status']='failed'
            else:
                encoded=body.get('data_base64')
                if not isinstance(encoded,str) or len(encoded)>96*1024*1024:
                    raise ValueError('Invalid or oversized publication result')
                try:
                    data=base64.b64decode(encoded,validate=True)
                except Exception as error:
                    raise ValueError('Invalid publication encoding') from error
                self._check_output(job, item['id'], data)
                if job['format']=='png':
                    if len(data)<24 or not data.startswith(b'\x89PNG\r\n\x1a\n') or data[12:16]!=b'IHDR':
                        raise ValueError('Expected a PNG publication result')
                    width,height=struct.unpack('>II',data[16:24])
                    if (width,height)!=(math.ceil(item['width']*job['_scale']),math.ceil(item['height']*job['_scale'])):
                        raise ValueError('PNG dimensions do not match the publication request')
                else:
                    from pypdf import PdfReader
                    if not data.startswith(b'%PDF-'):
                        raise ValueError('Expected a PDF publication result')
                    reader=PdfReader(io.BytesIO(data))
                    if len(reader.pages)!=1:
                        raise ValueError('Expected exactly one PDF page per publication item')
                    box=reader.pages[0].mediabox
                    if abs(float(box.width)-item['width']*.75)>2 or abs(float(box.height)-item['height']*.75)>2:
                        raise ValueError('PDF dimensions do not match the publication request')
                job['_outputs'][item['id']]=data; item['status']='completed'
            job['completed']=sum(i['status']=='completed' for i in job['items'])
            finished=all(i['status'] in ('completed','failed') for i in job['items'])
        if finished:
            self._assemble(job)
        return self.get(job_id)

    def _check_output(self, job, item_id, data):
        """Called under self.lock by both renderers before retaining bytes."""
        if not isinstance(data, bytes) or not data or len(data) > MAX_ITEM_OUTPUT:
            raise ValueError('Rendered page exceeds the 32 MiB publication limit')
        previous = len(job['_outputs'].get(item_id, b''))
        size = sum(len(value) for value in job['_outputs'].values()) - previous + len(data)
        if size > MAX_JOB_OUTPUT:
            raise ValueError('Publication results exceed the 256 MiB batch limit')
        retained = sum(len(value) for entry in self.jobs.values() for value in entry['_outputs'].values())
        if retained - previous + len(data) > MAX_SESSION_OUTPUT:
            raise ValueError('Publication session output limit reached; restart the service to release old results')

    def _run(self, job_id):
        job = self.jobs[job_id]
        with self.lock:
            job['status']='running'
        for item in job['items']:
            if item['status']=='completed':
                continue
            with self.lock:
                item['status']='running'
            try:
                if str(self.config.root) != job['_root']:
                    raise ConflictError('Connected folder changed; publication stopped')
                data = render_item(item,job['_assets'],job['format'],job['_scale'])
                with self.lock:
                    self._check_output(job, item['id'], data)
                    job['_outputs'][item['id']]=data
                    item['status']='completed'
            except Exception as error:
                with self.lock:
                    item['status']='failed'; item['error']=str(error)[:1000]
            with self.lock:
                job['completed']=sum(i['status']=='completed' for i in job['items'])
        self._assemble(job)

    def _assemble(self, job):
        job_id = job['job_id']
        try:
            if job['completed']:
                output = io.BytesIO()
                if job['format']=='pdf':
                    from pypdf import PdfReader, PdfWriter
                    writer=PdfWriter()
                    for item in job['items']:
                        if item['id'] in job['_outputs']:
                            for page in PdfReader(io.BytesIO(job['_outputs'][item['id']])).pages:
                                writer.add_page(page)
                    writer.write(output)
                else:
                    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                        for item in job['items']:
                            if item['id'] in job['_outputs']:
                                archive.writestr(f"{int(item['id']):03d}.png",job['_outputs'][item['id']])
                        archive.writestr('manifest.json',json.dumps({'revision':job['revision'],'items':[self._item(item) for item in job['items']]},ensure_ascii=False))
                with self.config.lock, self.files.lock:
                    if str(self.config.root) != job['_root']:
                        raise ConflictError('Connected folder changed; publication stopped')
                    path=self.files.state_path('design-studio','publications',job_id+'.'+('pdf' if job['format']=='pdf' else 'zip'))
                    path.parent.mkdir(parents=True,exist_ok=True)
                    atomic_write(path,output.getvalue())
                with self.lock:
                    job['_path']=path
                    job['url']=f'/api/design/publish/{job_id}/download?root='+quote(job['_root'],safe='')
            with self.lock:
                job['status']='completed' if job['completed']==job['total'] else 'partial' if job['completed'] else 'failed'
        except Exception as error:
            with self.lock:
                job['status']='failed'; job['error']=str(error)[:1000]
