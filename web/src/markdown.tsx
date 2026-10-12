import React,{useEffect,useRef,useState} from 'react';
import {createRoot,Root} from 'react-dom/client';
import MarkdownIt from 'markdown-it';
import katexPlugin from '@traptitech/markdown-it-katex';
import taskLists from 'markdown-it-task-lists';
import DOMPurify from 'dompurify';
import mermaid from 'mermaid';
import {EditorState,RangeSetBuilder} from '@codemirror/state';
import {EditorView,Decoration,WidgetType,keymap,ViewPlugin} from '@codemirror/view';
import {defaultKeymap,history,historyKeymap} from '@codemirror/commands';
import {search,searchKeymap} from '@codemirror/search';
import {markdown} from '@codemirror/lang-markdown';
import {api,media,OpenNote} from './api';
import 'katex/dist/katex.min.css';
import {VideoPlayer} from './media';
import {BaseViewer} from './base';

const md=new MarkdownIt({html:false,linkify:true}).use(katexPlugin,{throwOnError:false}).use(taskLists,{enabled:true,label:false});
mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'neutral',flowchart:{htmlLabels:false}});
const originalFence=md.renderer.rules.fence!;
md.renderer.rules.fence=(t,i,o,e,self)=>t[i].info.trim()==='mermaid'?'<pre class="mermaid" data-diagram="'+md.utils.escapeHtml(t[i].content)+'">'+md.utils.escapeHtml(t[i].content)+'</pre>':originalFence(t,i,o,e,self);
md.inline.ruler.before('link','wikilink',(state,silent)=>{
 const match=/^(!?)\[\[([^\]\n]+)\]\]/.exec(state.src.slice(state.pos));if(!match)return false;
 if(!silent){const token=state.push('html_inline','',0);const [target,...alias]=match[2].split('|');token.content=match[1]?`<span class="embed-placeholder" data-embed="${md.utils.escapeHtml(target)}"></span>`:`<a class="wikilink" href="#" data-note="${md.utils.escapeHtml(target)}">${md.utils.escapeHtml(alias.join('|')||target.split('/').pop()||target)}</a>`;}
 state.pos+=match[0].length;return true;
});
const imageRule=md.renderer.rules.image!;
md.renderer.rules.image=(t,i,o,e,self)=>{const target=t[i].attrGet('src')||'';t[i].attrSet('data-vault-src',target);t[i].attrSet('src','');return imageRule(t,i,o,e,self);};
export const stripFrontmatter=(text:string)=>text.replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/,'');

export function QueryView({query,onOpen}:{query:string,onOpen:OpenNote}){
 const [data,setData]=useState<any>();const [error,setError]=useState('');
 useEffect(()=>{let active=true;api('query',{query}).then(x=>active&&setData(x)).catch(e=>active&&setError(e.message));return()=>{active=false;};},[query]);
 const value=(v:any):React.ReactNode=>v===null||v===undefined?'—':Array.isArray(v)?v.map((x,i)=><React.Fragment key={i}>{i>0?', ':''}{value(x)}</React.Fragment>):typeof v==='object'&&v.label?v.path?<button className="text-link" onClick={()=>onOpen(v.path)}>{v.label}</button>:v.label:typeof v==='string'&&v.startsWith('[[')?<button className="text-link" onClick={()=>onOpen(v.slice(2,-2).split('|')[0])}>{v.slice(2,-2)}</button>:String(v);
 if(error)return <div className="query-error">{error}<details><summary>查看查询</summary><pre>{query}</pre></details></div>;
 if(!data)return <div className="subtle">正在读取目录…</div>;
 if(data.kind==='list')return <ul>{data.rows.map((row:any)=><li key={row.path}>{value(row.values['文件']||Object.values(row.values)[0])}</li>)}</ul>;
 return <div className="table-scroll"><table><thead><tr>{data.headers.map((h:string)=><th key={h}>{h}</th>)}</tr></thead><tbody>{data.rows.map((row:any,i:number)=><tr key={row.path+i}>{data.headers.map((h:string)=><td key={h}>{value(row.values[h])}</td>)}</tr>)}</tbody></table>{!data.rows.length&&<p className="subtle">暂无符合条件的笔记</p>}</div>;
}

function Embed({target,source,onOpen,depth}:{target:string,source:string,onOpen:OpenNote,depth:number}){
 const [path,setPath]=useState('');const [text,setText]=useState('');const [error,setError]=useState('');
 useEffect(()=>{let active=true;api('resolve?target='+encodeURIComponent(target)+'&source='+encodeURIComponent(source)).then(async d=>{if(d.candidates.length!==1){if(active)setError(d.candidates.length?'同名附件，请点击选择':'嵌入目标不存在');return;}const p=d.candidates[0];if(!active)return;setPath(p);if(p.endsWith('.md')&&depth<2){const note=await api('file?path='+encodeURIComponent(p));if(active){let value=note.text;const anchor=target.split('#')[1];if(anchor){const lines=value.split('\n');if(anchor.startsWith('^')){const i=lines.findIndex((line:string)=>line.trim().endsWith(anchor));if(i>=0){let start=i;while(start>0&&lines[start-1].trim())start--;value=lines.slice(start,i+1).join('\n');}}else{const i=lines.findIndex((line:string)=>/^#{1,6} /.test(line)&&line.replace(/^#+ /,'').trim()===anchor);if(i>=0){const level=lines[i].match(/^#+/)![0].length;let end=i+1;while(end<lines.length&&!new RegExp('^#{1,'+level+'} ').test(lines[end]))end++;value=lines.slice(i,end).join('\n');}}}setText(value);}}}).catch(e=>active&&setError(e.message));return()=>{active=false;};},[target,source,depth]);
 if(error)return <button className="missing-link" onClick={()=>onOpen(target)}>{error} · {target}</button>;
 if(!path)return <span className="subtle">加载附件…</span>;
 if(/\.(png|jpe?g|webp|gif|avif|svg)$/i.test(path))return <img src={media(path)} alt={target}/>;
 if(/\.(mp4|webm|mov|m4v)$/i.test(path))return <VideoPlayer path={path}/>;
 if(/\.(mp3|m4a|wav|ogg|flac)$/i.test(path))return <audio controls preload="metadata" src={media(path)}/>;
 if(path.endsWith('.base'))return <div className="embedded-note"><BaseViewer path={path} onOpen={onOpen} notify={setError}/></div>;
 if(path.endsWith('.md')&&text)return <div className="embedded-note"><button className="text-link" onClick={()=>onOpen(path)}>{path.split('/').pop()}</button><MarkdownPreview text={text} path={path} onOpen={onOpen} depth={depth+1}/></div>;
 return <button className="text-link" onClick={()=>onOpen(path)}>{target}</button>;
}

export function MarkdownPreview({text,path,onOpen,onTask,depth=0}:{text:string,path:string,onOpen:OpenNote,onTask?:(index:number)=>void,depth?:number}){
 const ref=useRef<HTMLDivElement>(null);const [embeds,setEmbeds]=useState<{target:string,element:HTMLElement}[]>([]);const roots=useRef<Map<HTMLElement,Root>>(new Map());const openRef=useRef(onOpen);openRef.current=onOpen;const stableOpen=useRef<OpenNote>((target,anchor)=>openRef.current(target,anchor)).current;
 const body=stripFrontmatter(text);const sections=body.split(/(^```dataview\s*\n[\s\S]*?^```\s*$)/m);
 useEffect(()=>{
  const el=ref.current;if(!el)return;let active=true;
  el.querySelectorAll<HTMLElement>('pre.mermaid').forEach(async node=>{const diagram=node.dataset.diagram||node.textContent||'';if(node.dataset.rendered===diagram)return;node.dataset.rendered=diagram;try{const id='m'+Math.random().toString(36).slice(2);const svg=await mermaid.render(id,diagram);if(active){node.innerHTML=DOMPurify.sanitize(svg.svg,{USE_PROFILES:{svg:true,svgFilters:true}});node.classList.add('rendered');}}catch(e){node.textContent='图表无法渲染：'+String(e);}});
  el.querySelectorAll<HTMLImageElement>('img[data-vault-src]').forEach(async image=>{const target=image.dataset.vaultSrc||'';if(/^https?:/.test(target)){image.src=target;return;}try{const d=await api('resolve?target='+encodeURIComponent(target)+'&source='+encodeURIComponent(path));if(active&&d.candidates.length===1)image.src=media(d.candidates[0]);}catch{image.alt='附件未找到：'+target;}});
  const found=Array.from(el.querySelectorAll<HTMLElement>('[data-embed]')).map(element=>({target:element.dataset.embed!,element}));setEmbeds(found);
  el.querySelectorAll<HTMLInputElement>('input[type=checkbox]').forEach((input,i)=>{input.disabled=!onTask;input.dataset.task=String(i);});
  return()=>{active=false;};
 },[body,path]);
 useEffect(()=>{const elements=new Set(embeds.map(e=>e.element));for(const [element,root] of roots.current){if(!elements.has(element)){roots.current.delete(element);queueMicrotask(()=>root.unmount());}}for(const {target,element} of embeds){let root=roots.current.get(element);if(!root){root=createRoot(element);roots.current.set(element,root);}root.render(<Embed target={target} source={path} onOpen={stableOpen} depth={depth}/>);}},[embeds,path,stableOpen,depth]);
 useEffect(()=>()=>{const old=Array.from(roots.current.values());roots.current.clear();queueMicrotask(()=>old.forEach(root=>root.unmount()));},[]);

 return <div ref={ref} className="markdown" onClick={e=>{const input=e.target as HTMLInputElement;if(input.type==='checkbox'&&input.dataset.task!==undefined){onTask?.(Number(input.dataset.task));return;}const anchor=(e.target as HTMLElement).closest<HTMLAnchorElement>('a');if(!anchor)return;const target=anchor.dataset.note||anchor.getAttribute('href')||'';if(!target||/^https?:|^mailto:/.test(target)){anchor.target='_blank';anchor.rel='noopener';return;}e.preventDefault();onOpen(target);}}>{sections.map((part,i)=>part.startsWith('```dataview')?<QueryView key={i} query={part.replace(/^```dataview\s*\n/,'').replace(/\n```\s*$/,'')} onOpen={onOpen}/>:<div key={i} dangerouslySetInnerHTML={{__html:DOMPurify.sanitize(md.render(part),{ADD_ATTR:['data-note','data-embed','data-vault-src','data-diagram']})}}/>)}</div>;
}

class WikiLinkWidget extends WidgetType{
 constructor(readonly target:string,readonly label:string,readonly open:OpenNote){super();}
 eq(other:WikiLinkWidget){return other.target===this.target&&other.label===this.label;}
 toDOM(){const a=document.createElement('a');a.textContent=this.label;a.href='#';a.className='live-wikilink';a.onclick=e=>{e.preventDefault();e.stopPropagation();this.open(this.target);};return a;}
 ignoreEvent(){return true;}
}

class MarkdownWidget extends WidgetType{
 root?:Root;
 constructor(readonly text:string,readonly path:string,readonly open:OpenNote,readonly from:number,readonly task:(pos:number)=>void){super();}
 eq(other:MarkdownWidget){return other.text===this.text&&other.path===this.path&&other.from===this.from;}
 toDOM(){const div=document.createElement('div');div.className='live-widget';this.root=createRoot(div);this.root.render(<MarkdownPreview text={this.text} path={this.path} onOpen={this.open} onTask={i=>{const matches=[...this.text.matchAll(/^[ \t]*[-*+] \[([ xX])\]/gm)];if(matches[i])this.task(this.from+matches[i].index!+matches[i][0].indexOf('[')+1);}}/>);return div;}
 destroy(){const root=this.root;queueMicrotask(()=>root?.unmount());}
 ignoreEvent(){return true;}
}

export function LiveEditor({initial,path,onChange,onOpen,source,onReady}:{initial:string,path:string,onChange:(text:string)=>void,onOpen:OpenNote,source:boolean,onReady?:(view:EditorView)=>void}){
 const host=useRef<HTMLDivElement>(null);const view=useRef<EditorView|null>(null);const callbacks=useRef({onChange,onOpen});callbacks.current={onChange,onOpen};
 useEffect(()=>{
  if(!host.current)return;
  const open:OpenNote=(target,anchor)=>callbacks.current.onOpen(target,anchor);
  const makeDecorations=(v:EditorView)=>{
   const ranges:any[]=[];const builder={add:(from:number,to:number,d:Decoration)=>ranges.push(d.range(from,to)),finish:()=>Decoration.set(ranges,true)};if(source)return builder.finish();const doc=v.state.doc;const cursor=v.state.selection.main;let line=1;
   const task=(pos:number)=>{const editor=view.current;if(!editor)return;const current=editor.state.doc.sliceString(pos,pos+1);editor.dispatch({changes:{from:pos,to:pos+1,insert:current===' '? 'x':' '}});};
   while(line<=doc.lines){const start=doc.line(line);let end=line;let block=false;
    if(start.text.startsWith('```')||start.text.trim()==='$$'){const marker=start.text.startsWith('```')?'```':'$$';while(end<doc.lines){end++;if(doc.line(end).text.startsWith(marker))break;}block=end>line;}
    else if(start.text.startsWith('|')&&line<doc.lines&&/^\s*\|?[\s:|-]+\|/.test(doc.line(line+1).text)){while(end<doc.lines&&doc.line(end+1).text.startsWith('|'))end++;block=true;}
    else if(/^!\[\[.*\]\]$/.test(start.text.trim())||/^[ \t]*[-*+] \[[ xX]\]/.test(start.text))block=true;
    else if(start.text.trim()==='---'&&line===1){block=true;while(end<doc.lines){end++;if(doc.line(end).text.trim()==='---')break;}}
    const last=doc.line(end);const active=cursor.from<=last.to&&cursor.to>=start.from;
    if(block&&!active){const text=doc.sliceString(start.from,last.to);builder.add(start.from,last.to,Decoration.replace({widget:new MarkdownWidget(text,path,open,start.from,task),block:true}));line=end+1;continue;}
    const heading=/^(#{1,6}) /.exec(start.text);if(heading){builder.add(start.from,start.to,Decoration.mark({class:'cm-heading cm-h'+heading[1].length}));if(!active)builder.add(start.from,start.from+heading[0].length,Decoration.replace({}));}
    // Decorations must be ordered; inline ranges are collected then sorted.
    if(!active){const ranges:{from:number,to:number,dec:Decoration}[]=[];for(const m of start.text.matchAll(/(?<!!)\[\[([^\]\n]+)\]\]/g)){const [target,...aliases]=m[1].split('|');const pos=start.from+m.index!;ranges.push({from:pos,to:pos+m[0].length,dec:Decoration.replace({widget:new WikiLinkWidget(target,aliases.join('|')||target.split('/').pop()||target,open)})});}for(const m of start.text.matchAll(/\*\*([^*]+)\*\*/g)){const pos=start.from+m.index!;ranges.push({from:pos,to:pos+2,dec:Decoration.replace({})},{from:pos+2,to:pos+m[0].length-2,dec:Decoration.mark({class:'cm-bold'})},{from:pos+m[0].length-2,to:pos+m[0].length,dec:Decoration.replace({})});}ranges.sort((a,b)=>a.from-b.from);for(const x of ranges)builder.add(x.from,x.to,x.dec);}
    line++;
   }
   return builder.finish();
  };
  // Block decorations are a direct state facet, not viewport decorations.
  const plugin=EditorView.decorations.compute(['doc','selection'],state=>makeDecorations({state} as EditorView));
  const bold={key:'Mod-b',run:(v:EditorView)=>{const s=v.state.selection.main;v.dispatch({changes:{from:s.from,to:s.to,insert:'**'+v.state.doc.sliceString(s.from,s.to)+'**'}});return true;}};
  const state=EditorState.create({doc:initial,extensions:[markdown(),history(),search(),keymap.of([bold,...searchKeymap,...defaultKeymap,...historyKeymap]),EditorState.phrases.of({'Find':'查找','Replace':'替换','next':'下一个','previous':'上一个','all':'全部','match case':'区分大小写','regexp':'正则表达式','by word':'整词','close':'关闭','replace':'替换','replace all':'全部替换'}),EditorView.lineWrapping,plugin,EditorView.updateListener.of(update=>{if(update.docChanged)callbacks.current.onChange(update.state.doc.toString());}),EditorView.theme({'&':{fontSize:'16px'},'.cm-content':{fontFamily:'inherit',padding:'26px 44px',minHeight:'65vh'},'.cm-focused':{outline:'none'}})]});
  const editor=new EditorView({state,parent:host.current});view.current=editor;onReady?.(editor);
  return()=>{view.current=null;editor.destroy();};
 },[path,source]);
 return <div className="live-editor" ref={host}/>;
}
