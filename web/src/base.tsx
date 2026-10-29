import React,{lazy,Suspense,useEffect,useRef,useState} from 'react';
import {t,useLocale,getLocale} from './i18n';
import {api,OpenNote} from './api';
import {ActionMenu,FormDialog,Modal,MenuPoint} from './ui';
import {VirtualList,VirtualTableBody} from './virtual';
import {LegacyBaseViewer} from './base-legacy';
import {BaseConfig,Field,Row,View,labelOf,useDatabase,valueOf} from './database-model';
import {DatabaseSettings} from './database-controls';
import {AttachmentPicker,ResolvedMedia,RecordVideo,imageRef,videoRef,refPath} from './database-media';
import {Timeline} from './database-timeline';
import {DatabaseBoard} from './database-board';
import {DatabaseViewDialog} from './database-board-setup';
import {Table2,Plus,Search,Filter,ArrowDownUp,Columns3,SlidersHorizontal,Settings2,ArrowUpRight,FolderOpen,FileText,Paperclip,Calendar,Image as ImageIcon} from 'lucide-react';
import {Cell} from './database-cell';
import {DatabaseTable} from './database-table';
import {RecordAction,RecordMenuItems,RecordMenuRenderer,RecordMenuTrigger} from './database-record-menu';
import {ViewIcon,FieldIcon,Tag,RecentBadge} from './database-ui';
import './database.css';
const DocumentPane=lazy(()=>import('./document').then(m=>({default:m.DocumentPane})));
const labels:Record<string,string>={table:'db.table',list:'db.list',cards:'db.gallery',leafloomTimeline:'db.timeline',leafloomBoard:'db.board'};
export const viewLabel=(v:View)=>['Table','List','Gallery','Timeline','Board'].includes(v.name)?t(labels[v.type]||v.name):v.name;
function Gallery({rows,config,view,open,play}:{rows:Row[],config:BaseConfig,view:View,open:(r:Row)=>void,play:(r:Row,v:string)=>void}){
 const host=useRef<HTMLDivElement>(null),[columns,setColumns]=useState(3),size=view.leafloom?.cardSize||'medium',target=size==='small'?200:size==='large'?400:290;
 useEffect(()=>{const observer=new ResizeObserver(entries=>setColumns(Math.max(1,Math.floor(entries[0].contentRect.width/target))));if(host.current)observer.observe(host.current);return()=>observer.disconnect();},[target]);
 const chunks:Row[][]=[];for(let i=0;i<rows.length;i+=columns)chunks.push(rows.slice(i,i+columns));
 return <div ref={host} className="db-gallery"><VirtualList threshold={20} items={chunks} itemKey={chunk=>chunk[0].path} estimate={370} height={560} render={chunk=><div className="db-gallery-row" style={{gridTemplateColumns:`repeat(${columns},minmax(0,1fr))`}}>{chunk.map(row=>{const attachments=Object.keys(config.fields).filter(k=>config.fields[k].type==='attachment').flatMap(k=>{const value=valueOf(row,k);return Array.isArray(value)?value:[];}),chosen=valueOf(row,view.leafloom?.coverField||''),cover=[...(Array.isArray(chosen)?chosen:chosen?[chosen]:[]),...attachments].find(imageRef),video=attachments.find(videoRef);return <article key={row.path} className="db-card" data-db-record={row.path}><RecordMenuTrigger row={row}/><div className="db-card-cover">{cover?<ResolvedMedia reference={cover} source={row.path} root={config.root} fit={view.leafloom?.fit} onClick={()=>open(row)}/>:<button className="db-media-placeholder" onClick={()=>open(row)}>{t('db.noCover')}</button>}{video&&<button className="db-play" aria-label={t('db.video')+' '+row.title} onClick={()=>play(row,video)}><span>▶</span></button>}</div><div className="db-card-body"><button className="db-card-title" onClick={()=>open(row)}>{row.title}<RecentBadge row={row}/></button>{(view.order||[]).filter(k=>k!=='title'&&k!=='file.name').map(k=>{const value=valueOf(row,k);if(value===null||value===undefined||value===''||(Array.isArray(value)&&!value.length))return null;return <div className="db-card-property" key={k} title={t(labelOf(k,config.fields[k]))}><FieldIcon fieldKey={k} field={config.fields[k]} size={13}/>{['select','multiselect'].includes(config.fields[k]?.type)?<div className="db-card-tags">{(Array.isArray(value)?value:[value]).map(v=><Tag key={String(v)} value={String(v)} field={config.fields[k]}/>)}</div>:<strong>{Array.isArray(value)?value.map(v=>config.fields[k]?.type==='attachment'?refPath(String(v)).split('/').pop():String(v)).join(' · '):String(value)}</strong>}</div>;})}</div></article>;})}</div>}/></div>;
}
export function BaseViewer({path,onOpen,notify,viewId:initialView='',embedded=false}:{path:string,onOpen:OpenNote,notify:(s:string)=>void,viewId?:string,embedded?:boolean}){
 useLocale();const model=useDatabase(path,initialView),{config,view,rows}=model;
 const [boardRows,setBoardRows]=useState<Row[]>([]),[createdVisible,setCreatedVisible]=useState<boolean>();
 const [section,setSection]=useState(''),[dialog,setDialog]=useState(''),[selected,setSelected]=useState<Row>(),[video,setVideo]=useState<{row:Row,ref:string}>(),[newlyCreated,setNewlyCreated]=useState(''),[settingsAnchor,setSettingsAnchor]=useState<HTMLElement|null>(null);
 const [recordMenu,setRecordMenu]=useState<{row:Row,anchor:HTMLElement,point?:MenuPoint}>(),[renameTarget,setRenameTarget]=useState<Row>(),[trashTarget,setTrashTarget]=useState<Row>();
 useEffect(()=>{setRecordMenu(undefined);setRenameTarget(undefined);setTrashTarget(undefined);},[path,config?.root,view?.id]);
 const pointerCleanup=useRef<()=>void>(()=>{});
 const databaseHost=useRef<HTMLDivElement>(null),recentPath=model.recentRows[0]?.path;
 useEffect(()=>{
  if(!recentPath||view?.type==='leafloomBoard')return;
  databaseHost.current?.querySelectorAll<HTMLElement>('.db-table-scroll,.db-list>.virtual-list,.db-gallery>.virtual-list').forEach(node=>{node.scrollTop=0;});
  const frame=requestAnimationFrame(()=>databaseHost.current?.querySelector<HTMLElement>('[data-db-record="'+CSS.escape(recentPath)+'"]')?.scrollIntoView({block:'nearest',inline:'nearest'}));
  return()=>cancelAnimationFrame(frame);
 },[recentPath,view?.id,view?.type]);
 useEffect(()=>()=>pointerCleanup.current(),[]);
 const isolatePointer=(event:React.PointerEvent<HTMLDivElement>)=>{
  event.stopPropagation();if(!event.isPrimary)return;pointerCleanup.current();
  // Native dragstart targets the draggable NodeView ancestor, outside this React root.
  // Suspend only its DOM drag flag; the parent ProseMirror document stays untouched.
  const ancestors:HTMLElement[]=[];let node=event.currentTarget.parentElement;
  while(node){if(node.getAttribute('draggable')==='true'){ancestors.push(node);node.setAttribute('draggable','false');}node=node.parentElement;}
  const owner=event.currentTarget.ownerDocument,pointer=event.pointerId;
  const restore=()=>{ancestors.forEach(node=>node.setAttribute('draggable','true'));owner.removeEventListener('pointerup',finish,true);owner.removeEventListener('pointercancel',finish,true);window.removeEventListener('blur',restore);};
  const finish=(next:PointerEvent)=>{if(next.pointerId===pointer)restore();};
  owner.addEventListener('pointerup',finish,true);owner.addEventListener('pointercancel',finish,true);window.addEventListener('blur',restore);pointerCleanup.current=restore;
 };
 const showSettings=(section:string,anchor:HTMLElement)=>{setSettingsAnchor(anchor);setSection(section);};
 useEffect(()=>{if(selected){const fresh=[...rows,...boardRows].find(r=>r.path===selected.path);if(fresh&&fresh.revision!==selected.revision)setSelected(fresh);}},[rows,boardRows]);
 useEffect(()=>{if(!selected||!config)return;let alive=true;void api<any>('file?'+new URLSearchParams({path:selected.path,root:config.root}),undefined,'GET',{force:true}).then(note=>{if(alive&&note.root===config.root)setSelected(old=>old&&old.path===note.path&&old.revision!==note.etag?{...old,title:note.metadata.name||note.metadata.title||old.title,metadata:note.metadata,revision:note.etag}:old);}).catch(()=>{});return()=>{alive=false;};},[config,selected?.path]);
 const commit=async(cmd:any)=>{try{return await model.command(cmd);}catch(e){model.setError((e as Error).message);throw e;}};
 const update=async(row:Row,values:any)=>{try{const result=await commit({type:'record.update',path:row.path,record_revision:row.revision,values});if(result.note)setSelected(old=>old?.path===row.path?{...old,title:result.note.metadata.title||result.note.metadata.name||old.title,metadata:result.note.metadata,revision:result.note.etag}:old);}catch(e){notify(t((e as Error).message));throw e;}};
 const recordAction=(action:RecordAction,row:Row)=>{
  if(!config||!view)return;setRecordMenu(undefined);
  if(action==='peek')setSelected(row);
  else if(action==='full'){setSelected(undefined);onOpen(row.path);}
  else if(action==='rename')setRenameTarget(row);
  else if(action==='trash')setTrashTarget(row);
  else if(action==='copy-link')void navigator.clipboard.writeText('[['+row.path+']]').then(()=>notify(t('db.noteLinkCopied'))).catch(()=>notify(t('db.noteLinkFailed')));
  else if(action==='duplicate')void commit({type:'record.duplicate',path:row.path,record_revision:row.revision,title:t('db.copyTitle',{title:row.title}),view_id:view.id,search:model.search}).then(result=>{setNewlyCreated(result.path);setCreatedVisible(result.visible!==false);notify(t(result.visible===false?'db.createdOutsideView':'db.recordDuplicated'));}).catch(e=>notify(t(e.message)));
 };
 const recordMenuItems:RecordMenuRenderer=(row,disabled,extra)=><RecordMenuItems row={row} disabled={disabled||model.busy} onAction={recordAction}>{extra}</RecordMenuItems>;
 const showRecordMenu=(event:React.MouseEvent|React.KeyboardEvent,point?:MenuPoint)=>{
  const target=event.target as Element;
  if(target.closest('input,textarea,select')||target.closest('[contenteditable]')?.getAttribute('contenteditable')==='true')return;
  const element=target.closest<HTMLElement>('[data-db-record]');if(!element||!event.currentTarget.contains(element))return;
  const row=[...rows,...boardRows].find(r=>r.path===element.dataset.dbRecord);if(!row)return;
  event.preventDefault();event.stopPropagation();
  const anchor=target.closest<HTMLElement>('button,a,[tabindex]')||element.querySelector<HTMLElement>('button')||element;
  setRecordMenu({row,anchor,point});
 };
 if(!config)return <div className="pad">{model.error?<><p role="alert">{t(model.error)}</p><button onClick={model.reload}>{t('db.reload')}</button></>:t('正在加载视图…')}</div>;
 const unknown=!view;
 if(unknown)return <div className="pad"><p>{t('db.missingView')}</p><button onClick={()=>model.setViewId('')}>{t('db.defaultView')}</button></div>;
 if(!view.supported)return <><div className="db-legacy-switch">{config.views.map(v=><button key={v.id} onClick={()=>model.setViewId(v.id)}>{viewLabel(v)}</button>)}</div>{(view.type==='tasknotesKanban'||view.type.toLowerCase().includes('tasklist')||view.type.toLowerCase().includes('calendar'))?<LegacyBaseViewer initialIndex={config.views.indexOf(view)} path={path} onOpen={onOpen} notify={notify}/>:<p className="pad">{t('db.unsupportedView')} · {view.type}</p>}</>;
 const order=(view.order||['title',...Object.keys(config.fields).filter(k=>!config.fields[k].readonly)]).filter(k=>k!=='title'&&k!=='file.name'&&config.fields[k]);
 const group=view.groupBy?.property;
 const groupLabel=(row:Row,index:number)=>group&&(index===0||JSON.stringify(valueOf(rows[index-1],group))!==JSON.stringify(valueOf(row,group)))?<h3 className="db-group-heading">{String(valueOf(row,group)??t('db.ungrouped'))}</h3>:null;
 return <div ref={databaseHost} className={'database '+(embedded?'db-embedded':'')} data-database={path} onContextMenu={e=>showRecordMenu(e,{x:e.clientX,y:e.clientY})} onClick={e=>{if((e.target as Element).closest('[data-db-record-menu]'))showRecordMenu(e);}} onKeyDown={e=>{if(e.key==='ContextMenu'||e.shiftKey&&e.key==='F10')showRecordMenu(e);if(e.ctrlKey||e.metaKey)e.stopPropagation();}} onPointerDown={isolatePointer} onDragStart={e=>{e.preventDefault();e.stopPropagation();}}>
 <header className="db-header"><div className="db-page-mark"><Table2 size={30} strokeWidth={1.4}/></div><div className="db-heading-line"><h1>{path.split('/').pop()?.replace(/\.base$/,'')}</h1>{embedded&&<button className="db-quiet-button" onClick={()=>onOpen(path)}><ArrowUpRight size={14}/>{t('db.fullPage')}</button>}</div><div className="db-page-meta"><span>{t('db.database')}</span><span className="db-meta-dot">·</span><FolderOpen size={13}/><span>{config.folder||t('知识库根目录')}</span></div></header>
 <div className="db-view-bar"><nav className="db-view-tabs" aria-label={t('db.views')}>{config.views.map(v=><button key={v.id} className={view.id===v.id?'active':''} aria-pressed={view.id===v.id} onClick={()=>model.setViewId(v.id)}><ViewIcon type={v.type}/><span>{viewLabel(v)}</span></button>)}<button className="db-add-view" title={t('db.addView')} aria-label={t('db.addView')} onClick={()=>setDialog('view')}><Plus size={16}/></button></nav>
 <div className="db-toolbar"><button className={'db-tool'+(view.leafloom?.conditions?.length?' is-active':'')} onClick={e=>showSettings('filter',e.currentTarget)}><Filter size={14}/><span>{t('db.filter')}</span>{!!view.leafloom?.conditions?.length&&<i/>}</button><button className={'db-tool'+(view.sort?.length?' is-active':'')} onClick={e=>showSettings('sort',e.currentTarget)}><ArrowDownUp size={14}/><span>{t('db.sort')}</span></button><span className="db-toolbar-divider"/><label className="db-search"><Search size={15}/><input aria-label={t('db.search')} placeholder={t('db.search')} value={model.search} onChange={e=>model.setSearch(e.target.value)}/></label>{[{key:'group',Icon:Columns3},{key:'fields',Icon:SlidersHorizontal},{key:'layout',Icon:Settings2}].map(({key,Icon})=><button className="db-icon-button" key={key} aria-label={t('db.'+key)} title={t('db.'+key)} onClick={e=>showSettings(key,e.currentTarget)}><Icon size={16}/></button>)}<button className="db-new-button" disabled={model.busy} onClick={()=>setDialog('record')}><Plus size={14}/>{t('db.addRecord')}</button></div></div>
 {model.error&&<div className="db-error" role="alert">{t(model.error)} <button onClick={model.reload}>{t('db.reload')}</button></div>}
 {view.type==='leafloomBoard'?<DatabaseBoard key={config.root+'\n'+path+'\n'+view.id} config={config} view={view} summary={model.boardSummary} search={model.search} busy={model.busy} commit={commit} open={setSelected} notify={notify} reload={model.reload} onRecords={records=>{setBoardRows(records);model.confirmRecent(records);}} recentRows={model.recentRows} recordMenu={recordMenuItems} onCreated={(path,visible)=>{setNewlyCreated(path);setCreatedVisible(visible);notify(t(visible?'db.createdRecord':'db.createdOutsideView'));}} configure={anchor=>showSettings('group',anchor)}/>:view.type==='table'?<DatabaseTable config={config} view={view} rows={rows} order={order} busy={model.busy} update={update} commit={commit} open={setSelected} add={()=>setDialog('record')} fields={anchor=>showSettings('fields',anchor)}/>:view.type==='list'?<div className="db-list"><VirtualList items={rows} itemKey={r=>r.path} height={560} estimate={70} render={(row,i)=><div>{groupLabel(row,i)}<div className="db-list-row" data-db-record={row.path}><button className="db-list-title" onClick={()=>setSelected(row)}><FileText size={16} strokeWidth={1.5}/><span>{row.title}</span><RecentBadge row={row}/><ArrowUpRight size={13}/></button>{order.map(k=><div key={k} className="db-list-field"><small>{t(labelOf(k,config.fields[k]))}</small><Cell row={row} fieldKey={k} field={config.fields[k]} root={config.root} disabled={model.busy} update={update}/></div>)}<RecordMenuTrigger row={row}/></div></div>}/></div>:view.type==='cards'?group?<>{[...new Set(rows.map(r=>JSON.stringify(valueOf(r,group))))].map(g=><section key={g}><h3 className="db-group-heading">{String(g?JSON.parse(g):t('db.ungrouped'))}</h3><Gallery rows={rows.filter(r=>JSON.stringify(valueOf(r,group))===g)} config={config} view={view} open={setSelected} play={(row,ref)=>setVideo({row,ref})}/></section>)}</>:<Gallery rows={rows} config={config} view={view} open={setSelected} play={(row,ref)=>setVideo({row,ref})}/>:<Timeline rows={rows} view={view} disabled={model.busy} update={update} open={setSelected}/>}
 {!rows.length&&!model.error&&!['table','leafloomBoard'].includes(view.type)&&<div className="db-empty"><ViewIcon type={view.type} size={30}/><strong>{t('db.noRecords')}</strong><span>{t('db.emptyHint')}</span><button className="db-quiet-button" onClick={()=>setDialog('record')}><Plus size={15}/>{t('db.addRecord')}</button></div>}{model.cursor&&<button className="db-load-more" disabled={model.busy} onClick={()=>void model.load(model.cursor)}>{t('db.loadMore')}</button>}
 <div className="db-footer"><p className="db-status" role="status"><FileText size={12}/>{view.type==='leafloomBoard'?new Set([...boardRows,...model.recentRows].map(r=>r.path)).size:rows.length} / {Math.max(model.total,view.type==='leafloomBoard'?new Set([...boardRows,...model.recentRows].map(r=>r.path)).size:rows.length)} <span>{t('db.records')}</span>{newlyCreated&&<span> · {t((createdVisible??rows.some(r=>r.path===newlyCreated))?'db.createdRecord':'db.createdOutsideView')}</span>}</p><span className="db-storage-hint" title={t('db.noteRecords')}>{t('db.localNotes')}</span></div>
 {section&&<DatabaseSettings anchor={settingsAnchor} key={section} config={config} view={view} section={section} commit={commit} onClose={()=>setSection('')}/>}
 {dialog==='record'&&<FormDialog className="db-form-modal" title={t('db.addRecord')} fields={[{name:'title',label:t('db.title'),required:true}]} onClose={()=>setDialog('')} onSubmit={async v=>{const result=await commit({type:'record.create',title:v.title,values:{},view_id:view.id,search:model.search});setNewlyCreated(result.path);setCreatedVisible(result.visible!==false);notify(t(result.visible===false?'db.createdOutsideView':'db.createdRecord'));}}/>}
 {dialog==='view'&&<DatabaseViewDialog config={config} order={order} commit={commit} onClose={()=>setDialog('')} onCreated={model.setViewId}/>}
 {selected&&<Modal title={selected.title} className="db-record-modal" wide onClose={()=>setSelected(undefined)}><div className="db-record-actions"><button className="db-quiet-button" onClick={()=>{onOpen(selected.path);setSelected(undefined);}}>{t('db.fullPage')}</button><button disabled={model.busy} className="db-quiet-button db-danger-action" onClick={()=>setTrashTarget(selected)}>{t('移到回收站')}</button></div>{model.error&&<p className="db-error" role="alert">{t(model.error)}</p>}<div className="db-record-properties">{Object.entries(config.fields).map(([k,f])=><label key={k}><span><FieldIcon fieldKey={k} field={f}/>{t(labelOf(k,f))}</span><Cell row={selected} fieldKey={k} field={f} root={config.root} disabled={model.busy} update={update}/></label>)}</div><Suspense fallback={<p>{t('正在打开内容…')}</p>}><DocumentPane path={selected.path} vaultRoot={config.root} onOpen={(target,anchor)=>{onOpen(target,anchor);setSelected(undefined);}} notify={notify} onRecord={()=>{}}/></Suspense></Modal>}
 {recordMenu&&<ActionMenu title={t('db.recordActions')} className="db-record-menu" anchor={recordMenu.anchor} point={recordMenu.point} onClose={()=>setRecordMenu(undefined)}>{recordMenuItems(recordMenu.row,model.busy)}</ActionMenu>}
 {renameTarget&&<FormDialog title={t('重命名')} className="db-form-modal" fields={[{name:'title',label:t('db.title'),value:renameTarget.title,required:true}]} onClose={()=>setRenameTarget(undefined)} onSubmit={async values=>{const title=values.title.trim();if(!title)throw new Error(t('db.titleRequired'));await update(renameTarget,{title});notify(t('db.recordRenamed'));}}/>}
 {trashTarget&&<FormDialog title={t('移到回收站')} description={t('db.trashRecordPrompt',{title:trashTarget.title})} submitLabel={t('移到回收站')} danger onClose={()=>setTrashTarget(undefined)} onSubmit={async()=>{const command={type:'record.trash',path:trashTarget.path,record_revision:trashTarget.revision};const preview=await commit({...command,dry_run:true});await commit({...command,dry_run:false,operation_token:preview.operation_token});setSelected(old=>old?.path===trashTarget.path?undefined:old);notify(t('db.recordTrashed'));}}/>}
 {video&&<RecordVideo reference={video.ref} source={video.row.path} root={config.root} onClose={()=>setVideo(undefined)}/>}
 </div>;
}
export function CreateDatabaseDialog({folder,onOpen,onClose}:{folder:string,onOpen:OpenNote,onClose:()=>void}){
 const operationId=useRef(crypto.randomUUID());
 return <FormDialog className="db-form-modal" title={t('db.create')} description={t('db.createHelp')} fields={[{name:'name',label:t('db.databaseName'),required:true},{name:'folder',label:t('db.recordFolder'),value:''},{name:'preset',label:t('db.template'),value:'basic',options:[{value:'basic',label:t('db.basicTemplate')},{value:'tasks',label:t('db.taskPreset')}]}]} onClose={onClose} onSubmit={async v=>{const session=await api<any>('session');if(/[\\/]/.test(v.name))throw new Error(t('db.invalidName'));const path=[folder,v.name.replace(/\.base$/,'')+'.base'].filter(Boolean).join('/');const operation_id=operationId.current;await api('bases/commands',{path,command:{type:'create',folder:v.folder||path.replace(/\.base$/,''),preset:v.preset},workspace_revision:session.config.revision,operation_id});onOpen(path);}}/>;
}
