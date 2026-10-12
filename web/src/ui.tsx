import React from 'react';
import {BookOpen,X} from 'lucide-react';
export class LazyBoundary extends React.Component<{children:React.ReactNode},{failed:boolean}>{
 state={failed:false};
 static getDerivedStateFromError(){return {failed:true};}
 render(){return this.state.failed?<div className="empty-state"><p>内容模块未能加载，可能是页面版本已更新。</p><button onClick={()=>window.location.reload()}>重新加载页面</button></div>:this.props.children;}
}
export const Action=({title,children,onClick}:{title:string,children:React.ReactNode,onClick:()=>void})=><button className="icon-button" title={title} aria-label={title} onClick={onClick}>{children}</button>;
export function Modal({title,children,onClose,wide=false}:{title:string,children:React.ReactNode,onClose:()=>void,wide?:boolean}){return <div className="modal-shade" onMouseDown={e=>{if(e.target===e.currentTarget)onClose();}}><section className={'modal '+(wide?'wide':'')}><header><h2>{title}</h2><Action title="关闭" onClick={onClose}><X size={20}/></Action></header>{children}</section></div>;}
export function LoadingShell({error,onRetry}:{error:string,onRetry:()=>void}){return <div className="app" aria-busy="true"><aside className="sidebar"><div className="brand"><BookOpen size={24}/><strong>本地知识库</strong></div><div className="skeleton"/><div className="skeleton"/><div className="skeleton"/></aside><main className="main"><div className="tabs">概览</div><div className="dashboard"><h1>本地知识库</h1><p role="status">{error||'正在读取目录设置…'}</p>{error&&<button onClick={onRetry}>重新连接</button>}<div className="skeleton"/><div className="skeleton"/></div></main></div>;}
