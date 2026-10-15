import React,{useEffect,useRef,useState} from 'react';
import {t,useLocale} from './i18n';
import {TunnelInfo} from './desktop';
import {SettingGroup,SettingRow,StatusNotice} from './settings-ui';

export function TunnelSettings(){
 useLocale();
 const desktop=window.leafloomDesktop;
 const [status,setStatus]=useState<TunnelInfo>();
 const [tunnelId,setTunnelId]=useState(''),[appKey,setAppKey]=useState(''),[enabled,setEnabled]=useState(true);
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 const initialized=useRef(false);
 useEffect(()=>{
  if(!desktop)return;
  let live=true,pending=false;
  const poll=async()=>{
   if(pending)return;pending=true;
   try{const next=await desktop.tunnelStatus();if(live){setStatus(next);if(!initialized.current){initialized.current=true;setTunnelId(next.tunnelId);setEnabled(next.tunnelId?next.enabled:true);}}}
   catch{if(live)setError('tunnel.error.process');}finally{pending=false;}
  };
  void poll();const timer=setInterval(()=>void poll(),2000);
  return()=>{live=false;clearInterval(timer);};
 },[desktop]);
 async function run(action:()=>Promise<TunnelInfo>){
  setBusy(true);setError('');
  try{const next=await action();setStatus(next);setTunnelId(next.tunnelId);setEnabled(next.enabled);setAppKey('');}
  catch(e){setError(String(e).match(/tunnel\.error\.[a-z]+/)?.[0]||'tunnel.error.storage');}
  finally{setBusy(false);}
 }
 if(!desktop)return <StatusNotice>{t('tunnel.desktopOnly')}</StatusNotice>;
 const dirty=!!status&&(tunnelId!==status.tunnelId||enabled!==status.enabled||!!appKey);
 return <>
  <SettingGroup id="tunnel" title={t('tunnel.title')} description={t('tunnel.description')}>
   <SettingRow label={t('tunnel.id')}><input aria-label={t('tunnel.id')} value={tunnelId} autoComplete="off" spellCheck={false} disabled={busy} onChange={e=>setTunnelId(e.target.value)}/></SettingRow>
   <SettingRow label={t('tunnel.key')} description={t('tunnel.keyHelp')}><input type="password" aria-label={t('tunnel.key')} autoComplete="new-password" spellCheck={false} placeholder={t(status?.keySaved?'tunnel.keySaved':'tunnel.keyPlaceholder')} disabled={busy} value={appKey} onChange={e=>setAppKey(e.target.value)}/></SettingRow>
   <SettingRow label={t('tunnel.auto')} description={t('tunnel.lifecycle')}><input type="checkbox" aria-label={t('tunnel.auto')} disabled={busy} checked={enabled} onChange={e=>setEnabled(e.target.checked)}/></SettingRow>
   <SettingRow label={t('tunnel.status')} description={t('tunnel.statusHelp')}><span role="status">{t('tunnel.state.'+(status?.state||'waiting'))}</span></SettingRow>
   {(error||status?.error)&&<StatusNotice kind="error">{t(error||status!.error)}</StatusNotice>}
   <div className="setting-actions">
    <button className="primary" disabled={busy||!status||!tunnelId.trim()||(enabled&&!appKey.trim()&&!status.keySaved)} onClick={()=>void run(()=>desktop.saveTunnel({tunnelId,enabled,...(appKey.trim()?{appKey:appKey.trim()}:{})}))}>{t(enabled?'tunnel.saveConnect':'tunnel.save')}</button>
    <button disabled={busy||dirty||!status?.keySaved} onClick={()=>void run(()=>desktop.reconnectTunnel())}>{t('tunnel.reconnect')}</button>
    <button disabled={busy||!status?.enabled} onClick={()=>void run(()=>desktop.disconnectTunnel())}>{t('tunnel.disconnect')}</button>
    <button disabled={busy||(!status?.keySaved&&!status?.tunnelId)} onClick={()=>void run(()=>desktop.clearTunnel())}>{t('tunnel.clear')}</button>
   </div>
   {dirty&&<p className="setting-detail" role="status">{t('tunnel.unsaved')}</p>}
  </SettingGroup>
  <SettingGroup title={t('tunnel.firstUse')} description={t('tunnel.setup')}>
   <p className="setting-detail">{t('tunnel.privacy')}</p>
   <div className="setting-actions">
    <button onClick={()=>void desktop.openExternal('https://chatgpt.com/').catch(()=>setError('tunnel.error.link'))}>{t('tunnel.openChatGPT')}</button>
    <button onClick={()=>void desktop.openExternal('https://developers.openai.com/api/docs/guides/secure-mcp-tunnels').catch(()=>setError('tunnel.error.link'))}>{t('tunnel.guide')}</button>
    <button onClick={()=>void desktop.openLogs().catch(()=>setError('tunnel.error.link'))}>{t('打开日志文件夹')}</button>
   </div>
  </SettingGroup>
 </>;
}
