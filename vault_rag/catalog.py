"""Whole-vault file metadata, links, safe property queries and existing view adapters."""
from __future__ import annotations
from contextlib import closing
import datetime as dt, json, re, sqlite3, threading, posixpath, logging
from pathlib import Path, PurePosixPath
from collections import defaultdict
import frontmatter, yaml
from vault_rag.local_state import Files, LINK_RE, digest, under
from vault_rag.platform_support import path_key

def tokens(text):
    text=text.lower();words=re.findall(r'[a-z0-9_]+(?:[-/][a-z0-9_]+)*|[\u3040-\u30ff\u3400-\u9fff]+',text);out=[]
    for w in words:
        if re.search(r'[\u3040-\u30ff\u3400-\u9fff]',w):out.extend([w] if len(w)==1 else [w[i:i+2] for i in range(len(w)-1)])
        else:out.append(w)
    return out

def list_value(value):
    if value is None:return []
    return value if isinstance(value,list) else [value]

class Expr:
    """Small expression interpreter. Never evaluates Python or JavaScript."""
    lex=re.compile(r'\s*("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|!=|>=|<=|==|[=><!(),]|-?\d+(?:\.\d+)?|[^\s=><!(),]+)')
    def __init__(self,source,row):self.items=[m.group(1) for m in self.lex.finditer(source)];self.i=0;self.row=row
    def take(self):
        if self.i>=len(self.items):raise ValueError('查询表达式不完整')
        value=self.items[self.i];self.i+=1;return value
    def peek(self):return self.items[self.i] if self.i<len(self.items) else ''
    def field(self,key):
        value=self.row
        for part in key.split('.'):
            if part=='length' and isinstance(value,(list,str)):value=len(value)
            elif isinstance(value,dict):value=value.get(part)
            else:return None
        return value
    def atom(self):
        token=self.take()
        if token=='!':return not self.atom()
        if token=='(':
            value=self.expression()
            if self.take()!=')':raise ValueError('查询括号不匹配')
            return value
        if token.startswith(('"',"'")):return token[1:-1]
        if re.fullmatch(r'-?\d+(?:\.\d+)?',token):return float(token)
        if token.lower() in ('true','false','null'):return {'true':True,'false':False,'null':None}[token.lower()]
        if self.peek()=='(':
            self.take();args=[]
            if self.peek()!=')':
                while True:
                    args.append(self.expression())
                    if self.peek()!=',':break
                    self.take()
            if self.take()!=')':raise ValueError('函数括号不匹配')
            if token=='contains':return len(args)==2 and args[1] in (args[0] or [])
            if token=='length':return len(args[0] or [])
            if token=='date':return str(args[0])[:10]
            if token=='file.hasTag':return args[0].lstrip('#') in self.row.get('file',{}).get('tags',[])
            if token=='file.inFolder':return under(self.row.get('file',{}).get('path',''),str(args[0]))
            raise ValueError('暂不支持的查询函数：'+token)
        return self.field(token)
    def expression(self,minimum=0):
        value=self.atom();prec={'OR':1,'AND':2,'=':3,'==':3,'!=':3,'>':3,'<':3,'>=':3,'<=':3}
        while self.peek().upper() in prec and prec[self.peek().upper()]>=minimum:
            op=self.take().upper();right=self.expression(prec[op]+1)
            if op=='OR':value=bool(value) or bool(right)
            elif op=='AND':value=bool(value) and bool(right)
            elif op in ('=','=='):value=value==right
            elif op=='!=':value=value!=right
            else:
                try:value={'>':lambda:value>right,'<':lambda:value<right,'>=':lambda:value>=right,'<=':lambda:value<=right}[op]()
                except TypeError:value=False
        return value
    def run(self):
        value=self.expression()
        if self.i!=len(self.items):raise ValueError('暂不支持的查询表达式：'+''.join(self.items[self.i:]))
        return value

def columns(source):
    return [x.strip() for x in re.split(r',(?=(?:[^"\']*["\'][^"\']*["\'])*[^"\']*$)',source) if x.strip()]

class Catalog:
    def __init__(self,files:Files,*,lazy=False):
        self.files=files;self.entries={};self.lock=threading.RLock();self.links=[]
        self.version=0;self.root=None;self.resolver_indexes=None
        self.references={};self.reference_keys={};self.edges={};self.changed_paths=[]
        self.persist=True
        self.directories={''};self.directory_table={}
        self.lazy=lazy;self.metadata_ready=False;self.scanned_folders={};self.opened_folders=set()
        self.update_lock=threading.RLock()
        self.complete_namespace=False
        self.scopes_verified=False

    def _entry(self,root,p,old=None,force=False,stat_value=None,parse=True):
        rel=p.relative_to(root).as_posix();stat=stat_value or p.stat();stamp=(stat.st_mtime_ns,stat.st_size)
        if old and old['_stat']==stamp and not force:
            if not parse or old.get('_hydrated',True):return old
            from vault_rag.catalog_cache import content
            cached=content(root,rel,stamp)
            if cached is not None:return {**old,**cached,'_hydrated':True,'_parsed':True}
        meta={};text='';body='';sha=''
        # Assets stay in the filename registry without being read/hashed/parsed.
        if parse and p.suffix.lower() in ('.md','.txt','.base') and stat.st_size<=10*1024*1024:
            raw=p.read_bytes();sha=digest(raw);text=raw.decode('utf-8-sig',errors='replace')
            try:
                post=frontmatter.loads(text) if p.suffix.lower()=='.md' else None
                meta=post.metadata if post else {};body=post.content if post else text
            except Exception:body=text
        title=str(meta.get('name') or meta.get('title') or p.stem)
        tags=[str(t).lstrip('#') for t in list_value(meta.get('tags'))]
        file={'path':rel,'name':p.stem,'folder':p.parent.relative_to(root).as_posix() if p.parent!=root else '',
              'ext':p.suffix.lstrip('.'),'tags':tags,'size':stat.st_size,'mtime':stat.st_mtime,
              'ctime':getattr(stat,'st_birthtime',stat.st_ctime),'basename':p.stem,'modified':stat.st_mtime,
              'link':{'path':rel,'label':title},'inlinks':[],'outlinks':[]}
        return {'path':rel,'title':title,'metadata':meta,'text':text,'body':body,'sha256':sha,'file':file,'_stat':stamp,'_parsed':parse,'_hydrated':parse}

    def restore(self):
        from vault_rag.catalog_cache import restore
        root=self.files.config.root
        entries,dirs=restore(root)
        self.directories=dirs
        persist=self.persist;self.persist=False
        try:self._publish(root,entries,set(entries),reset=True)
        finally:self.persist=persist
        self.metadata_ready=False

    def scan_selected(self):
        """Only read selected text notes; never traverse an excluded subtree."""
        config=self.files.config;root=config.root;entries={};dirs={''}
        scopes=config.data['include_roots']
        for scope in scopes:
            if not config.selected(scope,validated=True):continue
            exclusions=[p for p in config.data['exclude_roots'] if not under(scope,p)]
            for p in self.files.walk(scope,directories=dirs,exclude_roots=exclusions):
                rel=p.relative_to(root).as_posix()
                if p.suffix.lower() not in ('.md','.txt') or not config.selected(rel,validated=True):continue
                if config.role(rel)!='wiki' and not config.eligible(rel,{}):continue
                try:entries[rel]=self._entry(root,p,self.entries.get(rel))
                except FileNotFoundError:continue
        self.directories=dirs
        changed={p for p in set(entries)|set(self.entries) if entries.get(p) is not self.entries.get(p)}
        return self._publish(root,entries,changed,self.root!=str(root))

    def prepare_metadata(self,stop=None):
        """Explicit global feature preparation, outside locks used by readers."""
        with self.update_lock:
            root=self.files.config.root;revision=self.files.config.data.get('revision')
            entries={};dirs={''};changed=set()
            for p in self.files.walk(directories=dirs):
                if stop and stop.is_set():return False
                rel=p.relative_to(root).as_posix()
                try:entry=self._entry(root,p,self.entries.get(rel))
                except FileNotFoundError:continue
                entries[rel]=entry
                if entry is not self.entries.get(rel):changed.add(rel)
                if len(entries)%32==0:
                    import time
                    time.sleep(.001)
            if self.files.config.data.get('root')!=str(root) or self.files.config.data.get('revision')!=revision:return False
            self.directories=dirs;self._publish(root,entries,changed|set(self.entries).difference(entries),True)
            self.metadata_ready=True;self.complete_namespace=True;return True

    def refresh_scopes(self):
        """Refresh RAG text without discarding the lazy browsing registry."""
        with self.update_lock:
            config=self.files.config;root=config.root;revision=config.data.get('revision')
            scoped=Catalog(self.files);scoped.persist=False
            scoped.entries={p:e for p,e in self.entries.items() if Path(p).suffix.lower() in ('.md','.txt') and config.selected(p,validated=True)}
            scoped.root=str(root);scoped.scan_selected()
            entries=dict(self.entries);changed=set()
            for path in set(scoped.entries)|set(scoped.changed_paths):
                entry=scoped.entries.get(path)
                if entry is None:
                    if path in entries and not (root/path).is_file():entries.pop(path);changed.add(path)
                elif entry is not entries.get(path):entries[path]=entry;changed.add(path)
            if config.data.get('root')!=str(root) or config.data.get('revision')!=revision:return False
            self.directories.update(scoped.directories)
            self._publish(root,entries,changed,self.root!=str(root));self.scopes_verified=True;return True

    def read_cached(self,rel):
        root=self.files.config.root;p=self.files.config.path_for(rel)
        stat=p.stat();entry=self.entries.get(rel)
        if entry and entry['_stat']==(stat.st_mtime_ns,stat.st_size):
            entry=self._entry(root,p,entry,stat_value=stat)
            if entry.get('_hydrated'):
                if self.files.config.data.get('root')!=str(root):return self.files.read(rel)
                with self.lock:self.entries={**self.entries,rel:entry}
                return {'path':rel,'root':str(root),'text':entry['text'],'etag':entry['sha256'],'metadata':entry['metadata'],'mtime':stat.st_mtime}
        return self.files.read(rel)

    @staticmethod
    def _keys(target,source=''):
        from urllib.parse import unquote
        value=unquote(target.split('|')[0].split('#')[0]).strip().strip('<>')
        base=PurePosixPath(value).name
        return {path_key(x) for x in (value,base,base+'.md',posixpath.normpath(str(PurePosixPath(source).parent/value)))}

    def _publish(self,root,entries,changed,reset=False):
        if not changed and not reset:self.changed_paths=[];return len(entries)
        old=self.entries;indexes=self.indexes(entries);keys=set()
        for rel in changed:
            keys.update(self._keys(rel))
            for entry in (old.get(rel),entries.get(rel)):
                if entry:
                    keys.update(path_key(str(x)) for x in [entry['title'],entry['metadata'].get('id',''),*list_value(entry['metadata'].get('aliases'))] if x)
        references={} if reset else dict(self.references)
        reference_keys={} if reset else dict(self.reference_keys)
        edges={} if reset else dict(self.edges)
        affected=set(entries) if reset else set(changed)|{source for source,values in reference_keys.items() if keys.intersection(values)}
        for rel in affected:
            entry=entries.get(rel)
            if not entry or not rel.lower().endswith('.md'):
                references.pop(rel,None);reference_keys.pop(rel,None);edges.pop(rel,None);continue
            if reset or rel in changed:
                body=re.sub(r'^```[^\n]*\n.*?^```[^\n]*(?:\n|$)','',entry['text'],flags=re.S|re.M)
                references[rel]=[match.group(2) if match.group(1) else match.group(5) for match in LINK_RE.finditer(body)]
                reference_keys[rel]=set().union(*(self._keys(target,rel) for target in references[rel])) if references[rel] else set()
            links=[]
            for target in references.get(rel,[]):
                found=self.resolve(target,rel,entries=entries,indexes=indexes)
                if len(found)==1:links.append({'source':rel,'target':found[0]})
            edges[rel]=links
        links=[link for values in edges.values() for link in values]
        ins=defaultdict(list);outs=defaultdict(list)
        for link in links:ins[link['target']].append(link['source']);outs[link['source']].append(link['target'])
        # Readers keep immutable snapshots while this generation is assembled.
        for rel,entry in list(entries.items()):
            if entry['file'].get('inlinks')!=ins[rel] or entry['file'].get('outlinks')!=outs[rel]:
                entries[rel]={**entry,'file':{**entry['file'],'inlinks':ins[rel],'outlinks':outs[rel]}}
        if self.persist:self._persist(root,entries,changed,reset,old)
        table=defaultdict(list)
        for path in sorted(self.directories):
            if not path:continue
            parent,_,name=path.rpartition('/')
            table[parent].append({'path':path,'name':name,'directory':True,'size':0,'mtime':0})
        for path,entry in entries.items():
            parent,_,name=path.rpartition('/')
            table[parent].append({'path':path,'name':name,'directory':False,'size':entry['file']['size'],'mtime':entry['file']['mtime']})
        self.directory_table={path:sorted(rows,key=lambda row:(not row['directory'],row['name'].lower())) for path,rows in table.items()}
        if not self.complete_namespace:self.scanned_folders.clear()
        self.entries=entries;self.links=links;self.resolver_indexes=indexes;self.root=str(root)
        self.references=references;self.reference_keys=reference_keys;self.edges=edges
        self.version+=1;self.changed_paths=sorted(changed)
        return len(entries)

    def _persist(self,root,entries,changed,reset,old):
        from vault_rag.catalog_cache import persist
        persist(root,entries,changed,reset,old,self.directories)

    def scan(self):
        with self.update_lock:
            root=self.files.config.root;reset=self.root!=str(root);entries={};changed=set();directories={''};stats={}
            for p in self.files.walk(directories=directories,stats=stats):
                rel=p.relative_to(root).as_posix();old=None if reset else self.entries.get(rel)
                try:entry=self._entry(root,p,old,stat_value=stats.pop(p))
                except FileNotFoundError:continue
                entries[rel]=entry
                if entry is not old:changed.add(rel)
            changed.update(set(self.entries)-set(entries));changed.update(self.directories.symmetric_difference(directories))
            self.directories=directories
            result=self._publish(root,entries,changed,reset);self.metadata_ready=True;self.complete_namespace=True
            return result

    def apply(self,paths):
        with self.update_lock:
            paths=set(paths)
            try:self.files.attachments.apply(paths)
            except (OSError,sqlite3.Error,ValueError):
                logging.getLogger(__name__).warning('Attachment index update unavailable; refresh required',exc_info=True)
            root=self.files.config.root
            if self.root!=str(root):self.restore()
            entries=dict(self.entries);changed=set()
            for rel in set(paths):
                try:p=self.files.config.path_for(rel)
                except (ValueError,OSError):continue
                old_paths={path for path in entries if path==rel or path.startswith(rel+'/')}
                present=set()
                if p.is_file():items=[p]
                elif p.is_dir():
                    self.directories.add(rel);items=self.files.walk(rel,directories=self.directories) if (not self.lazy or self.complete_namespace) else (x for x in p.iterdir() if x.is_file());changed.add(rel)
                else:items=[]
                for item in items:
                    path=item.relative_to(root).as_posix()
                    try:entry=self._entry(root,item,entries.get(path),parse=(not self.lazy or self.metadata_ready or self.files.config.selected(path,validated=True)))
                    except FileNotFoundError:continue
                    entries[path]=entry;present.add(path);changed.add(path)
                    parent=path.rpartition('/')[0]
                    while parent:self.directories.add(parent);parent=parent.rpartition('/')[0]
                for path in old_paths-present:entries.pop(path,None);changed.add(path)
                if not p.exists():
                    removed={path for path in self.directories if path==rel or path.startswith(rel+'/')}
                    self.directories.difference_update(removed);changed.update(removed)
            if any(Path(p).suffix.lower() in ('.md','.txt','.base') for p in changed):self.metadata_ready=False
            return self._publish(root,entries,changed)
    def tree(self,rel='',*,force=False):
        # One visible folder only. Never wait for the catalog/metadata worker.
        config=self.files.config;path=config.path_for(rel)
        if not path.is_dir():raise ValueError('不是目录')
        self.opened_folders.add(rel)
        stamp=path.stat().st_mtime_ns
        if not force and self.root==config.data.get('root') and (self.complete_namespace or self.scanned_folders.get(rel)==stamp):
            return [{**row,'selected':config.selected(row['path'],validated=True)} for row in self.directory_table.get(rel,[])]
        rows=self.files.tree(rel)
        self.directory_table={**self.directory_table,rel:[{k:v for k,v in row.items() if k!='selected'} for row in rows]}
        self.scanned_folders[rel]=stamp
        return rows
    @staticmethod
    def indexes(entries):
        names=defaultdict(list);identities=defaultdict(list)
        for path,entry in entries.items():
            names[path_key(path.rsplit('/',1)[-1])].append(path)
            for key in [str(entry['metadata'].get('id','')),entry['title']]+[str(x) for x in list_value(entry['metadata'].get('aliases'))]:
                if key:identities[key].append(path)
        return set(entries),dict(names),dict(identities),{path_key(p):p for p in entries}
    def resolve(self,target,source='',entries=None,indexes=None):
        current=entries is None;entries=self.entries if current else entries
        if current and not self.complete_namespace:
            found=self.files.resolve(target,source)
            if found:return found
        if not entries:return self.files.resolve(target,source)
        indexes=indexes or self.resolver_indexes or self.indexes(entries)
        paths,names,identities,canonical=indexes
        found=self.files.resolve(target,source,paths=paths,names=names,canonical=canonical)
        if found:return found
        key=target.split('|')[0].split('#')[0]
        found=sorted(set(identities.get(key,[])))
        if found or not current:return found
        # An in-app creation can precede the watcher by a few milliseconds.
        for candidate in (str(PurePosixPath(source).parent/target),target):
            try:
                p=self.files.config.path_for(candidate)
                if p.is_file():return [p.relative_to(self.files.config.root).as_posix()]
            except (ValueError,OSError):pass
        return self.files.resolve(target,source)
    def search(self,query,limit=40):
        terms=tokens(query)
        if not terms:return []
        out=[]
        for entry in self.entries.values():
            text=(entry['path']+' '+entry['title']+' '+entry['body']).lower();weight=sum(1 for t in terms if t in text)+sum(3 for t in terms if t in entry['title'].lower())
            if weight:
                at=min((text.find(t) for t in terms if t in text),default=0)
                out.append({'path':entry['path'],'title':entry['title'],'score':weight,'excerpt':entry['body'][max(0,at-80):at+200],'directory':False})
        return sorted(out,key=lambda x:-x['score'])[:limit]
    def graph(self,path=None):
        links=self.links
        paths=set(self.entries)
        if path:
            paths={path}|{x['source'] for x in links if x['target']==path}|{x['target'] for x in links if x['source']==path}
            links=[x for x in links if x['source'] in paths and x['target'] in paths]
        return {'nodes':[{'id':p,'label':self.entries[p]['title'],'type':self.files.config.role(p)} for p in sorted(paths) if p.lower().endswith('.md')], 'links':[x for x in links if x['source'].lower().endswith('.md') and x['target'].lower().endswith('.md')]}
    def query(self,source):
        lines=[line.strip() for line in source.splitlines() if line.strip()]
        if not lines or not re.match(r'^(TABLE|LIST)\b',lines[0],re.I):raise ValueError('支持 TABLE 和 LIST 查询')
        first=lines[0];table=first.upper().startswith('TABLE');no_id='WITHOUT ID' in first.upper()
        fields=re.sub(r'^(TABLE|LIST)\s*(WITHOUT ID\s*)?','',first,flags=re.I)
        clauses={}
        for line in lines[1:]:
            m=re.match(r'^(FROM|WHERE|GROUP BY|SORT|LIMIT)\s+(.+)$',line,re.I)
            if not m:raise ValueError('暂不支持的查询语句：'+line)
            clauses[m.group(1).upper()]=m.group(2)
        rows=[]
        folders={part for path in self.entries for part in ['/'.join(path.split('/')[:i]) for i in range(1,len(path.split('/')))]}
        for entry in self.entries.values():
            if not entry['path'].lower().endswith('.md'):continue
            row={**entry['metadata'],'file':entry['file']}
            folder=clauses.get('FROM','').strip('"\'')
            if folder.startswith('#'):
                if folder[1:] not in entry['file']['tags']:continue
            elif folder and folder!='/':
                if not under(entry['path'],folder):
                    # Existing vault moves can retain old FROM paths; resolve only a unique directory suffix.
                    alternatives=[p for p in folders if p.endswith('/'+folder)]
                    if len(alternatives)!=1 or not under(entry['path'],alternatives[0]):continue
            if clauses.get('WHERE') and not Expr(clauses['WHERE'],row).run():continue
            rows.append(row)
        if clauses.get('GROUP BY'):
            groups=defaultdict(list)
            for row in rows:groups[str(Expr(clauses['GROUP BY'],row).run())].append(row)
            rows=[{'key':key,'rows':values,clauses['GROUP BY']:key,'file':{'link':{'label':key},'path':key}} for key,values in groups.items()]
        parsed=[]
        for col in columns(fields):
            m=re.match(r'(.*?)\s+AS\s+(.*)$',col,re.I);expr=m.group(1).strip() if m else col;label=m.group(2).strip('"\' ') if m else col
            parsed.append((expr,label))
        for row in rows:
            for expr,label in parsed:row[label]=Expr(expr,row).run()
        if clauses.get('SORT'):
            for col in reversed(columns(clauses['SORT'])):
                parts=col.rsplit(' ',1);desc=len(parts)==2 and parts[-1].upper()=='DESC';expr=parts[0] if len(parts)==2 and parts[-1].upper() in ('ASC','DESC') else col
                rows.sort(key=lambda x:(Expr(expr,x).run() is not None,str(Expr(expr,x).run()) if not isinstance(Expr(expr,x).run(),(int,float)) else Expr(expr,x).run()),reverse=desc)
        if clauses.get('LIMIT'):rows=rows[:int(clauses['LIMIT'])]
        headers=[label for _,label in parsed]
        if table and not no_id:headers=['文件']+headers
        out=[]
        for row in rows:
            values={label:row.get(label) for label in headers}
            if not no_id:values['文件']=row['file']['link']
            out.append({'path':row['file'].get('path',''),'values':values})
        return {'kind':'table' if table else 'list','headers':headers,'rows':out,'total':len(out)}
    def base(self,path,view_index=None):
        import hashlib
        raw=self.files.read(path)['text'];data=yaml.safe_load(raw) or {};rows=[]
        profiles=json.loads((Path(__file__).parent/'tasknotes_profiles.json').read_text(encoding='utf-8'))
        today=dt.date.today()
        def day(value):
            try:return dt.date.fromisoformat(str(value)[:10])
            except (ValueError,TypeError):return None
        def open_task(row):
            return row.get('status')!='done' if not row.get('recurrence') else today not in [day(v) for v in list_value(row.get('complete_instances'))]
        def matches(filter_,row):
            if not filter_:return True
            profile=profiles.get(hashlib.sha256(json.dumps(filter_,ensure_ascii=False,sort_keys=True).encode()).hexdigest())
            if profile:
                if not open_task(row):return False
                due=day(row.get('due'));scheduled=day(row.get('scheduled'));dates=[v for v in (due,scheduled) if v]
                if profile=='Today':return today in dates
                if profile=='Overdue':return any(v<today for v in dates)
                if profile=='This Week':return any(today<=v<=today+dt.timedelta(days=7) for v in dates)
                if profile=='Unscheduled':return not dates
                if profile=='Not Blocked':
                    for block in list_value(row.get('blockedBy')):
                        key=str(block.get('uid','')) if isinstance(block,dict) else str(block).strip('[]')
                        targets=self.resolve(key)
                        if any(self.entries[t]['metadata'].get('status')!='done' for t in targets):return False
                    return True
            if isinstance(filter_,str):return bool(Expr(filter_,row).run())
            if isinstance(filter_,dict):return all((all(matches(v,row) for v in vals) if op=='and' else any(matches(v,row) for v in vals) if op=='or' else not any(matches(v,row) for v in vals)) for op,vals in filter_.items())
            raise ValueError('视图筛选格式无效')
        for entry in self.entries.values():
            if entry['path'].lower().endswith('.md'):
                row={**entry['metadata'],'file':entry['file']}
                if matches(data.get('filters'),row):rows.append({'path':entry['path'],'title':entry['title'],'metadata':entry['metadata'],'file':entry['file'],'etag':entry['sha256']})
        for index,view in enumerate(data.get('views',[])):
            if view_index is not None and index!=view_index:
                view['rows']=[];continue
            try:
                view['rows']=[r for r in rows if matches(view.get('filters'),{**r['metadata'],'file':r['file']})]
                for sort in reversed(view.get('sort',[])):
                    key=sort.get('property') or sort.get('column');reverse=sort.get('direction','ASC')=='DESC'
                    view['rows'].sort(key=lambda r:(r['metadata'].get(key) is not None,str(r['metadata'].get(key,''))),reverse=reverse)
            except ValueError as e:view['rows']=[];view['error']=str(e)
        return {'properties':data.get('properties',{}),'views':data.get('views',[]),'active_view':view_index}

def render_template(text,now=None):
    now=now or dt.datetime.now();cursor=None
    def date(match):
        format_=match.group(1);mapping={'YYYY':f'{now.year:04d}','MM':f'{now.month:02d}','DD':f'{now.day:02d}','HH':f'{now.hour:02d}','mm':f'{now.minute:02d}','ss':f'{now.second:02d}','dddd':['星期一','星期二','星期三','星期四','星期五','星期六','星期日'][now.weekday()]}
        for key in sorted(mapping,key=len,reverse=True):format_=format_.replace(key,mapping[key])
        return format_
    text=re.sub(r'<%\s*tp\.date\.now\("([^"]+)"\)\s*%>',date,text)
    text=text.replace('{{date}}',now.date().isoformat()).replace('{{time}}',now.strftime('%H:%M'))
    if '<% tp.file.cursor %>' in text:cursor=text.index('<% tp.file.cursor %>');text=text.replace('<% tp.file.cursor %>','')
    if re.search(r'<%',text):raise ValueError('模板含暂不支持的脚本，占位符未执行')
    # Existing daily template's previous-day links use a Dataview date expression.
    def previous(match):
        day=dt.date.fromisoformat(match.group(1))-dt.timedelta(days=int(match.group(2)))
        return '"'+day.isoformat()+'"'
    text=re.sub(r'date\((\d{4}-\d{2}-\d{2}) - (\d+)d\)\.format\("YYYY-MM-DD"\)',previous,text)
    return {'text':text,'cursor':cursor}
