import {Diagnostic} from './i18n';
import {t,useLocale} from './i18n';
import React,{forwardRef,useEffect,useImperativeHandle,useMemo,useRef,useState} from 'react';
import cytoscape,{Core,CollectionReturnValue,NodeSingular} from 'cytoscape';
import {ArrowUpRight,ChevronLeft,Focus,Network,Plus,Minus,Search,SlidersHorizontal,X,RotateCcw,FileText,ChevronRight} from 'lucide-react';
import {OpenNote} from './api';
import {useApi,useStatus} from './hooks';
import {StatusNotice} from './settings-ui';
import {Action} from './ui';
import {GraphData,GraphIndex,graphIndex,graphSlice,groupOf} from './graph-model';
const displayGroup=(name:string)=>name==='根目录'?t('根目录'):name;
import './graph.css';
import {graphWebGLAvailable} from './graph-renderer';

const empty:GraphData={nodes:[],links:[]};
type Camera={fit:()=>void,zoom:(factor:number)=>void};
export function GraphPage({path,onOpen,active}:{path:string,onOpen:OpenNote,active:boolean}){
 useLocale();const status=useStatus();
 const {data,error,refresh}=useApi('graph',[],active),index=useMemo(()=>graphIndex(data||empty),[data]);
 const [center,setCenter]=useState(''),[depth,setDepth]=useState(1),[group,setGroup]=useState(''),[orphans,setOrphans]=useState(false);
 const [selected,setSelected]=useState(''),[query,setQuery]=useState(''),[searching,setSearching]=useState(false),[cursor,setCursor]=useState(0);
 const [filters,setFilters]=useState(false),[labels,setLabels]=useState(false),[arrows,setArrows]=useState(false),[revision,setRevision]=useState(0),[zoom,setZoom]=useState(1);
 const camera=useRef<Camera>(null),searchRef=useRef<HTMLInputElement>(null);
 const slice=useMemo(()=>graphSlice(index,{center,depth,group,orphans}),[index,center,depth,group,orphans]);
 const selectedNode=index.nodes.get(selected),centerNode=index.nodes.get(center);
 const groups=useMemo(()=>{const counts=new Map<string,number>();for(const node of index.nodes.values()){const key=groupOf(node.id);counts.set(key,(counts.get(key)||0)+1);}return [...counts].sort((a,b)=>b[1]-a[1]);},[index]);
 const ranked=useMemo(()=>[...index.nodes.values()].sort((a,b)=>index.neighbors.get(b.id)!.size-index.neighbors.get(a.id)!.size||a.label.localeCompare(b.label)),[index]);
 const matches=useMemo(()=>{const words=query.trim().toLocaleLowerCase().split(/\s+/);return ranked.filter(node=>words.every(word=>(node.label+' '+node.id).toLocaleLowerCase().includes(word))).slice(0,30);},[ranked,query]);
 const neighbors=useMemo(()=>selectedNode?[...index.neighbors.get(selected)!].map(id=>index.nodes.get(id)!).sort((a,b)=>a.label.localeCompare(b.label)):[],[index,selectedNode,selected]);
 const orphanCount=useMemo(()=>[...index.neighbors.values()].filter(neighbors=>!neighbors.size).length,[index]);
 useEffect(()=>{if(selected&&!index.nodes.has(selected))setSelected('');if(center&&!index.nodes.has(center))setCenter('');},[index,selected,center]);
 useEffect(()=>{if(searching)document.getElementById('graph-result-'+cursor)?.scrollIntoView({block:'nearest'});},[cursor,searching]);
 const select=(id:string)=>{setSelected(id);setSearching(false);setQuery('');};
 const find=(id:string)=>{if(!slice.nodes.some(node=>node.id===id)){setCenter('');setGroup('');setOrphans(true);}select(id);};
 const reset=()=>{setCenter('');setGroup('');setOrphans(false);setSelected('');setQuery('');setDepth(1);};
 return <section className="graph-page" hidden={!active} aria-label={t("关系图谱")}>
  <header className="graph-page-header"><div><div className="graph-eyebrow"><Network size={15}/>{t("探索与连接")}</div><h1>{t("关系图谱")}</h1><p>{t("沿着一条连接，发现下一个想法。")}</p></div><div className="graph-scope" aria-label={t("图谱范围")}><button aria-pressed={!center} onClick={()=>{setCenter('');setSelected('');}}>{t("全部笔记")}</button><button disabled={!path.toLowerCase().endsWith('.md')} aria-pressed={center===path&&!!path} onClick={()=>{setCenter(path);setGroup('');setSelected(path);}}>{t("当前笔记")}</button></div></header>
  {error?<StatusNotice kind="error">{<Diagnostic message={error}/>}<button onClick={()=>void refresh()}>{t("重试")}</button></StatusNotice>:!data?<StatusNotice kind="busy">{t("正在读取笔记关系…")}</StatusNotice>:<>
   <div className="graph-toolbar">
    <div className="graph-search" onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget))setSearching(false);}}>
     <Search size={16}/><input ref={searchRef} aria-label={t("搜索图谱笔记")} placeholder={t("搜索笔记，定位连接…")} value={query} role="combobox" aria-expanded={searching} aria-controls="graph-search-results" aria-autocomplete="list" aria-activedescendant={searching&&matches[cursor]?'graph-result-'+cursor:undefined} onFocus={()=>setSearching(true)} onChange={event=>{setQuery(event.target.value);setCursor(0);setSearching(true);}} onKeyDown={event=>{
      if(event.key==='Escape'){event.preventDefault();setSearching(false);searchRef.current?.blur();}
      if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();setSearching(true);setCursor(value=>Math.max(0,Math.min(matches.length-1,value+(event.key==='ArrowDown'?1:-1))));}
      if(event.key==='Enter'&&matches[cursor]){event.preventDefault();find(matches[cursor].id);searchRef.current?.blur();}
     }}/>{query&&<Action title={t("清除图谱搜索")} onClick={()=>{setQuery('');setCursor(0);searchRef.current?.focus();}}><X size={14}/></Action>}
     {searching&&<div id="graph-search-results" role="listbox" className="graph-search-results"><small>{query?t("匹配的笔记"):t("从连接最多的笔记开始")}</small>{matches.length?matches.map((node,i)=><button key={node.id} id={'graph-result-'+i} role="option" aria-selected={i===cursor} onMouseDown={event=>event.preventDefault()} onClick={()=>find(node.id)}><i style={{background:index.colors.get(groupOf(node.id))}}/><span><strong>{node.label}</strong><small>{node.id}</small></span><em>{index.neighbors.get(node.id)!.size}</em></button>):<p>{t("没有匹配的笔记，试试标题或路径。")}</p>}</div>}
    </div>
    <button className={'graph-filter-toggle'+(filters?' active':'')} aria-expanded={filters} aria-controls="graph-filters" onClick={()=>setFilters(!filters)}><SlidersHorizontal size={15}/>{t("显示与筛选")}</button>
   </div>
   {filters&&<div id="graph-filters" className="graph-filters"><label>{t("目录")}<select aria-label={t("筛选图谱目录")} value={group} onChange={event=>{setGroup(event.target.value);setSelected('');}}><option value="">{t("全部目录")}</option>{groups.map(([name,count])=><option key={name} value={name}>{displayGroup(name)} · {count}</option>)}</select></label><label><input type="checkbox" checked={orphans} onChange={event=>setOrphans(event.target.checked)}/>{t("显示独立笔记")}{" "}<span>{orphanCount}</span></label><label><input type="checkbox" checked={labels} onChange={event=>setLabels(event.target.checked)}/>{t("全部名称")}</label><label><input type="checkbox" checked={arrows} onChange={event=>setArrows(event.target.checked)}/>{t("连接方向")}</label></div>}
   {center&&<div className="graph-focus-bar"><button onClick={reset}><ChevronLeft size={14}/>{t("返回全图")}</button><span title={center}>{t("围绕「")}{centerNode?.label||center}{t("」探索")}</span><label>{t("连接层级")}<select aria-label={t("连接层级")} value={depth} onChange={event=>setDepth(Number(event.target.value))}>{[1,2,3].map(value=><option key={value} value={value}>{value} {" "}{t("层")}</option>)}</select></label></div>}
   <div className={'graph-workspace'+(selectedNode?' with-inspector':'')}>
    <div className="graph-stage">
     <div className="graph-summary"><strong>{slice.nodes.length.toLocaleString()}</strong> / {index.nodes.size.toLocaleString()} {" "}{t("篇笔记")}<span>·</span>{slice.links.length.toLocaleString()} {" "}{t("条连接")}{group&&<button onClick={()=>setGroup('')}>{displayGroup(group)}<X size={12}/></button>}</div>
     {slice.nodes.length?<GraphCanvas ref={camera} data={slice} index={index} selected={selected} onSelect={select} labels={labels} arrows={arrows} revision={revision} active={active} onZoom={setZoom}/>:<div className="graph-empty"><Network size={36} strokeWidth={1.2}/><h2>{index.nodes.size?t("这个范围还没有连接"):t("从第一篇笔记开始")}</h2><p>{index.nodes.size?t("切换目录，或显示尚未链接到其他内容的独立笔记。"):t("在 Markdown 中使用 [[笔记名称]] 建立连接。")}</p>{index.nodes.size>0&&<button onClick={()=>{setGroup('');setCenter('');setOrphans(true);}}>{t("显示全部笔记")}</button>}</div>}
     <div className="graph-camera"><Action title={t("放大图谱")} onClick={()=>camera.current?.zoom(1.3)}><Plus size={17}/></Action><span aria-label={t("图谱缩放比例")}>{Math.round(zoom*100)}%</span><Action title={t("缩小图谱")} onClick={()=>camera.current?.zoom(1/1.3)}><Minus size={17}/></Action><hr/><Action title={t("适应画布")} onClick={()=>camera.current?.fit()}><Focus size={17}/></Action><Action title={t("重新布局")} onClick={()=>setRevision(value=>value+1)}><RotateCcw size={15}/></Action></div>
     <div className="graph-gesture-hint">{t("拖动画布移动 · 滚轮或双指缩放 · 单击查看关联")}</div>
    </div>
    {selectedNode&&<aside className="graph-inspector" aria-label={t("笔记关联详情")}><header><span>{t("笔记与连接")}</span><Action title={t("关闭笔记详情")} onClick={()=>setSelected('')}><X size={16}/></Action></header><div className="graph-note-icon" style={{color:index.colors.get(groupOf(selected))}}><FileText size={25} strokeWidth={1.4}/></div><h2>{selectedNode.label}</h2><p className="graph-note-path">{selected}</p><div className="graph-note-actions"><button className="primary" onClick={()=>onOpen(selected)}>{t("打开笔记")}<ArrowUpRight size={14}/></button><button onClick={()=>{setCenter(selected);setGroup('');}}>{t("探索连接")}<Network size={14}/></button></div><div className="graph-neighbor-heading">{t("相连笔记")}<span>{neighbors.length}</span></div><div className="graph-neighbors">{neighbors.length?neighbors.map(node=><button key={node.id} onClick={()=>find(node.id)} title={node.id}><i style={{background:index.colors.get(groupOf(node.id))}}/><span>{node.label}</span><ChevronRight size={13}/></button>):<p>{t("这篇笔记还没有双链连接。")}</p>}</div></aside>}
   </div>
   <footer className="graph-legend"><span>{t("按目录着色")}</span>{groups.slice(0,7).map(([name,count])=><button key={name} aria-pressed={group===name} title={name+' · '+count+t(" 篇")} onClick={()=>{setGroup(group===name?'':name);setSelected('');}}><i style={{background:index.colors.get(name)}}/>{displayGroup(name)}</button>)}{groups.length>7&&<button onClick={()=>setFilters(true)}>{t("另")}{" "}{groups.length-7} {" "}{t("个目录")}</button>}<small>{t("节点越大，连接越多")}</small></footer>
  </>}
 </section>;
}

const GraphCanvas=forwardRef<Camera,{data:GraphData,index:GraphIndex,selected:string,onSelect:(id:string)=>void,labels:boolean,arrows:boolean,revision:number,active:boolean,onZoom:(zoom:number)=>void}>(function GraphCanvas({data,index,selected,onSelect,labels,arrows,revision,active,onZoom},ref){
 const container=useRef<HTMLDivElement>(null),cyRef=useRef<Core|null>(null),latest=useRef({selected,onSelect,labels,arrows,onZoom});latest.current={selected,onSelect,labels,arrows,onZoom};
 const [gpu]=useState(graphWebGLAvailable),[rendererError,setRendererError]=useState('');
 const savedView=useRef<{data:GraphData,revision:number,positions:{id:string,x:number,y:number}[],zoom:number,pan:{x:number,y:number}}|undefined>(undefined);
 const highlighted=useRef<{cy:Core,id:string,members:CollectionReturnValue}|null>(null);
 const [completed,setCompleted]=useState<GraphData>(),[busy,setBusy]=useState(true),[failed,setFailed]=useState(false),[retry,setRetry]=useState(0);
 const fit=()=>{const cy=cyRef.current;if(!cy||!cy.nodes().length)return;cy.stop();cy.fit(cy.elements(),50);if(cy.zoom()>1.5){cy.zoom(1.5);cy.center();}};
 const zoomBy=(factor:number)=>{const cy=cyRef.current;if(cy){cy.stop();cy.zoom({level:cy.zoom()*factor,renderedPosition:{x:cy.width()/2,y:cy.height()/2}});}};
 useImperativeHandle(ref,()=>({fit,zoom:zoomBy}));
 const highlight=(id:string)=>{
  const cy=cyRef.current;if(!cy)return;
  const node=cy.getElementById(id),nextId=node.length?id:'',previous=highlighted.current?.cy===cy?highlighted.current:null;
  if((previous?.id||'')===nextId)return;
  const members=node.length?node.closedNeighborhood():cy.collection();
  cy.batch(()=>{
   if(!previous?.id&&nextId){cy.elements().addClass('faded');members.removeClass('faded').addClass('neighbor');}
   else if(previous?.id&&nextId){previous.members.difference(members).removeClass('neighbor').addClass('faded');members.difference(previous.members).removeClass('faded').addClass('neighbor');}
   else cy.elements().removeClass('faded neighbor');
   if(previous?.id)cy.getElementById(previous.id).removeClass('spotlight');
   if(nextId)node.addClass('spotlight');
  });
  highlighted.current={cy,id:nextId,members};
 };
 const focus=(id:string)=>{const cy=cyRef.current,node=cy?.getElementById(id);if(!cy||!node?.length)return;
  const neighborhood=node.closedNeighborhood(),box=neighborhood.boundingBox(),padding=60,z=Math.min(1.6,Math.max(.4,Math.min((cy.width()-padding*2)/Math.max(box.w,1),(cy.height()-padding*2)/Math.max(box.h,1))));
  cy.stop();cy.animate({zoom:z,pan:{x:cy.width()/2-(box.x1+box.w/2)*z,y:cy.height()/2-(box.y1+box.h/2)*z}},{duration:window.matchMedia('(prefers-reduced-motion: reduce)').matches?0:220});
 };
 useEffect(()=>{
  if(!container.current)return;setBusy(true);setFailed(false);setRendererError('');
  const hubs=new Set([...data.nodes].sort((a,b)=>index.neighbors.get(b.id)!.size-index.neighbors.get(a.id)!.size).slice(0,8).map(node=>node.id));
  let cy:Core;
  try{cy=cytoscape({container:container.current,webgl:gpu,elements:[],minZoom:.06,maxZoom:3.5,wheelSensitivity:.22,boxSelectionEnabled:false,autounselectify:true,textureOnViewport:!gpu&&data.nodes.length>400,style:[
   {selector:'node',style:{'background-color':'data(color)',width:'data(size)',height:'data(size)',label:'data(label)','font-size':11,'font-family':'-apple-system, BlinkMacSystemFont, sans-serif',color:'#656763','text-valign':'bottom','text-margin-y':6,'text-background-color':'#fafbf9','text-background-opacity':.85,'text-background-padding':'2px','text-max-width':'140px','text-wrap':'ellipsis','overlay-opacity':0,'border-width':1.5,'border-color':'#fff'}},
   {selector:'edge',style:{width:1,'line-color':'#aeb9ba',opacity:.3,'curve-style':'haystack','target-arrow-color':'#94a3a5','arrow-scale':.7}},
   {selector:'node',style:{'text-opacity':0}},
   {selector:'node.label-visible',style:{'text-opacity':1}},
   {selector:'node.faded',style:{opacity:.16,'text-opacity':0}},
   {selector:'edge.faded',style:{opacity:.04}},
   {selector:'edge.neighbor',style:{'line-color':'#778ca8',opacity:.8,width:1.7,'z-index':5}},
   {selector:'node.neighbor',style:{'z-index':10}},
   {selector:'node.spotlight',style:{'border-color':'#526f94','border-width':3,'background-color':'#526f94',color:'#283e57','font-weight':600,'text-opacity':1,'z-index':20}}
  ]});}catch{
   // Cytoscape associates the core before allocating its renderer. Dispose a partial init too.
   const partial=(container.current as HTMLDivElement&{_cyreg?:{cy?:Core}})._cyreg?.cy;
   partial?.destroy();setBusy(false);setRendererError(t("图谱绘制未能启动，请重新尝试或刷新页面。"));return;
  }
  cyRef.current=cy;
  const gpuCanvas=container.current.querySelector<HTMLCanvasElement>('canvas[data-id$="-webgl"]');
  let settle:ReturnType<typeof setTimeout>|undefined,hover:ReturnType<typeof setTimeout>|undefined,alive=true,moving=false,dragging=false;
  let ordered:{node:NodeSingular,width:number}[]=[],styledZoom:number|undefined,styledArrows:boolean|undefined;
  const display=()=>{if(!alive)return;const z=cy.zoom(),zoomChanged=z!==styledZoom;latest.current.onZoom(z);cy.batch(()=>{
   const occupied:{x:number,y:number,w:number,h:number}[]=[];
   const selectedEntry=ordered.find(entry=>entry.node.id()===latest.current.selected);
   const entries=selectedEntry?[selectedEntry,...ordered.filter(entry=>entry!==selectedEntry)]:ordered;
   for(const {node,width:w} of entries){
    const size=Math.max(node.data('size'),(3+Math.min(7,Math.sqrt(node.data('degree'))*.65))/z),position=node.renderedPosition();
    const box={x:position.x-w/2,y:position.y+size*z/2+5,w,h:16};
    const candidate=node.id()===latest.current.selected||z>.7||hubs.has(node.id())&&node.data('degree')>1;
    const inViewport=box.x+box.w>0&&box.x<cy.width()&&box.y+box.h>0&&box.y<cy.height();
    const visible=inViewport&&(latest.current.labels||candidate&&occupied.length<120&&!occupied.some(other=>box.x<other.x+other.w+8&&box.x+box.w+8>other.x&&box.y<other.y+other.h+4&&box.y+box.h+4>other.y));
    if(visible)occupied.push(box);
    if(node.hasClass('label-visible')!==visible)node.toggleClass('label-visible',visible);if(zoomChanged)node.style({width:size,height:size,'font-size':11/z,'text-margin-y':5/z,'text-max-width':140/z});
   }
   if(zoomChanged||styledArrows!==latest.current.arrows)cy.edges().style({width:Math.max(1,.65/z),'target-arrow-shape':latest.current.arrows?'triangle':'none','curve-style':latest.current.arrows?'straight':'haystack'});
  });styledZoom=z;styledArrows=latest.current.arrows;};
  // Keep the gesture path free of graph-wide style work and React updates.
  const schedule=()=>{if(!moving){moving=true;clearTimeout(hover);highlight(latest.current.selected);}clearTimeout(settle);settle=setTimeout(()=>{moving=false;display();},120);};
  cy.on('zoom pan',schedule);
  cy.on('grab',()=>{dragging=true;clearTimeout(hover);});cy.on('free',()=>{dragging=false;schedule();});cy.on('tap','node',event=>latest.current.onSelect(event.target.id()));cy.on('tap',event=>{if(event.target===cy)latest.current.onSelect('');});
  cy.on('mouseover','node',event=>{if(moving||dragging)return;clearTimeout(hover);const id=event.target.id();hover=setTimeout(()=>{if(alive&&!moving&&!dragging)highlight(id);},50);if(container.current)container.current.style.cursor='pointer';});cy.on('mouseout','node',()=>{clearTimeout(hover);if(!moving&&!dragging)hover=setTimeout(()=>{if(alive&&!moving&&!dragging)highlight(latest.current.selected);},50);if(container.current)container.current.style.cursor='grab';});
  const worker=new Worker(new URL('./graph-layout.worker.ts',import.meta.url),{type:'module'});
  const restore=savedView.current?.data===data&&savedView.current.revision===revision?savedView.current:undefined;
  const populate=(points:{id:string,x:number,y:number}[])=>{if(!alive)return;const positions=new Map(points.map(node=>[node.id,node]));cy.add([
   ...data.nodes.map(node=>({data:{id:node.id,label:node.label,color:index.colors.get(groupOf(node.id)),size:10+Math.min(18,Math.sqrt(index.neighbors.get(node.id)!.size)*2.5),degree:index.neighbors.get(node.id)!.size},position:positions.get(node.id)})),
   ...data.links.map((link,i)=>({data:{id:'edge:'+i,source:link.source,target:link.target}}))
  ]);ordered=cy.nodes().toArray().sort((a,b)=>b.data('degree')-a.data('degree')).map(node=>({node,width:Math.min(140,[...String(node.data('label'))].reduce((sum,char)=>sum+(char.charCodeAt(0)>255?11:6),0))}));cy.resize();
  if(restore){cy.zoom(restore.zoom);cy.pan(restore.pan);}else fit();
  clearTimeout(settle);moving=false;display();highlight(latest.current.selected);setCompleted(data);setBusy(false);if(latest.current.selected&&!restore)focus(latest.current.selected);worker.terminate();};
  worker.onmessage=(event:MessageEvent<{id:string,x:number,y:number}[]>)=>populate(event.data);
  worker.onerror=()=>{if(alive){setBusy(false);setFailed(true);}worker.terminate();};
  const lost=(event:Event)=>{event.preventDefault();alive=false;clearTimeout(settle);clearTimeout(hover);worker.terminate();cy.stop();cyRef.current=null;
   if(cy.nodes().length)savedView.current={data,revision,positions:cy.nodes().map(node=>({id:node.id(),...node.position()})),zoom:cy.zoom(),pan:{...cy.pan()}};
   setBusy(false);setRendererError(t("图形加速连接中断。重新连接后可继续浏览原来的位置。"));
  };
  gpuCanvas?.addEventListener('webglcontextlost',lost);
  if(restore)populate(restore.positions);else worker.postMessage(data);
  // Cytoscape may resize before our observer; retain the previous measured viewport.
  let viewport={width:container.current.clientWidth,height:container.current.clientHeight};
  const observer=new ResizeObserver(()=>{const element=container.current;if(!element?.clientWidth||!element.clientHeight)return;
   const next={width:element.clientWidth,height:element.clientHeight},focusing=cy.animated();cy.stop();cy.resize();
   cy.panBy({x:(next.width-viewport.width)/2,y:(next.height-viewport.height)/2});viewport=next;
   if(focusing&&latest.current.selected)focus(latest.current.selected);
  });observer.observe(container.current);
  return()=>{alive=false;clearTimeout(settle);clearTimeout(hover);highlighted.current=null;observer.disconnect();worker.terminate();gpuCanvas?.removeEventListener('webglcontextlost',lost);cy.destroy();gpuCanvas?.getContext('webgl2')?.getExtension('WEBGL_lose_context')?.loseContext();cyRef.current=null;};
 },[data,index,revision,retry]);
 useEffect(()=>{cyRef.current?.stop();highlight(selected);if(selected){cyRef.current?.resize();focus(selected);}},[selected]);
 useEffect(()=>{const cy=cyRef.current;if(cy)cy.emit('zoom');},[labels,arrows]);
 useEffect(()=>{if(active){cyRef.current?.resize();}},[active]);
 return <><div className="graph" ref={container} tabIndex={0} role="region" aria-label={t("笔记关系图。方向键平移，加减号缩放，0 适应画布；可用搜索选择笔记。")} data-renderer={gpu?'webgl2':'canvas'} aria-busy={!failed&&!rendererError&&(busy||completed!==data)} onKeyDown={event=>{
  const cy=cyRef.current;if(!cy||event.target!==event.currentTarget)return;cy.stop();
  if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','0','Escape'].includes(event.key)){event.preventDefault();if(event.key==='0')fit();else if(event.key==='Escape')latest.current.onSelect('');else if(['+','=','-'].includes(event.key))zoomBy(event.key==='-'?1/1.3:1.3);else cy.panBy({x:event.key==='ArrowLeft'?50:event.key==='ArrowRight'?-50:0,y:event.key==='ArrowUp'?50:event.key==='ArrowDown'?-50:0});}
 }}/>{(busy||completed!==data)&&!failed&&!rendererError&&<div className="graph-loading"><StatusNotice kind="busy">{t("正在展开笔记之间的连接…")}</StatusNotice></div>}{failed&&<div className="graph-loading"><StatusNotice kind="error">{t("图谱布局未能完成。")}<button onClick={()=>setRetry(value=>value+1)}>{t("重新尝试")}</button></StatusNotice></div>}{rendererError&&<div className="graph-loading"><StatusNotice kind="error">{rendererError}<button onClick={()=>setRetry(value=>value+1)}>{t("重新连接")}</button></StatusNotice></div>}<span className="graph-renderer-badge" title={gpu?t("WebGL 2 绘制；是否使用硬件加速由浏览器决定。"):t("浏览器未提供 WebGL 2，使用兼容绘制。")}>{rendererError?t("绘制已暂停"):gpu?t("WebGL 加速"):t("兼容绘制")}</span></>;
});
