import React,{useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {ArrowLeft,ArrowRight,MoreHorizontal,Plus} from 'lucide-react';
import {t,useLocale} from './i18n';
import {ActionMenu,MenuPoint} from './ui';
import {BaseConfig,View} from './database-model';
import {ViewIcon} from './database-ui';

const labels:Record<string,string>={table:'db.table',list:'db.list',cards:'db.gallery',leafloomTimeline:'db.timeline',leafloomBoard:'db.board'};
export const viewLabel=(v:View)=>['Table','List','Gallery','Timeline','Board'].includes(v.name)?t(labels[v.type]||v.name):v.name;
type Position={id:string,after:boolean};
function reordered(ids:string[],id:string,position:Position){
 if(position.id===id)return ids;
 const next=ids.filter(v=>v!==id),at=next.indexOf(position.id);
 if(at<0)return ids;next.splice(at+(position.after?1:0),0,id);return next;
}

export function DatabaseViewTabs({config,activeId,busy,select,add,commit,notify}:{config:BaseConfig,activeId:string,busy:boolean,select:(id:string)=>void,add:()=>void,commit:(command:any)=>Promise<any>,notify:(message:string)=>void}){
 useLocale();
 const host=useRef<HTMLElement>(null),cleanup=useRef<()=>void>(()=>{}),alive=useRef(true),saving=useRef(false),suppressClick=useRef(false);
 const [pending,setPending]=useState<string[]>(),[drag,setDrag]=useState<{id:string,x:number,y:number}>(),[position,setPosition]=useState<Position>(),[menu,setMenu]=useState<{id:string,anchor:HTMLElement,point?:MenuPoint}>();
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;cleanup.current();};},[]);
 useEffect(()=>{cleanup.current();setMenu(undefined);},[config.revision]);
 const ids=config.views.map(v=>v.id),ordered=(pending||ids).map(id=>config.views.find(v=>v.id===id)).filter((v):v is View=>!!v);
 const blocked=busy||!!pending;
 const move=async(id:string,target:Position,revision=config.revision)=>{
  if(busy||saving.current)return;
  const next=reordered(ids,id,target);if(next.join('\n')===ids.join('\n'))return;
  saving.current=true;setPending(next);setMenu(undefined);select(activeId);
  try{await commit({type:'view.move',view_id:id,[target.after?'after_view_id':'before_view_id']:target.id,config_revision:revision});}
  catch(error){if(alive.current)notify(t((error as Error).message));}
  finally{saving.current=false;if(alive.current)setPending(undefined);}
 };
 const neighbor=(id:string,delta:number)=>{const at=ids.indexOf(id),target=ids[at+delta];if(target)void move(id,{id:target,after:delta>0});};
 const openMenu=(id:string,anchor:HTMLElement,point?:MenuPoint)=>{cleanup.current();setMenu({id,anchor,point});};
 const start=(event:React.PointerEvent<HTMLButtonElement>,id:string)=>{
  if(blocked||event.button!==0||!event.isPrimary||event.pointerType==='touch')return;
  cleanup.current();suppressClick.current=false;
  const nav=host.current!,owner=nav.ownerDocument,pointer=event.pointerId,revision=config.revision,startX=event.clientX,startY=event.clientY;
  let x=startX,y=startY,active=false,frame=0,target:Position|undefined;
  const locate=()=>{
   const box=nav.getBoundingClientRect(),node=owner.elementFromPoint(x,y)?.closest<HTMLElement>('[data-view-id]');
   target=node&&nav.contains(node)&&y>=box.top-8&&y<=box.bottom+8?{id:node.dataset.viewId!,after:x>node.getBoundingClientRect().left+node.offsetWidth/2}:undefined;
   setPosition(target);setDrag({id,x,y});
  };
  const scroll=()=>{const box=nav.getBoundingClientRect();if(x<box.left+32)nav.scrollLeft-=10;else if(x>box.right-32)nav.scrollLeft+=10;locate();frame=requestAnimationFrame(scroll);};
  const moving=(next:PointerEvent)=>{
   if(next.pointerId!==pointer)return;x=next.clientX;y=next.clientY;
   if(!active){if(Math.abs(y-startY)>10&&Math.abs(y-startY)>Math.abs(x-startX)){cancel();return;}if(Math.abs(x-startX)<6)return;active=true;suppressClick.current=true;setMenu(undefined);frame=requestAnimationFrame(scroll);}
   next.preventDefault();locate();
  };
  const clear=()=>{cancelAnimationFrame(frame);owner.removeEventListener('pointermove',moving,true);owner.removeEventListener('pointerup',finish,true);owner.removeEventListener('pointercancel',cancel,true);owner.removeEventListener('keydown',key,true);window.removeEventListener('blur',cancel);if(alive.current){setDrag(undefined);setPosition(undefined);}cleanup.current=()=>{};setTimeout(()=>{suppressClick.current=false;},0);};
  const cancel=()=>clear();
  const key=(next:KeyboardEvent)=>{if(next.key==='Escape'){next.preventDefault();next.stopPropagation();cancel();}};
  const finish=(next:PointerEvent)=>{if(next.pointerId!==pointer)return;const destination=target;clear();if(active&&destination)void move(id,destination,revision);};
  owner.addEventListener('pointermove',moving,{capture:true,passive:false});owner.addEventListener('pointerup',finish,true);owner.addEventListener('pointercancel',cancel,true);owner.addEventListener('keydown',key,true);window.addEventListener('blur',cancel);cleanup.current=clear;
 };
 const movingView=config.views.find(v=>v.id===drag?.id),menuIndex=ids.indexOf(menu?.id||'');
 return <><nav ref={host} className={'db-view-tabs'+(drag?' is-dragging':'')} aria-label={t('db.views')} aria-busy={!!pending}>
  {ordered.map(v=><div key={v.id} data-view-id={v.id} className={'db-view-tab'+(activeId===v.id?' is-active':'')+(drag?.id===v.id?' is-drag-source':'')+(position?.id===v.id&&drag?.id!==v.id?' insert-'+(position.after?'after':'before'):'')}>
   <button className={'db-view-tab-main'+(activeId===v.id?' active':'')} aria-pressed={activeId===v.id} title={t('db.viewReorderHint')} onPointerDown={e=>start(e,v.id)} onClick={e=>{if(suppressClick.current){suppressClick.current=false;e.preventDefault();return;}select(v.id);}} onContextMenu={e=>{e.preventDefault();e.stopPropagation();openMenu(v.id,e.currentTarget,{x:e.clientX,y:e.clientY});}} onKeyDown={e=>{if(e.altKey&&['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();e.stopPropagation();if(!blocked)neighbor(v.id,e.key==='ArrowLeft'?-1:1);}else if(e.key==='ContextMenu'||e.shiftKey&&e.key==='F10'){e.preventDefault();e.stopPropagation();openMenu(v.id,e.currentTarget);}}}><ViewIcon type={v.type}/><span>{viewLabel(v)}</span></button>
   <button className="db-view-tab-menu" aria-label={t('db.viewActions')+' '+viewLabel(v)} title={t('db.viewActions')} aria-haspopup="menu" aria-expanded={menu?.id===v.id} onClick={e=>openMenu(v.id,e.currentTarget)}><MoreHorizontal size={13}/></button>
  </div>)}<button className="db-add-view" title={t('db.addView')} aria-label={t('db.addView')} onClick={add}><Plus size={16}/></button>
 </nav>
 {menu&&<ActionMenu title={t('db.viewActions')} className="db-record-menu db-view-menu" anchor={menu.anchor} point={menu.point} onClose={()=>setMenu(undefined)}>{[-1,1].map(delta=><button key={delta} disabled={blocked||menuIndex+delta<0||menuIndex+delta>=ids.length} onClick={()=>neighbor(menu.id,delta)}>{delta<0?<ArrowLeft size={14}/>:<ArrowRight size={14}/>} {t(delta<0?'db.viewLeft':'db.viewRight')}</button>)}</ActionMenu>}
 {drag&&movingView&&createPortal(<div className="db-view-drag-overlay" aria-hidden="true" style={{left:drag.x+12,top:drag.y+14}}><ViewIcon type={movingView.type}/>{viewLabel(movingView)}</div>,document.body)}
 </>;
}
