"""Persistent single-vault configuration, rooted paths, and durable file operations."""
from __future__ import annotations
import hashlib, io, json, os, re, shutil, stat as statlib, threading, time, uuid
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, quote
import frontmatter
import pathspec
from ruamel.yaml import YAML
from vault_rag.platform_support import (state_directory, protect_private_directory, private_file_mode,
    preserve_file_mode, is_windows, is_link, path_key, validate_windows_parts)

PROTECTED = {'.git', '.obsidian', '.vault-rag', '.rag-layout-backups', 'node_modules', '__pycache__'}
TEXT_EXTENSIONS = {'.md', '.txt', '.json', '.yaml', '.yml', '.toml', '.csv', '.srt', '.vtt', '.py', '.js', '.ts', '.tsx', '.css', '.html', '.htm', '.svg', '.base', '.log'}
LINK_RE = re.compile(r'(!?\[\[)([^\]\n]+)(\]\])|(!?\[[^\]\n]*\]\()([^\n]*?)(\))')

def digest(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()

def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('xb') as f:
            preserve_file_mode(f, path)
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)

def relative(value: str) -> str:
    value = str(value).replace('\\','/')
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or '\x00' in value or re.match(r'^[A-Za-z]:',value):
        raise ValueError('路径必须位于已关联目录内')
    if is_windows():validate_windows_parts(p.parts)
    return '' if value in ('','.') else p.as_posix().rstrip('/')

def under(path: str, root: str) -> bool:
    path,root=path_key(path),path_key(root)
    return not root or path == root or path.startswith(root+'/')

def split_link(target: str) -> tuple[str,str,str]:
    raw, sep, alias = target.partition('|')
    base, marker, anchor = raw.partition('#')
    return base, ('#'+anchor if marker else ''), ('|'+alias if sep else '')

class ConflictError(Exception): pass

class LocalConfig:
    def __init__(self, directory: Path | None = None):
        self.directory = (directory or state_directory()).resolve()
        protect_private_directory(self.directory)
        self.path=self.directory/'config.json'; self.lock=threading.RLock(); self._spec_key=None; self._spec=None
        self.data=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else self.defaults()
    @staticmethod
    def defaults():
        return {'root':None,'include_roots':['RAG'],'exclude_roots':[], 'rules_roots':['RAG/Rules'], 'wiki_roots':['RAG/Navigation'], 'estimation_roots':['RAG/EstimationDB'], 'write_targets':{'notes':'RAG/Notes','rules':'RAG/Rules','navigation':'RAG/Navigation','estimation':'RAG/EstimationDB'}, 'homepage':'000-Home.md', 'templates':'Templates', 'daily_folder':'Daily', 'port':18080}
    @property
    def root(self):
        if not self.data.get('root'): raise ValueError('请先在网页关联一个本地目录')
        p=Path(self.data['root'])
        if is_windows() and p.drive.startswith('\\\\'):raise ValueError('请选择本机盘符目录，不支持网络共享')
        if not p.is_dir(): raise ValueError('已关联目录不存在，请在设置中重新关联')
        if is_link(p) or (is_windows() and any(is_link(x) for x in p.parents)):
            raise ValueError('已关联目录已变成符号链接或 junction，请重新关联')
        return p
    def save(self, values):
        with self.lock:
            data={**self.data,**values}
            if data.get('root'):
                p=Path(data['root']).expanduser()
                if is_windows() and p.drive.startswith('\\\\'):raise ValueError('请选择本机盘符目录，不支持网络共享')
                if not p.is_absolute() or not p.is_dir() or is_link(p) or (is_windows() and any(is_link(x) for x in p.parents)): raise ValueError('请选择存在的本机目录，不能使用符号链接或 junction')
                data['root']=str(p.resolve())
            for key in ('include_roots','exclude_roots','rules_roots','wiki_roots','estimation_roots'):
                data[key]=sorted(set(relative(x) for x in data.get(key,[])))
            data['write_targets']={k:relative(v) for k,v in data.get('write_targets',{}).items()}
            for key in ('homepage','templates','daily_folder'):data[key]=relative(data[key])
            if data.get('root'):
                for name in ('include_roots','rules_roots','wiki_roots','estimation_roots'):
                    for rel in data[name]:
                        p=Path(data['root'])/rel
                        if p.exists() and (not p.is_dir() or is_link(p) or not p.resolve().is_relative_to(Path(data['root']))):raise ValueError('目录配置不能指向文件、链接或根目录外部')
            data['revision']=uuid.uuid4().hex
            atomic_write(self.path,json.dumps(data,ensure_ascii=False,indent=2).encode());private_file_mode(self.path);self.data=data
            return data
    def path_for(self, rel: str, *, writable=False) -> Path:
        rel=relative(rel);p=self.root/rel
        if any(path_key(part) in {path_key(x) for x in PROTECTED} or part.startswith('.') for part in PurePosixPath(rel).parts):raise ValueError('应用或隐藏目录不允许通过网页访问')
        cur=self.root
        for part in PurePosixPath(rel).parts:
            cur=cur/part
            if is_link(cur):raise ValueError('不通过符号链接或 junction 访问文件')
        if not p.resolve().is_relative_to(self.root):raise ValueError('路径越出关联目录')
        if writable and not rel: raise ValueError('不能修改关联根目录')
        return p
    def selected(self, rel: str, *, validated=False) -> bool:
        # The most specific explicit directory choice wins; exclusions win ties.
        matches=[(len(PurePosixPath(r).parts),True) for r in self.data['include_roots'] if under(rel,r)]
        matches += [(len(PurePosixPath(r).parts),False) for r in self.data['exclude_roots'] if under(rel,r)]
        if not matches or not max(matches,key=lambda item:(item[0],not item[1]))[1]:return False
        if not validated:
            try:self.path_for(rel)
            except (ValueError,OSError):return False
        return True
    def role(self,rel):
        for name in ('rules','wiki','estimation'):
            if any(under(rel,r) for r in self.data[name+'_roots']):return name
        return 'notes'
    def eligible(self, rel: str, meta=None) -> bool:
        if Path(rel).suffix.lower() not in ('.md','.txt') or not self.selected(rel):return False
        if Path(rel).name.lower() in ('readme.md','_readme.md'):return False
        if any(x.lower() in ('attachments','_index','_archive','archive','archives','history','trash','_history','_trash') for x in PurePosixPath(rel).parts[:-1]):return False
        if self.role(rel)=='wiki':return False
        rag=self.root/'.ragignore'
        stat=rag.stat() if rag.is_file() else None
        key=(str(self.root),stat.st_mtime_ns if stat else None,stat.st_size if stat else None)
        if key!=self._spec_key:
            self._spec=pathspec.PathSpec.from_lines('gitignore',rag.read_text(encoding='utf-8').splitlines() if stat else []);self._spec_key=key
        if self._spec.match_file(rel):return False
        if meta is None:
            try:meta=frontmatter.loads(self.path_for(rel).read_text(encoding='utf-8')).metadata
            except (OSError,ValueError):return False
        from vault_rag.path_exclusions import frontmatter_requests_skip
        return not frontmatter_requests_skip(meta)

class Files:
    def __init__(self,config:LocalConfig):self.config=config; self.lock=threading.RLock();self.changed=lambda *paths:None
    def tree(self,rel=''):
        with self.config.lock:
            return self._tree(rel)
    def _tree(self,rel=''):
        p=self.config.path_for(rel);root=self.config.root
        if not p.is_dir():raise ValueError('不是目录')
        out=[]
        for x in p.iterdir():
            if x.name.startswith('.') or path_key(x.name) in {path_key(x) for x in PROTECTED} or is_link(x):continue
            rp=x.relative_to(root).as_posix();s=x.stat()
            out.append({'path':rp,'name':x.name,'directory':x.is_dir(),'size':s.st_size,'mtime':s.st_mtime, 'selected':self.config.selected(rp,validated=True)})
        return sorted(out,key=lambda x:(not x['directory'],x['name'].lower()))
    def read(self,rel):
        with self.config.lock:
            return self._read(rel)
    def _read(self,rel):
        p=self.config.path_for(rel)
        if p.stat().st_size>10*1024*1024:raise ValueError('文本文件过大，请下载后打开')
        b=p.read_bytes();text=b.decode('utf-8-sig')
        try:meta=frontmatter.loads(text).metadata if p.suffix=='.md' else {}
        except Exception:meta={}
        return {'path':rel,'root':str(self.config.root),'text':text,'etag':digest(b),'metadata':meta,'mtime':p.stat().st_mtime}
    def _history(self,p:Path):
        if not p.is_file():return
        rel=p.relative_to(self.config.root).as_posix();key=uuid.uuid4().hex
        h=self.config.root/'.vault-rag/history'/key
        h.mkdir(parents=True);shutil.copy2(p,h/'content')
        atomic_write(h/'record.json',json.dumps({'id':key,'path':rel,'time':time.time()},ensure_ascii=False).encode())
    def save(self,rel,text,etag,*,expected_root=None):
        with self.config.lock,self.lock:
            if expected_root is not None and expected_root!=str(self.config.root):raise ConflictError('关联目录已切换，未写入；原草稿仍保留')
            p=self.config.path_for(rel,writable=True)
            if not p.is_file():raise FileNotFoundError(rel)
            if p.suffix.lower() not in TEXT_EXTENSIONS:raise ValueError('该文件不支持文本编辑')
            old=p.read_bytes()
            if etag!=digest(old):raise ConflictError('文件已被其他窗口或程序修改，未覆盖；请合并后保存')
            normalized=text.replace('\r\n','\n').replace('\r','\n')
            if b'\r\n' in old:normalized=normalized.replace('\n','\r\n')
            new=normalized.encode('utf-8')
            if old.startswith(b'\xef\xbb\xbf'):new=b'\xef\xbb\xbf'+new
            if new!=old:self._history(p);atomic_write(p,new);self.changed(rel)
            return self.read(rel)
    def properties(self,rel,updates,etag,*,expected_root=None):
        read=self.read(rel);text=read['text'];nl='\r\n' if '\r\n' in text else '\n'
        match=re.match(r'^---\r?\n(.*?)\r?\n---(?:\r?\n|$)',text,re.S)
        yaml=YAML();yaml.preserve_quotes=True;yaml.width=4096
        data=yaml.load(match.group(1)) if match else {};data=data or {}
        for key,value in updates.items():
            if value is None:data.pop(key,None)
            else:data[key]=value
        out=io.StringIO();yaml.dump(data,out)
        prefix='---\n'+out.getvalue().rstrip('\n')+'\n---\n'
        return self.save(rel,prefix+(text[match.end():] if match else text),etag,expected_root=expected_root)
    def create(self,rel,*,directory=False,text=''):
        with self.lock:
            p=self.config.path_for(rel,writable=True)
            if p.exists():raise ConflictError('名称已存在')
            if not p.parent.is_dir():raise ValueError('父目录不存在')
            if directory:p.mkdir()
            else:
                with p.open('xb') as f:f.write(text.encode())
            self.changed(rel);return {'path':rel}
    def upload(self,folder,name,data):
        if '/' in name or '\\' in name:raise ValueError('上传文件名无效')
        rel='/'.join(x for x in (relative(folder),name) if x);p=self.config.path_for(rel,writable=True)
        if p.exists():raise ConflictError('同名文件已存在')
        with p.open('xb') as f:f.write(data)
        self.changed(rel);return {'path':rel}
    def delete(self,rel):
        with self.lock:
            p=self.config.path_for(rel,writable=True)
            if not p.exists():raise FileNotFoundError(rel)
            key=uuid.uuid4().hex;trash=self.config.root/'.vault-rag/trash'/key;trash.mkdir(parents=True)
            atomic_write(trash/'record.json',json.dumps({'id':key,'path':rel,'time':time.time()},ensure_ascii=False).encode())
            shutil.move(str(p),str(trash/'content'));self.changed(rel);return {'id':key,'path':rel}
    def records(self,kind,rel=None):
        if kind not in ('history','trash','operations'):raise ValueError('记录类型无效')
        d=self.config.root/'.vault-rag'/kind;out=[]
        if d.exists():
            for p in d.glob('*/record.json'):
                item=json.loads(p.read_text(encoding='utf-8'))
                if rel is None or item.get('path')==rel:out.append(item)
        return sorted(out,key=lambda x:x['time'],reverse=True)[:200]
    def clear_trash(self,*,expected_root):
        with self.config.lock,self.lock:
            root=self.config.root
            if expected_root!=str(root):raise ConflictError('关联目录已切换，未清空回收区；请重新打开回收区')
            state=root/'.vault-rag';trash=state/'trash'
            if is_link(state) or is_link(trash):raise ValueError('回收区不能指向符号链接或 junction')
            if not trash.exists():return {'deleted':0}
            if not trash.is_dir():raise ValueError('回收区不是目录')
            entries=list(trash.iterdir())
            # Validate every entry before deleting anything; never traverse linked records.
            if any(is_link(entry) for entry in entries):raise ValueError('回收区包含符号链接或 junction，未清空')
            for entry in entries:
                if entry.is_dir():shutil.rmtree(entry)
                else:entry.unlink()
            return {'deleted':len(entries)}
    def restore(self,kind,key):
        if kind not in ('history','trash','operations') or not re.fullmatch(r'[a-f0-9]{32}',key):raise ValueError('恢复记录无效')
        with self.lock:
            d=self.config.root/'.vault-rag'/kind/key;record=json.loads((d/'record.json').read_text(encoding='utf-8'))
            if kind=='operations':return self.undo_move(d,record)
            p=self.config.path_for(record['path'],writable=True)
            if kind=='trash':
                if p.exists():raise ConflictError('原位置已存在文件，请先重命名')
                p.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(d/'content'),str(p));shutil.rmtree(d)
            else:
                self._history(p);atomic_write(p,(d/'content').read_bytes())
            self.changed(record['path']);return {'path':record['path']}
    def resolve(self,target,source='',*,paths=None,names=None,canonical=None):
        target=unquote(split_link(target)[0]).strip().strip('<>')
        if not target:return [source] if source else []
        if re.match(r'^[a-zA-Z]+:',target):return []
        if paths is None:
            # Known file paths remain fast before the first catalog generation.
            for candidate in (str(PurePosixPath(source).parent/target),target):
                for option in (candidate,candidate+'.md'):
                    try:
                        path=self.config.path_for(option)
                        if path.is_file():return [path.relative_to(self.config.root).as_posix()]
                    except (ValueError,OSError):pass
            paths={p.relative_to(self.config.root).as_posix() for p in self.walk()}
        canonical=canonical if canonical is not None else {path_key(p):p for p in paths}
        candidates=[]
        for name in [str(PurePosixPath(source).parent/target),target]:
            # Normalize relative links, but never escape the root.
            parts=[];invalid=False
            for part in PurePosixPath(name).parts:
                if part=='..':
                    if not parts:invalid=True;break
                    parts.pop()
                elif part!='.':parts.append(part)
            if invalid:continue
            name='/'.join(parts)
            for option in (name,name+'.md'):
                found=canonical.get(path_key(option))
                if found is not None and found not in candidates:candidates.append(found)
            if candidates:return candidates
        base=PurePosixPath(target).name
        bases={path_key(base),path_key(base+'.md')}
        if names is not None:return sorted({p for name,items in names.items() if path_key(name) in bases for p in items})
        return sorted(p for p in paths if path_key(p.rsplit('/',1)[-1]) in bases)
    def walk(self,rel='',*,directories=None,stats=None):
        root=self.config.root
        pending=[self.config.path_for(rel)];protected={path_key(x) for x in PROTECTED}
        while pending:
            folder=pending.pop()
            try:
                if self.config.path_for(folder.relative_to(root).as_posix())!=folder:continue
            except (ValueError,OSError):continue
            if directories is not None:directories.add('' if folder==root else folder.relative_to(root).as_posix())
            try:
                with os.scandir(folder) as items:
                    for item in items:
                        if item.name.startswith('.') or path_key(item.name) in protected:continue
                        try:s=item.stat(follow_symlinks=False)
                        except OSError:continue
                        if statlib.S_ISLNK(s.st_mode) or getattr(s,'st_reparse_tag',0) in (0xA0000003,0xA000000C):continue
                        p=Path(item.path)
                        if statlib.S_ISDIR(s.st_mode):pending.append(p)
                        elif statlib.S_ISREG(s.st_mode):
                            if stats is not None:stats[p]=s
                            yield p
            except OSError:continue
    def move(self,source,destination):
        with self.lock:
            a=self.config.path_for(source,writable=True);b=self.config.path_for(destination,writable=True)
            if not a.exists():raise FileNotFoundError(source)
            if b.exists():raise ConflictError('目标名称已存在')
            if not b.parent.is_dir() or b.is_relative_to(a):raise ValueError('目标目录无效')
            allpaths={p.relative_to(self.config.root).as_posix() for p in self.walk()}
            names={}
            for rel in allpaths:names.setdefault(rel.rsplit('/',1)[-1],[]).append(rel)
            mapping={p:destination+p[len(source):] for p in allpaths if under(p,source)}
            edits={}
            for rel in sorted(p for p in allpaths if p.endswith('.md')):
                p=self.config.root/rel;old=p.read_bytes();text=old.decode('utf-8-sig');newsource=mapping.get(rel,rel)
                def replace(m):
                    target=m.group(2) if m.group(1) else m.group(5)
                    base,anchor,alias=split_link(target)
                    found=self.resolve(target,rel,paths=allpaths,names=names)
                    if len(found)!=1:return m.group(0)
                    resolved=found[0]
                    if resolved not in mapping and newsource==rel:return m.group(0)
                    newtarget=mapping.get(resolved,resolved)
                    if m.group(1):
                        if newtarget.endswith('.md') and not base.endswith('.md'):newtarget=newtarget[:-3]
                        return m.group(1)+newtarget+anchor+alias+m.group(3)
                    if base=='':return m.group(0)
                    relative_target=os.path.relpath(self.config.root/newtarget,(self.config.root/newsource).parent).replace(os.sep,'/')
                    return m.group(4)+quote(relative_target,safe='/.-_')+anchor+m.group(6)
                # Code fences are literal, not references.
                parts=re.split(r'(^```[^\n]*\n.*?^```[^\n]*(?:\n|$))',text,flags=re.M|re.S)
                new=''.join(part if i%2 else LINK_RE.sub(replace,part) for i,part in enumerate(parts))
                if new!=text:
                    data=new.encode();data=(b'\xef\xbb\xbf'+data) if old.startswith(b'\xef\xbb\xbf') else data
                    edits[rel]=(old,data)
            key=uuid.uuid4().hex;d=self.config.root/'.vault-rag/operations'/key;d.mkdir(parents=True)
            record={'id':key,'path':source,'destination':destination,'time':time.time(),'mapping':mapping,'edits':[]}
            for i,(rel,(old,new)) in enumerate(edits.items()):
                atomic_write(d/str(i),old);record['edits'].append({'path':rel,'after_path':mapping.get(rel,rel),'backup':str(i),'after_hash':digest(new)})
            atomic_write(d/'record.json',json.dumps(record,ensure_ascii=False).encode())
            moved=False
            try:
                for rel,(old,new) in edits.items():
                    if digest((self.config.root/rel).read_bytes())!=digest(old):raise ConflictError('关联文档发生修改，请重试移动')
                a.rename(b);moved=True
                for rel,(old,new) in edits.items():atomic_write(self.config.root/mapping.get(rel,rel),new)
            except Exception:
                if moved:b.rename(a)
                for rel,(old,new) in edits.items():atomic_write(self.config.root/rel,old)
                shutil.rmtree(d);raise
            self.changed(source,destination,*edits);return {'path':destination,'updated_links':len(edits),'operation_id':key}
    def undo_move(self,d,record):
        a=self.config.path_for(record['path'],writable=True);b=self.config.path_for(record['destination'],writable=True)
        if a.exists() or not b.exists():raise ConflictError('移动后的目录已变化，不能自动恢复')
        for item in record['edits']:
            p=self.config.path_for(item['after_path'])
            if not p.is_file() or digest(p.read_bytes())!=item['after_hash']:raise ConflictError('关联笔记后来已修改，不能覆盖恢复')
        b.rename(a)
        for item in record['edits']:atomic_write(self.config.path_for(item['path'],writable=True),(d/item['backup']).read_bytes())
        shutil.rmtree(d);self.changed(record['path'],record['destination'],*[item['path'] for item in record['edits']]);return {'path':record['path']}
