import React,{memo,useEffect,useMemo,useRef} from 'react';
import DOMPurify from 'dompurify';
import {VirtualList,VirtualTableBody} from './virtual';
export type ReadingJump={nonce:number,needle:string,occurrence:number,label?:string};
const count=(text:string,needle:string)=>needle?text.toLocaleLowerCase().split(needle.toLocaleLowerCase()).length-1:0;
export const HtmlBlock=memo(function HtmlBlock({html,jump,editable=false}:{html:string,jump?:ReadingJump,editable?:boolean}){
 const ref=useRef<HTMLDivElement>(null);
 const content=useMemo(()=>{
  const clean=DOMPurify.sanitize(editable?html:html.replace(/<input\b/g,'<input disabled'),{ADD_ATTR:['data-note','data-embed','data-vault-src','data-task']});
  if(!/^<(ul|ol|table)[ >]/.test(clean))return {clean};
  const first=new DOMParser().parseFromString(clean,'text/html').body.firstElementChild;
  const items=first?.tagName==='TABLE'?Array.from(first.querySelectorAll(':scope > tbody > tr')):Array.from(first?.children||[]);
  if(items.length<=200)return {clean};
  return {clean,tag:first!.tagName,items:items.map((element,index)=>({html:element.outerHTML,index,text:element.textContent||''})),header:first?.querySelector('thead')?.innerHTML,columns:items[0]?.children.length||1};
 },[html,editable]);
 const location=useMemo(()=>{
  let occurrence=jump?.occurrence||0;
  if(jump&&content.items)for(const item of content.items){const matches=count(item.text,jump.needle);if(matches>occurrence)return {index:item.index,occurrence};occurrence-=matches;}
  return {index:undefined,occurrence:jump?.occurrence||0};
 },[content,jump]);
 useEffect(()=>{
  if(!jump)return;let attempt=0,frame=0;
  const highlight=()=>{
   const element=ref.current;if(!element)return;
   if(jump.label){const heading=Array.from(element.querySelectorAll('h1,h2,h3,h4,h5,h6,p,li')).find(node=>jump.label!.startsWith('^')?node.textContent?.trim().endsWith(jump.label!):node.textContent===jump.label)||element.querySelector('h1,h2,h3,h4,h5,h6')||element.firstElementChild;if(heading){heading.scrollIntoView({block:'start'});return;}}
   const target=location.index===undefined?element:element.querySelector(`[data-index="${location.index}"]`);
   if(target&&jump.needle){const walker=document.createTreeWalker(target,NodeFilter.SHOW_TEXT);let node:Node|null,remaining=location.occurrence;const needle=jump.needle.toLocaleLowerCase();
    while((node=walker.nextNode())){const text=node.textContent?.toLocaleLowerCase()||'';let at=0;while((at=text.indexOf(needle,at))>=0){if(remaining--===0){const range=document.createRange();range.setStart(node,at);range.setEnd(node,at+jump.needle.length);window.getSelection()?.removeAllRanges();window.getSelection()?.addRange(range);node.parentElement?.scrollIntoView({block:'center'});return;}at+=needle.length;}}}
   if(attempt++<10)frame=requestAnimationFrame(highlight);
  };frame=requestAnimationFrame(highlight);return()=>cancelAnimationFrame(frame);
 },[jump,location]);
 if(!content.items)return <div ref={ref} className="markdown-section" dangerouslySetInnerHTML={{__html:content.clean}}/>;
 return <div ref={ref} className="markdown-section">{content.tag==='TABLE'?<div className="table-scroll"><table>{content.header&&<thead dangerouslySetInnerHTML={{__html:content.header}}/>}<VirtualTableBody items={content.items} scrollIndex={location.index} itemKey={item=>String(item.index)} columns={content.columns!} render={(row,index)=><tr data-index={index} dangerouslySetInnerHTML={{__html:row.html.replace(/^<tr>|<\/tr>$/g,'')}}/>}/></table></div>:<VirtualList items={content.items} scrollIndex={location.index} itemKey={item=>String(item.index)} estimate={32} render={item=>content.tag==='OL'?<ol start={item.index+1} dangerouslySetInnerHTML={{__html:item.html}}/>:<ul dangerouslySetInnerHTML={{__html:item.html}}/>}/>}</div>;
});
