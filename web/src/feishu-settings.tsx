import React,{useEffect,useRef,useState} from 'react';
import {api} from './api';
import {Diagnostic,getLocale,t,useLocale} from './i18n';
import {SettingGroup,SettingRow,StatusNotice} from './settings-ui';

type Options={enabled:boolean,binary:string,profile:string};
type State={config:Options,verification:{state:string,version?:string,user_name?:string,verified_at?:string}};

export function FeishuSettings(){
 useLocale();
 const [value,setValue]=useState<State>(),[draft,setDraft]=useState<Options>(),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const alive=useRef(true);
 useEffect(()=>{
  alive.current=true;const controller=new AbortController();
  api<State>('feishu',undefined,undefined,{force:true,signal:controller.signal}).then(next=>{setValue(next);setDraft(next.config);}).catch(e=>{if(!controller.signal.aborted)setError(e.message);});
  return()=>{alive.current=false;controller.abort();};
 },[]);
 const dirty=JSON.stringify(draft)!==JSON.stringify(value?.config);
 async function run(verify=false){
  if(!draft)return;
  setBusy(true);setError('');
  try{
   const next=verify?await api<State>('feishu/verify',{}):await api<State>('feishu',draft);
   if(alive.current){setValue(next);setDraft(next.config);}
  }catch(e){if(alive.current)setError((e as Error).message);}
  finally{if(alive.current)setBusy(false);}
 }
 return <SettingGroup id="feishu" title={t('feishu.title')} description={t('feishu.description')}>
  {error&&<StatusNotice kind="error"><Diagnostic message={error}/></StatusNotice>}
  {!draft||!value?<StatusNotice>{t('mcp.loading')}</StatusNotice>:<form onSubmit={e=>{e.preventDefault();void run();}}>
   <SettingRow label={t('feishu.enabled')}><input type="checkbox" aria-label={t('feishu.enabled')} checked={draft.enabled} disabled={busy} onChange={e=>setDraft({...draft,enabled:e.target.checked})}/></SettingRow>
   <SettingRow label={t('feishu.binary')} description={t('feishu.binaryHelp')}><input aria-label={t('feishu.binary')} value={draft.binary} disabled={busy} placeholder={t('feishu.automatic')} onChange={e=>setDraft({...draft,binary:e.target.value})}/></SettingRow>
   <SettingRow label={t('feishu.profile')} description={t('feishu.profileHelp')}><input aria-label={t('feishu.profile')} value={draft.profile} disabled={busy} onChange={e=>setDraft({...draft,profile:e.target.value})}/></SettingRow>
   <div className="setting-actions"><button type="submit" disabled={busy||!dirty}>{t('保存设置')}</button><button type="button" disabled={busy||dirty||!value.config.enabled} onClick={()=>void run(true)}>{t(busy?'feishu.working':'feishu.verify')}</button></div>
   {dirty&&<p className="setting-detail">{t('feishu.saveFirst')}</p>}
   <StatusNotice kind={value.verification.state==='connected'?'success':undefined}>{t('feishu.state.'+value.verification.state)}{value.verification.user_name&&' · '+value.verification.user_name}{value.verification.version&&' · '+value.verification.version}</StatusNotice>
   {value.verification.verified_at&&<p className="setting-detail">{t('feishu.checkedAt',{time:new Date(value.verification.verified_at).toLocaleString(getLocale())})}</p>}
   <p className="setting-detail">{t('feishu.permissionsHelp')}</p>
   <p className="setting-detail">{t('feishu.externalSetup')} <a href="https://github.com/larksuite/cli" target="_blank" rel="noreferrer">{t('feishu.setupGuide')}</a></p>
  </form>}
 </SettingGroup>;
}
