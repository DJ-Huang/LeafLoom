/* Capture authored DOM in a project copy. No requests ever write to the source. */
(()=>{
 'use strict';
 const params=new URLSearchParams(location.search),session=params.get('session'),parentOrigin=params.get('parentOrigin');
 if(!session||!parentOrigin||parent===window)return;
 const frame=document.querySelector('#source');
 const send=(type,payload={})=>parent.postMessage({type,session,...payload},parentOrigin);
 let running=false;
 const rendererSources=new Map();
 const resource=(value,base)=>{
  if(!value||/^(?:data:|blob:|#)/.test(value))return value;
  try{const url=new URL(value,base);return url.origin===location.origin?'__STUDIO_ASSET__/'+url.pathname.replace(/^\//,'')+url.search+url.hash:url.href;}catch{return value;}
 };
 const urls=(css,base)=>String(css).replace(/url\(\s*(['"]?)(.*?)\1\s*\)/g,(_m,_q,value)=>'url("'+resource(value,base).replaceAll('"','%22')+'")');
 function capturePage(board){
  const source=frame.contentDocument,base=frame.contentWindow.location.href;
  const root=source.querySelector('#artboard')||source.body;
  const sourceId=board.contextSource?.pageId||board.id;
  const definition=Array.isArray(frame.contentWindow.boards)?frame.contentWindow.boards.find(item=>item.id===sourceId):null;
  const kind=definition?.kind||board.kind||'';
  const sourceContext=new URL(base).searchParams.get('source')||(kind==='help'?'pause':'home');
  const interactions={navigation:0,switches:0,inlineHandlers:0,scriptSources:[...source.scripts].map(script=>script.src?resource(script.src,base):'inline')};
  const css=[];
  for(const sheet of source.styleSheets){try{css.push(urls([...sheet.cssRules].map(rule=>rule.cssText).join('\n'),sheet.href||base));}catch{/* Keep inaccessible external stylesheet reference. */if(sheet.href)css.push('@import url("'+sheet.href+'");');}}
  function node(element){
   if(element.nodeType===3){if(!element.textContent)return null;return {id:crypto.randomUUID(),type:'text',name:'Text',props:{authored:true,tag:'span',text:element.textContent,attributes:{style:'display:contents'}},style:{},children:[]};}
   if(element.nodeType!==1||['SCRIPT','STYLE','LINK','NOSCRIPT','META'].includes(element.tagName))return null;
   const attrs={};
   for(const attribute of element.attributes){
    if(/^on/i.test(attribute.name)){interactions.inlineHandlers+=1;continue;}
    if(attribute.name.startsWith('data-gdl'))continue;
    attrs[attribute.name]=attribute.name==='style'?urls(attribute.value,base):['src','href','xlink:href','poster'].includes(attribute.name)?resource(attribute.value,base):attribute.value;
   }
   const tag=element.localName;
   const result={id:crypto.randomUUID(),type:tag==='img'?'image':tag==='button'?'button':tag==='svg'?'svg':element.children.length?'element':'text',name:element.getAttribute('data-layer-name')||element.getAttribute('aria-label')||element.getAttribute('alt')||element.id||tag,props:{authored:true,tag,attributes:attrs},style:{},children:[]};
   if(tag==='svg'){
    // Rewrite DOM attribute values before serializing. Rewriting raw markup
    // would inject url("...") quotes into a quoted SVG attribute and invalidate
    // the entire board, including its paths, clips and gradient definitions.
    const copy=element.cloneNode(true);
    for(const child of copy.querySelectorAll('*'))for(const attribute of [...child.attributes]){
     if(/^on/i.test(attribute.name)){interactions.inlineHandlers+=1;child.removeAttribute(attribute.name);}
     else if(['href','xlink:href','src'].includes(attribute.name))child.setAttribute(attribute.name,resource(attribute.value,base));
     else if(/url\(/i.test(attribute.value))child.setAttribute(attribute.name,urls(attribute.value,base));
    }
    for(const style of copy.querySelectorAll('style'))style.textContent=urls(style.textContent,base);
    result.props.html=copy.innerHTML;
   }else if(tag==='img')result.props.src=resource(element.getAttribute('src'),base);
   else if(!element.children.length)result.props.text=element.textContent;
   else result.children=[...element.childNodes].map(node).filter(Boolean);
   const target=element.getAttribute('data-target');
   if(target){
    interactions.navigation+=1;
    const resolved=typeof frame.contentWindow.resolveBoardId==='function'?frame.contentWindow.resolveBoardId(target):target;
    result.props.action={type:'navigate',pageId:resolved,contextDefaults:{settingsFrom:sourceContext}};
    if(element.getAttribute('data-source'))result.props.action.context={settingsFrom:element.getAttribute('data-source')};
    // The CozyPaws renderer selects these two destinations from the incoming
    // source context. Retain that declarative choice instead of its snapshot.
    if(kind==='settings'&&['home','game','pause'].includes(target)&&element.closest('.settings-modal'))result.props.action.contextTarget='settingsFrom';
   }
   if(element.matches('button.toggle[role="switch"][aria-checked]')){
    interactions.switches+=1;
    result.script={source:'export function mount(ctx) { ctx.on("click", () => { const on = ctx.el.getAttribute("aria-checked") !== "true"; ctx.el.classList.toggle("on", on); ctx.el.setAttribute("aria-checked", String(on)); }); }'};
   }
   return result;
  }
  const result=node(root);
  // The review adapter may split native text while loading; capture the normal
  // prototype DOM instead, preserving artboard hierarchy and classes.
  const warnings=[];
  if(interactions.inlineHandlers)warnings.push(interactions.inlineHandlers+' inline event attributes were omitted; port custom behavior with mount(ctx).');
  if(interactions.scriptSources.length)warnings.push('Original script files are retained in the copied source; arbitrary event listeners, closures and runtime state are not replayed. Declarative page links and recognized switch controls were adapted.');
  const migration={source:'Design/UI/Site/screen.html?id='+encodeURIComponent(sourceId)+(board.contextSource?'&source='+encodeURIComponent(sourceContext):''),interactions,warnings};
  if(board.contextSource)migration.contextSource=board.contextSource;
  if(kind==='settings'&&root.querySelector('.settings-modal')||kind==='help'&&root.querySelector('.help-modal'))migration.contextDefaults={settingsFrom:sourceContext};
  return {id:board.id,name:board.name,group:board.group||'',width:board.width||720,height:board.height||1560,css:css.join('\n'),nodes:result?[result]:[],migration};
 }
 async function convert(data){
  if(running)return;running=true;
  try{
   const pages=[],queue=data.boards.map(board=>({...board}));
   for(const board of queue){
    send('studio-capture-progress',{name:board.name});
    frame.style.width=(board.width||720)+'px';frame.style.height=(board.height||1560)+'px';
    const target=new URL('/'+String(data.entry).replace(/^\//,''),location.origin);target.searchParams.set('id',board.contextSource?.pageId||board.id);
    if(board.contextSource)target.searchParams.set('source',board.contextSource.context.settingsFrom);
    await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('Page capture timed out: '+board.name)),15000);frame.onload=()=>{clearTimeout(timer);resolve();};frame.src=target.href;});
    const source=frame.contentDocument;
    if(!source)throw new Error('Cannot read legacy artboard');
    await Promise.race([Promise.allSettled([source.fonts.ready,...[...source.images].map(image=>image.decode().catch(()=>{}))]),new Promise(resolve=>setTimeout(resolve,7000))]);
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    const artboard=source.querySelector('#artboard');
    const reported=frame.contentWindow.__studioCaptureErrors;
    if(Array.isArray(reported)&&reported.length)throw new Error('Page script failed: '+board.name+' — '+reported.join('; '));
    // A failed script often leaves the authored root present but completely
    // empty. Counting that root as a converted page would silently lose work.
    // An intentionally empty artboard can opt in explicitly in the source.
    let emptyReason='';
    if(artboard&&!artboard.childElementCount&&!artboard.textContent.trim()&&source.scripts.length&&!board.allowEmpty&&!artboard.hasAttribute('data-studio-allow-empty')){
     // Older projects could add a metadata-only page without adding its
     // renderer. Preserve that known empty page with a visible conversion
     // warning; a supported renderer returning nothing is a hard failure.
     const definition=Array.isArray(frame.contentWindow.boards)?frame.contentWindow.boards.find(value=>value.id===board.id):null;
     const legacy=[...source.scripts].find(script=>/\/artboards\.js(?:[?#]|$)/.test(script.src));
     if(definition?.kind&&legacy){
      if(!rendererSources.has(legacy.src))rendererSources.set(legacy.src,fetch(legacy.src).then(response=>response.ok?response.text():'').catch(()=>''));
      const code=await rendererSources.get(legacy.src),cases=[...code.matchAll(/\bcase\s+['"]([^'"]+)['"]\s*:/g)].map(match=>match[1]);
      if(cases.length>=2&&!cases.includes(definition.kind)&&!code.includes('CUSTOM_ARTBOARDS'))emptyReason='Legacy page has metadata but no renderer for kind: '+definition.kind;
     }
     if(!emptyReason)throw new Error('Page rendered no content: '+board.name+'. Check the original page scripts before converting. Intentionally empty pages may set data-studio-allow-empty.');
    }
    const captured=capturePage(board);
    if(!board.contextSource&&captured.migration.contextDefaults){
     const defaultSource=captured.migration.contextDefaults.settingsFrom;
     captured.migration.contextVariants=[];
     for(const settingsFrom of ['home','game','pause'])if(settingsFrom!==defaultSource){
      const pageId=board.id+'--from-'+settingsFrom,context={settingsFrom};
      if(queue.some(item=>item.id===pageId))throw new Error('Context page identity already exists: '+pageId);
      captured.migration.contextVariants.push({context,pageId});
      queue.push({...board,id:pageId,name:board.name+' · source='+settingsFrom,contextSource:{pageId:board.id,context}});
     }
    }
    if(emptyReason){captured.migration.emptySource=true;captured.migration.warnings.push(emptyReason);}
    pages.push(captured);
   }
   frame.src='about:blank';send('studio-capture-complete',{pages});
  }catch(error){send('studio-capture-error',{message:error.message});}finally{running=false;}
 }
 addEventListener('message',event=>{if(event.source===parent&&event.origin===parentOrigin&&event.data?.session===session&&event.data.type==='studio-capture-init'&&Array.isArray(event.data.boards))void convert(event.data);});
 send('studio-capture-ready');
})();
