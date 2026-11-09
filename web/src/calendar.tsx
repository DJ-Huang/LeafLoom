import React,{lazy,Suspense,useCallback,useEffect,useRef,useState} from 'react';
import {ChevronLeft,ChevronRight,Plus,Settings,Bell,Trash2} from 'lucide-react';
import {api,Config,OpenNote} from './api';
import {t,getLocale,useLocale,Diagnostic} from './i18n';
import {Modal} from './ui';
import {applyProperties,documentState,hasDocumentDraft} from './document-state';
import './calendar.css';
const DocumentPane=lazy(()=>import('./document').then(m=>({default:m.DocumentPane})));
type SettingsValue={revision:string,shared_conflict?:boolean,workspace_revision:string,root:string,enabled:boolean,summary:boolean,summary_time:string,timezone:string,databases:string[],initialized?:boolean};
type Item={id:string,revision:string,conflicted?:boolean,title:string,description:string,kind:'todo'|'event'|'deadline',date:string,start:string,end:string,repeat:string,until:string,reminder:number|null,completed:boolean,occurrence?:string,path?:string,link?:{database:string,path:string,id?:string}|null,task?:{path:string,title:string,record_revision:string,config_revision:string,completed:boolean},broken_link?:boolean};
type SyncVersion={version:string,device:string,created:number,value:{items?:Record<string,{data:Partial<Item>,deleted:boolean,exceptions:Record<string,Partial<Item>&{deleted?:boolean}>}>,timezone?:string,databases?:string[]}};
type SyncStatus={root:string,workspace_revision:string,directory:string,records:number,pending:number,error:string,files:string[],conflicts:{entity:string,revision:string,versions:SyncVersion[]}[],migration:{state:string,backup?:string}};
type Page={results:Item[],next_cursor?:string,workspace_revision:string,settings:SettingsValue};
const read=<T,>(path:string,signal?:AbortSignal)=>api<T>(path,undefined,'GET',{force:true,signal});
const dateOf=(date:Date)=>`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
const localDate=(value:string)=>new Date(value+'T12:00:00');
const plus=(value:string,days:number)=>{const d=localDate(value);d.setDate(d.getDate()+days);return dateOf(d);};
const today=(zone?:string)=>zone?new Intl.DateTimeFormat('sv-SE',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()):dateOf(new Date());
const repeats=['none','daily','weekly','monthly','weekdays'];
async function all<T>(path:string,signal?:AbortSignal):Promise<T[]>{let rows:T[]=[],cursor='';do{const page=await read<{results:T[],next_cursor?:string}>(path+(path.includes('?')?'&':'?')+'limit=200'+(cursor?'&cursor='+encodeURIComponent(cursor):''),signal);rows.push(...page.results);cursor=page.next_cursor||'';}while(cursor);return rows;}

export function CalendarBadge(){
 const [count,setCount]=useState(0);
 useEffect(()=>{let live=true;const load=()=>void read<{results:{seen:boolean}[]}>('calendar/reminders?limit=200').then(r=>{if(live)setCount(r.results.filter(i=>!i.seen).length);}).catch(()=>{});load();window.addEventListener('vault-data-changed',load);return()=>{live=false;window.removeEventListener('vault-data-changed',load);};},[]);
 return count?<span className="cal-badge">{count}</span>:null;
}

export function CalendarPage({config,onOpen,notify,onRecord}:{config:Config,onOpen:OpenNote,notify:(s:string)=>void,onRecord:(kind:string,path?:string)=>void}){
 useLocale();
 const initial=new URLSearchParams(location.search).get('date');
 const [date,setDate]=useState(initial&&/^\d{4}-\d{2}-\d{2}$/.test(initial)?initial:today()),[mode,setMode]=useState<'month'|'agenda'>('month');
 const [settings,setSettings]=useState<SettingsValue>(),[items,setItems]=useState<Item[]>([]),[overdue,setOverdue]=useState<Item[]>([]),[next,setNext]=useState(''),[overdueNext,setOverdueNext]=useState(''),[completed,setCompleted]=useState(false);
 const [error,setError]=useState(''),[busy,setBusy]=useState(false),[epoch,setEpoch]=useState(0),[editing,setEditing]=useState<Item|null>(),[settingsOpen,setSettingsOpen]=useState(false),[panel,setPanel]=useState<'reminders'|'trash'>(),[daily,setDaily]=useState<{path:string,exists:boolean}>(),[mobileDetail,setMobileDetail]=useState(false);
 const [deleting,setDeleting]=useState<Item>(),[deleteScope,setDeleteScope]=useState('one');
 const [syncOpen,setSyncOpen]=useState(false),[sync,setSync]=useState<SyncStatus>();
 const [highlight,setHighlight]=useState(new URLSearchParams(location.search).get('item')||'');
 const root=config.root!, generation=useRef(0),operations=useRef(new Map<string,string>());
 const refresh=useCallback(()=>setEpoch(e=>e+1),[]);
 useEffect(()=>{const listener=()=>refresh();window.addEventListener('vault-data-changed',listener);return()=>window.removeEventListener('vault-data-changed',listener);},[refresh]);
 useEffect(()=>{const listener=(event:Event)=>{const d=(event as CustomEvent).detail;if(d.root===root&&/^\d{4}-\d{2}-\d{2}$/.test(d.date)){setDate(d.date);setMobileDetail(true);setHighlight(d.item_id||'');setCompleted(true);}};window.addEventListener('leafloom-calendar-open',listener);return()=>window.removeEventListener('leafloom-calendar-open',listener);},[root]);
 const month=date.slice(0,7)+'-01',endOfMonth=dateOf(new Date(localDate(month).getFullYear(),localDate(month).getMonth()+1,0));
 const first=mode==='month'?plus(month,-((localDate(month).getDay()+6)%7)):date;
 const last=mode==='month'?plus(first,41):plus(date,29);
 const query=`calendar/query?start=${first}&end=${last}&completed=${completed}`;
 const overdueQuery=`calendar/query?start=${today(settings?.timezone)}&end=${today(settings?.timezone)}&overdue=true`;
 useEffect(()=>{const controller=new AbortController(),id=++generation.current;setError('');
  void Promise.all([read<SettingsValue>('calendar/settings',controller.signal),read<SyncStatus>('calendar/sync',controller.signal),mode==='month'?all<Item>(query,controller.signal):read<Page>(query,controller.signal)]).then(async([s,syncState,result])=>{
   if(id!==generation.current)return;setSync(syncState);setSettings(s);setItems(Array.isArray(result)?result:result.results);setNext(Array.isArray(result)?'':result.next_cursor||'');
   if(!s.initialized&&!syncState.error&&!syncState.pending){const zone=Intl.DateTimeFormat().resolvedOptions().timeZone;const updated=await api<SettingsValue>('calendar/settings',{...s,timezone:zone},'PUT');if(id===generation.current)setSettings(updated);}
  }).catch(e=>{if(e.name!=='AbortError'&&id===generation.current)setError(e.message);});return()=>controller.abort();
 },[root,query,epoch,mode]);
 useEffect(()=>{const c=new AbortController();void read<Page>(overdueQuery,c.signal).then(p=>{setOverdue(p.results);setOverdueNext(p.next_cursor||'');}).catch(e=>{if(e.name!=='AbortError')setError(e.message);});return()=>c.abort();},[root,overdueQuery,epoch]);
 useEffect(()=>{const c=new AbortController();setDaily(undefined);void read<{path:string,exists:boolean}>('calendar/daily?date='+date,c.signal).then(setDaily).catch(e=>{if(e.name!=='AbortError')setError(e.message);});return()=>c.abort();},[root,date,epoch]);
 useEffect(()=>{if(highlight){const node=Array.from(document.querySelectorAll<HTMLElement>('[data-calendar-item]')).find(n=>n.dataset.calendarItem===highlight);node?.scrollIntoView({block:'center'});}},[highlight,items]);
 const select=(value:string)=>{setDate(value);setMobileDetail(true);history.replaceState(null,'','/?view=calendar&date='+value);};
 const execute=async(command:Record<string,unknown>)=>{
  if(!settings)throw new Error('calendar.loading');
  const item=items.concat(overdue).find(i=>i.id===command.id);
  if(command.type==='complete'&&item?.link&&item.repeat==='none'&&hasDocumentDraft(root,item.task?.path||item.link.path))throw new Error('db.draftConflict');
  const signature=JSON.stringify(command);let id=operations.current.get(signature);if(!id){id=crypto.randomUUID();operations.current.set(signature,id);}
  const result=await api('calendar/commands',{workspace_revision:settings.workspace_revision,operation_id:id,command});
  operations.current.delete(signature);
  if(result.note){const state=documentState(root,result.note.path);if(!state.dirty&&!state.pending)applyProperties(state,result.note);}
  refresh();return result;
 };
 const run=async(work:()=>Promise<unknown>)=>{if(busy)return;setBusy(true);setError('');try{await work();}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
 const more=(old:Item[],path:string,cursor:string,update:(items:Item[])=>void,setCursor:(s:string)=>void)=>run(async()=>{const p=await read<Page>(path+'&cursor='+encodeURIComponent(cursor));update([...old,...p.results]);setCursor(p.next_cursor||'');});
 const row=(item:Item)=><article className={'cal-item '+(item.id===highlight?'cal-highlight ':'')+(item.completed?'is-complete ':'')+(item.kind==='deadline'?'is-deadline':'')} key={item.id+item.occurrence} data-calendar-item={item.id}>
  {item.kind==='todo'&&<input type="checkbox" aria-label={item.title+' '+t('calendar.complete')} checked={item.completed} disabled={busy||!!item.broken_link||!!item.conflicted} onChange={e=>void run(()=>execute({type:'complete',id:item.id,revision:item.revision,occurrence:item.occurrence,completed:e.target.checked,...(item.task?{record_revision:item.task.record_revision,config_revision:item.task.config_revision}:{})}))}/>}
  <div className="cal-item-content"><button className="text-link" onClick={()=>item.conflicted?setSyncOpen(true):item.kind==='deadline'?onOpen(item.path!):setEditing(item)}>{item.title}</button><small>{item.date} · {item.start||t('calendar.allDay')}{item.end?'–'+item.end:''}{item.kind==='deadline'?' · '+t('calendar.deadline'):''}{item.repeat&&item.repeat!=='none'?' · '+t('calendar.repeat.'+item.repeat):''}</small>
  {item.conflicted&&<small className="error">{t('calendar.syncConflict')}</small>}{item.description&&<p>{item.description}</p>}{item.link&&<small>{item.broken_link?<span className="error">{t('calendar.brokenLink')}</span>:<button className="text-link" onClick={()=>onOpen(item.task?.path||item.link!.path)}>{item.task?.title||item.link.path}</button>}{item.repeat!=='none'?' · '+t('calendar.referenceOnly'):''}</small>}</div>
  {item.kind!=='deadline'&&<button className="icon-button" aria-label={t('calendar.delete')+' '+item.title} disabled={busy||!!item.conflicted} onClick={()=>{setDeleteScope('one');setDeleting(item);}}><Trash2 size={15}/></button>}
 </article>;
 return <section className={'calendar-page '+(mobileDetail?'cal-detail-open':'')} aria-label={t('calendar.title')}>
  <header className="cal-header"><div><h1>{t('calendar.title')}</h1><p>{t('calendar.subtitle')}</p></div><div className="cal-actions"><button onClick={()=>setSyncOpen(true)}>{t('calendar.syncTitle')}</button><button onClick={()=>setPanel('reminders')}><Bell size={16}/>{t('calendar.reminders')}</button><button onClick={()=>setPanel('trash')}><Trash2 size={16}/>{t('calendar.trash')}</button><button onClick={()=>setSettingsOpen(true)}><Settings size={16}/>{t('calendar.settings')}</button><button className="primary" disabled={!settings} onClick={()=>setEditing(null)}><Plus size={16}/>{t('calendar.new')}</button></div></header>
  {sync&&(sync.error||sync.pending>0||sync.conflicts.length>0)&&<div className="cal-sync-notice" role="status"><span>{sync.error?t(sync.error):sync.pending?t('calendar.syncPending'):t('calendar.syncConflictCount',{count:sync.conflicts.length})}</span><button onClick={()=>setSyncOpen(true)}>{t('calendar.syncReview')}</button></div>}
  {error&&<p role="alert" className="error"><Diagnostic message={error}/><button onClick={refresh}>{t('calendar.refresh')}</button></p>}
  <div className="cal-toolbar"><button aria-label={t('calendar.previous')} onClick={()=>select(mode==='month'?dateOf(new Date(localDate(month).getFullYear(),localDate(month).getMonth()-1,1)):plus(date,-30))}><ChevronLeft size={16}/></button><strong>{localDate(date).toLocaleDateString(getLocale(),{year:'numeric',month:'long'})}</strong><button aria-label={t('calendar.next')} onClick={()=>select(mode==='month'?plus(endOfMonth,1):plus(date,30))}><ChevronRight size={16}/></button><button onClick={()=>select(today(settings?.timezone))}>{t('calendar.today')}</button><button aria-pressed={mode==='month'} onClick={()=>{setMode('month');setMobileDetail(false);}}>{t('calendar.month')}</button><button aria-pressed={mode==='agenda'} onClick={()=>setMode('agenda')}>{t('calendar.agenda')}</button><label><input type="checkbox" checked={completed} onChange={e=>setCompleted(e.target.checked)}/>{t('calendar.showCompleted')}</label></div>
  <div className="cal-layout"><div className="cal-overview">{mode==='month'?<div className="cal-month">
   {Array.from({length:7},(_,i)=><div className="cal-weekday" key={i}>{new Date(2024,0,1+i).toLocaleDateString(getLocale(),{weekday:'short'})}</div>)}
   {Array.from({length:42},(_,i)=>{const value=plus(first,i),entries=items.filter(r=>r.date===value);return <button key={value} className={'cal-day '+(value===date?'selected ':'')+(value===today(settings?.timezone)?'today ':'')+(value.slice(0,7)!==month.slice(0,7)?'muted':'')} aria-label={value} aria-pressed={value===date} onClick={()=>select(value)}><span>{localDate(value).getDate()}</span>{entries.slice(0,3).map(item=><span className={'cal-chip '+item.kind+(item.completed?' completed':'')} key={item.id+item.occurrence}>{item.start} {item.title}</span>)}{entries.length>3&&<small>+{entries.length-3}</small>}</button>;})}
  </div>:<div className="cal-agenda"><h2>{t('calendar.upcoming')}</h2>{items.map(row)}{!items.length&&<p>{t('calendar.empty')}</p>}{next&&<button onClick={()=>void more(items,query,next,setItems,setNext)}>{t('calendar.more')}</button>}<h2>{t('calendar.overdue')}</h2>{overdue.map(row)}{!overdue.length&&<p>{t('calendar.empty')}</p>}{overdueNext&&<button onClick={()=>void more(overdue,overdueQuery,overdueNext,setOverdue,setOverdueNext)}>{t('calendar.more')}</button>}</div>}</div>
  <aside className="cal-detail"><button className="cal-back" onClick={()=>setMobileDetail(false)}>{t('calendar.back')}</button><h2>{localDate(date).toLocaleDateString(getLocale(),{month:'long',day:'numeric',weekday:'long'})}</h2><div className="cal-section-title"><h3>{t('calendar.dayItems')}</h3><button disabled={!settings} onClick={()=>setEditing(null)}><Plus size={15}/>{t('calendar.new')}</button></div>{items.filter(r=>r.date===date).map(row)}{!items.some(r=>r.date===date)&&<p className="subtle">{t('calendar.empty')}</p>}
  <h3>{t('calendar.dailyNote')}</h3>{daily?.exists?<div className="cal-note"><Suspense fallback={<p>{t('calendar.loading')}</p>}><DocumentPane key={daily.path} path={daily.path} vaultRoot={root} onOpen={onOpen} notify={notify} onRecord={onRecord}/></Suspense></div>:<button disabled={!daily||busy} onClick={()=>void run(async()=>{const result=await api('daily',{date,workspace_revision:settings?.workspace_revision});sessionStorage.setItem('edit:'+result.path,'1');setDaily({path:result.path,exists:true});})}>{t('calendar.createNote')}</button>}</aside></div>
  {syncOpen&&<SyncPanel root={root} close={()=>setSyncOpen(false)} changed={refresh}/>}
  {editing!==undefined&&settings&&<ItemDialog item={editing} date={date} workspace={settings.workspace_revision} save={execute} close={()=>setEditing(undefined)}/>}
  {settingsOpen&&settings&&<SettingsDialog value={settings} saved={value=>{setSettings(value);setSettingsOpen(false);refresh();}} close={()=>setSettingsOpen(false)}/>}
  {panel&&settings&&<HistoryPanel kind={panel} settings={settings} execute={execute} close={()=>setPanel(undefined)} open={value=>{select(value);setPanel(undefined);}}/>}
  {deleting&&<Modal title={t('calendar.delete')} onClose={()=>setDeleting(undefined)}><div className="cal-form"><p>{deleting.title}</p>{deleting.repeat!=='none'&&<label>{t('calendar.scope')}<select aria-label={t('calendar.scope')} value={deleteScope} onChange={e=>setDeleteScope(e.target.value)}><option value="one">{t('calendar.one')}</option><option value="future">{t('calendar.future')}</option></select></label>}<p>{t('calendar.restoreHelp')}</p><button disabled={busy} className="danger" onClick={()=>void run(async()=>{await execute({type:'delete',id:deleting.id,revision:deleting.revision,occurrence:deleting.occurrence,scope:deleteScope});setDeleting(undefined);})}>{t('calendar.delete')}</button></div></Modal>}
 </section>;
}

function ItemDialog({item,date,workspace,save,close}:{item:Item|null,date:string,workspace:string,save:(c:Record<string,unknown>)=>Promise<unknown>,close:()=>void}){
 const [value,setValue]=useState<Partial<Item>>(item?{...item}:{title:'',description:'',kind:'todo',date,start:'',end:'',repeat:'none',until:'',reminder:null,link:null});
 const [scope,setScope]=useState('one'),[error,setError]=useState(''),[busy,setBusy]=useState(false),[databases,setDatabases]=useState<{path:string,title:string}[]>([]),[database,setDatabase]=useState(item?.link?.database||''),[records,setRecords]=useState<{path:string,title:string}[]>([]),[search,setSearch]=useState(''),[cursor,setCursor]=useState('');
 const patch=(key:string,v:unknown)=>setValue(old=>({...old,[key]:v}));
 useEffect(()=>{const c=new AbortController();void all<{path:string,title:string}>('calendar/databases',c.signal).then(setDatabases).catch(e=>{if(e.name!=='AbortError')setError(e.message);});return()=>c.abort();},[]);
 useEffect(()=>{const c=new AbortController();setRecords([]);setCursor('');if(database){const timer=setTimeout(()=>void read<any>('calendar/tasks?database='+encodeURIComponent(database)+'&search='+encodeURIComponent(search)+'&limit=50',c.signal).then(p=>{setRecords(p.results);setCursor(p.next_cursor||'');}).catch(e=>{if(e.name!=='AbortError')setError(e.message);}),150);return()=>{clearTimeout(timer);c.abort();};}return()=>c.abort();},[database,search]);
 return <Modal title={t(item?'calendar.edit':'calendar.new')} onClose={()=>{if(!busy)close();}}><form className="cal-form" onSubmit={e=>{e.preventDefault();if(busy)return;setBusy(true);setError('');void save(item?{type:'edit',id:item.id,revision:item.revision,occurrence:item.occurrence,scope,item:value}:{type:'create',item:value}).then(close).catch(e=>setError(e.message)).finally(()=>setBusy(false));}}>
  {error&&<p role="alert" className="error"><Diagnostic message={error}/></p>}<fieldset disabled={busy}>
  <label>{t('calendar.itemTitle')}<input required maxLength={500} value={value.title} onChange={e=>patch('title',e.target.value)} autoFocus/></label>
  <label>{t('calendar.description')}<textarea rows={3} maxLength={20000} value={value.description} onChange={e=>patch('description',e.target.value)}/></label>
  <div className="cal-fields"><label>{t('calendar.kind')}<select aria-label={t('calendar.kind')} value={value.kind} onChange={e=>patch('kind',e.target.value)}><option value="todo">{t('calendar.todo')}</option><option value="event">{t('calendar.event')}</option></select></label><label>{t('calendar.date')}<input type="date" required value={value.date} onChange={e=>patch('date',e.target.value)}/></label></div>
  <label className="cal-check"><input type="checkbox" checked={!value.start} onChange={e=>setValue(v=>({...v,start:e.target.checked?'':'09:00',end:'',reminder:e.target.checked?null:10}))}/>{t('calendar.allDay')}</label>
  {value.start&&<div className="cal-fields"><label>{t('calendar.start')}<input type="time" required value={value.start} onChange={e=>patch('start',e.target.value)}/></label><label>{t('calendar.end')}<input type="time" value={value.end} onChange={e=>patch('end',e.target.value)}/></label><label>{t('calendar.reminder')}<select aria-label={t('calendar.reminder')} value={value.reminder??'off'} onChange={e=>patch('reminder',e.target.value==='off'?null:Number(e.target.value))}>{['off',0,10,30,60,1440].map(v=><option key={v} value={v}>{t('calendar.remind.'+v)}</option>)}</select></label></div>}
  {item&&item.repeat!=='none'&&<label>{t('calendar.scope')}<select aria-label={t('calendar.scope')} value={scope} onChange={e=>setScope(e.target.value)}><option value="one">{t('calendar.one')}</option><option value="future">{t('calendar.future')}</option></select></label>}
  <div className="cal-fields"><label>{t('calendar.repeat')}<select aria-label={t('calendar.repeat')} disabled={!!item&&item.repeat!=='none'&&scope==='one'} value={value.repeat} onChange={e=>patch('repeat',e.target.value)}>{repeats.map(v=><option key={v} value={v}>{t('calendar.repeat.'+v)}</option>)}</select></label>{value.repeat!=='none'&&<label>{t('calendar.until')}<input type="date" disabled={!!item&&item.repeat!=='none'&&scope==='one'} value={value.until} onChange={e=>patch('until',e.target.value)}/></label>}</div>
  <p className="subtle">{t('calendar.repeatHelp')}</p><label>{t('calendar.database')}<select aria-label={t('calendar.database')} value={database} onChange={e=>{setDatabase(e.target.value);patch('link',null);}}><option value="">{t('calendar.none')}</option>{databases.map(d=><option key={d.path} value={d.path}>{d.title}</option>)}</select></label>
  {database&&<><label>{t('calendar.findTask')}<input type="search" value={search} onChange={e=>setSearch(e.target.value)}/></label><label>{t('calendar.task')}<select aria-label={t('calendar.task')} value={value.link?.path||''} onChange={e=>patch('link',e.target.value?{database,path:e.target.value}:null)}><option value="">{t('calendar.none')}</option>{value.link&&!records.some(r=>r.path===value.link?.path)&&<option value={value.link.path}>{value.link.path}</option>}{records.map(r=><option key={r.path} value={r.path}>{r.title}</option>)}</select></label>{cursor&&<button type="button" onClick={()=>void read<any>('calendar/tasks?database='+encodeURIComponent(database)+'&search='+encodeURIComponent(search)+'&limit=50&cursor='+encodeURIComponent(cursor)).then(p=>{setRecords(r=>[...r,...p.results]);setCursor(p.next_cursor||'');}).catch(e=>setError(e.message))}>{t('calendar.more')}</button>}</>}
  {value.link&&<p>{t(value.repeat==='none'&&value.kind==='todo'?'calendar.syncHelp':'calendar.referenceOnly')}</p>}
  <div className="cal-actions"><button type="button" onClick={close}>{t('calendar.cancel')}</button><button className="primary" type="submit" disabled={!workspace}>{t('calendar.save')}</button></div></fieldset>
 </form></Modal>;
}

function SettingsDialog({value,saved,close}:{value:SettingsValue,saved:(s:SettingsValue)=>void,close:()=>void}){
 const [form,setForm]=useState(value),[databases,setDatabases]=useState<{path:string,title:string}[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 useEffect(()=>{const c=new AbortController();void all<{path:string,title:string}>('calendar/databases',c.signal).then(setDatabases).catch(e=>{if(e.name!=='AbortError')setError(e.message);});return()=>c.abort();},[]);
 return <Modal title={t('calendar.settings')} onClose={()=>{if(!busy)close();}}><form className="cal-form" onSubmit={e=>{e.preventDefault();setBusy(true);void api<SettingsValue>('calendar/settings',form,'PUT').then(saved).catch(e=>setError(e.message)).finally(()=>setBusy(false));}}>{error&&<p className="error" role="alert"><Diagnostic message={error}/></p>}<fieldset disabled={busy}>
 <label className="cal-check"><input type="checkbox" checked={form.enabled} onChange={e=>setForm({...form,enabled:e.target.checked})}/>{t('calendar.enableReminders')}</label><p>{t('calendar.reminderHelp')}</p><label className="cal-check"><input type="checkbox" checked={form.summary} onChange={e=>setForm({...form,summary:e.target.checked})}/>{t('calendar.summary')}</label><label>{t('calendar.summaryTime')}<input type="time" required value={form.summary_time} onChange={e=>setForm({...form,summary_time:e.target.value})}/></label><p>{t('calendar.syncSettingsHelp')}</p><label>{t('calendar.timezone')}<input disabled={form.shared_conflict} required value={form.timezone} onChange={e=>setForm({...form,timezone:e.target.value})}/></label><h3>{t('calendar.deadlineSources')}</h3><p>{t('calendar.deadlineHelp')}</p>
 {databases.map(d=><label className="cal-check" key={d.path}><input type="checkbox" disabled={form.shared_conflict} checked={form.databases.includes(d.path)} onChange={e=>setForm({...form,databases:e.target.checked?[...form.databases,d.path]:form.databases.filter(p=>p!==d.path)})}/>{d.title}</label>)}<button className="primary" type="submit">{t('calendar.save')}</button></fieldset></form></Modal>;
}

function HistoryPanel({kind,settings,execute,close,open}:{kind:'reminders'|'trash',settings:SettingsValue,execute:(c:Record<string,unknown>)=>Promise<unknown>,close:()=>void,open:(date:string)=>void}){
 const [rows,setRows]=useState<any[]>([]),[cursor,setCursor]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),[epoch,setEpoch]=useState(0);
 const load=async(next='')=>{const p=await read<any>('calendar/'+(kind==='trash'?'trash':'reminders')+(next?'?cursor='+encodeURIComponent(next):''));setRows(old=>next?[...old,...p.results]:p.results);setCursor(p.next_cursor||'');};
 useEffect(()=>{void load().catch(e=>setError(e.message));},[kind,epoch]);
 return <Modal title={t(kind==='trash'?'calendar.trash':'calendar.reminders')} onClose={close}><div className="cal-form">{error&&<p className="error" role="alert"><Diagnostic message={error}/></p>}{!rows.length&&<p>{t('calendar.empty')}</p>}{rows.map(r=><article className="cal-item" key={r.id+(r.occurrence||'')}><div><strong>{r.title||t('calendar.summary')}</strong><small>{r.date}{r.kind==='summary'?` · ${r.count} · ${t('calendar.overdue')}: ${r.overdue}`:''}</small>{r.state&&<small>{t('calendar.state.'+r.state)}</small>}</div>{kind==='trash'?<button disabled={busy} onClick={()=>{setBusy(true);void execute({type:'restore',id:r.id,revision:r.revision,occurrence:r.occurrence}).then(()=>setEpoch(e=>e+1)).catch(e=>setError(e.message)).finally(()=>setBusy(false));}}>{t('calendar.restore')}</button>:<button onClick={()=>{void api('calendar/reminders/seen',{root:settings.root,workspace_revision:settings.workspace_revision,id:r.id}).catch(e=>setError(e.message));open(r.date);}}>{t('calendar.open')}</button>}</article>)}{cursor&&<button onClick={()=>void load(cursor).catch(e=>setError(e.message))}>{t('calendar.more')}</button>}</div></Modal>;
}

function SyncPanel({root,close,changed}:{root:string,close:()=>void,changed:()=>void}){
 const [status,setStatus]=useState<SyncStatus>(),[error,setError]=useState(''),[busy,setBusy]=useState(false),[epoch,setEpoch]=useState(0);
 useEffect(()=>{const controller=new AbortController();void read<SyncStatus>('calendar/sync',controller.signal).then(value=>{if(value.root===root){setStatus(value);setError('');}}).catch(e=>{if(e.name!=='AbortError')setError(e.message);});return()=>controller.abort();},[root,epoch]);
 const select=async(entity:string,revision:string,selected:string)=>{
  if(!status||busy)return;setBusy(true);setError('');
  try{await api('calendar/sync/resolve',{workspace_revision:status.workspace_revision,entity,revision,selected});setEpoch(e=>e+1);changed();}
  catch(e){setError((e as Error).message);setEpoch(e=>e+1);}finally{setBusy(false);}
 };
 const describe=(value:Partial<Item>&{deleted?:boolean})=><dl className="cal-sync-fields">{Object.entries(value).filter(([key,v])=>v!==null&&v!==''&&v!==undefined&&key!=='id').map(([key,v])=>{
  const labels:Record<string,string>={title:'itemTitle',description:'description',kind:'kind',date:'date',start:'start',end:'end',repeat:'repeat',until:'until',reminder:'reminder',link:'task',completed:'complete',deleted:'delete'};
  let content=String(v);
  if(key==='kind')content=t('calendar.'+v);
  if(key==='repeat')content=t('calendar.repeat.'+v);
  if(key==='completed'||key==='deleted')content=t(v?'calendar.syncYes':'calendar.syncNo');
  if(key==='reminder')content=t('calendar.syncMinutes',{count:Number(v)});
  if(key==='link'&&typeof v==='object')content=(v as {database:string,path:string}).database+' → '+(v as {path:string}).path;
  return <React.Fragment key={key}><dt>{t('calendar.'+(labels[key]||key))}</dt><dd>{content}</dd></React.Fragment>;
 })}</dl>;
 return <Modal title={t('calendar.syncTitle')} onClose={()=>{if(!busy)close();}} className="cal-sync-dialog"><div className="cal-form">
  <p>{t('calendar.syncFilesHelp')}</p><p>{t('calendar.syncLocalHelp')}</p>
  {error&&<p className="error" role="alert"><Diagnostic message={error}/></p>}
  {status&&<><p>{t('calendar.syncRecords',{count:status.records})}</p><code>{status.directory}</code>
   {status.migration.backup&&<p>{t('calendar.syncBackup')} <code>{status.migration.backup}</code></p>}
   {status.error&&<p className="error">{t(status.error)}</p>}{status.pending>0&&<p>{t('calendar.syncPending')}</p>}
   {status.files.length>0&&<details><summary>{t('calendar.syncFiles')}</summary>{status.files.map(file=><p key={file}>{file}</p>)}</details>}
   {!status.error&&!status.pending&&!status.conflicts.length&&<p>{t('calendar.syncNoConflicts')}</p>}
   {status.conflicts.map(conflict=><section key={conflict.entity} className="cal-sync-conflict"><h3>{conflict.entity==='settings'?t('calendar.syncSharedSettings'):t('calendar.syncChoose')}</h3><p>{t('calendar.syncChooseHelp')}</p><div className="cal-sync-versions">
    {conflict.versions.map(version=><article key={version.version} className="cal-sync-version"><p>{version.device==='migration'?t('calendar.syncImported'):t('calendar.syncDevice',{id:version.device.slice(0,8)})}{version.created>0?' · '+new Date(version.created*1000).toLocaleString(getLocale()):''}</p>
     {version.value.items?Object.entries(version.value.items).map(([id,item])=><div key={id}><h4>{item.data.title}</h4>{item.deleted&&<strong>{t('calendar.syncDeleted')}</strong>}{describe(item.data)}{Object.entries(item.exceptions).map(([occurrence,change])=><details key={occurrence}><summary>{t('calendar.syncOccurrence',{date:occurrence})}</summary>{describe(change)}</details>)}</div>):<div><p>{t('calendar.timezone')}: {version.value.timezone}</p><p>{t('calendar.deadlineSources')}: {version.value.databases?.join(', ')||t('calendar.none')}</p></div>}
     <button className="primary" disabled={busy||!!status.error||status.pending>0} onClick={()=>void select(conflict.entity,conflict.revision,version.version)}>{t('calendar.syncUseVersion')}</button>
    </article>)}
   </div></section>)}
  </>}
  <button disabled={busy} onClick={()=>setEpoch(e=>e+1)}>{t('calendar.refresh')}</button>
 </div></Modal>;
}
