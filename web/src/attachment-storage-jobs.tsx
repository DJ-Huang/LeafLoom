import {useCallback,useEffect,useRef,useState} from 'react';
import {api,invalidate} from './api';
import {Diagnostic,t,useLocale} from './i18n';
import {StatusNotice} from './settings-ui';

type Progress={done:number,total:number,bytes_done?:number,bytes_total?:number,speed_bps?:number,file_bytes_done?:number,file_bytes_total?:number,phase?:string};
type Job={id:string,job_id?:string,kind:string,state:string,storage_id?:string,items?:{path:string,size:number,state?:string}[],exclusions?:{path:string,reason:string}[],summary?:{files:number,bytes:number},progress?:Progress,error?:string};
type Activity=''|'preview'|'task'|'cancel';
type SpeedMark={t:number,b:number,speed:number};
const pending=(job:Job)=>['queued','waiting_for_connection','waiting_for_auth','waiting_for_authorization','running','uploading','verifying'].includes(job.state);
const parsePaths=(text:string)=>[...new Set(text.split(/\r?\n/).map(line=>line.trim()).filter(Boolean))];
const formatBytes=(value:number)=>{const units=['B','KiB','MiB','GiB'];let amount=Math.max(0,value),index=0;while(amount>=1024&&index<units.length-1){amount/=1024;index++;}return (index?amount.toFixed(1):String(Math.round(amount)))+' '+units[index];};
const formatSpeed=(bps:number)=>{const units=['B/s','KiB/s','MiB/s'];let amount=Math.max(0,bps),index=0;while(amount>=1024&&index<units.length-1){amount/=1024;index++;}return t('as.transferSpeed',{speed:(index?amount.toFixed(1):String(Math.round(amount)))+' '+units[index]});};
const jobKey=(job:Job)=>job.job_id||job.id;
export function AttachmentStorageJobs({root,storages,disabled}:{root:string,storages:{storage_id:string,name:string,enabled:boolean}[],disabled:boolean}){
 useLocale();
 const enabled=storages.filter(item=>item.enabled);
 const speedMarks=useRef(new Map<string,SpeedMark>());
 const [jobs,setJobs]=useState<Job[]>([]),[target,setTarget]=useState(''),[pathsText,setPathsText]=useState(''),[busy,setBusy]=useState(false),[activity,setActivity]=useState<Activity>(''),[elapsed,setElapsed]=useState(0),[error,setError]=useState(''),[openDetails,setOpenDetails]=useState<Record<string,boolean>>({}),[dismissed,setDismissed]=useState<Record<string,boolean>>({});
 const decorate=(values:Job[])=>{
  const now=Date.now(),active=new Set<string>();
  const next=values.map(job=>{
   const id=jobKey(job);active.add(id);
   if(!pending(job)||!job.progress){speedMarks.current.delete(id);return job;}
   const verifying=job.progress.phase==='verifying';
   const bytes=(verifying?job.progress.file_bytes_done:job.progress.bytes_done)||0;const prev=speedMarks.current.get(id);
   let speed=job.progress.speed_bps||0;
   if(prev&&now>prev.t+400){
    const measured=(bytes-prev.b)/((now-prev.t)/1000);
    if(measured>0)speed=measured;
    else if(!(speed>0)&&now-prev.t<8000)speed=prev.speed||0;
   }else if(!(speed>0)&&prev&&now-prev.t<8000)speed=prev.speed||0;
   speedMarks.current.set(id,{t:now,b:bytes,speed:speed||0});
   return {...job,progress:{...job.progress,speed_bps:speed||0}};
  });
  for(const id of [...speedMarks.current.keys()])if(!active.has(id))speedMarks.current.delete(id);
  return next;
 };
 const load=useCallback(async(signal?:AbortSignal)=>{const result=await api<{jobs:Job[]}>('attachments/storage/jobs?'+new URLSearchParams({root}),undefined,'GET',{signal,force:true});if(!signal?.aborted)setJobs(decorate(result.jobs.filter(job=>job.state!=='cancelled')));},[root]);
 useEffect(()=>{const controller=new AbortController();void load(controller.signal).catch(reason=>{if(!controller.signal.aborted)setError(reason.message);});return()=>controller.abort();},[load]);
 useEffect(()=>{if(enabled.some(item=>item.storage_id===target))return;setTarget(enabled[0]?.storage_id||'');},[storages,target]);
 const hasPending=jobs.some(pending);
 useEffect(()=>{if(!hasPending)return;const controller=new AbortController(),timer=window.setInterval(()=>{void load(controller.signal).catch(reason=>{if(!controller.signal.aborted)setError(reason.message);});},1000);return()=>{controller.abort();window.clearInterval(timer);};},[hasPending,load]);
 useEffect(()=>{if(!busy){setElapsed(0);return;}const started=Date.now(),timer=window.setInterval(()=>setElapsed(Math.floor((Date.now()-started)/1000)),250);return()=>window.clearInterval(timer);},[busy]);
 const begin=(kind:Activity)=>{setBusy(true);setActivity(kind);setError('');};
 const end=()=>{setBusy(false);setActivity('');};
 const run=async(kind:Activity,work:()=>Promise<Job>)=>{if(busy)return;begin(kind);try{const job=await work();const id=jobKey(job);setDismissed(current=>{const next={...current};delete next[id];return next;});setJobs(current=>decorate([job,...current.filter(value=>jobKey(value)!==id)]));invalidate();}catch(reason){setError((reason as Error).message);}finally{end();}};
 const action=(job:Job,name:string)=>{
  if(name==='cancel'){
   if(busy)return;begin('cancel');
   const id=jobKey(job);
   void api<Job>('attachments/storage/jobs/'+encodeURIComponent(id)+'/cancel',{root,confirm:true},'POST')
    .then(()=>{setJobs(current=>current.filter(value=>jobKey(value)!==id));invalidate();})
    .catch(reason=>setError((reason as Error).message))
    .finally(end);
   return;
  }
  void run('task',()=>api<Job>('attachments/storage/jobs/'+encodeURIComponent(jobKey(job))+'/'+name,{root,confirm:true},'POST'));
 };
 const prepare=()=>{
  const paths=parsePaths(pathsText);
  if(paths.length>10000){setError(t('as.batchTooLarge'));return;}
  void run('preview',()=>api<Job>('attachments/storage/migrations',{root,storage_id:target,...(paths.length?{paths}:{})},'POST'));
 };
 const busyLabel=activity==='preview'?t('as.previewWorking'):activity==='cancel'?t('as.cancelWorking'):t('as.taskWorking');
 const visible=jobs.slice(0,30).filter(job=>!(job.state==='completed'&&dismissed[jobKey(job)]));
 return <section className="attachment-storage-tasks" aria-busy={busy}><h4>{t('as.tasks')}</h4><p className="setting-detail">{t('as.migrationHelp')}</p><p className="setting-detail">{t('as.remoteBatchHelp')}</p>{error&&<StatusNotice kind="error"><Diagnostic message={error}/></StatusNotice>}
  {busy&&<StatusNotice kind="busy"><div className="attachment-storage-busy"><span>{busyLabel}{elapsed>0?' · '+t('as.busyElapsed',{seconds:elapsed}):''}</span><progress aria-label={busyLabel}/></div></StatusNotice>}
  <div className="attachment-storage-actions"><select aria-label={t('as.migrationTarget')} disabled={disabled||busy} value={target} onChange={event=>setTarget(event.target.value)}><option value="">{t('as.migrationTarget')}</option>{storages.filter(item=>item.enabled).map(item=><option key={item.storage_id} value={item.storage_id}>{item.name||t('as.unnamed')}</option>)}</select><button disabled={disabled||busy||!storages.some(item=>item.storage_id===target&&item.enabled)} onClick={prepare}>{t('as.prepareMigration')}</button><button disabled={busy} onClick={()=>void load().catch(reason=>setError(reason.message))}>{t('aw.refresh')}</button></div>
  <label className="setting-detail" htmlFor="attachment-migration-paths">{t('as.batchPaths')}</label>
  <textarea id="attachment-migration-paths" rows={4} disabled={disabled||busy} aria-label={t('as.batchPaths')} placeholder={t('as.batchPathsPlaceholder')} value={pathsText} onChange={event=>setPathsText(event.target.value)}/>
  {visible.map(job=>{
   const id=jobKey(job);
   const current=job.items?.find(item=>['uploading','mapped','releasing'].includes(item.state||''));
   const progress=job.progress;
   const showProgress=!!progress&&progress.total>0&&(pending(job)||job.state==='completed'||job.state==='planned');
   const useBytes=!!progress&&(progress.bytes_total||0)>0;
   const phase=progress?.phase||'';
   const phaseKey=['hashing','probing','uploading','verifying'].includes(phase)?'as.transferPhase.'+phase:'';
   const speed=pending(job)?formatSpeed(progress?.speed_bps||0):'';
   const byteLabel=useBytes?t('as.transferBytes',{done:formatBytes(progress!.bytes_done||0),total:formatBytes(progress!.bytes_total||0)}):'';
   const fileLabel=pending(job)&&(progress?.file_bytes_total||0)>0?t('as.transferBytes',{done:formatBytes(progress!.file_bytes_done||0),total:formatBytes(progress!.file_bytes_total||0)}):'';
   const waitingBody=pending(job)&&!(progress?.file_bytes_done||0)&&['hashing','probing',''].includes(phase);
   const hint=pending(job)?(waitingBody?t('as.transferProbeHint'):phase==='verifying'?t('as.transferVerifyHint'):!(progress?.speed_bps||0)?t('as.transferSlowHint'):''):'';
   const detailsOpen=!!openDetails[id];
   const hasDetails=!!(job.items?.length||job.exclusions?.length||job.error);
   const progressValue=showProgress?(useBytes?progress!.bytes_done||0:progress!.done):0;
   const progressMax=showProgress?(useBytes?progress!.bytes_total||1:progress!.total):1;
   const statusLine=[t('as.transferProgress',{done:progress?.done||0,total:progress?.total||0}),byteLabel,speed,phaseKey?t(phaseKey):'',fileLabel,current?.path,hint].filter(Boolean).join(' · ');
   return <section className="attachment-storage-task" key={id}>
    <div className="attachment-storage-task-head"><strong>{t(job.kind==='migration'?'as.migration':'as.uploadTask')}</strong><span>{t('as.job.'+job.state)}</span>{job.summary&&<small>{t('as.taskSummary',{files:job.summary.files,mib:(job.summary.bytes/(1024*1024)).toFixed(1)})}</small>}</div>
    {showProgress&&<div className="attachment-storage-progress-row"><progress aria-label={statusLine||t('as.transferProgress',{done:progress!.done,total:progress!.total})} value={progressValue} max={progressMax}/><div className="attachment-storage-progress-actions">{hasDetails&&<button type="button" className="attachment-storage-detail-toggle" aria-expanded={detailsOpen} onClick={()=>setOpenDetails(current=>({...current,[id]:!current[id]}))}>{detailsOpen?t('as.hideDetails'):t('as.viewDetails')}</button>}{job.state==='completed'&&<button type="button" className="attachment-storage-detail-toggle" onClick={()=>setDismissed(current=>({...current,[id]:true}))}>{t('as.dismissTask')}</button>}</div></div>}
    {showProgress&&pending(job)&&statusLine&&<p className="attachment-storage-progress-meta">{statusLine}</p>}
    {job.error&&<p className="error"><Diagnostic message={job.error}/></p>}
    {detailsOpen&&<>
     {!!job.items?.length&&<div className="attachment-storage-detail-block"><p className="setting-detail">{t('as.migrationFiles',{count:job.items.length})}</p><ul>{job.items.slice(0,200).map(item=><li key={item.path}>{item.path}{item.state==='uploading'?' · '+t('as.job.uploading'):''}</li>)}</ul></div>}
     {!!job.exclusions?.length&&<div className="attachment-storage-detail-block"><p className="setting-detail">{t('as.exclusions',{count:job.exclusions.length})}</p><ul>{job.exclusions.slice(0,200).map((item,index)=><li key={index}>{item.path}: <Diagnostic message={item.reason}/></li>)}</ul></div>}
     <p className="setting-detail">{t('as.previewLimit')}</p>
    </>}
    <div className="attachment-storage-task-actions">{job.state==='planned'&&<button className="primary" disabled={busy||disabled} onClick={()=>void action(job,'execute')}>{t('as.executeMigration')}</button>}{['failed','interrupted','conflict','waiting_for_connection','waiting_for_auth','waiting_for_authorization'].includes(job.state)&&<button disabled={busy||disabled} onClick={()=>void action(job,'resume')}>{t('as.resumeMigration')}</button>}{(pending(job)||job.state==='planned')&&<button disabled={busy} onClick={()=>void action(job,'cancel')}>{t('取消')}</button>}</div>
   </section>;})}{!visible.length&&!busy&&<p className="setting-detail">{t('as.noTasks')}</p>}
 </section>;
}
