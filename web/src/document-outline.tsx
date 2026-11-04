import {useEffect,useMemo,useRef,useState} from 'react';
import type {Ref} from 'react';
import {ChevronDown,ChevronRight,ChevronsLeft,List} from 'lucide-react';
import {t,useLocale} from './i18n';
import type {DocumentHeading} from './rich-markdown';
import {VirtualList} from './virtual';
import './document-outline.css';

type OutlineRow=DocumentHeading&{key:string,parents:string[],hasChildren:boolean};

export function DocumentOutline({id,headings,compact,expanded,current,toggleRef,onJump,onToggle}:{id:string,headings:DocumentHeading[],compact:boolean,expanded:boolean,current?:number,toggleRef:Ref<HTMLButtonElement>,onJump:(heading:DocumentHeading,keepOutline?:boolean)=>void,onToggle:()=>void}){
 useLocale();
 const list=useRef<HTMLDivElement>(null),minimum=headings.reduce((depth,heading)=>Math.min(depth,heading.depth),6);
 const [folded,setFolded]=useState<Set<string>>(()=>new Set());
 const rows=useMemo(()=>{
  const stack:OutlineRow[]=[],counts=new Map<string,number>();
  return headings.map((heading,index)=>{
   while(stack.length&&stack.at(-1)!.depth>=heading.depth)stack.pop();
   // Text edits above a section must not reset its folding. Occurrence numbers
   // distinguish same-named headings without putting IDs into the note.
   const signature=JSON.stringify([heading.depth,heading.label]),occurrence=counts.get(signature)||0;
   counts.set(signature,occurrence+1);
   const row={...heading,key:JSON.stringify([signature,occurrence]),parents:stack.map(parent=>parent.key),hasChildren:!!headings[index+1]&&headings[index+1].depth>heading.depth};
   stack.push(row);return row;
  });
 },[headings]);
 const visibleRows=useMemo(()=>rows.filter(row=>row.parents.every(key=>!folded.has(key))),[rows,folded]);
 const currentRow=rows.find(row=>row.pos===current),currentKey=currentRow?.parents.find(key=>folded.has(key))||currentRow?.key;
 const index=visibleRows.findIndex(row=>row.key===currentKey);
 const followed=useRef<{current?:number,expanded:boolean}|undefined>(undefined);
 const followCurrent=followed.current?.current!==current||followed.current?.expanded!==expanded;
 useEffect(()=>{followed.current={current,expanded};},[current,expanded]);
 const toggleSection=(key:string,restoreFocus=true)=>{
  setFolded(previous=>{const next=new Set(previous);if(next.has(key))next.delete(key);else next.add(key);return next;});
  // Virtualization may change its row wrappers when folding a long directory.
  if(restoreFocus)requestAnimationFrame(()=>Array.from(list.current?.querySelectorAll<HTMLButtonElement>('.document-outline-fold')||[]).find(button=>button.dataset.headingKey===key)?.focus({preventScroll:true}));
 };
 useEffect(()=>{
  // Follow the reading position inside the outline without scrolling the page.
  const container=list.current,item=container?.querySelector<HTMLElement>('[aria-current="location"]');
  if(!expanded||!container||!item||visibleRows.length>200)return;
  const box=container.getBoundingClientRect(),row=item.getBoundingClientRect();
  if(row.top<box.top)container.scrollTop+=row.top-box.top;
  else if(row.bottom>box.bottom)container.scrollTop+=row.bottom-box.bottom;
 },[current,expanded,headings]);
 return <nav id={id} className={'document-outline'+(expanded?' is-expanded':' is-collapsed')+(compact&&expanded?' is-overlay':'')} aria-label={t('document.outline')}>
  <div className="document-outline-controls"><button ref={toggleRef} type="button" className="document-outline-toggle" aria-label={t(expanded?'document.hideOutline':'document.showOutline')} title={t(expanded?'document.hideOutline':'document.showOutline')} aria-expanded={expanded} aria-controls={expanded?id+'-list':undefined} onClick={onToggle}>{expanded?<ChevronsLeft size={19}/>:<List size={19}/>}</button></div>
  {expanded&&<div ref={list} id={id+'-list'} className="document-outline-list">{headings.length?<VirtualList items={visibleRows} itemKey={heading=>heading.key} estimate={32} height="100%" scrollIndex={followCurrent&&index>=0?index:undefined} render={heading=><div className="document-outline-row" style={{paddingLeft:8+(heading.depth-minimum)*14}}>
   {heading.hasChildren?<button type="button" className="document-outline-fold" data-heading-key={heading.key} aria-expanded={!folded.has(heading.key)} aria-label={t(folded.has(heading.key)?'document.expandSection':'document.collapseSection',{title:heading.label||t('暂无标题')})} title={t(folded.has(heading.key)?'document.expandSection':'document.collapseSection',{title:heading.label||t('暂无标题')})} onClick={()=>toggleSection(heading.key)}>{folded.has(heading.key)?<ChevronRight size={14}/>:<ChevronDown size={14}/>}</button>:<span className="document-outline-fold-space" aria-hidden="true"/>}
   <button type="button" className={'document-outline-entry'+(heading.depth===minimum?' is-top-level':'')} aria-current={heading.key===currentKey?'location':undefined} aria-expanded={heading.hasChildren?!folded.has(heading.key):undefined} title={heading.hasChildren?t(folded.has(heading.key)?'document.expandSection':'document.collapseSection',{title:heading.label||t('暂无标题')}):heading.label||t('暂无标题')} onClick={()=>{if(heading.hasChildren)toggleSection(heading.key,false);onJump(heading,heading.hasChildren);}}>{heading.label||t('暂无标题')}</button>
  </div>}/>:<p className="document-outline-empty">{t('document.emptyOutline')}</p>}</div>}
 </nav>;
}
