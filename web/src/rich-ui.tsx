import React,{useEffect,useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {AlignLeft,AlignCenter,AlignRight,ArrowDown,ArrowUp,Bold,Check,CheckSquare,Code,Code2,Copy,ExternalLink,MessageCircle,File,FileText,GripVertical,Heading1,Heading2,Heading3,Image,Italic,Link,Link2,List,ListOrdered,Minus,Plus,Quote,Search,Sigma,Strikethrough,Table,Trash2,Workflow} from 'lucide-react';
import type {LucideIcon} from 'lucide-react';
import type {Editor} from '@tiptap/core';
import {formatCommands,InsertCommand,InsertId} from './editor-catalog';
import {alignRichTable,blockAction,BlockTarget,convertRichBlock,selectedRowAsHeader} from './rich-commands';
import {t} from './i18n';
import {AnnotationColor,annotationColors} from './annotations';

export type AnchorRect={left:number,right:number,top:number,bottom:number};
const icons:Record<InsertId,LucideIcon>={text:FileText,h1:Heading1,h2:Heading2,h3:Heading3,bullet:List,ordered:ListOrdered,todo:CheckSquare,quote:Quote,divider:Minus,code:Code2,table:Table,image:Image,file:File,link:Link,wiki:Link2,math:Sigma,mermaid:Workflow};
const groups={recent:'最近使用',basic:'基础内容',lists:'列表',media:'媒体',advanced:'高级内容'};
export function RichPopup({anchor,children,className='',above=false,onEscape}:{anchor:AnchorRect,children:React.ReactNode,className?:string,above?:boolean,onEscape?:()=>void}){
 const ref=useRef<HTMLDivElement>(null),[position,setPosition]=useState({left:anchor.left,top:anchor.bottom+8});
 useLayoutEffect(()=>{
  const element=ref.current;if(!element)return;
  const place=()=>{const {width,height}=element.getBoundingClientRect(),margin=12,gap=8;const top=(above&&anchor.top-height-gap>=margin)||anchor.bottom+height+gap>window.innerHeight?anchor.top-height-gap:anchor.bottom+gap;
   setPosition({left:Math.max(margin,Math.min(anchor.left,window.innerWidth-width-margin)),top:Math.max(margin,Math.min(top,window.innerHeight-height-margin))});};
  place();const observer=new ResizeObserver(place);observer.observe(element);window.addEventListener('resize',place);return()=>{observer.disconnect();window.removeEventListener('resize',place);};
 },[anchor.left,anchor.top,anchor.bottom,above]);
 return createPortal(<div ref={ref} className={'rich-popup '+className} style={position} onPointerDown={event=>event.stopPropagation()} onKeyDown={event=>{
  if(event.nativeEvent.isComposing)return;
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();onEscape?.();return;}
  if((event.target as HTMLElement).closest('[role=menu]')&&['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
   const buttons=Array.from(ref.current?.querySelectorAll<HTMLButtonElement>('[role=menuitem]:not(:disabled)')||[]);if(!buttons.length)return;
   const index=buttons.indexOf(document.activeElement as HTMLButtonElement);event.preventDefault();buttons[event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:buttons.length-1))%buttons.length].focus();
  }
 }}>{children}</div>,document.body);
}
export type CommandRow={command:InsertCommand,group:keyof typeof groups};
export function CommandMenu({anchor,rows,selected,onSelected,onChoose,query,onQuery,onClose}:{anchor:AnchorRect,rows:CommandRow[],selected:number,onSelected:(index:number)=>void,onChoose:(id:InsertId)=>void,query:string,onQuery?:(value:string)=>void,onClose:()=>void}){
 const list=useRef<HTMLDivElement>(null);
 useLayoutEffect(()=>{list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({block:'nearest'});},[selected]);
 return <RichPopup anchor={anchor} className="rich-command-popup" onEscape={onClose}>
  {onQuery?<div className="rich-command-search"><Search size={15}/><input autoFocus value={query} aria-label={t('搜索命令…')} placeholder={t('搜索命令…')} onChange={event=>onQuery(event.target.value)} onKeyDown={event=>{
   if(event.nativeEvent.isComposing)return;
   if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();onSelected(rows.length?(selected+(event.key==='ArrowDown'?1:rows.length-1))%rows.length:0);}
   if(event.key==='Enter'&&rows[selected]){event.preventDefault();onChoose(rows[selected].command.id);}
  }}/></div>:<div className="rich-command-caption">{query?<><Search size={13}/><span>{query}</span></>:t('添加内容')}</div>}
  <div ref={list} className="rich-command-list" role="listbox" aria-label={t('插入内容')}>
   {rows.map(({command,group},index)=>{const Icon=icons[command.id];return <React.Fragment key={command.id}>
    {(index===0||rows[index-1].group!==group)&&<div className="rich-command-group">{t(groups[group])}</div>}
    <button type="button" role="option" aria-selected={index===selected} className="rich-command-option" onPointerEnter={()=>onSelected(index)} onMouseDown={event=>event.preventDefault()} onClick={()=>onChoose(command.id)}>
     <span className="rich-command-icon"><Icon size={21} strokeWidth={1.7}/></span><span className="rich-command-copy"><strong>{t(command.label)}</strong><small>{t(command.description)}</small></span>
    </button>
   </React.Fragment>;})}
   {!rows.length&&<div className="rich-command-empty"><Search size={24}/><span>{t('没有匹配的命令')}</span></div>}
  </div><div className="rich-command-footer"><span>↑ ↓ {t('选择')}</span><span>↵ {t('插入')}</span><span>esc {t('关闭')}</span></div>
 </RichPopup>;
}
export function WikiMenu({anchor,rows,selected,onSelected,onChoose,status,onClose}:{anchor:AnchorRect,rows:{title?:string,path:string}[],selected:number,onSelected:(index:number)=>void,onChoose:(path:string)=>void,status:string,onClose:()=>void}){
 const list=useRef<HTMLDivElement>(null);useLayoutEffect(()=>{list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({block:'nearest'});},[selected]);
 return <RichPopup anchor={anchor} className="rich-command-popup rich-wiki-popup" onEscape={onClose}><div className="rich-command-caption"><Link2 size={14}/>{t('笔记链接')}</div><div ref={list} className="rich-command-list" role="listbox" aria-label={t('笔记链接')}>
  {rows.map((row,index)=><button key={row.path} type="button" role="option" aria-selected={index===selected} className="rich-command-option" onMouseDown={event=>event.preventDefault()} onPointerEnter={()=>onSelected(index)} onClick={()=>onChoose(row.path)}><span className="rich-command-icon"><FileText size={20}/></span><span className="rich-command-copy"><strong>{row.title||row.path.split('/').pop()}</strong><small>{row.path}</small></span></button>)}
  {!rows.length&&<div className="rich-command-empty">{status}</div>}
 </div></RichPopup>;
}
export function FormatBar({editor,anchor,onLink,onAction,onAnnotate}:{editor:Editor,anchor:AnchorRect,onLink:()=>void,onAction:()=>void,onAnnotate?:(kind:'highlight'|'comment',color?:AnnotationColor)=>void}){
 const current=editor.isActive('heading')?'h'+editor.getAttributes('heading').level:editor.isActive('taskList')?'todo':editor.isActive('bulletList')?'bullet':editor.isActive('orderedList')?'ordered':editor.isActive('blockquote')?'quote':'text';
 const options:InsertId[]=['text','h1','h2','h3','bullet','ordered','todo','quote'];
 const formatIcons={bold:Bold,italic:Italic,strike:Strikethrough,inlineCode:Code};
 return <RichPopup anchor={anchor} className="rich-format-popup" above><div className="rich-format-bar" role="toolbar" aria-label={t('文字格式')} onMouseDown={event=>{if(!(event.target as HTMLElement).closest('select'))event.preventDefault();}}>
  <select aria-label={t('块类型')} value={current} onChange={event=>{convertRichBlock(editor,event.target.value as InsertId);onAction();}}>{options.map(id=><option key={id} value={id}>{t(({text:'正文',h1:'一级标题',h2:'二级标题',h3:'三级标题',bullet:'无序列表',ordered:'有序列表',todo:'待办事项',quote:'引用'} as any)[id])}</option>)}</select><span className="rich-menu-separator"/>
  {formatCommands.map(command=>{const Icon=formatIcons[command.id],mark=command.id==='inlineCode'?'code':command.id;return <button key={command.id} type="button" title={t(command.label)} aria-label={t(command.label)} aria-pressed={editor.isActive(mark)} onClick={()=>{editor.chain().focus().toggleMark(mark).run();onAction();}}><Icon size={16}/></button>;})}
  <button type="button" title={t('网页链接')} aria-label={t('网页链接')} aria-pressed={editor.isActive('link')} onClick={onLink}><Link size={16}/></button>
  {onAnnotate&&<><span className="rich-menu-separator"/><span className="leafloom-highlight-actions">
   {annotationColors.map(color=><button type="button" key={color} title={t('添加高亮')+' · '+color} aria-label={t('添加高亮')+' · '+color} className={'leafloom-color-button leafloom-'+color} onClick={()=>onAnnotate('highlight',color)}/>)}
  </span><button type="button" title={t('添加评论')} aria-label={t('添加评论')} onClick={()=>onAnnotate('comment')}><MessageCircle size={16}/></button></>}
 </div></RichPopup>;
}
export function BlockMenu({editor,target,anchor,onClose,onInsert}:{editor:Editor,target:BlockTarget,anchor:AnchorRect,onClose:()=>void,onInsert:()=>void}){
 const menu=useRef<HTMLDivElement>(null);useEffect(()=>{menu.current?.querySelector<HTMLButtonElement>('button')?.focus({preventScroll:true});},[]);
 const select=()=>editor.commands.setNodeSelection(target.pos);
 const action=(fn:()=>void)=>{select();fn();onClose();};
 const convertible=['paragraph','heading','blockquote','listItem','taskItem','bulletList','orderedList','taskList'].includes(target.node.type.name);
 const choices:{id:InsertId,label:string}[]=[{id:'text',label:'正文'},{id:'h1',label:'一级标题'},{id:'h2',label:'二级标题'},{id:'h3',label:'三级标题'},{id:'bullet',label:'无序列表'},{id:'ordered',label:'有序列表'},{id:'todo',label:'待办事项'},{id:'quote',label:'引用'}];
 return <RichPopup anchor={anchor} className="rich-block-popup" onEscape={onClose}><div ref={menu} role="menu" aria-label={t('块操作')}>
  <button type="button" role="menuitem" onClick={onInsert}><Plus size={16}/>{t('在下方插入')}</button>
  {convertible&&<><div className="rich-command-group">{t('转换为')}</div><div className="rich-convert-grid">{choices.map(choice=>{const Icon=icons[choice.id];return <button type="button" role="menuitem" key={choice.id} onClick={()=>action(()=>{convertRichBlock(editor,choice.id);})}><Icon size={15}/>{t(choice.label)}</button>;})}</div></>}
  <div className="rich-command-group">{t('块操作')}</div>
  <button type="button" role="menuitem" onClick={()=>action(()=>{blockAction(editor,'duplicate',target);})}><Copy size={16}/>{t('创建副本')}<kbd aria-hidden="true">{/Mac|iPhone|iPad/.test(navigator.platform)?'⌘ D':'Ctrl D'}</kbd></button>
  <button type="button" role="menuitem" onClick={()=>action(()=>{blockAction(editor,'up',target);})}><ArrowUp size={16}/>{t('上移')}</button>
  <button type="button" role="menuitem" onClick={()=>action(()=>{blockAction(editor,'down',target);})}><ArrowDown size={16}/>{t('下移')}</button>
  <button type="button" role="menuitem" className="danger" onClick={()=>action(()=>{blockAction(editor,'delete',target);})}><Trash2 size={16}/>{t('删除块')}</button>
 </div></RichPopup>;
}
export function TableBar({editor,anchor,onAction}:{editor:Editor,anchor:AnchorRect,onAction:()=>void}){
 const action=(fn:()=>unknown)=>{editor.commands.focus();fn();onAction();};
 return <RichPopup anchor={anchor} className="rich-table-popup" above><div role="toolbar" aria-label={t('表格操作')} onMouseDown={event=>event.preventDefault()}>
  <button type="button" aria-label={t('在下方添加行')} title={t('在下方添加行')} onClick={()=>action(()=>editor.commands.addRowAfter())}><Plus size={13}/>{t('行')}</button>
  <button type="button" aria-label={t('在右侧添加列')} title={t('在右侧添加列')} onClick={()=>action(()=>editor.commands.addColumnAfter())}><Plus size={13}/>{t('列')}</button>
  <button type="button" aria-label={t('删除行')} title={t('删除行')} onClick={()=>action(()=>editor.commands.deleteRow())}><Minus size={13}/>{t('行')}</button>
  <button type="button" aria-label={t('删除列')} title={t('删除列')} onClick={()=>action(()=>editor.commands.deleteColumn())}><Minus size={13}/>{t('列')}</button>
  <button type="button" title={t('此行作为表头')} onClick={()=>action(()=>selectedRowAsHeader(editor))}><Table size={15}/></button>
  {(['left','center','right'] as const).map((align,index)=>{const Icon=[AlignLeft,AlignCenter,AlignRight][index];return <button type="button" key={align} title={t(['左对齐','居中对齐','右对齐'][index])} onClick={()=>action(()=>alignRichTable(editor,align))}><Icon size={15}/></button>;})}
 </div></RichPopup>;
}
export function LinkPopover({anchor,label,target,onOpen,onEdit,onRemove,onClose}:{anchor:AnchorRect,label:string,target:string,onOpen:()=>void,onEdit:()=>void,onRemove:()=>void,onClose:()=>void}){
 return <RichPopup anchor={anchor} className="rich-link-popup" onEscape={onClose}><div className="rich-link-destination"><Link2 size={16}/><div><strong>{label||target}</strong><small>{target}</small></div></div><div className="rich-link-actions"><button type="button" onClick={onOpen}><ExternalLink size={14}/>{t('打开')}</button><button type="button" onClick={onEdit}>{t('修改')}</button><button type="button" onClick={onRemove}>{t('移除链接')}</button></div></RichPopup>;
}
