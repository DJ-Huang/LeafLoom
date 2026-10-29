import React,{useCallback,useEffect,useMemo,useRef,useState} from 'react';
import DOMPurify from 'dompurify';
import {ArrowLeft,ArrowRight,Monitor,Pause,Play,Square,X} from 'lucide-react';
import {t} from './i18n';
import {createMarkdown} from './markdown-core';
import {audienceDocument,PresenterCommand,PresenterDesktop,PresenterDisplay,PresenterDocument,PresenterEvent,PresenterInput,PresenterNotes,PresenterPage,PresenterSession,PresenterState} from './design-presenter-types';
import './design-presenter.css';

const blank=():PresenterNotes=>({overview:'',cues:{}});
type Props={document:PresenterDocument,pageId:string,session:PresenterSession,root:string,directory:string,notes:PresenterPage[],pending:boolean,error:string,commit:(commands:any[],label:string)=>boolean,snapshot:()=>Promise<PresenterDocument>,retry:()=>void,onClose:()=>void};

// This component owns frames so a video preview does not rerender the notes editor.
function OperationPreview({api,sessionId,subscribe,input,paused}:{api:PresenterDesktop,sessionId:()=>string,subscribe:(fn:(event:PresenterEvent)=>void)=>()=>void,input:(value:PresenterInput)=>void,paused:boolean}){
 const [frame,setFrame]=useState<{url:string,seq:number,width:number,height:number}|null>(null),image=useRef<HTMLImageElement>(null),surface=useRef<HTMLDivElement>(null),url=useRef(''),queued=useRef<PresenterInput|null>(null),raf=useRef(0),dragging=useRef(false),dragButton=useRef(0);
 useEffect(()=>subscribe(event=>{if(event.type!=='frame'||!event.jpeg||!event.seq)return;const next=URL.createObjectURL(new Blob([new Uint8Array(event.jpeg)],{type:'image/jpeg'}));if(url.current)URL.revokeObjectURL(url.current);url.current=next;setFrame({url:next,seq:event.seq,width:event.width!,height:event.height!});}),[subscribe]);
 useEffect(()=>()=>{if(url.current)URL.revokeObjectURL(url.current);cancelAnimationFrame(raf.current);},[]);
 const point=(event:{clientX:number,clientY:number})=>{const el=image.current;if(!el)return null;const box=el.getBoundingClientRect();return {x:Math.max(0,Math.min(1,(event.clientX-box.left)/box.width)),y:Math.max(0,Math.min(1,(event.clientY-box.top)/box.height))};};
 useEffect(()=>{const element=surface.current;if(!element)return;const wheel=(event:WheelEvent)=>{const p=point(event);if(!p||paused)return;event.preventDefault();input({kind:'wheel',...p,dx:Math.max(-10000,Math.min(10000,event.deltaX)),dy:Math.max(-10000,Math.min(10000,event.deltaY))});};element.addEventListener('wheel',wheel,{passive:false});return()=>element.removeEventListener('wheel',wheel);},[input,paused]);
 const flush=()=>{cancelAnimationFrame(raf.current);raf.current=0;if(queued.current){input(queued.current);queued.current=null;}};
 const pointer=(event:React.PointerEvent,kind:'down'|'up'|'move')=>{
  if(paused)return;const p=point(event);if(!p)return;
  if(kind==='down'){event.preventDefault();surface.current?.focus({preventScroll:true});surface.current?.setPointerCapture(event.pointerId);dragging.current=true;dragButton.current=event.button;}
  const button=kind==='move'&&dragging.current?dragButton.current:event.button<0?0:event.button;
  const value:PresenterInput={kind,...p,button,buttons:kind!=='up'&&dragging.current?[1,4,2][dragButton.current]:event.buttons,clickCount:event.detail||1,shift:event.shiftKey,alt:event.altKey};
  if(kind==='move'){queued.current=value;if(!raf.current)raf.current=requestAnimationFrame(flush);}else{flush();input(value);}
  if(kind==='up'){dragging.current=false;if(surface.current?.hasPointerCapture(event.pointerId))surface.current.releasePointerCapture(event.pointerId);}
 };
 return <div ref={surface} className="dp-operation" tabIndex={0} role="group" aria-label={t('观众画面操作预览')} data-presenter-preview onPointerDown={event=>pointer(event,'down')} onPointerMove={event=>pointer(event,'move')} onPointerUp={event=>pointer(event,'up')} onPointerCancel={event=>{if(dragging.current)pointer(event,'up');}} onContextMenu={event=>event.preventDefault()}>
  {frame?<img ref={image} src={frame.url} width={frame.width} height={frame.height} draggable={false} alt={t('观众实时画面')} onLoad={()=>void api.ack(sessionId(),frame.seq).catch(()=>{})} onError={()=>void api.ack(sessionId(),frame.seq).catch(()=>{})}/>:<p>{t('正在连接观众画面…')}</p>}
 </div>;
}

function NextPage({document:source,page,session}:{document:PresenterDocument,page?:PresenterPage,session:PresenterSession}){
 const iframe=useRef<HTMLIFrameElement>(null),[ready,setReady]=useState(false),doc=useMemo(()=>audienceDocument(source),[source]);
 useEffect(()=>{const listener=(event:MessageEvent)=>{if(event.source===iframe.current?.contentWindow&&event.origin===session.origin&&event.data?.session===session.id&&event.data.type==='studio-ready')setReady(true);};window.addEventListener('message',listener);return()=>window.removeEventListener('message',listener);},[session]);
 useEffect(()=>{if(ready&&page)iframe.current?.contentWindow?.postMessage({type:'studio-init',session:session.id,document:doc,pageId:page.id,mode:'static',assetBase:session.origin+'/'},session.origin);},[ready,page?.id,doc,session]);
 const scale=page?Math.min(220/page.width,124/page.height):1;
 return <div className="dp-next"><small>{t('下一页')}</small>{page?<><div className="dp-thumbnail" style={{width:page.width*scale,height:page.height*scale}}><iframe ref={iframe} title={t('下一页缩略图')} src={session.origin+'/Design/studio/runtime.html?'+new URLSearchParams({session:session.id,parentOrigin:location.origin})} sandbox="allow-scripts allow-same-origin" inert tabIndex={-1} style={{width:page.width,height:page.height,transform:`scale(${scale})`}}/></div><span>{page.name}</span></>:<span>{t('已到最后一页')}</span>}</div>;
}

export function DesignPresenterConsole(props:Props){
 const [deck,setDeck]=useState(props.document);
 const api=window.leafloomDesktop!.presenter,id=useRef(''),listeners=useRef(new Set<(event:PresenterEvent)=>void>()),closing=useRef(false),started=useRef(false);
 const [displays,setDisplays]=useState<PresenterDisplay[]>([]),[displayId,setDisplayId]=useState(0),[controllerDisplayId,setControllerDisplayId]=useState<number|null>(null),[allPages,setAllPages]=useState(false),[running,setRunning]=useState(false),[starting,setStarting]=useState(false),[error,setError]=useState(''),[suspended,setSuspended]=useState(false),[state,setState]=useState<PresenterState>({pageId:props.pageId}),[width,setWidth]=useState(60),[font,setFont]=useState(22),[editing,setEditing]=useState(false),[follow,setFollow]=useState(true),[editKey,setEditKey]=useState('overview'),[seconds,setSeconds]=useState(0);
 const root=useRef<HTMLDivElement>(null),notesScroll=useRef<HTMLDivElement>(null),autosave=useRef<ReturnType<typeof setTimeout>|undefined>(undefined),latest=useRef(props),draftKey='leafloom-presenter-notes:'+JSON.stringify([props.root,props.directory]);latest.current=props;
 const [drafts,setDrafts]=useState<Record<string,PresenterNotes>>(()=>{try{return JSON.parse(localStorage.getItem(draftKey)||'{}');}catch{return {};}}),draftRef=useRef(drafts);draftRef.current=drafts;
 const currentPage=deck.pages.find(page=>page.id===state.pageId)||deck.pages.find(page=>page.id===props.pageId)!;
 const group=deck.pages.find(page=>page.id===props.pageId)?.group;
 const pages=useMemo(()=>allPages||!group?deck.pages:deck.pages.filter(page=>page.group===group),[deck,allPages,group]);
 const pageIndex=pages.findIndex(page=>page.id===currentPage.id),nextPage=pages[pageIndex+1],cueKey=state.contextId||state.stepId||'';
 const saved=props.notes.find(page=>page.id===currentPage.id)?.presenterNotes||blank(),rawNotes=drafts[currentPage.id]||saved,notes={overview:rawNotes.overview||'',cues:rawNotes.cues||{}};
 const noteText=(key:string)=>key==='overview'?notes.overview:Object.hasOwn(notes.cues,key)&&typeof notes.cues[key]==='string'?notes.cues[key]:'';
 const subscribe=useCallback((fn:(event:PresenterEvent)=>void)=>{listeners.current.add(fn);return()=>{listeners.current.delete(fn);};},[]);
 const sessionId=useCallback(()=>id.current,[]);
 const command=useCallback((value:PresenterCommand)=>{if(id.current)void api.command(id.current,value).catch(reason=>setError(reason.message));},[api]);
 const input=useCallback((value:PresenterInput)=>{if(id.current)void api.input(id.current,value).catch(reason=>setError(reason.message));},[api]);
 useEffect(()=>{
  const off=api.subscribe(event=>{
   if(event.type==='displays'){setDisplays(event.displays||[]);return;}
   if(id.current&&event.id!==id.current)return;if(!id.current&&event.id&&started.current&&event.type!=='ended')id.current=event.id;
   if(event.type==='state'){setState(event.state||{});setSuspended(!!event.suspended);if(event.suspended)setError(t('观众输出已暂停，请重新选择屏幕后恢复。'));}
   if(event.type==='ended'&&!closing.current){setRunning(false);started.current=false;id.current='';setError(t('演示已结束'));}
   listeners.current.forEach(fn=>fn(event));
  });
  void api.displays().then(items=>{setDisplays(items);setDisplayId((items.find(item=>!item.current)||items[0])?.id||0);}).catch(reason=>setError(reason.message));
  return()=>{off();if(id.current)void api.stop(id.current).catch(()=>{});};
 },[api]);
 useEffect(()=>{if(!running)return;const timer=setInterval(()=>void api.heartbeat(id.current).catch(()=>{setSuspended(true);setError(t('控制连接已断开，讲稿已保留。'));}),2000);return()=>clearInterval(timer);},[running,api]);
 useEffect(()=>{if(!running||state.paused||suspended)return;const timer=setInterval(()=>setSeconds(value=>value+1),1000);return()=>clearInterval(timer);},[running,state.paused,suspended]);
 const flush=useCallback(()=>{
  clearTimeout(autosave.current);const entries=Object.entries(draftRef.current).filter(([pageId,notes])=>JSON.stringify(notes)!==JSON.stringify(latest.current.notes.find(page=>page.id===pageId)?.presenterNotes||blank()));
  if(entries.length)return latest.current.commit(entries.map(([pageId,presenterNotes])=>({type:'page.update',page_id:pageId,patch:{presenterNotes}})),t('编辑演示讲稿'));
  return true;
 },[]);
 useEffect(()=>{
  const remaining=Object.fromEntries(Object.entries(draftRef.current).filter(([pageId,notes])=>JSON.stringify(notes)!==JSON.stringify(props.notes.find(page=>page.id===pageId)?.presenterNotes||blank())));
  if(Object.keys(remaining).length!==Object.keys(draftRef.current).length){draftRef.current=remaining;setDrafts(remaining);try{localStorage.setItem(draftKey,JSON.stringify(remaining));}catch{}}
 },[props.notes,draftKey]);
 useEffect(()=>{root.current?.focus();return()=>{clearTimeout(autosave.current);};},[]);
 useEffect(()=>{setEditKey('overview');},[currentPage.id]);
 const changeNotes=(key:string,value:string)=>{
  const next={...notes,...(key==='overview'?{overview:value}:{cues:{...notes.cues,[key]:value}})},updated={...draftRef.current,[currentPage.id]:next};
  try{localStorage.setItem(draftKey,JSON.stringify(updated));}catch(reason){setError(t('讲稿草稿无法保存')+': '+String(reason));}
  draftRef.current=updated;setDrafts(updated);setFollow(false);clearTimeout(autosave.current);autosave.current=setTimeout(flush,700);
 };
 useEffect(()=>{if(!follow||editing||!cueKey)return;const container=notesScroll.current,section=container?.querySelector<HTMLElement>('[data-cue="'+CSS.escape(cueKey)+'"]');if(container&&section){container.scrollTop+=section.getBoundingClientRect().top-container.getBoundingClientRect().top-16;}},[currentPage.id,cueKey,follow,editing]);
 const markdown=useMemo(()=>createMarkdown(),[]),renderText=(text:string)=>DOMPurify.sanitize(markdown.render(text));
 const sections=[{key:'overview',label:t('整页讲稿')},...Object.keys(notes.cues||{}).map(key=>({key,label:key===cueKey?(state.contextLabel||state.label||t('当前讲解点')):key.startsWith('case:')?t('案例讲稿'):t('讲解步骤')})),...(cueKey&&!Object.hasOwn(notes.cues||{},cueKey)?[{key:cueKey,label:state.contextLabel||state.label||t('当前讲解点')}]:[])];
 const end=async()=>{if(closing.current)return;if(!flush()){setError(t('讲稿草稿无法保存'));return;}closing.current=true;if(id.current)await api.stop(id.current).catch(()=>{});props.onClose();};
 useEffect(()=>{
  const key=(event:KeyboardEvent)=>{
   if(event.key==='Tab'&&!(event.target as HTMLElement)?.closest('[data-presenter-preview]')){
    const controls=[...root.current!.querySelectorAll<HTMLElement>('button:not(:disabled),select,textarea,input,[tabindex="0"]')].filter(element=>element.getClientRects().length&&!element.closest('iframe'));
    const first=controls[0],last=controls[controls.length-1];
    if(event.type==='keydown'&&((event.shiftKey&&document.activeElement===first)||(!event.shiftKey&&document.activeElement===last))){event.preventDefault();(event.shiftKey?last:first)?.focus();return;}
   }
   if(!running||event.defaultPrevented||(event.target as HTMLElement)?.closest('textarea,input,select,[contenteditable="true"],.dp-notes'))return;
   if(event.ctrlKey||event.metaKey||['Control','Meta','Shift','Alt'].includes(event.key)||event.key.length>1&&!['Enter','Tab','Escape','Backspace','Delete','ArrowLeft','ArrowUp','ArrowRight','ArrowDown','Home','End','PageUp','PageDown'].includes(event.key))return;
   const preview=(event.target as HTMLElement)?.closest('[data-presenter-preview]');
   if(preview&&state.inputFocused){event.preventDefault();input({kind:'key',key:event.key,code:event.code,phase:event.type==='keyup'?'up':'down',shift:event.shiftKey,alt:event.altKey});return;}
   if(event.type==='keydown'&&['ArrowRight','ArrowLeft',' ','PageDown','PageUp'].includes(event.key)){event.preventDefault();command({action:['ArrowLeft','PageUp'].includes(event.key)?'previous':'next'});return;}
   if(preview&&!event.metaKey&&!event.ctrlKey){event.preventDefault();input({kind:'key',key:event.key,code:event.code,phase:event.type==='keyup'?'up':'down',shift:event.shiftKey,alt:event.altKey});}
  };
  window.addEventListener('keydown',key);window.addEventListener('keyup',key);return()=>{window.removeEventListener('keydown',key);window.removeEventListener('keyup',key);};
 },[running,state.inputFocused,command,input]);
 const begin=async()=>{
  if(started.current)return;started.current=true;setStarting(true);setError('');
  try{const display=displays.find(item=>item.id===displayId);if(!display)throw new Error(t('请选择观众屏幕'));const fresh=await props.snapshot();const first=fresh.pages.find(page=>page.id===props.pageId);if(!first)throw new Error(t('演示页面已不存在，请返回编辑重新选择'));const ordered=allPages||!first.group?fresh.pages:fresh.pages.filter(page=>page.group===first.group);setDeck(fresh);const value=await api.start({document:fresh,pageId:first.id,pageIds:ordered.map(page=>page.id),session:props.session,displayId,...(controllerDisplayId!==null?{controllerDisplayId}:{}),fullscreen:!display.current||controllerDisplayId!==null});id.current=value.id;setDisplayId(value.displayId);void api.displays().then(setDisplays);setRunning(true);root.current?.focus();}
  catch(reason){setError((reason as Error).message);started.current=false;}finally{setStarting(false);}
 };
 return <div ref={root} className="design-presenter" role="dialog" aria-modal="true" aria-label={t('演示者模式')} tabIndex={-1}>
  <header className="dp-header"><strong><Monitor size={20}/>{t('演示者模式')}</strong><span>{deck.name}</span><button onClick={()=>void end()}><X size={16}/>{t(running?'结束演示':'返回编辑')}</button></header>
  {error&&<div className="dp-notice" role="alert">{error}</div>}
  {!running?<div className="dp-setup"><h2>{t('选择观众屏幕')}</h2><p>{t('当前屏幕显示操作预览和讲稿，观众屏幕只显示课件。')}</p><div className="dp-displays">{displays.map((display,index)=><button key={display.id} className={displayId===display.id?'selected':''} onClick={()=>{setDisplayId(display.id);setControllerDisplayId(null);}}><Monitor size={40}/><strong>{index+1} · {display.label}</strong><span>{display.bounds.width} × {display.bounds.height} · {display.scaleFactor}×</span><small>{t(display.id===controllerDisplayId?'演示者控制台':display.current&&controllerDisplayId===null?'当前屏幕 · 独立窗口预演':'观众屏幕 · 原生全屏')}</small></button>)}</div><div className="dp-setup-actions"><button onClick={()=>void api.identify().catch(reason=>setError(reason.message))}>{t('识别屏幕')}</button><button disabled={displays.length<2} onClick={()=>{if(controllerDisplayId!==null){setDisplayId(controllerDisplayId);setControllerDisplayId(null);}else{const current=displays.find(display=>display.current),other=displays.find(display=>display.id===displayId&&!display.current)||displays.find(display=>!display.current);if(current&&other){setControllerDisplayId(other.id);setDisplayId(current.id);}}}}>{t('交换屏幕')}</button>{group&&<label><input type="checkbox" checked={allPages} onChange={event=>setAllPages(event.target.checked)}/>{t('播放全部页面')} <small>{allPages?deck.pages.length:pages.length}</small></label>}</div><button className="primary" disabled={starting||!displays.length||props.pending||!!props.error} onClick={()=>void begin()}><Play size={16}/>{t(starting?'正在启动…':'开始演示')}</button>{Object.keys(drafts).length>0&&<p>{t('已恢复未保存的讲稿草稿')} <button onClick={flush}>{t('保存讲稿')}</button></p>}</div>:<>
   {suspended&&<div className="dp-reconnect"><select aria-label={t('观众屏幕')} value={displayId} onChange={event=>setDisplayId(Number(event.target.value))}>{displays.map((display,index)=><option key={display.id} value={display.id}>{index+1} · {display.label}</option>)}</select><button onClick={()=>{setError('');command({action:'reopen',displayId});}}>{t('重新连接观众屏幕')}</button></div>}
   <main className="dp-main" style={{gridTemplateColumns:`minmax(0,${width}fr) 8px minmax(0,${100-width}fr)`}}>
    <section className="dp-view"><div className="dp-view-label"><strong>{t('观众实时画面')}</strong><span>{t(state.paused?'已暂停':state.playing?'视频播放中':'点击、拖动和滚动直接控制观众画面')}</span></div><OperationPreview api={api} sessionId={sessionId} subscribe={subscribe} input={input} paused={!!state.paused||suspended}/><div className="dp-live-state"><strong>{state.contextLabel||state.label||currentPage.name}</strong>{state.parameter&&<span>{state.parameter}</span>}</div></section>
    <div className="dp-resize" role="separator" aria-label={t('调整预览与讲稿宽度')} aria-orientation="vertical" aria-valuemin={35} aria-valuemax={75} aria-valuenow={width} tabIndex={0} onKeyDown={event=>{if(['ArrowLeft','ArrowRight'].includes(event.key)){event.stopPropagation();event.preventDefault();setWidth(value=>Math.max(35,Math.min(75,value+(event.key==='ArrowLeft'?-2:2))));}}} onPointerDown={event=>{event.currentTarget.setPointerCapture(event.pointerId);}} onPointerMove={event=>{if(event.currentTarget.hasPointerCapture(event.pointerId)){const box=event.currentTarget.parentElement!.getBoundingClientRect();setWidth(Math.max(35,Math.min(75,(event.clientX-box.left)/box.width*100)));}}} onPointerUp={event=>event.currentTarget.releasePointerCapture(event.pointerId)}/>
    <section className="dp-notes"><div className="dp-notes-toolbar"><strong>{t('讲稿')}</strong><span role="status">{props.error?t('保存失败，草稿已保留'):props.pending||Object.keys(drafts).length?t('正在保存…'):t('已保存')}</span><button className={editing?'selected':''} onClick={()=>{setEditing(value=>!value);setFollow(false);setEditKey(cueKey||'overview');}}>{t(editing?'阅读':'编辑')}</button><button aria-label={t('缩小讲稿字号')} onClick={()=>setFont(value=>Math.max(14,value-2))}>A−</button><button aria-label={t('放大讲稿字号')} onClick={()=>setFont(value=>Math.min(40,value+2))}>A+</button></div>
     <div className="dp-follow"><button className={follow?'selected':''} onClick={()=>{setFollow(true);setEditing(false);}}>{t(follow?'跟随当前步骤':'继续跟随')}</button><small>{state.contextLabel||state.label||t('整页讲稿')}</small></div>
     <div className="dp-note-content" ref={notesScroll} style={{fontSize:font}} onWheel={()=>setFollow(false)} onTouchStart={()=>setFollow(false)} onPointerDown={event=>{if(event.clientX>=event.currentTarget.getBoundingClientRect().right-18)setFollow(false);}} onKeyDown={event=>{if(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(event.key))setFollow(false);}}>
      {editing?<><label>{t('讲稿段落')}<select value={editKey} onChange={event=>setEditKey(event.target.value)}>{sections.map((section,index)=><option key={section.key} value={section.key}>{index?index+' · ':''}{section.label}</option>)}</select></label><textarea aria-label={t('编辑演示讲稿')} value={noteText(editKey)} onChange={event=>changeNotes(editKey,event.target.value)} spellCheck={false}/></>:sections.map((section,index)=><article key={section.key} data-cue={section.key} className={section.key===cueKey?'is-current':''}><h3>{index?index+' · ':''}{section.label}</h3>{noteText(section.key)?<div dangerouslySetInnerHTML={{__html:renderText(noteText(section.key))}}/>:<p className="dp-empty">{t('暂无讲稿，可切换到编辑添加。')}</p>}</article>)}
     </div>{props.error&&<div className="dp-notice">{props.error}<button onClick={props.retry}>{t('重试保存')}</button></div>}
    </section>
   </main>
   <footer className="dp-footer"><NextPage document={deck} page={nextPage} session={props.session}/><div className="dp-navigation"><div><button disabled={pageIndex<=0||suspended} onClick={()=>command({action:'page',pageId:pages[pageIndex-1]?.id})}>{t('上一页')}</button><select aria-label={t('页面目录')} value={currentPage.id} onChange={event=>command({action:'page',pageId:event.target.value})}>{pages.map((page,index)=><option key={page.id} value={page.id}>{index+1} · {page.name}</option>)}</select><button disabled={!nextPage||suspended} onClick={()=>command({action:'page',pageId:nextPage?.id})}>{t('下一页')}</button></div><div><button disabled={suspended||!!state.paused} onClick={()=>command({action:'previous'})}><ArrowLeft size={16}/>{t('上一步')}</button><strong>{pageIndex+1} / {pages.length} <small>{state.supported?`${(state.stepIndex||0)+1} / ${state.stepCount||1}`:t('整页播放')}</small></strong><button className="primary" disabled={suspended||!!state.paused} onClick={()=>command({action:'next'})}>{t('下一步')}<ArrowRight size={16}/></button></div></div><div className="dp-playback"><output aria-label={t('演示计时')}>{String(Math.floor(seconds/60)).padStart(2,'0')}:{String(seconds%60).padStart(2,'0')}</output><button disabled={suspended||!!state.black} onClick={()=>command({action:state.paused?'resume':'pause'})}>{state.paused?<Play size={16}/>:<Pause size={16}/>} {t(state.paused?'继续播放':'暂停')}</button><button disabled={suspended} className={state.black?'selected':''} onClick={()=>command({action:'black',enabled:!state.black})}><Square size={16}/>{t(state.black?'恢复画面':'黑屏')}</button><button disabled={displays.length<2||suspended} onClick={()=>command({action:'swap'})}>{t('交换屏幕')}</button></div></footer>
  </>}
 </div>;
}
