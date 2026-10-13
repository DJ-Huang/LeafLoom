import React,{useEffect,useRef,useState} from 'react';
import {api} from './api';
import {useStatus} from './hooks';
import {SettingGroup,SettingRow} from './settings-ui';
import {t,useLocale,Diagnostic} from './i18n';

export function DesktopPreferences(){
 useLocale();
 const [enabled,setEnabled]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 useEffect(()=>{void window.vaultDesktop?.getAutostart().then(setEnabled).catch(error=>setError(String(error)));},[]);
 if(!window.vaultDesktop)return null;
 return <SettingGroup id="desktop" title={t('桌面应用')}><SettingRow label={t('登录时启动')} description={t('登录后在后台提供检索服务，不打开主窗口。')}><input type="checkbox" aria-label={t('登录时启动')} checked={enabled} disabled={busy} onChange={async event=>{setBusy(true);setError('');try{setEnabled(await window.vaultDesktop!.setAutostart(event.target.checked));}catch(error){setError(String(error));}finally{setBusy(false);}}}/></SettingRow><p className="setting-detail">{t('关闭窗口后继续在后台运行；从托盘或菜单栏选择“退出”停止服务。')}</p>{error&&<p role="alert" className="error">{<Diagnostic message={error}/>}</p>}</SettingGroup>;
}

export function ModelPreparation(){
 useLocale();
 const status=useStatus(),model=status?.model,attempted=useRef(false);
 const [error,setError]=useState(''),[starting,setStarting]=useState(false);
 const prepare=async()=>{setError('');setStarting(true);try{await api('model-prepare',{});}catch(error){setError(String(error));}finally{setStarting(false);}};
 useEffect(()=>{if(window.vaultDesktop&&model&&!model.prepared&&!model.error&&!attempted.current){attempted.current=true;void prepare();}},[model?.prepared,model?.error]);
 if(!window.vaultDesktop||!model||model.prepared)return null;
 const downloading=starting||model.download==='下载模型中';
 return <div role="status" className="model-preparation"><strong>{t(downloading?'本地检索模型正在准备':'本地检索模型尚未就绪')}</strong><span>{error||model.error||t('首次需要联网下载 BGE-M3；你可以继续浏览和编辑，暂时使用关键词检索。')}</span>{!downloading&&<button onClick={()=>void prepare()}>{t(error||model.error?'重试下载':'准备模型')}</button>}</div>;
}
