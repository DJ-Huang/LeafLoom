import {Diagnostic} from './i18n';
import {t,useLocale} from './i18n';
import React,{useEffect,useId,useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {BookOpen,X,FileText,AlertTriangle} from 'lucide-react';
export class LazyBoundary extends React.Component<{children:React.ReactNode},{failed:boolean}>{
 state={failed:false};
 static getDerivedStateFromError(){return {failed:true};}
 render(){return this.state.failed?<div className="empty-state"><p>{t("内容模块未能加载，可能是页面版本已更新。")}</p><button onClick={()=>window.location.reload()}>{t("重新加载页面")}</button></div>:this.props.children;}
}
export const Action=({title,children,onClick}:{title:string,children:React.ReactNode,onClick:(event:React.MouseEvent<HTMLButtonElement>)=>void})=><button className="icon-button" title={title} aria-label={title} onClick={onClick}>{children}</button>;
export function Modal({title,children,onClose,wide=false,className='',hideHeader=false,style,icon}:{title:string,children:React.ReactNode,onClose:()=>void,wide?:boolean,className?:string,hideHeader?:boolean,style?:React.CSSProperties,icon?:React.ReactNode}){
 useLocale();
 const ref=useRef<HTMLDialogElement>(null),label=useId(),close=useRef(onClose);close.current=onClose;
 useEffect(()=>{const previous=document.activeElement as HTMLElement|null,dialog=ref.current!;dialog.showModal();
  return()=>{dialog.close();if(previous?.isConnected)previous.focus();};},[]);
 return <dialog ref={ref} className={'modal '+(wide?'wide ':'')+className} style={style} aria-labelledby={label} onCancel={event=>{event.preventDefault();close.current();}} onClick={event=>{if(event.target===event.currentTarget){const box=event.currentTarget.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)close.current();}}}>
  {hideHeader?<h2 id={label} className="sr-only">{title}</h2>:<header><div className="modal-heading">{icon&&<span className="modal-heading-icon" aria-hidden="true">{icon}</span>}<h2 id={label}>{title}</h2></div><Action title={t("关闭")} onClick={onClose}><X size={18}/></Action></header>}{children}
 </dialog>;
}
export type MenuPoint={x:number,y:number};
export function ActionMenu({title,anchor,point,className='',children,onClose}:{title:string,anchor:HTMLElement,point?:MenuPoint,className?:string,children:React.ReactNode,onClose:()=>void}){
 useLocale();
 const ref=useRef<HTMLDivElement>(null),close=useRef(onClose);close.current=onClose;
 useLayoutEffect(()=>{
  const menu=ref.current!;
  const place=()=>{const box=anchor.getBoundingClientRect();menu.style.left=Math.max(8,Math.min(point?.x??box.left,window.innerWidth-menu.offsetWidth-8))+'px';menu.style.top=Math.max(8,Math.min(point?.y??box.bottom+5,window.innerHeight-menu.offsetHeight-8))+'px';};
  const items=()=>Array.from(menu.querySelectorAll<HTMLElement>('button:not(:disabled),a[href]'));
  menu.querySelectorAll('button,a[href]').forEach(item=>item.setAttribute('role','menuitem'));place();items()[0]?.focus();
  const outside=(event:PointerEvent)=>{if(!menu.contains(event.target as Node)&&!anchor.contains(event.target as Node))close.current();};
  const key=(event:KeyboardEvent)=>{if(event.key==='Escape'||event.key==='Tab'){if(event.key==='Escape')event.preventDefault();close.current();return;}const list=items(),index=list.indexOf(document.activeElement as HTMLElement);if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();list[event.key==='Home'?0:event.key==='End'?list.length-1:(index+(event.key==='ArrowDown'?1:list.length-1))%list.length]?.focus();}};
  document.addEventListener('pointerdown',outside);menu.addEventListener('keydown',key);window.addEventListener('resize',place);window.addEventListener('scroll',place,true);
  return()=>{document.removeEventListener('pointerdown',outside);menu.removeEventListener('keydown',key);window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true);if(anchor.isConnected)anchor.focus();};
 },[anchor,point?.x,point?.y]);
 return createPortal(<div ref={ref} className={'action-menu action-list '+className} role="menu" aria-label={title} onContextMenu={event=>event.preventDefault()} onClick={event=>{if((event.target as HTMLElement).closest('button:not(:disabled),a[href]'))onClose();}}>{children}</div>,document.body);
}
export type FormField={name:string,label:string,value?:string,multiline?:boolean,required?:boolean,options?:{value:string,label:string}[]};
export function FormDialog({title,description,fields=[],submitLabel=t("保存"),danger=false,onSubmit,onClose,className=''}:{title:string,description?:string,fields?:FormField[],submitLabel?:string,danger?:boolean,className?:string,onSubmit:(values:Record<string,string>)=>Promise<void>,onClose:()=>void}){
 useLocale();
 const [values,setValues]=useState(()=>Object.fromEntries(fields.map(field=>[field.name,field.value||'']))),[busy,setBusy]=useState(false),[error,setError]=useState('');
 return <Modal title={title} className={'form-modal '+(danger?'form-modal-danger ':'')+className} icon={danger?<AlertTriangle size={19} strokeWidth={1.6}/>:<FileText size={19} strokeWidth={1.6}/>} onClose={()=>{if(!busy)onClose();}}><form onSubmit={async event=>{event.preventDefault();if(busy)return;setBusy(true);setError('');try{await onSubmit(values);onClose();}catch(error){setError((error as Error).message);}finally{setBusy(false);}}}>
  <div className="pad">{description&&<p className="hint">{description}</p>}{fields.map((field,index)=><label className="setting-field" key={field.name}>{field.label}{field.options?<select autoFocus={index===0} required={field.required} value={values[field.name]} onChange={event=>setValues({...values,[field.name]:event.target.value})}>{field.options.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select>:field.multiline?<textarea autoFocus={index===0} rows={5} required={field.required} value={values[field.name]} onChange={event=>setValues({...values,[field.name]:event.target.value})}/>:<input autoFocus={index===0} required={field.required} value={values[field.name]} onChange={event=>setValues({...values,[field.name]:event.target.value})}/>}</label>)}{error&&<p className="error" role="alert">{<Diagnostic message={error}/>}</p>}</div>
  <footer className="modal-footer"><button type="button" disabled={busy} onClick={onClose}>{t("取消")}</button><button className={danger?'danger-button':'primary'} disabled={busy}>{busy?t("处理中…"):submitLabel}</button></footer>
 </form></Modal>;
}
export function LoadingShell({error,onRetry}:{error:string,onRetry:()=>void}){
 useLocale();return <div className="app" aria-busy="true"><aside className="sidebar"><div className="brand"><BookOpen size={24}/><strong>{t("本地知识库")}</strong></div><div className="skeleton"/><div className="skeleton"/><div className="skeleton"/></aside><main className="main"><div className="tabs">{t("概览")}</div><div className="dashboard"><h1>{t("本地知识库")}</h1><p role="status">{error||t("正在读取目录设置…")}</p>{error&&<button onClick={onRetry}>{t("重新连接")}</button>}<div className="skeleton"/><div className="skeleton"/></div></main></div>;}
