import React,{useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {Editor,getMarkRange,JSONContent} from '@tiptap/core';
import DragHandle from '@tiptap/extension-drag-handle';
import {NodeSelection,TextSelection} from '@tiptap/pm/state';
import type {Node as PMNode} from '@tiptap/pm/model';
import {createRoot} from 'react-dom/client';
import {GripVertical,Plus} from 'lucide-react';
import {api,OpenNote} from './api';
import {t,useLocale} from './i18n';
import {FormDialog} from './ui';
import {DocumentState,documentHistory,travelDocument} from './document-state';
import type {EditMeta,TextSelection as SourceSelection} from './edit-history';
import {insertCommands,InsertId,safeLink} from './editor-catalog';
import {MarkdownBridge,ParsedRichDocument,parseRichMarkdown} from './rich-markdown';
import {richExtensions} from './rich-extensions';
import {releaseRichRange,RichRange,richAnchorKey,trackRichRange,trackedRichRange} from './rich-anchors';
import {blockAction,BlockTarget,CommandContext,convertRichBlock,insertRichAssets,insertRichCommand,matchingRichCommands,richBlock,richContext,setRichLink} from './rich-commands';
import {uploadEditorAssets} from './editor-assets';
import {AnchorRect,BlockMenu,CommandMenu,CommandRow,FormatBar,LinkPopover,TableBar,WikiMenu} from './rich-ui';
import './rich-editor.css';

type EditorFacade={state:{selection:{main:{from:number,to:number,head:number,empty:boolean}},doc:{length:number,sliceString:(from:number,to?:number)=>string}},dom:HTMLElement,dispatch:(spec:{selection?:{anchor:number,head?:number},scrollIntoView?:boolean})=>void,focus:()=>void};
type Props={initial:string,path:string,root:string,session:DocumentState,active:boolean,onChange:(text:string,meta?:EditMeta)=>void,onOpen:OpenNote,onReady?:(view:EditorFacade)=>void,onRelease?:(view:EditorFacade)=>void,onSource:(position:number)=>void};
type ManualMenu={kind:'insert'|'block',anchor:AnchorRect,target:BlockTarget,query:string};
type LinkState={id:string,label:string,target:string,wiki:boolean,anchor:AnchorRect};
type DialogState={id:string,kind:'link'|'wiki'|'math'|'mermaid'|'query'|'inlineMath',label:string,value:string};
const recentKey='leafloom-editor-recent';
function recentCommands():InsertId[]{try{return JSON.parse(localStorage.getItem(recentKey)||'[]').filter((id:InsertId)=>insertCommands.some(command=>command.id===id)).slice(0,6);}catch{return [];}}
function commandRows(query:string):CommandRow[]{
 const commands=matchingRichCommands(query),recent=query.trim()?[]:recentCommands();
 return [...recent.map(id=>({command:commands.find(command=>command.id===id)!,group:'recent' as const})).filter(row=>row.command),
  ...(['basic','lists','media','advanced'] as const).flatMap(group=>commands.filter(command=>command.category===group&&!recent.includes(command.id)).map(command=>({command,group})))];
}
const remember=(id:InsertId)=>{try{localStorage.setItem(recentKey,JSON.stringify([id,...recentCommands().filter(value=>value!==id)].slice(0,6)));}catch{}};
const rectAt=(editor:Editor,position:number):AnchorRect=>{const rect=editor.view.coordsAtPos(Math.min(editor.state.doc.content.size,Math.max(0,position)));return {left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom};};
function selectionRect(editor:Editor):AnchorRect{
 const selection=window.getSelection();if(selection?.rangeCount){const rect=selection.getRangeAt(0).getBoundingClientRect();if(rect.width||rect.height)return {left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom};}
 return rectAt(editor,editor.state.selection.from);
}
function markdownSelection(editor:Editor,bridge:MarkdownBridge):SourceSelection{
 const selection=editor.state.selection,from=bridge.toSource(editor.state.doc,selection.from),to=selection.empty?from:bridge.toSource(editor.state.doc,selection.to,-1);return {from:Math.min(from,to),to:Math.max(from,to)};
}
function loadParsed(text:string,signal:AbortSignal):Promise<ParsedRichDocument>{
 if(text.length*2<=256*1024)return Promise.resolve(parseRichMarkdown(text));
 return new Promise((resolve,reject)=>{
  const worker=new Worker(new URL('./rich-markdown.worker.ts',import.meta.url),{type:'module'});
  const abort=()=>{worker.terminate();reject(new DOMException('cancelled','AbortError'));};signal.addEventListener('abort',abort,{once:true});
  worker.onmessage=event=>{signal.removeEventListener('abort',abort);worker.terminate();event.data.error?reject(new Error(event.data.error)):resolve(event.data.parsed);};
  worker.onerror=event=>{signal.removeEventListener('abort',abort);worker.terminate();reject(new Error(event.message));};worker.postMessage({text});
 });
}
// Reuse unchanged source identities after a source edit or a document-level undo.
// This permits a bounded ProseMirror replacement instead of replacing its DOM.
function reuseSourceIds(parsed:ParsedRichDocument,bridge:MarkdownBridge){
 const available=new Map<string,string[]>();for(const block of bridge.blocks){const list=available.get(block.raw)||[];list.push(block.id);available.set(block.raw,list);}
 for(const block of parsed.blocks){const id=available.get(block.raw)?.shift();if(id){block.id=id;block.node.attrs={...block.node.attrs,sourceId:id};}}
}
export function RichEditor(props:Props){
 const locale=useLocale(),host=useRef<HTMLDivElement>(null),editorRef=useRef<Editor|undefined>(undefined),bridgeRef=useRef<MarkdownBridge|undefined>(undefined);
 const callbacks=useRef(props);callbacks.current=props;
 const [editor,setEditor]=useState<Editor>(),[version,setVersion]=useState(0),[error,setError]=useState(''),[loading,setLoading]=useState(true);
 const [manual,setManual]=useState<ManualMenu>(),[link,setLink]=useState<LinkState>(),[dialog,setDialog]=useState<DialogState>();
 const [selected,setSelected]=useState(0),[dismissed,setDismissed]=useState(''),[wikiRows,setWikiRows]=useState<{path:string,title?:string}[]>([]),[wikiStatus,setWikiStatus]=useState('');
 const [status,setStatus]=useState<{message:string,error?:boolean}>();
 const composing=useRef(false),compositionId=useRef(''),syncing=useRef(false),resyncing=useRef(false),refocus=useRef(false),sourceSelection=useRef<SourceSelection>({from:0,to:0});
 const pending=useRef(new Map<string,{controller:AbortController,input?:HTMLInputElement}>()),hover=useRef<BlockTarget|null>(null),handlers=useRef<any>({});
 const refresh=()=>setVersion(value=>value+1);
 const context=editor&&props.active?richContext(editor):null,contextKey=context?context.kind+':'+context.from+':'+context.query:'';
 const automatic=!!context&&!!editor?.isEditable&&!!editor?.view.hasFocus()&&contextKey!==dismissed&&!manual&&!dialog&&!link&&!composing.current;
 const rows=useMemo(()=>commandRows(manual?.kind==='insert'?manual.query:context?.query||''),[manual?.query,context?.query,locale,manual?.kind,version]);
 const closePanels=()=>{setManual(undefined);setDismissed(contextKey);if(link&&editor)releaseRichRange(editor,link.id);setLink(undefined);};
 const cancelPending=()=>{for(const [id,value] of pending.current){value.controller.abort();value.input?.remove();if(editorRef.current&&!editorRef.current.isDestroyed)releaseRichRange(editorRef.current,id);}pending.current.clear();};
 const showLinkDialog=(range:RichRange,label='',value='',kind:'link'|'wiki'='link',id?:string)=>{
  const current=editorRef.current;if(!current)return;
  if(link&&!id)releaseRichRange(current,link.id);
  setDialog({id:id||trackRichRange(current,range),kind,label,value});setLink(undefined);setManual(undefined);setDismissed(contextKey);
 };
 const showSpecialDialog=(position:number,node:PMNode)=>{
  const current=editorRef.current;if(!current)return;
  setDialog({id:trackRichRange(current,{from:position,to:position+node.nodeSize}),kind:node.type.name==='inlineMath'?'inlineMath':node.attrs.kind,label:'',value:node.type.name==='inlineMath'?node.attrs.formula:node.attrs.content});setManual(undefined);
 };
 const upload=async(files:File[],range:RichRange,id?:string)=>{
  const current=editorRef.current;if(!current||!files.length)return;
  const key=id||trackRichRange(current,range),controller=new AbortController();pending.current.set(key,{controller});
  const alive=()=>!current.isDestroyed&&callbacks.current.active&&!!trackedRichRange(current,key);
  try{
   const assets=await uploadEditorAssets(files,{root:props.root,path:props.path,signal:controller.signal,alive,status:message=>setStatus({message})});
   const target=trackedRichRange(current,key);if(!target||!alive())throw new DOMException('cancelled','AbortError');
   pending.current.delete(key);insertRichAssets(current,target,assets);setStatus({message:t('附件已插入')});
  }catch(error){if(!current.isDestroyed)setStatus({message:(error as Error).name==='AbortError'?t('附件插入已取消'):(error as Error).message,error:true});}
  finally{pending.current.delete(key);releaseRichRange(current,key);}
 };
 const chooseFile=(images:boolean,range:RichRange)=>{
  const current=editorRef.current;if(!current)return;
  const id=trackRichRange(current,range),input=document.createElement('input'),controller=new AbortController();
  input.type='file';input.multiple=true;input.hidden=true;if(images)input.accept='image/png,image/jpeg,image/gif,image/webp,image/avif,image/svg+xml';
  pending.current.set(id,{controller,input});document.body.append(input);
  input.onchange=()=>{pending.current.delete(id);input.remove();if(!controller.signal.aborted&&!current.isDestroyed)void upload(Array.from(input.files||[]),range,id);};
  input.oncancel=()=>{pending.current.delete(id);input.remove();releaseRichRange(current,id);};controller.signal.addEventListener('abort',()=>input.remove(),{once:true});input.click();
 };
 const chooseCommand=(id:InsertId)=>{
  const current=editorRef.current;if(!current||!current.isEditable||current.view.composing)return;
  const actual=richContext(current),menu=manual;
  if(!menu&&actual?.kind!=='slash')return;
  const after=menu?menu.target.pos+menu.target.node.nodeSize:undefined,range=menu?{from:after!,to:after!}:{from:actual!.from,to:actual!.to};
  remember(id);setManual(undefined);setDismissed(contextKey);setSelected(0);
  if(id==='image'||id==='file'){chooseFile(id==='image',range);return;}
  if(id==='link'){showLinkDialog(range);return;}
  insertRichCommand(current,id,range,after);
  if(id==='math'||id==='mermaid'){const selection=current.state.selection;if(selection instanceof NodeSelection)showSpecialDialog(selection.from,selection.node);}
 };
 const chooseWiki=(path:string)=>{
  const current=editorRef.current,actual=current&&richContext(current);if(!current||!current.isEditable||!actual||actual.kind!=='wiki'||current.view.composing)return;
  const closing=current.state.doc.textBetween(actual.to,Math.min(current.state.doc.content.size,actual.to+2))===']]'?2:0;
  const label=wikiRows.find(row=>row.path===path)?.title||path.split('/').pop()||path;
  current.chain().focus().insertContentAt({from:actual.from,to:actual.to+closing},{type:'wikiLink',attrs:{target:path,label}}).run();setDismissed(contextKey);setSelected(0);
 };
 handlers.current={chooseCommand,chooseWiki,showSpecialDialog,showLinkDialog,rows,wikiRows,selected,contextKey,dismissed,manual,dialog,link,refresh};
 useEffect(()=>{setSelected(0);},[contextKey,manual?.query]);
 useEffect(()=>{
  if(!context||context.kind!=='wiki'||!automatic){setWikiRows([]);return;}
  const controller=new AbortController();setWikiRows([]);setWikiStatus(t(context.query.trim()?'正在搜索…':'输入笔记名称以搜索'));
  if(!context.query.trim())return()=>controller.abort();
  const timer=setTimeout(()=>{void api<{path:string,title?:string}[]>('search-files?query='+encodeURIComponent(context.query.trim()),undefined,undefined,{signal:controller.signal}).then(rows=>{
   if(controller.signal.aborted)return;const results=rows.filter(row=>row.path.toLowerCase().endsWith('.md')&&!/[\[\]|#\r\n]/.test(row.path));setWikiRows(results);setWikiStatus(t('没有匹配的笔记'));
  }).catch(error=>{if(error.name!=='AbortError')setWikiStatus(t('笔记搜索失败，请重试'));});},180);
  return()=>{clearTimeout(timer);controller.abort();};
 },[context?.kind,context?.query,context?.from,automatic,locale]);
 useEffect(()=>{
  const controller=new AbortController();let instance:Editor|undefined,facade:EditorFacade|undefined,handleRoot:ReturnType<typeof createRoot>|undefined,handle:HTMLDivElement|undefined;
  setLoading(true);setError('');
  const init=async()=>{
   let text:string,parsed:ParsedRichDocument;
   do{text=callbacks.current.initial;parsed=await loadParsed(text,controller.signal);if(controller.signal.aborted)return;}while(callbacks.current.initial!==text);
   const bridge=new MarkdownBridge(parsed);bridgeRef.current=bridge;
   const openManual=(kind:'insert'|'block')=>{
    const target=hover.current;if(!target||!instance||instance.isDestroyed||target.node.attrs.kind==='definitions')return;
    const rect=handle!.getBoundingClientRect();setManual({kind,target,anchor:{left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom},query:''});setSelected(0);instance.commands.lockDragHandle();
   };
   const drag=DragHandle.configure({
    render:()=>{handle=document.createElement('div');handle.className='rich-block-handle';handle.style.visibility='hidden';handleRoot=createRoot(handle);handleRoot.render(<><button type="button" title={t('插入内容')} aria-label={t('插入内容')} onMouseDown={event=>event.preventDefault()} onClick={()=>openManual('insert')}><Plus size={17}/></button><button type="button" className="rich-drag-grip" title={t('拖动或打开块操作')} aria-label={t('块操作')} onClick={()=>openManual('block')}><GripVertical size={17}/></button></>);return handle;},
    computePositionConfig:{placement:'left-start',strategy:'fixed'},nested:{allowedContainers:['doc','bulletList','orderedList','taskList','blockquote'],rules:[{id:'protect-special-and-cells',evaluate:({node,parent})=>node.attrs.kind==='definitions'||['tableCell','tableHeader','tableRow'].includes(node.type.name)||['tableCell','tableHeader'].includes(parent?.type.name||'')?1000:0}]},
    onNodeChange:value=>{const {node}=value,pos=(value as typeof value&{pos?:number}).pos;hover.current=node&&pos!==undefined?{node,pos}:null;},
    onElementDragStart:()=>{setManual(undefined);setDismissed(handlers.current.contextKey);},
   });
   instance=new Editor({
    element:host.current!,content:parsed.doc,editable:callbacks.current.active,extensions:[...richExtensions({path:props.path,onOpen:(target,anchor)=>callbacks.current.onOpen(target,anchor),onEdit:(pos,node)=>handlers.current.showSpecialDialog(pos,node),onSource:position=>{const source=bridgeRef.current?.toSource(instance!.state.doc,position)||0;callbacks.current.onSource(source);}}),drag],
    injectCSS:false,enableInputRules:true,enablePasteRules:true,
    editorProps:{
     attributes:{class:'markdown rich-prose',role:'textbox','aria-label':t('笔记正文'),'aria-multiline':'true','data-placeholder':t('输入 / 插入内容'),spellcheck:'true'},
     handleKeyDown(view,event){
      if(!view.editable)return false;
      if(event.isComposing||event.keyCode===229||view.composing||composing.current)return false;
      const current=instance!,ui=handlers.current,actual=richContext(current),key=event.key.toLowerCase(),mod=event.metaKey||event.ctrlKey;
      if(mod&&key==='z'){event.preventDefault();travelDocument(callbacks.current.session,event.shiftKey?'redo':'undo');return true;}
      if(mod&&key==='y'){event.preventDefault();travelDocument(callbacks.current.session,'redo');return true;}
      if(mod&&key==='d'){event.preventDefault();return blockAction(current,'duplicate');}
      if(mod&&event.shiftKey&&key==='k'){event.preventDefault();ui.showLinkDialog(view.state.selection,view.state.doc.textBetween(view.state.selection.from,view.state.selection.to));return true;}
      if(event.altKey&&event.shiftKey&&key==='f'){const button=document.querySelector<HTMLButtonElement>('.rich-format-bar button');if(button){button.focus();return true;}}
      const visible=actual&&actual.kind+':'+actual.from+':'+actual.query!==ui.dismissed&&!ui.manual&&!ui.dialog&&!ui.link;
      if(visible){
       const options=actual.kind==='slash'?commandRows(actual.query):ui.wikiRows;
       if(event.key==='Escape'){setDismissed(actual.kind+':'+actual.from+':'+actual.query);return true;}
       if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)&&options.length){setSelected(value=>event.key==='Home'?0:event.key==='End'?options.length-1:(value+(event.key==='ArrowDown'?1:options.length-1))%options.length);return true;}
       if(event.key==='Enter'&&options.length){const index=Math.min(ui.selected,options.length-1);if(actual.kind==='slash')ui.chooseCommand((options[index] as CommandRow).command.id);else ui.chooseWiki((options[index] as {path:string}).path);return true;}
      }
      if(event.key==='Tab'&&!current.isActive('table'))return event.shiftKey?(current.isActive('taskList')?current.commands.liftListItem('taskItem'):current.commands.liftListItem('listItem')):(current.isActive('taskList')?current.commands.sinkListItem('taskItem'):current.commands.sinkListItem('listItem'));
      if(event.key==='Enter'&&current.isActive('table')){if(event.shiftKey)return true;return current.commands.goToNextCell()||current.chain().addRowAfter().goToNextCell().run();}
      if(event.key==='Escape'){setManual(undefined);setLink(undefined);setDismissed(ui.contextKey);return false;}
      return false;
     },
     handlePaste(view,event){
      if(view.composing||composing.current)return false;const data=event.clipboardData;if(!data)return false;
      if(data.files.length&&!instance!.isActive('codeBlock')){event.preventDefault();void handlers.current.upload(Array.from(data.files),view.state.selection);return true;}
      const value=data.getData('text/plain'),url=safeLink(value.trim());
      if(!view.state.selection.empty&&url){event.preventDefault();setRichLink(instance!,view.state.selection,url,view.state.doc.textBetween(view.state.selection.from,view.state.selection.to));return true;}
      if(instance!.isActive('codeBlock'))return false;
      if(instance!.isActive('table')&&/[\r\n\t]/.test(value)){event.preventDefault();instance!.commands.insertContent({type:'text',text:value.replace(/[\r\n\t]+/g,' ')});return true;}
      if(!data.getData('text/html')&&/\n|^(?:#{1,6} |[-*+] |\d+[.)] |```|~~~|> |\$\$|!\[|\|)/.test(value)){
       event.preventDefault();const parsed=parseRichMarkdown(value);instance!.commands.insertContent(parsed.doc.content||[]);return true;
      }
      return false;
     },
     handleDrop(view,event){const files=Array.from(event.dataTransfer?.files||[]),position=view.posAtCoords({left:event.clientX,top:event.clientY})?.pos;
      if(!files.length){if(view.dragging&&position!==undefined){const $pos=view.state.doc.resolve(position);for(let depth=$pos.depth;depth>0;depth--)if(['tableCell','tableHeader','codeBlock'].includes($pos.node(depth).type.name)){event.preventDefault();return true;}}return false;}
      event.preventDefault();if(position!==undefined){const $pos=view.state.doc.resolve(position);if($pos.parent.type.name!=='codeBlock')void handlers.current.upload(files,{from:position,to:position});}return true;
     },
     handleClick(view,position,event){
      const anchor=(event.target as HTMLElement).closest<HTMLAnchorElement>('a');
      if(!anchor){
       const target=event.target as HTMLElement,cell=target.closest('td,th'),paragraph=cell?.querySelector('p');
       if(paragraph&&view.dom.contains(paragraph)&&!event.shiftKey&&!event.ctrlKey&&!event.metaKey&&event.detail<2&&!target.closest('img')){const start=view.posAtDOM(paragraph,0),node=view.state.doc.nodeAt(start-1);if(node?.isTextblock){const at=Math.max(start,Math.min(start+node.content.size,position));view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc,at)));view.focus();return true;}}
       const last=view.dom.lastElementChild;if(event.target===view.dom&&last&&event.clientY>last.getBoundingClientRect().bottom){view.dispatch(view.state.tr.setSelection(TextSelection.near(view.state.doc.resolve(view.state.doc.content.size),-1)));view.focus();return true;}return false;
      }
      if(!view.dom.contains(anchor))return false;
      const wiki=anchor.dataset.wikiTarget,href=wiki||anchor.getAttribute('href')||'';if(!href||href==='#')return false;event.preventDefault();
      const open=()=>{if(safeLink(href))window.open(href,'_blank','noopener,noreferrer');else callbacks.current.onOpen(href);};
      if(event.ctrlKey||event.metaKey){open();return true;}
      let range:RichRange|undefined;
      if(wiki!==undefined)view.state.doc.descendants((node,pos)=>{if(node.type.name==='wikiLink'&&view.nodeDOM(pos)===anchor)range={from:pos,to:pos+node.nodeSize};});
      else range=getMarkRange(view.state.doc.resolve(position),view.state.schema.marks.link)||undefined;
      if(!range)return true;
      const rect=anchor.getBoundingClientRect();setLink({id:trackRichRange(instance!,range),label:anchor.textContent||'',target:href,wiki:wiki!==undefined,anchor:{left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom}});setManual(undefined);return true;
     },
     handleDOMEvents:{
      dragover(_view,event){if((event as DragEvent).dataTransfer?.types.includes('Files')){event.preventDefault();return true;}return false;},
      compositionstart(){composing.current=true;compositionId.current=crypto.randomUUID();refresh();return false;},compositionend(){composing.current=false;queueMicrotask(refresh);return false;},
      beforeinput(_view,event){const input=event as InputEvent;if(input.inputType==='historyUndo'||input.inputType==='historyRedo'){event.preventDefault();travelDocument(callbacks.current.session,input.inputType==='historyUndo'?'undo':'redo');return true;}return false;},
     }
    },
    onTransaction({editor:current,transaction}){
     if(syncing.current||resyncing.current||!bridgeRef.current)return;
     if(transaction.docChanged){
      setDismissed('');
      try{
       const before=sourceSelection.current,text=bridgeRef.current.update(current.state.doc),after=markdownSelection(current,bridgeRef.current);
       sourceSelection.current=after;
       const structural=transaction.steps.some(step=>!['replace'].includes(step.toJSON().stepType)),command=structural||transaction.getMeta('leafloomEdit')==='command'||['paste','drop'].includes(transaction.getMeta('uiEvent'));
       callbacks.current.onChange(text,{kind:command?'command':'typing',...(composing.current?{group:'ime:'+compositionId.current}:{}),before,after});
      }catch(error){setError(t('无法保存此编辑，请保留页面并查看源码')+' · '+String(error));}
     }else sourceSelection.current=markdownSelection(current,bridgeRef.current);
     for(const [id,value] of pending.current)if(!trackedRichRange(current,id)){value.controller.abort();value.input?.remove();pending.current.delete(id);}
     refresh();
    },
    onFocus:refresh,onBlur:refresh,
   });
   bridge.bind(instance.state.doc);editorRef.current=instance;setEditor(instance);setLoading(false);
   const current=instance;
   const imeCapture=(event:KeyboardEvent)=>{
    if(event.isComposing||event.keyCode===229||composing.current||current.view.composing){event.stopImmediatePropagation();return;}
    if(resyncing.current&&(event.ctrlKey||event.metaKey)&&['z','y'].includes(event.key.toLowerCase())){event.preventDefault();event.stopImmediatePropagation();travelDocument(callbacks.current.session,event.key.toLowerCase()==='y'||event.shiftKey?'redo':'undo');}
   };current.view.dom.addEventListener('keydown',imeCapture,true);
   facade={
    get state(){const bridge=bridgeRef.current!,selection=current.state.selection,{from,to}=markdownSelection(current,bridge);return {selection:{main:{from,to,head:bridge.toSource(current.state.doc,selection.head),empty:selection.empty}},doc:{length:bridge.text.length,sliceString:(from:number,to?:number)=>bridge.text.slice(from,to)}};},
    dom:current.view.dom,
    dispatch(spec){if(!spec.selection)return;const bridge=bridgeRef.current!,from=bridge.toEditor(current.state.doc,spec.selection.anchor),to=bridge.toEditor(current.state.doc,spec.selection.head??spec.selection.anchor),tr=current.state.tr;tr.setSelection(from===to?TextSelection.near(tr.doc.resolve(from)):TextSelection.between(tr.doc.resolve(from),tr.doc.resolve(to)));current.view.dispatch(spec.scrollIntoView?tr.scrollIntoView():tr);},
    focus(){current.commands.focus();}
   };
   callbacks.current.onReady?.(facade);
  };
  void init().catch(error=>{if(error.name!=='AbortError'){setError(String(error));setLoading(false);}});
  return()=>{controller.abort();cancelPending();if(instance){if(facade)callbacks.current.onRelease?.(facade);instance.destroy();}handle?.remove();if(handleRoot)queueMicrotask(()=>handleRoot?.unmount());editorRef.current=undefined;bridgeRef.current=undefined;setEditor(undefined);};
 },[props.path,props.root]);
 handlers.current.upload=upload;
 useLayoutEffect(()=>{
  const current=editorRef.current,bridge=bridgeRef.current;if(!current||!bridge)return;
  const resume=()=>{const focus=refocus.current&&callbacks.current.active&&(document.activeElement===document.body||document.activeElement===current.view.dom);resyncing.current=false;current.setEditable(callbacks.current.active,false);if(focus)current.view.focus();refocus.current=false;};
  if(props.initial===bridge.text){if(resyncing.current){resume();refresh();}return;}
  const controller=new AbortController(),text=props.initial;
  if(!resyncing.current)refocus.current=current.view.hasFocus();resyncing.current=true;current.setEditable(false,false);current.view.dispatch(current.state.tr.setMeta(richAnchorKey,{clear:true}));cancelPending();setManual(undefined);setLink(undefined);setDialog(undefined);refresh();
  const apply=(parsed:ParsedRichDocument)=>{
   if(controller.signal.aborted||current.isDestroyed||callbacks.current.initial!==text)return;
   reuseSourceIds(parsed,bridge);const next=new MarkdownBridge(parsed),doc=current.schema.nodeFromJSON(parsed.doc);next.bind(doc);
   const old=current.state.doc;let prefix=0,suffix=0;
   while(prefix<old.childCount&&prefix<doc.childCount&&old.child(prefix).eq(doc.child(prefix)))prefix++;
   while(suffix<old.childCount-prefix&&suffix<doc.childCount-prefix&&old.child(old.childCount-1-suffix).eq(doc.child(doc.childCount-1-suffix)))suffix++;
   let from=0,oldTo=old.content.size,nextTo=doc.content.size;for(let i=0;i<prefix;i++)from+=old.child(i).nodeSize;
   for(let i=0;i<suffix;i++){oldTo-=old.child(old.childCount-1-i).nodeSize;nextTo-=doc.child(doc.childCount-1-i).nodeSize;}
   const bookmark=documentHistory(callbacks.current.session).bookmark||sourceSelection.current,focused=refocus.current&&(document.activeElement===document.body||document.activeElement===current.view.dom),tr=current.state.tr.replaceWith(from,oldTo,doc.content.cut(from,nextTo));
   const at=next.toEditor(tr.doc,bookmark.from),end=next.toEditor(tr.doc,bookmark.to);tr.setSelection(at===end?TextSelection.near(tr.doc.resolve(at)):TextSelection.between(tr.doc.resolve(at),tr.doc.resolve(end)));
   syncing.current=true;bridgeRef.current=next;try{current.view.dispatch(focused?tr.scrollIntoView():tr);next.bind(current.state.doc);}finally{syncing.current=false;}
   sourceSelection.current=bookmark;resume();setError('');refresh();
  };
  if(text.length*2<=256*1024){try{apply(parseRichMarkdown(text));}catch(error){setError(String(error));}}
  else void loadParsed(text,controller.signal).then(apply).catch(error=>{if(error.name!=='AbortError')setError(String(error));});
  return()=>controller.abort();
 },[props.initial,props.session.externalEpoch,editor]);
 useEffect(()=>{
  const current=editorRef.current;if(!current)return;
  if(!props.active){cancelPending();setManual(undefined);setLink(undefined);setDialog(undefined);}
  current.setEditable(props.active&&!resyncing.current,false);refresh();
 },[props.active,editor]);
 useEffect(()=>{
  if(!editor)return;editor.view.dom.setAttribute('aria-label',t('笔记正文'));editor.view.dom.setAttribute('data-placeholder',t('输入 / 插入内容'));
  const handle=host.current?.querySelector('.rich-block-handle');if(handle){const buttons=handle.querySelectorAll('button');buttons[0]?.setAttribute('title',t('插入内容'));buttons[0]?.setAttribute('aria-label',t('插入内容'));buttons[1]?.setAttribute('title',t('拖动或打开块操作'));buttons[1]?.setAttribute('aria-label',t('块操作'));}
  editor.view.dom.querySelectorAll<HTMLInputElement>('li[data-type=taskItem] > label > input').forEach(input=>{const label=t('待办事项')+': '+(input.closest('li')?.querySelector('div')?.textContent||t('正文'));input.setAttribute('aria-label',label);const text=input.parentElement?.querySelector('span');if(text)text.textContent=label;});
  editor.view.dispatch(editor.state.tr.setMeta('leafloomLocale',locale));
 },[locale,editor]);
 useEffect(()=>{if(editor&&!manual)editor.commands.unlockDragHandle();},[manual,editor]);
 useEffect(()=>{
  const changed=(event:Event)=>{const detail=(event as CustomEvent).detail;if(detail.reset||detail.type==='config'||detail.root&&detail.root!==props.root)cancelPending();};
  const outside=(event:PointerEvent)=>{const target=event.target as HTMLElement;if(!target.closest('.rich-popup,.rich-block-handle')&&!host.current?.contains(target)){setManual(undefined);setDismissed(handlers.current.contextKey);const current=editorRef.current;if(handlers.current.link&&current)releaseRichRange(current,handlers.current.link.id);setLink(undefined);}};
  const scroll=()=>refresh();window.addEventListener('vault-data-changed',changed);document.addEventListener('pointerdown',outside);host.current?.closest('.writing-area')?.addEventListener('scroll',scroll,{passive:true});
  const area=host.current?.closest('.writing-area');return()=>{window.removeEventListener('vault-data-changed',changed);document.removeEventListener('pointerdown',outside);area?.removeEventListener('scroll',scroll);};
 },[props.root]);
 const closeDialog=()=>{if(editor&&dialog){releaseRichRange(editor,dialog.id);if(props.active)editor.commands.focus();}setDialog(undefined);};
 const closeManual=()=>{setManual(undefined);editorRef.current?.view.focus();};
 const selectLink=()=>{if(!editor)return;showLinkDialog(editor.state.selection,editor.state.doc.textBetween(editor.state.selection.from,editor.state.selection.to),editor.getAttributes('link').href||'');};
 let anchor:AnchorRect|undefined;try{if(editor)anchor=rectAt(editor,context?.from??editor.state.selection.from);}catch{}
 const focused=!!editor?.view.hasFocus()||!!document.activeElement?.closest('.rich-format-popup,.rich-table-popup'),selection=editor?.state.selection,showFormat=!!editor?.isEditable&&props.active&&focused&&!selection?.empty&&!editor.isActive('codeBlock')&&!manual&&!dialog&&!link&&!automatic;
 let tableAnchor:AnchorRect|undefined;if(editor?.isEditable&&props.active&&focused&&editor.isActive('table')&&!showFormat&&!manual&&!dialog&&!link&&!automatic){const cell=editor.view.dom.querySelector('.selectedCell')||editor.view.domAtPos(editor.state.selection.from).node.parentElement?.closest('table');const rect=cell?.getBoundingClientRect();if(rect)tableAnchor={left:rect.left,right:rect.right,top:rect.top,bottom:rect.top};}
 return <div className="live-editor rich-editor" aria-busy={loading||resyncing.current}>
  {loading&&<p className="pad subtle">{t('正在打开内容…')}</p>}{error&&<div className="conflict-banner" role="alert">{error}<button type="button" onClick={()=>props.onSource(sourceSelection.current.from)}>{t('查看源码')}</button></div>}
  <div ref={host} className="rich-editor-host" onPointerDown={event=>{if(event.target===event.currentTarget&&editor){editor.commands.focus('end');}}}/>
  {editor&&props.active&&anchor&&automatic&&context?.kind==='slash'&&<CommandMenu anchor={anchor} rows={rows} selected={Math.min(selected,Math.max(0,rows.length-1))} onSelected={setSelected} onChoose={chooseCommand} query={context.query} onClose={()=>setDismissed(contextKey)}/>}
  {editor&&props.active&&anchor&&automatic&&context?.kind==='wiki'&&<WikiMenu anchor={anchor} rows={wikiRows} selected={Math.min(selected,Math.max(0,wikiRows.length-1))} onSelected={setSelected} onChoose={chooseWiki} status={wikiStatus} onClose={()=>setDismissed(contextKey)}/>}
  {editor&&props.active&&manual?.kind==='insert'&&<CommandMenu anchor={manual.anchor} rows={rows} selected={Math.min(selected,Math.max(0,rows.length-1))} onSelected={setSelected} onChoose={chooseCommand} query={manual.query} onQuery={query=>setManual(value=>value?{...value,query}:undefined)} onClose={closeManual}/>}
  {editor&&props.active&&manual?.kind==='block'&&<BlockMenu editor={editor} target={manual.target} anchor={manual.anchor} onClose={closeManual} onInsert={()=>setManual({...manual,kind:'insert'})}/>}
  {editor&&showFormat&&<FormatBar editor={editor} anchor={selectionRect(editor)} onLink={selectLink} onAction={refresh}/>}
  {editor&&tableAnchor&&<TableBar editor={editor} anchor={tableAnchor} onAction={refresh}/>}
  {editor&&props.active&&link&&<LinkPopover anchor={link.anchor} label={link.label} target={link.target} onClose={closePanels} onOpen={()=>{if(safeLink(link.target))window.open(link.target,'_blank','noopener,noreferrer');else props.onOpen(link.target);closePanels();}} onEdit={()=>{const range=trackedRichRange(editor,link.id);if(range)showLinkDialog(range,link.label,link.target,link.wiki?'wiki':'link',link.id);}} onRemove={()=>{const range=trackedRichRange(editor,link.id);if(range){if(link.wiki)editor.commands.insertContentAt(range,{type:'text',text:link.label});else editor.chain().focus().setTextSelection(range).unsetLink().run();}closePanels();}}/>}
  {status&&<div className={'editor-upload-status'+(status.error?' error':'')} role="status"><span>{status.message}</span><button type="button" aria-label={t('关闭')} onClick={()=>setStatus(undefined)}>×</button></div>}
  {dialog&&<FormDialog title={t(dialog.kind==='link'?'网页链接':dialog.kind==='wiki'?'笔记链接':dialog.kind==='mermaid'?'Mermaid 图表':dialog.kind==='query'?'查询':'公式')} fields={dialog.kind==='link'||dialog.kind==='wiki'?[{name:'target',label:t(dialog.kind==='wiki'?'笔记路径':'链接地址'),value:dialog.value,required:true},{name:'label',label:t('显示文字'),value:dialog.label}]:[{name:'content',label:t(dialog.kind==='mermaid'?'图表内容':dialog.kind==='query'?'查询内容':'公式内容'),value:dialog.value,multiline:true,required:true}]} onClose={closeDialog} submitLabel={t('保存')} onSubmit={async values=>{
   const current=editorRef.current,range=current&&trackedRichRange(current,dialog.id);if(!current||!range||!props.active)throw new Error(t('插入位置已改变，请重新操作'));
   if(dialog.kind==='link'){
    const value=values.target.trim(),relative=(text:string)=>!!text&&!/^(?:[\w+.-]+:|\/\/|\/|\\)|[\r\n\0]/.test(text);
    if(!safeLink(value)&&!(relative(dialog.value)&&relative(value)))throw new Error(t('请输入有效的网页或邮件链接'));setRichLink(current,range,value,values.label||value);
   }else if(dialog.kind==='wiki'){
    const target=values.target.trim();if(!target||/[\[\]|\r\n]/.test(target))throw new Error(t('请输入有效的笔记路径'));current.commands.insertContentAt(range,{type:'wikiLink',attrs:{target,label:values.label||target.split('/').pop()||target}});
   }else{
    const node=current.state.doc.nodeAt(range.from);if(!node||!['specialBlock','inlineMath'].includes(node.type.name))throw new Error(t('插入位置已改变，请重新操作'));
    const content=values.content,raw=dialog.kind==='math'?'$$\n'+content+'\n$$':dialog.kind==='mermaid'?'```mermaid\n'+content+'\n```':dialog.kind==='query'?'```dataview\n'+content+'\n```':'';
    const attrs=dialog.kind==='inlineMath'?{...node.attrs,formula:content}:{...node.attrs,content,raw};current.view.dispatch(current.state.tr.setNodeMarkup(range.from,undefined,attrs).setMeta('leafloomEdit','command'));
   }
   releaseRichRange(current,dialog.id);
  }}/>}
 </div>;
}
