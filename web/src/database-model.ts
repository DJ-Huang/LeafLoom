import {useCallback,useEffect,useRef,useState} from 'react';
import {api,Change} from './api';
import {documentState,applyProperties,hasDocumentDraft} from './document-state';
export type Field={type:string,displayName:string,options?:string[],optionMeta?:Record<string,{label?:string,labelKey?:string,color?:string}>,readonly?:boolean};
export type Row={path:string,title:string,metadata:Record<string,any>,file:Record<string,any>,revision:string,recent?:boolean,pendingIndex?:boolean};
type Recent={row:Row,scope:string,version:number,confirmed:boolean};
export type View={id:string,name:string,type:string,order?:string[],sort?:{property:string,direction:string}[],groupBy?:{property:string,direction?:string},leafloom?:Record<string,any>,supported:boolean};
export type BaseConfig={path:string,root:string,revision:string,workspace_revision:string,fields:Record<string,Field>,views:View[],folder?:string,config:any,tasks?:TaskSetup,suggested_tasks:TaskSetup&{newFields:string[]}};
export type TaskSetup={statusField:string,priorityField:string,dueField:string,initialStatus:string,completedStatuses:string[]};
export type BoardGroup={key:string,value:string|null,count:number,configured:boolean,label?:string,labelKey?:string,color?:string};
export type BoardSummary={groups:BoardGroup[],catalog_version:number|string,config_revision:string,total:number,needs_group:boolean};
export const valueOf=(row:Row,key:string)=>key==='title'?row.title:key.startsWith('file.')?row.file[key.slice(5)]:row.metadata[key.replace(/^note\./,'')];
export const labelOf=(key:string,field?:Field)=>field?.displayName&&field.displayName!==key?field.displayName:({title:'db.title',category:'db.category',attachments:'db.attachments',cover:'db.cover',start_date:'db.start',end_date:'db.end','file.ctime':'db.created','file.mtime':'db.modified'}[key]||key);
export function useDatabase(path:string,initialView:string){
 const [config,setConfig]=useState<BaseConfig>(),[viewId,setViewId]=useState(initialView),[rows,setRows]=useState<Row[]>([]),[total,setTotal]=useState(0),[cursor,setCursor]=useState(''),[search,setSearch]=useState(''),[readError,setReadError]=useState(''),[writeError,setWriteError]=useState(''),[busy,setBusy]=useState(false),[epoch,setEpoch]=useState(0);
 const error=writeError||readError;
 const [configEpoch,setConfigEpoch]=useState(0);
 const [boardSummary,setBoardSummary]=useState<BoardSummary>();
 const [recent,setRecent]=useState<Recent[]>([]),recentRef=useRef<Recent[]>([]);
 const changeRecent=(change:(old:Recent[])=>Recent[])=>{const next=change(recentRef.current);if(next!==recentRef.current){recentRef.current=next;setRecent(next);}};
 const creations=useRef(new Map<string,string>());
 const queryScope=useRef('');
 const life=useRef(0),locked=useRef(false),configRef=useRef(config);configRef.current=config;
 useEffect(()=>{let alive=true;const controller=new AbortController();void api<BaseConfig>('bases/config?path='+encodeURIComponent(path),undefined,'GET',{signal:controller.signal,force:true}).then(c=>{if(alive){configRef.current=c;setConfig(c);setReadError('');setEpoch(x=>x+1);}}).catch(e=>{if(alive&&e.name!=='AbortError')setReadError(e.message);});return()=>{alive=false;controller.abort();};},[path,configEpoch]);
 useEffect(()=>{let frame=0,configuration=false,records=false;const schedule=()=>{
  if(frame)return;frame=requestAnimationFrame(()=>{frame=0;if(configuration)setConfigEpoch(x=>x+1);else if(records)setEpoch(x=>x+1);configuration=false;records=false;});
 };const reload=(event:Event)=>{
  const change=(event as CustomEvent<Change>).detail||{reset:true},c=configRef.current;if(change.root&&c&&change.root!==c.root)return;
  const paths=change.paths||[],reset=change.reset||change.type==='reset'||change.type==='config'||!paths.length;
  if(reset||!c||paths.some(p=>p===path||path.startsWith(p+'/'))){configuration=true;schedule();return;}
  const folder=c.folder||'';if(!folder||paths.some(p=>p===folder||p.startsWith(folder+'/')||folder.startsWith(p+'/'))){records=true;schedule();}
 };window.addEventListener('vault-data-changed',reload);return()=>{cancelAnimationFrame(frame);window.removeEventListener('vault-data-changed',reload);};},[path]);
 const view=config?.views.find(v=>v.id===viewId)||(!viewId?config?.views[0]:undefined);
 useEffect(()=>{if(config?.path===path&&!viewId&&config.views.length)setViewId(config.views[0].id);},[config,viewId,path]);
 const scope=JSON.stringify([config?.root,path,view?.id,search]),activeScope=useRef(scope);activeScope.current=scope;
 useEffect(()=>{changeRecent(old=>old.some(r=>r.scope!==scope)?old.filter(r=>r.scope===scope):old);},[scope]);
 const confirmRecent=(records:Row[])=>changeRecent(old=>{const next=old.filter(r=>!records.some(row=>row.path===r.row.path&&row.revision===r.row.revision));return next.length===old.length?old:next;});
 const load=useCallback(async(next='')=>{
  if(!config||!view?.supported)return;
  const generation=life.current;
  try{const recent_paths=recentRef.current.filter(r=>r.scope===scope).map(r=>r.row.path);const page=await api<any>('bases/query',{path,view_id:view.id,search,cursor:next,...(recent_paths.length?{recent_paths}:{})});if(generation!==life.current)return;if(page.workspace_revision!==config.workspace_revision){setRows([]);setBoardSummary(undefined);setConfigEpoch(x=>x+1);return;}setRows(old=>next?[...old,...page.results.filter((row:Row)=>!old.some(r=>r.path===row.path))]:page.results);setTotal(page.total);setCursor(page.next_cursor||'');setBoardSummary(view.type==='leafloomBoard'?page:undefined);setReadError('');
   changeRecent(old=>{const found=new Map<string,Row>((page.recent_records||[]).map((r:Row)=>[r.path,r]));return old.flatMap(r=>{if(r.scope!==scope)return [r];if(page.results.some((row:Row)=>row.path===r.row.path&&row.revision===r.row.revision))return [];const row=found.get(r.row.path);if(row&&(row.revision===r.row.revision||Number(page.catalog_version)>r.version))return [{...r,row,confirmed:true,version:Number(page.catalog_version)}];return page.recent_records&&Number(page.catalog_version)>r.version?[]:[r];});});}
  catch(e){if(generation===life.current){setReadError((e as Error).message);if(next){setCursor('');setEpoch(x=>x+1);}}}
 },[config?.revision,view?.id,search,epoch]);
 const issuedSearch=useRef(search);
 useEffect(()=>{life.current++;const scope=JSON.stringify([path,view?.id,search]);if(queryScope.current!==scope){queryScope.current=scope;setRows([]);}setCursor('');const timer=setTimeout(()=>{issuedSearch.current=search;void load();},issuedSearch.current===search?0:150);return()=>{clearTimeout(timer);life.current++;};},[load]);
 const command=async(cmd:Record<string,any>)=>{
  const c=configRef.current;if(!c||c.path!==path||locked.current)throw new Error('db.busy');
  const record=cmd.path&&documentState(c.root,cmd.path);
  if(record&&(record.dirty||record.pending)&&!cmd.order_only)throw new Error('db.draftConflict');
  if(cmd.type==='board.group.remove'&&!cmd.dry_run&&cmd.records?.some((r:{path:string})=>hasDocumentDraft(c.root,r.path)))throw new Error('db.draftConflict');
  locked.current=true;setBusy(true);
  const creationScope=activeScope.current;
  const signature=JSON.stringify(cmd),creating=['record.create','record.duplicate','record.move','board.undo'].includes(cmd.type)||cmd.type==='board.group.remove'&&!cmd.dry_run;
  if(creating&&!creations.current.has(signature))creations.current.set(signature,crypto.randomUUID());
  try{const result=await api<any>('bases/commands',{path,command:Object.fromEntries(Object.entries({...cmd,...(['record.create','record.duplicate'].includes(cmd.type)?{return_record:true}:{})}).filter(([k])=>!['config_revision','order_only'].includes(k))),workspace_revision:c.workspace_revision,expected_revision:cmd.config_revision||c.revision,operation_id:creating?creations.current.get(signature):crypto.randomUUID()});
   setWriteError('');if(result.note){const state=documentState(c.root,result.note.path);if(state&&!state.dirty&&!state.pending)applyProperties(state,result.note);}
   if(creating)creations.current.delete(signature);
   if(result.dry_run||result.changed===false)return result;
   const sameScope=()=>configRef.current?.root===c.root&&configRef.current?.path===c.path;
   if(sameScope()&&creationScope===activeScope.current&&result.record&&result.visible!==false){changeRecent(old=>[{row:result.record,scope:creationScope,version:Number(result.catalog_version),confirmed:false},...old.filter(r=>r.row.path!==result.record.path)].slice(0,20));setEpoch(x=>x+1);}
   if(sameScope()&&cmd.type==='record.trash')changeRecent(old=>old.filter(r=>r.row.path!==cmd.path));
   if(sameScope()&&cmd.type==='board.group.remove')changeRecent(old=>old.filter(r=>!cmd.records.some((record:{path:string})=>record.path===r.row.path)));
   if(sameScope()&&result.note){const fresh=(row:Row):Row=>({...row,title:String(result.note.metadata.name||result.note.metadata.title||row.title),metadata:result.note.metadata,revision:result.note.etag,file:{...row.file,mtime:result.note.mtime,modified:result.note.mtime}});setRows(old=>old.map(row=>row.path===result.note.path?fresh(row):row));changeRecent(old=>old.map(r=>r.row.path===result.note.path?{...r,row:fresh(r.row),version:Number(result.catalog_version??r.version),confirmed:false}:r));}
   if(sameScope()&&cmd.type==='record.trash')setRows(old=>old.filter(row=>row.path!==cmd.path));
   if(!String(cmd.type).startsWith('record.')||cmd.type==='record.move'){
    try{const fresh=await api<BaseConfig>('bases/config?path='+encodeURIComponent(path),undefined,'GET',{force:true});
     if(sameScope()){configRef.current=fresh;setConfig(fresh);}
    }catch(e){setReadError((e as Error).message);setConfigEpoch(x=>x+1);}
   }return result;
  }
  finally{locked.current=false;setBusy(false);}
 };
 const recentRows=recent.filter(r=>r.scope===scope).map(r=>({...r.row,recent:true,pendingIndex:!r.confirmed}));
 const displayRows=[...recentRows,...rows.filter(row=>!recentRows.some(r=>r.path===row.path))];
 return {config,view,boardSummary,recentRows,confirmRecent,viewId,setViewId,rows:displayRows,total:Math.max(total,displayRows.length),cursor,search,setSearch,error,setError:setWriteError,busy,command,load,reload:()=>{setWriteError('');setConfigEpoch(x=>x+1);}};
}
