import {Diagnostic,t,useLocale} from './i18n';
import React,{useCallback,useEffect,useRef,useState} from 'react';
import {CheckCircle2,ExternalLink,Folder,FolderOpen,Layers,Maximize,Minimize,MessageSquare,Palette,Play,Plus,RefreshCw,Save} from 'lucide-react';
import {api,Change,OpenNote} from './api';
import {Modal} from './ui';
import {DirectoryTree} from './tree';
import {addAiReference} from './ai-context';
import {DesignWorkbench} from './design-workbench';
import {DesignProjects} from './design-projects';
import './design-projects.css';

export type DesignScreenSummary={
 id:string;
 name:string;
 group:string;
 width:number;
 height:number;
 base?:string;
};

export type DesignProjectSummary={
 managed?:boolean;
 cover?:string;
 id:string;
 name:string;
 directory:string;
 spec_path:string;
 entry:string;
 portal_entry:string;
 html_project_id:string|null;
 standard_version:string;
 platforms:string[];
 orientation:string;
 width:number;
 height:number;
 screen_count:number;
 variant_count:number;
 board_count:number;
 asset_count:number;
 transformed_layer_count:number;
 screens:DesignScreenSummary[];
};

type WebSession={id:string|null,url:string,origin?:string,entry?:string,mode:'saved'|'draft'|'external'};

type CheckReport={
 ok:boolean;
 directory:string;
 summary?:Record<string,any>;
 errors:string[];
 warnings:string[];
};

type SelectedLayerInfo={
 id:string;
 name:string;
 type:string;
 x:number;
 y:number;
 width:number;
 height:number;
 opacity?:string;
 text?:string;
 assetId?:string;
 sourceRef?:string;
 transform?:Record<string,any>;
};

const PRESET_OPTIONS=[
 {value:'mobile-portrait',label:'移动端竖屏 (720×1560)',width:720,height:1560},
 {value:'game-landscape',label:'游戏横屏 (1560×720)',width:1560,height:720},
 {value:'desktop-web',label:'桌面网页 (1440×900)',width:1440,height:900},
 {value:'custom',label:'自定义画板尺寸',width:720,height:1560},
];

export function DesignStudio({
 root,
 active,
 initialFolder='',
 createInFolder,
 onClearCreateInFolder,
 onOpenNote,
 onOpenFolder,
 notify,
 refresh,
}:{
 root:string;
 active:boolean;
 initialFolder?:string;
 createInFolder?:string;
 onClearCreateInFolder?:()=>void;
 onOpenNote:OpenNote;
 onOpenFolder:(path:string)=>void;
 notify:(message:string)=>void;
 refresh:number;
}){
 useLocale();
 const frame=useRef<HTMLIFrameElement>(null),currentSession=useRef<WebSession|null>(null);
 const [projects,setProjects]=useState<DesignProjectSummary[]>([]);
 const [selectedDir,setSelectedDir]=useState<string>('');
 const [loading,setLoading]=useState(true);
 const [error,setError]=useState('');
 const [session,setSession]=useState<WebSession|null>(null);
 const [frameBusy,setFrameBusy]=useState(false);
 const [revision,setRevision]=useState(0);
 const [full,setFull]=useState(false);
 const [showHome,setShowHome]=useState(true);

 // Live canvas state from layer_review.js
 const [activeBoardId,setActiveBoardId]=useState<string>('');
 const [selectedLayer,setSelectedLayer]=useState<SelectedLayerInfo|null>(null);
 const [boardTransforms,setBoardTransforms]=useState<Record<string,any>>({});
 const [dirty,setDirty]=useState(false);
 const [savingTransforms,setSavingTransforms]=useState(false);
 const lastSavedTransforms=useRef<Record<string,string>>({});
 const autoSaveTimer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);

 // Modals
 const [createOpen,setCreateOpen]=useState(false);
 const [parentFolder,setParentFolder]=useState('');
 const [folderSlug,setFolderSlug]=useState('NewDesignProject');
 const [projectName,setProjectName]=useState('');
 const [templateId,setTemplateId]=useState<'blank'|'forma'|'motion'|'atelier'>('blank');
 const [preset,setPreset]=useState('mobile-portrait');
 const [customWidth,setCustomWidth]=useState(720);
 const [customHeight,setCustomHeight]=useState(1560);
 const [creating,setCreating]=useState(false);
 const createPending=useRef(false);
 const createFolderHintId=React.useId();
 const [createError,setCreateError]=useState('');

 const [screenModalOpen,setScreenModalOpen]=useState(false);
 const [screenId,setScreenId]=useState('');
 const [screenName,setScreenName]=useState('');
 const [screenGroup,setScreenGroup]=useState('核心页面');
 const [screenCaption,setScreenCaption]=useState('');
 const [savingScreen,setSavingScreen]=useState(false);
 const [screenError,setScreenError]=useState('');

 const [checkReport,setCheckReport]=useState<CheckReport|null>(null);
 const [checking,setChecking]=useState(false);

 const selectedProject=projects.find(p=>p.directory===selectedDir)||projects[0]||null;

 const loadProjects=useCallback(async(preferredDir?:string)=>{
  setLoading(true);setError('');
  try{
   const res=await api<{projects:DesignProjectSummary[],selected:DesignProjectSummary|null}>(
    'design/projects?'+new URLSearchParams({current_path:preferredDir??selectedDir??initialFolder}),
    undefined,undefined,{force:true}
   );
   setProjects(res.projects||[]);
   if(preferredDir&&res.projects.some(p=>p.directory===preferredDir)){
    setSelectedDir(preferredDir);
   }else if(!selectedDir||!res.projects.some(p=>p.directory===selectedDir)){
    setSelectedDir(res.selected?.directory||res.projects[0]?.directory||'');
   }
  }catch(e){
   setError((e as Error).message);
  }finally{
   setLoading(false);
  }
 },[selectedDir,initialFolder]);

 useEffect(()=>{
  if(active)void loadProjects();
 },[active,root,refresh,showHome]);

 // Open Create Modal when triggered from FolderView or Sidebar tree ("在此新建设计项目")
 useEffect(()=>{
  if(createInFolder!==undefined){
   setParentFolder(createInFolder);
   setFolderSlug('UI-Design');
   setProjectName('');
   setCreateError('');
   setTemplateId('blank');setCreateOpen(true);
   onClearCreateInFolder?.();
  }
 },[createInFolder,onClearCreateInFolder]);

 // Start HTML viewer session for the selected design project
 const projectTransformsRef=useRef<Record<string,Record<string,any>>>({});
 useEffect(()=>{
  if(!active||!selectedProject||selectedProject.managed||showHome)return;
  let alive=true,created:WebSession|null=null;
  setFrameBusy(true);setError('');setSession(null);
  setSelectedLayer(null);setActiveBoardId('');setDirty(false);
  projectTransformsRef.current={};
  void api<{all_boards:Record<string,Record<string,any>>}>(
   'design/projects/transforms?'+new URLSearchParams({directory:selectedProject.directory}),
   undefined,undefined,{force:true}
  ).then(res=>{
   if(!alive)return;
   projectTransformsRef.current=res.all_boards||{};
   for(const [bid,tmap] of Object.entries(projectTransformsRef.current)){
    lastSavedTransforms.current[selectedProject.directory+'::'+bid]=JSON.stringify(tmap||{});
   }
  }).catch(()=>{});
  api<WebSession>('html-sessions',{
   root,
   path:selectedProject.entry,
   ...(selectedProject.html_project_id?{project_id:selectedProject.html_project_id}:{}),
  }).then(result=>{
   created=result;
   if(!alive){
    if(result.id)void api('html-sessions/'+result.id,undefined,'DELETE').catch(()=>{});
    return;
   }
   currentSession.current=result;
   setSession(result);
  }).catch(e=>{
   if(alive){setError((e as Error).message);setFrameBusy(false);}
  });
  return()=>{
   alive=false;currentSession.current=null;
   if(created?.id)void api('html-sessions/'+created.id,undefined,'DELETE').catch(()=>{});
  };
 },[active,root,selectedProject?.directory,selectedProject?.entry,selectedProject?.html_project_id,revision,showHome]);

 const saveTransformsNow=useCallback(async(boardId:string,transforms:Record<string,any>,silent=false)=>{
  if(!selectedProject||!boardId)return;
  clearTimeout(autoSaveTimer.current);
  const serialized=JSON.stringify(transforms||{});
  setSavingTransforms(true);
  try{
   await api('design/projects/transforms',{
    directory:selectedProject.directory,
    board_id:boardId,
    transforms:transforms||{},
    merge:false,
   });
   lastSavedTransforms.current[selectedProject.directory+'::'+boardId]=serialized;
   projectTransformsRef.current[boardId]=transforms||{};
   setDirty(false);
   if(!silent)notify(t('已保存画板图层设计修改'));
  }catch(e){
   notify((e as Error).message);
  }finally{
   setSavingTransforms(false);
  }
 },[selectedProject,notify]);

 const sendLayerToAi=useCallback((boardId:string,layer:SelectedLayerInfo)=>{
  if(!selectedProject||!layer)return;
  const lines=[
   `[设计项目: ${selectedProject.name} (${selectedProject.directory})]`,
   `[画板: ${boardId} | 图层: ${layer.name} (${layer.id})]`,
   `- 类型: ${layer.type} | 坐标: (${layer.x}, ${layer.y}) | 尺寸: ${layer.width}×${layer.height} px`,
  ];
  if(layer.text)lines.push(`- 文本内容: ${layer.text}`);
  if(layer.assetId)lines.push(`- 关联素材 ID: ${layer.assetId}`);
  if(layer.sourceRef)lines.push(`- 源码来源: ${layer.sourceRef}`);
  if(layer.transform&&Object.keys(layer.transform).length){
   lines.push(`- 当前图层变换: ${JSON.stringify(layer.transform)}`);
  }
  addAiReference({
   root,
   kind:'design',label:selectedProject.name+' / '+layer.name,
   path:selectedProject.spec_path,
   text:lines.join('\n'),
  });
  notify(t('已将选中图层添加到 AI 对话'));
 },[root,selectedProject,notify]);

 // Listen for postMessage from VIEWER_JS inside the design iframe
 useEffect(()=>{
  const listener=(event:MessageEvent)=>{
   const s=currentSession.current;
   if(!s?.id||event.source!==frame.current?.contentWindow||event.origin!==s.origin||event.data?.session!==s.id)return;
   const data=event.data;
   if(data.type==='leafloom-web-ready')setFrameBusy(false);
   if(data.type==='leafloom-web-expired'){setFrameBusy(false);setError(t('网页会话已失效，请重新打开。'));}
   if(data.type==='leafloom-design-state'&&data.payload){
    const {action,boardId,selected,transforms}=data.payload;
    if(boardId){
     setActiveBoardId(boardId);
     setBoardTransforms(transforms||{});
     const key=(selectedProject?.directory||'')+'::'+boardId;
     const serialized=JSON.stringify(transforms||{});
     if(action==='ready'){
      const savedForBoard=projectTransformsRef.current[boardId];
      if(savedForBoard&&Object.keys(savedForBoard).length>0&&serialized==='{}'){
       frame.current?.contentWindow?.postMessage({
        session:s.id,
        command:'design-reload-transforms',
        boardId,
        transforms:savedForBoard,
       },s.origin);
      }else{
       lastSavedTransforms.current[key]=serialized;
      }
      setDirty(false);
     }else if(!(key in lastSavedTransforms.current)){
      lastSavedTransforms.current[key]=serialized;
      setDirty(false);
     }else if(lastSavedTransforms.current[key]!==serialized){
      setDirty(true);
      clearTimeout(autoSaveTimer.current);
      autoSaveTimer.current=setTimeout(()=>{
       void saveTransformsNow(boardId,transforms||{},true);
      },800);
     }
    }
    setSelectedLayer(selected||null);
   }
   if(data.type==='leafloom-design-save-transforms'&&data.payload){
    const {boardId,transforms}=data.payload;
    if(boardId){
     setActiveBoardId(boardId);
     setBoardTransforms(transforms||{});
     void saveTransformsNow(boardId,transforms||{},false);
    }
   }
   if(data.type==='leafloom-design-ai-reference'&&data.payload?.layer){
    sendLayerToAi(data.payload.boardId||activeBoardId,data.payload.layer);
   }
  };
  const escape=(event:KeyboardEvent)=>{if(event.key==='Escape')setFull(false);};
  window.addEventListener('message',listener);
  window.addEventListener('keydown',escape);
  return()=>{
   clearTimeout(autoSaveTimer.current);
   window.removeEventListener('message',listener);
   window.removeEventListener('keydown',escape);
  };
 },[selectedProject?.directory,activeBoardId,saveTransformsNow,sendLayerToAi]);

 // Listen for external SSE transform updates (e.g. MCP design_update_layers)
 useEffect(()=>{
  if(!active||!selectedProject)return;
  const changed=(event:Event)=>{
   const change=(event as CustomEvent<Change>).detail;
   if(change.design_transforms&&change.design_transforms.directory===selectedProject.directory){
    const {board_id,transforms}=change.design_transforms;
    const key=selectedProject.directory+'::'+board_id;
    const serialized=JSON.stringify(transforms||{});
    if(lastSavedTransforms.current[key]===serialized)return;
    lastSavedTransforms.current[key]=serialized;
    const s=currentSession.current;
    if(s?.id&&s.origin){
     frame.current?.contentWindow?.postMessage({
      session:s.id,
      command:'design-reload-transforms',
      boardId:board_id,
      transforms:transforms||{},
     },s.origin);
    }
   }
  };
  window.addEventListener('vault-data-changed',changed);
  return()=>window.removeEventListener('vault-data-changed',changed);
 },[active,selectedProject]);

 const sendFrameCommand=(cmd:string)=>{
  const s=currentSession.current;
  if(s?.id&&s.origin)frame.current?.contentWindow?.postMessage({session:s.id,command:cmd},s.origin);
 };

 const targetDirectory=[parentFolder.trim(),folderSlug.trim()].filter(Boolean).join('/');

 const validFolderName=!!folderSlug.trim()&&!/[\\/]/.test(folderSlug.trim())&&!['.','..'].includes(folderSlug.trim());

 // Only explicit activation of Create may write; directory browsing and implicit
 // form submission (including Enter in a text field) must remain read-only.
 const submitCreateProject=async(event:React.MouseEvent<HTMLButtonElement>)=>{
  if(createPending.current||!validFolderName||!event.currentTarget.form?.reportValidity())return;
  createPending.current=true;
  setCreating(true);setCreateError('');
  try{
   const res=await api<{project:DesignProjectSummary}>('design/projects',{
    root,managed:true,
    directory:targetDirectory,
    name:projectName.trim()||folderSlug.trim()||targetDirectory.split('/').pop(),
    ...(templateId!=='blank'?{template_id:templateId}:{preset,width:customWidth,height:customHeight}),
   });
   setCreateOpen(false);
   notify(t('已创建设计项目：')+res.project.name);
   await loadProjects(res.project.directory);
   setSelectedDir(res.project.directory);
   setShowHome(false);
   setRevision(n=>n+1);
  }catch(e){
   setCreateError((e as Error).message);
  }finally{
   createPending.current=false;
   setCreating(false);
  }
 };

 const submitUpsertScreen=async(event:React.FormEvent)=>{
  event.preventDefault();
  if(savingScreen||!selectedProject)return;
  if(!screenId.trim()&&!screenName.trim()){setScreenError(t('请输入画板名称或标识'));return;}
  setSavingScreen(true);setScreenError('');
  try{
   await api('design/projects/screens',{
    directory:selectedProject.directory,
    screen_id:screenId.trim()||screenName.trim(),
    name:screenName.trim()||screenId.trim(),
    group:screenGroup.trim()||'核心页面',
    caption:screenCaption.trim(),
    width:selectedProject.width,
    height:selectedProject.height,
   });
   setScreenModalOpen(false);
   setScreenId('');setScreenName('');setScreenCaption('');
   notify(t('已添加画板，正在刷新画板工作台'));
   await loadProjects(selectedProject.directory);
   setRevision(n=>n+1);
  }catch(e){
   setScreenError((e as Error).message);
  }finally{
   setSavingScreen(false);
  }
 };

 const runCheckProject=async()=>{
  if(!selectedProject||checking)return;
  setChecking(true);
  try{
   const res=await api<CheckReport>('design/projects/check',{directory:selectedProject.directory});
   setCheckReport(res);
  }catch(e){
   notify((e as Error).message);
  }finally{
   setChecking(false);
  }
 };

 const standalone=(()=>{
  if(!session?.id||!session.origin||!session.url)return '';
  const target=new URL(session.url);
  return session.origin+'/__leafloom__/viewer?'+new URLSearchParams({session:session.id,path:target.pathname+target.search+target.hash});
 })();

 return <section className={'design-studio'+(full?' design-studio-full':'')} hidden={!active} aria-label={t('设计工作台')}>
  {!showHome&&<div className="design-studio-toolbar">
   <div className="design-studio-left">
    <span className="design-badge"><Palette size={15}/>{t('设计工作台')}</span>
    <button onClick={()=>setShowHome(true)}><Folder size={15}/>{t('所有项目')}</button>
    {projects.length>0&&(
     <select
      className="design-project-select"
      aria-label={t('选择设计项目')}
      value={selectedProject?.directory||''}
      onChange={e=>setSelectedDir(e.target.value)}
     >
      {projects.map(p=>(
       <option key={p.directory} value={p.directory}>
        {p.name} ({p.directory||'/'})
       </option>
      ))}
     </select>
    )}
    <button type="button" className="primary" onClick={()=>{setParentFolder(initialFolder||'');setFolderSlug('NewDesignProject');setProjectName('');setCreateError('');setTemplateId('blank');setCreateOpen(true);}}>
     <Plus size={15}/>{t('新建设计项目')}
    </button>
    {selectedProject&&!selectedProject.managed&&(
     <button type="button" onClick={()=>setShowHome(true)}>
      <Layers size={15}/>{t('转换为可视化副本')}
     </button>
    )}
   </div>

   {selectedProject&&!selectedProject.managed&&(
    <div className="design-studio-actions">
     <button
      type="button"
      className={dirty?'primary':''}
      disabled={!activeBoardId||savingTransforms}
      onClick={()=>void saveTransformsNow(activeBoardId,boardTransforms,false)}
      title={t('将当前画板的图层位置、缩放、旋转和文案修改保存到 Design/layer-transforms.json')}
     >
      <Save size={15}/>
      {savingTransforms?t('保存中…'):dirty?t('保存修改 *'):t('已同步')}
     </button>
     {selectedLayer&&(
      <button
       type="button"
       onClick={()=>sendLayerToAi(activeBoardId,selectedLayer)}
       title={t('将当前选中的画板图层作为上下文引用添加到 AI 对话')}
      >
       <MessageSquare size={15}/>{t('引用图层：')}{selectedLayer.name.slice(0,10)}
      </button>
     )}
     <button type="button" disabled={checking} onClick={()=>void runCheckProject()}>
      <CheckCircle2 size={15}/>{checking?t('检查中…'):t('契约检查')}
     </button>
     <button type="button" onClick={()=>onOpenFolder(selectedProject.directory)} title={t('在知识库目录中浏览该项目的所有 Markdown 与设计文件')}>
      <FolderOpen size={15}/>{t('打开目录')}
     </button>
     <button type="button" onClick={()=>{if(error)setRevision(n=>n+1);else sendFrameCommand('reload');}} title={t('刷新设计画板')}>
      <RefreshCw size={15}/>
     </button>
     {!window.leafloomDesktop&&standalone&&(
      <a className="button" href={standalone} target="_blank" rel="noopener noreferrer" title={t('在浏览器独立标签页中打开')}>
       <ExternalLink size={15}/>
      </a>
     )}
     <button type="button" onClick={()=>setFull(x=>!x)} title={full?t('退出全屏'):t('全屏设计')}>
      {full?<Minimize size={15}/>:<Maximize size={15}/>}
     </button>
    </div>
   )}
  </div>}

  {showHome&&<DesignProjects root={root} projects={projects} onOpen={directory=>{setSelectedDir(directory);setShowHome(false);}} onCreate={()=>{setParentFolder(initialFolder||'');setFolderSlug('NewDesignProject');setProjectName('');setCreateError('');setTemplateId('blank');setCreateOpen(true);}} reload={()=>loadProjects()} notify={notify}/>}
  {!showHome&&selectedProject?.managed&&<DesignWorkbench key={root+'::'+selectedProject.directory} root={root} directory={selectedProject.directory} displayName={selectedProject.name} notify={notify} onBack={()=>setShowHome(true)} onOpenNote={onOpenNote}/>}

  {!showHome&&!selectedProject?.managed&&(frameBusy||error)&&(
   <div className={'html-preview-message'+(error?' error':'')} role={error?'alert':'status'}>
    {error?<Diagnostic message={error}/>:t('正在加载设计工作台画板…')}
    {error&&<button onClick={()=>setRevision(n=>n+1)}>{t('重试')}</button>}
   </div>
  )}

  {!showHome&&!loading&&projects.length===0&&!error&&(
   <div className="empty-state">
    <Palette size={38}/>
    <h2>{t('在知识库中开启类 Figma 网页与 UI 设计')}</h2>
    <p>{t('选择知识库中的任意目录创建设计项目。每个项目包含多画板、可拖拽/缩放/旋转的图层树、组件契约与素材清单，并支持 AI/MCP 直接协同编辑。')}</p>
    <button className="primary" onClick={()=>{setParentFolder(initialFolder||'');setTemplateId('blank');setCreateOpen(true);}}>
     <Plus size={16}/>{t('在知识库中新建设计项目')}
    </button>
   </div>
  )}

  {!showHome&&!selectedProject?.managed&&selectedProject&&session&&(
   <iframe
    key={session.url}
    ref={frame}
    className="design-studio-frame"
    title={t('设计工作台 · ')+selectedProject.name}
    src={session.url}
    allow="fullscreen; clipboard-read; clipboard-write"
    allowFullScreen
   />
  )}

  {createOpen&&(
   <Modal title={t('在知识库中新建设计项目')} wide className="design-create-modal" onClose={()=>{if(!creating)setCreateOpen(false);}}>
    <form onSubmit={event=>event.preventDefault()} aria-busy={creating}>
     <fieldset className="pad design-create-form" disabled={creating}>
      <p className="hint">{t('design.template.intro')}</p>
      <fieldset className="design-template-picker" disabled={creating}>
       <legend>{t('design.template.choose')}</legend>
       <div className="design-template-options">
        <label data-template-id="blank" className={'design-template-card'+(templateId==='blank'?' selected':'')}>
         <input type="radio" name="design-template" value="blank" checked={templateId==='blank'} onChange={()=>setTemplateId('blank')}/>
         <span className="design-template-art design-template-blank" aria-hidden="true"><span><Plus size={28}/></span></span>
         <span className="design-template-copy"><strong>{t('design.template.blank')}</strong><span>{t('design.template.blankDescription')}</span></span>
        </label>
        <label data-template-id="forma" className={'design-template-card'+(templateId==='forma'?' selected':'')}>
         <input type="radio" name="design-template" value="forma" checked={templateId==='forma'} onChange={()=>setTemplateId('forma')}/>
         <span className="design-template-art design-template-forma"><img src="/api/design/templates/forma/preview" alt={t('design.template.formaPreview')}/></span>
         <span className="design-template-copy"><strong>FORMA <small>{t('design.template.builtIn')}</small></strong><span>{t('design.template.formaDescription')}</span><span className="design-template-meta"><Layers size={13} aria-hidden="true"/>{t('design.template.formaLayers')}</span></span>
        </label>
        <label data-template-id="atelier" className={'design-template-card'+(templateId==='atelier'?' selected':'')}>
         <input type="radio" name="design-template" value="atelier" checked={templateId==='atelier'} onChange={()=>setTemplateId('atelier')}/>
         <span className="design-template-art design-template-atelier"><img src="/api/design/templates/atelier/preview" alt={t('design.template.atelierPreview')}/></span>
         <span className="design-template-copy"><strong>ATELIER <small>{t('design.template.builtIn')}</small></strong><span>{t('design.template.atelierDescription')}</span><span className="design-template-meta"><Layers size={13} aria-hidden="true"/>{t('design.template.atelierLayers')}</span></span>
        </label>
        <label data-template-id="motion" className={'design-template-card'+(templateId==='motion'?' selected':'')}>
         <input type="radio" name="design-template" value="motion" checked={templateId==='motion'} onChange={()=>setTemplateId('motion')}/>
         <span className="design-template-art design-template-motion" aria-hidden="true"><span className="design-motion-orbit"/><span className="design-motion-word">Motion<br/><i>Playground.</i></span><span className="design-motion-label">01 / PLAY &amp; LEARN</span></span>
         <span className="design-template-copy"><strong>Motion Playground <small>{t('design.template.builtIn')}</small></strong><span>{t('design.template.motionDescription')}</span><span className="design-template-meta"><Play size={13} aria-hidden="true"/>{t('design.template.motionModes')}</span></span>
        </label>
       </div>
      </fieldset>
      <div className="design-folder-picker">
       <div className="design-folder-picker-header">
        <strong>{t('design.create.parent')}</strong>
        <button type="button" className={'design-root-btn'+(parentFolder===''?' selected':'')} onClick={()=>setParentFolder('')}>
         <Folder size={14}/>{t('知识库根目录 /')}
        </button>
       </div>
       <div className="design-folder-tree">
        <DirectoryTree
         path=""
         dirsOnly={true}
         selected={parentFolder}
         refresh={refresh}
         onOpen={()=>{}}
         onFolder={folder=>setParentFolder(folder)}
         manage={()=>{}}
        />
       </div>
      </div>

      <div className="design-target-preview" aria-live="polite">
       <span>{t('design.create.selectedParent')}</span>
       <code>{parentFolder?'/'+parentFolder:'/'}</code>
      </div>
      <p className="hint">{t('design.create.browseHint')}</p>

      <div className="design-form-grid">
       <label className="setting-field">
        {t('项目文件夹名称（英文或中文目录名）')}
        <input
         required
         value={folderSlug}
         aria-invalid={!validFolderName}
         aria-describedby={!validFolderName?createFolderHintId:undefined}
         placeholder="例如：萌宠安家 或 cozy-ui"
         onChange={e=>setFolderSlug(e.target.value)}
        />
       </label>
       <label className="setting-field">
        {t('项目显示名称')}
        <input
         value={projectName}
         placeholder={folderSlug||t('例如：萌宠安家 UI 设计')}
         onChange={e=>setProjectName(e.target.value)}
        />
       </label>
      </div>

      <div className="design-target-preview" aria-live="polite">
       <span>{t('完整生成路径：')}</span>
       <code>{'/'+targetDirectory}</code>
      </div>

      {templateId==='blank'&&<div className="design-form-grid">
       <label className="setting-field">
        {t('画板尺寸预设')}
        <select
         value={preset}
         onChange={e=>{
          const next=e.target.value;
          setPreset(next);
          const found=PRESET_OPTIONS.find(o=>o.value===next);
          if(found){setCustomWidth(found.width);setCustomHeight(found.height);}
         }}
        >
         {PRESET_OPTIONS.map(o=><option key={o.value} value={o.value}>{t(o.label)}</option>)}
        </select>
       </label>
       <div className="design-dimensions-fields">
        <label className="setting-field">
         {t('画板宽度 (px)')}
         <input type="number" min={120} max={7680} value={customWidth} onChange={e=>setCustomWidth(Number(e.target.value)||720)}/>
        </label>
        <label className="setting-field">
         {t('画板高度 (px)')}
         <input type="number" min={120} max={7680} value={customHeight} onChange={e=>setCustomHeight(Number(e.target.value)||1560)}/>
        </label>
       </div>
      </div>}

      {!validFolderName&&<p id={createFolderHintId} className="error">{t('design.create.folderNameHint')}</p>}
      {createError&&<p className="error" role="alert"><Diagnostic message={createError}/></p>}
     </fieldset>
     <footer className="modal-footer">
      <button type="button" disabled={creating} onClick={()=>setCreateOpen(false)}>{t('取消')}</button>
      <button type="button" className="primary" disabled={creating||!validFolderName} onClick={submitCreateProject}>{creating?t('正在创建…'):t('创建并打开设计工作台')}</button>
     </footer>
    </form>
   </Modal>
  )}

  {screenModalOpen&&selectedProject&&(
   <Modal title={t('新增或更新画板')} onClose={()=>{if(!savingScreen)setScreenModalOpen(false);}}>
    <form onSubmit={submitUpsertScreen}>
     <div className="pad">
      <p className="hint">{t('所属设计项目：')}{selectedProject.name} ({selectedProject.directory})</p>
      <label className="setting-field">
       {t('画板中文名称')}
       <input autoFocus required value={screenName} placeholder="例如：背包合成页" onChange={e=>setScreenName(e.target.value)}/>
      </label>
      <label className="setting-field">
       {t('画板标识 ID（英文，留空自动生成）')}
       <input value={screenId} placeholder="例如：backpack-merge" onChange={e=>setScreenId(e.target.value)}/>
      </label>
      <label className="setting-field">
       {t('所属分组')}
       <input value={screenGroup} placeholder="核心流程 / 系统弹层" onChange={e=>setScreenGroup(e.target.value)}/>
      </label>
      <label className="setting-field">
       {t('画板设计说明')}
       <input value={screenCaption} placeholder="描述该画板的核心组件与交互目标" onChange={e=>setScreenCaption(e.target.value)}/>
      </label>
      {screenError&&<p className="error" role="alert"><Diagnostic message={screenError}/></p>}
     </div>
     <footer className="modal-footer">
      <button type="button" disabled={savingScreen} onClick={()=>setScreenModalOpen(false)}>{t('取消')}</button>
      <button className="primary" disabled={savingScreen}>{savingScreen?t('处理中…'):t('保存画板')}</button>
     </footer>
    </form>
   </Modal>
  )}

  {checkReport&&(
   <Modal title={t('设计项目契约检查结果')} onClose={()=>setCheckReport(null)}>
    <div className="pad">
     <p className={checkReport.ok?'status-ok':'error'}>
      <strong>{checkReport.ok?t('✓ 契约检查通过'):t('✕ 契约检查存在问题')}</strong>
     </p>
     {checkReport.summary&&(
      <dl className="design-check-summary">
       {Object.entries(checkReport.summary).map(([k,v])=>(
        <React.Fragment key={k}>
         <dt>{k}</dt>
         <dd>{typeof v==='object'?JSON.stringify(v):String(v)}</dd>
        </React.Fragment>
       ))}
      </dl>
     )}
     {checkReport.errors.length>0&&(
      <div className="error">
       <strong>{t('错误项：')}</strong>
       <ul>{checkReport.errors.map((err,i)=><li key={i}>{err}</li>)}</ul>
      </div>
     )}
     {checkReport.warnings.length>0&&(
      <div className="hint">
       <strong>{t('提示项：')}</strong>
       <ul>{checkReport.warnings.map((w,i)=><li key={i}>{w}</li>)}</ul>
      </div>
     )}
     {selectedProject&&(
      <p className="hint">
       <button type="button" className="link-button" onClick={()=>{setCheckReport(null);onOpenNote(selectedProject.spec_path);}}>
        {t('在编辑器中打开 Design/project-spec.json')}
       </button>
      </p>
     )}
    </div>
    <footer className="modal-footer">
     <button className="primary" onClick={()=>setCheckReport(null)}>{t('关闭')}</button>
    </footer>
   </Modal>
  )}
 </section>;
}
