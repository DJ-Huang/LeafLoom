import {useCallback,useEffect,useId,useRef,useState} from 'react';
import {api,media} from './api';
import {Diagnostic,t,useLocale} from './i18n';
import {Modal} from './ui';
import './attachments.css';

type Attachment={path:string,name:string,size:number,mtime:number,mime:string};
type Page={items:Attachment[],next_cursor:string|null,total:number};
type Request={query:string,after:string};
function ModifiedTime({seconds,locale}:{seconds:number,locale:string}){
 const date=new Date(seconds*1000);
 return Number.isNaN(date.getTime())?<span>—</span>:<time dateTime={date.toISOString()}>{date.toLocaleString(locale)}</time>;
}
export function Attachments(props:{onClose:()=>void,root:string,onChanged?:()=>void}){
 return <AttachmentBrowser key={props.root} {...props}/>;
}
function AttachmentBrowser({onClose,root,onChanged}:{onClose:()=>void,root:string,onChanged?:()=>void}){
 const locale=useLocale(),label=useId();
 const [query,setQuery]=useState(''),[page,setPage]=useState<Page>(),[busy,setBusy]=useState(false),[error,setError]=useState(''),[cancelled,setCancelled]=useState(false);
 const [indexReady,setIndexReady]=useState(false),[indexRevision,setIndexRevision]=useState(0);
 const migrationChanged=useCallback((state:string)=>{
  setIndexRevision(value=>value+1);
  if(['completed','rolled_back'].includes(state))onChanged?.();
 },[onChanged]);
 const active=useRef<AbortController|undefined>(undefined),generation=useRef(0),last=useRef<Request>({query:'',after:''});
 const load=useCallback(async(request:Request)=>{
  if(active.current&&JSON.stringify(last.current)===JSON.stringify(request))return;
  active.current?.abort();const controller=new AbortController();active.current=controller;const id=++generation.current;last.current=request;
  setBusy(true);setPage(undefined);setError('');setCancelled(false);
  try{
   if(controller.signal.aborted)return;
   const params=new URLSearchParams({root,query:request.query,after:request.after,limit:'100'});
   const result=await api<Page>('attachments?'+params,undefined,'GET',{signal:controller.signal,force:true});
   if(id===generation.current&&!controller.signal.aborted)setPage(result);
  }catch(reason){if(id===generation.current&&!controller.signal.aborted)setError((reason as Error).message);}
  finally{if(id===generation.current){active.current=undefined;setBusy(false);}}
 },[root]);
 useEffect(()=>()=>{generation.current++;active.current?.abort();},[]);
 const indexChanged=useCallback((usable:boolean)=>{
  setIndexReady(usable);
  if(usable)void load({query:last.current.query,after:''});
  else{generation.current++;active.current?.abort();active.current=undefined;setPage(undefined);setBusy(false);}
 },[load]);
 const cancel=()=>{generation.current++;active.current?.abort();active.current=undefined;setBusy(false);setCancelled(true);};
 const navigate=(request:Request)=>{if(!active.current)void load(request);};
 return <Modal title={t('attachments.title')} onClose={onClose} wide className="attachments-modal">
  <div className="pad">
   <p className="hint">{t('attachments.description')}</p>
   <AttachmentDatabase root={root} revision={indexRevision} onReady={indexChanged}/>
   <AttachmentMigration root={root} onChanged={migrationChanged}/>
   {indexReady&&<>
   <form className="attachments-search" onSubmit={event=>{event.preventDefault();void load({query:query.trim(),after:''});}}>
    <label htmlFor={label}>{t('attachments.searchLabel')}</label>
    <div><input id={label} type="search" value={query} onChange={event=>setQuery(event.target.value)} autoFocus/><button type="submit">{t('attachments.search')}</button></div>
   </form>
   <div aria-live="polite" role="status">{busy?t('attachments.loading'):cancelled?t('attachments.cancelled'):page?t('attachments.count',{count:page.total}):null}</div>
   {busy&&<button onClick={cancel}>{t('取消')}</button>}
   {error&&<p className="error" role="alert"><Diagnostic message={error}/></p>}
   {(error||cancelled)&&<button onClick={()=>navigate(last.current)}>{t('attachments.retry')}</button>}
   {page&&<>
    {page.items.length===0?<p>{t('attachments.empty')}</p>:<ul className="attachments-list" aria-label={t('attachments.title')}>
     {page.items.map(item=><li key={item.path}><div><strong>{item.name}</strong><small>{item.path}</small><small>{item.size.toLocaleString(locale)} {t('attachments.bytes')} · {item.mime} · <ModifiedTime seconds={item.mtime} locale={locale}/></small></div><a href={media(item.path,true)} download aria-label={t('attachments.download',{name:item.name})}>{t('下载原文件')}</a></li>)}
    </ul>}
    <div className="attachments-pagination"><button disabled={!last.current.after||busy} onClick={()=>navigate({query:last.current.query,after:''})}>{t('attachments.first')}</button><button disabled={!page.next_cursor||busy} onClick={()=>navigate({query:last.current.query,after:page.next_cursor!})}>{t('attachments.next')}</button><span className="hint">{t('attachments.pageHint')}</span></div>
   </>}
   </>}
  </div>
 </Modal>;
}

type IndexStatus={state:'uninitialized'|'ready'|'needs_upgrade'|'unsupported'|'building'|'failed'|'cancelled'|'interrupted',schema_version:number|null,current_version:number,usable:boolean,files?:number,last_scanned_at?:number,error?:string,progress?:{done:number},job_id?:string};
function AttachmentDatabase({root,revision,onReady}:{root:string,revision:number,onReady:(usable:boolean)=>void}){
 const [status,setStatus]=useState<IndexStatus>(),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const lifetime=useRef<AbortController|undefined>(undefined),timer=useRef<number|undefined>(undefined),sequence=useRef(0),listed=useRef('');
 const refresh=useCallback(async()=>{
  const controller=lifetime.current;if(!controller||controller.signal.aborted)return;
  const serial=++sequence.current;
  window.clearTimeout(timer.current);
  try{
   const result=await api<IndexStatus>('attachments/status?'+new URLSearchParams({root}),undefined,'GET',{signal:controller.signal,force:true});
   if(serial!==sequence.current||controller.signal.aborted)return;
   setStatus(result);setError('');
   const usable=result.usable&&result.state!=='building'&&result.state!=='unsupported';
   const marker=JSON.stringify([usable,result.job_id,result.last_scanned_at]);
   if(marker!==listed.current){listed.current=marker;onReady(usable);}
   if(result.state==='building')timer.current=window.setTimeout(()=>void refresh(),1200);
  }catch(reason){if(serial===sequence.current&&!controller.signal.aborted){setError((reason as Error).message);timer.current=window.setTimeout(()=>void refresh(),3000);}}
 },[root,onReady]);
 useEffect(()=>{
  const controller=new AbortController();lifetime.current=controller;void refresh();
  return()=>{sequence.current++;controller.abort();window.clearTimeout(timer.current);};
 },[refresh,revision]);
 const act=async(action:'initialize'|'rebuild'|'index-cancel')=>{
  const controller=lifetime.current;if(!controller||controller.signal.aborted||busy)return;
  sequence.current++;window.clearTimeout(timer.current);setBusy(true);setError('');
  if(action!=='index-cancel'){listed.current='';onReady(false);}
  try{
   await api('attachments/'+action,{root},'POST',{signal:controller.signal});
   if(!controller.signal.aborted)await refresh();
  }catch(reason){if(!controller.signal.aborted){setError((reason as Error).message);timer.current=window.setTimeout(()=>void refresh(),3000);}}
  finally{if(!controller.signal.aborted)setBusy(false);}
 };
 const building=status?.state==='building';
 return <section className="attachment-migration" aria-label={t('attachments.database')}>
  <h3>{t('attachments.database')}</h3>
  <p role="status" aria-live="polite">{status?t('attachments.indexState.'+status.state):t('attachments.checking')}{building&&status.progress?<> · {t('attachments.scanned',{count:status.progress.done})}</>:null}</p>
  {status?.schema_version!=null&&<p className="hint">{t('attachments.version',{version:status.schema_version,current:status.current_version})}</p>}
  {(error||status?.error)&&<p className="error" role="alert"><Diagnostic message={error||status!.error!}/></p>}
  {building?<button disabled={busy} onClick={()=>void act('index-cancel')}>{t('attachments.cancelBuild')}</button>:status?.state==='unsupported'?null:status&&<details className="attachment-advanced"><summary>{t('attachments.advanced')}</summary><p className="hint">{t('attachments.initializeSafety')}</p><button disabled={busy} onClick={()=>void act(status.state==='needs_upgrade'?'initialize':status.usable?'rebuild':'initialize')}>{t(status.state==='needs_upgrade'?'attachments.upgrade':status.usable?'attachments.refresh':['failed','cancelled','interrupted'].includes(status.state)?'attachments.retryInitialize':'attachments.initialize')}</button></details>}
  {error&&<button disabled={busy} onClick={()=>void refresh()}>{t('attachments.checkStatus')}</button>}
 </section>;
}

type Migration={
 id:string,root:string,destination:string,state:string,phase?:string,
 progress?:{done:number,total:number},summary?:{files:number,bytes:number,notes:number},
 moves?:{source:string,destination:string,size:number}[],blockers?:{path:string,reason:string}[],
 exclusions?:{path:string,reason:string}[],error?:string,
};
const migrationActive=(state:string)=>['planning','running','rolling_back'].includes(state);
function AttachmentMigration({root,onChanged}:{root:string,onChanged:(state:string)=>void}){
 const locale=useLocale(),destinationId=useId();
 const [destination,setDestination]=useState('_attachments'),[jobs,setJobs]=useState<Migration[]>([]),[job,setJob]=useState<Migration>();
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[acknowledged,setAcknowledged]=useState(false),[confirmation,setConfirmation]=useState<'rollback'|'resume'>();
 const lifetime=useRef<AbortController|undefined>(undefined),sequence=useRef(0);
 const changeMarker=useRef('');
 const accept=useCallback((value:Migration)=>{
  setJob(value);setJobs(current=>[value,...current.filter(item=>item.id!==value.id)]);
  const marker=JSON.stringify([value.id,value.state,value.phase]);
  if(marker!==changeMarker.current){changeMarker.current=marker;onChanged(value.state);}
 },[onChanged]);
 const refresh=useCallback(async(id?:string)=>{
  const controller=lifetime.current;if(!controller||controller.signal.aborted)return;
  const serial=++sequence.current;
  try{
   if(id){const result=await api<Migration>('attachments/migrations/'+encodeURIComponent(id),undefined,'GET',{signal:controller.signal,force:true});if(serial===sequence.current&&!controller.signal.aborted)accept(result);}
   else{const result=await api<{jobs:Migration[]}>('attachments/migrations',undefined,'GET',{signal:controller.signal,force:true});if(serial!==sequence.current||controller.signal.aborted)return;const scoped=result.jobs.filter(item=>item.root===root);setJobs(scoped);if(scoped.length){const detail=await api<Migration>('attachments/migrations/'+encodeURIComponent(scoped[0].id),undefined,'GET',{signal:controller.signal,force:true});if(serial===sequence.current&&!controller.signal.aborted)accept(detail);}}
   if(serial===sequence.current&&!controller.signal.aborted)setError('');
  }catch(reason){if(serial===sequence.current&&!controller.signal.aborted)setError((reason as Error).message);}
 },[root,accept]);
 useEffect(()=>{
  const controller=new AbortController();lifetime.current=controller;
  setJob(undefined);setJobs([]);setAcknowledged(false);setConfirmation(undefined);setError('');setBusy(false);
  void refresh();return()=>{sequence.current++;controller.abort();};
 },[refresh]);
 useEffect(()=>{
  if(!job||!migrationActive(job.state)||busy)return;
  let alive=true,timer:number;
  const tick=async()=>{await refresh(job.id);if(alive)timer=window.setTimeout(tick,1200);};
  timer=window.setTimeout(tick,1200);return()=>{alive=false;window.clearTimeout(timer);};
 },[job,busy,refresh,error]);
 const act=async(action:'preview'|'execute'|'cancel'|'rollback'|'resume')=>{
  const controller=lifetime.current;if(!controller||controller.signal.aborted||busy)return;
  const serial=++sequence.current;setBusy(true);setError('');setConfirmation(undefined);
  try{
   const path='attachments/migrations'+(action==='preview'?'':'/'+encodeURIComponent(job!.id)+'/'+action);
   const result=await api<Migration>(path,action==='preview'?{root,destination:destination.trim()}:{root,...(action==='cancel'?{}:{confirm:true})},'POST',{signal:controller.signal});
   if(serial!==sequence.current||controller.signal.aborted)return;
   setAcknowledged(false);accept(result);
   const detail=await api<Migration>('attachments/migrations/'+encodeURIComponent(result.id||job!.id),undefined,'GET',{signal:controller.signal,force:true});
   if(serial===sequence.current&&!controller.signal.aborted)accept(detail);
  }catch(reason){if(serial===sequence.current&&!controller.signal.aborted)setError((reason as Error).message);}
  finally{if(serial===sequence.current&&!controller.signal.aborted)setBusy(false);}
 };
 const active=job&&migrationActive(job.state),blocked=!!job?.blockers?.length;
 return <section className="attachment-migration" aria-labelledby={destinationId+'-heading'}>
  <h3 id={destinationId+'-heading'}>{t('migration.title')}</h3>
  <p>{t('migration.intro')}</p>
  <p className="hint">{t('migration.safety')}</p>
  <p className="hint">{t('migration.htmlExcluded')}</p>
  <form className="attachments-search" onSubmit={event=>{event.preventDefault();void act('preview');}}>
   <label htmlFor={destinationId}>{t('migration.destination')}</label><div><input id={destinationId} value={destination} disabled={busy||!!active} onChange={event=>setDestination(event.target.value)}/><button className="primary" disabled={busy||!!active||!destination.trim()}>{t('migration.preview')}</button></div>
  </form>
  {!!jobs.length&&<label className="migration-job-picker">{t('migration.history')}<select value={job?.id||''} disabled={busy} onChange={event=>{setAcknowledged(false);setConfirmation(undefined);void refresh(event.target.value);}}>{jobs.map(item=><option key={item.id} value={item.id}>{item.id} · {t('migration.state.'+item.state)}</option>)}</select></label>}
  {error&&<p className="error" role="alert"><Diagnostic message={error}/></p>}
  <button type="button" disabled={busy} onClick={()=>void refresh(job?.id)}>{t('migration.reload')}</button>
  {job&&<div className="migration-plan">
   <p role="status" aria-live="polite">{t('migration.state.'+job.state)}{job.phase&&<> · <Diagnostic message={job.phase}/></>}{job.progress&&<> · {job.progress.done.toLocaleString(locale)} / {job.progress.total.toLocaleString(locale)}</>}</p>
   {active&&job.progress&&<progress aria-label={t('migration.progress')} value={job.progress.done} max={Math.max(1,job.progress.total)}/>}
   <p><strong>{t('migration.destination')}:</strong> {job.destination}</p>
   {job.summary&&<p>{t('migration.summary',{files:job.summary.files,bytes:job.summary.bytes,notes:job.summary.notes})}</p>}
   {job.error&&<p className="error" role="alert"><Diagnostic message={job.error}/></p>}
   {blocked&&<div className="migration-warning" role="alert"><strong>{t('migration.blockers')}</strong><ul>{job.blockers!.map((item,index)=><li key={index}><code>{item.path}</code>: <Diagnostic message={item.reason}/></li>)}</ul></div>}
   {!!job.exclusions?.length&&<details><summary>{t('migration.exclusions',{count:job.exclusions.length})}</summary><ul>{job.exclusions.map((item,index)=><li key={index}>{item.path}: <Diagnostic message={item.reason}/></li>)}</ul></details>}
   {!!job.moves?.length&&<details open={job.state==='ready'}><summary>{t('migration.moves',{shown:job.moves.length,total:job.summary?.files??job.moves.length})}</summary><ol className="migration-moves">{job.moves.map((item,index)=><li key={index}><span>{item.source}</span><span>→ {item.destination}</span><small>{item.size.toLocaleString(locale)} {t('attachments.bytes')}</small></li>)}</ol></details>}
   {job.state==='ready'&&<><p className="migration-warning">{t('migration.executeWarning')}</p><label className="migration-ack"><input type="checkbox" checked={acknowledged} disabled={busy||blocked} onChange={event=>setAcknowledged(event.target.checked)}/>{t('migration.acknowledge')}</label><button className="primary" disabled={busy||blocked||!acknowledged} onClick={()=>void act('execute')}>{t('migration.execute')}</button></>}
   {['planning','ready','running'].includes(job.state)&&<button disabled={busy} onClick={()=>void act('cancel')}>{t('migration.cancel')}</button>}
   {['completed','failed','interrupted','cancelled','conflict'].includes(job.state)&&<button disabled={busy} onClick={()=>setConfirmation('rollback')}>{t('migration.rollback')}</button>}
   {['interrupted','failed','cancelled'].includes(job.state)&&<button disabled={busy} onClick={()=>setConfirmation('resume')}>{t('migration.resume')}</button>}
   {confirmation&&<div className="migration-warning" role="alert"><p>{t('migration.confirm.'+confirmation)}</p><button disabled={busy} onClick={()=>void act(confirmation)}>{t('migration.confirmAction')}</button><button disabled={busy} onClick={()=>setConfirmation(undefined)}>{t('取消')}</button></div>}
   <p className="hint">{t('migration.recovery')}</p>
  </div>}
 </section>;
}
