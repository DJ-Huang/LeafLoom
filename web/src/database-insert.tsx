import React,{useEffect,useState} from 'react';
import {api} from './api';
import {t} from './i18n';
import {Modal} from './ui';
import {BaseConfig} from './database-model';
export function DatabaseInsert({onInsert,onClose}:{onInsert:(reference:string)=>void,onClose:()=>void}){
 const [items,setItems]=useState<{path:string,title:string}[]>([]),[cursor,setCursor]=useState(''),[path,setPath]=useState(''),[config,setConfig]=useState<BaseConfig>(),[view,setView]=useState(''),[error,setError]=useState('');
 const load=async(next='')=>{try{const result=await api<any>('bases?'+new URLSearchParams({cursor:next}));setItems(old=>next?[...old,...result.results]:result.results);setCursor(result.next_cursor||'');}catch(e){setError((e as Error).message);}};
 useEffect(()=>{void load();},[]);
 useEffect(()=>{setConfig(undefined);setView('');if(!path)return;const c=new AbortController();void api<BaseConfig>('bases/config?path='+encodeURIComponent(path),undefined,'GET',{signal:c.signal}).then(setConfig).catch(e=>{if(e.name!=='AbortError')setError(e.message);});return()=>c.abort();},[path]);
 return <Modal title={t('db.insert')} onClose={onClose}><div className="pad db-insert"><label>{t('db.databaseName')}<select value={path} onChange={e=>setPath(e.target.value)}><option value="">—</option>{items.map(i=><option key={i.path} value={i.path}>{i.path}</option>)}</select></label>{cursor&&<button onClick={()=>void load(cursor)}>{t('db.loadMore')}</button>}{config&&<label>{t('db.view')}<select value={view} onChange={e=>setView(e.target.value)}><option value="">{t('db.defaultView')}</option>{config.views.map(v=><option key={v.id} value={v.id}>{v.name}</option>)}</select></label>}{error&&<p className="error">{t(error)}</p>}<button disabled={!config} onClick={()=>{onInsert('![['+path+(view?'#view='+view:'')+']]');}}>{t('db.insert')}</button></div></Modal>;
}
