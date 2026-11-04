import React,{useEffect,useRef,useState} from 'react';
import {Archive,Copy,FolderOpen,Heart,Image,MoreHorizontal,Plus,RotateCcw,Search,Trash2} from 'lucide-react';
import {api,media} from './api';
import {t,useLocale} from './i18n';
import {Modal} from './ui';
import type {DesignProjectSummary} from './design-studio';

type Relocation={source:string,destination:string};
type Workspace={revision:string,meta:Record<string,any>,history:{can_undo:boolean,can_redo:boolean},relocation?:Relocation};
type Session={id:string,origin:string,url:string};
export function designManagementError(error:unknown):string{
 const failure=error as {status?:number,message?:string};
 return failure?.status===404&&failure.message==='Not Found'
  ? t('当前后台尚未加载项目管理功能，请从托盘退出并重新启动应用；仅刷新页面无效。')
  : failure?.message||t('操作未完成');
}
type DesignStorage=Pick<Storage,'getItem'|'setItem'|'removeItem'|'key'|'length'>;
const queuePrefix='leafloom-design-queue:',sourcePrefix='leafloom-design-source:';

export function designQueueStatus(root:string,directory?:string,storage?:DesignStorage):'pending'|'corrupt'|null{
 try{
  const area=storage??globalThis.localStorage;
  const inspect=(key:string)=>{const raw=area.getItem(key);if(raw===null)return null;let value:unknown;try{value=JSON.parse(raw);}catch{return 'corrupt' as const;}if(!Array.isArray(value)||value.some(item=>!item||typeof item.id!=='string'||!item.id.trim()))return 'corrupt' as const;return value.length?'pending' as const:null;};
  if(directory!==undefined)return inspect(queuePrefix+JSON.stringify([root,directory]));
  let pending=false;
  for(let index=0;index<area.length;index++){
   const key=area.key(index);if(!key?.startsWith(queuePrefix))continue;
   let parts:unknown;try{parts=JSON.parse(key.slice(queuePrefix.length));}catch{if(key.startsWith(queuePrefix+'['+JSON.stringify(root)+','))return 'corrupt';continue;}
   if(!Array.isArray(parts)||parts[0]!==root)continue;
   if(parts.length!==2||typeof parts[1]!=='string')return 'corrupt';
   const state=inspect(key);if(state==='corrupt')return state;if(state==='pending')pending=true;
  }
  return pending?'pending':null;
 }catch{return 'corrupt';}
}

export function rekeyDesignSourceDrafts(root:string,oldDirectory:string,newDirectory:string,storage?:DesignStorage):{moved:number,retained:number,failed:boolean}{
 const result={moved:0,retained:0,failed:false};if(oldDirectory===newDirectory)return result;
 try{
  const area=storage??globalThis.localStorage,keys:string[]=[];
  for(let index=0;index<area.length;index++){const key=area.key(index);if(key?.startsWith(sourcePrefix))keys.push(key);}
  for(const key of keys){
   let parts:unknown;
   try{parts=JSON.parse(key.slice(sourcePrefix.length));}catch{if(key.startsWith(sourcePrefix+JSON.stringify([root,oldDirectory]).slice(0,-1)+',')){result.retained++;result.failed=true;}continue;}
   if(!Array.isArray(parts)||parts[0]!==root||parts[1]!==oldDirectory)continue;
   if(parts.length!==3||typeof parts[2]!=='string'){result.retained++;result.failed=true;continue;}
   try{
    const original=area.getItem(key);if(original===null)continue;
    const target=sourcePrefix+JSON.stringify([root,newDirectory,parts[2]]);
    if(area.getItem(target)!==null){result.retained++;continue;}
    area.setItem(target,original);
    if(area.getItem(target)!==original||area.getItem(key)!==original){result.retained++;result.failed=true;continue;}
    area.removeItem(key);
    if(area.getItem(key)!==null){result.retained++;result.failed=true;}else result.moved++;
   }catch{result.retained++;result.failed=true;}
  }
 }catch{result.failed=true;}
 return result;
}

export function rekeyDesignRelocation(root:string,relocation?:Relocation,storage?:DesignStorage){
 const visible=(directory:string)=>!!directory&&!directory.split(/[\\/]/).some(part=>part.startsWith('.'));
 if(!relocation||!visible(relocation.source)||!visible(relocation.destination))return{moved:0,retained:0,failed:false};
 return rekeyDesignSourceDrafts(root,relocation.source,relocation.destination,storage);
}

export function DesignProjects({root,projects,onOpen,onCreate,reload,notify}:{root:string,projects:DesignProjectSummary[],onOpen:(directory:string)=>void,onCreate:()=>void,reload:()=>Promise<void>,notify:(message:string)=>void}){
 useLocale();
 const [workspace,setWorkspace]=useState<Workspace>(),[filter,setFilter]=useState('recent'),[query,setQuery]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [dialog,setDialog]=useState<{action:string,project:DesignProjectSummary}>(),[value,setValue]=useState('');
 const [purgeDialog,setPurgeDialog]=useState<{root:string,revision:string,directories:string[]|null,names:string[],id:string}>();
 const [migration,setMigration]=useState<{directory:string,revision:string,session:Session,boards:any[],entry:string}>(),[progress,setProgress]=useState('');
 const capture=useRef<HTMLIFrameElement>(null),migrationRef=useRef(migration);migrationRef.current=migration;
 const refresh=async()=>{const next=await api<Workspace>('design/workspace',undefined,undefined,{force:true});setWorkspace(next);await reload();};
 useEffect(()=>{let alive=true;void api<Workspace>('design/workspace',undefined,undefined,{force:true}).then(v=>{if(alive){setWorkspace(v);setError('');}}).catch(e=>{if(alive){setWorkspace(undefined);setError(designManagementError(e));}});return()=>{alive=false;};},[root,projects]);
 const run=async(operation:()=>Promise<unknown>)=>{if(busy)return;setBusy(true);setError('');try{await operation();await refresh();}catch(e){setError(designManagementError(e));}finally{setBusy(false);}};
 const assertQueueClear=(project:DesignProjectSummary)=>{if(designQueueStatus(root,project.directory))throw new Error(t('项目有待保存或损坏的修改记录，请先打开项目处理后再移动、复制或删除'));};
 const relocateDrafts=(relocation?:Relocation)=>{const result=rekeyDesignRelocation(root,relocation);if(result.retained||result.failed)notify(t('项目已移动；部分源码草稿仍保留在原目录，请撤销移动后处理草稿'));};
 const manage=async(project:DesignProjectSummary,action:string,extra:Record<string,unknown>={})=>{if(!workspace)throw new Error(t('项目管理尚未就绪，请稍后重试'));if(action==='move'||action==='delete')assertQueueClear(project);await api('design/workspace',{root,directory:project.directory,action,expected_revision:workspace.revision,operation_id:crypto.randomUUID(),...extra});if(action==='move'&&typeof extra.destination==='string'){const destination=extra.destination.replace(/\\/g,'/').split('/').filter(part=>part&&part!=='.').join('/');relocateDrafts({source:project.directory,destination});}};
 const managementHistory=async(action:'undo'|'redo')=>{if(designQueueStatus(root))throw new Error(t('当前知识库有待保存或损坏的设计修改，请先打开对应项目处理后再撤销或重做项目管理操作'));const result=await api<Workspace>('design/workspace/history',{root,action,expected_revision:workspace?.revision});relocateDrafts(result.relocation);};
 const open=(project:DesignProjectSummary)=>{void manage(project,'open').catch(()=>{});onOpen(project.directory);};
 const showDialog=(action:string,project:DesignProjectSummary)=>{if(!workspace){setError(t('项目管理尚未就绪，请稍后重试'));return;}if((action==='move'||action==='copy')&&designQueueStatus(root,project.directory)){setError(t('项目有待保存或损坏的修改记录，请先打开项目处理后再移动、复制或删除'));return;}setDialog({action,project});setValue(action==='rename'?project.name:action==='cover'?(project.cover||''):project.directory+(action==='migrate'?'-Studio':'-Copy'));};
 useEffect(()=>{
  const listener=(event:MessageEvent)=>{
   const current=migrationRef.current;if(!current||event.source!==capture.current?.contentWindow||event.origin!==current.session.origin||event.data?.session!==current.session.id)return;
   if(event.data.type==='studio-capture-ready')capture.current?.contentWindow?.postMessage({type:'studio-capture-init',session:current.session.id,boards:current.boards,entry:current.entry},current.session.origin);
   if(event.data.type==='studio-capture-progress')setProgress(String(event.data.name||''));
   if(event.data.type==='studio-capture-error'){setError(String(event.data.message));setMigration(undefined);setBusy(false);}
   if(event.data.type==='studio-capture-complete'){
    void api('design/migrate/finish',{root,directory:current.directory,pages:event.data.pages,expected_revision:current.revision,operation_id:crypto.randomUUID()}).then(async()=>{await refresh();notify(t('转换完成，原项目保持完整'));onOpen(current.directory);}).catch(e=>setError(e.message)).finally(()=>{void api('html-sessions/'+current.session.id,undefined,'DELETE').catch(()=>{});setMigration(undefined);setBusy(false);});
   }
  };window.addEventListener('message',listener);return()=>window.removeEventListener('message',listener);
 },[root,workspace,projects]);
 const submit=async(event:React.FormEvent)=>{
  event.preventDefault();if(!dialog||busy)return;const {project,action}=dialog;
  if(action==='migrate'){
   setBusy(true);setError('');try{const response=await api<any>('design/migrate',{root,directory:project.directory,destination:value});setMigration({directory:value,revision:response.revision,session:response.session,boards:response.document.migration.boards,entry:response.document.migration.entry});setProgress(t('正在转换页面…'));setDialog(undefined);}catch(e){setError((e as Error).message);setBusy(false);}return;
  }
  await run(async()=>{if(action==='copy'){assertQueueClear(project);await api('design/copy',{root,directory:project.directory,destination:value});}else await manage(project,action,action==='move'?{destination:value}:{value});setDialog(undefined);});
 };
 const rows=filter==='trash'?Object.entries(workspace?.meta||{}).filter(([,v])=>v.deleted).map(([directory,v])=>({...v.project,...v,directory} as DesignProjectSummary)):
  projects.filter(p=>{const meta=workspace?.meta[p.directory]||{};return !meta.deleted&&(filter==='archive'?!!meta.archived:!meta.archived)&&(filter!=='favorites'||meta.favorite);});
 const visible=rows.filter(p=>(p.name+' '+p.directory).toLowerCase().includes(query.toLowerCase())).sort((a,b)=>Number(workspace?.meta[b.directory]?.openedAt||0)-Number(workspace?.meta[a.directory]?.openedAt||0));
 const managementDisabled=busy||!workspace;
 const openPurge=(project?:DesignProjectSummary)=>{if(!workspace||busy)return;const targets=project?[project]:rows;try{for(const target of targets)assertQueueClear(target);setError('');setPurgeDialog({root,revision:workspace.revision,directories:project?[project.directory]:null,names:targets.map(target=>workspace.meta[target.directory]?.name||target.name),id:crypto.randomUUID()});}catch(reason){setError(designManagementError(reason));}};
 const confirmPurge=()=>void run(async()=>{if(!purgeDialog)return;for(const directory of purgeDialog.directories??rows.map(project=>project.directory))assertQueueClear({directory} as DesignProjectSummary);await api('design/workspace/trash',{root:purgeDialog.root,expected_revision:purgeDialog.revision,operation_id:purgeDialog.id,directories:purgeDialog.directories,confirm:true});setPurgeDialog(undefined);notify(t('项目已永久删除'));});
 return <div className="design-project-home">
  <div className="design-home-heading"><div><h2>{t('设计项目')}</h2><p>{t('从素材到可交互的游戏画面，人工与 AI 一起设计。')}</p></div><button className="primary" disabled={managementDisabled} onClick={onCreate}><Plus size={16}/>{t('新建设计项目')}</button></div>
  <div className="design-home-filter"><div role="tablist">{[['recent','最近项目'],['favorites','收藏'],['archive','已归档'],['trash','回收站']].map(([id,label])=><button key={id} role="tab" aria-selected={filter===id} onClick={()=>setFilter(id)}>{t(label)}</button>)}</div><label><Search size={15}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder={t('搜索项目名称或目录')}/></label><button disabled={busy||!workspace?.history.can_undo} title={t('撤销项目管理操作')} onClick={()=>void run(()=>managementHistory('undo'))}><RotateCcw size={15}/>{t('撤销')}</button><button disabled={busy||!workspace?.history.can_redo} onClick={()=>void run(()=>managementHistory('redo'))}>{t('重做')}</button></div>
  {error&&<div className="error" role="alert"><p>{error}</p><button disabled={busy} onClick={()=>void run(async()=>{})}>{t('重试')}</button></div>}
  {!workspace&&!error&&<p role="status">{t('正在加载项目管理…')}</p>}
  {filter==='trash'&&<div className="design-home-heading"><p>{t('永久删除回收区内的全部文件和目录，无法恢复。')}</p><button className="danger" disabled={managementDisabled||!rows.length} onClick={()=>openPurge()}><Trash2 size={15}/>{t('清空项目回收站')}</button></div>}
  {migration&&<div role="status">{t('正在转换副本：')}{progress}<iframe ref={capture} title={t('转换项目副本')} className="design-capture-frame" src={migration.session.origin+'/Design/studio/capture.html?'+new URLSearchParams({session:migration.session.id,parentOrigin:location.origin})}/></div>}
  <div className="design-project-grid">{visible.map(project=>{const meta=workspace?.meta[project.directory]||{};return <article key={project.directory} className="design-project-card">
   <button className="design-project-cover" disabled={filter==='trash'||busy} onClick={()=>open(project)}>{(meta.cover||project.cover)?<img src={media(project.directory+'/'+(meta.cover||project.cover))} alt="" loading="lazy"/>:<span><FolderOpen size={38}/>{project.managed?t('可视化 HTML'):t('传统 HTML 项目')}</span>}</button>
   <div className="design-project-card-body"><button className="design-project-title" disabled={filter==='trash'||busy} onClick={()=>open(project)}>{meta.name||project.name}</button><small>{project.directory}</small><p>{t('{count} 个页面',{count:project.board_count})} · {t('{count} 项素材',{count:project.asset_count})}</p>
   {filter==='trash'?<div className="design-project-card-actions"><button disabled={managementDisabled} onClick={()=>void run(()=>manage(project,'restore'))}>{t('恢复项目')}</button><button className="danger" disabled={managementDisabled} onClick={()=>openPurge(project)}><Trash2 size={14}/>{t('永久删除项目')}</button></div>:<div className="design-project-card-actions"><button disabled={managementDisabled} aria-label={t('收藏')} aria-pressed={!!meta.favorite} onClick={()=>void run(()=>manage(project,'favorite',{value:!meta.favorite}))}><Heart size={15} fill={meta.favorite?'currentColor':'none'}/></button><button disabled={managementDisabled} title={t('复制项目')} onClick={()=>showDialog('copy',project)}><Copy size={15}/></button><button disabled={managementDisabled} title={t('设置项目封面')} onClick={()=>showDialog('cover',project)}><Image size={15}/></button><button disabled={managementDisabled} title={meta.archived?t('取消归档'):t('归档')} onClick={()=>void run(()=>manage(project,'archive',{value:!meta.archived}))}><Archive size={15}/></button><details onKeyDown={event=>{if(event.key==='Escape'){event.preventDefault();event.currentTarget.open=false;event.currentTarget.querySelector('summary')?.focus();}}}><summary aria-label={t('更多操作')}><MoreHorizontal size={16}/></summary><div onClick={event=>{if((event.target as Element).closest('button'))event.currentTarget.parentElement?.removeAttribute('open');}}><button disabled={managementDisabled} onClick={()=>showDialog('rename',project)}>{t('重命名')}</button><button disabled={managementDisabled} onClick={()=>showDialog('move',project)}>{t('移动项目')}</button>{!project.managed&&<button disabled={managementDisabled} onClick={()=>showDialog('migrate',project)}>{t('转换为可视化副本')}</button>}<button disabled={managementDisabled} onClick={()=>void run(()=>manage(project,'delete'))}><Trash2 size={14}/>{t('移到回收站')}</button></div></details></div>}
   {!project.managed&&filter!=='trash'&&<button className="dw-upload" disabled={managementDisabled} onClick={()=>showDialog('migrate',project)}>{t('转换为可视化副本')}</button>}
   </div></article>;})}</div>
  {!visible.length&&<div className="empty-state"><FolderOpen size={32}/><p>{t('这里还没有设计项目')}</p></div>}
  {purgeDialog&&<Modal className="design-management-modal" title={t(purgeDialog.directories?'永久删除项目':'清空项目回收站')} onClose={()=>{if(!busy)setPurgeDialog(undefined);}}><p>{t('永久删除以下 {count} 个项目？项目文件和设计历史将无法恢复，相关项目管理操作也将无法撤销。',{count:purgeDialog.names.length})}</p><ul>{purgeDialog.names.map((name,index)=><li key={index}>{name}</li>)}</ul>{error&&<p className="error" role="alert">{error}</p>}<div className="modal-actions"><button disabled={busy} onClick={()=>setPurgeDialog(undefined)}>{t('取消')}</button><button className="danger" disabled={busy} onClick={confirmPurge}>{busy?t('处理中…'):t(purgeDialog.directories?'永久删除项目':'永久清空')}</button></div></Modal>}
  {dialog&&<Modal className="design-management-modal" title={t(({rename:'重命名项目',move:'移动项目',copy:'复制项目',migrate:'转换为可视化副本',cover:'设置项目封面'} as Record<string,string>)[dialog.action])} onClose={()=>{if(!busy)setDialog(undefined);}}><form onSubmit={submit}><label>{t(dialog.action==='rename'?'项目名称':dialog.action==='cover'?'项目内图片路径':'新项目目录')}<input autoFocus value={value} onChange={e=>setValue(e.target.value)} required={dialog.action!=='cover'}/></label>{dialog.action==='migrate'&&<p>{t('原项目保持完整；在新目录转换页面、图层和素材。')}</p>}<div className="modal-actions"><button type="button" onClick={()=>setDialog(undefined)} disabled={busy}>{t('取消')}</button><button className="primary" disabled={busy}>{busy?t('处理中…'):t('保存')}</button></div></form></Modal>}
 </div>;
}
