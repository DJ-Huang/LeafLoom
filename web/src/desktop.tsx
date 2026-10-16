import React,{useEffect,useState} from 'react';
import {api} from './api';
import {t,useLocale} from './i18n';
import {SettingGroup,SettingRow,StatusNotice} from './settings-ui';
import {AppUpdate,UpdateInfo} from './app-update';

export type DesktopInfo={version:string,platform:string,openAtLogin:boolean,error?:string};
export type TunnelInfo={tunnelId:string,enabled:boolean,keySaved:boolean,state:string,error:string};
declare global {
 interface Window {
  leafloomPrepareQuit?:()=>Promise<void>;
  leafloomDesktop?:{
   appInfo:()=>Promise<DesktopInfo>;
   updateStatus:()=>Promise<UpdateInfo>;
   checkUpdate:()=>Promise<UpdateInfo>;
   downloadUpdate:()=>Promise<UpdateInfo>;
   installUpdate:()=>Promise<UpdateInfo>;
   tunnelStatus:()=>Promise<TunnelInfo>;
   saveTunnel:(value:{tunnelId:string,appKey?:string,enabled:boolean})=>Promise<TunnelInfo>;
   reconnectTunnel:()=>Promise<TunnelInfo>;
   disconnectTunnel:()=>Promise<TunnelInfo>;
   clearTunnel:()=>Promise<TunnelInfo>;
   chooseDirectory:()=>Promise<{path?:string,cancelled?:boolean}>;
   revealFile:(path:string)=>Promise<void>;
   openExternal:(url:string)=>Promise<void>;
   setOpenAtLogin:(enabled:boolean)=>Promise<{openAtLogin:boolean}>;
   openLogs:()=>Promise<void>;
   retry:()=>Promise<void>;
   quit:()=>Promise<void>;
  };
 }
}
export async function chooseDirectory(){
 const result=await (window.leafloomDesktop?.chooseDirectory()||api<{path?:string}>('choose-directory',{}));
 return {...result,path:result.path||''};
}

export function DesktopSettings(){
 useLocale();
 const [info,setInfo]=useState<DesktopInfo>(),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 useEffect(()=>{void window.leafloomDesktop?.appInfo().then(setInfo).catch(e=>setError(e.message));},[]);
 if(!window.leafloomDesktop)return null;
 return <SettingGroup title={t('桌面 App')}><SettingRow label={t('登录时启动')} description={t('关闭窗口后留在托盘；退出会停止本地服务。')}><input type="checkbox" aria-label={t('登录时启动')} disabled={!info||busy} checked={info?.openAtLogin||false} onChange={event=>{setBusy(true);setError('');void window.leafloomDesktop!.setOpenAtLogin(event.target.checked).then(value=>setInfo(info=>({...info!,...value}))).catch(e=>setError(e.message)).finally(()=>setBusy(false));}}/></SettingRow><AppUpdate current={info?.version||''} platform={info?.platform||''}/><SettingRow label={t('打开日志文件夹')}><button onClick={()=>void window.leafloomDesktop!.openLogs().catch(e=>setError(e.message))}>{t('打开日志文件夹')}</button></SettingRow>{error&&<StatusNotice kind="error">{error}</StatusNotice>}</SettingGroup>;
}
