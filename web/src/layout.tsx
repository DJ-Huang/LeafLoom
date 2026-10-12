import React,{useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {BookOpen,Calendar,ChevronRight,FileText,Home,PanelLeftClose,Search,X} from 'lucide-react';
import {Config,OpenNote} from './api';
import {useStatus} from './hooks';
import {Action} from './ui';

export const fileName=(path:string)=>path.split('/').pop()||path;
export type Preferences={recent:string[],sidebarWidth:number,sidebarCollapsed:boolean,wide:boolean};
const defaults:Preferences={recent:[],sidebarWidth:240,sidebarCollapsed:false,wide:false};
function readPreferences(root:string):Preferences{
 try{const saved=JSON.parse(localStorage.getItem('workspace:'+root)||'null');return {
  recent:Array.isArray(saved?.recent)?saved.recent.filter((path:unknown)=>typeof path==='string').slice(0,12):[],
  sidebarWidth:Math.max(200,Math.min(360,Number(saved?.sidebarWidth)||240)),sidebarCollapsed:saved?.sidebarCollapsed===true,wide:saved?.wide===true
 };}catch{return {...defaults};}
}
export function usePreferences(root:string){
 const initial=useMemo(()=>readPreferences(root),[root]),[state,setState]=useState({root,value:initial});
 const value=state.root===root?state.value:initial;
 const update=useCallback((change:Partial<Preferences>|((value:Preferences)=>Partial<Preferences>))=>setState(previous=>{
  const current=previous.root===root?previous.value:initial,next={...current,...(typeof change==='function'?change(current):change)};
  if(root)try{localStorage.setItem('workspace:'+root,JSON.stringify(next));}catch{/* Layout storage failure must not interrupt editing. */}
  return {root,value:next};
 }),[root,initial]);
 return [value,update] as const;
}
export function Sidebar({children,width,collapsed,mobileOpen,onToggle,onWidth,onDismiss}:{children:React.ReactNode,width:number,collapsed:boolean,mobileOpen:boolean,onToggle:()=>void,onWidth:(width:number)=>void,onDismiss:()=>void}){
 const drag=useRef<{x:number,width:number}|undefined>(undefined),aside=useRef<HTMLElement>(null),dismiss=useRef(onDismiss);dismiss.current=onDismiss;
 useEffect(()=>{if(!mobileOpen)return;const previous=document.activeElement as HTMLElement|null;
  const focusable=()=>Array.from(aside.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],[tabindex="0"]')||[]).filter(element=>element.getClientRects().length);
  focusable()[0]?.focus();
  const key=(event:KeyboardEvent)=>{if(document.querySelector('dialog[open]'))return;if(event.key==='Escape'){event.preventDefault();dismiss.current();}if(event.key==='Tab'){const items=focusable(),first=items[0],last=items[items.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}};
  window.addEventListener('keydown',key);return()=>{window.removeEventListener('keydown',key);if(previous?.isConnected)previous.focus();};
 },[mobileOpen]);
 return <>{mobileOpen&&<button className="sidebar-scrim" aria-label="关闭导航" onClick={onDismiss}/>}
  <aside ref={aside} id="workspace-sidebar" aria-label="知识库导航" className={'sidebar'+(collapsed?' collapsed':'')+(mobileOpen?' mobile-open':'')} style={{width}}>
   <div className="sidebar-collapse"><Action title="收起导航" onClick={onToggle}><PanelLeftClose size={16}/></Action></div>{children}
   <div className="sidebar-resize" role="separator" aria-label="调整导航宽度" aria-orientation="vertical" aria-valuemin={200} aria-valuemax={360} aria-valuenow={width} tabIndex={0}
    onPointerDown={event=>{drag.current={x:event.clientX,width};event.currentTarget.setPointerCapture(event.pointerId);}}
    onPointerMove={event=>{if(drag.current)onWidth(Math.max(200,Math.min(360,drag.current.width+event.clientX-drag.current.x)));}}
    onPointerUp={()=>{drag.current=undefined;}} onPointerCancel={()=>{drag.current=undefined;}}
    onKeyDown={event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();onWidth(event.key==='Home'?200:event.key==='End'?360:Math.max(200,Math.min(360,width+(event.key==='ArrowRight'?16:-16))));}}}/>
  </aside></>;
}
export function Tabs({tabs,active,view,knowledgeVisited,onSelect,onClose,onHome,onKnowledge}:{tabs:string[],active:string,view:string,knowledgeVisited:boolean,onSelect:(path:string)=>void,onClose:(path:string)=>void,onHome:()=>void,onKnowledge:()=>void}){
 return <nav className="tabs" aria-label="已打开的页面"><button className={'tab '+(view==='home'?'active':'')} onClick={onHome}><Home size={14}/>首页</button>{knowledgeVisited&&<button className={'tab '+(view==='knowledge'?'active':'')} onClick={onKnowledge}><Search size={14}/>知识检索</button>}{tabs.map(path=><div className={'document-tab '+(view==='document'&&path===active?'active':'')} key={path}>
  <button className="tab" title={path} aria-current={view==='document'&&path===active?'page':undefined} onClick={()=>onSelect(path)}><FileText size={14}/><span>{fileName(path)}</span></button><button className="tab-close" aria-label={'关闭 '+fileName(path)} onClick={()=>onClose(path)}><X size={12}/></button>
 </div>)}</nav>;
}
export function IndexStatus(){const status=useStatus();return <div className="index-status"><span className={'status-dot '+(status?.last_error?'error':'')}/><div><strong>{status?.sync?.state||'正在同步目录'}</strong><small>{status?.num_files||0} 篇检索资料 · {status?.catalog_files||0} 个文件</small>{status?.watch?.error&&<small>监听不可用 · 每 10 秒检查</small>}{status?.last_error&&<small className="error">{status.last_error}</small>}</div></div>;}
export function Dashboard({config,recent,onOpen,onCreate,onKnowledge,onDaily}:{config:Config,recent:string[],onOpen:OpenNote,onCreate:()=>void,onKnowledge:()=>void,onDaily:()=>void}){
 return <div className="dashboard"><div className="page-icon"><BookOpen size={42} strokeWidth={1.4}/></div><h1>你的知识库</h1><p className="dashboard-intro">从上次的思路继续，或记下新的想法。</p>
  <div className="home-shortcuts"><button onClick={onCreate}><FileText size={20}/><span>新建笔记</span></button><button onClick={onDaily}><Calendar size={20}/><span>今日笔记</span></button><button onClick={onKnowledge}><Search size={20}/><span>检索知识</span></button></div>
  {config.homepage&&<button className="homepage-link" onClick={()=>onOpen(config.homepage)}><Home size={18}/><div><strong>知识库首页</strong><span>{config.homepage}</span></div><ChevronRight size={16}/></button>}
  <section className="recent-section"><h2>最近打开</h2>{recent.length?<div className="recent-list">{recent.map(path=><button key={path} onClick={()=>onOpen(path)}><FileText size={17}/><div><strong>{fileName(path).replace(/\.md$/i,'')}</strong><span>{path}</span></div><ChevronRight size={14}/></button>)}</div>:<div className="recent-empty"><FileText size={22}/><p>打开一篇笔记，从这里继续阅读。</p></div>}</section>
  <div className="dashboard-footer"><span>本地文件</span><span title={config.root||''}>{fileName(config.root||'')}</span></div>
 </div>;
}
