import MarkdownIt from 'markdown-it';
import type {JSONContent} from '@tiptap/core';
import type {Node as PMNode} from '@tiptap/pm/model';

type Token=ReturnType<MarkdownIt['parse']>[number];
export type RichBlock={id:string,from:number,to:number,raw:string,before:string,node:JSONContent,virtual?:boolean};
export type ParsedRichDocument={text:string,prefix:string,suffix:string,blocks:RichBlock[],doc:JSONContent,eol:string};
export const richId=()=>crypto.randomUUID();
const textNode=(text:string,marks:JSONContent['marks']=[]):JSONContent=>({type:'text',text,...(marks.length?{marks}: {})});

function parser(){
 const md=new MarkdownIt({html:false,linkify:true});
 md.inline.ruler.before('link','vault_link',(state,silent)=>{
  const match=/^(!?)\[\[([^\]\n]+)\]\]/.exec(state.src.slice(state.pos));if(!match)return false;
  if(!silent){const token=state.push(match[1]?'vault_embed':'vault_link','',0);token.content=match[2].replace(/\\\|/g,'|');}
  state.pos+=match[0].length;return true;
 });
 md.inline.ruler.before('escape','vault_math',(state,silent)=>{
  const match=/^\$([^\s$][^\n$]*?)\$(?!\d)/.exec(state.src.slice(state.pos));if(!match)return false;
  if(!silent){const token=state.push('vault_math','',0);token.content=match[1];}
  state.pos+=match[0].length;return true;
 });
 return md;
}
function inline(tokens:Token[]):JSONContent[]{
 const nodes:JSONContent[]=[],marks:NonNullable<JSONContent['marks']>=[];
 const names:Record<string,string>={strong:'bold',em:'italic',s:'strike'};
 for(const token of tokens){
  if(token.type==='text'||token.type==='html_inline'){if(token.content)nodes.push(textNode(token.content,[...marks]));}
  else if(token.type==='softbreak')nodes.push(textNode(' ',[...marks]));
  else if(token.type==='hardbreak')nodes.push({type:'hardBreak',...(marks.length?{marks:[...marks]}:{})});
  else if(token.type==='code_inline')nodes.push(textNode(token.content,[...marks,{type:'code'}]));
  else if(token.type==='link_open')marks.push({type:'link',attrs:{href:token.attrGet('href')||'',title:token.attrGet('title')}});
  else if(token.type==='link_close'){for(let at=marks.length-1;at>=0;at--)if(marks[at].type==='link'){marks.splice(at,1);break;}}
  else if(token.type==='image')nodes.push({type:'vaultImage',attrs:{src:token.attrGet('src')||'',alt:token.content,title:token.attrGet('title')||''},...(marks.length?{marks:[...marks]}:{})});
  else if(token.type==='vault_link'){
   const [target,...labels]=token.content.split('|');nodes.push({type:'wikiLink',attrs:{target,label:labels.join('|')||target.split('/').pop()||target},...(marks.length?{marks:[...marks]}:{})});
  }else if(token.type==='vault_math')nodes.push({type:'inlineMath',attrs:{formula:token.content},...(marks.length?{marks:[...marks]}:{})});
  else if(token.type==='vault_embed')throw new Error('Embedded note is an opaque block');
  else if(token.type.endsWith('_open')&&names[token.type.slice(0,-5)])marks.push({type:names[token.type.slice(0,-5)]});
  else if(token.type.endsWith('_close')&&names[token.type.slice(0,-6)]){
   const kind=names[token.type.slice(0,-6)];for(let at=marks.length-1;at>=0;at--)if(marks[at].type===kind){marks.splice(at,1);break;}
  }else throw new Error('Unsupported inline token: '+token.type);
 }
 return nodes;
}
function parseTokens(tokens:Token[]):JSONContent[]{
 const root:JSONContent={type:'doc',content:[]},stack=[root];
 const append=(node:JSONContent)=>stack.at(-1)!.content!.push(node);
 const open=(node:JSONContent)=>{append(node);stack.push(node);};
 const names:Record<string,string>={paragraph:'paragraph',heading:'heading',blockquote:'blockquote',bullet_list:'bulletList',ordered_list:'orderedList',list_item:'listItem',table:'table',tr:'tableRow',th:'tableHeader',td:'tableCell'};
 for(const token of tokens){
  if(token.type==='inline'){
   const item=stack.at(-2),task=/^\[([ xX])\] /.exec(token.content);if(item?.type==='listItem'&&task)item.attrs={taskMarker:true,checked:task[1]!==' '};
   stack.at(-1)!.content!.push(...inline(token.children||[]));continue;
  }
  if(token.type.endsWith('_open')&&names[token.type.slice(0,-5)]){
   const name=token.type.slice(0,-5);let attrs:Record<string,any>|undefined;
   if(name==='heading')attrs={level:Number(token.tag.slice(1))};
   if(name==='ordered_list')attrs={start:Number(token.attrGet('start')||1)};
   if(name==='td'||name==='th'){const align=/text-align:(left|center|right)/.exec(token.attrGet('style')||'');attrs={align:align?.[1]||null};}
   open({type:names[name],...(attrs?{attrs}:{}),content:[]});continue;
  }
  if(token.type.endsWith('_close')){if(names[token.type.slice(0,-6)]){if(token.type==='td_close'||token.type==='th_close'){const cell=stack.at(-1)!;cell.content=[{type:'paragraph',content:cell.content}];}stack.pop();}continue;}
  if(token.type==='thead_open'||token.type==='tbody_open')continue;
  if(token.type==='fence'||token.type==='code_block'){append({type:'codeBlock',attrs:{language:token.info.trim().split(/\s/)[0]||null},content:token.content? [textNode(token.content.replace(/\n$/,''))]:[]});continue;}
  if(token.type==='hr'){append({type:'horizontalRule'});continue;}
  throw new Error('Unsupported block token: '+token.type);
 }
 const tasks=(node:JSONContent)=>{
  node.content?.forEach(tasks);
  if(node.type!=='bulletList'&&node.type!=='orderedList')return;
  const items=node.content||[],allTasks=items.length>0&&items.every(item=>item.attrs?.taskMarker);
  if(allTasks&&node.type==='bulletList')node.type='taskList';
  for(const item of items){
   if(!item.attrs?.taskMarker)continue;
   item.type='taskItem';const first=item.content![0].content![0],match=/^\[([ xX])\] /.exec(first.text!)!;
   item.attrs={checked:item.attrs.checked};first.text=first.text!.slice(match[0].length);
   if(!first.text)item.content![0].content!.shift();
  }
 };
 root.content!.forEach(tasks);return root.content!;
}
function special(raw:string):JSONContent|null{
 let kind='',content='';
 const fence=/^\s*(`{3,}|~{3,})([^\r\n]*)\r?\n([\s\S]*?)\r?\n\s*\1\s*$/.exec(raw);
 if(fence&&['mermaid','dataview'].includes(fence[2].trim())){kind=fence[2].trim()==='mermaid'?'mermaid':'query';content=fence[3];}
 else if(/^\s*\$\$/.test(raw)){kind='math';content=raw.trim().replace(/^\$\$\s*\n?|\n?\s*\$\$$/g,'');}
 else if(/^\s*!\[\[[\s\S]*\]\]\s*$/.test(raw)){kind='embed';content=raw.trim().slice(3,-2);}
 return kind?{type:'specialBlock',attrs:{kind,raw,content}}:null;
}
const opaque=(raw:string,kind='protected'):JSONContent=>({type:'specialBlock',attrs:{kind,raw,content:raw}});

export function parseRichMarkdown(text:string):ParsedRichDocument{
 const md=parser(),front=/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/.exec(text)?.[0]||'',body=text.slice(front.length),offsets=[front.length];
 for(let i=0;i<body.length;i++)if(body[i]==='\n')offsets.push(front.length+i+1);offsets.push(text.length);
 const tokens=md.parse(body,{}),blocks:RichBlock[]=[];
 let group:Token[]=[],start=front.length,end=front.length,lastEnd=front.length;
 const push=(from:number,to:number,node:JSONContent,raw=text.slice(from,to))=>{
  const id=richId(),before=text.slice(lastEnd,from);node.attrs={...node.attrs,sourceId:id};
  blocks.push({id,from,to,raw,before,node});lastEnd=to;
 };
 const flush=()=>{
  if(!group.length)return;
  let to=end;if(text.slice(to-2,to)==='\r\n')to-=2;else if(text[to-1]==='\n')to--;
  const gap=text.slice(lastEnd,start);
  if(gap.trim())push(lastEnd,start,opaque(gap,'definitions'));
  const raw=text.slice(start,to);let node=special(raw);
  if(!node){try{const parsed=parseTokens(group);node=parsed.length===1?parsed[0]:opaque(raw);}catch{node=opaque(raw);}}
  push(start,to,node);group=[];
 };
 for(const token of tokens){
  if(!group.length)start=offsets[token.map?.[0]||0];if(token.map)end=offsets[token.map[1]]??text.length;
  group.push(token);if(token.level===0&&token.nesting!==1)flush();
 }
 flush();
 // Math delimiters aren't Markdown-it block tokens. Merge their token spans
 // before exposing a formula as editable prose.
 for(let i=0;i<blocks.length;i++){
  const block=blocks[i];if(!block.raw.trimStart().startsWith('$$'))continue;
  let j=i,raw=block.raw;
  while(!/\$\$\s*$/.test(raw.slice(2))&&j+1<blocks.length){j++;raw=text.slice(block.from,blocks[j].to);}
  const node=special(raw);if(node){node.attrs={...node.attrs,sourceId:block.id};blocks.splice(i,j-i+1,{...block,to:blocks[j].to,raw,node});}
 }
 if(!blocks.length&&body.trim())push(front.length,text.length,opaque(body,'definitions'));
 if(!blocks.length){
  const prefix=text;const id=richId(),node={type:'paragraph',attrs:{sourceId:id},content:[]} as JSONContent;
  return {text,prefix,suffix:'',blocks:[{id,from:text.length,to:text.length,raw:'',before:'',node}],doc:{type:'doc',content:[node]},eol:text.includes('\r\n')?'\r\n':'\n'};
 }
 const trailing=text.slice(blocks.at(-1)!.to);
 if(trailing.trim()){const from=blocks.at(-1)!.to;push(from,text.length,opaque(trailing,'definitions'));}
 const prefix=text.slice(0,blocks[0].from);blocks[0].before='';let suffix=text.slice(blocks.at(-1)!.to);
 if(['table','bulletList','orderedList','taskList','blockquote','specialBlock','codeBlock','horizontalRule'].includes(blocks.at(-1)!.node.type!)){
  const id=richId(),node:JSONContent={type:'paragraph',attrs:{sourceId:id},content:[]};
  // A cursor after a non-text block is a view affordance, not a file edit.
  blocks.push({id,from:text.length,to:text.length,raw:'',before:suffix,node,virtual:true});suffix='';
 }
 return {text,prefix,suffix,blocks,doc:{type:'doc',content:blocks.map(block=>block.node)},eol:text.includes('\r\n')?'\r\n':'\n'};
}

const escapeText=(text:string)=>text.replace(/\\/g,'\\\\').replace(/([`*_[\]~])/g,'\\$1').replace(/(^|\n)([ \t]*)(\d+)([.)]) /g,'$1$2$3\\$4 ').replace(/(^|\n)([ \t]*)([>#]|[-+]) /g,'$1$2\\$3 ');
const urlText=(url:string)=>url.replace(/[()\s<>]/g,char=>encodeURIComponent(char).replace(/\(/g,'%28').replace(/\)/g,'%29'));
function inlineMarkdown(nodes:JSONContent[]=[]):string{
 let out='',active:NonNullable<JSONContent['marks']>=[];
 const equivalent=(a:any,b:any)=>a.type===b.type&&JSON.stringify(a.attrs||{})===JSON.stringify(b.attrs||{})&&a.fence===b.fence&&a.pad===b.pad;
 const emphasis=(mark:{type:string})=>['bold','italic','strike'].includes(mark.type);
 const prepared:JSONContent[]=[];
 nodes.forEach((node,index)=>{
  if(node.type!=='text'||!node.marks?.some(emphasis)){prepared.push(node);return;}
  const text=node.text||'',match=/^(\s*)([\s\S]*?)(\s*)$/.exec(text)!,before=nodes[index-1]?.marks||[],after=nodes[index+1]?.marks||[];
  if(!match[2]){prepared.push({...node,marks:node.marks.filter(mark=>!emphasis(mark)||before.some(value=>equivalent(value,mark))&&after.some(value=>equivalent(value,mark)))});return;}
  if(match[1])prepared.push({...node,text:match[1],marks:node.marks.filter(mark=>!emphasis(mark)||before.some(value=>equivalent(value,mark)))});
  prepared.push({...node,text:match[2]});
  if(match[3])prepared.push({...node,text:match[3],marks:node.marks.filter(mark=>!emphasis(mark)||after.some(value=>equivalent(value,mark)))});
 });
 const opening=(mark:any)=>mark.type==='code'?(mark.fence||'`')+(mark.pad||''):({bold:'**',italic:'*',strike:'~~',link:'['}[mark.type as string]||'');
 const closing=(mark:any)=>mark.type==='link'?']('+urlText(mark.attrs.href)+(mark.attrs.title?' "'+String(mark.attrs.title).replace(/"/g,'\\"')+'"':'')+')':mark.type==='code'?(mark.pad||'')+(mark.fence||'`'):opening(mark);
 for(const node of prepared){
  const marks=(node.marks||[]).map(mark=>mark.type==='code'?{...mark,fence:'`'.repeat(Math.max(0,...[...(node.text||'').matchAll(/`+/g)].map(match=>match[0].length))+1),pad:/^`|`$|^ .* $/.test(node.text||'')?' ':''}:mark);let same=0;while(same<active.length&&same<marks.length&&equivalent(active[same],marks[same]))same++;
  for(let i=active.length-1;i>=same;i--)out+=closing(active[i]);
  for(let i=same;i<marks.length;i++)out+=opening(marks[i]);active=marks;
  if(node.type==='text')out+=marks.some(mark=>mark.type==='code')?node.text||'':escapeText(node.text||'');
  else if(node.type==='hardBreak')out+='  \n';
  else if(node.type==='wikiLink'){
   const target=node.attrs?.target||'',label=node.attrs?.label||'';out+='[['+target+(label&&label!==target.split('/').pop()?'|'+label:'')+']]';
  }else if(node.type==='inlineMath')out+='$'+(node.attrs?.formula||'')+'$';
  else if(node.type==='vaultImage')out+='!['+String(node.attrs?.alt||'').replace(/[\\[\]]/g,'\\$&')+']('+urlText(node.attrs?.src||'')+(node.attrs?.title?' "'+String(node.attrs.title).replace(/"/g,'\\"')+'"':'')+')';
 }
 for(let i=active.length-1;i>=0;i--)out+=closing(active[i]);
 return out;
}
export function serializeRichNode(node:JSONContent):string{
 const children=node.content||[];
 if(node.type==='paragraph')return inlineMarkdown(children);
 if(node.type==='heading')return '#'.repeat(node.attrs?.level||1)+' '+inlineMarkdown(children);
 if(node.type==='horizontalRule')return '---';
 if(node.type==='specialBlock')return node.attrs?.raw||'';
 if(node.type==='codeBlock'){
  const text=children.map(child=>child.text||'').join(''),longest=Math.max(2,...[...text.matchAll(/`+/g)].map(match=>match[0].length)),fence='`'.repeat(longest+1);
  return fence+(node.attrs?.language||'')+'\n'+text+'\n'+fence;
 }
 if(node.type==='blockquote')return children.map(serializeRichNode).join('\n\n').split('\n').map(line=>'> '+line).join('\n');
 if(node.type==='bulletList'||node.type==='orderedList'||node.type==='taskList'){
  return children.map((item,index)=>{
   const marker=node.type==='orderedList'?String((node.attrs?.start??1)+index)+'. ':'- ',prefix=marker+(item.type==='taskItem'||node.type==='taskList'?'['+(item.attrs?.checked?'x':' ')+'] ':''),indent=marker.length;
   const parts=(item.content||[]).map(serializeRichNode),body=parts.map((part,i)=>i>0?'\n'+part:part).join('\n');
   return prefix+body.split('\n').map((line,i)=>i?' '.repeat(indent)+line:line).join('\n');
  }).join('\n');
 }
 if(node.type==='table'){
  if(!children.length)return '|  |\n| --- |';
  const rows=children.map(row=>(row.content||[]).map(cell=>inlineMarkdown(cell.content?.[0]?.content).replace(/\|/g,'\\|').replace(/\s*\n\s*/g,' ')));
  const lines=rows.map(row=>'| '+row.join(' | ')+' |');
  lines.splice(1,0,'| '+(children[0].content||[]).map(cell=>cell.attrs?.align==='center'?':---:':cell.attrs?.align==='right'?'---:':cell.attrs?.align==='left'?':---':'---').join(' | ')+' |');
  return lines.join('\n');
 }
 if(node.type==='doc'||node.type==='listItem'||node.type==='taskItem'||node.type==='tableCell'||node.type==='tableHeader')return children.map(serializeRichNode).join('\n\n');
 throw new Error('Unsupported rich node: '+node.type);
}
function fingerprint(node:JSONContent):string{
 const strip=(value:any):any=>Array.isArray(value)?value.map(strip):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).filter(([key])=>key!=='sourceId').map(([key,v])=>[key,strip(v)])):value;
 return JSON.stringify(strip(node));
}
type BoundBlock=RichBlock&{snapshot?:PMNode,fingerprint?:string};
export class MarkdownBridge{
 text:string;prefix:string;suffix:string;eol:string;blocks:BoundBlock[];
 constructor(parsed:ParsedRichDocument){this.text=parsed.text;this.prefix=parsed.prefix;this.suffix=parsed.suffix;this.eol=parsed.eol;this.blocks=parsed.blocks;}
 bind(doc:PMNode){doc.forEach(node=>{const record=this.blocks.find(block=>block.id===node.attrs.sourceId);if(record){record.snapshot=node;record.fingerprint=fingerprint(node.toJSON());}});}
 update(doc:PMNode){
  const old=this.blocks,records=new Map(old.map((block,index)=>[block.id,{block,index}])),next:BoundBlock[]=[];let output=this.prefix,previous=-1;
  doc.forEach(node=>{
   const id=node.attrs.sourceId||richId(),entry=records.get(id)||records.get(String(id).split('~')[0]),shape=entry?.block.snapshot===node?entry.block.fingerprint:fingerprint(node.toJSON());
   const raw=entry&&shape===entry.block.fingerprint?entry.block.raw:serializeRichNode(node.toJSON()).replace(/\r?\n/g,this.eol);
   let before=!next.length?'':entry&&entry.index===previous+1?entry.block.before:this.eol+this.eol;
   if(next.length&&entry?.block.virtual&&raw&&!/\n[ \t\r]*\n/.test(before))before=this.eol+this.eol;
   output+=before;const from=output.length;output+=raw;
   next.push({id,from,to:output.length,raw,before,node:node.toJSON(),snapshot:node,fingerprint:shape,virtual:!!entry?.block.virtual&&!raw});previous=entry?.index??-2;
  });
  // Retain the document's trailing whitespace, including a missing final newline.
  output+=this.suffix;this.blocks=next;this.text=output;return output;
 }
 blockAtSource(position:number){return this.blocks.find(block=>position>=block.from&&position<=block.to)||this.blocks.find(block=>block.from>=position)||this.blocks.at(-1);}
 private points(node:PMNode,raw:string){
  const points:{pm:number,source:number}[]=[{pm:node.isTextblock?1:0,source:0}],prefix=node.type.name==='codeBlock'?raw.indexOf('\n')+1:node.type.name==='heading'?(/^#{1,6} +/.exec(raw)?.[0].length||0):0;
  let seek=prefix;
  node.descendants((child,pos)=>{
   if(child.isText){
    const text=child.text||'',direct=raw.indexOf(text,seek);
    if(direct>=0){for(let i=0;i<=text.length;i++)points.push({pm:pos+1+i,source:direct+i});seek=direct+text.length;}
    else for(let i=0;i<text.length;i++){
     let at=raw.indexOf(text[i],seek);if(at<0&&/\s/.test(text[i]))at=raw.slice(seek).search(/\s/)+seek;if(at<seek)at=seek;
     points.push({pm:pos+1+i,source:at},{pm:pos+2+i,source:Math.min(raw.length,at+1)});seek=Math.min(raw.length,at+1);
    }
   }else if(child.isLeaf){
    let from=seek,to=seek;
    const token=child.type.name==='wikiLink'?'[['+child.attrs.target:child.type.name==='inlineMath'?'$'+child.attrs.formula:child.type.name==='vaultImage'?'![':null;
    if(token){const at=raw.indexOf(token,seek);if(at>=0){from=at;to=child.type.name==='wikiLink'?raw.indexOf(']]',at)+2:child.type.name==='inlineMath'?at+token.length+1:raw.indexOf(')',at)+1;}}
    points.push({pm:pos+1,source:from},{pm:pos+1+child.nodeSize,source:Math.max(from,to)});seek=Math.max(seek,to);
   }
  });
  points.push({pm:node.isTextblock?node.nodeSize-1:node.nodeSize,source:raw.length});return points;
 }
 toSource(doc:PMNode,position:number,assoc=1):number{
  let result=this.text.length;doc.forEach((node,pos)=>{
   if(position<pos||position>pos+node.nodeSize)return;
   const block=this.blocks.find(block=>block.id===node.attrs.sourceId);if(!block)return;
   if(node.isAtom){result=position<=pos?block.from:block.to;return;}
   const relative=position-pos,points=this.points(node,block.raw),exact=points.filter(point=>point.pm===relative);
   const point=exact.length?(assoc<0?exact[0]:exact.at(-1)!):points.reduce((best,item)=>Math.abs(item.pm-relative)<Math.abs(best.pm-relative)?item:best,points[0]);
   result=block.from+point.source;
  });return result;
 }
 toEditor(doc:PMNode,position:number):number{
  const block=this.blockAtSource(position);if(!block)return 0;let result=0;
  doc.forEach((node,pos)=>{if(node.attrs.sourceId!==block.id)return;const points=this.points(node,block.raw),relative=position-block.from;
   const point=points.reduce((best,item)=>Math.abs(item.source-relative)<Math.abs(best.source-relative)?item:best,points[0]);result=Math.max(pos,Math.min(pos+node.nodeSize,pos+point.pm));
  });return Math.max(0,Math.min(doc.content.size,result));
 }
}
