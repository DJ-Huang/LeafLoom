import {t,useLocale} from './i18n';
import React,{useEffect,useRef,useState} from 'react';
import {ExternalLink,Maximize,Minimize,RefreshCw} from 'lucide-react';
import {api,Change} from './api';

const sandbox='allow-scripts allow-modals allow-downloads allow-popups allow-popups-to-escape-sandbox';

export function HtmlPreview({path,root,text,active}:{path:string,root:string,text:string,active:boolean}){
 useLocale();
 const frame=useRef<HTMLIFrameElement>(null);
 const [src,setSrc]=useState('');const [location,setLocation]=useState('');
 const [full,setFull]=useState(false);const [busy,setBusy]=useState(false);
 const [error,setError]=useState('');const [refresh,setRefresh]=useState(0);
 const loaded=useRef<{path:string,root:string,text:string,refresh:number}|undefined>(undefined);
 const currentLocation=useRef('');const currentSrc=useRef('');
 useEffect(()=>{if(!active)return;const changed=(event:Event)=>{const change=(event as CustomEvent<Change>).detail;if(change.reset||change.type==='config'||change.paths?.some(path=>!(/\.(md|txt|base)$/i.test(path))))setRefresh(value=>value+1);};window.addEventListener('vault-data-changed',changed);return()=>window.removeEventListener('vault-data-changed',changed);},[active]);

 useEffect(()=>{
  if(!active)return;
  const previous=loaded.current;
  if(previous?.path===path&&previous.root===root&&previous.text===text&&previous.refresh===refresh)return;
  let alive=true;setBusy(true);setError('');
  api<{url:string}>('html-preview',{path,root,text}).then(result=>{
   if(!alive)return;
   const next=new URL(result.url,window.location.origin);
   if(currentLocation.current&&currentSrc.current){
    const current=new URL(currentLocation.current,window.location.origin);
    const entry=new URL(currentSrc.current,window.location.origin);
    const prefix=entry.pathname.split('/').slice(0,4).join('/')+'/';
    // Refresh the current local page, including its query and article anchor.
    // After editing the entry HTML, return to that entry's new snapshot.
    if(previous?.path===path&&previous.root===root&&previous.text===text&&current.pathname.startsWith(prefix)){
     const nextPrefix=next.pathname.split('/').slice(0,4).join('/')+'/';
     next.pathname=nextPrefix+current.pathname.slice(prefix.length);next.search=current.search;next.hash=current.hash;
    }else if(current.pathname===entry.pathname)next.hash=current.hash;
   }
   const url=next.href;
   currentSrc.current=result.url;currentLocation.current=url;
   setSrc(url);setLocation(url);loaded.current={path,root,text,refresh};
  }).catch(e=>{if(alive)setError((e as Error).message);}).finally(()=>{if(alive)setBusy(false);});
  return()=>{alive=false;};
 },[path,root,text,active,refresh]);

 useEffect(()=>{
  const listener=(event:MessageEvent)=>{
   if(event.source!==frame.current?.contentWindow||event.origin!=='null')return;
   const data=event.data;if(!data||typeof data!=='object')return;
   if(data.type==='vault-html-preview-expired'){setError(t("网页预览已失效，请点击刷新重新打开。"));loaded.current=undefined;}
   if(data.type==='vault-html-preview-exit')setFull(false);
   if(data.type==='vault-html-preview-location'&&typeof data.url==='string'){
    try{
     const next=new URL(data.url);const base=new URL(currentSrc.current,window.location.origin);
     const prefix=base.pathname.split('/').slice(0,4).join('/')+'/';
     if(next.origin===base.origin&&next.pathname.startsWith(prefix)){
      currentLocation.current=next.href;setLocation(next.href);
     }
    }catch{}
   }
  };
  const escape=(event:KeyboardEvent)=>{if(event.key==='Escape')setFull(false);};
  window.addEventListener('message',listener);window.addEventListener('keydown',escape);
  return()=>{window.removeEventListener('message',listener);window.removeEventListener('keydown',escape);};
 },[]);
 useEffect(()=>{if(!active)setFull(false);},[active]);

 return <section className={'html-preview'+(full?' html-preview-full':'')} hidden={!active} aria-label={t("HTML 网页浏览")}>
  <div className="html-preview-toolbar">
   <span>{full?t("全屏阅读 · ")+path.split('/').pop():t("网页浏览")}</span>
   <button title={t("刷新网页")} disabled={busy} onClick={()=>setRefresh(x=>x+1)}><RefreshCw size={15}/>{t("刷新")}</button>
   <a className="button" href={location||undefined} target="_blank" rel="noopener noreferrer" aria-disabled={!src||!!error} onClick={e=>{if(!src||error)e.preventDefault();}}><ExternalLink size={15}/>{t("独立标签页")}</a>
   <button title={full?t("退出全屏阅读"):t("全屏阅读")} onClick={()=>setFull(x=>!x)}>{full?<Minimize size={15}/>:<Maximize size={15}/>} {full?t("退出全屏"):t("全屏阅读")}</button>
  </div>
  {(busy||error)&&<div className={'html-preview-message'+(error?' error':'')} role={error?'alert':'status'}>{error||t("正在打开网页…")}</div>}
  {src&&<iframe ref={frame} className="html-preview-frame" title={t("网页 · ")+path.split('/').pop()} sandbox={sandbox} src={src}/>}
 </section>;
}
