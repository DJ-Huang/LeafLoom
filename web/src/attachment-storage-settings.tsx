import {useEffect,useRef,useState} from 'react';
import {api,invalidate} from './api';
import {Diagnostic,t,useLocale} from './i18n';
import {SettingGroup,SettingRow,StatusNotice} from './settings-ui';
import {AttachmentStorageJobs} from './attachment-storage-jobs';
import type {AttachmentCredentialStatus} from './desktop';
import {AssetLibrarySettings} from './asset-library';

type Storage={storage_id:string,name:string,base_url:string,remote_root:string,upload_directory:string,username:string,connection_hint:'direct'|'official-client',enabled:boolean,password_saved:boolean,connection?:{state:string,message?:string,scanned?:number,directories?:number,pending_directories?:number,retry_attempts?:number,next_retry_at?:number|null,retry_paused?:boolean}};
type StorageConfig={root:string,revision:string,storages:Storage[],default_storage_id:string,cache_limit_bytes:number,outbox_limit_bytes:number,cache:{used_bytes:number,files:number},outbox:{used_bytes:number,pending:number}};
const mib=1024*1024;
const copy=(value:StorageConfig)=>JSON.parse(JSON.stringify(value)) as StorageConfig;
const size=(bytes:number)=>new Intl.NumberFormat(undefined,{maximumFractionDigits:1}).format(bytes/mib)+' MiB';
const connectionStates=new Set(['ready','unconfigured','unchecked','scanning','auth_required','unreachable','invalid_service']);
function ConnectionStatus({connection}:{connection:NonNullable<Storage['connection']>}){
 return connectionStates.has(connection.state)?<>{t('as.connectionState.'+connection.state)}</>:<Diagnostic message={connection.message||connection.state}/>;
}

export function AttachmentStorageSettings({root,onUnsavedChange}:{root:string,onUnsavedChange?:(dirty:boolean)=>void}){
 useLocale();
 const [draft,setDraft]=useState<StorageConfig>(),[baseline,setBaseline]=useState<StorageConfig>(),[passwords,setPasswords]=useState<Record<string,string>>({}),[cleared,setCleared]=useState<string[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState(''),[messageKind,setMessageKind]=useState<'success'|'error'>('success');
 const [credentialStatus,setCredentialStatus]=useState<AttachmentCredentialStatus>();
 const [libraryDirty,setLibraryDirty]=useState(false);
 const scope=useRef<AbortController>(new AbortController());
 const dirty=!!draft&&!!baseline&&(JSON.stringify(draft)!==JSON.stringify(baseline)||Object.keys(passwords).length>0||cleared.length>0);
 const latestDraft=useRef(draft),isDirty=useRef(dirty);latestDraft.current=draft;isDirty.current=dirty;
 const monitoring=!!draft?.storages.some(item=>item.enabled);
 useEffect(()=>{onUnsavedChange?.(dirty||libraryDirty);return()=>onUnsavedChange?.(false);},[dirty,libraryDirty,onUnsavedChange]);
 const load=async(signal=scope.current.signal)=>{const value=await api<StorageConfig>('attachments/storage?'+new URLSearchParams({root}),undefined,'GET',{signal,force:true});if(!signal.aborted){setDraft(copy(value));setBaseline(value);}return value;};
 useEffect(()=>{const controller=new AbortController();scope.current=controller;void load(controller.signal).catch(reason=>{if(!controller.signal.aborted)setError(reason.message);});return()=>controller.abort();},[root]);
 useEffect(()=>{
  if(!window.leafloomDesktop?.attachmentCredentialStatus)return;
  let active=true,polling=false,previous='';
  const poll=async()=>{
   if(polling||!active)return;polling=true;
   try{
    const value=await window.leafloomDesktop!.attachmentCredentialStatus();
    if(!active)return;setCredentialStatus(value);
    if(previous&&previous!=='ready'&&value.state==='ready'&&!isDirty.current)await load();
    previous=value.state;
   }catch{if(active)setCredentialStatus({state:'status_unavailable',saved:true,attempts:0,retry_scheduled:false,next_retry_at:null});}
   finally{polling=false;}
  };
  void poll();const timer=window.setInterval(()=>void poll(),3000);
  return()=>{active=false;window.clearInterval(timer);};
 },[root]);
 useEffect(()=>{
  if(!monitoring)return;
  const controller=new AbortController();let polling=false;
  const poll=async()=>{
   if(polling||controller.signal.aborted)return;polling=true;const revision=latestDraft.current?.revision;
   try{const result=await api<StorageConfig>('attachments/storage?'+new URLSearchParams({root}),undefined,'GET',{signal:controller.signal,force:true});if(!controller.signal.aborted&&!isDirty.current&&latestDraft.current?.revision===revision){setDraft(copy(result));setBaseline(result);}}
   catch(reason){if(!controller.signal.aborted)setError((reason as Error).message);}finally{polling=false;}
  };
  const timer=window.setInterval(()=>void poll(),2000);
  return()=>{controller.abort();window.clearInterval(timer);};
 },[root,monitoring]);
 useEffect(()=>{if(!dirty)return;const leave=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue='';};window.addEventListener('beforeunload',leave);return()=>window.removeEventListener('beforeunload',leave);},[dirty]);
 const change=(id:string,values:Partial<Storage>)=>setDraft(current=>current&&({...current,storages:current.storages.map(item=>item.storage_id===id?{...item,...values}:item)}));
 const run=async(work:()=>Promise<void>)=>{if(busy)return;setBusy(true);setError('');setMessage('');setMessageKind('success');try{await work();}catch(reason){if(!scope.current.signal.aborted)setError((reason as Error).message);}finally{if(!scope.current.signal.aborted)setBusy(false);}};
 const save=()=>run(async()=>{
  if(!draft)return;
  const saved=await api<StorageConfig>('attachments/storage',{root,revision:draft.revision,storages:draft.storages.map(({storage_id,name,base_url,remote_root,upload_directory,username,connection_hint,enabled})=>({storage_id,name,base_url:base_url.trim(),remote_root,upload_directory,username,connection_hint,enabled})),default_storage_id:draft.default_storage_id,cache_limit_bytes:draft.cache_limit_bytes,outbox_limit_bytes:draft.outbox_limit_bytes},'PUT',{signal:scope.current.signal});
  if(scope.current.signal.aborted)return;
  setDraft(copy(saved));setBaseline(saved);
  // A password is never included in the persisted storage configuration.
  let pending=false;
  for(const item of saved.storages){
   const id=item.storage_id,clear=cleared.includes(id),password=passwords[id];
   if(!clear&&password===undefined)continue;
   if(window.leafloomDesktop){const result=clear?await window.leafloomDesktop.clearAttachmentCredential({storage_id:id}):await window.leafloomDesktop.saveAttachmentCredential({storage_id:id,password});pending ||= result.state!=='ready';}
   else await api('attachments/storage/credentials',{entries:{[id]:clear?null:{password,revision:crypto.randomUUID()}}},'POST',{signal:scope.current.signal});
   setPasswords(current=>{const next={...current};delete next[id];return next;});setCleared(current=>current.filter(value=>value!==id));
  }
  await load();invalidate();setMessage(t(pending?'as.credentialsPending':'as.saved'));
 });
 const action=(kind:'test'|'scan',id:string)=>run(async()=>{const result=await api<{ok?:boolean,state?:string}>('attachments/storage/'+kind,{root,storage_id:id},'POST',{signal:scope.current.signal});await load();invalidate();const success=result.ok!==false&&(result.state==='ready'||kind==='scan'&&result.state==='scanning'||(!result.state&&result.ok===true));setMessageKind(success?'success':'error');setMessage(t(success?(kind==='test'?'as.tested':result.state==='scanning'?'as.scanStarted':'as.scanned'):(kind==='test'?'as.testFailed':'as.scanFailed')));});
 const discard=()=>{if(baseline)setDraft(copy(baseline));setPasswords({});setCleared([]);setError('');setMessage('');};
 return <SettingGroup id="attachment-storage" title={t('as.title')} description={t('as.description')}>
  {error&&<StatusNotice kind="error"><Diagnostic message={error}/></StatusNotice>}{message&&<StatusNotice kind={messageKind}>{message}</StatusNotice>}
  {credentialStatus&&<StatusNotice kind={credentialStatus.state==='ready'?'success':credentialStatus.retry_scheduled?'info':'error'}>
   <span role="status">{t('as.credentials.title')}: {t('as.credentials.state.'+credentialStatus.state)} {credentialStatus.retry_scheduled&&t('as.credentials.retryScheduled')}</span>
   {credentialStatus.state!=='ready'&&<button disabled={busy} onClick={()=>void run(async()=>{const result=await window.leafloomDesktop!.retryAttachmentCredentials();setCredentialStatus(result);if(!isDirty.current)await load();})}>{t('as.credentials.retry')}</button>}
  </StatusNotice>}
  {!draft?<button disabled={busy} onClick={()=>void run(async()=>{await load();})}>{t('重试')}</button>:<fieldset className="attachment-storage-fields" disabled={busy}>
   <SettingRow label={t('as.default')} description={t('as.defaultHelp')}><select aria-label={t('as.default')} value={draft.default_storage_id} onChange={event=>setDraft({...draft,default_storage_id:event.target.value})}><option value="local">{t('as.local')}</option>{draft.storages.map(item=><option key={item.storage_id} value={item.storage_id} disabled={!item.enabled}>{item.name||t('as.unnamed')}</option>)}</select></SettingRow>
   {draft.storages.map(item=><section className="attachment-storage-profile" key={item.storage_id}>
    <div className="attachment-storage-heading"><strong>{item.name||t('as.unnamed')}</strong><label><input type="checkbox" checked={item.enabled} onChange={event=>change(item.storage_id,{enabled:event.target.checked})}/>{t('as.enabled')}</label></div>
    <SettingRow label={t('as.name')}><input aria-label={t('as.name')} value={item.name} onChange={event=>change(item.storage_id,{name:event.target.value})}/></SettingRow>
    <SettingRow label={t('as.url')} description={t('as.urlHelp')}><input aria-label={t('as.url')} type="url" placeholder="https://files.example.com" value={item.base_url} onChange={event=>change(item.storage_id,{base_url:event.target.value})}/></SettingRow>
    <SettingRow label={t('as.remoteRoot')}><input aria-label={t('as.remoteRoot')} value={item.remote_root} onChange={event=>change(item.storage_id,{remote_root:event.target.value})}/></SettingRow>
    <SettingRow label={t('as.incoming')} description={t('as.incomingHelp')}><input aria-label={t('as.incoming')} value={item.upload_directory} onChange={event=>change(item.storage_id,{upload_directory:event.target.value})}/></SettingRow>
    <SettingRow label={t('as.username')}><input aria-label={t('as.username')} autoComplete="off" value={item.username} onChange={event=>change(item.storage_id,{username:event.target.value})}/></SettingRow>
    <SettingRow label={t('as.password')} description={t(cleared.includes(item.storage_id)?'as.passwordCleared':item.password_saved?'as.passwordSaved':'as.passwordMissing')}><input aria-label={t('as.password')} type="password" autoComplete="new-password" value={passwords[item.storage_id]??''} placeholder={item.password_saved?t('as.keepPassword'):''} onChange={event=>{const password=event.target.value;setPasswords(current=>{const next={...current};if(password==='')delete next[item.storage_id];else next[item.storage_id]=password;return next;});if(password!=='')setCleared(current=>current.filter(id=>id!==item.storage_id));}}/><button disabled={!item.password_saved&&passwords[item.storage_id]===undefined} onClick={()=>{setCleared(current=>[...current.filter(id=>id!==item.storage_id),item.storage_id]);setPasswords(current=>{const next={...current};delete next[item.storage_id];return next;});}}>{t('as.clearPassword')}</button></SettingRow>
    <SettingRow label={t('as.connection')}><select aria-label={t('as.connection')} value={item.connection_hint} onChange={event=>change(item.storage_id,{connection_hint:event.target.value as Storage['connection_hint']})}><option value="direct">{t('as.direct')}</option><option value="official-client">{t('as.official')}</option></select></SettingRow>
    {item.connection_hint==='official-client'&&<StatusNotice>{t('as.officialHelp')}</StatusNotice>}
    {item.connection&&<p className="setting-detail" role="status">{t('as.connectionState')}: <ConnectionStatus connection={item.connection}/></p>}
    {item.connection?.retry_paused&&<p className="setting-detail" role="status">{t('as.recovery.authPaused')}</p>}
    {item.connection?.state==='unreachable'&&item.connection.next_retry_at!=null&&<p className="setting-detail" role="status">{t('as.recovery.scheduled',{seconds:Math.max(0,Math.ceil(item.connection.next_retry_at-Date.now()/1000)),attempts:item.connection.retry_attempts??0})}</p>}
    {item.connection?.state==='scanning'&&<p className="setting-detail" role="status">{t('as.scanProgress',{files:item.connection.scanned??0,directories:item.connection.directories??0,pending:item.connection.pending_directories??0})}</p>}
    <div className="attachment-storage-actions"><button disabled={dirty||!item.enabled} onClick={()=>void action('test',item.storage_id)}>{t('as.test')}</button><button disabled={dirty||!item.enabled} onClick={()=>void action('scan',item.storage_id)}>{t('as.scan')}</button><button disabled={!!baseline?.storages.some(source=>source.storage_id===item.storage_id)} onClick={()=>{setDraft({...draft,default_storage_id:draft.default_storage_id===item.storage_id?'local':draft.default_storage_id,storages:draft.storages.filter(source=>source.storage_id!==item.storage_id)});setPasswords(current=>{const next={...current};delete next[item.storage_id];return next;});setCleared(current=>current.filter(id=>id!==item.storage_id));}}>{t('as.remove')}</button></div>
   </section>)}
   <p className="setting-detail">{t('as.disableHelp')}</p>
   <button onClick={()=>setDraft({...draft,storages:[...draft.storages,{storage_id:crypto.randomUUID().replace(/-/g,''),name:'',base_url:'',remote_root:'/',upload_directory:'Incoming',username:'',connection_hint:'direct',enabled:true,password_saved:false}]})}>{t('as.add')}</button>
   <StatusNotice>{t(window.leafloomDesktop?'as.desktopCredentials':'as.browserCredentials')}</StatusNotice>
   <SettingRow label={t('as.cacheLimit')} description={t('as.cacheHelp')}><input aria-label={t('as.cacheLimit')} type="number" min="0" step="64" value={draft.cache_limit_bytes/mib} onChange={event=>setDraft({...draft,cache_limit_bytes:Math.max(0,Number(event.target.value)||0)*mib})}/><span>MiB</span></SettingRow>
   <SettingRow label={t('as.outboxLimit')} description={t('as.outboxHelp')}><input aria-label={t('as.outboxLimit')} type="number" min="0" step="64" value={draft.outbox_limit_bytes/mib} onChange={event=>setDraft({...draft,outbox_limit_bytes:Math.max(0,Number(event.target.value)||0)*mib})}/><span>MiB</span></SettingRow>
   <p className="setting-detail">{t('as.usage',{cache:size(draft.cache.used_bytes),files:draft.cache.files,outbox:size(draft.outbox.used_bytes),pending:draft.outbox.pending})}</p>
   <div className="attachment-storage-actions"><button className="primary" disabled={!dirty} onClick={()=>void save()}>{t('as.save')}</button><button disabled={!dirty} onClick={discard}>{t('取消更改')}</button><button disabled={dirty} onClick={()=>void run(async()=>{await api('attachments/cache/clear',{root},'POST',{signal:scope.current.signal});await load();setMessage(t('as.cacheCleared'));})}>{t('as.clearCache')}</button></div>
   <AttachmentStorageJobs root={root} storages={draft.storages} disabled={dirty||busy}/>
  </fieldset>}
  {baseline&&<AssetLibrarySettings key={root} root={root} storages={baseline.storages} disabled={dirty||busy} onUnsavedChange={setLibraryDirty}/>}
 </SettingGroup>;
}
