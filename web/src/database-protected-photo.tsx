import React,{useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {csrf} from './api';
import {t} from './i18n';
import {Modal} from './ui';

const idle = 30 * 60 * 1000;
const endpoint = '/api/photo-vault';
const subscribers = new Set<()=>void>();
type Gallery = {folder:string,captions:boolean,title:string|null};
type PhotoSettings = {scopes:string[],galleries?:Gallery[],key_ready?:boolean,protected_captions?:boolean};
const scopes = new Map<string,Promise<PhotoSettings|null>>();
let token = '', owner = '', timer: number | undefined, pending = 0;
const queue: (()=>Promise<void>)[] = [];

const subscribe = (callback:()=>void) => {
 subscribers.add(callback);
 return () => {subscribers.delete(callback);};
};
const publish = () => subscribers.forEach(callback => callback());
const url = (root:string, suffix='', args:Record<string,string>={}) => endpoint+suffix+'?'+new URLSearchParams({root,...args});
const headers = (session=token) => ({'X-Photo-Session':session,'X-Vault-CSRF':csrf});

function session(root:string, body:object, unlocked=token) {
 return fetch(url(root),{method:'POST',headers:{...headers(unlocked),'Content-Type':'application/json'},
  body:JSON.stringify(body),keepalive:'action' in body,cache:'no-store'});
}

function lock(notify=true) {
 if(notify && token) void session(owner,{action:'lock'}).catch(()=>{});
 token='';owner='';
 window.clearTimeout(timer);
 publish();
}

function touch() {
 window.clearTimeout(timer);
 timer=window.setTimeout(()=>lock(),idle);
}

window.addEventListener('pagehide',()=>lock());

export const protectedRef = (path:string) => /\.llphoto$/i.test(path);
function usePhotoSettings(root:string) {
 const [value,setValue] = useState<{root:string,settings:PhotoSettings}|null>(null);
 useEffect(()=>{
  if(!root)return;
  let live=true;
  if(!scopes.has(root)){
   scopes.set(root,fetch(url(root),{cache:'no-store'}).then(async response=>{
    if(!response.ok) {scopes.delete(root);return null;}
    return await response.json() as PhotoSettings;
   }).catch(()=>{scopes.delete(root);return null;}));
  }
  void scopes.get(root)?.then(settings=>{if(live)setValue(settings?{root,settings}:null);});
  return ()=>{live=false;};
 },[root]);
 return value?.root===root?value.settings:null;
}

export function usePhotoScopes(root:string) {
 return usePhotoSettings(root)?.scopes;
}

export function useCaptionGallery(root:string,folder?:string|null) {
 const settings=usePhotoSettings(root);
 if(!settings)return undefined;
 if(folder===null||folder===undefined)return null;
 if(settings.galleries)return settings.galleries.find(g=>g.folder===folder&&g.captions)||null;
 return settings.protected_captions&&settings.scopes.includes(folder)?{folder,captions:true,title:'角色照片'}:null;
}

export function PhotoUnlock({root}:{root:string}) {
 const [open,setOpen]=useState(false),[password,setPassword]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const current=useSyncExternalStore(subscribe,()=>owner===root?token:'');
 const close=()=>{if(!busy){setOpen(false);setPassword('');setError('');}};
 return current?<button type="button" onClick={()=>lock()}>{t('photo.lock')}</button>:<>
  <button type="button" onClick={event=>{event.stopPropagation();setOpen(true);}}>{t('photo.unlock')}</button>
  {open&&<Modal title={t('photo.unlock')} onClose={close}><form className="pad" onSubmit={async event=>{
   event.preventDefault();setBusy(true);setError('');
   try{
    const response=await session(root,{password});
    if(!response.ok)throw new Error();
    const data=await response.json();
    if(token)lock();
    owner=root;token=data.token;touch();publish();setOpen(false);
   }catch{setError(t('photo.unlockFailed'));}
   finally{setPassword('');setBusy(false);}
  }}><label>{t('photo.password')} <input type="password" required autoFocus autoComplete="off"
   value={password} onChange={event=>setPassword(event.target.value)}/></label>
   {error&&<p role="alert">{error}</p>}<button disabled={busy}>{t('photo.unlock')}</button></form></Modal>}
 </>;
}

function drain() {
 while(pending<3&&queue.length){
  const run=queue.shift()!;
  pending++;
  void run().finally(()=>{pending--;drain();});
 }
}

export function ProtectedPhoto({root,path,fit='contain',onClick}:{root:string,path:string,fit?:string,onClick?:()=>void}) {
 const host=useRef<HTMLDivElement>(null);
 const [visible,setVisible]=useState(false),[image,setImage]=useState(''),[failed,setFailed]=useState(false);
 const current=useSyncExternalStore(subscribe,()=>owner===root?token:'');
 useEffect(()=>{
  const observer=new IntersectionObserver(([entry])=>setVisible(entry.isIntersecting));
  if(host.current)observer.observe(host.current);
  return ()=>observer.disconnect();
 },[]);
 useEffect(()=>{
  setImage('');setFailed(false);
  if(!visible||!current)return;
  const controller=new AbortController();
  let object='';
  queue.push(async()=>{
   try{
    if(controller.signal.aborted)return;
    let response:Response|undefined;
    for(let attempt=0;attempt<3;attempt++){
     response=await fetch(url(root,'/image',{path}),{headers:headers(current),signal:controller.signal,cache:'no-store'});
     if(response.status!==429)break;
     await new Promise(resolve=>setTimeout(resolve,150*(attempt+1)));
    }
    if(response?.status===423&&token===current)lock(false);
    if(!response?.ok)throw new Error();
    const blob=await response.blob();
    if(controller.signal.aborted)return;
    touch();object=URL.createObjectURL(blob);setImage(object);
   }catch{if(!controller.signal.aborted)setFailed(true);}
  });
  drain();
  return ()=>{controller.abort();if(object)URL.revokeObjectURL(object);};
 },[root,path,visible,current]);
 return <div ref={host} className="db-protected-photo">
  {!current?<PhotoUnlock root={root}/>:image?<img src={image} alt="" style={{objectFit:fit as 'cover'|'contain'}} onClick={onClick}/>
   :failed?<span>{t('photo.unavailable')}</span>:null}
 </div>;
}

export function useProtectedPhotoSession(root:string) {
 return useSyncExternalStore(subscribe,()=>owner===root?token:'');
}

type Caption = {caption:string,revision:string};

async function readCaption(root:string,source:string,current:string,signal?:AbortSignal):Promise<Caption> {
 const response=await fetch(url(root,'/caption',{source}),{headers:headers(current),cache:'no-store',signal});
 if(response.status===423&&token===current)lock(false);
 if(!response.ok)throw new Error(t('photo.captionUnavailable'));
 touch();
 return response.json();
}

export async function saveProtectedCaption(root:string,source:string,caption:string,revision?:string) {
 const current=owner===root?token:'';
 if(!current)throw new Error(t('photo.unlock'));
 revision=revision??(await readCaption(root,source,current)).revision;
 const response=await fetch(url(root,'/caption',{source}),{method:'POST',cache:'no-store',
  headers:{...headers(current),'Content-Type':'application/json'},body:JSON.stringify({caption,revision})});
 if(response.status===423&&token===current)lock(false);
 if(!response.ok)throw new Error(t('photo.captionUnavailable'));
 touch();
 return (await response.json()).revision as string;
}

export function ProtectedCaption({root,source,revision,editable=false,onSaved}:{
 root:string,source:string,revision:string,editable?:boolean,onSaved?:(revision:string)=>void,
}) {
 const current=useProtectedPhotoSession(root);
 const host=useRef<HTMLElement|null>(null);
 const [visible,setVisible]=useState(false),[value,setValue]=useState<Caption>(),[draft,setDraft]=useState<string>(),
  [error,setError]=useState(''),[saving,setSaving]=useState(false);
 useEffect(()=>{
  const observer=new IntersectionObserver(([entry])=>setVisible(entry.isIntersecting));
  if(host.current)observer.observe(host.current);
  return ()=>observer.disconnect();
 },[]);
 useEffect(()=>{
  setValue(undefined);setDraft(undefined);setError('');
  if(!current||!visible)return;
  const controller=new AbortController();
  queue.push(async()=>{
   if(controller.signal.aborted)return;
   try{
    const loaded=await readCaption(root,source,current,controller.signal);
    if(!controller.signal.aborted)setValue(loaded);
   }catch{if(!controller.signal.aborted)setError(t('photo.captionUnavailable'));}
  });
  drain();
  return ()=>controller.abort();
 },[root,source,revision,current,visible]);
 const Container=editable?'div':'span';
 return <Container ref={element=>{host.current=element;}} className="db-protected-caption">{current&&value?value.caption||t('photo.protectedCaption'):t('photo.protectedCaption')}
  {editable&&!current&&<PhotoUnlock root={root}/>}
  {editable&&current&&value&&draft===undefined&&<button type="button" onClick={()=>setDraft(value.caption)}>{t('photo.editCaption')}</button>}
  {editable&&current&&value&&draft!==undefined&&<form onSubmit={async event=>{
   event.preventDefault();setSaving(true);setError('');
   try{
    const next=await saveProtectedCaption(root,source,draft,value.revision);
    if(token===current){setValue({caption:draft.trim(),revision:next});setDraft(undefined);onSaved?.(next);}
   }catch(e){setError((e as Error).message);}finally{setSaving(false);}
  }}><label>{t('photo.caption')} <input maxLength={160} required autoComplete="off" value={draft} onChange={event=>setDraft(event.target.value)}/></label>
   <button disabled={saving}>{t('保存')}</button><button type="button" onClick={()=>setDraft(undefined)}>{t('取消')}</button></form>}
  {editable&&current&&error&&<span role="alert">{error}</span>}
 </Container>;
}

export async function uploadProtectedPhoto(root:string, source:string, file:File) {
 const response=await fetch(url(root,'/image',{source}),{method:'POST',headers:headers(),body:file,cache:'no-store'});
 if(response.status===423)lock(false);
 if(!response.ok)throw new Error(t('photo.importFailed'));
 touch();
 return (await response.json()).path as string;
}
