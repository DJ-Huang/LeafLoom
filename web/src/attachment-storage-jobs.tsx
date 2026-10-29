import {useCallback,useEffect,useState} from 'react';
import {api,invalidate} from './api';
import {Diagnostic,t,useLocale} from './i18n';
import {StatusNotice} from './settings-ui';

type Job={id:string,job_id?:string,kind:string,state:string,storage_id?:string,items?:{path:string,size:number}[],exclusions?:{path:string,reason:string}[],summary?:{files:number,bytes:number},progress?:{done:number,total:number},error?:string};
const pending=(job:Job)=>['queued','waiting_for_connection','waiting_for_auth','waiting_for_authorization','running','uploading','verifying'].includes(job.state);
export function AttachmentStorageJobs({root,storages,disabled}:{root:string,storages:{storage_id:string,name:string,enabled:boolean}[],disabled:boolean}){
 useLocale();
 const [jobs,setJobs]=useState<Job[]>([]),[target,setTarget]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const load=useCallback(async(signal?:AbortSignal)=>{const result=await api<{jobs:Job[]}>('attachments/storage/jobs?'+new URLSearchParams({root}),undefined,'GET',{signal,force:true});if(!signal?.aborted)setJobs(result.jobs);},[root]);
 useEffect(()=>{const controller=new AbortController();void load(controller.signal).catch(reason=>{if(!controller.signal.aborted)setError(reason.message);});return()=>controller.abort();},[load]);
 const hasPending=jobs.some(pending);
 useEffect(()=>{if(!hasPending)return;const controller=new AbortController(),timer=window.setInterval(()=>{void load(controller.signal).catch(reason=>{if(!controller.signal.aborted)setError(reason.message);});},1800);return()=>{controller.abort();window.clearInterval(timer);};},[hasPending,load]);
 const run=async(work:()=>Promise<Job>)=>{if(busy)return;setBusy(true);setError('');try{const job=await work();setJobs(current=>[job,...current.filter(value=>(value.job_id||value.id)!==(job.job_id||job.id))]);invalidate();}catch(reason){setError((reason as Error).message);}finally{setBusy(false);}};
 const action=(job:Job,name:string)=>run(()=>api<Job>('attachments/storage/jobs/'+encodeURIComponent(job.job_id||job.id)+'/'+name,{root,confirm:true},'POST'));
 return <section className="attachment-storage-tasks"><h4>{t('as.tasks')}</h4><p className="setting-detail">{t('as.migrationHelp')}</p>{error&&<StatusNotice kind="error"><Diagnostic message={error}/></StatusNotice>}
  <div className="attachment-storage-actions"><select aria-label={t('as.migrationTarget')} disabled={disabled||busy} value={target} onChange={event=>setTarget(event.target.value)}><option value="">{t('as.migrationTarget')}</option>{storages.filter(item=>item.enabled).map(item=><option key={item.storage_id} value={item.storage_id}>{item.name||t('as.unnamed')}</option>)}</select><button disabled={disabled||busy||!storages.some(item=>item.storage_id===target&&item.enabled)} onClick={()=>void run(()=>api<Job>('attachments/storage/migrations',{root,storage_id:target},'POST'))}>{t('as.prepareMigration')}</button><button disabled={busy} onClick={()=>void load().catch(reason=>setError(reason.message))}>{t('aw.refresh')}</button></div>
  {jobs.slice(0,30).map(job=><section className="attachment-storage-task" key={job.job_id||job.id}><div><strong>{t(job.kind==='migration'?'as.migration':'as.uploadTask')}</strong><span>{t('as.job.'+job.state)}</span>{job.summary&&<small>{t('as.taskSummary',{files:job.summary.files,mib:(job.summary.bytes/(1024*1024)).toFixed(1)})}</small>}</div>{job.progress&&job.progress.total>0&&<progress value={job.progress.done} max={job.progress.total}/>} {job.error&&<p className="error"><Diagnostic message={job.error}/></p>}
   {!!job.items?.length&&<details open={job.state==='planned'}><summary>{t('as.migrationFiles',{count:job.items.length})}</summary><ul>{job.items.slice(0,200).map(item=><li key={item.path}>{item.path}</li>)}</ul></details>}{!!job.exclusions?.length&&<details><summary>{t('as.exclusions',{count:job.exclusions.length})}</summary><ul>{job.exclusions.slice(0,200).map((item,index)=><li key={index}>{item.path}: <Diagnostic message={item.reason}/></li>)}</ul></details>}
   <p className="setting-detail">{t('as.previewLimit')}</p><div>{job.state==='planned'&&<button className="primary" disabled={busy||disabled} onClick={()=>void action(job,'execute')}>{t('as.executeMigration')}</button>}{['failed','interrupted','cancelled','conflict','waiting_for_connection','waiting_for_auth','waiting_for_authorization'].includes(job.state)&&<button disabled={busy||disabled} onClick={()=>void action(job,'resume')}>{t('重试')}</button>}{(pending(job)||job.state==='planned')&&<button disabled={busy} onClick={()=>void action(job,'cancel')}>{t('取消')}</button>}</div>
  </section>)}{!jobs.length&&<p className="setting-detail">{t('as.noTasks')}</p>}
 </section>;
}
