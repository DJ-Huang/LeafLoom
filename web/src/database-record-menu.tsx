import React from 'react';
import {Copy,FileText,Link,MoreHorizontal,PanelRight,Pencil,Trash2,ArrowUpRight} from 'lucide-react';
import {t} from './i18n';
import {Row} from './database-model';

export type RecordAction='peek'|'full'|'rename'|'duplicate'|'copy-link'|'trash';
export type RecordMenuRenderer=(row:Row,disabled:boolean,extra?:React.ReactNode)=>React.ReactNode;
export function RecordMenuTrigger({row}:{row:Row}){
 return <button type="button" className="db-record-more" data-db-record-menu aria-haspopup="menu" aria-label={t('db.recordActions')+' '+row.title} title={t('db.recordActions')}><MoreHorizontal size={15}/></button>;
}
export function RecordMenuItems({row,disabled,onAction,children}:{row:Row,disabled:boolean,onAction:(action:RecordAction,row:Row)=>void,children?:React.ReactNode}){
 return <><div className="db-record-menu-caption"><FileText size={14}/><span>{row.title}</span></div>
  <button onClick={()=>onAction('peek',row)}><PanelRight size={15}/><span>{t('db.openPeek')}</span></button>
  <button onClick={()=>onAction('full',row)}><ArrowUpRight size={15}/><span>{t('db.openPage')}</span></button>
  <hr/>
  <button disabled={disabled} onClick={()=>onAction('rename',row)}><Pencil size={15}/><span>{t('重命名')}</span></button>
  <button disabled={disabled} onClick={()=>onAction('duplicate',row)}><Copy size={15}/><span>{t('db.duplicateRecord')}</span></button>
  <button onClick={()=>onAction('copy-link',row)}><Link size={15}/><span>{t('db.copyNoteLink')}</span></button>
  {children&&<><hr/>{children}</>}
  <hr/>
  <button disabled={disabled} className="db-record-menu-danger" onClick={()=>onAction('trash',row)}><Trash2 size={15}/><span>{t('移到回收站')}</span></button>
 </>;
}
