import React,{useEffect,useRef,useState} from 'react';
import {audienceDocument,PresenterDocument,PresenterSession,PresenterState} from './design-presenter-types';

declare global {interface Window {leafloomAudience?:{ready:()=>Promise<void>,report:(value:any)=>void,subscribe:(fn:(value:any)=>void)=>()=>void};}}

export function PresenterAudience(){
 const frame=useRef<HTMLIFrameElement>(null),current=useRef<{id:string,document:PresenterDocument,pageId:string,pageIds:string[],session:PresenterSession,initialState?:{paused:boolean,black:boolean}}|null>(null),started=useRef(false);
 const [config,setConfig]=useState<typeof current.current>(null),[black,setBlack]=useState(true),[error,setError]=useState(false);
 useEffect(()=>{
  const api=window.leafloomAudience;if(!api)return;
  const send=(payload:any)=>{const c=current.current;if(c)frame.current?.contentWindow?.postMessage({...payload,session:c.session.id},c.session.origin);};
  const unsubscribe=api.subscribe(value=>{
   if(value.type==='configure'){
    const c={...value,document:audienceDocument(value.document)};current.current=c;started.current=false;setBlack(true);setError(false);setConfig(c);return;
   }
   if(value.type!=='command'||value.id!==current.current?.id)return;
   const command=value.command;
   if(command.action==='black')setBlack(!!command.enabled);
   send({type:'studio-presenter-command',command});
  });
  const message=(event:MessageEvent)=>{
   const c=current.current;if(!c||event.source!==frame.current?.contentWindow||event.origin!==c.session.origin||event.data?.session!==c.session.id)return;
   const data=event.data;
   if(data.type==='studio-ready')send({type:'studio-init',document:c.document,pageId:c.pageId,presenterPageIds:c.pageIds,mode:'preview',assetBase:c.session.origin+'/',selectedIds:[]});
   if(data.type==='studio-rendered'&&!started.current){started.current=true;send({type:'studio-presentation',enabled:true});if(c.initialState?.paused)send({type:'studio-presenter-command',command:{action:'pause'}});if(c.initialState?.black)send({type:'studio-presenter-command',command:{action:'black',enabled:true}});send({type:'studio-presenter-command',command:{action:'state'}});setBlack(!!c.initialState?.black);api.report({id:c.id,type:'ready'});}
   if(data.type==='studio-presenter-state')api.report({id:c.id,type:'state',state:data.state as PresenterState});
   if(data.type==='studio-error'){setBlack(true);setError(true);api.report({id:c.id,type:'error',error:String(data.message)});}
  };
  window.addEventListener('message',message);void api.ready();
  return()=>{unsubscribe();window.removeEventListener('message',message);};
 },[]);
 return <div style={{position:'fixed',inset:0,background:'#111816'}}>
  {config&&<iframe ref={frame} title="Presentation" src={config.session.origin+'/Design/studio/runtime.html?'+new URLSearchParams({session:config.session.id,parentOrigin:location.origin})} style={{display:'block',border:0,width:'100%',height:'100%'}} sandbox="allow-scripts allow-same-origin" allow="fullscreen" allowFullScreen/>}
  {(black||error)&&<div aria-hidden="true" style={{position:'absolute',inset:0,background:'#000',zIndex:2}}/>}
 </div>;
}
