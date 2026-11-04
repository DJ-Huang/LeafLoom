import React,{useEffect,useRef,useState} from 'react';
import {Check,Palette,Plus,Settings2,Trash2} from 'lucide-react';
import {t} from './i18n';
import {ActionMenu,FormDialog,Modal} from './ui';
import {BaseConfig,labelOf} from './database-model';
import {optionLabel} from './database-ui';

type Choice={value:string,label:string,color:string};
const colors=['default','gray','blue','green','red','orange','yellow','purple','pink'];
const kinds=['text','number','select','multiselect','date','checkbox','url','attachment'];

export function DatabaseFieldEditor({config,fieldKey,commit,onClose}:{config:BaseConfig,fieldKey:string,commit:(command:any)=>Promise<any>,onClose:()=>void}){
 const original=useRef(config.fields[fieldKey]).current,revision=useRef(config.revision),input=useRef<HTMLInputElement>(null),newChoiceInput=useRef<HTMLInputElement>(null);
 const retired=useRef(new Map<string,Choice>());
 const [name,setName]=useState(()=>t(labelOf(fieldKey,original))),[kind,setKind]=useState(original.type),[choices,setChoices]=useState<Choice[]>(()=>[...new Set(original.options||[])].map(value=>({value,label:optionLabel(value,original),color:original.optionMeta?.[value]?.color||'default'})));
 const [newChoice,setNewChoice]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),[removing,setRemoving]=useState<Choice>(),[palette,setPalette]=useState<{value:string,anchor:HTMLElement}>();
 const tasks=useRef(config.tasks?.statusField===fieldKey?config.tasks:undefined).current,[initial,setInitial]=useState(tasks?.initialStatus||''),[completed,setCompleted]=useState(tasks?.completedStatuses||[]);
 const selection=['select','multiselect'].includes(kind),roleInvalid=!!tasks&&(!choices.some(c=>c.value===initial)||!completed.length||completed.some(value=>!choices.some(c=>c.value===value)));
 const fixedType=!!config.tasks&&[config.tasks.statusField,config.tasks.priorityField,config.tasks.dueField].includes(fieldKey)||config.views.some(v=>v.type==='leafloomBoard'&&v.groupBy?.property===fieldKey||v.type==='leafloomTimeline'&&[v.leafloom?.startField,v.leafloom?.endField].includes(fieldKey));
 useEffect(()=>{input.current?.focus();input.current?.select();},[]);
 const patch=(value:string,change:Partial<Choice>)=>setChoices(old=>old.map(c=>c.value===value?{...c,...change}:c));
 const add=()=>{
  const label=newChoice.trim();if(!label)return;
  if(choices.some(c=>c.label.trim().toLocaleLowerCase()===label.toLocaleLowerCase())){setError(t('db.duplicateOption'));return;}
  const reserved=new Set([...(original.options||[]),...Object.keys(original.optionMeta||{}),...choices.map(c=>c.value)]),value=reserved.has(label)?'option_'+crypto.randomUUID().replaceAll('-',''):label;
  setChoices(old=>[...old,{value,label,color:'gray'}]);setNewChoice('');setError('');newChoiceInput.current?.focus();
 };
 const save=async(event:React.FormEvent)=>{
  event.preventDefault();if(busy)return;setError('');
  if(!name.trim()){setError(t('db.fieldNameRequired'));return;}
  if(selection){const labels=choices.map(c=>c.label.trim().toLocaleLowerCase());if(labels.some(v=>!v)){setError(t('db.optionNameRequired'));return;}if(new Set(labels).size!==labels.length){setError(t('db.duplicateOption'));return;}}
  if(selection&&newChoice.trim()){setError(t('db.optionDraftPending'));newChoiceInput.current?.focus();return;}
  if(roleInvalid){setError(t('db.boardChooseStates'));return;}
  const field:any={type:kind};
  if(selection){
   const meta:any=structuredClone(original.optionMeta||{});
   for(const choice of [...retired.current.values(),...choices]){const before=meta[choice.value]||{},entry={...before};if(choice.label.trim()!==optionLabel(choice.value,original)||before.label!==undefined||!(original.options||[]).includes(choice.value))entry.label=choice.label.trim();if(choice.color==='default')delete entry.color;else entry.color=choice.color;meta[choice.value]=entry;}
   field.options=choices.map(c=>c.value);field.optionMeta=meta;field.allowCustomOptions=false;
  }
  setBusy(true);
  try{await commit({type:'field.set',key:fieldKey,displayName:name.trim(),field,config_revision:revision.current,...(tasks?{task_setup:{...tasks,initialStatus:initial,completedStatuses:completed}}:{})});onClose();}
  catch(e){setError((e as Error).message);}finally{setBusy(false);}
 };
 return <Modal title={t('db.editField')} className="db-field-edit-modal" icon={<Settings2 size={18}/>} onClose={()=>{if(!busy)onClose();}}><form onSubmit={save}><fieldset disabled={busy}>
  <div className="db-field-basics"><label>{t('db.fieldName')}<input ref={input} required value={name} onChange={event=>setName(event.target.value)}/></label><label>{t('db.fieldType')}<select value={kind} disabled={fixedType} title={fixedType?t('db.fieldTypeInUse'):undefined} onChange={event=>setKind(event.target.value)}>{kinds.map(k=><option key={k} value={k}>{t('db.type.'+k)}</option>)}</select></label></div>
  {kind!==original.type&&<p className="db-panel-help">{t('db.fieldTypeKeepsValues')}</p>}
  {selection&&<section className="db-field-choices"><h3>{t('db.fieldChoices')}</h3><p className="db-panel-help">{t('db.optionEditingHint')}</p>
   {!choices.length&&<p className="db-choice-empty">{t('db.noOptions')}</p>}
   {choices.map((choice,index)=><div className="db-choice-row" data-option-value={choice.value} key={choice.value}><button type="button" className={'db-choice-color '+(choice.color==='default'?'':'db-tag-color-'+choice.color)} aria-label={t('db.optionColor')+' '+choice.label} title={t('db.optionColor')} aria-haspopup="menu" onClick={event=>setPalette({value:choice.value,anchor:event.currentTarget})}><Palette size={15}/></button><input className={'db-choice-name '+(choice.color==='default'?'':'db-tag-color-'+choice.color)} aria-label={t('db.optionName')+' '+(index+1)} value={choice.label} onChange={event=>patch(choice.value,{label:event.target.value})}/><button type="button" className="db-choice-remove" aria-label={t('db.deleteOption')+' '+choice.label} title={t('db.deleteOption')} onClick={()=>setRemoving(choice)}><Trash2 size={14}/></button></div>)}
   <div className="db-choice-add"><Plus size={15}/><input ref={newChoiceInput} aria-label={t('db.newOptionName')} placeholder={t('db.newOptionName')} value={newChoice} onChange={event=>setNewChoice(event.target.value)} onKeyDown={event=>{if(event.key==='Enter'){event.preventDefault();event.stopPropagation();add();}}}/><button type="button" disabled={!newChoice.trim()} onClick={add}>{t('db.addOption')}</button></div>
  </section>}
  {tasks&&<section className="db-field-task-roles"><h3>{t('db.configureTasks')}</h3><p className="db-panel-help">{t('db.optionTaskRolesHint')}</p><label>{t('db.initialStatus')}<select value={initial} onChange={event=>setInitial(event.target.value)}><option value="">{t('db.chooseOption')}</option>{choices.map(c=><option key={c.value} value={c.value}>{c.label}</option>)}</select></label><span>{t('db.completedStatuses')}</span><div className="db-field-completed">{choices.map(c=><label key={c.value}><input type="checkbox" checked={completed.includes(c.value)} onChange={event=>setCompleted(event.target.checked?[...completed,c.value]:completed.filter(v=>v!==c.value))}/>{c.label}</label>)}</div></section>}
  <p className="db-panel-help db-field-shared-hint">{t('db.fieldSharedHint')}</p>{error&&<p className="db-panel-error" role="alert">{t(error)}</p>}
 </fieldset><footer className="modal-footer"><button type="button" disabled={busy} onClick={onClose}>{t('取消')}</button><button className="db-save-button" disabled={busy}>{t('保存')}</button></footer></form>
 {palette&&<ActionMenu title={t('db.optionColor')} className="db-option-palette" anchor={palette.anchor} portalTarget={palette.anchor.closest<HTMLElement>('dialog')||undefined} onClose={()=>setPalette(undefined)}>{colors.map(color=><button type="button" key={color} onClick={()=>patch(palette.value,{color})}><span className={'db-palette-dot '+(color==='default'?'db-palette-auto':'db-tag-color-'+color)}/><span>{t(color==='default'?'db.defaultOptionColor':'db.color.'+color)}</span>{choices.find(c=>c.value===palette.value)?.color===color&&<Check size={14}/>}</button>)}</ActionMenu>}
 {removing&&<FormDialog title={t('db.deleteOption')} className="db-delete-field-modal" danger description={t('db.deleteOptionDescription',{name:removing.label})} submitLabel={t('db.deleteOption')} onClose={()=>setRemoving(undefined)} onSubmit={async()=>{if((original.options||[]).includes(removing.value))retired.current.set(removing.value,removing);setChoices(old=>old.filter(c=>c.value!==removing.value));if(initial===removing.value)setInitial('');if(completed.includes(removing.value))setCompleted(old=>old.filter(value=>value!==removing.value));setError('');}}/>}
 </Modal>;
}
