import React,{useEffect,useRef,useState} from 'react';
import {api} from './api';
import {Diagnostic,t,useLocale} from './i18n';
import {RunAction,SettingGroup,SettingRow,StatusNotice} from './settings-ui';

type OfficeSettings={root:string,folder:string,path:string,workspace_revision:string,revision:string,
 configured:boolean,office_providers:string[],office_provider:string|null,implemented:boolean,providers:{id:string,implemented:boolean}[]};

export function WorkHubSettings({root,revision,folder,run,onChanged}:{root:string|null,revision?:string,folder:string,run:RunAction,onChanged:()=>void}){
 useLocale();
 const scope=useRef('');scope.current=JSON.stringify([root,revision,folder]);
 const [settings,setSettings]=useState<OfficeSettings>(),[error,setError]=useState(''),[reload,setReload]=useState(0),[saved,setSaved]=useState(false);
 useEffect(()=>{
  setSettings(undefined);setError('');setSaved(false);
  if(!root)return;
  const controller=new AbortController();
  api<OfficeSettings>('work-hub/settings?'+new URLSearchParams({root}),undefined,'GET',{force:true,signal:controller.signal})
   .then(value=>{if(!controller.signal.aborted)setSettings(value);})
   .catch(error=>{if(!controller.signal.aborted)setError(error.message);});
  return()=>controller.abort();
 },[root,revision,folder,reload]);
 const selected=settings?.office_providers||[settings?.office_provider||'auto'];
 const choose=(office_providers:string[])=>{
  if(!settings||JSON.stringify(office_providers)===JSON.stringify(selected))return;
  const requestScope=scope.current;
  setSaved(false);
  void run(t('wh.save'),()=>api<OfficeSettings>('work-hub/settings',{
   root:settings.root,workspace_revision:settings.workspace_revision,revision:settings.revision,office_providers,
  },'PUT'),value=>{if(scope.current!==requestScope)return;setSettings(value);setSaved(true);onChanged();});
 };
 return <SettingGroup id="work-hub-settings" title={t('wh.title')} description={t('wh.help')}>
  {!root?<StatusNotice>{t('wh.needsVault')}</StatusNotice>:error?<StatusNotice kind="error"><Diagnostic message={error}/> <button onClick={()=>setReload(value=>value+1)}>{t('重新载入设置')}</button></StatusNotice>:!settings?<StatusNotice kind="busy">{t('wh.loading')}</StatusNotice>:<>
   <SettingRow label={t('wh.mode')} description={t('wh.modeHelp')}><div className="work-hub-options">
    {['auto','local'].map(mode=><label className="work-hub-choice" key={mode}><input type="radio" name="work-hub-mode" checked={selected.length===1&&selected[0]===mode} onChange={()=>choose([mode])}/>{t('wh.provider.'+mode)}</label>)}
   </div></SettingRow>
   <SettingRow stacked label={t('wh.office')} description={t('wh.autoSave')}><div className="work-hub-options work-hub-platforms" role="group" aria-label={t('wh.office')}>
    {[...settings.providers.filter(item=>!['auto','local'].includes(item.id)),...selected.filter(id=>!settings.providers.some(item=>item.id===id)).map(id=>({id,implemented:false}))].map(item=><label className="work-hub-choice" key={item.id}><input type="checkbox" checked={selected.includes(item.id)} onChange={event=>{
     const platforms=selected.filter(id=>!['auto','local'].includes(id));
     const next=event.target.checked?[...platforms,item.id]:platforms.filter(id=>id!==item.id);
     choose(next.length?next:['auto']);
    }}/><span>{settings.providers.some(provider=>provider.id===item.id)?t('wh.provider.'+item.id):item.id}{item.implemented?'':' · '+t('wh.notImplemented')}</span></label>)}
   </div></SettingRow>
   {!settings.implemented&&<StatusNotice>{t('wh.unsupported')}</StatusNotice>}
   {selected.includes('feishu')&&<p className="setting-detail">{t('wh.feishuConnection')}</p>}
   <p className="setting-detail">{t('wh.sharedConfig',{path:settings.path})}</p>
   <p className="setting-detail">{t('wh.explicitSource')}</p>
   <button onClick={()=>setReload(value=>value+1)}>{t('重新载入设置')}</button>
   {saved&&<StatusNotice kind="success">{t('wh.saved')}</StatusNotice>}
  </>}
 </SettingGroup>;
}
