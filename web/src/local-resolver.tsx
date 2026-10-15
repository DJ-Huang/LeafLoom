import React,{useEffect,useState} from 'react';
import {api} from './api';
import {t} from './i18n';
import {SettingGroup,SettingRow,StatusNotice} from './settings-ui';

type Resolver={supported:boolean,needed:boolean,configured:boolean,running:boolean,error:string};
export function LocalResolverSettings(){
 const [status,setStatus]=useState<Resolver>(),[busy,setBusy]=useState(false),[error,setError]=useState('');
 useEffect(()=>{let alive=true;void api<Resolver>('local-resolver',undefined,undefined,{force:true}).then(value=>{if(alive)setStatus(value);}).catch(()=>{});return()=>{alive=false;};},[]);
 if(!status?.supported)return null;
 return <SettingGroup title={t('Safari 本机网页兼容')} description={t('macOS 14/15 的 Safari 需要本机解析配置。仅配置本应用的专属域名，系统会请求管理员授权。')}>
  <SettingRow label={status.configured?t('已启用'):t('未启用')} description={t('不改变默认 DNS；移除后仍可使用 App 和其他兼容浏览器。')}><button disabled={busy||(!status.configured&&!status.running)} onClick={async()=>{setBusy(true);setError('');try{setStatus(await api<Resolver>('local-resolver',{enabled:!status.configured}));}catch(error){setError((error as Error).message);}finally{setBusy(false);}}}>{busy?t('正在处理…'):status.configured?t('移除兼容配置'):t('启用 Safari 兼容')}</button></SettingRow>
  {error&&<StatusNotice kind="error">{error}</StatusNotice>}{!status.running&&<StatusNotice>{t('本机解析服务尚未运行，请重新启动本地服务后重试')}</StatusNotice>}
 </SettingGroup>;
}
