import React from 'react';
import {CheckCircle2,AlertCircle,Loader2} from 'lucide-react';

export type RunAction=<T>(label:string,work:(valid:()=>boolean)=>Promise<T>,done?:(result:T)=>void)=>Promise<void>;
export function SettingGroup({id,title,description,children}:{id?:string,title:string,description?:string,children:React.ReactNode}){
 return <section className="setting-group" id={id?'setting-'+id:undefined} tabIndex={-1}><div className="setting-group-heading"><h3>{title}</h3>{description&&<p>{description}</p>}</div>{children}</section>;
}
export function SettingRow({label,description,children,stacked=false}:{label:string,description?:string,children:React.ReactNode,stacked?:boolean}){
 return <div className={'setting-row'+(stacked?' stacked':'')}><div className="setting-row-label"><strong>{label}</strong>{description&&<p>{description}</p>}</div><div className="setting-row-control">{children}</div></div>;
}
export function StatusNotice({kind='info',children}:{kind?:'info'|'error'|'success'|'busy',children:React.ReactNode}){
 return <div className={'status-notice '+kind} role={kind==='error'?'alert':'status'}>{kind==='busy'?<Loader2 size={16} className="spin"/>:kind==='success'?<CheckCircle2 size={16}/>:<AlertCircle size={16}/>}<div>{children}</div></div>;
}
