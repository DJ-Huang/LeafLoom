import {autocompletion,closeCompletion,Completion,CompletionContext,completionStatus,acceptCompletion,moveCompletionSelection} from '@codemirror/autocomplete';
import {EditorState,Prec} from '@codemirror/state';
import {EditorView,keymap} from '@codemirror/view';
import {api} from './api';
import {t} from './i18n';
import {insertCommands,InsertId,InsertRange,editAnnotations} from './editor-commands';
import {prosePosition} from './editor-syntax';

export function slashRange(state:EditorState,pos=state.selection.main.head){
 if(!state.selection.main.empty||!prosePosition(state,pos))return null;
 const line=state.doc.lineAt(pos),before=state.doc.sliceString(line.from,pos);
 const match=/(?:^|\s)\/([^\s/\\]*)$/.exec(before);
 if(!match)return null;
 const from=pos-match[1].length-1;
 if(!prosePosition(state,from)||/\[\[[^\]]*$/.test(before.slice(0,from-line.from)))return null;
 return {from,to:pos,query:match[1]};
}
export function wikiRange(state:EditorState,pos=state.selection.main.head){
 if(!state.selection.main.empty)return null;
 const line=state.doc.lineAt(pos),before=state.doc.sliceString(line.from,pos),match=/\[\[([^\]\n|]*)$/.exec(before);
 if(!match)return null;
 const from=pos-match[0].length;
 if(!prosePosition(state,from))return null;
 return {from,to:pos,query:match[1]};
}
export function matchingCommands(query:string){
 const term=query.toLocaleLowerCase();
 return insertCommands.filter(command=>(t(command.label)+' '+command.aliases).toLocaleLowerCase().includes(term));
}
export function editorCompletion(run:(id:InsertId,range:InsertRange)=>void){
 const source=async(context:CompletionContext)=>{
  const slash=slashRange(context.state,context.pos);
  if(slash){
   const groups={basic:t('基础内容'),insert:t('插入'),technical:t('技术内容')};
   return {from:slash.from,to:slash.to,filter:false,options:matchingCommands(slash.query).map(command=>({
    label:t(command.label),detail:command.icon,section:{name:groups[command.group],rank:['basic','insert','technical'].indexOf(command.group)},
    apply:(view:EditorView)=>{if(view.composing)return;const current=slashRange(view.state);if(current){closeCompletion(view);run(command.id,current);}}
   } as Completion))};
  }
  const wiki=wikiRange(context.state,context.pos);
  if(!wiki||!wiki.query.trim())return null;
  const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
  const ready=new Promise<boolean>(resolve=>{
   timer=setTimeout(()=>resolve(true),180);
   context.addEventListener('abort',()=>{clearTimeout(timer);controller.abort();resolve(false);},{onDocChange:true});
  });
  if(!await ready||context.aborted)return null;
  try{
   const rows=await api<{path:string,title?:string}[]>('search-files?query='+encodeURIComponent(wiki.query.trim()),undefined,undefined,{signal:controller.signal});
   if(context.aborted)return null;
   return {from:wiki.from,to:wiki.to,filter:false,options:rows.filter(row=>row.path.toLowerCase().endsWith('.md')&&!/[\[\]|#\r\n]/.test(row.path)).map(row=>({
    label:row.title||row.path.split('/').pop()!,detail:row.path,
    apply:(view:EditorView)=>{
     const current=wikiRange(view.state);if(view.composing||!current)return;
     const to=view.state.doc.sliceString(current.to,current.to+2)===']]'?current.to+2:current.to;
     const insert='[['+row.path+']]';
     view.dispatch({changes:{from:current.from,to,insert},selection:{anchor:current.from+insert.length},annotations:editAnnotations});view.focus();
    }
   } as Completion))};
  }catch(error){if((error as Error).name==='AbortError')return null;return null;}
 };
 return [
  autocompletion({override:[source],activateOnTypingDelay:40,defaultKeymap:false,icons:false,maxRenderedOptions:30,optionClass:()=> 'leafloom-completion-option'}),
  // Markdown's Enter handler uses high precedence. The completion handler must
  // win, while IME events and an empty result list pass through untouched.
  Prec.highest(keymap.of([
   {key:'ArrowDown',run:view=>!view.composing&&moveCompletionSelection(true)(view)},
   {key:'ArrowUp',run:view=>!view.composing&&moveCompletionSelection(false)(view)},
   {key:'Enter',run:view=>!view.composing&&completionStatus(view.state)==='active'&&acceptCompletion(view)},
   {key:'Escape',run:view=>!view.composing&&closeCompletion(view)}
  ]))
 ];
}
