import {t,useLocale} from './i18n';
import React,{useEffect,useRef,useState} from 'react';
import {Compartment,EditorSelection,EditorState} from '@codemirror/state';
import {EditorView,keymap,tooltips,ViewPlugin} from '@codemirror/view';
import {defaultKeymap,history,historyKeymap,redo} from '@codemirror/commands';
import {search,searchKeymap,openSearchPanel as cmOpenSearchPanel} from '@codemirror/search';
import {startCompletion,closeCompletion} from '@codemirror/autocomplete';
import {OpenNote} from './api';
import {FormDialog} from './ui';
import {editingMarkdown,prosePosition} from './editor-syntax';
import {formatCommands,insertLink,InsertId,InsertRange,insertSnippet,safeLink,toggleFormat} from './editor-commands';
import {editorCompletion} from './editor-completion';
import {editorUI,editorVisible,refreshEditorUI,dismissEditorUI} from './editor-ui';
import {pendingAnchors,removeAnchor,trackRange,trackedRange} from './editor-anchors';
import {attachmentController,attachmentEvents} from './editor-attachments';
import {liveDecorations} from './editor-decorations';
import './editor.css';
import {DocumentState,documentHistory,travelDocument} from './document-state';
import {EditMeta,textChange} from './edit-history';
import {editorOffset,editorText,sourceOffset} from './source-offsets';
export const openSearchPanel=(view:any)=>cmOpenSearchPanel(view.sourceView||view);

// IME confirmation belongs to the browser, including the interval before its
// first text mutation and Chromium's EditContext composition path.
const compositionGuard=ViewPlugin.fromClass(class{
 composing=false;
 start=()=>{this.composing=true;};
 end=()=>{this.composing=false;};
 key=(event:KeyboardEvent)=>{if(event.isComposing||event.keyCode===229||this.composing||this.view.compositionStarted)event.stopImmediatePropagation();};
 constructor(readonly view:EditorView){view.contentDOM.addEventListener('compositionstart',this.start,true);view.contentDOM.addEventListener('compositionend',this.end,true);view.contentDOM.addEventListener('keydown',this.key,true);}
 destroy(){this.view.contentDOM.removeEventListener('compositionstart',this.start,true);this.view.contentDOM.removeEventListener('compositionend',this.end,true);this.view.contentDOM.removeEventListener('keydown',this.key,true);}
});

const phrases=()=>EditorState.phrases.of({'Find':t('查找'),'Replace':t('替换'),'next':t('下一个'),'previous':t('上一个'),'all':t('全部'),'match case':t('区分大小写'),'regexp':t('正则表达式'),'by word':t('整词'),'close':t('关闭'),'replace':t('替换'),'replace all':t('全部替换')});
type Props={initial:string,path:string,root:string,onChange:(text:string,meta?:EditMeta)=>void,onOpen:OpenNote,source:boolean,session?:DocumentState,active?:boolean,onReady?:(view:any)=>void,onRelease?:(view:any)=>void};
export function LiveEditor({initial,path,root,onChange,onOpen,source,session,active=true,onReady,onRelease}:Props){
 const locale=useLocale(),host=useRef<HTMLDivElement>(null),view=useRef<EditorView|null>(null);
 const callbacks=useRef({onChange,onOpen,active});callbacks.current={onChange,onOpen,active};
 const attachments=useRef<ReturnType<typeof attachmentController>|undefined>(undefined);
 const language=useRef(new Compartment());
 const syncing=useRef(false),composition=useRef(''),raw=useRef(initial);
 const [link,setLink]=useState<{id:string,label:string}>(),[status,setStatus]=useState<{message:string,error?:boolean}>();
 const closeLink=()=>{const current=view.current;if(current&&link){current.dispatch({effects:removeAnchor.of(link.id)});current.focus();}setLink(undefined);};
 useEffect(()=>{
  if(!host.current)return;
  raw.current=initial;
  let editor:EditorView;
  const run=(id:InsertId,range:InsertRange)=>{
   if(editor.composing)return;
   if(id==='image'||id==='file'){attachments.current?.choose(id==='image',range);return;}
   if(id==='link'){
    const anchor=trackRange(editor,range),selected=editor.state.doc.sliceString(range.from,range.to);
    editor.dispatch({effects:dismissEditorUI.of(null)});setLink({id:anchor,label:editor.state.selection.main.empty&&selected.startsWith('/')?'':selected});return;
   }
   insertSnippet(editor,id,range);if(id==='wiki')startCompletion(editor);
  };
  const state=EditorState.create({doc:initial,extensions:[
   editingMarkdown(),...(session?[]:[history()]),search(),compositionGuard,language.current.of(phrases()),EditorView.lineWrapping,
   keymap.of([
    ...(session?[
     {key:'Mod-z',run:()=>{travelDocument(session,'undo');return true;}},
     {key:'Mod-Shift-z',run:()=>{travelDocument(session,'redo');return true;}},
     {key:'Mod-y',run:()=>{travelDocument(session,'redo');return true;}}
    ]:[]),
    {key:'Mod-Shift-z',run:redo},
    ...(!source?[{key:'Mod-Shift-k',run:(v:EditorView)=>{if(prosePosition(v.state,v.state.selection.main.from))run('link',v.state.selection.main);return true;}}]:[]),
    ...formatCommands.map(command=>({key:command.key,run:(v:EditorView)=>toggleFormat(v,command.id)})),
    ...searchKeymap,...defaultKeymap,...historyKeymap
   ]),
   ...(!source?[
    pendingAnchors,editorCompletion(run),editorUI(run),attachmentEvents(()=>attachments.current),
    liveDecorations(path,(target,anchor)=>callbacks.current.onOpen(target,anchor)),
    tooltips({parent:document.body})
   ]:[]),
   EditorView.domEventHandlers({compositionstart(){composition.current=crypto.randomUUID();return false;},beforeinput(event){if(session&&(event.inputType==='historyUndo'||event.inputType==='historyRedo')){event.preventDefault();travelDocument(session,event.inputType==='historyUndo'?'undo':'redo');return true;}return false;}}),
   EditorView.updateListener.of(update=>{if(update.docChanged&&!syncing.current){
    const before=update.startState.selection.main,after=update.state.selection.main,previous=raw.current,eol=previous.includes('\r\n')?'\r\n':'\n',changes:{from:number,to:number,insert:string}[]=[];
    update.changes.iterChanges((from,to,_nextFrom,_nextTo,inserted)=>changes.push({from:sourceOffset(previous,from),to:sourceOffset(previous,to),insert:inserted.toString().replace(/\n/g,eol)}));
    for(const change of changes.reverse())raw.current=raw.current.slice(0,change.from)+change.insert+raw.current.slice(change.to);
    callbacks.current.onChange(raw.current,{kind:'source',before:{from:sourceOffset(previous,before.from),to:sourceOffset(previous,before.to)},after:{from:sourceOffset(raw.current,after.from),to:sourceOffset(raw.current,after.to)},...(editor.composing?{group:'source-ime:'+composition.current}:{})});
   }}),
   EditorView.theme({'&':{fontSize:'16px'},'.cm-content':{fontFamily:'inherit',padding:source?'32px':'32px 40px 100px 64px',minHeight:'65vh'},'.cm-focused':{outline:'none'}})
  ]});
  editor=new EditorView({state,parent:host.current});view.current=editor;
  if(!source)attachments.current=attachmentController(editor,{root,path,active:()=>callbacks.current.active,status:(message,error)=>setStatus({message,error})});
  const facade=session?{sourceView:editor,dom:editor.dom,get state(){const s=editor.state.selection.main;return {selection:{main:{from:sourceOffset(raw.current,s.from),to:sourceOffset(raw.current,s.to),head:sourceOffset(raw.current,s.head),empty:s.empty}},doc:{length:raw.current.length,sliceString:(from:number,to?:number)=>raw.current.slice(from,to)}};},dispatch(spec:{selection?:{anchor:number,head?:number},scrollIntoView?:boolean}){if(spec.selection)editor.dispatch({selection:EditorSelection.single(editorOffset(raw.current,spec.selection.anchor),editorOffset(raw.current,spec.selection.head??spec.selection.anchor)),scrollIntoView:spec.scrollIntoView});},focus(){editor.focus();}}:editor;
  onReady?.(facade);
  return()=>{attachments.current?.destroy();attachments.current=undefined;onRelease?.(facade);view.current=null;editor.destroy();};
 },[path,root,source]);
 useEffect(()=>{const current=view.current;if(!current||!session||initial===raw.current)return;const change=textChange(current.state.doc.toString(),editorText(initial));raw.current=initial;if(!change)return;const selection=documentHistory(session).bookmark;syncing.current=true;try{current.dispatch({changes:change,...(selection?{selection:EditorSelection.single(editorOffset(initial,selection.from),editorOffset(initial,selection.to)),scrollIntoView:true}:{})});}finally{syncing.current=false;}},[initial,session?.externalEpoch]);
 useEffect(()=>{const editor=view.current;if(editor){editor.dispatch({effects:[language.current.reconfigure(phrases()),...(!source?[refreshEditorUI.of(null)]:[])]});if(!source)closeCompletion(editor);}},[locale,source]);
 useEffect(()=>{const editor=view.current;if(editor&&!source){editor.dispatch({effects:editorVisible.of(active)});if(!active){closeCompletion(editor);attachments.current?.abortAll();setLink(undefined);}}},[active,source]);
 return <div className={'live-editor'+(source?' source-editor':'')}>
  <div ref={host}/>
  {status&&<div className={'editor-upload-status'+(status.error?' error':'')} role="status"><span>{status.message}</span><button type="button" aria-label={t('关闭')} onClick={()=>setStatus(undefined)}>×</button></div>}
  {link&&<FormDialog title={t('网页链接')} fields={[{name:'url',label:t('链接地址'),required:true},{name:'label',label:t('显示文字'),value:link.label}]} submitLabel={t('插入')} onClose={closeLink} onSubmit={async values=>{
   const editor=view.current,range=editor&&trackedRange(editor,link.id);
   if(!editor||!range||!active)throw new Error(t('插入位置已改变，请重新操作'));
   if(!safeLink(values.url.trim()))throw new Error(t('请输入有效的网页或邮件链接'));
   insertLink(editor,range,values.url.trim(),values.label||values.url.trim());editor.dispatch({effects:removeAnchor.of(link.id)});
  }}/>}
 </div>;
}
