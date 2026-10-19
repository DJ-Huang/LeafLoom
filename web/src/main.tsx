import {Diagnostic} from './i18n';
import {getLocale,t,useLocale} from './i18n';
import React,{lazy,Suspense,useCallback,useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {BookOpen,Calendar,Home,PanelLeft,Plus,RefreshCw,Search,Settings,ArrowLeft,Network,MessageSquare,Globe,Paperclip,Palette} from 'lucide-react';
import {api,applySession,invalidate,media,Config,OpenNote,Session} from './api';
import {DirectoryTree,FolderView} from './tree';
import {Action,ActionMenu,Modal,LoadingShell,LazyBoundary,FormDialog,FormField} from './ui';
import {updateStatus} from './hooks';
import {Association,ConnectedSettings} from './settings';
import {SettingsLocation,SettingsResult,parentFolder} from './settings-model';
import {Dashboard,Sidebar,PathNavigation,IndexStatus,fileName,usePreferences} from './layout';
import './style.css';
import './ai.css';
import {AiSelectionEvent} from './ai-context';
import {Welcome,SetupGuide,GettingStarted,Guide,UserPreferences} from './onboarding';
import {setLocale} from './i18n';
import {Logo} from './brand';
import {StorageMigrationNotice} from './storage-migration';
import {HtmlPreview} from './html-preview';
const Attachments=lazy(()=>import('./attachments').then(module=>({default:module.Attachments})));
const DesignStudio=lazy(()=>import('./design-studio').then(module=>({default:module.DesignStudio})));

let documentModule:Promise<typeof import('./document')>|undefined;
function DocumentPane(props:React.ComponentProps<typeof import('./document')['DocumentPane']>){
 useLocale();
 const [component,setComponent]=useState<typeof import('./document')['DocumentPane']>(),[error,setError]=useState('');
 useEffect(()=>{let alive=true;void(documentModule||(documentModule=import('./document'))).then(module=>{if(alive)setComponent(()=>module.DocumentPane);}).catch(error=>{if(alive)setError(String(error));});return()=>{alive=false;};},[]);
 if(error)return <div className="empty-state">{<Diagnostic message={error}/>}<button onClick={()=>window.location.reload()}>{t("重新加载页面")}</button></div>;
 const Component=component;return Component?<Component {...props}/>:<p className="pad subtle">{t("正在打开内容…")}</p>;
}
const FileSearch=lazy(()=>import('./search').then(module=>({default:module.FileSearch})));
const KnowledgeSearch=lazy(()=>import('./search').then(module=>({default:module.KnowledgeSearch})));
const GraphPage=lazy(()=>import('./graph').then(module=>({default:module.GraphPage})));
const AiPanel=lazy(()=>import('./ai-panel').then(module=>({default:module.AiPanel})));
type View='home'|'document'|'knowledge'|'folder'|'graph'|'web'|'design'|'attachments';
type FileOperation={kind:'file'|'rename'|'move'|'delete',path?:string};
const folderOf=(path:string)=>path.includes('/')?path.slice(0,path.lastIndexOf('/')):'';
const within=(path:string,parent:string)=>path===parent||path.startsWith(parent+'/');
function App(){
 useEffect(()=>{
  let last=0;
  const activity=()=>{if(document.hidden||Date.now()-last<1000)return;last=Date.now();void api('activity',{}).catch(()=>{});};
  const events=['pointerdown','pointermove','wheel','touchmove','keydown','focus'];
  for(const event of events)window.addEventListener(event,activity,{passive:true});
  return()=>{for(const event of events)window.removeEventListener(event,activity);};
 },[]);
 useLocale();
 const [guide,setGuide]=useState<Guide|null>(null),[demoMode,setDemoMode]=useState(false);
 const saveGuide=useCallback(async(values:Partial<Guide>)=>{const next=await api<UserPreferences>('preferences',{guide:values},'PUT');setGuide(next.guide);},[]);
 const [config,setConfig]=useState<Config>(),[suggestion,setSuggestion]=useState(''),[tabs,setTabs]=useState<string[]>([]),[active,setActive]=useState(''),[view,setView]=useState<View>('home'),[knowledgeVisited,setKnowledgeVisited]=useState(false),[backToKnowledge,setBackToKnowledge]=useState(false);
 const [currentFolder,setCurrentFolder]=useState(''),[refresh,setRefresh]=useState(0),[settings,setSettings]=useState<SettingsLocation>(),[quickSearch,setQuickSearch]=useState(false),[toast,setToast]=useState(''),[menu,setMenu]=useState<string>(),[operation,setOperation]=useState<FileOperation>(),[candidates,setCandidates]=useState<string[]>(),[connectionError,setConnectionError]=useState(''),[mobileOpen,setMobileOpen]=useState(false);
 const [attachmentsVisited,setAttachmentsVisited]=useState(false);
 const [graphVisited,setGraphVisited]=useState(false),[backToGraph,setBackToGraph]=useState(false);
 const [designCreateFolder,setDesignCreateFolder]=useState<string|undefined>();
 const [aiOpen,setAiOpen]=useState(()=>sessionStorage.getItem('ai-open')==='true'),[aiVisited,setAiVisited]=useState(()=>sessionStorage.getItem('ai-open')==='true'),[aiSelection,setAiSelection]=useState<{id:string,reference:AiSelectionEvent['reference']}>();
 useEffect(()=>{sessionStorage.setItem('ai-open',String(aiOpen));if(aiOpen)setAiVisited(true);},[aiOpen]);
 useEffect(()=>{const add=(event:Event)=>{const {reference}=(event as CustomEvent<AiSelectionEvent>).detail;setAiSelection({id:crypto.randomUUID(),reference});setAiOpen(true);setAiVisited(true);};window.addEventListener('vault-ai-reference',add);return()=>window.removeEventListener('vault-ai-reference',add);},[]);
 const menuAnchor=useRef<HTMLElement|null>(null);
 const openSettings=useCallback((location:SettingsLocation={section:'general'})=>{setSettings(location);setMenu(undefined);},[]);
 const [narrow,setNarrow]=useState(()=>window.matchMedia('(max-width:900px)').matches);
 const [preferences,setPreferences]=usePreferences(config?.root||'');
 const session=useRef<Session|undefined>(undefined),sessionRequest=useRef(0),toastTimer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
 const notify=useCallback((message:string)=>{clearTimeout(toastTimer.current);setToast(message);toastTimer.current=setTimeout(()=>setToast(''),7000);},[]);
 useEffect(()=>()=>clearTimeout(toastTimer.current),[]);
 useEffect(()=>{const media=window.matchMedia('(max-width:900px)'),change=()=>{setNarrow(media.matches);setMobileOpen(false);};media.addEventListener('change',change);return()=>media.removeEventListener('change',change);},[]);
 const changed=useCallback(()=>setRefresh(value=>value+1),[]);
 const resetWorkspace=useCallback(()=>{setAttachmentsVisited(false);setTabs([]);setActive('');setView('home');setKnowledgeVisited(false);setBackToKnowledge(false);setGraphVisited(false);setBackToGraph(false);setCurrentFolder('');setQuickSearch(false);setOperation(undefined);setMenu(undefined);setCandidates(undefined);setMobileOpen(false);history.replaceState(null,'','/');},[]);
 const loadSession=useCallback(async()=>{
  const request=++sessionRequest.current;
  try{const next=await api<Session>('session');if(request!==sessionRequest.current)return;const previous=session.current,scopeChanged=applySession(next);session.current=next;setConfig(value=>JSON.stringify(value)===JSON.stringify(next.config)?value:next.config);setSuggestion(next.suggested_root);setConnectionError('');
   if(!previous){const params=new URLSearchParams(location.search),target=params.get('note'),folder=params.get('folder');if(target&&next.config.root){setTabs([target]);setActive(target);setView('document');}else if(folder!==null&&next.config.root){setCurrentFolder(folder);setView('folder');}else if(params.get('view')==='knowledge'){setView('knowledge');setKnowledgeVisited(true);}else if(params.get('view')==='attachments'){setView('attachments');setAttachmentsVisited(true);}else if(params.get('view')==='web'){setView('web');}else if(params.get('view')==='design'){setView('design');}else if(params.get('view')==='graph'){setView('graph');setGraphVisited(true);}}
   else if(previous.config.root!==next.config.root)resetWorkspace();
   if(scopeChanged&&previous)invalidate({reset:true});
   const [status,userPreferences]=await Promise.all([api('status'),api<UserPreferences>('preferences')]);if(request===sessionRequest.current){updateStatus(status);setLocale(userPreferences.locale);setGuide(userPreferences.guide);setDemoMode(!!next.demo);}
  }catch(error){if(request===sessionRequest.current)setConnectionError((error as Error).message);}
 },[resetWorkspace]);
 useEffect(()=>{void loadSession();let alive=true;const events=new EventSource('/api/events');let connected=false;
  events.onmessage=event=>{if(!alive)return;try{const change=JSON.parse(event.data);if(change.type==='status'){updateStatus(change.status);return;}if(change.type==='reset'){if(connected)invalidate({reset:true});connected=true;void loadSession();return;}if(change.type==='config'||change.service_instance_id!==session.current?.service_instance_id||change.config_revision!==session.current?.config.revision){void loadSession();return;}if(change.type==='files')invalidate(change);}catch{setConnectionError(t("服务通知暂不可用，请刷新数据"));}};
  events.onopen=()=>{if(alive)setConnectionError('');};events.onerror=()=>{if(alive)setConnectionError(t("与本地服务的连接中断，正在重试；你的草稿仍保留"));};
  const close=()=>events.close();window.addEventListener('pagehide',close);const resume=()=>{if(events.readyState===EventSource.CLOSED)window.location.reload();};window.addEventListener('pageshow',resume);
  return()=>{alive=false;events.close();window.removeEventListener('pagehide',close);window.removeEventListener('pageshow',resume);};
 },[loadSession]);
 useEffect(()=>{if(active&&config?.root)setPreferences(value=>({recent:[active,...value.recent.filter(path=>path!==active)].slice(0,12)}));},[active,config?.root,setPreferences]);
 const mounted=[active,...preferences.recent.filter(path=>path!==active&&tabs.includes(path))].filter(Boolean).slice(0,3);
 const refreshData=useCallback(()=>{invalidate({reset:true});void loadSession();},[loadSession]);
 const showHome=()=>{setBackToGraph(false);setView('home');setMobileOpen(false);setBackToKnowledge(false);history.replaceState(null,'','/');};
 const showGraph=()=>{setView('graph');setGraphVisited(true);setMobileOpen(false);setBackToKnowledge(false);history.replaceState(null,'','/?view=graph');};
 const showKnowledge=()=>{setBackToGraph(false);setView('knowledge');setKnowledgeVisited(true);setMobileOpen(false);history.replaceState(null,'','/?view=knowledge');};
 const showDesign=(createFolder?:string)=>{setBackToGraph(false);setBackToKnowledge(false);if(createFolder!==undefined)setDesignCreateFolder(createFolder);setView('design');setMobileOpen(false);history.replaceState(null,'','/?view=design');};
 const selectDocument=useCallback((path:string)=>{setTabs(value=>value.includes(path)?value:[...value,path]);setActive(path);setView('document');setMobileOpen(false);history.replaceState(null,'','/?note='+encodeURIComponent(path));},[]);
 const open=useCallback<OpenNote>(async(target,anchor)=>{
  const origin=session.current?.config.root;
  try{const split=target.split('|')[0].split('#'),part=split[0],data=await api('resolve?target='+encodeURIComponent(part||active)+'&source='+encodeURIComponent(active));
   if(session.current?.config.root!==origin)return;
   if(data.candidates.length!==1){setCandidates(data.candidates);if(!data.candidates.length)notify(t("没有找到文档：")+target);return;}
   const path=data.candidates[0];selectDocument(path);
   if(anchor||split[1]){sessionStorage.setItem('jump:'+path,anchor||split[1]);window.dispatchEvent(new CustomEvent('vault-navigation-anchor',{detail:path}));}
  }catch(error){notify((error as Error).message);}
 },[active,notify,selectDocument]);
 const openFile:OpenNote=(path,anchor)=>{setBackToKnowledge(false);setBackToGraph(false);void open(path,anchor);};
 const showFolder=(path:string)=>{setBackToGraph(false);setCurrentFolder(path);setView('folder');setMobileOpen(false);setBackToKnowledge(false);history.replaceState(null,'','/?folder='+encodeURIComponent(path));};
 const toggleSidebar=useCallback(()=>{if(narrow)setMobileOpen(value=>!value);else setPreferences(value=>({sidebarCollapsed:!value.sidebarCollapsed}));},[narrow,setPreferences]);
 useEffect(()=>{const key=(event:KeyboardEvent)=>{if(event.defaultPrevented||event.isComposing||document.querySelector('dialog[open]'))return;if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){event.preventDefault();if(session.current?.config.root)setQuickSearch(true);}if((event.metaKey||event.ctrlKey)&&event.key==='\\'){event.preventDefault();toggleSidebar();}};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);},[toggleSidebar]);
 const saved=(next:Config)=>{sessionRequest.current++;if(next.root!==config?.root)resetWorkspace();if(session.current){session.current={...session.current,config:next};applySession(session.current);}setConfig(next);invalidate({reset:true});changed();void loadSession();};
 const moveFile=async(path:string,target:string)=>{
  const origin=session.current?.config.root,result=await api('move',{source:path,destination:target});if(origin!==session.current?.config.root)return;
  const remap=(item:string)=>within(item,path)?target+item.slice(path.length):item;
  setTabs(value=>value.map(remap));setActive(value=>value?remap(value):value);setCurrentFolder(value=>value?remap(value):value);setPreferences(value=>({recent:value.recent.map(remap)}));
  if(view==='document'&&active)history.replaceState(null,'','/?note='+encodeURIComponent(remap(active)));else if(view==='folder')history.replaceState(null,'','/?folder='+encodeURIComponent(remap(currentFolder)));
  changed();notify(t("已移动，修复 ")+result.updated_links+t(" 篇文档的引用"));
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
  if(kind==='rename'||kind==='move'){const value=values.name.trim();if(!value)throw new Error(t("请输入名称或目标路径"));await moveFile(path,kind==='rename'?[folderOf(path),value].filter(Boolean).join('/'):value);return;}
  if(kind==='delete'){await api('delete',{path});if(origin!==session.current?.config.root)return;const remaining=tabs.filter(item=>!within(item,path));setTabs(remaining);setPreferences(value=>({recent:value.recent.filter(item=>!within(item,path))}));if(within(active,path)){setActive(remaining[0]||'');if(view==='document'){if(remaining[0])selectDocument(remaining[0]);else showHome();}}if(within(currentFolder,path)){if(view==='folder')showFolder(folderOf(path));else setCurrentFolder(folderOf(path));}changed();notify(t("已移入回收区，可以恢复"));return;}
  const name=values.name.trim();if(!name)throw new Error(t("请输入名称"));const target=[currentFolder,name].filter(Boolean).join('/');
  const created=await api('create',{path:target,directory:false});
  if(origin!==session.current?.config.root)return;
  sessionStorage.setItem('edit:'+created.path,'1');setBackToKnowledge(false);setBackToGraph(false);selectDocument(created.path);changed();
 };
 const fields:FormField[]=operation?.kind==='delete'?[]:operation?[{name:'name',label:operation.kind==='move'?t("目标路径（相对知识库根目录）"):t("名称"),required:true,value:operation.kind==='rename'?fileName(operation.path!):operation.kind==='move'?operation.path:t("未命名.md")}]:[];
 if(!config)return <LoadingShell error={connectionError} onRetry={()=>void loadSession()}/>;
 if(!config.root)return <><Welcome config={config} onSaved={saved} notify={notify}/>{toast&&<div role="status" className="toast">{toast}</div>}</>;
 return <div className="app">
  <Sidebar width={preferences.sidebarWidth} collapsed={preferences.sidebarCollapsed} mobileOpen={mobileOpen} onToggle={toggleSidebar} onWidth={sidebarWidth=>setPreferences({sidebarWidth})} onDismiss={()=>setMobileOpen(false)}>
   <div className="brand"><div className="brand-mark small"><Logo size={30}/></div><div><strong>{t("本地知识库")}</strong><span title={config.root}>{fileName(config.root)}</span></div></div>
   <nav className="sidebar-shortcuts" aria-label={t("快捷入口")}>
    <button onClick={()=>setQuickSearch(true)}><Search size={17}/><span>{t("搜索文件")}</span><kbd>{navigator.platform.includes('Mac')?'⌘':'Ctrl'} K</kbd></button>
    <button className={view==='home'?'active':''} onClick={showHome}><Home size={17}/>{t("首页")}</button>
    <button className={view==='knowledge'?'active':''} onClick={showKnowledge}><Search size={17}/>{t("知识检索")}</button>
    <button className={view==='graph'?'active':''} onClick={showGraph}><Network size={17}/>{t("关系图谱")}</button>
    <button className={view==='design'?'active':''} onClick={()=>showDesign()}><Palette size={17}/>{t('设计工作台')}</button>
    <button className={view==='web'?'active':''} onClick={()=>{setView('web');setMobileOpen(false);history.replaceState(null,'','/?view=web');}}><Globe size={17}/>{t('网页')}</button>
    <button className={view==='attachments'?'active':''} onClick={()=>{setView('attachments');setAttachmentsVisited(true);setMobileOpen(false);history.replaceState(null,'','/?view=attachments');}}><Paperclip size={17}/>{t('attachments.title')}</button>
    <button onClick={()=>void daily()}><Calendar size={17}/>{t("今日笔记")}</button>
   </nav>
   <div className="section-label"><span>{t("文件目录")}</span><div><Action title={t("刷新数据")} onClick={refreshData}><RefreshCw size={14}/></Action><Action title={t("新建笔记")} onClick={()=>newFile('file')}><Plus size={15}/></Action></div></div>
   <div className="file-tree"><DirectoryTree key={config.root} onOpen={openFile} onFolder={setCurrentFolder} selected={view==='document'?active:''} refresh={refresh} manage={manage}/></div>
   <div className="sidebar-tools"><button onClick={()=>openSettings()}><Settings size={16}/>{t("设置")}</button><button className="help-button" onClick={()=>{showHome();void saveGuide({step:'done',dismissed:false}).catch(error=>notify(error.message));}}>{t("新手指南")}</button><a href={`https://dj-huang.github.io/LeafLoom/docs/${getLocale()}/`} target="_blank" rel="noopener noreferrer"><BookOpen size={16}/>{t('help.center')}</a></div><IndexStatus onOpen={()=>openSettings({section:'index',targetId:'sync'})}/>
  </Sidebar>
  <main className="main" inert={narrow&&mobileOpen}><StorageMigrationNotice/>
   {connectionError&&<div role="status" className="connection-banner">{<Diagnostic message={connectionError}/>}<button onClick={refreshData}>{t("刷新数据")}</button></div>}
   <div className="workspace-topbar"><button className="icon-button sidebar-toggle" aria-label={t("切换导航")} aria-controls="workspace-sidebar" aria-expanded={narrow?mobileOpen:!preferences.sidebarCollapsed} onClick={toggleSidebar}><PanelLeft size={17}/></button><PathNavigation view={view} path={view==='document'?active:currentFolder} onFolder={showFolder}/><button className="ai-open-button" aria-expanded={aiOpen} onClick={()=>setAiOpen(value=>!value)}><MessageSquare size={15}/>{t("AI 对话")}</button></div>
   {view==='home'&&<Dashboard config={config} recent={preferences.recent} onOpen={openFile} onCreate={()=>newFile('file')} onKnowledge={showKnowledge} onDaily={()=>void daily()} onDesign={()=>showDesign()} guideContent={<GettingStarted guide={guide} onGuide={saveGuide} onAction={action=>{if(action==='create')newFile('file');else if(action==='search'||action==='source')showKnowledge();else if(action==='graph')showGraph();else if(action==='ai'){setAiOpen(true);setAiVisited(true);}else if(config.homepage)openFile(config.homepage);else showFolder('');}}/>}/>}
   {attachmentsVisited&&<LazyBoundary><Suspense fallback={view==='attachments'?<p className="pad subtle">{t('aw.loading')}</p>:null}><Attachments key={config.root} root={config.root!} active={view==='attachments'} onOpen={path=>openFile(path)} onChanged={changed}/></Suspense></LazyBoundary>}
   {view==='web'&&<HtmlPreview path="" root={config.root} active/>}
   {view==='design'&&<LazyBoundary><Suspense fallback={<p className="pad subtle">{t('正在加载设计工作台画板…')}</p>}><DesignStudio root={config.root} active={view==='design'} initialFolder={currentFolder} createInFolder={designCreateFolder} onClearCreateInFolder={()=>setDesignCreateFolder(undefined)} onOpenNote={openFile} onOpenFolder={showFolder} notify={notify} refresh={refresh}/></Suspense></LazyBoundary>}
   {view==='folder'&&<FolderView key={config.root+'\n'+currentFolder} path={currentFolder} onOpen={openFile} onFolder={showFolder} onCreate={()=>newFile('file')} onCreateDesign={folder=>showDesign(folder)} refresh={refresh} manage={manage}/>}
   {knowledgeVisited&&<LazyBoundary><Suspense fallback={view==='knowledge'?<p className="pad subtle">{t("正在打开知识检索…")}</p>:null}><KnowledgeSearch key={config.root} active={view==='knowledge'} revision={config.revision} onOpen={path=>{setBackToKnowledge(true);setBackToGraph(false);void open(path);}} onSettings={()=>openSettings({section:'index',targetId:'scope'})}/></Suspense></LazyBoundary>}
   {graphVisited&&<LazyBoundary><Suspense fallback={view==='graph'?<p className="pad subtle">{t("正在打开关系图谱…")}</p>:null}><GraphPage key={config.root} path={active} active={view==='graph'} onOpen={path=>{setBackToKnowledge(false);setBackToGraph(true);void open(path);}}/></Suspense></LazyBoundary>}
   {view==='document'&&backToGraph&&<div className="return-search"><button onClick={showGraph}><ArrowLeft size={14}/>{t("返回关系图谱")}</button></div>}
   {view==='document'&&backToKnowledge&&<div className="return-search"><button onClick={showKnowledge}><ArrowLeft size={14}/>{t("返回检索结果")}</button></div>}
   <div className="panes" hidden={view!=='document'}>{mounted.map(path=><div key={path} style={{display:view==='document'&&active===path?'contents':'none'}}><LazyBoundary><DocumentPane vaultRoot={config.root!} key={config.root+path} path={path} onOpen={open} notify={notify} onRecord={record} active={view==='document'&&active===path} wide={preferences.wide} onWidthChange={()=>setPreferences(value=>({wide:!value.wide}))}/></LazyBoundary></div>)}</div>
  </main>
  {aiVisited&&<LazyBoundary><Suspense fallback={aiOpen?<aside className="ai-panel"><p className="pad subtle">{t("正在打开 AI 对话…")}</p></aside>:null}><AiPanel key={config.root} config={config} path={view==='document'?active:''} visible={aiOpen} onClose={()=>setAiOpen(false)} onOpen={openFile} notify={notify} selection={aiSelection} demo={demoMode}/></Suspense></LazyBoundary>}
  {quickSearch&&<LazyBoundary><Suspense fallback={<Modal title={t("搜索文件")} onClose={()=>setQuickSearch(false)}><p className="pad subtle">{t("正在打开搜索…")}</p></Modal>}><FileSearch key={config.root+'\n'+config.revision} recent={preferences.recent} onOpen={openFile} onClose={()=>setQuickSearch(false)}/></Suspense></LazyBoundary>}
  {settings&&<ConnectedSettings config={config} location={settings} folder={view==='document'?parentFolder(active):currentFolder} onSaved={saved} onClose={()=>setSettings(undefined)} notify={notify} onChanged={changed} onOpen={(result:SettingsResult)=>{if(result.directory){showFolder(result.path);return;}if(result.edit)sessionStorage.setItem('edit:'+result.path,'1');if(result.cursor!=null)sessionStorage.setItem('cursor:'+result.path,String(result.cursor));setBackToKnowledge(false);setBackToGraph(false);selectDocument(result.path);}}/>}
  {menu!==undefined&&menuAnchor.current&&<ActionMenu title={fileName(menu)||t("目录管理")} anchor={menuAnchor.current} onClose={()=>setMenu(undefined)}><button onClick={()=>{const dir=/\.[a-zA-Z0-9]+$/.test(fileName(menu))?folderOf(menu):menu;setMenu(undefined);showDesign(dir);}}>{t("在此新建设计项目")}</button><button onClick={()=>manage('rename',menu)}>{t("重命名")}</button><button onClick={()=>manage('move',menu)}>{t("移动")}</button><button onClick={()=>record('history',menu)}>{t("编辑历史")}</button>{window.leafloomDesktop&&<button onClick={()=>{void window.leafloomDesktop!.revealFile(menu).catch(error=>notify(error.message));setMenu(undefined);}}>{t("在文件管理器中显示")}</button>}<a href={media(menu,true)}>{t("下载原文件")}</a><button className="danger" onClick={()=>manage('delete',menu)}>{t("移入回收区")}</button></ActionMenu>}
  {operation&&<FormDialog key={operation.kind+operation.path} title={{file:t("新建笔记"),rename:t("重命名"),move:t("移动文件或目录"),delete:t("移入回收区")}[operation.kind]} description={operation.kind==='delete'?t("将「")+operation.path+t("」移入回收区？之后可以恢复。"):operation.path||t("位置：")+(currentFolder||t("知识库根目录"))} fields={fields} submitLabel={operation.kind==='delete'?t("移入回收区"):operation.kind==='move'?t("移动"):operation.kind==='rename'?t("重命名"):t("创建")} danger={operation.kind==='delete'} onSubmit={submitOperation} onClose={()=>setOperation(undefined)}/>}
  {candidates&&candidates.length>1&&<Modal title={t("请选择同名文档")} onClose={()=>setCandidates(undefined)}><div className="action-list">{candidates.map(path=><button key={path} onClick={()=>{setCandidates(undefined);selectDocument(path);}}>{path}</button>)}</div></Modal>}
  {guide&&guide.step!=='done'&&<SetupGuide config={config} guide={guide} onSaved={saved} onGuide={saveGuide}/>}
  {toast&&<div role="status" className="toast">{toast}</div>}
 </div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
