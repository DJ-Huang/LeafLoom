"""Whole-vault file metadata, links, safe property queries and existing view adapters."""
from __future__ import annotations
from contextlib import closing
import datetime as dt, json, re, sqlite3, threading, posixpath
from pathlib import Path, PurePosixPath
from collections import defaultdict
import frontmatter, yaml
from vault_rag.local_state import Files, LINK_RE, digest, under
from vault_rag.platform_support import path_key

def tokens(text):
    text=text.lower();words=re.findall(r'[a-z0-9_]+(?:[-/][a-z0-9_]+)*|[\u3400-\u9fff]+',text);out=[]
    for w in words:
        if re.search(r'[\u3400-\u9fff]',w):out.extend([w] if len(w)==1 else [w[i:i+2] for i in range(len(w)-1)])
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
    def __init__(self,files:Files):
        self.files=files;self.entries={};self.lock=threading.RLock();self.links=[]
        self.version=0;self.root=None;self.resolver_indexes=None
        self.references={};self.reference_keys={};self.edges={};self.changed_paths=[]
        self.persist=True
        self.directories={''};self.directory_table={}

    def _entry(self,root,p,old=None,force=False,stat_value=None):
        rel=p.relative_to(root).as_posix();stat=stat_value or p.stat();stamp=(stat.st_mtime_ns,stat.st_size)
        if old and old['_stat']==stamp and not force:return old
        meta={};text='';body='';sha=''
        # Assets stay in the filename registry without being read/hashed/parsed.
        if p.suffix.lower() in ('.md','.txt','.base') and stat.st_size<=10*1024*1024:
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
        return {'path':rel,'title':title,'metadata':meta,'text':text,'body':body,'sha256':sha,'file':file,'_stat':stamp}

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
        self.entries=entries;self.links=links;self.resolver_indexes=indexes;self.root=str(root)
        self.references=references;self.reference_keys=reference_keys;self.edges=edges
        self.version+=1;self.changed_paths=sorted(changed)
        return len(entries)

    def _persist(self,root,entries,changed,reset,old):
        cache=root/'.vault-rag/catalog.sqlite';cache.parent.mkdir(exist_ok=True)
        with closing(sqlite3.connect(cache)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, title TEXT, metadata TEXT, sha256 TEXT, mtime REAL)')
            if reset:
                stale={row[0] for row in db.execute('SELECT path FROM files')}-set(entries)
            else:stale=set(old)-set(entries)
            db.executemany('DELETE FROM files WHERE path=?',[(path,) for path in stale])
            db.executemany('INSERT OR REPLACE INTO files VALUES(?,?,?,?,?)',
                [(x['path'],x['title'],json.dumps(x['metadata'],ensure_ascii=False,default=str),x['sha256'],x['file']['mtime'])
                 for path in (set(entries) if reset else changed) if (x:=entries.get(path)) is not None])
            db.commit()

    def scan(self):
        with self.lock:
            root=self.files.config.root;reset=self.root!=str(root);entries={};changed=set();directories={''};stats={}
            for p in self.files.walk(directories=directories,stats=stats):
                rel=p.relative_to(root).as_posix();old=None if reset else self.entries.get(rel)
                try:entry=self._entry(root,p,old,stat_value=stats.pop(p))
                except FileNotFoundError:continue
                entries[rel]=entry
                if entry is not old:changed.add(rel)
            changed.update(set(self.entries)-set(entries));changed.update(self.directories.symmetric_difference(directories))
            self.directories=directories
            return self._publish(root,entries,changed,reset)

    def apply(self,paths):
        with self.lock:
            root=self.files.config.root
            if self.root!=str(root):return self.scan()
            entries=dict(self.entries);changed=set()
            for rel in set(paths):
                try:p=self.files.config.path_for(rel)
                except (ValueError,OSError):continue
                old_paths={path for path in entries if path==rel or path.startswith(rel+'/')}
                present=set()
                if p.is_file():items=[p]
                elif p.is_dir():
                    self.directories.add(rel);items=self.files.walk(rel,directories=self.directories);changed.add(rel)
                else:items=[]
                for item in items:
                    path=item.relative_to(root).as_posix()
                    try:entry=self._entry(root,item,entries.get(path),force=True)
                    except FileNotFoundError:continue
                    entries[path]=entry;present.add(path);changed.add(path)
                    parent=path.rpartition('/')[0]
                    while parent:self.directories.add(parent);parent=parent.rpartition('/')[0]
                for path in old_paths-present:entries.pop(path,None);changed.add(path)
                if not p.exists():
                    removed={path for path in self.directories if path==rel or path.startswith(rel+'/')}
                    self.directories.difference_update(removed);changed.update(removed)
            return self._publish(root,entries,changed)
    def tree(self,rel=''):
        # Every request still validates the directory before returning cached names.
        with self.files.config.lock:
            path=self.files.config.path_for(rel)
            if not path.is_dir():raise ValueError('不是目录')
            if self.root!=self.files.config.data.get('root'):return self.files.tree(rel)
            return [{**row,'selected':self.files.config.selected(row['path'],validated=True)} for row in self.directory_table.get(rel,[])]
    @staticmethod
    def indexes(entries):
        names=defaultdict(list);identities=defaultdict(list)
        for path,entry in entries.items():
            names[path.rsplit('/',1)[-1]].append(path)
            for key in [str(entry['metadata'].get('id','')),entry['title']]+[str(x) for x in list_value(entry['metadata'].get('aliases'))]:
                if key:identities[key].append(path)
        return set(entries),dict(names),dict(identities),{path_key(p):p for p in entries}
    def resolve(self,target,source='',entries=None,indexes=None):
        current=entries is None;entries=self.entries if current else entries
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
        return []
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
        return {'nodes':[{'id':p,'label':self.entries[p]['title'],'type':self.files.config.role(p)} for p in sorted(paths) if p.endswith('.md')], 'links':[x for x in links if x['source'].endswith('.md') and x['target'].endswith('.md')]}
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
            if not entry['path'].endswith('.md'):continue
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
            if entry['path'].endswith('.md'):
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
