import React,{useEffect,useState} from 'react';
import {api,media} from './api';
import {t} from './i18n';
import {Modal} from './ui';
import {VideoPlayer} from './media';
import {csrf,invalidate} from './api';
import {PhotoUnlock,ProtectedPhoto,protectedRef,uploadProtectedPhoto,usePhotoScopes,useProtectedPhotoSession} from './database-protected-photo';
export const imageRef=(value:string)=>/\.(png|jpe?g|webp|gif|avif|svg|llphoto)$/i.test(refPath(value));
export const videoRef=(value:string)=>/\.(mp4|webm|mov|m4v)$/i.test(refPath(value));
export function refPath(value:string){return value.replace(/^!?\[\[/,'').replace(/\]\]$/,'').split('|')[0];}
export function ResolvedMedia({reference,source,root,fit='cover',onClick}:{reference:string,source:string,root:string,fit?:string,onClick?:()=>void}){
 const target=refPath(reference);
 const [path,setPath]=useState(''),[failed,setFailed]=useState(false);
 useEffect(()=>{const controller=new AbortController();setPath('');setFailed(false);if(protectedRef(target))return;void api<any>('resolve?'+new URLSearchParams({target,source}),undefined,'GET',{signal:controller.signal}).then(v=>{if(!controller.signal.aborted)setPath(v.candidates.length===1?v.candidates[0]:target);}).catch(()=>{if(!controller.signal.aborted)setPath(target);});return()=>controller.abort();},[reference,source,root]);
 if(protectedRef(target))return <ProtectedPhoto root={root} path={target} fit={fit} onClick={onClick}/>;
 return failed||!path?<div className="db-media-placeholder">{t('db.noCover')}</div>:<img src={media(path,false,root)} style={{objectFit:fit as 'cover'|'contain'}} loading="lazy" alt="" onError={()=>setFailed(true)} onClick={onClick}/>;
}
export function AttachmentPicker({root,value,onSave,onClose,source=''}:{root:string,source?:string,value:string[],onSave:(values:string[])=>Promise<void>,onClose:()=>void}){
 const [query,setQuery]=useState(''),[items,setItems]=useState<any[]>([]),[selected,setSelected]=useState(value),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const scopes=usePhotoScopes(root),current=useProtectedPhotoSession(root);
 const folder=source.split('/').slice(0,-1).join('/');
 const protectedCover=Boolean(source&&(scopes?.includes(folder)||value.some(value=>protectedRef(refPath(value)))));
 useEffect(()=>{if(protectedCover)return;const c=new AbortController();const timer=setTimeout(()=>void api<any>('attachments?'+new URLSearchParams({root,query,limit:'100'}),undefined,'GET',{signal:c.signal}).then(v=>setItems(v.items||v.results||[])).catch(e=>{if(e.name!=='AbortError')setError(e.message);}),200);return()=>{clearTimeout(timer);c.abort();};},[query,root,protectedCover]);
 if(source&&!scopes)return <Modal title={t('db.attachments')} onClose={onClose}><p>{t('photo.unavailable')}</p></Modal>;
 if(protectedCover)return <Modal title={t('db.attachments')} onClose={()=>{if(!busy)onClose();}}><div className="pad db-picker">
  {!current?<PhotoUnlock root={root}/>:<label>{t('db.upload')} <input type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={async event=>{
   const file=event.target.files?.[0];if(!file)return;
   setBusy(true);setError('');
   try{const path=await uploadProtectedPhoto(root,source,file);setSelected(['[['+path+']]']);invalidate({paths:[path]});}
   catch(cause){setError((cause as Error).message);}finally{setBusy(false);}
  }}/></label>}
  {error&&<p role="alert">{error}</p>}
  <button disabled={busy||!current||!selected.length} onClick={async()=>{setBusy(true);try{await onSave(selected);onClose();}catch(cause){setError((cause as Error).message);}finally{setBusy(false);}}}>{t('保存')}</button>
 </div></Modal>;
 return <Modal title={t('db.attachments')} onClose={()=>{if(!busy)onClose();}}><div className="pad db-picker"><input aria-label={t('db.searchAttachments')} placeholder={t('db.searchAttachments')} value={query} onChange={e=>setQuery(e.target.value)}/><label>{t('db.upload')}<input type="file" multiple disabled={busy} onChange={async e=>{const files=Array.from(e.target.files||[]);setBusy(true);setError('');try{for(const file of files){const response=await fetch('/api/upload?'+new URLSearchParams({root,name:file.name,central:'true',unique:'true'}),{method:'POST',headers:{'X-Vault-CSRF':csrf},body:file});const result=await response.json();if(!response.ok)throw new Error(result.error);setSelected(old=>[...old,'[['+result.path+']]']);invalidate({paths:[result.path]});}}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}/></label><div className="db-picked">{selected.map(v=><button key={v} onClick={()=>setSelected(selected.filter(x=>x!==v))}>{refPath(v)} ×</button>)}</div><div className="db-picker-results">{items.map(item=>{const ref='[['+item.path+']]';return <label key={item.path}><input type="checkbox" checked={selected.includes(ref)} onChange={e=>setSelected(e.target.checked?[...selected,ref]:selected.filter(x=>x!==ref))}/>{item.name||item.path}</label>;})}</div>{error&&<p className="error">{t(error)}</p>}<button disabled={busy} onClick={async()=>{setBusy(true);try{await onSave(selected);onClose();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>{t('保存')}</button></div></Modal>;
}
export function RecordVideo({reference,source,root,onClose}:{reference:string,source:string,root:string,onClose:()=>void}){
 const [path,setPath]=useState('');useEffect(()=>{const c=new AbortController();void api<any>('resolve?'+new URLSearchParams({target:refPath(reference),source}),undefined,'GET',{signal:c.signal}).then(v=>setPath(v.candidates[0]||refPath(reference))).catch(()=>setPath(refPath(reference)));return()=>c.abort();},[reference,source]);
 return <Modal title={t('db.video')} onClose={onClose} wide>{path&&<VideoPlayer path={path} root={root}/>}</Modal>;
}
