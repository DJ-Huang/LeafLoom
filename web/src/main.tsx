import React,{lazy,Suspense,useCallback,useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {BookOpen,Calendar,Home,PanelLeft,Plus,RefreshCw,Search,Settings,ArrowLeft,Network} from 'lucide-react';
import {api,applySession,invalidate,media,Config,OpenNote,Session} from './api';
import {DirectoryTree,FolderView} from './tree';
import {Action,ActionMenu,Modal,LoadingShell,LazyBoundary,FormDialog,FormField} from './ui';
import {updateStatus} from './hooks';
import {Association,ConnectedSettings} from './settings';
import {SettingsLocation,SettingsResult,parentFolder} from './settings-model';
import {Dashboard,Sidebar,PathNavigation,IndexStatus,fileName,usePreferences} from './layout';
import './style.css';

let documentModule:Promise<typeof import('./document')>|undefined;
function DocumentPane(props:React.ComponentProps<typeof import('./document')['DocumentPane']>){
 const [component,setComponent]=useState<typeof import('./document')['DocumentPane']>(),[error,setError]=useState('');
 useEffect(()=>{let alive=true;void(documentModule||(documentModule=import('./document'))).then(module=>{if(alive)setComponent(()=>module.DocumentPane);}).catch(error=>{if(alive)setError(String(error));});return()=>{alive=false;};},[]);
 if(error)return <div className="empty-state">{error}<button onClick={()=>window.location.reload()}>重新加载页面</button></div>;
 const Component=component;return Component?<Component {...props}/>:<p className="pad subtle">正在打开内容…</p>;
}
const FileSearch=lazy(()=>import('./search').then(module=>({default:module.FileSearch})));
const KnowledgeSearch=lazy(()=>import('./search').then(module=>({default:module.KnowledgeSearch})));
const GraphPage=lazy(()=>import('./graph').then(module=>({default:module.GraphPage})));
type View='home'|'document'|'knowledge'|'folder'|'graph';
type FileOperation={kind:'file'|'rename'|'move'|'delete',path?:string};
const folderOf=(path:string)=>path.includes('/')?path.slice(0,path.lastIndexOf('/')):'';
const within=(path:string,parent:string)=>path===parent||path.startsWith(parent+'/');
function App(){
 const [config,setConfig]=useState<Config>(),[suggestion,setSuggestion]=useState(''),[tabs,setTabs]=useState<string[]>([]),[active,setActive]=useState(''),[view,setView]=useState<View>('home'),[knowledgeVisited,setKnowledgeVisited]=useState(false),[backToKnowledge,setBackToKnowledge]=useState(false);
 const [currentFolder,setCurrentFolder]=useState(''),[refresh,setRefresh]=useState(0),[settings,setSettings]=useState<SettingsLocation>(),[quickSearch,setQuickSearch]=useState(false),[toast,setToast]=useState(''),[menu,setMenu]=useState<string>(),[operation,setOperation]=useState<FileOperation>(),[candidates,setCandidates]=useState<string[]>(),[connectionError,setConnectionError]=useState(''),[mobileOpen,setMobileOpen]=useState(false);
 const [graphVisited,setGraphVisited]=useState(false),[backToGraph,setBackToGraph]=useState(false);
 const menuAnchor=useRef<HTMLElement|null>(null);
 const openSettings=useCallback((location:SettingsLocation={section:'general'})=>{setSettings(location);setMenu(undefined);},[]);
 const [narrow,setNarrow]=useState(()=>window.matchMedia('(max-width:900px)').matches);
 const [preferences,setPreferences]=usePreferences(config?.root||'');
 const session=useRef<Session|undefined>(undefined),sessionRequest=useRef(0),toastTimer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
 const notify=useCallback((message:string)=>{clearTimeout(toastTimer.current);setToast(message);toastTimer.current=setTimeout(()=>setToast(''),7000);},[]);
 useEffect(()=>()=>clearTimeout(toastTimer.current),[]);
 useEffect(()=>{const media=window.matchMedia('(max-width:900px)'),change=()=>{setNarrow(media.matches);setMobileOpen(false);};media.addEventListener('change',change);return()=>media.removeEventListener('change',change);},[]);
 const changed=useCallback(()=>setRefresh(value=>value+1),[]);
 const resetWorkspace=useCallback(()=>{setTabs([]);setActive('');setView('home');setKnowledgeVisited(false);setBackToKnowledge(false);setGraphVisited(false);setBackToGraph(false);setCurrentFolder('');setQuickSearch(false);setOperation(undefined);setMenu(undefined);setCandidates(undefined);setMobileOpen(false);history.replaceState(null,'','/');},[]);
 const loadSession=useCallback(async()=>{
  const request=++sessionRequest.current;
  try{const next=await api<Session>('session');if(request!==sessionRequest.current)return;const previous=session.current,scopeChanged=applySession(next);session.current=next;setConfig(value=>JSON.stringify(value)===JSON.stringify(next.config)?value:next.config);setSuggestion(next.suggested_root);setConnectionError('');
   if(!previous){const params=new URLSearchParams(location.search),target=params.get('note'),folder=params.get('folder');if(target&&next.config.root){setTabs([target]);setActive(target);setView('document');}else if(folder!==null&&next.config.root){setCurrentFolder(folder);setView('folder');}else if(params.get('view')==='knowledge'){setView('knowledge');setKnowledgeVisited(true);}else if(params.get('view')==='graph'){setView('graph');setGraphVisited(true);}}
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
 const showHome=()=>{setBackToGraph(false);setView('home');setMobileOpen(false);setBackToKnowledge(false);history.replaceState(null,'','/');};
 const showGraph=()=>{setView('graph');setGraphVisited(true);setMobileOpen(false);setBackToKnowledge(false);history.replaceState(null,'','/?view=graph');};
 const showKnowledge=()=>{setBackToGraph(false);setView('knowledge');setKnowledgeVisited(true);setMobileOpen(false);history.replaceState(null,'','/?view=knowledge');};
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
 const openFile:OpenNote=(path,anchor)=>{setBackToKnowledge(false);setBackToGraph(false);void open(path,anchor);};
 const showFolder=(path:string)=>{setBackToGraph(false);setCurrentFolder(path);setView('folder');setMobileOpen(false);setBackToKnowledge(false);history.replaceState(null,'','/?folder='+encodeURIComponent(path));};
 const toggleSidebar=useCallback(()=>{if(narrow)setMobileOpen(value=>!value);else setPreferences(value=>({sidebarCollapsed:!value.sidebarCollapsed}));},[narrow,setPreferences]);
 useEffect(()=>{const key=(event:KeyboardEvent)=>{if(event.isComposing||document.querySelector('dialog[open]'))return;if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){event.preventDefault();if(session.current?.config.root)setQuickSearch(true);}if((event.metaKey||event.ctrlKey)&&event.key==='\\'){event.preventDefault();toggleSidebar();}};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);},[toggleSidebar]);
 const saved=(next:Config)=>{sessionRequest.current++;if(next.root!==config?.root)resetWorkspace();if(session.current){session.current={...session.current,config:next};applySession(session.current);}setConfig(next);invalidate({reset:true});changed();void loadSession();};
 const moveFile=async(path:string,target:string)=>{
  const origin=session.current?.config.root,result=await api('move',{source:path,destination:target});if(origin!==session.current?.config.root)return;
  const remap=(item:string)=>within(item,path)?target+item.slice(path.length):item;
  setTabs(value=>value.map(remap));setActive(value=>value?remap(value):value);setCurrentFolder(value=>value?remap(value):value);setPreferences(value=>({recent:value.recent.map(remap)}));
  if(view==='document'&&active)history.replaceState(null,'','/?note='+encodeURIComponent(remap(active)));else if(view==='folder')history.replaceState(null,'','/?folder='+encodeURIComponent(remap(currentFolder)));
  changed();notify('已移动，修复 '+result.updated_links+' 篇文档的引用');
 };
 const manage=(action:string,path:string,destination?:string)=>{
  if(action==='menu'){menuAnchor.current=document.activeElement as HTMLElement;setMenu(path);return;}
  if(action==='move'&&destination){void moveFile(path,destination).catch(error=>notify(error.message));return;}
  if(action==='rename'||action==='move'||action==='delete'){setMenu(undefined);setOperation({kind:action,path});}
 };
 const record=useCallback((kind:string,path?:string)=>{openSettings({section:kind==='trash'?'trash':'history',path});},[openSettings]);
 const newFile=(kind:'file')=>setOperation({kind});
 const daily=async()=>{const origin=session.current?.config.root;try{const data=await api('daily',{});if(origin!==session.current?.config.root)return;if(data.created)sessionStorage.setItem('edit:'+data.path,'1');changed();openFile(data.path);}catch(error){notify((error as Error).message);}};
 const submitOperation=async(values:Record<string,string>)=>{
  if(!operation)return;const {kind,path=''}=operation,origin=session.current?.config.root;
  if(kind==='rename'||kind==='move'){const value=values.name.trim();if(!value)throw new Error('请输入名称或目标路径');await moveFile(path,kind==='rename'?[folderOf(path),value].filter(Boolean).join('/'):value);return;}
  if(kind==='delete'){await api('delete',{path});if(origin!==session.current?.config.root)return;const remaining=tabs.filter(item=>!within(item,path));setTabs(remaining);setPreferences(value=>({recent:value.recent.filter(item=>!within(item,path))}));if(within(active,path)){setActive(remaining[0]||'');if(view==='document'){if(remaining[0])selectDocument(remaining[0]);else showHome();}}if(within(currentFolder,path)){if(view==='folder')showFolder(folderOf(path));else setCurrentFolder(folderOf(path));}changed();notify('已移入回收区，可以恢复');return;}
  const name=values.name.trim();if(!name)throw new Error('请输入名称');const target=[currentFolder,name].filter(Boolean).join('/');
  const created=await api('create',{path:target,directory:false});
  if(origin!==session.current?.config.root)return;
  sessionStorage.setItem('edit:'+created.path,'1');setBackToKnowledge(false);setBackToGraph(false);selectDocument(created.path);changed();
 };
 const fields:FormField[]=operation?.kind==='delete'?[]:operation?[{name:'name',label:operation.kind==='move'?'目标路径（相对知识库根目录）':'名称',required:true,value:operation.kind==='rename'?fileName(operation.path!):operation.kind==='move'?operation.path:'未命名.md'}]:[];
 if(!config)return <LoadingShell error={connectionError} onRetry={()=>void loadSession()}/>;
 if(!config.root)return <><Association config={config} suggestion={suggestion} onSaved={saved} notify={notify}/>{toast&&<div role="status" className="toast">{toast}</div>}</>;
 return <div className="app">
  <Sidebar width={preferences.sidebarWidth} collapsed={preferences.sidebarCollapsed} mobileOpen={mobileOpen} onToggle={toggleSidebar} onWidth={sidebarWidth=>setPreferences({sidebarWidth})} onDismiss={()=>setMobileOpen(false)}>
   <div className="brand"><div className="brand-mark small"><BookOpen size={18}/></div><div><strong>本地知识库</strong><span title={config.root}>{fileName(config.root)}</span></div></div>
   <nav className="sidebar-shortcuts" aria-label="快捷入口">
    <button onClick={()=>setQuickSearch(true)}><Search size={17}/><span>搜索文件</span><kbd>{navigator.platform.includes('Mac')?'⌘':'Ctrl'} K</kbd></button>
    <button className={view==='home'?'active':''} onClick={showHome}><Home size={17}/>首页</button>
    <button className={view==='knowledge'?'active':''} onClick={showKnowledge}><Search size={17}/>知识检索</button>
    <button className={view==='graph'?'active':''} onClick={showGraph}><Network size={17}/>关系图谱</button>
    <button onClick={()=>void daily()}><Calendar size={17}/>今日笔记</button>
   </nav>
   <div className="section-label"><span>文件目录</span><div><Action title="刷新数据" onClick={refreshData}><RefreshCw size={14}/></Action><Action title="新建笔记" onClick={()=>newFile('file')}><Plus size={15}/></Action></div></div>
   <div className="file-tree"><DirectoryTree key={config.root} onOpen={openFile} onFolder={setCurrentFolder} selected={view==='document'?active:''} refresh={refresh} manage={manage}/></div>
   <div className="sidebar-tools"><button onClick={()=>openSettings()}><Settings size={16}/>设置</button></div><IndexStatus onOpen={()=>openSettings({section:'index',targetId:'sync'})}/>
  </Sidebar>
  <main className="main" inert={narrow&&mobileOpen}>
   {connectionError&&<div role="status" className="connection-banner">{connectionError}<button onClick={refreshData}>刷新数据</button></div>}
   <div className="workspace-topbar"><button className="icon-button sidebar-toggle" aria-label="切换导航" aria-controls="workspace-sidebar" aria-expanded={narrow?mobileOpen:!preferences.sidebarCollapsed} onClick={toggleSidebar}><PanelLeft size={17}/></button><PathNavigation view={view} path={view==='document'?active:currentFolder} onFolder={showFolder}/></div>
   {view==='home'&&<Dashboard config={config} recent={preferences.recent} onOpen={openFile} onCreate={()=>newFile('file')} onKnowledge={showKnowledge} onDaily={()=>void daily()}/>}
   {view==='folder'&&<FolderView key={config.root+'\n'+currentFolder} path={currentFolder} onOpen={openFile} onFolder={showFolder} onCreate={()=>newFile('file')} refresh={refresh} manage={manage}/>}
   {knowledgeVisited&&<LazyBoundary><Suspense fallback={view==='knowledge'?<p className="pad subtle">正在打开知识检索…</p>:null}><KnowledgeSearch key={config.root} active={view==='knowledge'} revision={config.revision} onOpen={path=>{setBackToKnowledge(true);setBackToGraph(false);void open(path);}} onSettings={()=>openSettings({section:'index',targetId:'scope'})}/></Suspense></LazyBoundary>}
   {graphVisited&&<LazyBoundary><Suspense fallback={view==='graph'?<p className="pad subtle">正在打开关系图谱…</p>:null}><GraphPage key={config.root} path={active} active={view==='graph'} onOpen={path=>{setBackToKnowledge(false);setBackToGraph(true);void open(path);}}/></Suspense></LazyBoundary>}
   {view==='document'&&backToGraph&&<div className="return-search"><button onClick={showGraph}><ArrowLeft size={14}/>返回关系图谱</button></div>}
   {view==='document'&&backToKnowledge&&<div className="return-search"><button onClick={showKnowledge}><ArrowLeft size={14}/>返回检索结果</button></div>}
   <div className="panes" hidden={view!=='document'}>{mounted.map(path=><div key={path} style={{display:view==='document'&&active===path?'contents':'none'}}><LazyBoundary><DocumentPane vaultRoot={config.root!} key={config.root+path} path={path} onOpen={open} notify={notify} onRecord={record} active={view==='document'&&active===path} wide={preferences.wide} onWidthChange={()=>setPreferences(value=>({wide:!value.wide}))}/></LazyBoundary></div>)}</div>
  </main>
  {quickSearch&&<LazyBoundary><Suspense fallback={<Modal title="搜索文件" onClose={()=>setQuickSearch(false)}><p className="pad subtle">正在打开搜索…</p></Modal>}><FileSearch key={config.root+'\n'+config.revision} recent={preferences.recent} onOpen={openFile} onClose={()=>setQuickSearch(false)}/></Suspense></LazyBoundary>}
  {settings&&<ConnectedSettings config={config} location={settings} folder={view==='document'?parentFolder(active):currentFolder} onSaved={saved} onClose={()=>setSettings(undefined)} notify={notify} onChanged={changed} onOpen={(result:SettingsResult)=>{if(result.directory){showFolder(result.path);return;}if(result.edit)sessionStorage.setItem('edit:'+result.path,'1');if(result.cursor!=null)sessionStorage.setItem('cursor:'+result.path,String(result.cursor));setBackToKnowledge(false);setBackToGraph(false);selectDocument(result.path);}}/>}
  {menu!==undefined&&menuAnchor.current&&<ActionMenu title={fileName(menu)||'目录管理'} anchor={menuAnchor.current} onClose={()=>setMenu(undefined)}><button onClick={()=>manage('rename',menu)}>重命名</button><button onClick={()=>manage('move',menu)}>移动</button><button onClick={()=>record('history',menu)}>编辑历史</button><a href={media(menu,true)}>下载原文件</a><button className="danger" onClick={()=>manage('delete',menu)}>移入回收区</button></ActionMenu>}
  {operation&&<FormDialog key={operation.kind+operation.path} title={{file:'新建笔记',rename:'重命名',move:'移动文件或目录',delete:'移入回收区'}[operation.kind]} description={operation.kind==='delete'?'将「'+operation.path+'」移入回收区？之后可以恢复。':operation.path||'位置：'+(currentFolder||'知识库根目录')} fields={fields} submitLabel={operation.kind==='delete'?'移入回收区':operation.kind==='move'?'移动':operation.kind==='rename'?'重命名':'创建'} danger={operation.kind==='delete'} onSubmit={submitOperation} onClose={()=>setOperation(undefined)}/>}
  {candidates&&candidates.length>1&&<Modal title="请选择同名文档" onClose={()=>setCandidates(undefined)}><div className="action-list">{candidates.map(path=><button key={path} onClick={()=>{setCandidates(undefined);selectDocument(path);}}>{path}</button>)}</div></Modal>}
  {toast&&<div role="status" className="toast">{toast}</div>}
 </div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
