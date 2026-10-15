import {EditorSelection,EditorState,Transaction} from '@codemirror/state';
import {EditorView} from '@codemirror/view';
import {isolateHistory} from '@codemirror/commands';
import {syntaxTree} from '@codemirror/language';
import {t} from './i18n';
import {blockAt,MarkdownBlock,prosePosition,simpleBlockText,topBlocks} from './editor-syntax';

export type InsertId='text'|'h1'|'h2'|'h3'|'bullet'|'ordered'|'todo'|'quote'|'divider'|'code'|'table'|'image'|'file'|'link'|'wiki'|'math'|'mermaid';
export type InsertCommand={id:InsertId,label:string,aliases:string,icon:string,group:'basic'|'insert'|'technical'};
export const insertCommands:readonly InsertCommand[]=[
 {id:'text',label:'正文',aliases:'text paragraph 正文 段落',icon:'T',group:'basic'},
 {id:'h1',label:'一级标题',aliases:'h1 heading title 标题',icon:'H1',group:'basic'},
 {id:'h2',label:'二级标题',aliases:'h2 heading title 标题',icon:'H2',group:'basic'},
 {id:'h3',label:'三级标题',aliases:'h3 heading title 标题',icon:'H3',group:'basic'},
 {id:'bullet',label:'无序列表',aliases:'bullet list ul 列表',icon:'•',group:'basic'},
 {id:'ordered',label:'有序列表',aliases:'number ordered list ol 列表',icon:'1.',group:'basic'},
 {id:'todo',label:'待办事项',aliases:'todo task checkbox 待办 任务',icon:'☑',group:'basic'},
 {id:'quote',label:'引用',aliases:'quote blockquote 引用',icon:'❝',group:'basic'},
 {id:'divider',label:'分割线',aliases:'divider hr separator 分割线',icon:'―',group:'basic'},
 {id:'code',label:'代码块',aliases:'code 代码',icon:'<>',group:'technical'},
 {id:'table',label:'表格',aliases:'table 表格',icon:'▦',group:'basic'},
 {id:'image',label:'图片',aliases:'image picture 图片 截图',icon:'▧',group:'insert'},
 {id:'file',label:'附件',aliases:'file attachment 附件 文件',icon:'↥',group:'insert'},
 {id:'link',label:'网页链接',aliases:'link url 网页 链接',icon:'↗',group:'insert'},
 {id:'wiki',label:'笔记链接',aliases:'wiki note link 笔记 双链',icon:'[[',group:'insert'},
 {id:'math',label:'公式',aliases:'math equation latex 公式',icon:'∑',group:'technical'},
 {id:'mermaid',label:'Mermaid 图表',aliases:'mermaid diagram flowchart 图表 流程图',icon:'◇',group:'technical'}
];
export type InsertRange={from:number,to:number};
export const editAnnotations=[Transaction.userEvent.of('input.editor-command'),isolateHistory.of('full')];
export function snippet(id:InsertId):{text:string,offset:number}{
 const simple:Partial<Record<InsertId,string>>={text:'',h1:'# ',h2:'## ',h3:'### ',bullet:'- ',ordered:'1. ',todo:'- [ ] ',quote:'> ',divider:'---\n',wiki:'[[',code:'```\n\n```',math:'$$\n\n$$',mermaid:'```mermaid\ngraph LR\n  A --> B\n```',table:'| A | B |\n| --- | --- |\n|  |  |\n|  |  |'};
 const text=simple[id]??'';
 return {text,offset:id==='code'?4:id==='math'?3:id==='table'?2:id==='mermaid'?19:text.length};
}
export function insertSnippet(view:EditorView,id:InsertId,range:InsertRange=view.state.selection.main){
 const {state}=view,content=snippet(id),line=state.doc.lineAt(range.from),block=blockAt(state,range.from);
 const empty=(state.doc.sliceString(line.from,range.from)+state.doc.sliceString(range.to,line.to)).trim()==='';
 if(id==='wiki'||empty){
  const before=id!=='wiki'&&line.from>0&&state.doc.lineAt(line.from-1).text.trim()?'\n':'';
  const after=id!=='wiki'&&line.to<state.doc.length&&state.doc.lineAt(line.to+1).text.trim()&&!content.text.endsWith('\n')?'\n':'';
  view.dispatch({changes:{from:range.from,to:range.to,insert:before+content.text+after},selection:{anchor:range.from+before.length+content.offset},annotations:editAnnotations});
 }else{
  const at=Math.max(block.to,range.to),tail=state.doc.sliceString(at,Math.min(state.doc.length,at+2));
  const insert='\n\n'+content.text+(tail&&tail!=='\n\n'&&!content.text.endsWith('\n')?'\n':'');
  view.dispatch({changes:[{from:range.from,to:range.to,insert:''},{from:at,insert}],selection:{anchor:at-(range.to-range.from)+2+content.offset},annotations:editAnnotations});
 }
 view.focus();
}
export type FormatId='bold'|'italic'|'strike'|'inlineCode';
export const formatCommands:{id:FormatId,label:string,marker:string,key:string}[]=[
 {id:'bold',label:'加粗',marker:'**',key:'Mod-b'},
 {id:'italic',label:'斜体',marker:'*',key:'Mod-i'},
 {id:'strike',label:'删除线',marker:'~~',key:'Mod-Shift-x'},
 {id:'inlineCode',label:'行内代码',marker:'`',key:'Mod-e'}
];
export function toggleFormat(view:EditorView,id:FormatId){
 const {state}=view,s=state.selection.main;
 const kind={bold:'StrongEmphasis',italic:'Emphasis',strike:'Strikethrough',inlineCode:'InlineCode'}[id];
 for(let node=syntaxTree(state).resolveInner(s.from,1);node;node=node.parent!){
  if(node.name!==kind||node.to<s.to)continue;
  const first=node.firstChild,last=node.lastChild;if(!first||!last||first===last)break;
  const prefix=state.doc.sliceString(first.to,Math.max(first.to,s.from)),suffix=state.doc.sliceString(Math.min(s.to,last.from),last.from);
  if(!prefix.replace(/[*_~`]/g,'')&&!suffix.replace(/[*_~`]/g,'')){
   const changes=state.changes([{from:first.from,to:first.to,insert:''},{from:last.from,to:last.to,insert:''}]);
   view.dispatch({changes,selection:s.map(changes),annotations:editAnnotations});view.focus();return true;
  }
  if(s.from>=first.to&&s.to<=last.from&&!s.empty){
   const marker=state.doc.sliceString(first.from,first.to);
   const wrap=(value:string)=>value.replace(/^(\s*)([\s\S]*?)(\s*)$/,(_,left,body,right)=>left+(body?marker+body+marker:'')+right);
   const left=wrap(prefix),selected=state.doc.sliceString(s.from,s.to),right=wrap(suffix);
   view.dispatch({changes:{from:node.from,to:node.to,insert:left+selected+right},selection:{anchor:node.from+left.length,head:node.from+left.length+selected.length},annotations:editAnnotations});view.focus();return true;
  }
  break;
 }
 if(!prosePosition(state,s.from))return false;
 let mark=formatCommands.find(item=>item.id===id)!.marker;
 let text=state.doc.sliceString(s.from,s.to),from=s.from,to=s.to,insert:string,anchor:number,head:number;
 if(id==='inlineCode'&&text.includes('`'))mark='`'.repeat(Math.max(...[...text.matchAll(/`+/g)].map(m=>m[0].length))+1);
 // Syntax-aware removal above keeps bold and italic distinct even when their
 // delimiters meet (***text***). Empty insertion pairs are not parsed yet.
 const before=state.doc.sliceString(Math.max(0,from-mark.length),from),after=state.doc.sliceString(to,to+mark.length);
 if(s.empty&&before===mark&&after===mark){from-=mark.length;to+=mark.length;insert='';anchor=head=from;}
 else{insert=mark+text+mark;anchor=from+mark.length;head=anchor+text.length;}
 view.dispatch({changes:{from,to,insert},selection:EditorSelection.single(anchor,head),annotations:editAnnotations});view.focus();return true;
}
export function safeLink(value:string){try{const url=new URL(value);return /^(https?:|mailto:)$/.test(url.protocol)?url.href:null;}catch{return null;}}
export function linkMarkdown(label:string,url:string){return '['+label.replace(/[\\[\]]/g,'\\$&')+']('+url.replace(/[()\s]/g,char=>encodeURIComponent(char).replace(/\(/g,'%28').replace(/\)/g,'%29'))+')';}
export function insertLink(view:EditorView,range:InsertRange,url:string,label?:string){
 const safe=safeLink(url);if(!safe)return false;
 const text=label??(view.state.doc.sliceString(range.from,range.to)||safe);
 const insert=linkMarkdown(text,safe);
 view.dispatch({changes:{from:range.from,to:range.to,insert},selection:{anchor:range.from+insert.length},annotations:editAnnotations});view.focus();return true;
}
export const convertibleIds:InsertId[]=['text','h1','h2','h3','bullet','ordered','todo','quote'];
export function convertBlock(view:EditorView,id:InsertId,block=blockAt(view.state)){
 const text=simpleBlockText(view.state,block);if(text===null||!convertibleIds.includes(id))return false;
 const lines=text.split('\n');let insert=text;
 if(/^h[123]$/.test(id))insert='#'.repeat(Number(id[1]))+' '+lines.join(' ');
 else if(id==='bullet'||id==='todo'||id==='quote'||id==='ordered')insert=lines.map((line,i)=>(id==='ordered'?`${i+1}. `:snippet(id).text)+line).join('\n');
 view.dispatch({changes:{from:block.from,to:block.to,insert},selection:{anchor:block.from+insert.length},annotations:editAnnotations});view.focus();return true;
}
export type BlockAction='duplicate'|'up'|'down'|'delete';
export function actOnBlock(view:EditorView,action:BlockAction,block:MarkdownBlock=blockAt(view.state)){
 const blocks=topBlocks(view.state,true),index=blocks.findIndex(b=>b.from===block.from&&b.to===block.to);
 if(index<0||block.name==='Frontmatter')return false;
 const doc=view.state.doc,text=doc.sliceString(block.from,block.to);
 if(action==='duplicate')view.dispatch({changes:{from:block.to,insert:'\n\n'+text},selection:{anchor:block.to+2},annotations:editAnnotations});
 else if(action==='delete'){
  const next=blocks[index+1],previous=blocks[index-1];
  const from=next?block.from:previous?previous.to:block.from,to=next?next.from:block.to;
  view.dispatch({changes:{from,to,insert:''},selection:{anchor:from},annotations:editAnnotations});
 }else{
  const other=blocks[index+(action==='up'?-1:1)];if(!other||other.name==='Frontmatter')return false;
  const first=action==='up'?other:block,last=action==='up'?block:other;
  const gap=doc.sliceString(first.to,last.from),a=doc.sliceString(first.from,first.to),b=doc.sliceString(last.from,last.to);
  const separator=/\n[ \t]*\n/.test(gap)?gap:gap+'\n';
  const before=first.from>0&&doc.lineAt(first.from-1).text.trim()?'\n':'';
  const after=last.to<doc.length&&doc.lineAt(last.to+1).text.trim()?'\n':'';
  view.dispatch({changes:{from:first.from,to:last.to,insert:before+b+separator+a+after},selection:{anchor:action==='up'?first.from+before.length:first.from+before.length+b.length+separator.length},annotations:editAnnotations});
 }
 view.focus();return true;
}
export function commandLabel(id:InsertId){return t(insertCommands.find(command=>command.id===id)!.label);}
