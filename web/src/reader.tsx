import React,{lazy,memo,Suspense,useEffect,useMemo,useRef,useState} from 'react';
import {createRoot,Root} from 'react-dom/client';
import DOMPurify from 'dompurify';
import {api,affected,Change,media,OpenNote} from './api';
import {useApi} from './hooks';
import {VirtualList,VirtualTableBody} from './virtual';
import {VideoPlayer} from './media';
import {HtmlBlock,ReadingJump} from './html-block';
import {Block,blocks,createMarkdown,hasMath,stripFrontmatter} from './markdown-core';
export {stripFrontmatter};
const BaseViewer=lazy(()=>import('./base').then(module=>({default:module.BaseViewer})));
let diagramModule:Promise<typeof import('mermaid')>|undefined;
const diagrams=()=>diagramModule||(diagramModule=import('mermaid').then(module=>{module.default.initialize({startOnLoad:false,securityLevel:'strict',theme:'neutral',htmlLabels:false,flowchart:{htmlLabels:false}});return module;}));

export function QueryView({query,onOpen}:{query:string,onOpen:OpenNote}){
 const [data,setData]=useState<any>(),[error,setError]=useState('');
 useEffect(()=>{const controller=new AbortController();let alive=true;const load=()=>api('query',{query},undefined,{signal:controller.signal}).then(value=>{if(alive)setData(value);}).catch(e=>{if(alive&&e.name!=='AbortError')setError(e.message);});void load();const changed=()=>void load();window.addEventListener('vault-data-changed',changed);return()=>{alive=false;controller.abort();window.removeEventListener('vault-data-changed',changed);};},[query]);
 const value=(v:any):React.ReactNode=>v===null||v===undefined?'—':Array.isArray(v)?v.map((x,i)=><React.Fragment key={i}>{i>0?', ':''}{value(x)}</React.Fragment>):typeof v==='object'&&v.label?v.path?<button className="text-link" onClick={()=>onOpen(v.path)}>{v.label}</button>:v.label:typeof v==='string'&&v.startsWith('[[')?<button className="text-link" onClick={()=>onOpen(v.slice(2,-2).split('|')[0])}>{v.slice(2,-2)}</button>:String(v);
 if(error)return <div className="query-error">{error}<details><summary>查看查询</summary><pre>{query}</pre></details></div>;
 if(!data)return <div className="subtle">正在读取目录…</div>;
 if(data.kind==='list')return <ul><VirtualList items={data.rows as any[]} itemKey={row=>row.path} render={row=><li>{value(row.values['文件']||Object.values(row.values)[0])}</li>}/></ul>;
 return <div className="table-scroll"><table><thead><tr>{data.headers.map((h:string)=><th key={h}>{h}</th>)}</tr></thead><VirtualTableBody items={data.rows as any[]} columns={data.headers.length} itemKey={row=>row.path} render={(row,index)=><tr key={row.path} data-index={index}>{data.headers.map((h:string)=><td key={h}>{value(row.values[h])}</td>)}</tr>}/></table>{!data.rows.length&&<p className="subtle">暂无符合条件的笔记</p>}</div>;
}

function Embed({target,source,onOpen,depth}:{target:string,source:string,onOpen:OpenNote,depth:number}){
 const [path,setPath]=useState(''),[text,setText]=useState(''),[error,setError]=useState('');
 useEffect(()=>{const controller=new AbortController();let alive=true;api('resolve?target='+encodeURIComponent(target)+'&source='+encodeURIComponent(source),undefined,undefined,{signal:controller.signal}).then(async data=>{
  if(data.candidates.length!==1){if(alive)setError(data.candidates.length?'同名附件，请点击选择':'嵌入目标不存在');return;}const next=data.candidates[0];if(!alive)return;setPath(next);
  if(next.endsWith('.md')&&depth<2){const note=await api('file?path='+encodeURIComponent(next),undefined,undefined,{signal:controller.signal});if(!alive)return;let body=note.text;const anchor=target.split('#')[1];if(anchor){const lines=body.split('\n');if(anchor.startsWith('^')){const i=lines.findIndex((line:string)=>line.trim().endsWith(anchor));if(i>=0){let start=i;while(start>0&&lines[start-1].trim())start--;body=lines.slice(start,i+1).join('\n');}}else{const i=lines.findIndex((line:string)=>/^#{1,6} /.test(line)&&line.replace(/^#+ /,'').trim()===anchor);if(i>=0){const level=lines[i].match(/^#+/)![0].length;let end=i+1;while(end<lines.length&&!new RegExp('^#{1,'+level+'} ').test(lines[end]))end++;body=lines.slice(i,end).join('\n');}}}setText(body);}
 }).catch(e=>{if(alive&&e.name!=='AbortError')setError(e.message);});return()=>{alive=false;controller.abort();};},[target,source,depth]);
 if(error)return <button className="missing-link" onClick={()=>onOpen(target)}>{error} · {target}</button>;
 if(!path)return <span className="subtle">加载附件…</span>;
 if(/\.(png|jpe?g|webp|gif|avif|svg)$/i.test(path))return <img src={media(path)} alt={target} loading="lazy" decoding="async"/>;
 if(/\.(mp4|webm|mov|m4v)$/i.test(path))return <VideoPlayer path={path}/>;
 if(/\.(mp3|m4a|wav|ogg|flac)$/i.test(path))return <audio controls preload="metadata" src={media(path)}/>;
 if(path.endsWith('.base'))return <Suspense fallback={<p>正在打开视图…</p>}><BaseViewer path={path} onOpen={onOpen} notify={setError}/></Suspense>;
 if(path.endsWith('.md')&&text)return <div className="embedded-note"><button className="text-link" onClick={()=>onOpen(path)}>{path.split('/').pop()}</button><MarkdownPreview text={text} path={path} onOpen={onOpen} depth={depth+1}/></div>;
 return <button className="text-link" onClick={()=>onOpen(path)}>{target}</button>;
}

export const MarkdownPreview=memo(function MarkdownPreview({text,path,onOpen,onTask,depth=0,active=true}:{text:string,path:string,onOpen:OpenNote,onTask?:(index:number)=>void,depth?:number,active?:boolean}){
 const ref=useRef<HTMLDivElement>(null),roots=useRef<Map<HTMLElement,Root>>(new Map()),openRef=useRef(onOpen);openRef.current=onOpen;
 const [parts,setParts]=useState<Block[]>([]),[visible,setVisible]=useState(16),[error,setError]=useState('');
 const [jump,setJump]=useState<{block:number,value:ReadingJump}>();
 useEffect(()=>{const area=ref.current?.closest('.writing-area');if(!area)return;const reveal=(event:Event)=>{const detail=(event as CustomEvent).detail;const index=parts.findIndex(part=>part.from<=detail.pos&&part.to>detail.pos);if(index<0)return;const part=parts[index],needle=detail.needle||'',before=text.slice(part.from,detail.pos);setVisible(value=>Math.max(value,index+1));setJump({block:index,value:{nonce:performance.now(),needle,label:detail.label,occurrence:needle?before.toLocaleLowerCase().split(needle.toLocaleLowerCase()).length-1:0}});};area.addEventListener('vault-reading-jump',reveal);return()=>area.removeEventListener('vault-reading-jump',reveal);},[parts,text]);
 useEffect(()=>{if(!active)return;const changed=(event:Event)=>{const change=(event as CustomEvent<Change>).detail;ref.current?.querySelectorAll<HTMLImageElement|HTMLMediaElement>('img,video,audio').forEach(element=>{const url=new URL(element.src,location.origin),target=url.searchParams.get('path');if(url.origin===location.origin&&url.pathname==='/api/media'&&target&&affected('file?path='+encodeURIComponent(target),change)){const seconds=element instanceof HTMLMediaElement?element.currentTime:0;element.src=media(target);if(element instanceof HTMLMediaElement)element.addEventListener('loadedmetadata',()=>{element.currentTime=Math.min(seconds,element.duration||0);},{once:true});}});};window.addEventListener('vault-data-changed',changed);return()=>window.removeEventListener('vault-data-changed',changed);},[active]);
 useEffect(()=>{
  let alive=true,worker:Worker|undefined;setError('');setParts([]);setVisible(16);
  const ready=(value:Block[])=>{let task=0;for(const part of value)if(part.kind==='html')part.html=part.html.replace(/<input\b(?=[^>]*type="checkbox")/g,()=>'<input data-task="'+task+++'"');if(alive)setParts(value);};
  if(text.length*2>256*1024){worker=new Worker(new URL('./markdown.worker.ts',import.meta.url),{type:'module'});worker.onmessage=event=>{if(!alive)return;if(event.data.error)setError(event.data.error);else ready(event.data.blocks);};worker.onerror=()=>{if(alive)setError('文档解析失败，请重试或查看源码');};if(hasMath(text))void import('./math');worker.postMessage({text});}
  else{void(async()=>{const md=createMarkdown();if(hasMath(text)){const plugin=await import('./math');md.use(plugin.default,{throwOnError:false});}ready(blocks(md,text));})().catch(e=>{if(alive)setError(String(e));});}
  return()=>{alive=false;worker?.terminate();};
 },[text]);
 useEffect(()=>{if(visible>=parts.length)return;const timer=setTimeout(()=>setVisible(value=>Math.min(parts.length,value+16)),16);return()=>clearTimeout(timer);},[parts,visible]);
 useEffect(()=>{
  const el=ref.current;if(!el)return;let alive=true;const controller=new AbortController();
  const observer=new IntersectionObserver(entries=>{for(const entry of entries){if(!entry.isIntersecting)continue;const node=entry.target as HTMLElement;observer.unobserve(node);
   if(node.matches('pre.mermaid')){const diagram=node.dataset.diagram||node.textContent||'';if(node.dataset.rendered===diagram||node.classList.contains('rendered'))continue;void diagrams().then(async module=>{if(!alive)return;const svg=await module.default.render('m'+Math.random().toString(36).slice(2),diagram);if(alive){node.dataset.rendered=diagram;node.innerHTML=DOMPurify.sanitize(svg.svg,{USE_PROFILES:{svg:true,svgFilters:true}});node.classList.add('rendered');}}).catch(e=>{if(alive)node.textContent='图表无法渲染：'+String(e);});}
   else if(node.matches('img[data-vault-src]')){const image=node as HTMLImageElement,target=image.dataset.vaultSrc||'';if(/^https?:/.test(target)){image.src=target;continue;}void api('resolve?target='+encodeURIComponent(target)+'&source='+encodeURIComponent(path),undefined,undefined,{signal:controller.signal}).then(data=>{if(alive&&data.candidates.length===1)image.src=media(data.candidates[0]);}).catch(()=>{});}
   else if(node.dataset.embed&&!roots.current.has(node)){const root=createRoot(node);roots.current.set(node,root);root.render(<Embed target={node.dataset.embed} source={path} onOpen={(target,anchor)=>openRef.current(target,anchor)} depth={depth}/>);}
  }},{rootMargin:'500px'});
  for(const [element,root] of roots.current)if(!el.contains(element)){roots.current.delete(element);queueMicrotask(()=>root.unmount());}
  el.querySelectorAll('pre.mermaid,img[data-vault-src],[data-embed]').forEach(node=>observer.observe(node));
  el.querySelectorAll<HTMLInputElement>('input[type=checkbox]').forEach(input=>{input.disabled=!onTask;});
  el.dispatchEvent(new CustomEvent('vault-document-rendered',{bubbles:true}));
  return()=>{alive=false;observer.disconnect();controller.abort();};
 },[parts,visible,path,depth,onTask]);
 useEffect(()=>()=>{const old=[...roots.current.values()];roots.current.clear();queueMicrotask(()=>old.forEach(root=>root.unmount()));},[]);
 if(error)return <p className="error">{error}</p>;
 return <div ref={ref} className="markdown" onClick={event=>{const input=event.target as HTMLInputElement;if(input.type==='checkbox'&&input.dataset.task!==undefined){onTask?.(Number(input.dataset.task));return;}const anchor=(event.target as HTMLElement).closest<HTMLAnchorElement>('a');if(!anchor)return;const target=anchor.dataset.note||anchor.getAttribute('href')||'';if(!target||/^https?:|^mailto:/.test(target)){anchor.target='_blank';anchor.rel='noopener';return;}event.preventDefault();onOpen(target);}}>{parts.slice(0,visible).map((part,index)=>part.kind==='query'?<QueryView key={index} query={part.query} onOpen={onOpen}/>:<HtmlBlock key={index} html={part.html} editable={!!onTask} jump={jump?.block===index?jump.value:undefined}/>)}{visible<parts.length&&<p className="subtle">正在加载后续内容…</p>}</div>;
});
