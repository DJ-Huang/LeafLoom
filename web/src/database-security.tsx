import React,{createContext,useContext,useEffect,useMemo,useRef,useState,useSyncExternalStore} from 'react';
import {LockKeyhole,ShieldCheck,Table2} from 'lucide-react';
import {api,clearRequestCache,csrf,invalidate,Note} from './api';
import {hasDatabaseDrafts,retireDatabaseDocuments} from './document-state';
import {t} from './i18n';
import {Modal} from './ui';

const route='/api/database-security';
const idle=30*60*1000;
const sessions=new Map<string,{token:string,timer:number,root:string,path:string}>();
const listeners=new Set<()=>void>();
const subscribe=(listener:()=>void)=>{listeners.add(listener);return()=>{listeners.delete(listener);};};
const publish=()=>listeners.forEach(listener=>listener());
const sessionKey=(root:string,path:string)=>JSON.stringify([root,path]);
const endpoint=(root:string,path:string,action:string)=>
 route+(action?'/'+action:'')+'?'+new URLSearchParams({root,path});

async function call(root:string,path:string,action:string,options:{body?:unknown,file?:File,signal?:AbortSignal,token?:string,post?:boolean}={}){
 const {body,file,signal,token,post}=options;
 const response=await fetch(endpoint(root,path,action),{
  method:post||body!==undefined||file?'POST':'GET',cache:'no-store',signal,
  headers:{'X-Vault-CSRF':csrf,...(token?{'X-Database-Session':token}:{}),...(body!==undefined?{'Content-Type':'application/json'}:{}),...(file?{'X-Database-Filename':encodeURIComponent(file.name)}:{})},
  body:file??(body===undefined?undefined:JSON.stringify(body)),
 });
 if(!response.ok){
  if(response.status===423&&token&&sessions.get(sessionKey(root,path))?.token===token)forget(root,path,false);
  const result=await response.json().catch(()=>({}));
  throw new Error(result.error||'db.securityInvalid');
 }
 if(token&&sessions.get(sessionKey(root,path))?.token===token)remember(root,path,token);
 return response;
}

function forget(root:string,path:string,notify=true){
 const key=sessionKey(root,path),session=sessions.get(key);
 if(!session)return;
 clearTimeout(session.timer);sessions.delete(key);publish();
 if(notify)void fetch(endpoint(root,path,'lock'),{
  method:'POST',headers:{'X-Vault-CSRF':csrf,'X-Database-Session':session.token},keepalive:true,
 }).catch(()=>{});
}

function remember(root:string,path:string,token:string){
 const key=sessionKey(root,path),prior=sessions.get(key);
 clearTimeout(prior?.timer);
 sessions.set(key,{root,path,token,timer:window.setTimeout(()=>forget(root,path),idle)});
 if(prior?.token!==token)publish();
}

window.addEventListener('pagehide',()=>{for(const session of sessions.values())forget(session.root,session.path);});

type SecureDatabase={
 request:typeof api;
 record:(source:string,signal?:AbortSignal)=>Promise<Note>;
 save:(source:string,text:string,revision:string)=>Promise<Note>;
 asset:(target:string,source:string,signal?:AbortSignal)=>Promise<Blob>;
 upload:(file:File)=>Promise<{path:string}>;
 hasDraft:(path?:string)=>boolean;
 setDraft:(path:string,changed:boolean)=>void;
 lock:()=>boolean;
};
const SecurityContext=createContext<SecureDatabase|null>(null);
export const useSecureDatabase=()=>useContext(SecurityContext);
export function useDatabaseRequest(){return useSecureDatabase()?.request||api;}

function makeSession(root:string,path:string,token:string,drafts:Set<string>):SecureDatabase{
 const ask=(action:string,options:Parameters<typeof call>[3]={})=>call(root,path,action,{...options,token});
 const json=async(action:string,options:Parameters<typeof call>[3]={})=>(await ask(action,options)).json();
 return {
  request:(url,body,_method,options)=>json(url.split('?')[0].split('/')[1],{body,signal:options?.signal}),
  record:(source,signal)=>json('record/read',{body:{source},signal}),
  save:(source,text,revision)=>json('record',{body:{source,text,revision}}),
  asset:async(target,source,signal)=>(await ask('asset/read',{body:{target,source},signal})).blob(),
  upload:file=>json('asset',{file}),
  hasDraft:source=>source?drafts.has(source):drafts.size>0,
  setDraft:(source,dirty)=>{if(dirty)drafts.add(source);else drafts.delete(source);},
  lock:()=>{if(drafts.size)return false;forget(root,path);return true;},
 };
}

export function DatabaseSecurityBoundary({path,embedded,children}:{path:string,embedded:boolean,children:(status:{root:string,onConverted:()=>void})=>React.ReactNode}){
 const [state,setState]=useState<{root:string,encrypted:boolean}>(),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 const root=state?.root||'',drafts=useRef(new Set<string>());
 const token=useSyncExternalStore(subscribe,()=>sessions.get(sessionKey(root,path))?.token||'');
 useEffect(()=>{
  const controller=new AbortController();
  const load=async()=>{
   try{
    const {config}=await api('session',undefined,'GET',{signal:controller.signal});
    const {encrypted}=await (await call(config.root,path,'',{signal:controller.signal})).json();
    if(controller.signal.aborted)return;
    setState({root:config.root,encrypted});setError('');
   }catch(error){if(!controller.signal.aborted)setError((error as Error).message);}
  };
  void load();
  const refresh=(event:Event)=>{
   const change=(event as CustomEvent).detail;
   if(!change?.root||change.root!==root||change.paths?.includes(path))void load();
  };
  window.addEventListener('vault-data-changed',refresh);
  return()=>{controller.abort();window.removeEventListener('vault-data-changed',refresh);};
 },[path,retry,root]);
 const secure=useMemo(()=>token?makeSession(root,path,token,drafts.current):null,[root,path,token]);
 useEffect(()=>{if(!token)drafts.current.clear();},[token]);
 if(!state)return <div className="pad">{error?<><p role="alert">{t(error)}</p><button onClick={()=>setRetry(value=>value+1)}>{t('db.reload')}</button></>:t('正在加载视图…')}</div>;
 if(state.encrypted&&!secure)return <DatabaseUnlock root={root} path={path} embedded={embedded}/>;
 const converted=()=>setState({...state,encrypted:true});
 return <SecurityContext.Provider value={state.encrypted?secure:null} key={state.encrypted?token:'plain'}>{children({root,onConverted:converted})}</SecurityContext.Provider>;
}

function DatabaseUnlock({root,path,embedded}:{root:string,path:string,embedded:boolean}){
 const [password,setPassword]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 return <div className={'database'+(embedded?' db-embedded':'')} data-database={path}>
  <header className="db-header"><div className="db-page-mark"><Table2 size={30}/></div><h1>{path.split('/').pop()?.replace(/\.base$/i,'')}</h1></header>
  <section className="db-locked-panel" aria-label={t('db.securityLocked')}>
   <div className="db-lock-icon"><LockKeyhole size={24} strokeWidth={1.6}/></div>
   <h2>{t('db.securityLocked')}</h2>
   <p>{t('db.securityUnlockHint')}</p>
   <form onSubmit={async event=>{
    event.preventDefault();setBusy(true);setError('');
    try{
     const {token}=await (await call(root,path,'unlock',{body:{password}})).json();
     remember(root,path,token);
    }catch(error){setError((error as Error).message);}
    finally{setPassword('');setBusy(false);}
   }}>
    <label className="setting-field">{t('db.securityPassphrase')}<input type="password" required autoComplete="current-password" value={password} onChange={event=>setPassword(event.target.value)}/></label>
    {error&&<p className="error" role="alert">{t(error)}</p>}
    <button className="primary" disabled={busy}>{t(busy?'处理中…':'db.securityUnlock')}</button>
   </form>
  </section>
 </div>;
}

type Preview={revision:string,records:number,attachments:number,shared:number,legacy:boolean};
export function DatabaseSecurityButton({root,path,folder,busy,onConverted,notify}:{root:string,path:string,folder?:string|null,busy:boolean,onConverted:()=>void,notify:(message:string)=>void}){
 const secure=useSecureDatabase(),[open,setOpen]=useState(false),[preview,setPreview]=useState<Preview>(),[error,setError]=useState(''),
  [waiting,setWaiting]=useState(false),[password,setPassword]=useState(''),[confirm,setConfirm]=useState(''),[oldPassword,setOldPassword]=useState('');
 const drafts=()=>Boolean(folder&&hasDatabaseDrafts(root,folder,path));
 const begin=async()=>{
  if(drafts()){notify(t('db.securityDrafts'));return;}
  setOpen(true);setWaiting(true);setError('');setPreview(undefined);
  try{setPreview(await (await call(root,path,'preview',{post:true})).json());}
  catch(error){setError((error as Error).message);}
  finally{setWaiting(false);}
 };
 const close=()=>{if(!waiting){setOpen(false);setPassword('');setConfirm('');setOldPassword('');}};
 if(secure)return <button type="button" className="db-tool db-security-control" disabled={busy} onClick={()=>{
  if(!secure.lock())notify(t('db.securityDrafts'));
 }}><LockKeyhole size={14}/>{t('db.securityLock')}</button>;
 return <>
  {folder&&<button type="button" className="db-tool db-security-control" disabled={busy} onClick={()=>void begin()}><LockKeyhole size={14}/>{t('db.securityEnable')}</button>}
  {open&&<Modal className="db-security-modal" title={t('db.securityEnable')} icon={<ShieldCheck size={19}/>} onClose={close}>
   <form onSubmit={async event=>{
    event.preventDefault();if(!preview||waiting)return;
    if(password!==confirm){setError('db.securityMismatch');return;}
    if(drafts()){setError('db.securityDrafts');return;}
    setWaiting(true);setError('');
    try{
     await call(root,path,'convert',{body:{revision:preview.revision,password,old_password:oldPassword,confirm:true}});
     retireDatabaseDocuments(root,folder!,path);
     clearRequestCache();
     onConverted();invalidate();
    }catch(error){setError((error as Error).message);}
    finally{setWaiting(false);setPassword('');setConfirm('');setOldPassword('');}
   }}>
    <div className="pad db-security-fields">
     <p>{t('db.securityConvertHint')}</p>
     {waiting&&!preview&&<p role="status">{t('db.securityChecking')}</p>}
     {preview&&<>
      <div className="db-security-summary"><span>{t('db.securityRecords',{count:preview.records})}</span><span>{t('db.securityAttachments',{count:preview.attachments})}</span></div>
      {preview.shared>0&&<p>{t('db.securitySharedAssets')}</p>}
      {preview.legacy&&<label className="setting-field">{t('db.securityOldPassphrase')}<input type="password" required autoComplete="current-password" value={oldPassword} onChange={event=>setOldPassword(event.target.value)}/></label>}
      <label className="setting-field">{t('db.securityPassphrase')}<input type="password" required minLength={12} autoComplete="new-password" value={password} onChange={event=>setPassword(event.target.value)}/></label>
      <label className="setting-field">{t('db.securityConfirmPassphrase')}<input type="password" required autoComplete="new-password" value={confirm} onChange={event=>setConfirm(event.target.value)}/></label>
      <p className="subtle">{t('db.securityPasswordHint')}</p>
     </>}
     {error&&<p role="alert" className="error">{t(error)}</p>}
    </div>
    <footer className="modal-footer"><button type="button" disabled={waiting} onClick={close}>{t('取消')}</button>{preview&&<button className="primary" disabled={waiting}>{t(waiting?'处理中…':'db.securityConvert')}</button>}</footer>
   </form>
  </Modal>}
 </>;
}

export async function createSecureDatabase(root:string,path:string,password:string,preset:string){
 const {token}=await (await call(root,path,'create',{body:{password,preset}})).json();
 remember(root,path,token);
}

export function PrivateRecordBody({path,revision,onSaved}:{path:string,revision:string,onSaved:()=>void}){
 const secure=useSecureDatabase()!;
 const [note,setNote]=useState<Note>(),[text,setText]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const dirty=Boolean(note&&text!==note.text);
 useEffect(()=>{
  const controller=new AbortController();
  if(!secure.hasDraft(path))void secure.record(path,controller.signal).then(value=>{
   if(!controller.signal.aborted){setNote(value);setText(value.text);setError('');}
  }).catch(error=>{if(!controller.signal.aborted)setError((error as Error).message);});
  return()=>controller.abort();
 },[secure,path,revision]);
 useEffect(()=>()=>secure.setDraft(path,false),[secure,path]);
 return <form className="db-private-record" onSubmit={async event=>{
  event.preventDefault();if(!note||busy)return;
  setBusy(true);setError('');
  try{const saved=await secure.save(path,text,note.etag);setNote(saved);setText(saved.text);secure.setDraft(path,false);onSaved();}
  catch(error){setError((error as Error).message);}
  finally{setBusy(false);}
 }}>
  {note&&<><label className="setting-field">{t('db.securityRecordBody')}<textarea rows={10} value={text} onChange={event=>{setText(event.target.value);secure.setDraft(path,event.target.value!==note.text);}}/></label>
   {dirty&&<div className="db-private-record-actions"><button type="button" disabled={busy} onClick={()=>{setText(note.text);secure.setDraft(path,false);}}>{t('db.securityDiscard')}</button><button className="primary" disabled={busy}>{t('保存')}</button></div>}</>}
  {error&&<p className="error" role="alert">{t(error)}</p>}
 </form>;
}
