import {useEffect,useRef,useState} from 'react';
import {AlertCircle,CheckCircle2,Loader2,RefreshCw} from 'lucide-react';
import {api} from './api';
import {Diagnostic,t,useLocale} from './i18n';
import {Modal} from './ui';

type Storage={storage_id:string,name:string,enabled:boolean};
type Connection={state:string,code?:string,scan_state?:string,scan_id?:string,scan_scanned?:number,scan_missing?:number,scan_excluded?:number,scanned?:number,directories?:number,pending_directories?:number};
type Phase='idle'|'starting'|'scanning'|'completed'|'failed'|'unconfirmed';
export function AttachmentServerRefresh({root,sourceFilter,storages,onUpdated}:{root:string,sourceFilter:string,storages:Storage[],onUpdated:()=>void}){
 useLocale();
 const [open,setOpen]=useState(false),[selection,setSelection]=useState(''),[scan,setScan]=useState<{storage_id:string,name:string,scan_id?:string}>(),[phase,setPhase]=useState<Phase>('idle'),[connection,setConnection]=useState<Connection>(),[error,setError]=useState('');
 const life=useRef(new AbortController()),updated=useRef(onUpdated);updated.current=onUpdated;
 useEffect(()=>{const controller=new AbortController();life.current=controller;setOpen(false);setSelection('');setScan(undefined);setPhase('idle');setConnection(undefined);setError('');return()=>controller.abort();},[root]);
 const enabled=storages.filter(storage=>storage.enabled),specific=sourceFilter.startsWith('storage:')?sourceFilter.slice(8):'',available=specific?enabled.filter(storage=>storage.storage_id===specific):enabled,busy=phase==='starting'||phase==='scanning';
 const start=async(id:string)=>{
  const target=enabled.find(storage=>storage.storage_id===id);if(!target||busy)return;
  const controller=life.current;
  setScan({...target});setConnection(undefined);setPhase('starting');setError('');
  try{
   const result=await api<{ok?:boolean,state:string,scan_id?:string}>('attachments/storage/scan',{root,storage_id:id},'POST',{signal:controller.signal});
   if(controller.signal.aborted||controller!==life.current)return;
   if(result.ok===false||!['scanning','ready'].includes(result.state))throw new Error(t('aw.serverRefreshFailed'));
   setScan({...target,scan_id:result.scan_id});setOpen(false);setPhase('scanning');
  }catch(reason){if(!controller.signal.aborted&&controller===life.current){setError((reason as Error).message);setPhase('failed');}}
 };
 useEffect(()=>{
  if(phase!=='scanning'||!scan)return;
  const controller=new AbortController();let polling=false;
  const poll=async()=>{
   if(polling||controller.signal.aborted)return;polling=true;
   try{
    const result=await api<{storages:(Storage&{connection?:Connection})[]}>('attachments/storage?'+new URLSearchParams({root}),undefined,'GET',{signal:controller.signal,force:true});
    if(controller.signal.aborted)return;
    const current=result.storages.find(storage=>storage.storage_id===scan.storage_id)?.connection;
    if(!current)throw new Error(t('aw.serverRefreshStatusUnavailable'));
    setConnection(current);setError('');
    if(!scan.scan_id||!current.scan_id||scan.scan_id!==current.scan_id){setPhase('unconfirmed');updated.current();return;}
    if(current.scan_state==='completed'){setPhase('completed');updated.current();}
    else if(current.scan_state==='failed'||current.scan_state==='cancelled'){setPhase('failed');updated.current();}
    else if(current.scan_state!=='scanning'){setPhase('unconfirmed');updated.current();}
   }catch(reason){if(!controller.signal.aborted)setError((reason as Error).message);}finally{polling=false;}
  };
  void poll();const timer=window.setInterval(()=>void poll(),2000);
  return()=>{controller.abort();window.clearInterval(timer);};
 },[root,phase,scan?.storage_id,scan?.scan_id]);
 const status=phase==='completed'?'aw.serverRefreshComplete':phase==='failed'?'aw.serverRefreshFailed':phase==='unconfirmed'?'aw.serverRefreshUnconfirmed':'aw.serverRefreshRunning';
 if(phase==='idle'&&(sourceFilter==='local'||!storages.length))return null;
 return <div className="aw-server-refresh">
  {sourceFilter!=='local'&&<button disabled={busy||!available.length} title={t(available.length?'aw.serverRefreshHint':'aw.serverRefreshNoEnabled')} onClick={()=>{if(available.length===1)void start(available[0].storage_id);else{setSelection('');setOpen(true);}}}>{busy?<Loader2 size={15} className="aw-spin"/>:<RefreshCw size={15}/>} {t('aw.serverRefresh')}</button>}
  {phase!=='idle'&&<div className={'aw-server-refresh-status '+(phase==='failed'?'error':'')} role="status">{phase==='completed'?<CheckCircle2 size={13}/>:phase==='failed'||phase==='unconfirmed'?<AlertCircle size={13}/>:<Loader2 size={13} className="aw-spin"/>}<div><strong>{scan?.name||t('as.unnamed')}: {t(status)}</strong>{busy&&connection&&<small>{t('aw.serverRefreshProgress',{files:connection.scan_scanned??connection.scanned??0,directories:connection.directories??0,pending:connection.pending_directories??0})}</small>}{phase==='completed'&&connection?.scan_missing!==undefined&&<small>{t('aw.serverRefreshMissing',{count:connection.scan_missing})}</small>}{phase==='completed'&&connection?.scan_excluded!==undefined&&<small>{t('aw.serverRefreshExcluded',{count:connection.scan_excluded})}</small>}{phase==='failed'&&<><small>{t('aw.serverRefreshRetained')}</small>{connection?.code&&<small><Diagnostic message={connection.code}/></small>}</>}{error&&<small className="error"><Diagnostic message={error}/></small>}</div></div>}
  {open&&<Modal title={t('aw.serverRefreshChoose')} onClose={()=>{if(!busy)setOpen(false);}} className="aw-server-refresh-dialog"><div className="pad"><p>{t('aw.serverRefreshHint')}</p><label>{t('aw.sourceServers')}<select aria-label={t('aw.sourceServers')} value={selection} onChange={event=>setSelection(event.target.value)} disabled={busy}><option value="">{t('aw.serverRefreshChoose')}</option>{enabled.map(storage=><option key={storage.storage_id} value={storage.storage_id}>{storage.name||t('as.unnamed')}</option>)}</select></label>{error&&<p className="error"><Diagnostic message={error}/></p>}<footer><button disabled={busy} onClick={()=>setOpen(false)}>{t('取消')}</button><button className="primary" disabled={busy||!selection} onClick={()=>void start(selection)}>{t('aw.serverRefreshStart')}</button></footer></div></Modal>}
 </div>;
}
