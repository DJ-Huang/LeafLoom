import React,{useEffect,useRef,useState} from 'react';
import {api} from './api';
import {Diagnostic,t,useLocale} from './i18n';
import {SettingGroup,SettingRow,StatusNotice} from './settings-ui';

type Access={enabled:boolean,write:boolean};
type AccessState={local:Access,tunnel:Access,token?:string};

export function McpSettings({port}:{port:number}){
 useLocale();
 const [value,setValue]=useState<AccessState>(),[token,setToken]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[copied,setCopied]=useState(false);
 const alive=useRef(true);
 useEffect(()=>{
  alive.current=true;const controller=new AbortController();
  api<AccessState>('mcp-access',undefined,undefined,{force:true,signal:controller.signal}).then(setValue).catch(e=>{if(!controller.signal.aborted)setError(e.message);});
  return()=>{alive.current=false;controller.abort();};
 },[]);
 async function configure(kind:'local'|'tunnel',updates:Partial<Access>&{rotate?:boolean}){
  if(!value)return;
  setBusy(true);setError('');setCopied(false);
  try{
   const next=await api<AccessState>('mcp-access',{kind,...value[kind],...updates});
   if(!alive.current)return;
   setValue({local:next.local,tunnel:next.tunnel});
   if(next.token)setToken(next.token);else if(!next.local.enabled)setToken('');
  }catch(e){if(alive.current)setError((e as Error).message);}
  finally{if(alive.current)setBusy(false);}
 }
 const url=`http://127.0.0.1:${port}/mcp`;
 const connection=token?JSON.stringify({mcpServers:{leafloom:{url,headers:{Authorization:'Bearer '+token}}}},null,2):'';
 return <SettingGroup id="mcp" title={t('mcp.title')} description={t('mcp.scope')}>
  {error&&<StatusNotice kind="error"><Diagnostic message={error}/></StatusNotice>}
  {!value?<StatusNotice>{t('mcp.loading')}</StatusNotice>:<>
   <SettingRow label={t('mcp.localRead')} description={t('mcp.localReadHelp')}><input type="checkbox" aria-label={t('mcp.localRead')} checked={value.local.enabled} disabled={busy} onChange={e=>void configure('local',{enabled:e.target.checked,write:false})}/></SettingRow>
   <SettingRow label={t('mcp.localWrite')} description={t('mcp.writeHelp')}><input type="checkbox" aria-label={t('mcp.localWrite')} checked={value.local.write} disabled={busy||!value.local.enabled} onChange={e=>void configure('local',{write:e.target.checked})}/></SettingRow>
   {value.local.enabled&&<div className="setting-actions"><button disabled={busy} onClick={()=>void configure('local',{rotate:true})}>{t('mcp.rotate')}</button></div>}
   {connection&&<>
    <StatusNotice>{t('mcp.tokenOnce')}</StatusNotice>
    <textarea aria-label={t('mcp.connectionConfig')} readOnly rows={10} value={connection} spellCheck={false}/>
    <div className="setting-actions"><button onClick={async()=>{try{await navigator.clipboard.writeText(connection);if(alive.current)setCopied(true);}catch{if(alive.current)setError(t('mcp.copyFailed'));}}}>{t(copied?'mcp.copied':'mcp.copy')}</button></div>
   </>}
   <SettingRow label={t('mcp.tunnelRead')} description={t('mcp.tunnelReadHelp')}><input type="checkbox" aria-label={t('mcp.tunnelRead')} checked={value.tunnel.enabled} disabled={busy} onChange={e=>void configure('tunnel',{enabled:e.target.checked,write:false})}/></SettingRow>
   <SettingRow label={t('mcp.tunnelWrite')} description={t('mcp.writeHelp')}><input type="checkbox" aria-label={t('mcp.tunnelWrite')} checked={value.tunnel.write} disabled={busy||!value.tunnel.enabled} onChange={e=>void configure('tunnel',{write:e.target.checked})}/></SettingRow>
   <p className="setting-detail">{t('mcp.legacy')}</p>
  </>}
 </SettingGroup>;
}
