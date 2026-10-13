import React,{useSyncExternalStore} from 'react';
import {api} from './api';
import zh from '../../vault_rag/locales/zh-CN.json';
import en from '../../vault_rag/locales/en.json';
import ja from '../../vault_rag/locales/ja.json';

export type Locale='zh-CN'|'en'|'ja';
export type LocaleChoice=Locale|'auto';
const catalogues:Record<Locale,Record<string,string>>={'zh-CN':zh,en,ja};
const reverse=new Map<string,string>();
for(const values of Object.values(catalogues))for(const [key,value] of Object.entries(values))if(!reverse.has(value))reverse.set(value,key);
export const resolveLocale=(value:string):Locale=>value.toLowerCase().startsWith('zh')?'zh-CN':value.toLowerCase().startsWith('ja')?'ja':'en';
let choice:LocaleChoice='auto';
try{const saved=localStorage.getItem('leafloom-locale');if(['auto','zh-CN','en','ja'].includes(saved||''))choice=saved as LocaleChoice;}catch{/* The server remains the preference authority. */}
let locale:Locale=choice==='auto'?resolveLocale(navigator.language):choice;
const listeners=new Set<()=>void>();
export function setLocale(value:LocaleChoice){
 choice=value;locale=value==='auto'?resolveLocale(navigator.language):value;
 document.documentElement.lang=locale;document.title=t('本地知识库');
 try{localStorage.setItem('leafloom-locale',value);}catch{/* A browser storage failure does not interrupt editing. */}
 for(const listener of listeners)listener();
}
export const getLocale=()=>locale;
export const getLocaleChoice=()=>choice;
export function useLocale(){return useSyncExternalStore(callback=>{listeners.add(callback);return()=>listeners.delete(callback);},()=>locale);}
export function t(key:string,params:Record<string,string|number>={}){
 const canonical=catalogues[locale][key]!==undefined?key:reverse.get(key)||key;
 const text=catalogues[locale][canonical]??catalogues.en[canonical]??key;
 return text.replace(/\{(\w+)\}/g,(match,name)=>params[name]===undefined?match:String(params[name]));
}
export function LocalePicker(){
 useLocale();const [error,setError]=React.useState('');
 return <div className="locale-picker"><label><span>{t('界面语言')}</span><select aria-label={t('界面语言')} value={choice} onChange={async event=>{
  const value=event.target.value as LocaleChoice;setError('');
  try{await api('preferences',{locale:value},'PUT');setLocale(value);}catch(error){setError((error as Error).message);}
 }}><option value="auto">{t('跟随系统')}</option><option value="zh-CN">中文</option><option value="en">English</option><option value="ja">日本語</option></select></label>{error&&<p className="error" role="alert">{error}</p>}</div>;
}
export function Diagnostic({message}:{message:string}){
 useLocale();const translated=t(message);
 return /[\u3400-\u9fff]/.test(message)&&translated===message?<details className="error-details"><summary>{t('操作未完成')} · {t('诊断详情')}</summary><pre>{message}</pre></details>:<>{translated}</>;
}
setLocale(choice);
