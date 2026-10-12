import React,{useEffect,useRef,useState} from 'react';
import cytoscape from 'cytoscape';
import {OpenNote} from './api';
import {useApi} from './hooks';
import {Modal} from './ui';
export function GraphView({path,onOpen,onClose}:{path:string,onOpen:OpenNote,onClose:()=>void}){
 const [all,setAll]=useState(!path);const {data}=useApi('graph'+(!all&&path?'?path='+encodeURIComponent(path):''));const container=useRef<HTMLDivElement>(null);
 useEffect(()=>{if(!data||!container.current)return;const cy=cytoscape({container:container.current,elements:[...data.nodes.map((n:any)=>({data:{id:n.id,label:n.label}})),...data.links.map((l:any,i:number)=>({data:{id:'e'+i,source:l.source,target:l.target}}))],style:[{selector:'node',style:{'background-color':'#787770','width':14,'height':14,'label':'data(label)','font-size':10,'color':'#37352f','text-valign':'bottom','text-margin-y':6}},{selector:'edge',style:{'width':1,'line-color':'#cccac3','opacity':0.55}},{selector:':selected',style:{'background-color':'#529cca'}}],layout:{name:data.nodes.length>100?'concentric':'cose',animate:false} as any});cy.on('tap','node',e=>{onOpen(e.target.id());onClose();});return()=>cy.destroy();},[data,onOpen]);
 return <Modal title="笔记关系" onClose={onClose} wide><div className="graph-controls"><button className={!all?'active':''} onClick={()=>setAll(false)}>当前笔记</button><button className={all?'active':''} onClick={()=>setAll(true)}>全部笔记</button><span className="hint">点击节点打开文档，滚轮缩放</span></div><div className="graph" ref={container}/></Modal>;
}

