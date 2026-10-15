import React,{useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Editor,Extension,mergeAttributes,nodeInputRule,Node as TiptapNode} from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import {Table,TableRow,TableHeader,TableCell} from '@tiptap/extension-table';
import TaskList from '@tiptap/extension-task-list';
import TaskItem from '@tiptap/extension-task-item';
import {BulletList,OrderedList} from '@tiptap/extension-list';
import Code from '@tiptap/extension-code';
import {Plugin} from '@tiptap/pm/state';
import {Decoration,DecorationSet} from '@tiptap/pm/view';
import type {Node as PMNode} from '@tiptap/pm/model';
import {api,media,OpenNote} from './api';
import {t,useLocale} from './i18n';
import {MarkdownPreview} from './reader';
import {richId} from './rich-markdown';
import {richAnchorPlugin} from './rich-anchors';

export type SpecialActions={path:string,onOpen:OpenNote,onEdit:(pos:number,node:PMNode)=>void,onSource:(pos:number)=>void};
function SpecialPreview({node,pos,actions}:{node:PMNode,pos:()=>number|undefined,actions:SpecialActions}){
 useLocale();const host=useRef<HTMLDivElement>(null),[visible,setVisible]=useState(false);
 const {kind,raw,content}=node.attrs;
 useEffect(()=>{const element=host.current;if(!element)return;const observer=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting)){setVisible(true);observer.disconnect();}},{root:element.closest('.writing-area'),rootMargin:'500px'});observer.observe(element);return()=>observer.disconnect();},[]);
 if(kind==='definitions')return null;
 const label=kind==='math'?t('公式'):kind==='mermaid'?t('Mermaid 图表'):kind==='query'?t('查询'):kind==='embed'?t('嵌入笔记'):t('保留的原文内容');
 return <div ref={host} className={'rich-special-body rich-special-'+kind}>
  <div className="rich-special-tools"><span>{label}</span><button type="button" onClick={()=>{const at=pos();if(at!==undefined)actions.onSource(at);}}>{t('查看源码')}</button>{['math','mermaid','query'].includes(kind)&&<button type="button" onClick={()=>{const at=pos();if(at!==undefined)actions.onEdit(at,node);}}>{t('修改')}</button>}</div>
  {visible?<MarkdownPreview text={raw||content} path={actions.path} onOpen={actions.onOpen}/>:<div className="rich-special-placeholder">{label}</div>}
 </div>;
}
function sourceIds(){return Extension.create({
 name:'leafloomSourceIds',
 addGlobalAttributes(){return [{types:['paragraph','heading','blockquote','bulletList','orderedList','taskList','codeBlock','horizontalRule','table','specialBlock'],attributes:{sourceId:{default:null,rendered:false}}}];},
 addProseMirrorPlugins(){return [new Plugin({appendTransaction(transactions,_old,state){
  if(!transactions.some(tr=>tr.docChanged))return null;
  const seen=new Set<string>(),tr=state.tr;state.doc.forEach((node,pos)=>{const id=node.attrs.sourceId;if(!id||seen.has(id)){const next=id?String(id).split('~')[0]+'~'+richId():richId();tr.setNodeMarkup(pos,undefined,{...node.attrs,sourceId:next});seen.add(next);}else seen.add(id);});
  return tr.docChanged?tr.setMeta('addToHistory',false):null;
 }})];}
});}
const tableCellAttributes=function(this:any){return {...this.parent?.(),align:{default:null,parseHTML:(element:HTMLElement)=>element.style.textAlign||null,renderHTML:(attrs:Record<string,any>)=>attrs.align?{style:'text-align: '+attrs.align}:{}}};};
const Cell=TableCell.extend({content:'paragraph',addAttributes:tableCellAttributes});
const Header=TableHeader.extend({content:'paragraph',addAttributes:tableCellAttributes});
export function richExtensions(actions:SpecialActions){
 const SpecialBlock=TiptapNode.create({
  name:'specialBlock',group:'block',atom:true,selectable:true,draggable:true,
  addAttributes(){return {kind:{default:'protected'},raw:{default:''},content:{default:''}};},
  parseHTML(){return [{tag:'div[data-vault-block]',getAttrs:element=>({kind:(element as HTMLElement).dataset.vaultBlock,raw:(element as HTMLElement).dataset.vaultRaw,content:(element as HTMLElement).dataset.vaultContent})}];},
  renderHTML({node}){return ['div',{'data-vault-block':node.attrs.kind,'data-vault-raw':node.attrs.raw,'data-vault-content':node.attrs.content},node.attrs.content];},
  addNodeView(){return ({node,getPos})=>{
   const dom=document.createElement('div');dom.className='rich-special';dom.contentEditable='false';const root=createRoot(dom);
   const render=(value:PMNode)=>{dom.dataset.kind=value.attrs.kind;root.render(<SpecialPreview node={value} pos={getPos} actions={actions}/>);};render(node);
   return {dom,update(next){if(next.type.name!=='specialBlock')return false;render(next);return true;},stopEvent:event=>!!(event.target as HTMLElement).closest('button,a,input,video,audio,iframe'),ignoreMutation:()=>true,destroy(){queueMicrotask(()=>root.unmount());}};
  };}
 });
 const WikiLink=TiptapNode.create({
  name:'wikiLink',group:'inline',inline:true,atom:true,selectable:true,
  addAttributes(){return {target:{default:''},label:{default:''}};},
  parseHTML(){return [{tag:'a[data-wiki-target]',getAttrs:element=>({target:(element as HTMLElement).dataset.wikiTarget,label:element.textContent})}];},
  renderHTML({node}){return ['a',{'data-wiki-target':node.attrs.target,href:'#',class:'wikilink'},node.attrs.label||node.attrs.target];},
  addInputRules(){return [nodeInputRule({find:/\[\[([^\]\n]+)\]\]$/,type:this.type,getAttributes:match=>{const [target,...alias]=match[1].split('|');return {target,label:alias.join('|')||target.split('/').pop()||target};}})];}
 });
 const InlineMath=TiptapNode.create({
  name:'inlineMath',group:'inline',inline:true,atom:true,selectable:true,
  addAttributes(){return {formula:{default:''}};},
  parseHTML(){return [{tag:'span[data-inline-math]',getAttrs:element=>({formula:(element as HTMLElement).dataset.inlineMath})}];},
  renderHTML({node}){return ['span',{'data-inline-math':node.attrs.formula,class:'rich-inline-math'},node.attrs.formula];},
  addInputRules(){return [nodeInputRule({find:/\$([^\s$][^\n$]*?)\$$/,type:this.type,getAttributes:match=>({formula:match[1]})})];},
  addNodeView(){return ({node,getPos})=>{
   const dom=document.createElement('span');dom.contentEditable='false';dom.className='rich-inline-math';let version=0;
   const render=(value:PMNode)=>{dom.dataset.inlineMath=value.attrs.formula;const current=++version;dom.textContent=value.attrs.formula;void Promise.all([import('katex'),import('./math')]).then(([module])=>{if(current===version)module.default.render(value.attrs.formula,dom,{throwOnError:false,output:'htmlAndMathml'});});};
   render(node);dom.ondblclick=()=>{const pos=getPos();if(pos!==undefined)actions.onEdit(pos,node);};
   return {dom,update(next){if(next.type.name!=='inlineMath')return false;node=next;render(next);return true;},destroy(){version++;},ignoreMutation:()=>true};
  };}
 });
 const Image=TiptapNode.create({
  name:'vaultImage',group:'inline',inline:true,atom:true,selectable:true,draggable:true,
  addAttributes(){return {src:{default:''},alt:{default:''},title:{default:''}};},
  parseHTML(){return [{tag:'img[src]',getAttrs:element=>({src:(element as HTMLImageElement).getAttribute('data-vault-src')||(element as HTMLImageElement).getAttribute('src'),alt:(element as HTMLImageElement).alt,title:(element as HTMLImageElement).title})}];},
  renderHTML({HTMLAttributes}){return ['img',mergeAttributes(HTMLAttributes,{'data-vault-src':HTMLAttributes.src})];},
  addInputRules(){return [nodeInputRule({find:/!\[([^\]\n]*)\]\(([^\s)]+)\)$/,type:this.type,getAttributes:match=>({alt:match[1],src:match[2]})})];},
  addNodeView(){return ({node})=>{
   const dom=document.createElement('img');dom.loading='lazy';dom.decoding='async';let controller:AbortController;
   const render=(value:PMNode)=>{
    controller?.abort();controller=new AbortController();const signal=controller.signal;dom.alt=value.attrs.alt;dom.title=value.attrs.title;dom.dataset.vaultSrc=value.attrs.src;
    if(/^https?:/i.test(value.attrs.src)){dom.src=value.attrs.src;return;}
    dom.removeAttribute('src');void api('resolve?target='+encodeURIComponent(value.attrs.src)+'&source='+encodeURIComponent(actions.path),undefined,undefined,{signal}).then(result=>{if(!signal.aborted&&result.candidates.length===1)dom.src=media(result.candidates[0]);}).catch(()=>{});
   };render(node);
   return {dom,update(next){if(next.type.name!=='vaultImage')return false;if(next.attrs.src!==node.attrs.src||next.attrs.alt!==node.attrs.alt||next.attrs.title!==node.attrs.title)render(next);node=next;return true;},destroy(){controller.abort();}};
  };}
 });
 return [StarterKit.configure({undoRedo:false,underline:false,trailingNode:false,code:false,bulletList:false,orderedList:false,link:{openOnClick:false,autolink:false,linkOnPaste:false},dropcursor:{color:'var(--link)',width:3}}),
  BulletList.extend({content:'(listItem | taskItem)+'}),OrderedList.extend({content:'(listItem | taskItem)+'}),
  Code.extend({excludes:''}),
  Table.configure({resizable:false,allowTableNodeSelection:true}),TableRow,Cell,Header,TaskList.extend({content:'(taskItem | listItem)+'}),TaskItem.configure({nested:true,a11y:{checkboxLabel:node=>t('待办事项')+': '+(node.textContent||t('正文'))}}),SpecialBlock,WikiLink,InlineMath,Image,sourceIds(),
  Extension.create({name:'leafloomAnchors',addProseMirrorPlugins(){return [richAnchorPlugin(),new Plugin({props:{decorations(state){const {$from}=state.selection;if($from.depth!==1||$from.parent.type.name!=='paragraph'||$from.parent.content.size)return DecorationSet.empty;return DecorationSet.create(state.doc,[Decoration.node($from.before(),$from.after(),{class:'rich-empty','data-placeholder':t('输入 / 插入内容')})]);}}})];}})
 ];
}
