"""Metadata-only asset retrieval. Original files are accessed only for details/preview."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import threading
import time

from vault_rag.attachment_policy import extensions_for
from vault_rag.catalog import tokens
from vault_rag.local_state import atomic_write, digest, ConflictError

_PIPELINES = {'standard': 'builtin', 'built-in': 'builtin', 'builtin': 'builtin',
              'lightweight': 'urp', 'urp': 'urp', 'hd': 'hdrp', 'hdrp': 'hdrp'}


def signature(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


class AssetSearch:
    def __init__(self, files):
        self.files = files
        self.lock = threading.RLock()
        self.building = set()
        self.stopped = threading.Event()
        self.threads = []
        self.states = {}
        self.scope_revisions = {}
        self.refresh_event = threading.Event()
        self.refresh_thread = threading.Thread(target=self._refresh_loop,name='asset-scope',daemon=True)
        self.refresh_thread.start()

    def directory(self):
        return self.files.runtime.files.state_path('asset-search')

    def scope(self):
        root = str(self.files.config.root)
        groups = self.files.attachment_groups
        scope = groups.search_scope(root) if groups else {
            'group_ids':[],'groups':[],'scope_revision':signature([]),
            'scope_state':'scope_not_configured','conflict_group_ids':[]}
        scope = {**scope, 'scope_revision': signature([scope['scope_revision'], extensions_for(self.files.runtime.files)])}
        if str(self.files.config.root)!=root:
            raise ConflictError('Workspace changed while reading asset scope')
        if self.scope_revisions.get(root)!=scope['scope_revision']:
            # Drop the old full-library projection on upgrade, and stale projections on scope changes.
            with self.files.config.lock:
                if str(self.files.config.root)!=root:
                    raise ConflictError('Workspace changed while refreshing asset scope')
                for name in ('current.json','catalog.json'):
                    path = self.files.runtime.files.state_path('asset-search',name)
                    if path.exists():
                        try:value = json.loads(path.read_text())
                        except (ValueError,UnicodeError):value = {}
                        if value.get('scope_version')!=1 or value.get('scope_revision')!=scope['scope_revision']:
                            path.unlink()
                self.scope_revisions[root]=scope['scope_revision']
                self.states[root]={'state':'not_built','completed':0,'total':0}
        return scope

    def refresh_scope(self):
        self.refresh_event.set()

    def _refresh_loop(self):
        while not self.stopped.is_set():
            self.refresh_event.wait()
            self.refresh_event.clear()
            if self.stopped.is_set():
                break
            try:
                self.scope()
                if self.settings()['enabled']:
                    self.schedule(self.snapshot())
            except Exception:
                pass  # Foreground queries report the current index/scope state.

    def _attachments(self, **filters):
        catalog = self.files.runtime.files.attachments
        rows, cursor = [], ''
        while True:
            page = catalog.listing(limit=200, cursor=cursor, **filters)
            rows.extend(page['items'])
            cursor = page.get('next_cursor') or page.get('cursor') or ''
            if not cursor:
                return rows

    def snapshot(self, request=None):
        f = self.files
        root, revision = str(f.config.root), f.notes.workspace_revision
        scope = self.scope()
        if not scope['group_ids'] or (request and request.group_id and request.group_id not in scope['group_ids']):
            return []
        members = {}
        for group_id in scope['group_ids']:
            for row in self._attachments(group_id=group_id):
                members[(row.get('storage_id','local'),row['path'])]=row
        rows = list(members.values())
        # Only identities visible in the current catalog may participate. No name joins.
        rows = [r for r in rows if r.get('state', 'ready') not in {'missing', 'excluded'}
                and r.get('source_enabled', True)]
        by_asset = {r['asset_id']: r for r in rows if r.get('asset_id')}
        documents, linked = [], set()
        library_source = f.asset_library.settings(root)['storage_id'] if f.asset_library else ''
        products = f.asset_library._items(root) if library_source and library_source in {r.get('storage_id') for r in rows} else []
        for product in products:
            available = [{**p,**by_asset[p['asset_id']]} for p in product['files'] if p.get('asset_id') in by_asset]
            if not available:
                continue
            linked.update(p.get('asset_id') for p in available)
            product = {**product,'files':available}
            official, personal = product['official'], product['personal']
            fields = {'title': product['title'], 'filename': ' '.join(p['name'] for p in available),
                      'path': ' '.join(p['path'] for p in available),
                      'official.categories': official.get('categories', []) + official.get('categories_zh', []),
                      'official.keywords': official.get('keywords', []) + official.get('keywords_zh', []),
                      'official.summary': official.get('summary_zh', ''),
                      'official.description': official.get('source_excerpt', ''),
                      'personal.category': personal.get('category', ''), 'personal.tags': personal.get('tags', []),
                      'personal.description': personal.get('description', '')}
            for index, row in enumerate(available):
                for key in ('description', 'tags', 'category'):
                    fields[f'file.{index}.{key}'] = row.get('personal_metadata', {}).get(key, row.get(key, ''))
            documents.append(self._document(product['id'], 'product' if product['kind']=='product' else 'package',
                fields, available, official.get('compatibility', {}),
                personal.get('description') or official.get('summary_zh', ''),
                'product_cover' if official.get('cover') else '', product))
        for row in rows:
            if row.get('asset_id') in linked:
                continue
            identity = row.get('asset_id') if row.get('storage_id','local')!='local' else signature(['local',row['path']])
            identity = identity or signature([row.get('storage_id','local'),row['path']])
            fields = {k: row.get(k, '') for k in ('name', 'path', 'description', 'tags', 'category')}
            documents.append(self._document('file:'+identity, 'file', fields, [row], {},
                row.get('description', ''), 'file_thumbnail' if row.get('mime', '').startswith('image/') else '', None))
        if str(f.config.root) != root or f.notes.workspace_revision != revision or self.scope()['scope_revision']!=scope['scope_revision']:
            raise ConflictError('Connected workspace changed during asset search')
        if request and any((request.source!='all',request.storage_id,request.group_id)):
            allowed = set()
            for group_id in ([request.group_id] if request.group_id else scope['group_ids']):
                allowed.update((r.get('storage_id','local'),r['path']) for r in self._attachments(
                    source=request.source,storage_id=request.storage_id,group_id=group_id))
            documents = [d for d in documents if any((r.get('storage_id','local'),r['path']) in allowed for r in d['files'])]
        if request and request.formats:
            formats = {v.lower().lstrip('.') for v in request.formats}
            documents = [d for d in documents if any(Path(r['name']).suffix.lower().lstrip('.') in formats for r in d['files'])]
        if request and request.pipeline:
            documents = [d for d in documents if request.pipeline in (d['pipelines'] or ['unknown'])]
        for document in documents:
            document['scope_revision']=scope['scope_revision']
        return documents

    def _document(self, key, kind, fields, rows, compatibility, summary, preview, product):
        fields = {k: ' '.join(map(str, v)) if isinstance(v, list) else str(v) for k,v in fields.items()}
        pipelines = sorted({_PIPELINES[v.lower()] for r in compatibility.get('render_pipelines', [])
                            for v in r.get('pipelines', []) if v.lower() in _PIPELINES})
        identities = [{k:r.get(k) for k in ('path','size','mtime','etag','content_generation','state')} for r in rows]
        revision = signature([fields, identities, compatibility, product.get('revision') if product else None])
        text = '\n'.join(k+': '+v for k,v in fields.items() if v)
        return dict(result_id=key, kind=kind, title=fields.get('title') or fields.get('name'), fields=fields,
                    files=rows, compatibility=compatibility, pipelines=pipelines, summary=summary,
                    preview=preview, revision=revision, text=text, text_hash=signature(text), product=product)

    def status(self):
        scope = self.scope()
        return {'enabled': self.settings()['enabled'], **scope, **self.states.get(str(self.files.config.root),
            {'state': 'not_built', 'completed': 0, 'total': 0})}

    def settings(self):
        path = self.directory() / 'settings.json'
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            return {'enabled': False, 'revision': 'initial'}

    def configure(self, enabled, revision, *, root=None):
        if type(enabled) is not bool:
            raise ValueError('Invalid asset index setting')
        with self.lock, self.files.config.lock:
            if root is not None and str(self.files.config.root)!=root:
                raise ConflictError('Connected folder changed')
            if revision != self.settings()['revision']:
                raise ConflictError('Asset search settings changed')
            value = {'enabled': enabled, 'revision': signature([enabled, time.time_ns()])}
            self.directory().mkdir(parents=True, exist_ok=True, mode=0o700)
            atomic_write(self.directory()/'settings.json', json.dumps(value).encode())
        if enabled:
            self.schedule(self.snapshot())
        return value

    def rebuild(self, root, revision):
        with self.lock, self.files.config.lock:
            if str(self.files.config.root)!=root or self.settings()['revision']!=revision:
                raise ConflictError('Asset search settings changed')
            if not self.settings()['enabled']:
                raise ValueError('Enable semantic asset indexing before rebuilding')
            if root in self.building:
                raise ConflictError('Wait for the current asset index batch to finish')
            self.files.runtime.files.state_path('asset-search','current.json').unlink(missing_ok=True)
            self.states[root]={'state':'not_built','completed':0,'total':0}
        self.schedule(self.snapshot())
        return self.status()

    def schedule(self, documents):
        scope = self.scope()
        if not scope['group_ids'] or not documents:
            return
        if any(d.get('scope_revision')!=scope['scope_revision'] for d in documents):
            self.refresh_scope()
            return
        model = self.files.runtime.model
        root = str(self.files.config.root)
        if not self.settings()['enabled'] or not model.ready or root in self.building or self.stopped.is_set():
            return
        entries = [{'id': d['result_id'], 'text': d['text'], 'hash': d['text_hash']} for d in documents]
        generation = signature([1,scope['scope_revision'],model.fingerprint,entries])
        directory = self.directory()
        manifest = directory/'current.json'
        try:
            if json.loads(manifest.read_text()).get('generation') == generation:
                self.states[root] = {'state':'ready', 'completed':len(entries), 'total':len(entries)}
                return
        except (FileNotFoundError, ValueError):
            pass
        revision = self.files.notes.workspace_revision
        settings_revision = self.settings()['revision']
        with self.lock:
            if root in self.building:
                return
            self.building.add(root)
        def build():
            try:
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                for offset in range(0, len(entries), 8):
                    if self.stopped.is_set() or str(self.files.config.root)!=root or self.files.notes.workspace_revision!=revision or self.settings()['revision']!=settings_revision or not self.settings()['enabled'] or self.scope()['scope_revision']!=scope['scope_revision']:
                        return
                    self.states[root] = {'state':'building','completed':offset,'total':len(entries)}
                    self.files.runtime.rag.request('asset_build', directory=str(directory), entries=entries[offset:offset+8],
                                                   fingerprint=model.fingerprint)
                latest = self.snapshot()
                if [(d['result_id'],d['text_hash']) for d in latest]!=[(d['id'],d['hash']) for d in entries]:
                    return
                with self.files.attachment_groups.lock, self.files.config.lock:
                    if (str(self.files.config.root)!=root or self.files.notes.workspace_revision!=revision or self.stopped.is_set()
                            or self.settings()['revision']!=settings_revision or self.scope()['scope_revision']!=scope['scope_revision']):
                        return
                    atomic_write(manifest, json.dumps({'scope_version':1,'scope_revision':scope['scope_revision'],'generation':generation,'fingerprint':model.fingerprint,'entries':entries}, ensure_ascii=False).encode())
                    self.states[root] = {'state':'ready','completed':len(entries),'total':len(entries)}
            except Exception:
                self.states[root] = {'state':'failed','completed':0,'total':len(entries)}
            finally:
                with self.lock:
                    self.building.discard(root)
                if str(self.files.config.root)==root and self.scope()['scope_revision']!=scope['scope_revision']:
                    self.refresh_scope()
        thread = threading.Thread(target=build, name='asset-index', daemon=True)
        self.threads = [t for t in self.threads if t.is_alive()]
        self.threads.append(thread)
        thread.start()

    def search(self, request):
        root, revision = str(self.files.config.root), self.files.notes.workspace_revision
        scope = self.scope()
        documents = self.snapshot(request)
        if not scope['group_ids']:
            return {'results':[],'mode':'keyword','degraded_reason':scope['scope_state'],'scope':scope,'index':self.status()}
        # Search metadata is a disposable projection, independent of note RAG.
        complete = self.snapshot() if any((request.source!='all',request.storage_id,request.group_id,request.formats,request.pipeline)) else documents
        with self.files.attachment_groups.lock, self.files.config.lock:
            if (str(self.files.config.root)!=root or self.files.notes.workspace_revision!=revision
                    or self.scope()['scope_revision']!=scope['scope_revision']):
                raise ConflictError('Workspace or asset search scope changed before publishing metadata')
            directory = self.directory()
            directory.mkdir(parents=True,exist_ok=True,mode=0o700)
            atomic_write(self.files.runtime.files.state_path('asset-search','catalog.json'),
                         json.dumps({'scope_version':1,'scope_revision':scope['scope_revision'],'revision':signature(complete),'documents':complete},ensure_ascii=False).encode())
        # Build the complete authorized corpus, never a filtered generation.
        self.schedule(complete)
        query = request.query.strip().casefold()
        if not query:
            raise ValueError('Enter an asset search query')
        qt = set(tokens(query))
        matches, exact, scores = {}, set(), {}
        for d in documents:
            key = d['result_id']
            if query in {d['title'].casefold(), *(r['name'].casefold() for r in d['files'])}:
                exact.add(key)
            fields = [k for k,v in d['fields'].items() if qt.intersection(tokens(v)) or query in v.casefold()]
            coverage = len(qt.intersection(tokens(d['text']))) / max(1,len(qt))
            score = coverage*10 + sum(3 if k in {'title','name','filename'} else 1 for k in fields)
            if fields:
                scores[key] = score
                matches[key] = fields
        lexical = sorted(scores, key=lambda k:(k not in exact, -scores[k], k))[:50]
        rankings, degraded = [lexical], None
        if request.mode == 'hybrid':
            model = self.files.runtime.model
            if not self.settings()['enabled']:
                degraded = 'semantic_index_disabled'
            elif not model.ready:
                degraded = 'model_not_prepared'
            else:
                try:
                    manifest = json.loads((self.directory()/'current.json').read_text())
                    if manifest.get('scope_version')!=1 or manifest.get('scope_revision')!=scope['scope_revision'] or manifest['fingerprint'] != model.fingerprint:
                        raise ValueError('stale_model')
                    hits = self.files.runtime.rag.request('asset_dense', timeout=3, directory=str(self.directory()),
                        query=request.query, fingerprint=model.fingerprint,
                        entries=[{'id':d['result_id'],'hash':d['text_hash']} for d in documents])
                    rankings.append([h['id'] for h in hits if h['similarity']>=0.45][:50])
                except FileNotFoundError:
                    degraded = 'semantic_index_building'
                except TimeoutError:
                    degraded = 'semantic_query_timeout'
                except Exception:
                    degraded = 'semantic_index_unavailable'
        fused = {}
        for ranking in rankings:
            for rank,key in enumerate(ranking,1):
                fused[key] = fused.get(key,0) + 1/(60+rank)
        by_id = {d['result_id']:d for d in documents}
        ordered = sorted(fused,key=lambda k:(k not in exact,-fused[k],k))[:request.limit]
        live = {d['result_id']:d['revision'] for d in self.snapshot(request)}
        if self.scope()['scope_revision']!=scope['scope_revision']:
            raise ConflictError('Asset search scope changed; search again')
        ordered = [key for key in ordered if live.get(key)==by_id[key]['revision']]
        return {'scope':scope,'results':[self.compact(by_id[k], matches.get(k,[]), 'semantic' if k not in matches else 'keyword') for k in ordered],
                'mode': 'keyword' if request.mode=='keyword' or degraded else 'hybrid',
                'degraded_reason':degraded,'index':self.status()}

    @staticmethod
    def compact(d, matches, channel):
        return {k:d[k] for k in ('result_id','revision','title','kind','compatibility','pipelines')} | {
            'summary':d['summary'][:600], 'matched_fields':matches, 'match_channel':channel,
            'file_count':len(d['files']), 'preview_kind':d['preview'] or 'unsupported',
            'metadata_state':'described' if d['summary'] else 'limited',
            'evidence':'recorded_metadata; compatibility is not an engine verification'}

    def details(self, result_id):
        for d in self.snapshot():
            if d['result_id'] == result_id:
                files = []
                for row in d['files']:
                    info = self.files._stat(row['path'], self.files.notes.workspace_revision)
                    files.append({**row, 'revision':info['revision'], 'selection':{'path':row['path']}})
                current = next((v for v in self.snapshot() if v['result_id']==result_id),None)
                if current is None or current['revision']!=d['revision']:
                    raise ConflictError('Asset search scope or details changed; search again')
                return {**self.compact(d, [], 'details'), 'fields':d['fields'], 'product':d['product'], 'files':files}
        raise FileNotFoundError('Asset result is no longer available')

    def preview(self, result_id, expected_revision):
        d = next((d for d in self.snapshot() if d['result_id']==result_id), None)
        if d is None:
            raise FileNotFoundError('Asset result is no longer available')
        if d['revision'] != expected_revision:
            raise ConflictError('Asset changed; retrieve its details again')
        if not d['preview']:
            return {'preview_kind':'unsupported','reason':'No recorded cover or supported image thumbnail'}
        if d['preview']=='product_cover':
            path = self.files.asset_library.cover(str(self.files.config.root),d['product']['product_id'])
        else:
            path = self.files.workspace.thumbnail(str(self.files.config.root), d['files'][0]['path'])
        data = path.read_bytes()
        # Never let a provider's oversized or malformed cover enter the MCP response.
        import io
        from PIL import Image
        with Image.open(io.BytesIO(data)) as picture:
            if picture.width*picture.height>32_000_000:
                raise ValueError('Preview exceeds pixel limit')
            picture.thumbnail((512,512))
            image = io.BytesIO()
            picture.convert('RGB').save(image,format='WEBP',quality=80)
        current = next((v for v in self.snapshot() if v['result_id']==result_id),None)
        if current is None or current['revision']!=expected_revision:
            raise ConflictError('Asset changed while preparing preview')
        return {'preview_kind':d['preview'], 'revision':d['revision'],
                '_image':base64.b64encode(image.getvalue()).decode('ascii')}

    def stop(self):
        self.stopped.set()
        self.refresh_event.set()
        self.refresh_thread.join(timeout=2)
        for thread in self.threads:
            thread.join(timeout=2)
