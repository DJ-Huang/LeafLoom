import {useEffect,useRef,useState} from 'react';
import {api,invalidate} from './api';
import {Diagnostic,t,useLocale} from './i18n';
import {SettingGroup,SettingRow,StatusNotice} from './settings-ui';
import {Modal} from './ui';

type Storage={storage_id:string,name:string,base_url:string,remote_root:string,upload_directory:string,username:string,connection_hint:'direct'|'official-client',enabled:boolean,password_saved:boolean,connection?:{state:string,retry_paused?:boolean}};
type StorageConfig={root:string,revision:string,storages:Storage[],default_storage_id:string,cache_limit_bytes:number,outbox_limit_bytes:number};
const address=(item:Storage)=>item.base_url.replace(/\/$/,'')+(item.remote_root?'/'+item.remote_root:'');
export function AttachmentStorageSettings({root,onUnsavedChange}:{root:string,onUnsavedChange?:(dirty:boolean)=>void}){
 useLocale();
 const [config,setConfig]=useState<StorageConfig>(),[editing,setEditing]=useState<Storage>(),[password,setPassword]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
 const scope=useRef(new AbortController()),editor=useRef(editing);editor.current=editing;
 const original=config?.storages.find(item=>item.storage_id===editing?.storage_id);
 const dirty=!!editing&&(!original||JSON.stringify(editing)!==JSON.stringify(original)||!!password);
 useEffect(()=>{onUnsavedChange?.(dirty);return()=>onUnsavedChange?.(false);},[dirty,onUnsavedChange]);
 useEffect(()=>{const controller=new AbortController();scope.current=controller;let polling=false;const load=async()=>{if(polling||editor.current)return;polling=true;try{const result=await api<StorageConfig>('attachments/storage?'+new URLSearchParams({root}),undefined,'GET',{signal:controller.signal,force:true});if(!controller.signal.aborted)setConfig(result);}catch(reason){if(!controller.signal.aborted)setError((reason as Error).message);}finally{polling=false;}};void load();const timer=window.setInterval(()=>void load(),15000);return()=>{controller.abort();window.clearInterval(timer);};},[root]);
 useEffect(()=>{if(!dirty)return;const leave=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue='';};window.addEventListener('beforeunload',leave);return()=>window.removeEventListener('beforeunload',leave);},[dirty]);
 const persist=async(next:StorageConfig)=>{
  const saved=await api<StorageConfig>('attachments/storage',{root,revision:next.revision,storages:next.storages.map(({storage_id,name,base_url,remote_root,upload_directory,username,connection_hint,enabled})=>({storage_id,name,base_url:base_url.trim(),remote_root,upload_directory,username,connection_hint,enabled})),default_storage_id:next.default_storage_id,cache_limit_bytes:next.cache_limit_bytes,outbox_limit_bytes:next.outbox_limit_bytes},'PUT',{signal:scope.current.signal});
  if(!scope.current.signal.aborted)setConfig(saved);return saved;
 };
 const run=async(work:()=>Promise<void>)=>{if(busy)return;setBusy(true);setError('');setMessage('');try{await work();}catch(reason){if(!scope.current.signal.aborted)setError((reason as Error).message);}finally{if(!scope.current.signal.aborted)setBusy(false);}};
 const save=()=>run(async()=>{
  if(!editing||!config)return;
  const target={...editing,base_url:editing.base_url.trim()};
  if(!target.name){try{target.name=new URL(target.base_url.replace(/^\\\\/,'smb://').replace(/\\/g,'/')).hostname;}catch{target.name=t('as.unnamed');}}
  const next={...config,storages:original?config.storages.map(item=>item.storage_id===target.storage_id?target:item):[...config.storages,target],default_storage_id:config.storages.length?config.default_storage_id:target.storage_id};
  await persist(next);
  if(password){
   if(window.leafloomDesktop)await window.leafloomDesktop.saveAttachmentCredential({storage_id:target.storage_id,password});
   else await api('attachments/storage/credentials',{entries:{[target.storage_id]:{password,revision:crypto.randomUUID()}}},'POST',{signal:scope.current.signal});
   if(scope.current.signal.aborted)return;setPassword('');
  }
  const result=await api<{state:string}>('attachments/storage/test',{root,storage_id:target.storage_id},'POST',{signal:scope.current.signal});
  const updated=await api<StorageConfig>('attachments/storage?'+new URLSearchParams({root}),undefined,'GET',{signal:scope.current.signal,force:true});
  if(scope.current.signal.aborted)return;setConfig(updated);invalidate();
  if(result.state==='ready'){setEditing(undefined);setMessage(t('as.connected'));}else setError(t('as.connectionState.'+result.state));
 });
 const edit=(item:Storage)=>{setEditing({...item});setPassword('');setError('');};
 const discard=()=>{setEditing(undefined);setPassword('');setError('');};
 return <SettingGroup id="attachment-storage" title={t('as.connections')}>
  {error&&<StatusNotice kind="error"><Diagnostic message={error}/>{!config&&<button onClick={()=>location.reload()}>{t('重试')}</button>}</StatusNotice>}{message&&<StatusNotice kind="success">{message}</StatusNotice>}
  {!config?<p>{t('attachments.checking')}</p>:<div className="attachment-storage-fields">{config.storages.map(item=><section className="attachment-storage-profile" key={item.storage_id}><div className="attachment-storage-heading"><strong>{item.name||t('as.unnamed')}</strong>{config.default_storage_id===item.storage_id&&<span className="subtle">{t('as.defaultBadge')}</span>}<details className="as-card-menu"><summary aria-label={t('as.serverActions')}>•••</summary><div><button disabled={busy} onClick={()=>edit(item)}>{t('as.edit')}</button><button disabled={busy||!item.enabled||config.default_storage_id===item.storage_id} onClick={()=>void run(async()=>{await persist({...config,default_storage_id:item.storage_id});invalidate();})}>{t('as.makeDefault')}</button><button disabled={busy||config.default_storage_id==='local'} onClick={()=>void run(async()=>{await persist({...config,default_storage_id:'local'});invalidate();})}>{t('as.useLocal')}</button><button disabled={busy} onClick={()=>void run(async()=>{await persist({...config,storages:config.storages.map(value=>value.storage_id===item.storage_id?{...value,enabled:!item.enabled}:value),default_storage_id:config.default_storage_id===item.storage_id&&!item.enabled?item.storage_id:config.default_storage_id===item.storage_id?'local':config.default_storage_id});invalidate();})}>{t(item.enabled?'as.disable':'as.enable')}</button></div></details></div><p className="as-server-address">{address(item)}</p><small role="status">{t(!item.enabled?'as.disabled':item.connection?.retry_paused?'aw.authPaused':'as.connectionState.'+(item.connection?.state||'unchecked'))}</small></section>)}{!config.storages.length&&<p className="subtle">{t('as.noServers')}</p>}<button disabled={busy} onClick={()=>edit({storage_id:crypto.randomUUID().replace(/-/g,''),name:'',base_url:'',remote_root:'',upload_directory:'Incoming',username:'',connection_hint:'direct',enabled:true,password_saved:false})}>{t('as.add')}</button></div>}
  {editing&&<Modal title={t(original?'as.edit':'as.add')} onClose={()=>{if(busy)return;if(dirty)setError(t('as.saveBeforeExit'));else discard();}} className="as-edit-dialog"><form className="pad" onSubmit={event=>{event.preventDefault();void save();}}><fieldset disabled={busy}><SettingRow label={t('as.url')} description={t('as.simpleAddressHelp')}><input required aria-label={t('as.url')} autoFocus value={address(editing)} placeholder="https://files.example.com/dav/" onChange={event=>setEditing({...editing,base_url:event.target.value,remote_root:''})}/></SettingRow><SettingRow label={t('as.username')}><input required aria-label={t('as.username')} autoComplete="username" value={editing.username} onChange={event=>setEditing({...editing,username:event.target.value})}/></SettingRow><SettingRow label={t('as.password')}><input required={!editing.password_saved} aria-label={t('as.password')} type="password" autoComplete="new-password" value={password} placeholder={editing.password_saved?t('as.keepPassword'):''} onChange={event=>setPassword(event.target.value)}/></SettingRow><details><summary>{t('as.optionalName')}</summary><input aria-label={t('as.name')} value={editing.name} onChange={event=>setEditing({...editing,name:event.target.value})}/></details>{error&&<p role="alert" className="error"><Diagnostic message={error}/></p>}<footer><button type="button" onClick={discard}>{t('取消更改')}</button><button className="primary" type="submit">{t(busy?'as.connecting':'as.saveConnect')}</button></footer></fieldset></form></Modal>}
 </SettingGroup>;
}
