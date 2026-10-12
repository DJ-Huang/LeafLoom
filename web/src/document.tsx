import React,{lazy,memo,Suspense,useCallback,useEffect,useMemo,useRef,useState,useSyncExternalStore} from 'react';
import {BookOpen,Download,FileText,Code,Eye,Search,History,PanelRight,ChevronRight,Link2} from 'lucide-react';
import {api,affected,Change,media,Note,OpenNote} from './api';
import {useApi} from './hooks';
import {Action,LazyBoundary} from './ui';
import {VideoPlayer,AudioPlayer} from './media';
import {HtmlPreview} from './html-preview';
import {VirtualList} from './virtual';
import {acceptDiskVersion,applyProperties,changeDocument,documentState,loadDocument,saveDocument} from './document-state';
import {MarkdownPreview} from './reader';
const LiveEditor=lazy(()=>import('./editor').then(module=>({default:module.LiveEditor})));
const BaseViewer=lazy(()=>import('./base').then(module=>({default:module.BaseViewer})));
const name=(path:string)=>path.split('/').pop()||path;
const folderOf=(path:string)=>path.includes('/')?path.slice(0,path.lastIndexOf('/')):'';

function Properties({note,onUpdate,notify}:{note:Note,onUpdate:(note:Note)=>void,notify:(message:string)=>void}){
 const update=async(key:string)=>{const raw=prompt('修改属性 '+key,typeof note.metadata[key]==='object'?JSON.stringify(note.metadata[key]):String(note.metadata[key]??''));if(raw===null)return;let value:any=raw;try{value=JSON.parse(raw);}catch{}try{onUpdate(await api('properties',{path:note.path,root:note.root,updates:{[key]:value},etag:note.etag},'PATCH'));}catch(error){notify((error as Error).message);}};
 return <div className="property-list">{Object.entries(note.metadata).map(([key,value])=><button key={key} className="property" onClick={()=>update(key)}><span>{key}</span><strong>{Array.isArray(value)?value.join(' · '):typeof value==='object'?JSON.stringify(value):String(value)}</strong></button>)}<button className="text-link" onClick={()=>{const key=prompt('属性名称');if(key)void update(key);}}>＋ 添加属性</button></div>;
}
export const DocumentPane=memo(function DocumentPane({path,vaultRoot,onOpen,notify,onRecord,active=true}:{path:string,vaultRoot:string,onOpen:OpenNote,notify:(message:string)=>void,onRecord:(kind:string,path?:string)=>void,active?:boolean}){
 const session=useMemo(()=>documentState(vaultRoot,path),[vaultRoot,path]);
 useSyncExternalStore(useCallback(fn=>{session.listeners.add(fn);return()=>{session.listeners.delete(fn);};},[session]),()=>session.version);
 const ext=(path.split('.').pop()||'').toLowerCase(),isHtml=ext==='html'||ext==='htm';
 const textFile=['md','txt','base','html','htm','json','yaml','yml','toml','csv','srt','vtt','py','js','ts','css','log'].includes(ext);
 const viewKey='view:'+vaultRoot+'\n'+path;
 const [mode,setMode]=useState<'live'|'source'|'read'>(()=>{const editing=sessionStorage.getItem('edit:'+path);if(editing){sessionStorage.removeItem('edit:'+path);return ext==='md'?'live':'source';}return (sessionStorage.getItem(viewKey+':mode') as 'live'|'source'|'read')||'read';});
 const [side,setSide]=useState(!isHtml&&window.innerWidth>1000),[find,setFind]=useState(false),[search,setSearch]=useState(''),[match,setMatch]=useState(0);
 const [,setResourceVersion]=useState(0);
 const area=useRef<HTMLDivElement>(null),editor=useRef<any>(null),restored=useRef(false),pendingAnchor=useRef('');
 const {data:related}=useApi('related?path='+encodeURIComponent(path),[],active&&side&&textFile&&ext!=='base');
 const text=session.text,note=session.note;
 const outline=useMemo(()=>[...text.matchAll(/^(#{1,6}) (.+)$/gm)].map(item=>({label:item[2],depth:item[1].length,pos:item.index!})),[text]);
 const matches=useMemo(()=>{if(!search)return [];const lower=text.toLocaleLowerCase(),needle=search.toLocaleLowerCase(),out:number[]=[];let at=0;while((at=lower.indexOf(needle,at))>=0&&out.length<10000){out.push(at);at+=Math.max(1,needle.length);}return out;},[text,search]);
 useEffect(()=>{if(textFile||!active)return;const changed=(event:Event)=>{if(affected('file?path='+encodeURIComponent(path),(event as CustomEvent<Change>).detail))setResourceVersion(value=>value+1);};window.addEventListener('vault-data-changed',changed);return()=>window.removeEventListener('vault-data-changed',changed);},[path,textFile,active]);
 useEffect(()=>{
  if(!textFile||ext==='base')return;const controller=new AbortController();void loadDocument(session,controller.signal);
  const changed=(event:Event)=>{const change=(event as CustomEvent<Change>).detail;if(active&&affected('file?path='+encodeURIComponent(path),change))void loadDocument(session,controller.signal,true);};
  const restored=(event:Event)=>{if((event as CustomEvent).detail===path)void loadDocument(session,controller.signal,true);};
  window.addEventListener('vault-data-changed',changed);window.addEventListener('vault-restored',restored);
  return()=>{controller.abort();window.removeEventListener('vault-data-changed',changed);window.removeEventListener('vault-restored',restored);};
 },[session,active,textFile,ext,path]);
 useEffect(()=>{sessionStorage.setItem(viewKey+':mode',mode);},[mode,viewKey]);
 useEffect(()=>{
  if(!active)return;
  const key=(event:KeyboardEvent)=>{if((event.metaKey||event.ctrlKey)&&event.key==='s'){event.preventDefault();void saveDocument(session);}if((event.metaKey||event.ctrlKey)&&event.key==='f'&&mode==='read'){event.preventDefault();setFind(true);}};
  window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);
 },[active,mode,session]);
 useEffect(()=>{
  const element=area.current;if(!element)return;
  const scroll=()=>restored.current&&sessionStorage.setItem(viewKey+':scroll',String(element.scrollTop));
  const render=()=>{const saved=Number(sessionStorage.getItem(viewKey+':scroll')||0);if(!restored.current&&session.note&&element.querySelector('.markdown-section,.plain-reading,.cm-content,iframe')&&(element.scrollHeight-element.clientHeight>=saved||!element.querySelector('.markdown .subtle'))){element.scrollTop=saved;restored.current=true;}const anchor=sessionStorage.getItem('jump:'+path);if(anchor){const heading=anchor.startsWith('^')?Array.from(element.querySelectorAll('p,li')).find(node=>node.textContent?.trim().endsWith(anchor)):Array.from(element.querySelectorAll('h1,h2,h3,h4,h5,h6')).find(node=>node.textContent===anchor);if(heading){sessionStorage.removeItem('jump:'+path);pendingAnchor.current='';heading.scrollIntoView({block:'start'});}else if(pendingAnchor.current!==anchor&&element.querySelector('.markdown-section')){const heading=outline.find(item=>item.label===anchor||item.label.replace(/[*_`]/g,'')===anchor),pos=heading?.pos??(anchor.startsWith('^')?text.indexOf(anchor):-1);if(pos>=0){pendingAnchor.current=anchor;element.dispatchEvent(new CustomEvent('vault-reading-jump',{detail:{pos,label:anchor}}));}}}};
  const navigate=(event:Event)=>{if((event as CustomEvent).detail===path){pendingAnchor.current='';render();}};window.addEventListener('vault-navigation-anchor',navigate);element.addEventListener('scroll',scroll,{passive:true});element.addEventListener('vault-document-rendered',render);render();
  return()=>{scroll();window.removeEventListener('vault-navigation-anchor',navigate);element.removeEventListener('scroll',scroll);element.removeEventListener('vault-document-rendered',render);};
 },[viewKey,path,note,mode]);
 useEffect(()=>{if(!active)area.current?.querySelectorAll<HTMLMediaElement>('video,audio').forEach(media=>media.pause());},[active]);
 const toggleTask=useCallback((index:number)=>{const tasks=[...session.text.matchAll(/^[ \t]*[-*+] \[([ xX])\]/gm)];if(tasks[index]){const pos=tasks[index].index!+tasks[index][0].indexOf('[')+1;changeDocument(session,session.text.slice(0,pos)+(session.text[pos]===' '?'x':' ')+session.text.slice(pos+1));}},[session]);
 const jump=(pos:number,label?:string)=>{
  if(mode!=='read'&&editor.current){editor.current.dispatch({selection:{anchor:pos},scrollIntoView:true});editor.current.focus();return;}
  const element=area.current;if(!element)return;element.dispatchEvent(new CustomEvent('vault-reading-jump',{detail:{pos,label,needle:search}}));
  if(label){sessionStorage.setItem('jump:'+path,label);const heading=Array.from(element.querySelectorAll('h1,h2,h3,h4,h5,h6')).find(node=>node.textContent===label);if(heading){sessionStorage.removeItem('jump:'+path);heading.scrollIntoView({block:'start'});}return;}
  const walker=document.createTreeWalker(element.querySelector('.markdown')||element,NodeFilter.SHOW_TEXT);const needle=search.toLocaleLowerCase();let node:Node|null,count=0;const wanted=Math.max(0,matches.indexOf(pos));
  while((node=walker.nextNode())){const content=node.textContent?.toLocaleLowerCase()||'';let at=0;while(needle&&(at=content.indexOf(needle,at))>=0){if(count++===wanted){const range=document.createRange();range.setStart(node,at);range.setEnd(node,at+search.length);window.getSelection()?.removeAllRanges();window.getSelection()?.addRange(range);node.parentElement?.scrollIntoView({block:'center'});return;}at+=needle.length;}}

 };
 if(ext==='base')return <LazyBoundary><Suspense fallback={<p>正在打开视图…</p>}><BaseViewer path={path} onOpen={onOpen} notify={notify}/></Suspense></LazyBoundary>;
 if(!textFile)return <div className="media-view"><div className="media-heading"><h2>{name(path)}</h2><a className="button" href={media(path,true)}><Download size={15}/> 下载原文件</a></div>{/^(png|jpg|jpeg|webp|gif|svg|avif)$/.test(ext)?<img src={media(path)} alt={name(path)} decoding="async"/>:/^(mp4|webm|mov|m4v)$/.test(ext)?<VideoPlayer path={path} active={active} stateKey={viewKey}/>:/^(mp3|m4a|wav|ogg|flac)$/.test(ext)?<AudioPlayer path={path} active={active} stateKey={viewKey}/>:ext==='pdf'?active&&<iframe className="pdf-view" src={media(path)} title={name(path)}/>:<div className="empty-state"><BookOpen size={40}/><h2>文件已保存在本地</h2><p>此格式可下载后使用对应程序打开。</p></div>}</div>;
 if(!note)return <div className={'empty-state '+(session.error?'error':'')}>{session.error||'正在打开文档…'}{session.error&&<button onClick={()=>void loadDocument(session,undefined,true)}>重试</button>}</div>;
 return <div className="document"><div className="document-toolbar"><span className="breadcrumb">{folderOf(path)||'知识库'} <ChevronRight size={12}/> {name(path)}</span><div className="toolbar-actions"><span className={'save-state '+(session.state.includes('冲突')?'error':'')}>{session.state}</span><button onClick={()=>void saveDocument(session)}>保存</button><div className="segmented">{!isHtml&&<button className={mode==='live'?'active':''} title="实时编辑" onClick={()=>setMode('live')}><FileText size={15}/></button>}<button className={mode==='source'?'active':''} title="源码" onClick={()=>setMode('source')}><Code size={15}/></button><button className={mode==='read'?'active':''} title={isHtml?'网页':'阅读'} onClick={()=>setMode('read')}><Eye size={15}/></button></div><Action title="文内查找" onClick={()=>{if(mode==='read')setFind(value=>!value);else void import('./editor').then(module=>{if(editor.current)module.openSearchPanel(editor.current);});}}><Search size={16}/></Action><Action title="版本历史" onClick={()=>onRecord('history',path)}><History size={16}/></Action><Action title="关联信息" onClick={()=>setSide(value=>!value)}><PanelRight size={16}/></Action></div></div>
  {session.error&&<div className="conflict-banner">{session.error}{session.dirty&&<button onClick={()=>{const url=URL.createObjectURL(new Blob([session.text],{type:'text/plain;charset=utf-8'})),link=document.createElement('a');link.href=url;link.download=name(path)+'.draft.txt';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}}>下载当前草稿</button>}{session.state.includes('冲突')&&<button onClick={async()=>{const latest=await api<Note>('file?path='+encodeURIComponent(path),undefined,undefined,{force:true});const original=window.open('','_blank');if(original){original.document.body.textContent=latest.text;original.document.title='磁盘版本 · '+name(path);}if(confirm('核对磁盘版本后，使用当前编辑内容保存？')){acceptDiskVersion(session,latest.etag);void saveDocument(session);}}}>查看磁盘版本并合并</button>}</div>}
  {find&&mode==='read'&&<div className="reading-search"><input autoFocus aria-label="文内查找" placeholder="查找正文…" value={search} onChange={event=>{setSearch(event.target.value);setMatch(0);}} onKeyDown={event=>{if(event.key==='Enter'&&matches.length)jump(matches[match%matches.length]);if(event.key==='Escape')setFind(false);}}/><span>{matches.length?`${match%matches.length+1} / ${matches.length}`:'0 个匹配'}</span><button onClick={()=>{if(matches.length){const next=(match+1)%matches.length;setMatch(next);jump(matches[next]);}}}>下一个</button></div>}
  <div className="document-body"><div ref={area} className={'writing-area'+(isHtml?' html-writing-area':'')}>
   <LazyBoundary><Suspense fallback={<p className="pad subtle">正在打开内容…</p>}>{mode==='read'?(isHtml?active&&<HtmlPreview path={path} root={vaultRoot} text={text} active/>:ext==='md'?<div className="reading-content"><MarkdownPreview active={active} text={text} path={path} onOpen={onOpen} onTask={toggleTask}/></div>:<pre className="plain-reading">{text}</pre>):<LiveEditor key={path+mode+session.externalEpoch} initial={text} path={path} source={mode==='source'||ext!=='md'} onChange={value=>changeDocument(session,value)} onOpen={onOpen} onRelease={view=>{sessionStorage.setItem(viewKey+':cursor',String(view.state.selection.main.head));editor.current=null;}} onReady={view=>{editor.current=view;area.current?.dispatchEvent(new CustomEvent('vault-document-rendered'));const stored=sessionStorage.getItem('cursor:'+path)||sessionStorage.getItem(viewKey+':cursor');if(stored!==null){sessionStorage.removeItem('cursor:'+path);view.dispatch({selection:{anchor:Math.min(Number(stored)||0,view.state.doc.length)},scrollIntoView:true});}view.dom.addEventListener('keyup',()=>sessionStorage.setItem(viewKey+':cursor',String(view.state.selection.main.head)));}}/>}</Suspense></LazyBoundary>
  </div>{side&&<aside className="related-panel"><h3>文档属性</h3><Properties note={note} onUpdate={value=>{if(!applyProperties(session,value))notify('正文有未保存修改；属性已保存，请合并后再保存正文');}} notify={notify}/><h3>文档目录</h3><div className="outline"><VirtualList items={outline} itemKey={item=>String(item.pos)} estimate={30} height={360} render={item=><button style={{paddingLeft:8+(item.depth-1)*10}} onClick={()=>jump(item.pos,item.label)}>{item.label}</button>}/></div><h3>反向链接 <span>{related?.incoming.length||0}</span></h3>{related?.incoming.map((target:string)=><button className="relation-link" key={target} onClick={()=>onOpen(target)}><Link2 size={12}/>{name(target)}</button>)}<h3>关联文档</h3>{related?.outgoing.map((target:string)=><button className="relation-link" key={target} onClick={()=>onOpen(target)}>{name(target)}</button>)}</aside>}</div></div>;
});
