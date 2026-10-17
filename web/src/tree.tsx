import {Diagnostic} from './i18n';
import {t,useLocale} from './i18n';
import React,{useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {BookOpen,ChevronDown,ChevronRight,FileText,Folder,FolderOpen,MoreHorizontal} from 'lucide-react';
import {api,affected,Change,OpenNote} from './api';
import {VirtualList} from './virtual';
const within=(path:string,parent:string)=>!parent||path===parent||path.startsWith(parent+'/');
export function selectedPath(path:string,includes:string[],excludes:string[]){const choices=[...includes.filter(p=>within(path,p)).map(p=>({depth:p.split('/').filter(Boolean).length,enabled:true})),...excludes.filter(p=>within(path,p)).map(p=>({depth:p.split('/').filter(Boolean).length,enabled:false}))];choices.sort((a,b)=>b.depth-a.depth||Number(a.enabled)-Number(b.enabled));return choices[0]?.enabled||false;}
type Entry={path:string,name:string,directory:boolean};
export function FolderView({path,onOpen,onFolder,onCreate,onCreateDesign,refresh,manage}:{path:string,onOpen:OpenNote,onFolder:(path:string)=>void,onCreate:()=>void,onCreateDesign?:(folder:string)=>void,refresh:number,manage:(action:string,path:string)=>void}){
 useLocale();
 const [entries,setEntries]=useState<Entry[]>(),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 useEffect(()=>{
  const controller=new AbortController();let generation=0;
  const load=async(force=false)=>{const request=++generation;try{const result=await api<Entry[]>('tree?path='+encodeURIComponent(path),undefined,undefined,{signal:controller.signal,force});if(!controller.signal.aborted&&request===generation){setEntries(result);setError('');}}catch(error){if(!controller.signal.aborted&&request===generation)setError((error as Error).message);}};
  void load(refresh>0||retry>0);
  const changed=(event:Event)=>{if(affected('tree?path='+encodeURIComponent(path),(event as CustomEvent<Change>).detail))void load(true);};
  window.addEventListener('vault-data-changed',changed);return()=>{controller.abort();window.removeEventListener('vault-data-changed',changed);};
 },[path,refresh,retry]);
 return <section className="folder-page"><div className="folder-heading"><FolderOpen size={32}/><h1>{path.split('/').pop()||t("知识库")}</h1><button onClick={onCreate}>{t("新建笔记")}</button>{onCreateDesign&&<button onClick={()=>onCreateDesign(path)}>{t("在此新建设计项目")}</button>}</div>
  {error&&<div role="alert" className="error">{<Diagnostic message={error}/>} <button onClick={()=>setRetry(value=>value+1)}>{t("重试")}</button></div>}
  {entries?<div className="folder-entries">{entries.length?<VirtualList items={entries} itemKey={entry=>entry.path} estimate={48} render={entry=><div className="folder-entry"><button className="folder-entry-link" onClick={()=>entry.directory?onFolder(entry.path):onOpen(entry.path)}>{entry.directory?<Folder size={18}/>:<FileText size={18}/>}<span>{entry.name}</span>{entry.directory&&<ChevronRight size={14}/>}</button><button className="icon-button" aria-label={t("管理 ")+entry.name} onClick={event=>{event.currentTarget.focus();manage('menu',entry.path);}}><MoreHorizontal size={16}/></button></div>}/>:<p className="subtle">{t("此目录暂无文件。")}</p>}</div>:!error&&<p className="subtle">{t("正在加载目录…")}</p>}
 </section>;
}
export function DirectoryTree({path='',depth=0,onOpen,onFolder,selected,refresh,manage,onScope,include=[],exclude=[],dirsOnly=false}:{path?:string,depth?:number,onOpen:OpenNote,onFolder:(path:string)=>void,selected:string,refresh:number,manage:(action:string,path:string,destination?:string)=>void,onScope?:(path:string,include:boolean)=>void,include?:string[],exclude?:string[],dirsOnly?:boolean}){
 useLocale();
 const [folders,setFolders]=useState<Record<string,Entry[]>>({}),[opened,setOpened]=useState<Set<string>>(new Set()),[error,setError]=useState('');
 const current=useRef({folders,opened});current.current={folders,opened};
 const controller=useRef<AbortController>(new AbortController());
 const load=useCallback(async(folder:string,force=false)=>{try{const entries=await api<Entry[]>('tree?path='+encodeURIComponent(folder),undefined,undefined,{signal:controller.current.signal,force});setFolders(value=>({...value,[folder]:entries}));setError('');}catch(error){if((error as Error).name!=='AbortError')setError((error as Error).message);}},[]);
 useEffect(()=>{controller.current=new AbortController();void load(path);const changed=(event:Event)=>{const change=(event as CustomEvent<Change>).detail;for(const folder of [path,...current.current.opened])if(affected('tree?path='+encodeURIComponent(folder),change))void load(folder,true);};window.addEventListener('vault-data-changed',changed);return()=>{controller.current.abort();window.removeEventListener('vault-data-changed',changed);};},[path,load]);
 useEffect(()=>{if(refresh){for(const folder of [path,...current.current.opened])void load(folder,true);}},[refresh,path,load]);
 const rows=useMemo(()=>{const out:{entry:Entry,depth:number}[]=[];const visit=(folder:string,level:number)=>{for(const entry of folders[folder]||[]){if(dirsOnly&&!entry.directory)continue;out.push({entry,depth:level});if(entry.directory&&opened.has(entry.path))visit(entry.path,level+1);}};visit(path,depth);return out;},[folders,opened,path,depth,dirsOnly]);
 if(!folders[path])return <p className="subtle indent">{error||t("正在加载…")}</p>;
 return <div className="directory-tree" role="tree">{error&&<p className="subtle">{<Diagnostic message={error}/>}</p>}<VirtualList items={rows} itemKey={row=>row.entry.path} estimate={31} render={({entry,depth:level},index)=><div role="treeitem" aria-level={level+1} aria-expanded={entry.directory?opened.has(entry.path):undefined} aria-selected={selected===entry.path} aria-posinset={index+1} aria-setsize={rows.length} className={'tree-row '+(selected===entry.path?'selected':'')} style={{paddingLeft:14+level*16}} tabIndex={-1} draggable={!dirsOnly} onDragStart={event=>event.dataTransfer.setData('application/x-vault-path',entry.path)} onDragOver={event=>{if(entry.directory)event.preventDefault();}} onDrop={event=>{event.preventDefault();const source=event.dataTransfer.getData('application/x-vault-path');if(source&&entry.directory)manage('move',source,entry.path+'/'+source.split('/').pop());}} onContextMenu={event=>{if(dirsOnly)return;event.preventDefault();event.currentTarget.focus();manage('menu',entry.path);}}>
 {dirsOnly&&onScope&&<input aria-label={t("索引 ")+entry.path} type="checkbox" checked={selectedPath(entry.path,include,exclude)} ref={element=>{if(element)element.indeterminate=[...include,...exclude].some(p=>p!==entry.path&&within(p,entry.path));}} onChange={event=>onScope(entry.path,event.target.checked)}/>}
 <button type="button" className="tree-label" onClick={()=>{if(entry.directory){setOpened(value=>{const next=new Set(value);if(next.has(entry.path))next.delete(entry.path);else next.add(entry.path);return next;});if(!folders[entry.path])void load(entry.path);onFolder(entry.path);}else onOpen(entry.path);}}>{entry.directory?(opened.has(entry.path)?<ChevronDown size={12}/>:<ChevronRight size={12}/>):<span className="arrow-space"/>}{entry.directory?(opened.has(entry.path)?<FolderOpen size={15}/>:<Folder size={15}/>):/\.(md|txt|base)$/.test(entry.path)?<FileText size={15}/>:<BookOpen size={15}/>}<span>{entry.name}</span></button>{!dirsOnly&&<button type="button" className="tree-more" aria-label={t("管理 ")+entry.name} onClick={event=>{event.currentTarget.focus();manage('menu',entry.path);}}><MoreHorizontal size={14}/></button>}</div>}/></div>;
}
