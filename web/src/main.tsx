import React,{lazy,Suspense,useCallback,useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {BookOpen,Calendar,FilePlus,FolderPlus,Home,History,Network,PanelLeft,Plus,RefreshCw,Search,Settings,Trash2,Upload,ArrowLeft} from 'lucide-react';
import {api,applySession,csrf,invalidate,media,Config,OpenNote,Session} from './api';
import {DirectoryTree} from './tree';
import {Action,Modal,LoadingShell,LazyBoundary,FormDialog,FormField} from './ui';
import {updateStatus} from './hooks';
import {Association,ConnectedSettings} from './settings';
import {Dashboard,Sidebar,Tabs,IndexStatus,fileName,usePreferences} from './layout';
import './style.css';

let documentModule:Promise<typeof import('./document')>|undefined;
function DocumentPane(props:React.ComponentProps<typeof import('./document')['DocumentPane']>){
 const [component,setComponent]=useState<typeof import('./document')['DocumentPane']>(),[error,setError]=useState('');
 useEffect(()=>{let alive=true;void(documentModule||(documentModule=import('./document'))).then(module=>{if(alive)setComponent(()=>module.DocumentPane);}).catch(error=>{if(alive)setError(String(error));});return()=>{alive=false;};},[]);
 if(error)return <div className="empty-state">{error}<button onClick={()=>window.location.reload()}>重新加载页面</button></div>;
 const Component=component;return Component?<Component {...props}/>:<p className="pad subtle">正在打开内容…</p>;
}
const GraphView=lazy(()=>import('./graph').then(module=>({default:module.GraphView})));
const FileSearch=lazy(()=>import('./search').then(module=>({default:module.FileSearch})));
const KnowledgeSearch=lazy(()=>import('./search').then(module=>({default:module.KnowledgeSearch})));
type View='home'|'document'|'knowledge';
type FileOperation={kind:'file'|'folder'|'template'|'rename'|'move'|'delete',path?:string,templates?:{path:string,title:string}[]};
const folderOf=(path:string)=>path.includes('/')?path.slice(0,path.lastIndexOf('/')):'';
const within=(path:string,parent:string)=>path===parent||path.startsWith(parent+'/');
function App(){
 const [config,setConfig]=useState<Config>(),[suggestion,setSuggestion]=useState(''),[tabs,setTabs]=useState<string[]>([]),[active,setActive]=useState(''),[view,setView]=useState<View>('home'),[knowledgeVisited,setKnowledgeVisited]=useState(false),[backToKnowledge,setBackToKnowledge]=useState(false);
 const [currentFolder,setCurrentFolder]=useState(''),[refresh,setRefresh]=useState(0),[settings,setSettings]=useState(false),[graph,setGraph]=useState(false),[quickSearch,setQuickSearch]=useState(false),[toast,setToast]=useState(''),[menu,setMenu]=useState<string>(),[operation,setOperation]=useState<FileOperation>(),[records,setRecords]=useState<{kind:string,path?:string,data:any[]}>(),[candidates,setCandidates]=useState<string[]>(),[connectionError,setConnectionError]=useState(''),[mobileOpen,setMobileOpen]=useState(false);
 const [narrow,setNarrow]=useState(()=>window.matchMedia('(max-width:900px)').matches);
 const [preferences,setPreferences]=usePreferences(config?.root||'');
 const inputFile=useRef<HTMLInputElement>(null),session=useRef<Session|undefined>(undefined),sessionRequest=useRef(0),toastTimer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
 const notify=useCallback((message:string)=>{clearTimeout(toastTimer.current);setToast(message);toastTimer.current=setTimeout(()=>setToast(''),7000);},[]);
 useEffect(()=>()=>clearTimeout(toastTimer.current),[]);
 useEffect(()=>{const media=window.matchMedia('(max-width:900px)'),change=()=>{setNarrow(media.matches);setMobileOpen(false);};media.addEventListener('change',change);return()=>media.removeEventListener('change',change);},[]);
 const changed=useCallback(()=>setRefresh(value=>value+1),[]);
 const resetWorkspace=useCallback(()=>{setTabs([]);setActive('');setView('home');setKnowledgeVisited(false);setBackToKnowledge(false);setCurrentFolder('');setQuickSearch(false);setGraph(false);setRecords(undefined);setOperation(undefined);setMenu(undefined);setCandidates(undefined);setMobileOpen(false);history.replaceState(null,'','/');},[]);
 const loadSession=useCallback(async()=>{
  const request=++sessionRequest.current;
  try{const next=await api<Session>('session');if(request!==sessionRequest.current)return;const previous=session.current,scopeChanged=applySession(next);session.current=next;setConfig(value=>JSON.stringify(value)===JSON.stringify(next.config)?value:next.config);setSuggestion(next.suggested_root);setConnectionError('');
   if(!previous){const params=new URLSearchParams(location.search),target=params.get('note');if(target&&next.config.root){setTabs([target]);setActive(target);setView('document');}else if(params.get('view')==='knowledge'){setView('knowledge');setKnowledgeVisited(true);}}
   else if(previous.config.root!==next.config.root)resetWorkspace();
   if(scopeChanged&&previous)invalidate({reset:true});
   const status=await api('status');if(request===sessionRequest.current)updateStatus(status);
  }catch(error){if(request===sessionRequest.current)setConnectionError((error as Error).message);}
 },[resetWorkspace]);
 useEffect(()=>{void loadSession();let alive=true;const events=new EventSource('/api/events');let connected=false;
  events.onmessage=event=>{if(!alive)return;try{const change=JSON.parse(event.data);if(change.type==='status'){updateStatus(change.status);return;}if(change.type==='reset'){if(connected)invalidate({reset:true});connected=true;void loadSession();return;}if(change.type==='config'||change.service_instance_id!==session.current?.service_instance_id||change.config_revision!==session.current?.config.revision){void loadSession();return;}if(change.type==='files')invalidate(change);}catch{setConnectionError('服务通知暂不可用，请刷新数据');}};
  events.onopen=()=>{if(alive)setConnectionError('');};events.onerror=()=>{if(alive)setConnectionError('与本地服务的连接中断，正在重试；你的草稿仍保留');};
  const close=()=>events.close();window.addEventListener('pagehide',close);const resume=()=>{if(events.readyState===EventSource.CLOSED)window.location.reload();};window.addEventListener('pageshow',resume);
  return()=>{alive=false;events.close();window.removeEventListener('pagehide',close);window.removeEventListener('pageshow',resume);};
 },[loadSession]);
 useEffect(()=>{if(active&&config?.root)setPreferences(value=>({recent:[active,...value.recent.filter(path=>path!==active)].slice(0,12)}));},[active,config?.root,setPreferences]);
 const mounted=[active,...preferences.recent.filter(path=>path!==active&&tabs.includes(path))].filter(Boolean).slice(0,3);
 const refreshData=useCallback(()=>{invalidate({reset:true});void loadSession();},[loadSession]);
 const showHome=()=>{setView('home');setMobileOpen(false);setBackToKnowledge(false);history.replaceState(null,'','/');};
 const showKnowledge=()=>{setView('knowledge');setKnowledgeVisited(true);setMobileOpen(false);history.replaceState(null,'','/?view=knowledge');};
 const selectDocument=useCallback((path:string)=>{setTabs(value=>value.includes(path)?value:[...value,path]);setActive(path);setView('document');setMobileOpen(false);history.replaceState(null,'','/?note='+encodeURIComponent(path));},[]);
 const open=useCallback<OpenNote>(async(target,anchor)=>{
  const origin=session.current?.config.root;
  try{const split=target.split('|')[0].split('#'),part=split[0],data=await api('resolve?target='+encodeURIComponent(part||active)+'&source='+encodeURIComponent(active));
   if(session.current?.config.root!==origin)return;
   if(data.candidates.length!==1){setCandidates(data.candidates);if(!data.candidates.length)notify('没有找到文档：'+target);return;}
   const path=data.candidates[0];selectDocument(path);
   if(anchor||split[1]){sessionStorage.setItem('jump:'+path,anchor||split[1]);window.dispatchEvent(new CustomEvent('vault-navigation-anchor',{detail:path}));}
  }catch(error){notify((error as Error).message);}
 },[active,notify,selectDocument]);
 const openFile:OpenNote=(path,anchor)=>{setBackToKnowledge(false);void open(path,anchor);};
 const closeTab=(path:string)=>{const index=tabs.indexOf(path),remaining=tabs.filter(item=>item!==path);setTabs(remaining);
  if(path===active){const next=remaining[Math.min(index,remaining.length-1)]||'';setActive(next);if(view==='document'){if(next)selectDocument(next);else showHome();}}
 };
 const toggleSidebar=useCallback(()=>{if(narrow)setMobileOpen(value=>!value);else setPreferences(value=>({sidebarCollapsed:!value.sidebarCollapsed}));},[narrow,setPreferences]);
 useEffect(()=>{const key=(event:KeyboardEvent)=>{if(event.isComposing||document.querySelector('dialog[open]'))return;if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){event.preventDefault();if(session.current?.config.root)setQuickSearch(true);}if((event.metaKey||event.ctrlKey)&&event.key==='\\'){event.preventDefault();toggleSidebar();}};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);},[toggleSidebar]);
 const saved=(next:Config)=>{sessionRequest.current++;if(next.root!==config?.root)resetWorkspace();if(session.current){session.current={...session.current,config:next};applySession(session.current);}setConfig(next);invalidate({reset:true});changed();void loadSession();};
 const moveFile=async(path:string,target:string)=>{
  const origin=session.current?.config.root,result=await api('move',{source:path,destination:target});if(origin!==session.current?.config.root)return;
  const remap=(item:string)=>within(item,path)?target+item.slice(path.length):item;
  setTabs(value=>value.map(remap));setActive(value=>value?remap(value):value);setCurrentFolder(value=>value?remap(value):value);setPreferences(value=>({recent:value.recent.map(remap)}));
  if(view==='document'&&active)history.replaceState(null,'','/?note='+encodeURIComponent(remap(active)));
  changed();notify('已移动，修复 '+result.updated_links+' 篇文档的引用');
 };
 const manage=(action:string,path:string,destination?:string)=>{
  if(action==='menu'){setMenu(path);return;}
  if(action==='move'&&destination){void moveFile(path,destination).catch(error=>notify(error.message));return;}
  if(action==='rename'||action==='move'||action==='delete'){setMenu(undefined);setOperation({kind:action,path});}
 };
 const record=useCallback(async(kind:string,path?:string)=>{const origin=session.current?.config.root;try{const data=await api('records?kind='+kind+(path?'&path='+encodeURIComponent(path):''));if(origin===session.current?.config.root){setMenu(undefined);setRecords({kind,path,data});}}catch(error){notify((error as Error).message);}},[notify]);
 const newFile=(kind:'file'|'folder')=>setOperation({kind});
 const newTemplate=async()=>{const origin=session.current?.config.root;try{const templates=await api('templates');if(origin!==session.current?.config.root)return;if(!templates.length){notify('模板目录中暂无模板，可在设置中选择模板目录');return;}setOperation({kind:'template',templates});}catch(error){notify((error as Error).message);}};
 const daily=async()=>{const origin=session.current?.config.root;try{const data=await api('daily',{});if(origin!==session.current?.config.root)return;if(data.created)sessionStorage.setItem('edit:'+data.path,'1');changed();openFile(data.path);}catch(error){notify((error as Error).message);}};
 const submitOperation=async(values:Record<string,string>)=>{
  if(!operation)return;const {kind,path=''}=operation,origin=session.current?.config.root;
  if(kind==='rename'||kind==='move'){const value=values.name.trim();if(!value)throw new Error('请输入名称或目标路径');await moveFile(path,kind==='rename'?[folderOf(path),value].filter(Boolean).join('/'):value);return;}
  if(kind==='delete'){await api('delete',{path});if(origin!==session.current?.config.root)return;const remaining=tabs.filter(item=>!within(item,path));setTabs(remaining);setPreferences(value=>({recent:value.recent.filter(item=>!within(item,path))}));if(within(active,path)){setActive(remaining[0]||'');if(view==='document'){if(remaining[0])selectDocument(remaining[0]);else showHome();}}if(within(currentFolder,path))setCurrentFolder(folderOf(path));changed();notify('已移入回收区，可以恢复');return;}
  const name=values.name.trim();if(!name)throw new Error('请输入名称');const target=[currentFolder,name].filter(Boolean).join('/');
  const created=kind==='template'?await api('template',{path:target,template:values.template}):await api('create',{path:target,directory:kind==='folder'});
  if(origin!==session.current?.config.root)return;
  if(kind==='folder')setCurrentFolder(created.path);else{if(created.cursor!==null&&created.cursor!==undefined)sessionStorage.setItem('cursor:'+created.path,String(created.cursor));sessionStorage.setItem('edit:'+created.path,'1');setBackToKnowledge(false);selectDocument(created.path);}changed();
 };
 const fields:FormField[]=operation?.kind==='delete'?[]:operation?[{name:'name',label:operation.kind==='move'?'目标路径（相对知识库根目录）':'名称',required:true,value:operation.kind==='rename'?fileName(operation.path!):operation.kind==='move'?operation.path:operation.kind==='folder'?'新目录':'未命名.md'},...(operation.kind==='template'?[{name:'template',label:'模板',value:operation.templates?.[0]?.path,required:true,options:operation.templates?.map(template=>({value:template.path,label:template.title}))}]:[])]:[];
 if(!config)return <LoadingShell error={connectionError} onRetry={()=>void loadSession()}/>;
 if(!config.root)return <><Association config={config} suggestion={suggestion} onSaved={saved} notify={notify}/>{toast&&<div role="status" className="toast">{toast}</div>}</>;
 return <div className="app">
  <Sidebar width={preferences.sidebarWidth} collapsed={preferences.sidebarCollapsed} mobileOpen={mobileOpen} onToggle={toggleSidebar} onWidth={sidebarWidth=>setPreferences({sidebarWidth})} onDismiss={()=>setMobileOpen(false)}>
   <div className="brand"><div className="brand-mark small"><BookOpen size={18}/></div><div><strong>本地知识库</strong><span title={config.root}>{fileName(config.root)}</span></div></div>
   <nav className="sidebar-shortcuts" aria-label="快捷入口">
    <button onClick={()=>setQuickSearch(true)}><Search size={17}/><span>搜索文件</span><kbd>{navigator.platform.includes('Mac')?'⌘':'Ctrl'} K</kbd></button>
    <button className={view==='home'?'active':''} onClick={showHome}><Home size={17}/>首页</button>
    <button className={view==='knowledge'?'active':''} onClick={showKnowledge}><Search size={17}/>知识检索</button>
    <button onClick={()=>void daily()}><Calendar size={17}/>今日笔记</button>
   </nav>
   <div className="section-label"><span>文件目录</span><div><Action title="刷新数据" onClick={refreshData}><RefreshCw size={14}/></Action><Action title="新建笔记" onClick={()=>newFile('file')}><Plus size={15}/></Action></div></div>
   <div className="file-tree"><DirectoryTree key={config.root} onOpen={openFile} onFolder={setCurrentFolder} selected={view==='document'?active:''} refresh={refresh} manage={manage}/></div>
   <div className="sidebar-tools"><button onClick={()=>newFile('folder')}><FolderPlus size={15}/>新建目录</button><button onClick={()=>inputFile.current?.click()}><Upload size={15}/>上传文件</button><button onClick={()=>void newTemplate()}><FilePlus size={15}/>从模板新建</button><button onClick={()=>setGraph(true)}><Network size={15}/>关系图</button><button onClick={()=>void record('operations')}><History size={15}/>目录操作历史</button><button onClick={()=>void record('trash')}><Trash2 size={15}/>回收区</button><button onClick={()=>setSettings(true)}><Settings size={15}/>设置</button></div><IndexStatus/>
  </Sidebar>
  <main className="main" inert={narrow&&mobileOpen}>
   {connectionError&&<div role="status" className="connection-banner">{connectionError}<button onClick={refreshData}>刷新数据</button></div>}
   <div className="workspace-topbar"><button className="icon-button sidebar-toggle" aria-label="切换导航" aria-controls="workspace-sidebar" aria-expanded={narrow?mobileOpen:!preferences.sidebarCollapsed} onClick={toggleSidebar}><PanelLeft size={17}/></button><Tabs tabs={tabs} active={active} view={view} knowledgeVisited={knowledgeVisited} onSelect={path=>{setBackToKnowledge(false);selectDocument(path);}} onClose={closeTab} onHome={showHome} onKnowledge={showKnowledge}/></div>
   {view==='home'&&<Dashboard config={config} recent={preferences.recent} onOpen={openFile} onCreate={()=>newFile('file')} onKnowledge={showKnowledge} onDaily={()=>void daily()}/>}
   {knowledgeVisited&&<LazyBoundary><Suspense fallback={view==='knowledge'?<p className="pad subtle">正在打开知识检索…</p>:null}><KnowledgeSearch key={config.root} active={view==='knowledge'} revision={config.revision} onOpen={path=>{setBackToKnowledge(true);void open(path);}} onSettings={()=>setSettings(true)}/></Suspense></LazyBoundary>}
   {view==='document'&&backToKnowledge&&<div className="return-search"><button onClick={showKnowledge}><ArrowLeft size={14}/>返回检索结果</button></div>}
   <div className="panes" hidden={view!=='document'}>{mounted.map(path=><div key={path} style={{display:view==='document'&&active===path?'contents':'none'}}><LazyBoundary><DocumentPane vaultRoot={config.root!} key={config.root+path} path={path} onOpen={open} notify={notify} onRecord={record} active={view==='document'&&active===path} wide={preferences.wide} onWidthChange={()=>setPreferences(value=>({wide:!value.wide}))}/></LazyBoundary></div>)}</div>
  </main>
  <input type="file" multiple ref={inputFile} hidden onChange={async event=>{for(const file of Array.from(event.target.files||[])){try{const response=await fetch('/api/upload?folder='+encodeURIComponent(currentFolder)+'&name='+encodeURIComponent(file.name),{method:'POST',headers:{'X-Vault-CSRF':csrf},body:file});const data=await response.json();if(!response.ok)throw new Error(data.error);notify('已上传 '+file.name);}catch(error){notify((error as Error).message);}}changed();event.target.value='';}}/>
  {quickSearch&&<LazyBoundary><Suspense fallback={<Modal title="搜索文件" onClose={()=>setQuickSearch(false)}><p className="pad subtle">正在打开搜索…</p></Modal>}><FileSearch key={config.root+'\n'+config.revision} recent={preferences.recent} onOpen={openFile} onClose={()=>setQuickSearch(false)}/></Suspense></LazyBoundary>}
  {settings&&<ConnectedSettings config={config} onSaved={saved} onClose={()=>setSettings(false)} notify={notify}/>}
  {graph&&<LazyBoundary><Suspense fallback={<Modal title="笔记关系" onClose={()=>setGraph(false)}><p className="pad subtle">正在打开图谱…</p></Modal>}><GraphView path={active} onOpen={(path,anchor)=>{setGraph(false);openFile(path,anchor);}} onClose={()=>setGraph(false)}/></Suspense></LazyBoundary>}
  {menu!==undefined&&<Modal title={fileName(menu)||'目录管理'} onClose={()=>setMenu(undefined)}><div className="action-list"><button onClick={()=>manage('rename',menu)}>重命名</button><button onClick={()=>manage('move',menu)}>移动</button><button onClick={()=>void record('history',menu)}>编辑历史</button><a href={media(menu,true)}>下载原文件</a><button className="danger" onClick={()=>manage('delete',menu)}>移入回收区</button></div></Modal>}
  {operation&&<FormDialog key={operation.kind+operation.path} title={{file:'新建笔记',folder:'新建目录',template:'从模板新建',rename:'重命名',move:'移动文件或目录',delete:'移入回收区'}[operation.kind]} description={operation.kind==='delete'?'将「'+operation.path+'」移入回收区？之后可以恢复。':operation.path||'位置：'+(currentFolder||'知识库根目录')} fields={fields} submitLabel={operation.kind==='delete'?'移入回收区':operation.kind==='move'?'移动':operation.kind==='rename'?'重命名':'创建'} danger={operation.kind==='delete'} onSubmit={submitOperation} onClose={()=>setOperation(undefined)}/>}
  {records&&<Modal title={{history:'编辑历史',trash:'回收区',operations:'目录操作历史'}[records.kind]||'历史记录'} onClose={()=>setRecords(undefined)}><div className="record-list">{records.data.length?records.data.map(record=><div className="record" key={record.id}><div><strong>{record.path}</strong><small>{new Date(record.time*1000).toLocaleString('zh-CN')}{record.destination?' → '+record.destination:''}</small></div><button onClick={async()=>{try{const restored=await api('restore',{kind:records.kind,id:record.id});window.dispatchEvent(new CustomEvent('vault-restored',{detail:restored.path}));notify('已恢复');changed();setRecords(undefined);}catch(error){notify((error as Error).message);}}}>恢复</button></div>):<p className="subtle">暂无记录</p>}</div></Modal>}
  {candidates&&candidates.length>1&&<Modal title="请选择同名文档" onClose={()=>setCandidates(undefined)}><div className="action-list">{candidates.map(path=><button key={path} onClick={()=>{setCandidates(undefined);selectDocument(path);}}>{path}</button>)}</div></Modal>}
  {toast&&<div role="status" className="toast">{toast}</div>}
 </div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
