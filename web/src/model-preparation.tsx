import React,{useEffect,useRef,useState} from 'react';
import {api} from './api';
import {Diagnostic,getLocale,t} from './i18n';
import './model-preparation.css';

const activeStates=new Set(['starting','checking','connecting','downloading','verifying','saving']);
const labels:Record<string,string>={starting:'model.starting',checking:'model.checking',connecting:'model.connecting',downloading:'model.downloading',verifying:'model.verifying',saving:'model.saving',ready:'模型已准备',failed:'model.failed'};
const bytes=(value:number)=>{const unit=value>=1024**3?'GiB':value>=1024**2?'MiB':'KiB',scale=unit==='GiB'?1024**3:unit==='MiB'?1024**2:1024;return (value/scale).toLocaleString(getLocale(),{maximumFractionDigits:1})+' '+unit;};

export function ModelPreparation({status}:{status:any}){
 const model=status?.model;
 const [requesting,setRequesting]=useState(false),[error,setError]=useState(''),[now,setNow]=useState(Date.now());
 const [opening,setOpening]=useState(false),[directoryError,setDirectoryError]=useState('');
 const request=useRef(false);
 const progress=requesting&&!activeStates.has(model?.preparation?.state)?undefined:model?.preparation;
 const state=progress?.state||(requesting?'starting':''),active=requesting||activeStates.has(state),failed=state==='failed';
 useEffect(()=>{if(!active)return;setNow(Date.now());const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[active]);
 const prepare=async()=>{
  if(request.current||active)return;request.current=true;setRequesting(true);setError('');
  try{await api('model-prepare',{});}catch(error){setError((error as Error).message);}
  finally{request.current=false;setRequesting(false);}
 };
 const openDirectory=async()=>{
  setOpening(true);setDirectoryError('');
  try{await api('model-directory/open',{});}catch(error){setDirectoryError(t('model.openDirectoryFailed')+': '+(error as Error).message);}
  finally{setOpening(false);}
 };
 const title=active||failed?t(labels[state]||'model.starting'):model?.loaded?t('已加载'):model?.prepared?t('已准备'):t('待准备');
 const elapsed=progress?.started_at?Math.max(0,Math.floor(((active?now/1000:progress.updated_at)-progress.started_at))):0;
 const stalled=active&&progress?.updated_at&&now/1000-progress.updated_at>30;
 const total=Number(progress?.total_files)||0,completed=Math.max(0,Math.min(total,Number(progress?.completed_files)||0));
 const phase=failed?progress?.failed_stage:state;
 const step=['verifying','saving','ready'].includes(phase)?2:phase==='downloading'?1:0;
 const diagnostic=error||(failed?model?.error:'');
 return <div className="model-preparation">
  <div className="model-preparation-heading"><div><strong>BGE-M3</strong><span role="status">{title}</span></div><button disabled={active||!!model?.prepared} onClick={()=>void prepare()}>{active?t('model.preparing'):model?.prepared?t('模型已准备'):failed||error?t('model.retry'):t('准备模型')}</button></div>
  <div className="model-preparation-directory"><div><span>{t('model.directory')}</span><code>{model?.path||t('model.pathLoading')}</code></div><button disabled={opening||!model?.path} onClick={()=>void openDirectory()}>{t(opening?'model.openingDirectory':'model.openDirectory')}</button></div>
  {directoryError&&<div className="model-preparation-error" role="alert">{directoryError}</div>}
  {(active||failed||state==='ready')&&<div className={'model-preparation-card'+(failed?' failed':'')}>
   <ol className="model-preparation-steps" aria-label={t('model.steps')}>{['model.stepConnect','model.stepDownload','model.stepVerify'].map((label,index)=><li key={label} className={state==='ready'||index<step?'done':index===step?'current':''} aria-current={index===step&&active?'step':undefined}><span>{state==='ready'||index<step?'✓':index+1}</span>{t(label)}</li>)}</ol>
   {active&&<><div className="model-preparation-meter">{total>0&&['downloading','verifying'].includes(state)?<progress aria-label={title} max={total} value={completed}/>:<progress aria-label={title}/>}<span>{t('model.elapsed',{time:Math.floor(elapsed/60)+':'+String(elapsed%60).padStart(2,'0')})}</span></div>
    <div className="model-preparation-details">{total>0&&<span>{t(state==='downloading'?'model.downloadFiles':'model.checkedFiles',{done:completed,total})}</span>}{state==='downloading'&&Number(progress?.downloaded_bytes)>0&&<span>{t('model.received',{size:bytes(progress.downloaded_bytes)})}{!stalled&&Number(progress?.bytes_per_second)>0?' · '+bytes(progress.bytes_per_second)+'/s':''}</span>}</div>
    {progress?.current_file&&<div className="model-preparation-file">{progress.current_file}</div>}
    {stalled&&<p className="model-preparation-wait" role="status">{t(['starting','connecting','downloading'].includes(state)?'model.slowNetwork':'model.largeFile')}</p>}
   </>}
   <p>{t(failed?'model.retryHelp':state==='ready'?'model.readyHelp':'model.backgroundHelp')}</p>
  </div>}
  {!active&&!failed&&!model?.prepared&&<p className="model-preparation-help">{t('model.firstDownload')}</p>}
  {diagnostic&&<div className="model-preparation-error" role="alert"><Diagnostic message={diagnostic}/></div>}
 </div>;
}
