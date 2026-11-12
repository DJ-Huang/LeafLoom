import {useEffect,useState} from 'react';
import {AlertCircle,CheckCircle2,Loader2,RefreshCw} from 'lucide-react';
import {api} from './api';
import {Diagnostic,t,useLocale} from './i18n';
import {Modal} from './ui';

type Connection={phase?:string,current_directory?:string,server_directories?:number,scan_paused?:boolean,membership_mode?:string,scan_excluded?:number,state:string,code?:string,reason?:string,operation?:string,checked_at?:number,scan_state?:string,scan_mode?:string,cached_directories?:number,scan_scanned?:number,scanned?:number,directories?:number,pending_directories?:number,last_success_at?:number,next_scan_at?:number,next_retry_at?:number,retry_paused?:boolean};
type Metadata={done?:number,total?:number,storage_id?:string,state?:string,phase?:string,retrying?:boolean,code?:string,reason?:string,operation?:string,checked_at?:number,last_synced_at?:number,pending?:number};
type Storage={storage_id:string,name:string,enabled:boolean,membership_mode?:string,connection?:Connection};
const catalogWork=(item:Storage)=>['import','catalog'].includes(item.connection?.phase||'');
const activeWork=(item:Storage)=>item.connection?.scan_state==='scanning'||item.connection?.state==='scanning';
// Pause only stops directory discovery. Catalog import/sync must still show progress.
const running=(item:Storage)=>!activeWork(item)?false:catalogWork(item)||!item.connection?.scan_paused;
const attention=(state?:string)=>!!state&&!['ready','queued','syncing','local_only','uninitialized'].includes(state);
export function AttachmentServerRefresh({root}:{root:string}){
 const locale=useLocale();
 const [open,setOpen]=useState(false),[storages,setStorages]=useState<Storage[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(''),[metadata,setMetadata]=useState<Metadata>();
 const enabled=storages.filter(item=>item.enabled),scans=enabled.filter(running),scanning=scans.length>0;
 const failed=!!error||enabled.some(item=>!item.connection?.scan_paused&&['unconfigured','auth_required','unreachable','invalid_service','cancelled'].includes(item.connection?.state||''));
 const metadataWaitingRetry=!!metadata?.storage_id&&metadata.state==='unreachable';
 const metadataFailed=!!metadata?.storage_id&&attention(metadata.state)&&!metadataWaitingRetry;
 const pollingActive=scanning||metadataWaitingRetry||metadata?.state==='syncing'||metadata?.state==='queued';
 useEffect(()=>{
  const controller=new AbortController();let polling=false;
  const poll=async()=>{
   if(polling||document.hidden)return;polling=true;
   try{
    const [servers,library]=await Promise.allSettled([
     api<{storages:Storage[]}>('attachments/storage?'+new URLSearchParams({root}),undefined,'GET',{signal:controller.signal,force:true}),
     api<Metadata>('asset-library/status?'+new URLSearchParams({root}),undefined,'GET',{signal:controller.signal,force:true}),
    ]);
    if(controller.signal.aborted)return;
    if(servers.status==='fulfilled')setStorages(servers.value.storages);
    if(library.status==='fulfilled')setMetadata(library.value);
    setError(servers.status==='rejected'?(servers.reason as Error).message:library.status==='rejected'?(library.reason as Error).message:'');
   }finally{polling=false;}
  };
  void poll();const timer=window.setInterval(()=>void poll(),open||pollingActive?2000:15000);
  return()=>{controller.abort();window.clearInterval(timer);};
 },[root,open,pollingActive]);
 const number=(value:number)=>value.toLocaleString(locale);
 const progress=(items:Storage[])=>({done:items.reduce((sum,item)=>sum+(item.connection?.directories||0),0),pending:items.reduce((sum,item)=>sum+(item.connection?.pending_directories||0),0)});
 const counts=progress(scans);
 const title=scanning?t('aw.syncProgressCompact',{done:number(counts.done),pending:number(counts.pending)}):t(!enabled.length?'as.local':enabled.every(item=>item.connection?.scan_paused)?'sc.paused':failed||metadataFailed?'aw.syncAttention':metadataWaitingRetry?'aw.autoRetry':metadata?.pending||metadata?.state==='syncing'||metadata?.state==='queued'?'aw.syncing':'aw.autoSync');
 const sync=async(item:Storage,forceFull=false)=>{
  setBusy(item.storage_id);setError('');
  try{
   await api('attachments/storage/scan',{root,storage_id:item.storage_id,...(forceFull?{force_full:true}:{})},'POST');
   setStorages(current=>current.map(value=>value.storage_id===item.storage_id?{...value,connection:{state:'scanning',scan_state:'scanning',scanned:0,directories:0,pending_directories:1,membership_mode:value.membership_mode||value.connection?.membership_mode}}:value));
   setBusy('');
   if(metadata?.storage_id===item.storage_id)await api('asset-library/actions',{root,action:'sync',operation_id:crypto.randomUUID()},'POST');
  }catch(reason){setError((reason as Error).message);}finally{setBusy('');}
 };
 const importCatalog=async(item:Storage)=>{
  setBusy(item.storage_id);setError('');
  // Show import progress immediately, even while directory checks stay paused.
  setStorages(current=>current.map(value=>value.storage_id===item.storage_id?{...value,connection:{...value.connection,state:'scanning',scan_state:'scanning',phase:'import',membership_mode:value.membership_mode||value.connection?.membership_mode||'discover',scanned:0,directories:0,pending_directories:1}}:value));
  try{
   await api('attachments/storage/catalog-import',{root,storage_id:item.storage_id},'POST');
  }catch(reason){
   setError((reason as Error).message);
   setStorages(current=>current.map(value=>value.storage_id===item.storage_id?{...value,connection:{...value.connection,state:value.connection?.scan_paused?'ready':(value.connection?.state||'ready'),scan_state:value.connection?.scan_paused?'paused':value.connection?.scan_state,phase:undefined}}:value));
  }finally{setBusy('');}
 };
 const pause=async(item:Storage)=>{
  setBusy(item.storage_id);setError('');
  try{const paused=!item.connection?.scan_paused;await api('attachments/storage/scan-pause',{root,storage_id:item.storage_id,paused},'POST');setStorages(current=>current.map(value=>value.storage_id===item.storage_id?{...value,connection:{...value.connection,state:value.connection?.state||'ready',scan_paused:paused}}:value));}
  catch(reason){setError((reason as Error).message);}finally{setBusy('');}
 };
 const metadataMessage=()=>{
  if(metadataFailed)return 'aw.syncAttention';
  if(metadataWaitingRetry)return 'aw.autoRetry';
  if(metadata?.state==='syncing'&&metadata.phase&&['pulling','publishing','projecting'].includes(metadata.phase))return 'sc.metadata.'+metadata.phase;
  if(metadata?.state==='syncing')return metadata.retrying?(metadata.phase==='connecting'?'aw.reconnecting':'aw.recoveredSyncing'):'aw.syncing';
  if(metadata?.state==='queued')return 'aw.syncQueued';
  if(metadata?.state==='uninitialized')return 'aw.syncWaiting';
  return metadata?.pending?'aw.syncing':'ag.synced';
 };
 const stamp=(value?:number)=>value?new Date(value*1000).toLocaleString(locale):t('aw.notSynced');
 return <><button className="aw-sync-button" onClick={()=>setOpen(true)} aria-label={t('aw.syncDetails')} title={title}>
  {scanning?<Loader2 size={15} className="aw-spin"/>:failed||metadataFailed?<AlertCircle size={15}/>:<CheckCircle2 size={15}/>}
  <span aria-live="polite" aria-atomic="true">{title}</span>{scanning&&(failed||metadataFailed)&&<AlertCircle size={14} className="error" aria-label={t('aw.syncAttention')}/>}
 </button>{open&&<Modal title={t('aw.syncDetails')} onClose={()=>setOpen(false)} className="aw-sync-dialog"><div className="pad">
  <p className="subtle">{t('sc.available')}</p>
  {error&&<p role="alert" className="error"><Diagnostic message={error}/></p>}{!enabled.length&&<p>{t('aw.noServers')}</p>}
  {enabled.map(item=>{const c=item.connection,isRunning=running(item),mode=item.membership_mode||c?.membership_mode||'discover',statusKey=catalogWork(item)&&activeWork(item)?'sc.phase.'+(c?.phase||'import'):c?.scan_paused?'sc.paused':isRunning?'sc.phase.'+(c?.phase||'checking_directories'):c?.retry_paused?'aw.authPaused':'as.connectionState.'+(c?.state||'unchecked');return <section key={item.storage_id}>
   <strong>{item.name||t('as.unnamed')}</strong><p>{t(statusKey)}</p>
   <small>{t(mode==='app_only'?'sc.membershipAppOnly':'sc.membershipDiscover')}</small>
   {(isRunning||c?.directories!==undefined)&&<p role="status">{t('as.scanProgress',{files:number(c?.scan_scanned??c?.scanned??0),directories:number(c?.directories??0),pending:number(c?.pending_directories??0)})}</p>}
   {isRunning&&c?.current_directory!==undefined&&<small>{t('sc.currentDirectory')}: {c.current_directory||'/'}</small>}
   {c?.server_directories!==undefined&&<small>{t('sc.networkDirectories',{count:number(c.server_directories)})}</small>}
   {c?.scan_mode&&['full','incremental','resume'].includes(c.scan_mode)&&<small>{t('aw.scanMode.'+c.scan_mode)} · {t('aw.scanReused',{count:number(c.cached_directories||0)})}</small>}
   {!c?.scan_paused&&c?.code&&attention(c.state)&&c.state!=='scanning'&&<p className="error"><Diagnostic message={c.reason||c.code}/></p>}
   <small>{t('aw.lastSynced')}: {stamp(c?.last_success_at)}</small>
   {c?.next_retry_at&&c.state==='unreachable'?<small>{t('aw.nextRetry')}: {stamp(c.next_retry_at)}</small>:!c?.scan_paused&&c?.next_scan_at&&c.next_scan_at>Date.now()/1000?<small>{t('aw.nextSync')}: {stamp(c.next_scan_at)}</small>:null}
   <div className="aw-actions"><button disabled={!!busy||isRunning||c?.retry_paused||(mode==='discover'&&c?.scan_paused)} onClick={()=>void sync(item)}><RefreshCw size={14}/>{t('aw.syncNow')}</button>
   {mode==='discover'&&<button disabled={!!busy||isRunning||c?.retry_paused||c?.scan_paused} onClick={()=>void sync(item,true)} title={t('aw.fullCheckHelp')}>{t('aw.fullCheck')}</button>}
   {mode==='discover'&&<button disabled={!!busy||isRunning||c?.retry_paused} onClick={()=>void importCatalog(item)} title={t('sc.importCatalogHelp')}>{busy===item.storage_id&&c?.phase==='import'?<Loader2 size={14} className="aw-spin"/>:null}{t(isRunning&&c?.phase==='import'?'sc.phase.import':'sc.importCatalog')}</button>}
   {mode==='discover'&&<button disabled={!!busy||(isRunning&&catalogWork(item))} onClick={()=>void pause(item)}>{t(c?.scan_paused?'sc.resume':'sc.pause')}</button>}</div>
  </section>;})}
  {metadata?.storage_id&&<section><strong>{t('aw.metadataSync')}</strong>
   <p role="status">{t(metadataMessage())}</p>
   {metadata.state==='syncing'&&metadata.total!==undefined&&<small>{t('sc.metadataProgress',{done:number(metadata.done||0),total:number(metadata.total)})}</small>}
   {metadataFailed&&metadata.code&&<p className="error"><Diagnostic message={metadata.reason||metadata.code}/></p>}
   {metadataWaitingRetry&&metadata.code&&<details className="aw-sync-last-error"><summary>{t('aw.lastConnectionIssue')}</summary><p><Diagnostic message={metadata.reason||metadata.code}/></p>
    {metadata.checked_at&&<small>{t('aw.lastFailure')}: {stamp(metadata.checked_at)}</small>}
   </details>}
   {metadataFailed&&metadata.checked_at&&<small>{t('aw.lastFailure')}: {stamp(metadata.checked_at)}</small>}
   {metadata.last_synced_at&&<small>{t('aw.lastSynced')}: {stamp(metadata.last_synced_at)}</small>}
  </section>}
  <p className="subtle">{t('aw.autoSyncHelp')}</p>
 </div></Modal>}</>;
}
