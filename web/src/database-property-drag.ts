import {useEffect,useRef,useState} from 'react';
import type {PointerEvent as ReactPointerEvent,RefObject} from 'react';

export type PropertySection='visible'|'extra';
export type PropertyPosition={key:string,after:boolean};
export function reorderProperty(keys:string[],key:string,position:PropertyPosition){
 if(key===position.key)return keys;
 const next=keys.filter(k=>k!==key),at=next.indexOf(position.key);
 if(at<0)return keys;next.splice(at+(position.after?1:0),0,key);return next;
}
export function usePropertyDrag(host:RefObject<HTMLDivElement|null>,scope:string,blocked:boolean,save:(section:PropertySection,keys:string[])=>void){
 const cleanup=useRef<()=>void>(()=>{}),alive=useRef(true);
 const [drag,setDrag]=useState<{key:string,section:PropertySection,x:number,y:number}>(),[position,setPosition]=useState<PropertyPosition>();
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;cleanup.current();};},[]);
 useEffect(()=>{cleanup.current();},[scope,blocked]);
 const start=(event:ReactPointerEvent<HTMLButtonElement>,key:string,section:PropertySection,keys:string[])=>{
  if(blocked||!event.isPrimary||event.button!==0)return;
  event.preventDefault();event.stopPropagation();cleanup.current();
  const owner=event.currentTarget.ownerDocument,pointer=event.pointerId,startY=event.clientY,scroller=host.current?.closest('dialog');
  let x=event.clientX,y=startY,active=false,frame=0,target:PropertyPosition|undefined;
  const locate=()=>{const node=owner.elementFromPoint(x,y)?.closest<HTMLElement>('[data-detail-field]');target=node&&host.current?.contains(node)&&node.dataset.detailSection===section?{key:node.dataset.detailField!,after:y>node.getBoundingClientRect().top+node.offsetHeight/2}:undefined;setPosition(target);setDrag({key,section,x,y});};
  const scroll=()=>{if(scroller){const box=scroller.getBoundingClientRect();if(y<box.top+48)scroller.scrollTop-=12;else if(y>box.bottom-48)scroller.scrollTop+=12;}locate();frame=requestAnimationFrame(scroll);};
  const moving=(next:PointerEvent)=>{if(next.pointerId!==pointer)return;x=next.clientX;y=next.clientY;if(!active){if(Math.abs(y-startY)<5)return;active=true;frame=requestAnimationFrame(scroll);}next.preventDefault();locate();};
  const clear=()=>{cancelAnimationFrame(frame);owner.removeEventListener('pointermove',moving,true);owner.removeEventListener('pointerup',finish,true);owner.removeEventListener('pointercancel',cancel,true);owner.removeEventListener('keydown',keyboard,true);window.removeEventListener('blur',cancel);if(alive.current){setDrag(undefined);setPosition(undefined);}cleanup.current=()=>{};};
  const cancel=()=>clear();
  const keyboard=(next:KeyboardEvent)=>{if(next.key==='Escape'){next.preventDefault();next.stopPropagation();clear();}};
  const finish=(next:PointerEvent)=>{if(next.pointerId!==pointer)return;const destination=target;clear();if(active&&destination){const ordered=reorderProperty(keys,key,destination);if(ordered.some((k,i)=>k!==keys[i]))save(section,ordered);}};
  owner.addEventListener('pointermove',moving,{capture:true,passive:false});owner.addEventListener('pointerup',finish,true);owner.addEventListener('pointercancel',cancel,true);owner.addEventListener('keydown',keyboard,true);window.addEventListener('blur',cancel);cleanup.current=clear;
 };
 return {drag,position,start,cancel:()=>cleanup.current()};
}
