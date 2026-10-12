"""Scoped lexical/wiki/dense retrieval and immutable incremental index generations."""
from __future__ import annotations
from contextlib import closing
import datetime as dt, json, logging, math, os, re, shutil, sqlite3, threading, time, uuid
from collections import Counter, defaultdict
from pathlib import Path
import frontmatter
from vault_rag.local_state import atomic_write,digest,under
from vault_rag.catalog import tokens,list_value,LINK_RE
from vault_rag.service import _effective_note_type,_metadata_match
from vault_rag.verification_rank import verification_tier,trust_label,UNVERIFIED_EXCERPT_PREFIX

log=logging.getLogger(__name__)

def chunks(entries,model=None):
    from llama_index.core import Document
    from vault_rag.chunking import documents_to_nodes
    from vault_rag.metadata_sanitize import sanitize_metadata_for_vector_store
    docs=[Document(text=e['body'],metadata=sanitize_metadata_for_vector_store({**e['metadata'],'file_path':e['path'],'file_name':Path(e['path']).name})) for e in entries]
    out=[]
    for n in documents_to_nodes(docs):
        text=n.get_content(metadata_mode='none')
        # Bound long sections without losing text. Short existing sections retain IDs.
        pieces=[text]
        if len(text)>=1500 and model is not None and hasattr(model,'load'):
            model.load();offsets=model.model.tokenizer(text,add_special_tokens=False,return_offsets_mapping=True)['offset_mapping']
            if len(offsets)>1536:
                pieces=[text[0 if i==0 else offsets[i][0]:len(text) if i+1536>=len(offsets) else offsets[i+1535][1]] for i in range(0,len(offsets),1408)]
        elif len(text)>=5000:pieces=[text[i:i+4000] for i in range(0,len(text),3600)]
        for piece in pieces:out.append({'id':n.node_id if len(pieces)==1 else digest(str(n.metadata['file_path'])+'\n'+piece),'text':piece,'metadata':dict(n.metadata)})
    return out

class Knowledge:
    def __init__(self,config,catalog,model):
        self.config=config;self.catalog=catalog;self.model=model;self.snapshot={'nodes':[],'docs':[]};self.lock=threading.RLock();self.build_lock=threading.Lock();self.progress={'state':'等待关联目录'};self.last_signature=None;self.last_error=None;self.query_ms=None;self.live_chunks={}
    def eligible_entries(self):
        return [e for e in self.catalog.entries.values() if self.config.eligible(e['path'],e['metadata'])]
    def signature(self,entries):
        policy={k:self.config.data.get(k) for k in ('root','include_roots','exclude_roots','rules_roots','wiki_roots','estimation_roots')}
        wikis=[(e['path'],e['sha256']) for e in self.catalog.entries.values() if self.config.role(e['path'])=='wiki']
        return digest(json.dumps([policy,[(e['path'],e['sha256']) for e in entries],wikis,self.model.fingerprint,3],sort_keys=True,default=str))
    def load(self):
        root=self.config.root;index=root/'.vault-rag';pointer=index/'current.json'
        if pointer.is_file():
            current=json.loads(pointer.read_text());generation=index/'generations'/current['generation']
            status=json.loads((generation/'status.json').read_text());nodes=[json.loads(x) for x in (generation/'nodes.jsonl').read_text().splitlines() if x]
            docs=json.loads((generation/'documents.json').read_text())
            if status.get('vault_root')!=str(root):return
            self.snapshot={'nodes':nodes,'docs':docs,'status':status,'directory':str(generation),'root':str(root),'wikis':json.loads((generation/'wiki-sources.json').read_text()) if (generation/'wiki-sources.json').exists() else {}};self.last_signature=status.get('signature') if status.get('policy_revision')==self.config.data.get('revision') else None;self.progress={'state':'已同步','completed':len(nodes),'total':len(nodes)}
        elif (index/'nodes.jsonl').is_file() and (index/'status.json').is_file():
            status=json.loads((index/'status.json').read_text())
            if status.get('vault_root')==str(root):self.snapshot={'nodes':[json.loads(x) for x in (index/'nodes.jsonl').read_text().splitlines() if x],'docs':[],'status':status,'root':str(root)}
    def build(self,force=False):
        if not self.build_lock.acquire(blocking=False):return
        stage=None
        try:
            entries=self.eligible_entries();signature=self.signature(entries);root=self.config.root;policy_revision=self.config.data.get('revision')
            if not force and signature==self.last_signature:return
            self.progress={'state':'整理索引','completed':0,'total':0,'started_at':time.time()}
            nodes=chunks(entries,self.model if self.model.ready else None);vectors={};fingerprint=self.model.fingerprint
            if nodes and not self.model.ready:
                self.progress={'state':'等待模型准备','total':len(nodes),'completed':0};return
            index=root/'.vault-rag';index.mkdir(exist_ok=True)
            if nodes:
                cache=index/'embeddings.sqlite'
                with closing(sqlite3.connect(cache)) as db:
                    db.execute('CREATE TABLE IF NOT EXISTS embeddings(key TEXT PRIMARY KEY, vector TEXT)')
                    inputs=[];keys=[];missing=[]
                    for i,n in enumerate(nodes):
                        meta=n['metadata'];input_=str(meta.get('name',''))+'\n'+str(meta.get('header_path',''))+'\n'+n['text'];key=digest(str(fingerprint)+'\n'+input_);inputs.append(input_);keys.append(key)
                        hit=db.execute('SELECT vector FROM embeddings WHERE key=?',(key,)).fetchone()
                        if hit:vectors[n['id']]=json.loads(hit[0])
                        else:missing.append(i)
                    self.progress.update(state='更新向量',total=len(missing),completed=0,reused=len(nodes)-len(missing))
                    for offset in range(0,len(missing),4):
                        ids=missing[offset:offset+4];batch=self.model.encode([inputs[i] for i in ids])
                        for i,v in zip(ids,batch):
                            vectors[nodes[i]['id']]=v;db.execute('INSERT OR REPLACE INTO embeddings VALUES(?,?)',(keys[i],json.dumps(v)))
                        db.commit();self.progress['completed']=offset+len(ids)
            generation=uuid.uuid4().hex;stage=index/'generations'/generation;stage.mkdir(parents=True)
            if nodes:
                import lancedb
                db=lancedb.connect(str(stage/'lancedb'))
                db.create_table('vault_chunks',[{'id':n['id'],'file_path':n['metadata']['file_path'],'vector':vectors[n['id']]} for n in nodes],mode='overwrite')
                del db
            wiki_records={}
            for page in self.catalog.entries.values():
                if self.config.role(page['path'])!='wiki':continue
                old=self.snapshot.get('wikis',{}).get(page['path'],{})
                targets={link['target'] for link in self.catalog.links if link['source']==page['path']}
                for source in list_value(page['metadata'].get('sources'))+list_value(page['metadata'].get('relatedNotes')):targets.update(self.catalog.resolve(str(source).strip('[]'),page['path']))
                hashes={p:self.catalog.entries[p]['sha256'] for p in sorted(targets) if p.endswith('.md')}
                wiki_records[page['path']]={'page_hash':page['sha256'],'source_hashes':{**hashes,**old.get('source_hashes',{})}} if old.get('page_hash')==page['sha256'] else {'page_hash':page['sha256'],'source_hashes':hashes}
            atomic_write(stage/'wiki-sources.json',json.dumps(wiki_records,ensure_ascii=False).encode())
            status={'indexed_at':dt.datetime.now(dt.timezone.utc).isoformat(),'vault_root':str(root),'vault_content_folder':'RAG','vault_content_root':str(root/'RAG'),'indexed_roots':list(self.config.data['include_roots']),'num_files':len(entries),'num_chunks':len(nodes),'embedding_model':self.model.model_id,'embedding_fingerprint':fingerprint,'content_scope_version':2,'signature':signature,'generation':generation,'policy_revision':policy_revision,'lance_uri':str(stage/'lancedb'),'nodes_jsonl':str(stage/'nodes.jsonl'),'build_seconds':time.time()-self.progress['started_at']}
            atomic_write(stage/'nodes.jsonl',('\n'.join(json.dumps(n,ensure_ascii=False,default=str) for n in nodes)+'\n').encode())
            docs=[{k:e[k] for k in ('path','title','metadata','body','text','sha256')} for e in entries]
            atomic_write(stage/'documents.json',json.dumps(docs,ensure_ascii=False,default=str).encode());atomic_write(stage/'status.json',json.dumps(status,ensure_ascii=False,indent=2).encode())
            if self.config.data.get('revision')!=policy_revision or str(self.config.root)!=str(root):raise RuntimeError('索引范围已变化，本次构建未发布；将重新同步')
            with self.lock:
                atomic_write(index/'current.json',json.dumps({'generation':generation}).encode())
                self.snapshot={'nodes':nodes,'docs':docs,'status':status,'directory':str(stage),'root':str(root),'wikis':wiki_records}
                # Compatibility status at the old location. Old vector table is never reused.
                atomic_write(index/'status.json',json.dumps(status,ensure_ascii=False,indent=2).encode())
                atomic_write(index/'nodes.jsonl',(stage/'nodes.jsonl').read_bytes())
                self.last_signature=signature
                generations=sorted((index/'generations').iterdir(),key=lambda p:p.stat().st_mtime,reverse=True)
                for old in generations[2:]:
                    if old!=stage:shutil.rmtree(old,ignore_errors=True)
            self.last_error=None;self.progress={'state':'已同步','completed':len(nodes),'total':len(nodes),'finished_at':time.time(),'build_seconds':status['build_seconds']};self.write_catalog(entries)
        except Exception as e:
            self.last_error=str(e);self.progress['state']='同步失败';log.exception('Index sync failed')
            if stage and self.snapshot.get('directory')!=str(stage):shutil.rmtree(stage,ignore_errors=True)
        finally:self.build_lock.release()
    def write_catalog(self,entries):
        roots=self.config.data['wiki_roots']
        if not roots or not entries:return
        target=self.config.path_for(roots[0]+'/_generated-index.md',writable=True)
        if target.exists() and 'managed_by: vault-rag' not in target.read_text():return
        target.parent.mkdir(parents=True,exist_ok=True)
        lines=['---','type: moc','rag_index: false','managed_by: vault-rag','---','','# 可检索知识目录','','本页由服务维护；主题总结在显式整理时更新。','']
        for e in entries:lines.append('- [['+e['path']+'|'+e['title'].replace('|',' ')+']]')
        text='\n'.join(lines)+'\n'
        if not target.exists() or target.read_text()!=text:atomic_write(target,text.encode())
    def allowed(self,node,*,domain=None,type_=None,rules=False):
        path=node['metadata'].get('file_path','')
        try:live_meta={**self.catalog.files.read(path)['metadata'],'file_path':path}
        except (OSError,ValueError):return False
        if not self.config.eligible(path,live_meta):return False
        role=self.config.role(path)
        if rules!=(role=='rules'):return False
        estimation=(domain or '').lower()=='estimation' or (type_ or '').lower() in ('estimation','estimation-index')
        is_estimation=role=='estimation' or 'estimation' in str(live_meta.get('domain','')).lower()
        if estimation!=is_estimation:return False
        return _metadata_match(live_meta,type_=type_,domain=domain)
    @staticmethod
    def lexical(query,nodes):
        query_tokens=Counter(tokens(query));docs=[Counter(tokens(' '.join([str(n['metadata'].get('name','')),str(n['metadata'].get('file_path','')),str(n['metadata'].get('role','')),str(n['metadata'].get('rule_id','')),n['text']]))) for n in nodes]
        if not query_tokens:return []
        lengths=[sum(d.values()) for d in docs];avg=sum(lengths)/max(1,len(docs));df=Counter(t for d in docs for t in d);scores=[]
        for n,d,length in zip(nodes,docs,lengths):
            score=0
            for token in query_tokens:
                tf=d[token]
                if tf:score+=math.log(1+(len(docs)-df[token]+.5)/(df[token]+.5))*tf*2.2/(tf+1.2*(.25+.75*length/max(1,avg)))
            name=str(n['metadata'].get('name','')).lower();stem=Path(n['metadata'].get('file_path','')).stem.lower()
            if query.lower().strip() in (name,stem,str(n['metadata'].get('id','')).lower(),str(n['metadata'].get('rule_id','')).lower()):score+=20
            if score>0:scores.append((n['id'],score))
        return sorted(scores,key=lambda x:-x[1])
    def wiki(self,query,eligible):
        names=set(n['metadata']['file_path'] for n in eligible);navigation=[];candidates=[];qt=set(tokens(query))
        for entry in self.catalog.entries.values():
            if self.config.role(entry['path'])!='wiki' or not self.config.selected(entry['path']):continue
            if not qt.intersection(tokens(entry['title']+' '+entry['body'])):continue
            targets=[l['target'] for l in self.catalog.links if l['source']==entry['path']]
            for target in list_value(entry['metadata'].get('sources'))+list_value(entry['metadata'].get('relatedNotes')):targets.extend(self.catalog.resolve(str(target).strip('[]'),entry['path']))
            targets=sorted(set(targets))
            if entry['metadata'].get('managed_by')=='vault-rag':
                targets=[p for p in targets if qt.intersection(tokens(self.catalog.entries.get(p,{}).get('title','')+' '+p))]
            inside=[p for p in targets if p in names]
            if not inside:continue
            hashes=entry['metadata'].get('source_hashes',{}) or self.snapshot.get('wikis',{}).get(entry['path'],{}).get('source_hashes',{});stale=any(self.catalog.entries.get(p,{}).get('sha256')!=hash_ for p,hash_ in hashes.items())
            navigation.append({'file_path':entry['path'],'title':entry['title'],'sources':inside,'stale':stale,'excerpt':entry['body'][:500] if not stale and all(p in names for p in targets) else ''})
            candidates.extend(n['id'] for n in eligible if n['metadata']['file_path'] in inside)
        return navigation[:5],list(dict.fromkeys(candidates))
    def retrieval_nodes(self,snap):
        """Serve current lexical evidence while dense generations build or are unavailable."""
        groups=defaultdict(list)
        for node in snap.get('nodes',[]):groups[node['metadata']['file_path']].append(node)
        versions={e['path']:e['sha256'] for e in snap.get('docs',[])}
        nodes=[];live={};pending=set()
        for path in sorted(set(groups)|set(self.catalog.entries)):
            if not self.config.selected(path) or Path(path).suffix.lower() not in ('.md','.txt'):continue
            try:read=self.catalog.files.read(path)
            except (OSError,ValueError,UnicodeDecodeError):continue
            if not self.config.eligible(path,read['metadata']):continue
            live[path]=read
            if versions.get(path)==read['etag'] and groups[path]:nodes.extend(groups[path]);continue
            pending.add(path)
            post=frontmatter.loads(read['text']) if path.lower().endswith('.md') else None
            entry={'path':path,'body':post.content if post else read['text'],'metadata':read['metadata']}
            for node in chunks([entry]):
                node['id']+='-live-'+read['etag'][:16]
                nodes.append(node);self.live_chunks[node['id']]={'node':node,'revision':read['etag'],'root':str(self.config.root)}
        while len(self.live_chunks)>1000:self.live_chunks.pop(next(iter(self.live_chunks)))
        return nodes,live,pending

    def search(self,query,top_k=3,type_=None,domain=None,mode='hybrid',rules=False,compact=True):
        with self.lock:
            return self._search(query,top_k,type_,domain,mode,rules,compact)
    def _search(self,query,top_k=3,type_=None,domain=None,mode='hybrid',rules=False,compact=True):
        if mode not in ('hybrid','wiki','rag','keyword'):raise ValueError('检索模式无效')
        query=query.strip()
        if not query:return {'ok':True,'no_relevant_hit':True,'results':[],'navigation':[]}
        if len(query)>4096:raise ValueError('查询过长')
        start=time.perf_counter();policy_revision=self.config.data.get('revision');snap=self.snapshot
        if snap.get('root')!=str(self.config.root):
            if getattr(self.catalog,'root',None)!=str(self.config.root):raise ValueError('该目录目录表尚未准备，请等待同步')
            snap={'nodes':[],'docs':[]}
        allnodes,live,pending=self.retrieval_nodes(snap);allowed={}
        for path,read in live.items():
            meta={**read['metadata'],'file_path':path};role=self.config.role(path)
            estimation=(domain or '').lower()=='estimation' or (type_ or '').lower() in ('estimation','estimation-index')
            is_estimation=role=='estimation' or 'estimation' in str(meta.get('domain','')).lower()
            allowed[path]=(rules==(role=='rules') and estimation==is_estimation and _metadata_match(meta,type_=type_,domain=domain))
        nodes=[n for n in allnodes if allowed[n['metadata']['file_path']]]
        lookup={n['id']:n for n in nodes}
        lexical=self.lexical(query,nodes);nav,wiki=self.wiki(query,nodes) if mode in ('wiki','hybrid') and not rules else ([],[])
        rankings=[];channels=defaultdict(list);vector_scores={};degraded=None
        if mode in ('hybrid','rag','keyword'):
            rankings.append([key for key,_ in lexical[:100]])
            for key,_ in lexical:channels[key].append('keyword')
        if mode in ('hybrid','wiki'):
            rankings.append(wiki)
            for key in wiki:channels[key].append('wiki')
        if mode in ('hybrid','rag') and nodes:
            if snap.get('status',{}).get('embedding_fingerprint')!=self.model.fingerprint or not self.model.ready:degraded='向量模型或索引尚未准备，使用关键词与 Wiki'
            else:
                try:
                    import lancedb
                    vector=self.model.encode([query])[0];db=lancedb.connect(str(Path(snap['directory'])/'lancedb'));table=db.open_table('vault_chunks')
                    paths=sorted({n['metadata']['file_path'] for n in nodes});where='file_path IN ('+','.join("'"+p.replace("'","''")+"'" for p in paths)+')'
                    hits=table.search(vector).distance_type('cosine').where(where,prefilter=True).limit(min(80,len(nodes))).to_list();vkeys=[]
                    for hit in hits:
                        key=hit['id'];sim=1-float(hit['_distance']);vector_scores[key]=sim
                        if key in lookup and sim>=0.45:vkeys.append(key);channels[key].append('vector')
                    rankings.append(vkeys)
                except Exception as e:degraded='向量暂不可用：'+str(e);log.exception('Dense search degraded')
        fused=defaultdict(float)
        for ranking in rankings:
            for i,key in enumerate(ranking):fused[key]+=1/(60+i+1)
        ordered=sorted(fused,key=lambda key:-fused[key]);preferred=[key for key in ordered if verification_tier(live[lookup[key]['metadata']['file_path']]['metadata'])>=2];backfill=[key for key in ordered if key not in preferred];out=[];seen=set()
        for key in preferred+backfill:
            n=lookup[key];path=n['metadata']['file_path'];meta={**live[path]['metadata'],'file_path':path,'file_name':Path(path).name,'header_path':n['metadata'].get('header_path','')}
            if path in seen:continue
            seen.add(path);tier=verification_tier(meta);excerpt=n['text'];truncated=len(excerpt)>900
            if tier<2:excerpt=UNVERIFIED_EXCERPT_PREFIX+excerpt
            row={'chunk_id':key,'file_path':path,'note_type':_effective_note_type(meta),'trust':trust_label(tier),'excerpt':excerpt[:900]+('…' if truncated else ''),'excerpt_truncated':truncated,'channels':channels[key],'revision':live[path]['etag'],'index_pending':path in pending,'metadata':{k:v for k,v in meta.items() if k in ('domain','rule_id','techStack','verified_date','verification_scope','common_assumption','role') and v}}
            if not compact:row.update(score=fused[key],vector_score=vector_scores.get(key),ranking='preferred' if tier>=2 else 'backfill',verified_status=meta.get('verified_status',''),metadata=meta)
            out.append(row)
            if len(out)>=max(1,min(int(top_k),50)):break
        if policy_revision!=self.config.data.get('revision'):raise ValueError('检索期间目录范围已变化，请重新检索')
        self.query_ms=(time.perf_counter()-start)*1000
        return {'ok':True,'no_relevant_hit':not out,'results':out,'navigation':nav,'mode':mode,'degraded':degraded,'query_ms':self.query_ms}
    def get_chunk(self,key):
        with self.lock:
            cached=self.live_chunks.get(key)
            if cached and cached['root']==str(self.config.root):
                node=cached['node'];revision=cached['revision']
            else:
                if self.snapshot.get('root')!=str(self.config.root):return {'ok':False,'error':'关联目录已变化，请重新检索'}
                node=next((n for n in self.snapshot.get('nodes',[]) if n['id']==key),None)
                if not node:return {'ok':False,'error':'片段不存在，请重新检索'}
                revision=next((d['sha256'] for d in self.snapshot.get('docs',[]) if d['path']==node['metadata']['file_path']),None)
            path=node['metadata']['file_path']
            try:read=self.catalog.files.read(path)
            except (OSError,ValueError):return {'ok':False,'error':'片段已不可读，请重新检索'}
            if not self.config.eligible(path,read['metadata']):return {'ok':False,'error':'片段已退出检索范围，请重新检索'}
            if revision!=read['etag']:return {'ok':False,'error':'来源已经变化，请重新检索获取当前片段','revision_changed':True}
            meta={**read['metadata'],'file_path':path,'file_name':Path(path).name,'header_path':node['metadata'].get('header_path','')}
            return {'ok':True,'chunk_id':key,'file_path':path,'metadata':meta,'text':node['text'],'revision':read['etag']}
    def get_note(self,path):
        found=self.catalog.resolve(path)
        if len(found)!=1:return {'ok':False,'error':'笔记不存在或名称不唯一','candidates':found}
        path=found[0]
        if not self.config.eligible(path):return {'ok':False,'error':'该笔记未进入当前检索范围'}
        read=self.catalog.files.read(path)
        return {'ok':True,'file_path':path,'metadata':read['metadata'],'text':read['text'],'revision':read['etag']}
    def status(self):
        snap=self.snapshot;config=self.config.data
        return {**snap.get('status',{}),'ok':bool(config.get('root')),'configured':bool(config.get('root')),'vault_root':config.get('root'),'vault_content_root':str(Path(config['root'])/'RAG') if config.get('root') else None,'indexed_roots':config['include_roots'],'excluded_roots':config['exclude_roots'],'write_targets':config['write_targets'],'templates_folder':config['templates'],'daily_folder':config['daily_folder'],'homepage':config['homepage'],'rules_roots':config['rules_roots'],'wiki_roots':config['wiki_roots'],'estimation_roots':config['estimation_roots'],'model':self.model.status(),'sync':dict(self.progress),'last_error':self.last_error,'catalog_files':len(self.catalog.entries),'scope_matches_settings':bool(snap.get('status',{}).get('policy_revision')==config.get('revision') and snap.get('root')==config.get('root')),'last_query_ms':self.query_ms,'service_transport':'streamable-http'}

class Runtime:
    def __init__(self,config):
        from vault_rag.local_state import Files
        from vault_rag.catalog import Catalog
        from vault_rag.embedded_model import EmbeddedModel
        self.config=config;self.files=Files(config);self.catalog=Catalog(self.files);self.model=EmbeddedModel(config.directory);self.knowledge=Knowledge(config,self.catalog,self.model);self.event=threading.Event();self.stop_event=threading.Event();self.files.changed=self.event.set;self.thread=None;self.root=None
    def start(self):
        if self.thread and self.thread.is_alive():return
        self.thread=threading.Thread(target=self.loop,name='vault-sync',daemon=True);self.thread.start()
    def loop(self):
        while not self.stop_event.is_set():
            try:
                root=str(self.config.root)
                if root!=self.root:
                    self.root=root;self.catalog.entries={};self.knowledge.snapshot={'nodes':[],'docs':[]};self.knowledge.last_signature=None;self.knowledge.load()
                self.catalog.scan();self.knowledge.build()
                if self.model.ready and not getattr(self.model,'warmed',True):
                    self.progress_before_warmup=dict(self.knowledge.progress);self.knowledge.progress={'state':'正在预热检索'}
                    self.model.warmup();self.knowledge.progress=self.progress_before_warmup
            except ValueError as e:self.knowledge.progress={'state':str(e)}
            except Exception as e:self.knowledge.last_error=str(e);log.exception('File scan failed')
            self.event.wait(2);self.event.clear()
    def stop(self):self.stop_event.set();self.event.set()
