import React,{useState} from 'react';
import {t,useLocale} from './i18n';

export function StorageMigrationNotice(){
 useLocale();
 const [visible,setVisible]=useState(()=>{try{return localStorage.getItem('leafloom:migration-conflicts')==='true';}catch{return false;}});
 if(!visible)return null;
 const download=()=>{
  const backups:Record<string,unknown>={};
  for(let i=0;i<localStorage.length;i++){const key=localStorage.key(i)!;if(key.startsWith('leafloom:migration-backup:'))backups[key]=JSON.parse(localStorage.getItem(key)!);}
  const url=URL.createObjectURL(new Blob([JSON.stringify(backups,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download='leafloom-storage-backup.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 };
 return <div className="conflict-banner" role="status"><span>{t('迁移发现已有状态，已保留当前版本和原入口备份。')}</span><button onClick={download}>{t('下载迁移备份')}</button><button onClick={()=>{localStorage.removeItem('leafloom:migration-conflicts');setVisible(false);}}>{t('关闭')}</button></div>;
}
