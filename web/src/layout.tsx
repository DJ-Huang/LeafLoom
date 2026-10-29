import {t,useLocale} from './i18n';
import React,{useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {BookOpen,Paperclip,Calendar,ChevronRight,FileText,Table2,Folder,Home,Palette,PanelLeftClose,Search,Network,ArrowUpRight} from 'lucide-react';
import {Config,OpenNote} from './api';
import {useStatus} from './hooks';
import {Action} from './ui';

export const fileName=(path:string)=>path.replace(/\\/g,'/').split('/').pop()||path;
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
 useLocale();
 const drag=useRef<{x:number,width:number}|undefined>(undefined),aside=useRef<HTMLElement>(null),dismiss=useRef(onDismiss);dismiss.current=onDismiss;
 useEffect(()=>{if(!mobileOpen)return;const previous=document.activeElement as HTMLElement|null;
  const focusable=()=>Array.from(aside.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],[tabindex="0"]')||[]).filter(element=>element.getClientRects().length);
  focusable()[0]?.focus();
  const key=(event:KeyboardEvent)=>{if(document.querySelector('dialog[open]'))return;if(event.key==='Escape'){event.preventDefault();dismiss.current();}if(event.key==='Tab'){const items=focusable(),first=items[0],last=items[items.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}};
  window.addEventListener('keydown',key);return()=>{window.removeEventListener('keydown',key);if(previous?.isConnected)previous.focus();};
 },[mobileOpen]);
 return <>{mobileOpen&&<button className="sidebar-scrim" aria-label={t("关闭导航")} onClick={onDismiss}/>}
  <aside ref={aside} id="workspace-sidebar" aria-label={t("知识库导航")} className={'sidebar'+(collapsed?' collapsed':'')+(mobileOpen?' mobile-open':'')} style={{width}}>
   <div className="sidebar-collapse"><Action title={t("收起导航")} onClick={onToggle}><PanelLeftClose size={16}/></Action></div>{children}
   <div className="sidebar-resize" role="separator" aria-label={t("调整导航宽度")} aria-orientation="vertical" aria-valuemin={200} aria-valuemax={360} aria-valuenow={width} tabIndex={0}
    onPointerDown={event=>{drag.current={x:event.clientX,width};event.currentTarget.setPointerCapture(event.pointerId);}}
    onPointerMove={event=>{if(drag.current)onWidth(Math.max(200,Math.min(360,drag.current.width+event.clientX-drag.current.x)));}}
    onPointerUp={()=>{drag.current=undefined;}} onPointerCancel={()=>{drag.current=undefined;}}
    onKeyDown={event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();onWidth(event.key==='Home'?200:event.key==='End'?360:Math.max(200,Math.min(360,width+(event.key==='ArrowRight'?16:-16))));}}}/>
  </aside></>;
}
export function PathNavigation({path,view,onFolder}:{path:string,view:string,onFolder:(path:string)=>void}){
 useLocale();
 const parts=path.split('/').filter(Boolean),browsing=view==='document'||view==='folder';
 return <nav className="path-navigation" aria-label={t("当前位置")}><ol>
  {browsing?<><li><button onClick={()=>onFolder('')} title={t("打开知识库根目录")}><BookOpen size={15}/><span>{t("知识库")}</span></button></li>{parts.map((part,index)=>{
   const current=index===parts.length-1,target=parts.slice(0,index+1).join('/');
   return <li key={target}><ChevronRight size={13} aria-hidden="true"/>{current?<span className="path-current" aria-current="page" title={path}>{view==='document'?(part.endsWith('.base')?<Table2 size={15}/>:<FileText size={15}/>):<Folder size={15}/>}<span>{part.replace(/\.base$/,'')}</span></span>:<button title={t("打开 ")+target} onClick={()=>onFolder(target)}>{part}</button>}</li>;
  })}</>:<li><span className="path-current" aria-current="page">{view==='attachments'?<Paperclip size={15}/>:view==='knowledge'?<Search size={15}/>:view==='graph'?<Network size={15}/>:view==='design'?<Palette size={15}/>:<Home size={15}/>}<span>{view==='downloads'?t('dl.title'):view==='attachments'?t('attachments.title'):view==='knowledge'?t("知识检索"):view==='graph'?t("关系图谱"):view==='design'?t("设计工作台"):view==='web'?t("网页"):t("首页")}</span></span></li>}
 </ol></nav>;
}
export function IndexStatus({onOpen}:{onOpen:()=>void}){
 useLocale();const status=useStatus(),failed=!!(status?.last_error||status?.watch?.error);return <button className="index-status" onClick={onOpen} aria-label={t("查看同步与索引")} title={status?.last_error||t("{p0} 篇检索资料 · {p1} 个文件",{p0:status?.num_files||0,p1:status?.catalog_files||0})}><span className={'status-dot '+(failed?'error':'')}/><span>{failed?t("同步需要关注"):t(status?.sync?.state||'正在同步目录')}</span><ChevronRight size={13}/></button>;}
export function Dashboard({config,recent,onOpen,onCreate,onKnowledge,onDaily,onDesign,guideContent}:{config:Config,recent:string[],onOpen:OpenNote,onCreate:()=>void,onKnowledge:()=>void,onDaily:()=>void,onDesign?:()=>void,guideContent?:React.ReactNode}){
 useLocale();
 const shortcuts=[{Icon:FileText,title:t('新建笔记'),detail:t('ui.newNoteHint'),action:onCreate},{Icon:Calendar,title:t('今日笔记'),detail:t('ui.dailyHint'),action:onDaily},{Icon:Search,title:t('检索知识'),detail:t('ui.searchHint'),action:onKnowledge},...(onDesign?[{Icon:Palette,title:t('设计工作台'),detail:t('ui.designHint'),action:onDesign}]:[])];
 return <div className="dashboard"><header className="dashboard-heading"><div className="page-icon"><BookOpen size={31} strokeWidth={1.4}/></div><span className="dashboard-eyebrow">{t('ui.yourWorkspace')}</span><h1>{t('你的知识库')}</h1><p className="dashboard-intro">{t('从上次的思路继续，或记下新的想法。')}</p></header>
  <button className="home-search-entry" onClick={onKnowledge}><Search size={17}/><span>{t('ui.homeSearch')}</span><ArrowUpRight size={15}/></button>
  <section className="home-actions-section" aria-label={t('ui.quickStart')}><h2 className="home-section-heading">{t('ui.quickStart')}</h2><div className="home-shortcuts">{shortcuts.map(({Icon,title,detail,action})=><button key={title} onClick={action}><span className="home-shortcut-icon"><Icon size={20} strokeWidth={1.5}/></span><strong>{title}</strong><span className="home-shortcut-detail">{detail}</span><ArrowUpRight className="home-shortcut-arrow" size={14}/></button>)}</div></section>
  {config.homepage&&<button className="homepage-link" onClick={()=>onOpen(config.homepage)}><span className="home-feature-icon"><Home size={20} strokeWidth={1.5}/></span><div><strong>{t('知识库首页')}</strong><span>{fileName(config.homepage).replace(/\.(md|base)$/i,'')}</span></div><ArrowUpRight size={15}/></button>}
  {guideContent}
  <section className="recent-section"><div className="home-section-heading"><h2>{t('最近打开')}</h2><span>{recent.length?String(recent.length).padStart(2,'0'):''}</span></div>{recent.length?<div className="recent-list">{recent.map(path=><button key={path} onClick={()=>onOpen(path)}><span className="recent-note-icon">{path.endsWith('.base')?<Table2 size={20} strokeWidth={1.45}/>:<FileText size={20} strokeWidth={1.45}/>}</span><div><strong>{fileName(path).replace(/\.(md|base)$/i,'')}</strong><span>{path.includes('/')?path.slice(0,path.lastIndexOf('/')):t('知识库根目录')}</span></div><ArrowUpRight size={14}/></button>)}</div>:<div className="recent-empty"><FileText size={24} strokeWidth={1.4}/><p>{t('打开一篇笔记，从这里继续阅读。')}</p></div>}</section>
  <div className="dashboard-footer"><span className="status-dot"/><span>{t('本地文件')}</span><span>{fileName(config.root||'')}</span></div>
 </div>;
}
