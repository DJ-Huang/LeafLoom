import React,{useEffect,useState} from 'react';
import {api,OpenNote} from './api';
import {t,useLocale} from './i18n';
import {Modal} from './ui';

type Page={id:string,name:string,group?:string};
type Report={revision:string,missing_pages:{id:string,name:string}[],dynamic_warning:boolean};

export function DesignExport({pages,root,directory,revision,pending,notify,onOpenNote,onClose}:{pages:Page[],root:string,directory:string,revision:string,pending:boolean,notify:(message:string)=>void,onOpenNote?:OpenNote,onClose:()=>void}){
 useLocale();
 const [selected,setSelected]=useState(()=>pages.map(page=>page.id));
 const [report,setReport]=useState<(Report&{selectionKey:string})|null>(null),[checking,setChecking]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const selectionKey=JSON.stringify(selected);
 useEffect(()=>{
  let active=true;setReport(null);setError('');
  if(!selected.length||pending){setChecking(false);return ()=>{active=false;};}
  setChecking(true);
  const timer=setTimeout(()=>{void api<Report>('design/export/preflight',{root,directory,page_ids:selected,expected_revision:revision}).then(value=>{if(active)setReport({...value,selectionKey});}).catch(reason=>{if(active)setError((reason as Error).message);}).finally(()=>{if(active)setChecking(false);});},200);
  return ()=>{active=false;clearTimeout(timer);};
 },[selectionKey,root,directory,revision,pending]);
 const close=()=>{if(!busy)onClose();};
 const run=async()=>{
  if(!report||report.selectionKey!==selectionKey||report.revision!==revision||pending||!selected.length)return;
  setBusy(true);setError('');
  try{
   const result=await api<{url?:string,path?:string}>('design/export',{root,directory,page_ids:selected,expected_revision:report.revision});
   if(result.url){const anchor=document.createElement('a');anchor.href=result.url;anchor.download='';anchor.rel='noopener';anchor.click();}
   else if(result.path)onOpenNote?.(result.path);
   notify(t('已导出独立运行项目'));onClose();
  }catch(reason){setError((reason as Error).message);}finally{setBusy(false);}
 };
 return <Modal title={t('导出 HTML')} onClose={close} className="dw-export-modal">
  <div className="dw-export-body">
   <p className="dw-hint">{t('选择页面并导出已保存的交互式 HTML ZIP。按原顺序播放，首页为第一个所选页面。')}</p>
   <p className="dw-hint">{t('外部网址不会打包；离线使用前请检查引用和交互。')}</p>
   <div className="dw-export-select"><strong>{t('选择页面')} · {selected.length} / {pages.length}</strong><div><button type="button" disabled={busy} onClick={()=>setSelected(pages.map(page=>page.id))}>{t('全选')}</button><button type="button" disabled={busy} onClick={()=>setSelected([])}>{t('取消全选')}</button></div></div>
   <div className="dw-export-pages">{pages.map(page=><label className="dw-export-page" key={page.id}><input data-testid={'export-page-'+page.id} type="checkbox" disabled={busy} checked={selected.includes(page.id)} onChange={()=>setSelected(selected.includes(page.id)?selected.filter(id=>id!==page.id):[...selected,page.id])}/><span>{page.name}{page.group&&<small>{page.group}</small>}</span></label>)}</div>
   {checking&&<p role="status" className="dw-hint">{t('正在检查页面依赖…')}</p>}
   {report?.missing_pages.length? <div className="dw-export-warning"><strong>{t('以下关联页面未选择')}</strong><p>{t('跳转到未选择的页面将不可用，嵌入的页面将留空。可以补选后再导出。')}</p>{report.missing_pages.map(page=><button type="button" key={page.id} disabled={busy} onClick={()=>setSelected(current=>[...current,page.id])}>+ {page.name}</button>)}</div>:null}
   {report?.dynamic_warning&&<p className="dw-export-warning">{t('脚本中的动态素材和页面跳转可能无法自动识别，请解压后检查交互；如有遗漏，请补选页面或检查脚本引用。')}</p>}
   {pending&&<p className="dw-export-warning">{t('请先完成待保存修改')}</p>}
   {error&&<p role="alert" className="error">{error}</p>}
  </div>
  <footer className="modal-footer"><button type="button" disabled={busy} onClick={close}>{t('取消')}</button><button type="button" data-testid="export-selected" className="primary" disabled={!selected.length||pending||checking||!report||report.selectionKey!==selectionKey||report.revision!==revision||busy} onClick={()=>void run()}>{t(busy?'导出中…':'导出 HTML ZIP')}</button></footer>
 </Modal>;
}
