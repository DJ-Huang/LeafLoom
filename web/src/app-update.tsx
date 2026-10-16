import React,{useEffect,useState} from 'react';
import {t,useLocale} from './i18n';
import {SettingRow,StatusNotice} from './settings-ui';

export type UpdateInfo={current:string,latest:string,phase:'idle'|'checking'|'current'|'available'|'development'|'downloading'|'verifying'|'ready'|'installing'|'error',received:number,total:number,error:string};
const bytes=(value:number)=>`${(value/1024/1024).toFixed(1)} MB`;
export function AppUpdate({current,platform}:{current:string,platform:string}){
 useLocale();
 const [update,setUpdate]=useState<UpdateInfo>(),[working,setWorking]=useState(false),[error,setError]=useState('');
 useEffect(()=>{
  let active=true,timer:ReturnType<typeof setTimeout>;
  const poll=async()=>{
   try {const value=await window.leafloomDesktop!.updateStatus();if(active){setUpdate(value);setError('');}}
   catch {if(active)setError(t('update.error.connection'));}
   finally {if(active)timer=setTimeout(()=>void poll(),500);}
  };
  void poll();return()=>{active=false;clearTimeout(timer);};
 },[]);
 const run=async(action:()=>Promise<UpdateInfo>)=>{
  setWorking(true);setError('');
  try {setUpdate(await action());}catch{setError(t('update.error.connection'));}finally{setWorking(false);}
 };
 const phase=update?.phase||'idle', busy=working||['checking','downloading','verifying','installing'].includes(phase);
 const progress=update?.total?Math.min(100,100*update.received/update.total):0;
 return <div id="setting-app-update" className="app-update" tabIndex={-1}>
  <SettingRow label={t('update.title')} description={t('update.current',{version:update?.current||current||'…'})}>
   <button disabled={busy||!update} onClick={()=>void run(()=>window.leafloomDesktop!.checkUpdate())}>{t(phase==='checking'?'update.checking':'update.check')}</button>
  </SettingRow>
  <p className="setting-detail">{update?.latest?t('update.latest',{version:update.latest}):t('update.unchecked')}</p>
  {phase==='current'&&<StatusNotice kind="success">{t('update.currentStatus')}</StatusNotice>}
  {phase==='development'&&<StatusNotice>{t('update.development')}</StatusNotice>}
  {(phase==='available'||phase==='ready'||(phase==='error'&&!!update?.total))&&<div className="update-actions"><button className="primary" disabled={busy} onClick={()=>void run(()=>phase==='ready'?window.leafloomDesktop!.installUpdate():window.leafloomDesktop!.downloadUpdate())}>{t(phase==='ready'?'update.install':'update.download')}</button><span>{t(platform==='darwin'?'update.macHelp':'update.windowsHelp')}</span></div>}
  {phase==='downloading'&&<div className="update-progress"><label htmlFor="app-update-progress">{t('update.progress',{percent:Math.floor(progress),received:bytes(update!.received),total:bytes(update!.total)})}</label><progress id="app-update-progress" max={100} value={progress}/></div>}
  {(phase==='verifying'||phase==='installing')&&<StatusNotice kind="busy">{t(phase==='verifying'?'update.verifying':'update.installing')}</StatusNotice>}
  {(error||update?.error)&&<StatusNotice kind="error">{error||t(update!.error)}</StatusNotice>}
 </div>;
}
