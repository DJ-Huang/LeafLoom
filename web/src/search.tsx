import React,{useCallback,useEffect,useId,useRef,useState} from 'react';
import {ArrowUpRight,BookOpen,Clock,FileText,Search} from 'lucide-react';
import {api,OpenNote} from './api';
import {Modal} from './ui';
import {VirtualList} from './virtual';
import {fileName} from './layout';

type FileResult={path:string,title?:string,excerpt?:string};
export function FileSearch({recent,onOpen,onClose}:{recent:string[],onOpen:OpenNote,onClose:()=>void}){
 const [query,setQuery]=useState(''),[data,setData]=useState<{query:string,rows:FileResult[]}>(),[busy,setBusy]=useState(false),[error,setError]=useState(''),[selection,setSelection]=useState(0),[revision,setRevision]=useState(0);
 const generation=useRef(0),input=useRef<HTMLInputElement>(null),list=useRef<HTMLDivElement>(null),listId=useId();
 const term=query.trim();const rows:FileResult[]=term?(data?.query===term?data.rows:[]):recent.map(path=>({path}));
 useEffect(()=>{const changed=()=>setRevision(value=>value+1);window.addEventListener('vault-data-changed',changed);return()=>window.removeEventListener('vault-data-changed',changed);},[]);
 useEffect(()=>{const current=++generation.current,controller=new AbortController();setSelection(0);setError('');setBusy(!!term);
  const timer=setTimeout(()=>{if(!term){setData(undefined);return;}void api<FileResult[]>('search-files?query='+encodeURIComponent(term),undefined,undefined,{signal:controller.signal}).then(rows=>{if(current===generation.current)setData({query:term,rows});}).catch(error=>{if(current===generation.current&&error.name!=='AbortError')setError(error.message);}).finally(()=>{if(current===generation.current)setBusy(false);});},200);
  return()=>{generation.current++;clearTimeout(timer);controller.abort();};
 },[term,revision]);
 const select=(path:string)=>{onOpen(path);onClose();};
 const selected=Math.min(selection,Math.max(0,rows.length-1));
 useEffect(()=>{list.current?.querySelector('[data-selected="true"]')?.scrollIntoView({block:'nearest'});},[selected,rows.length]);
 return <Modal title="搜索文件" className="quick-search" onClose={onClose}><div className="quick-search-input"><Search size={19}/><input ref={input} autoFocus aria-label="搜索文件" role="combobox" aria-autocomplete="list" aria-expanded={rows.length>0} aria-controls={listId} aria-activedescendant={rows.length?listId+'-'+selected:undefined} placeholder="搜索文件…" value={query} onChange={event=>setQuery(event.target.value)} onKeyDown={event=>{
  if(event.nativeEvent.isComposing)return;if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();setSelection(Math.max(0,Math.min(rows.length-1,selected+(event.key==='ArrowDown'?1:-1))));}else if(event.key==='Enter'&&rows[selected]){event.preventDefault();select(rows[selected].path);}
 }}/><kbd>Esc</kbd></div><p className="search-caption" role="status">{error?error:busy?'正在查找…':term?rows.length+' 个匹配':'最近打开'}</p>
  <div id={listId} ref={list} className="quick-search-results" role="listbox" aria-label="匹配文件"><VirtualList items={rows} itemKey={row=>row.path} estimate={58} height={340} scrollIndex={selected} render={(row,index)=><button id={listId+'-'+index} role="option" aria-selected={index===selected} data-selected={index===selected} className="quick-search-result" onMouseMove={()=>setSelection(index)} onClick={()=>select(row.path)}><FileText size={18}/><div><strong>{row.title||fileName(row.path)}</strong><span>{row.path}</span></div><ArrowUpRight size={14}/></button>}/>{!busy&&!error&&!rows.length&&<div className="search-empty">{term?'没有匹配的文件，试试其他名称。':'打开的文件会出现在这里。'}</div>}</div>
  <footer className="search-help"><span><kbd>↑</kbd><kbd>↓</kbd> 选择</span><span><kbd>↵</kbd> 打开</span><span>知识内容请使用侧栏的「知识检索」</span></footer>
 </Modal>;
}

type Evidence={chunk_id:string,file_path:string,excerpt:string,channels:string[],trust:string,index_pending?:boolean,excerpt_truncated?:boolean};
type SearchData={results:Evidence[],navigation:{file_path:string,title:string,stale:boolean}[],degraded?:string,query_ms?:number};
type Snapshot={query:string,mode:string,data:SearchData};
export function KnowledgeSearch({active,revision,onOpen,onSettings}:{active:boolean,revision?:string,onOpen:OpenNote,onSettings:()=>void}){
 const [mode,setMode]=useState('knowledge'),[query,setQuery]=useState(''),[snapshot,setSnapshot]=useState<Snapshot>(),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const generation=useRef(0),request=useRef<AbortController|undefined>(undefined),last=useRef<Snapshot|undefined>(undefined),visible=useRef(active);visible.current=active;
 const execute=useCallback(async(term:string,scope:string)=>{
  if(!term.trim())return;request.current?.abort();const controller=new AbortController();request.current=controller;const current=++generation.current;setBusy(true);setError('');
  try{const data=await api<SearchData>('knowledge-search',{query:term.trim(),domain:scope==='estimation'?'estimation':null,mode:'hybrid'},undefined,{signal:controller.signal});
   if(current===generation.current){const next={query:term.trim(),mode:scope,data};last.current=next;setSnapshot(next);}
  }catch(error){if(current===generation.current&&(error as Error).name!=='AbortError')setError((error as Error).message);}finally{if(current===generation.current)setBusy(false);}
 },[]);
 useEffect(()=>{generation.current++;request.current?.abort();last.current=undefined;setSnapshot(undefined);setBusy(false);setError('');},[revision]);
 useEffect(()=>{let timer:ReturnType<typeof setTimeout>;const changed=()=>{clearTimeout(timer);if(visible.current&&last.current)timer=setTimeout(()=>{const saved=last.current;if(saved)void execute(saved.query,saved.mode);},150);};window.addEventListener('vault-data-changed',changed);return()=>{clearTimeout(timer);generation.current++;request.current?.abort();window.removeEventListener('vault-data-changed',changed);};},[execute]);
 const changeMode=(next:string)=>{generation.current++;request.current?.abort();setMode(next);setSnapshot(undefined);last.current=undefined;setBusy(false);setError('');};
 return <div className="search-page" hidden={!active}><div className="page-icon"><Search size={38} strokeWidth={1.4}/></div><h1>知识检索</h1><p className="dashboard-intro">在自己的资料中，找到可追溯的依据。</p>
  <div className="knowledge-modes" aria-label="检索范围"><button className={mode==='knowledge'?'active':''} aria-pressed={mode==='knowledge'} onClick={()=>changeMode('knowledge')}><BookOpen size={15}/>知识资料</button><button className={mode==='estimation'?'active':''} aria-pressed={mode==='estimation'} onClick={()=>changeMode('estimation')}><Clock size={15}/>工时评估</button></div>
  <form className="knowledge-search-form" onSubmit={event=>{event.preventDefault();void execute(query,mode);}}><Search size={18}/><input aria-label="检索知识" placeholder={mode==='estimation'?'查找工时经验、基准与公式…':'输入问题或关键词…'} value={query} onChange={event=>setQuery(event.target.value)}/><button className="primary" disabled={!query.trim()||busy}>{busy?'检索中…':'检索'}</button></form>
  {error&&<div className="notice error" role="alert">{error}<button onClick={()=>void execute(query,mode)}>重试</button></div>}
  {snapshot&&<section className="knowledge-results" aria-busy={busy}><div className="results-heading"><h2>「{snapshot.query}」的检索依据</h2><span>{snapshot.data.results.length} 条资料{snapshot.data.query_ms!==undefined?' · '+Math.round(snapshot.data.query_ms)+' ms':''}</span></div>
   {snapshot.data.degraded&&<div className="notice" role="status">{snapshot.data.degraded}</div>}
   <VirtualList items={snapshot.data.results} itemKey={row=>row.chunk_id} estimate={200} render={row=><button className="search-result" onClick={()=>onOpen(row.file_path)}><div className="evidence-heading"><FileText size={17}/><span className="search-result-title">{fileName(row.file_path).replace(/\.md$/i,'')}</span><ArrowUpRight size={15}/></div><span className="result-path">{row.file_path}</span><p>{row.excerpt}</p><div className="evidence-tags">{row.channels.map(channel=><span key={channel}>{{keyword:'关键词',wiki:'Wiki 关联',vector:'语义'}[channel]||channel}</span>)}<span>{row.trust}</span>{row.index_pending&&<span className="pending-tag">索引待更新</span>}{row.excerpt_truncated&&<span>打开查看完整正文</span>}</div></button>}/>
   {!snapshot.data.results.length&&<div className="recent-empty"><Search size={26}/><p>没有匹配的资料。可以换个关键词，或检查检索目录。</p><button onClick={onSettings}>选择检索目录</button></div>}
   {!!snapshot.data.navigation.length&&<div className="topic-links"><h3>相关主题入口</h3>{snapshot.data.navigation.map(item=><button key={item.file_path} onClick={()=>onOpen(item.file_path)}><BookOpen size={15}/>{item.title}{item.stale&&<span>待更新</span>}<ChevronArrow/></button>)}</div>}
  </section>}
  {!snapshot&&!busy&&!error&&<div className="knowledge-intro"><FileText size={28} strokeWidth={1.4}/><h2>让资料之间产生连接</h2><p>结合关键词、Wiki 关联与语义检索，<br/>保留每条结果的来源和可信度。</p><button className="text-link" onClick={onSettings}>管理检索目录 →</button></div>}
 </div>;
}
const ChevronArrow=()=> <ArrowUpRight size={14}/>;
