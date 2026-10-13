import React,{useEffect,useId,useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {BookOpen,X} from 'lucide-react';
export class LazyBoundary extends React.Component<{children:React.ReactNode},{failed:boolean}>{
 state={failed:false};
 static getDerivedStateFromError(){return {failed:true};}
 render(){return this.state.failed?<div className="empty-state"><p>内容模块未能加载，可能是页面版本已更新。</p><button onClick={()=>window.location.reload()}>重新加载页面</button></div>:this.props.children;}
}
export const Action=({title,children,onClick}:{title:string,children:React.ReactNode,onClick:(event:React.MouseEvent<HTMLButtonElement>)=>void})=><button className="icon-button" title={title} aria-label={title} onClick={onClick}>{children}</button>;
export function Modal({title,children,onClose,wide=false,className='',hideHeader=false}:{title:string,children:React.ReactNode,onClose:()=>void,wide?:boolean,className?:string,hideHeader?:boolean}){
 const ref=useRef<HTMLDialogElement>(null),label=useId(),close=useRef(onClose);close.current=onClose;
 useEffect(()=>{const previous=document.activeElement as HTMLElement|null,dialog=ref.current!;dialog.showModal();
  return()=>{dialog.close();if(previous?.isConnected)previous.focus();};},[]);
 return <dialog ref={ref} className={'modal '+(wide?'wide ':'')+className} aria-labelledby={label} onCancel={event=>{event.preventDefault();close.current();}} onClick={event=>{if(event.target===event.currentTarget){const box=event.currentTarget.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)close.current();}}}>
  {hideHeader?<h2 id={label} className="sr-only">{title}</h2>:<header><h2 id={label}>{title}</h2><Action title="关闭" onClick={onClose}><X size={18}/></Action></header>}{children}
 </dialog>;
}
export function ActionMenu({title,anchor,children,onClose}:{title:string,anchor:HTMLElement,children:React.ReactNode,onClose:()=>void}){
 const ref=useRef<HTMLDivElement>(null),close=useRef(onClose);close.current=onClose;
 useLayoutEffect(()=>{
  const menu=ref.current!;
  const place=()=>{const box=anchor.getBoundingClientRect();menu.style.left=Math.max(8,Math.min(box.left,window.innerWidth-menu.offsetWidth-8))+'px';menu.style.top=Math.max(8,Math.min(box.bottom+5,window.innerHeight-menu.offsetHeight-8))+'px';};
  const items=()=>Array.from(menu.querySelectorAll<HTMLElement>('button:not(:disabled),a[href]'));
  items().forEach(item=>item.setAttribute('role','menuitem'));place();items()[0]?.focus();
  const outside=(event:PointerEvent)=>{if(!menu.contains(event.target as Node)&&!anchor.contains(event.target as Node))close.current();};
  const key=(event:KeyboardEvent)=>{if(event.key==='Escape'||event.key==='Tab'){if(event.key==='Escape')event.preventDefault();close.current();return;}const list=items(),index=list.indexOf(document.activeElement as HTMLElement);if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();list[event.key==='Home'?0:event.key==='End'?list.length-1:(index+(event.key==='ArrowDown'?1:list.length-1))%list.length]?.focus();}};
  document.addEventListener('pointerdown',outside);menu.addEventListener('keydown',key);window.addEventListener('resize',place);window.addEventListener('scroll',place,true);
  return()=>{document.removeEventListener('pointerdown',outside);menu.removeEventListener('keydown',key);window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true);if(anchor.isConnected)anchor.focus();};
 },[anchor]);
 return createPortal(<div ref={ref} className="action-menu action-list" role="menu" aria-label={title} onClick={event=>{if((event.target as HTMLElement).closest('button:not(:disabled),a[href]'))onClose();}}>{children}</div>,document.body);
}
export type FormField={name:string,label:string,value?:string,multiline?:boolean,required?:boolean,options?:{value:string,label:string}[]};
export function FormDialog({title,description,fields=[],submitLabel='保存',danger=false,onSubmit,onClose}:{title:string,description?:string,fields?:FormField[],submitLabel?:string,danger?:boolean,onSubmit:(values:Record<string,string>)=>Promise<void>,onClose:()=>void}){
 const [values,setValues]=useState(()=>Object.fromEntries(fields.map(field=>[field.name,field.value||'']))),[busy,setBusy]=useState(false),[error,setError]=useState('');
 return <Modal title={title} onClose={()=>{if(!busy)onClose();}}><form onSubmit={async event=>{event.preventDefault();if(busy)return;setBusy(true);setError('');try{await onSubmit(values);onClose();}catch(error){setError((error as Error).message);}finally{setBusy(false);}}}>
  <div className="pad">{description&&<p className="hint">{description}</p>}{fields.map((field,index)=><label className="setting-field" key={field.name}>{field.label}{field.options?<select autoFocus={index===0} required={field.required} value={values[field.name]} onChange={event=>setValues({...values,[field.name]:event.target.value})}>{field.options.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select>:field.multiline?<textarea autoFocus={index===0} rows={5} required={field.required} value={values[field.name]} onChange={event=>setValues({...values,[field.name]:event.target.value})}/>:<input autoFocus={index===0} required={field.required} value={values[field.name]} onChange={event=>setValues({...values,[field.name]:event.target.value})}/>}</label>)}{error&&<p className="error" role="alert">{error}</p>}</div>
  <footer className="modal-footer"><button type="button" disabled={busy} onClick={onClose}>取消</button><button className={danger?'danger-button':'primary'} disabled={busy}>{busy?'处理中…':submitLabel}</button></footer>
 </form></Modal>;
}
export function LoadingShell({error,onRetry}:{error:string,onRetry:()=>void}){return <div className="app" aria-busy="true"><aside className="sidebar"><div className="brand"><BookOpen size={24}/><strong>本地知识库</strong></div><div className="skeleton"/><div className="skeleton"/><div className="skeleton"/></aside><main className="main"><div className="tabs">概览</div><div className="dashboard"><h1>本地知识库</h1><p role="status">{error||'正在读取目录设置…'}</p>{error&&<button onClick={onRetry}>重新连接</button>}<div className="skeleton"/><div className="skeleton"/></div></main></div>;}
