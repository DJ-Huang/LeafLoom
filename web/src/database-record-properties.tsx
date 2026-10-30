import React,{useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {ArrowDown,ArrowUp,ChevronRight,GripVertical,MoreHorizontal,Pencil,Plus,Settings2,Trash2} from 'lucide-react';
import {t} from './i18n';
import {ActionMenu,FormDialog,MenuPoint,Modal} from './ui';
import {BaseConfig,Row,View,labelOf,valueOf} from './database-model';
import {Cell} from './database-cell';
import {FieldIcon} from './database-ui';
import {PropertySection,usePropertyDrag} from './database-property-drag';
import {DatabaseFieldEditor} from './database-field-editor';

// A combined view can reuse an explicitly configured, matching category layout.
export function recordDetailLayout(config:BaseConfig,view:View,row:Row){
 const source=Array.isArray(view.leafloom?.detailFields)?view:config.views.find(v=>Array.isArray(v.leafloom?.detailFields)&&v.leafloom?.conditions?.length&&v.leafloom.conditions.every((c:any)=>c.operator==='eq'&&JSON.stringify(valueOf(row,c.field))===JSON.stringify(c.value)))||view;
 const configured=source.leafloom?.detailFields;
 const keys:unknown[]=Array.isArray(configured)?configured:['title',...(source.order||[]),source.groupBy?.property,source.leafloom?.startField,source.leafloom?.endField,source.leafloom?.coverField];
 return {view:source,keys:[...new Set(keys)].filter((k):k is string=>typeof k==='string'&&!!config.fields[k])};
}

function AddRecordField({config,view,visible,commit,onClose}:{config:BaseConfig,view:View,visible:string[],commit:(cmd:any)=>Promise<any>,onClose:()=>void}){
 const revision=useRef(config.revision),[key]=useState(()=> 'field_'+crypto.randomUUID().replaceAll('-','').slice(0,12));
 const input=useRef<HTMLInputElement>(null);useEffect(()=>{input.current?.focus();},[]);
 const [name,setName]=useState(''),[type,setType]=useState('text'),[options,setOptions]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 return <Modal title={t('db.addField')} className="db-add-field-modal form-modal" icon={<Plus size={18}/>} onClose={()=>{if(!busy)onClose();}}><form onSubmit={async e=>{
  e.preventDefault();if(busy||!name.trim())return;setBusy(true);setError('');
  try{await commit({type:'field.set',key,displayName:name.trim(),field:{type,...(['select','multiselect'].includes(type)?{options:[...new Set(options.split(/[,，\n]/).map(v=>v.trim()).filter(Boolean))]}:{})},detail_view_id:view.id,detail_fields:visible,config_revision:revision.current});onClose();}
  catch(e){setError((e as Error).message);}finally{setBusy(false);}
 }}><fieldset disabled={busy}><label>{t('db.fieldName')}<input ref={input} autoFocus required value={name} onChange={e=>setName(e.target.value)}/></label><label>{t('db.fieldType')}<select value={type} onChange={e=>setType(e.target.value)}>{['text','number','select','multiselect','date','checkbox','url','attachment'].map(kind=><option key={kind} value={kind}>{t('db.type.'+kind)}</option>)}</select></label>{['select','multiselect'].includes(type)&&<label>{t('db.options')}<textarea rows={3} value={options} onChange={e=>setOptions(e.target.value)}/><small>{t('db.fieldOptionsHint')}</small></label>}<p className="db-panel-help">{t('db.addFieldDetailHint')}</p>{error&&<p role="alert" className="db-panel-error">{t(error)}</p>}</fieldset><footer className="modal-footer"><button type="button" disabled={busy} onClick={onClose}>{t('取消')}</button><button className="db-save-button" disabled={busy||!name.trim()}>{t('db.addField')}</button></footer></form></Modal>;
}

export function RecordProperties({config,view,row,busy,update,commit}:{config:BaseConfig,view:View,row:Row,busy:boolean,update:(row:Row,values:any)=>Promise<void>,commit:(cmd:any)=>Promise<any>}){
 const [adding,setAdding]=useState(false),[editingField,setEditingField]=useState(''),layout=recordDetailLayout(config,view,row);
 const extra=[...new Set<string>([...(Array.isArray(layout.view.leafloom?.detailExtraOrder)?layout.view.leafloom.detailExtraOrder:[]),...Object.keys(config.fields)])].filter(k=>!!config.fields[k]&&!layout.keys.includes(k));
 const host=useRef<HTMLDivElement>(null),alive=useRef(true),locked=useRef(false),renameInput=useRef<HTMLInputElement>(null),cancelRename=useRef(false);
 const [pending,setPending]=useState<{section:PropertySection,keys:string[]}>(),[renaming,setRenaming]=useState<{key:string,value:string,revision:string}>(),[renameBusy,setRenameBusy]=useState(false),[renameError,setRenameError]=useState('');
 const [menu,setMenu]=useState<{key:string,section:PropertySection,anchor:HTMLElement,point?:MenuPoint}>(),[deleting,setDeleting]=useState<{key:string,name:string,revision:string,dependencies:boolean}>();
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 useEffect(()=>{setMenu(undefined);if(renaming&&!config.fields[renaming.key])setRenaming(undefined);},[config.revision,layout.view.id]);
 useEffect(()=>{if(renaming){renameInput.current?.focus();renameInput.current?.select();}},[renaming?.key]);
 const blocked=busy||!!pending||renameBusy;
 const saveOrder=async(section:PropertySection,keys:string[])=>{
  if(blocked||locked.current)return;locked.current=true;setPending({section,keys});setMenu(undefined);
  try{await commit({type:'view.update',view_id:layout.view.id,patch:{leafloom:{[section==='visible'?'detailFields':'detailExtraOrder']:keys}},config_revision:config.revision});}
  catch{/* The shared model shows the save error; keep the previous layout. */}
  finally{locked.current=false;if(alive.current)setPending(undefined);}
 };
 const sorting=usePropertyDrag(host,config.revision+'\n'+layout.view.id,blocked,(section,keys)=>void saveOrder(section,keys));
 const keysFor=(section:PropertySection)=>(pending?.section===section?pending.keys:section==='visible'?layout.keys:extra).filter(k=>!!config.fields[k]);
 const editable=(key:string)=>!!config.fields[key]&&key!=='title'&&!key.startsWith('file.')&&!key.startsWith('formula.')&&!config.fields[key].readonly;
 const showMenu=(key:string,section:PropertySection,anchor:HTMLElement,point?:MenuPoint)=>{sorting.cancel();setMenu({key,section,anchor,point});};
 const shift=(key:string,section:PropertySection,delta:number)=>{const keys=[...keysFor(section)],index=keys.indexOf(key);if(index+delta<0||index+delta>=keys.length)return;[keys[index],keys[index+delta]]=[keys[index+delta],keys[index]];void saveOrder(section,keys);};
 const rename=async()=>{
  if(!renaming||locked.current||cancelRename.current)return;
  if(!config.fields[renaming.key]){setRenaming(undefined);return;}
  const name=renaming.value.trim();if(!name){setRenameError(t('db.fieldNameRequired'));renameInput.current?.focus();return;}
  if(name===t(labelOf(renaming.key,config.fields[renaming.key]))){setRenaming(undefined);return;}
  locked.current=true;setRenameBusy(true);setRenameError('');
  try{await commit({type:'field.set',key:renaming.key,field:{type:config.fields[renaming.key].type},displayName:name,config_revision:renaming.revision});if(alive.current)setRenaming(undefined);}
  catch{if(alive.current)renameInput.current?.focus();}
  finally{locked.current=false;if(alive.current)setRenameBusy(false);}
 };
 const property=(key:string,section:PropertySection)=>{
  const name=t(labelOf(key,config.fields[key])),keys=keysFor(section);
  return <div key={key} role="group" aria-label={name} data-detail-field={key} data-detail-section={section} className={'db-record-property-row'+(sorting.drag?.key===key?' is-drag-source':'')+(sorting.position?.key===key&&sorting.drag?.key!==key?' insert-'+(sorting.position.after?'after':'before'):'')} onContextMenu={event=>{const target=event.target as Element;if(target.closest('input,textarea')||target.closest('[contenteditable]')?.getAttribute('contenteditable')==='true')return;event.preventDefault();event.stopPropagation();showMenu(key,section,event.currentTarget.querySelector<HTMLElement>('.db-property-name')||event.currentTarget,{x:event.clientX,y:event.clientY});}}>
   <div className="db-property-label"><button className="db-property-grip" disabled={blocked||!!renaming} aria-label={t('db.dragProperty')+' '+name} title={t('db.dragProperty')} onPointerDown={event=>{setMenu(undefined);sorting.start(event,key,section,keys);}}><GripVertical size={13}/></button>
   {renaming?.key===key?<input ref={renameInput} className="db-property-rename" aria-label={t('db.fieldName')} value={renaming.value} disabled={renameBusy} onChange={event=>setRenaming({...renaming,value:event.target.value})} onBlur={()=>void rename()} onKeyDown={event=>{if(event.key==='Enter'){event.preventDefault();event.stopPropagation();void rename();}if(event.key==='Escape'){event.preventDefault();event.stopPropagation();cancelRename.current=true;setRenaming(undefined);setRenameError('');}}}/>:<button className="db-property-name" aria-haspopup="menu" title={name} onClick={event=>showMenu(key,section,event.currentTarget)} onKeyDown={event=>{if(event.key==='ContextMenu'||event.shiftKey&&event.key==='F10'){event.preventDefault();event.stopPropagation();showMenu(key,section,event.currentTarget);}else if(event.altKey&&['ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();event.stopPropagation();if(!blocked)shift(key,section,event.key==='ArrowUp'?-1:1);}}}><FieldIcon fieldKey={key} field={config.fields[key]}/><span>{name}</span></button>}
   <button className="db-property-menu-trigger" aria-label={t('db.propertyActions')+' '+name} aria-haspopup="menu" aria-expanded={menu?.key===key} title={t('db.propertyActions')} onClick={event=>showMenu(key,section,event.currentTarget)}><MoreHorizontal size={13}/></button></div>
   <Cell row={row} fieldKey={key} field={config.fields[key]} root={config.root} disabled={busy} update={update}/>
  </div>;
 };
 const menuKeys=menu?keysFor(menu.section):[],menuIndex=menu?menuKeys.indexOf(menu.key):-1;
 return <div ref={host} className="db-record-properties" aria-busy={!!pending||renameBusy}>{keysFor('visible').map(k=>property(k,'visible'))}{!!extra.length&&<details className="db-record-more-properties"><summary><ChevronRight size={14}/>{t('db.moreProperties',{count:extra.length})}</summary><div className="db-record-extra">{keysFor('extra').map(k=>property(k,'extra'))}</div></details>}{renameError&&<p role="alert" className="db-panel-error">{renameError}</p>}<button className="db-record-add-field" disabled={blocked} onClick={()=>setAdding(true)}><Plus size={15}/>{t('db.addField')}</button>
 {adding&&<AddRecordField config={config} view={layout.view} visible={layout.keys} commit={commit} onClose={()=>setAdding(false)}/>}
 {editingField&&<DatabaseFieldEditor key={editingField} config={config} fieldKey={editingField} commit={commit} onClose={()=>setEditingField('')}/>}
 {menu&&<ActionMenu title={t('db.propertyActions')} className="db-record-menu db-property-menu" anchor={menu.anchor} point={menu.point} portalTarget={menu.anchor.closest<HTMLElement>('dialog')||undefined} onClose={()=>setMenu(undefined)}><button disabled={blocked||!editable(menu.key)} onClick={()=>setEditingField(menu.key)}><Settings2 size={14}/>{t('db.editField')}</button><button disabled={blocked||!editable(menu.key)} onClick={()=>{cancelRename.current=false;setRenameError('');setRenaming({key:menu.key,value:t(labelOf(menu.key,config.fields[menu.key])),revision:config.revision});}}><Pencil size={14}/>{t('重命名')}</button>{[-1,1].map(delta=><button key={delta} disabled={blocked||menuIndex+delta<0||menuIndex+delta>=menuKeys.length} onClick={()=>shift(menu.key,menu.section,delta)}>{delta<0?<ArrowUp size={14}/>:<ArrowDown size={14}/>} {t(delta<0?'db.moveUp':'db.moveDown')}</button>)}<hr/><button className="db-record-menu-danger" disabled={blocked||!editable(menu.key)} onClick={()=>{const key=menu.key,dependencies=config.views.some(v=>v.groupBy?.property===key||v.sort?.some(s=>s.property===key)||v.leafloom?.conditions?.some((c:any)=>c.field===key)||['startField','endField','coverField'].some(k=>v.leafloom?.[k]===key))||!!config.tasks&&Object.values(config.tasks).includes(key);setDeleting({key,name:t(labelOf(key,config.fields[key])),revision:config.revision,dependencies});}}><Trash2 size={14}/>{t('db.deleteField')}</button>{!editable(menu.key)&&<p className="db-property-menu-hint">{t('db.builtInFieldProtected')}</p>}</ActionMenu>}
 {deleting&&<FormDialog title={t('db.deleteField')} className="db-delete-field-modal" danger description={t('db.deleteFieldDescription',{name:deleting.name})+(deleting.dependencies?' '+t('db.deleteFieldDependencies'):'')} submitLabel={t('db.deleteField')} onClose={()=>setDeleting(undefined)} onSubmit={async()=>{await commit({type:'field.remove',key:deleting.key,config_revision:deleting.revision});}}/>}
 {sorting.drag&&createPortal(<div className="db-property-drag-overlay" aria-hidden="true" style={{left:Math.max(8,Math.min(sorting.drag.x+12,window.innerWidth-208)),top:Math.min(sorting.drag.y+12,window.innerHeight-48)}}><FieldIcon fieldKey={sorting.drag.key} field={config.fields[sorting.drag.key]}/>{t(labelOf(sorting.drag.key,config.fields[sorting.drag.key]))}</div>,host.current?.closest('dialog')||document.body)}
 </div>;
}
