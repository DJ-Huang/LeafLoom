import {Diagnostic} from './i18n';
import {t,useLocale} from './i18n';
import './settings.css';
import {chooseDirectory,registerQuitBlocker} from './desktop';
import {DesktopPreferences} from './desktop-ui';
import {LocalePicker} from './i18n';
import React,{useCallback,useEffect,useRef,useState} from 'react';
import {BookOpen,Settings,Files,FileText,Search,Sparkles,History,Trash2,ChevronLeft,X,ArrowUpRight} from 'lucide-react';
import {api,Config} from './api';
import {DirectoryTree,selectedPath} from './tree';
import {Action,Modal} from './ui';
import {useStatus} from './hooks';
import {FileTools,RecordsPage,SkillInstaller} from './settings-content';
import {RunAction,SettingGroup,SettingRow,StatusNotice} from './settings-ui';
import {copyConfig,configChanged,searchSettings,settingsSections,SettingsLocation,SettingsResult} from './settings-model';

const icons={general:Settings,files:Files,templates:FileText,index:Search,ai:Sparkles,history:History,trash:Trash2};
const within=(path:string,parent:string)=>!parent||path===parent||path.startsWith(parent+'/');

type SettingsProps={config:Config,location:SettingsLocation,folder:string,onSaved:(config:Config)=>void,onClose:()=>void,onOpen:(result:SettingsResult)=>void,onChanged:()=>void,notify:(message:string)=>void};
export function ConnectedSettings({config,location,folder,onSaved,onClose,onOpen,onChanged,notify}:SettingsProps){
 useLocale();
 const status=useStatus(),[draft,setDraft]=useState(()=>copyConfig(config)),[baseline,setBaseline]=useState(config);
 const [section,setSection]=useState(location.section),[query,setQuery]=useState(''),[mobileContent,setMobileContent]=useState(false),[targetId,setTargetId]=useState(location.targetId),[recordPath,setRecordPath]=useState(location.path);
 const [working,setWorking]=useState(''),[error,setError]=useState(''),[message,setMessage]=useState(''),[exit,setExit]=useState<{result?:SettingsResult}>(),[externalChange,setExternalChange]=useState(false);
 const scope=useRef({root:config.root,alive:true,serial:0}),ownSave=useRef(false),previousRoot=useRef(config.root),currentConfig=useRef(config),content=useRef<HTMLDivElement>(null);currentConfig.current=config;
 if(scope.current.root!==config.root){scope.current.root=config.root;scope.current.serial++;}
 useEffect(()=>{scope.current.alive=true;return()=>{scope.current.alive=false;scope.current.serial++;};},[]);
 const dirty=configChanged(draft,baseline),rootChanged=draft.root!==config.root,busy=!!working;
 useEffect(()=>registerQuitBlocker(()=>dirty||busy),[dirty,busy]);
 useEffect(()=>{
  if(config.root!==baseline.root){setDraft(copyConfig(config));setBaseline(config);setSection('general');setExit(undefined);setError('');setWorking('');setExternalChange(false);setTargetId(undefined);return;}
  if(config.revision!==baseline.revision&&!ownSave.current){
   if(configChanged(draft,baseline))setExternalChange(true);else{setDraft(copyConfig(config));setBaseline(config);}
  }
 },[config,baseline,draft]);
 useEffect(()=>{setRecordPath(location.path);setSection(location.section);setTargetId(location.targetId);setQuery('');setMobileContent(!!location.targetId||!!location.path||location.section!=='general');},[location]);
 useEffect(()=>{if(previousRoot.current!==config.root){previousRoot.current=config.root;setRecordPath(undefined);setSection('general');setTargetId(undefined);setQuery('');setExit(undefined);}},[config.root]);
 useEffect(()=>{if(!dirty)return;const leave=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue='';};window.addEventListener('beforeunload',leave);return()=>window.removeEventListener('beforeunload',leave);},[dirty]);
 useEffect(()=>{content.current?.scrollTo(0,0);if(!targetId)return;const timer=setTimeout(()=>{const element=content.current?.querySelector<HTMLElement>('#setting-'+targetId);element?.scrollIntoView({block:'center'});element?.focus({preventScroll:true});},80);return()=>clearTimeout(timer);},[section,targetId,query]);
 const run:RunAction=useCallback(async(label,work,done)=>{
  const snapshot=scope.current,root=snapshot.root,serial=++snapshot.serial;
  const valid=()=>scope.current.alive&&scope.current.root===root&&scope.current.serial===serial;
  setWorking(label);setError('');setMessage('');
  try{const result=await work(valid);if(valid())done?.(result);}
  catch(error){if(valid())setError((error as Error).message);}
  finally{if(valid())setWorking('');}
 },[]);
 const save=async()=>{
  const origin=config.root,revision=config.revision,serial=++scope.current.serial;
  const valid=()=>scope.current.alive&&scope.current.serial===serial&&scope.current.root===origin;
  setWorking(t("保存设置"));setError('');setMessage('');ownSave.current=true;
  try{
   // Re-read before applying a whole configuration draft so an external change is not silently overwritten.
   const session=await api<{config:Config}>('session',undefined,undefined,{force:true});
   if(!valid())return false;
   if(session.config.root!==origin||session.config.revision!==revision){setExternalChange(true);throw new Error(t("设置已在其他页面更新，请重新载入后再修改。"));}
   const next=await api<Config>('config',{...draft,...Object.fromEntries((['rules_roots','wiki_roots','estimation_roots'] as const).map(key=>[key,draft[key].map(path=>path.trim()).filter(Boolean)]))});
   if(!valid())return false;
   setDraft(copyConfig(next));setBaseline(next);setExternalChange(false);onSaved(next);setMessage(t("设置已保存"));return next;
  }catch(error){if(valid())setError((error as Error).message);return false;}
  finally{ownSave.current=false;if(scope.current.alive&&scope.current.serial===serial)setWorking('');}
 };
 const discard=()=>{setDraft(copyConfig(currentConfig.current));setBaseline(currentConfig.current);setExternalChange(false);setError('');setMessage('');};
 const completeExit=(result?:SettingsResult)=>{onClose();if(result)onOpen(result);};
 const requestExit=(result?:SettingsResult)=>{if(busy)return;if(dirty){setQuery('');setMobileContent(true);setExit({result});return;}completeExit(result);};
 const sectionInfo=settingsSections.find(item=>item.id===section)!,results=searchSettings(query);
 const select=(next:SettingsLocation)=>{setSection(next.section);setQuery('');setTargetId(next.targetId);setMobileContent(true);setError('');setMessage('');};
 const field=(key:'homepage'|'templates'|'daily_folder',label:string)=><input aria-label={label} value={draft[key]} onChange={event=>setDraft(value=>({...value,[key]:event.target.value}))}/>;
 const scopeChange=(path:string,checked:boolean)=>setDraft(value=>({...value,include_roots:[...value.include_roots.filter(item=>!within(item,path)),...(checked?[path]:[])],exclude_roots:[...value.exclude_roots.filter(item=>!within(item,path)),...(!checked?[path]:[])]}));
 const blocked=rootChanged&&['files','index','history','trash'].includes(section);
 return <Modal title={t("设置")} onClose={()=>requestExit()} className={'settings-modal'+(mobileContent?' showing-content':'')} hideHeader>
  <div className="settings-shell">
   <aside className="settings-nav" aria-label={t("设置分类")}><div className="settings-nav-heading"><div className="brand-mark small"><BookOpen size={17}/></div><strong>{t("知识库设置")}</strong><Action title={t("关闭设置")} onClick={()=>requestExit()}><X size={17}/></Action></div>
    <div className="settings-search"><Search size={15}/><input aria-label={t("搜索设置")} placeholder={t("搜索设置…")} value={query} disabled={busy} onChange={event=>{setQuery(event.target.value);setMobileContent(false);}}/>{query&&<button className="icon-button" aria-label={t("清除设置搜索")} onClick={()=>setQuery('')}><X size={13}/></button>}</div>
    <nav><p className="settings-nav-label">{t("知识库")}</p>{settingsSections.map((item,index)=>{const Icon=icons[item.id];return <React.Fragment key={item.id}>{index===5&&<p className="settings-nav-label">{t("浏览与恢复")}</p>}<button disabled={busy} className={section===item.id&&!query?'active':''} aria-current={section===item.id&&!query?'page':undefined} onClick={()=>select({section:item.id})}><Icon size={16}/>{item.title}</button></React.Fragment>;})}</nav>
    <div className="settings-nav-foot"><span className="status-dot"/>{t("本地知识库")}<span>{t("文件始终保留在本机")}</span></div>
   </aside>
   <div className={'settings-main'+(query?' has-search-results':'')}>
    <header className="settings-page-heading"><button className="icon-button settings-back" aria-label={t("返回设置分类")} onClick={()=>{setMobileContent(false);setQuery('');}}><ChevronLeft size={18}/></button><div><h2>{query?t("搜索设置"):sectionInfo.title}</h2><p>{query?t("查找功能，直接前往对应位置。"):sectionInfo.description}</p></div><Action title={t("关闭设置")} onClick={()=>requestExit()}><X size={18}/></Action></header>
    <div className={'settings-scroll'+(targetId?' setting-focus-'+targetId:'')} ref={content}>
     {externalChange&&<StatusNotice kind="error">{t("设置已在其他页面更新。")}<button disabled={busy} onClick={async()=>{await run(t("重新载入设置"),()=>api<{config:Config}>('session',undefined,undefined,{force:true}),session=>{setDraft(copyConfig(session.config));setBaseline(session.config);setExternalChange(false);onSaved(session.config);});}}>{t("放弃草稿并重新载入")}</button></StatusNotice>}
     {error&&<StatusNotice kind="error">{<Diagnostic message={error}/>}</StatusNotice>}{message&&<StatusNotice kind="success">{message}</StatusNotice>}
     {query?<div className="settings-search-results">{results.length?results.map(result=><button key={result.id} onClick={()=>select({section:result.section,targetId:result.id})}><div><strong>{result.title}</strong><span>{settingsSections.find(item=>item.id===result.section)!.title} · {result.description}</span></div><ArrowUpRight size={16}/></button>):<div className="setting-empty">{t("没有匹配的设置，试试“上传”“模板”或“索引”。")}</div>}</div>:<fieldset className="settings-fields" disabled={busy||externalChange}>
     {section==='general'&&<SettingGroup title={t("界面语言")}><LocalePicker/></SettingGroup>}
     {blocked?<StatusNotice>{t("关联目录尚未保存。请先保存设置或取消更改，再操作此知识库。")}</StatusNotice>:<>
      {section==='general'&&<><DesktopPreferences/><SettingGroup id="root" title={t("关联目录")}><SettingRow label={t("知识库目录")} description={t("直接使用本机文件；网页可以浏览关联目录内的全部内容。")} stacked><div className="input-row"><input aria-label={t("关联目录")} value={draft.root||''} onChange={event=>setDraft(value=>({...value,root:event.target.value}))}/><button onClick={()=>void run(t("选择目录"),()=>chooseDirectory(),result=>{if(result.path)setDraft(value=>({...value,root:result.path!}));})}>{t("选择目录")}</button></div></SettingRow>{rootChanged&&<StatusNotice>{t("保存后将切换知识库，并重新加载文件与检索范围。")}</StatusNotice>}</SettingGroup><SettingGroup id="homepage" title={t("开始页面")}><SettingRow label={t("知识库首页")} description={t("首页快捷入口指向的文件，相对于关联目录。")}>{field('homepage',t("知识库首页"))}</SettingRow></SettingGroup><div className="settings-local-note"><BookOpen size={18}/><p>{t("你的文件，你的知识。")}<br/><span>{t("笔记、附件与历史记录继续保存在本机。")}</span></p></div></>}
      {section==='files'&&<FileTools key={config.root} config={config} folder={folder} run={run} onOpen={result=>requestExit(result)} onChanged={onChanged}/>}
      {section==='templates'&&<><SettingGroup id="templates" title={t("模板与日记")}><SettingRow label={t("模板目录")} description={t("用于从模板新建笔记。")}>{field('templates',t("模板目录"))}</SettingRow><SettingRow label={t("日记目录")} description={t("今日笔记的默认保存位置。")}>{field('daily_folder',t("日记目录"))}</SettingRow></SettingGroup><SettingGroup id="write-targets" title={t("默认写入位置")} description={t("所有路径相对于知识库根目录。")}>{Object.entries(draft.write_targets).map(([key,value])=><SettingRow key={key} label={({notes:t("知识正文"),rules:t("规则"),navigation:t("主题导航"),estimation:t("工时资料")} as Record<string,string>)[key]||key}><input aria-label={t("写入位置 ")+key} value={value} onChange={event=>setDraft(draft=>({...draft,write_targets:{...draft.write_targets,[key]:event.target.value}}))}/></SettingRow>)}</SettingGroup></>}
      {section==='index'&&<><SettingGroup id="scope" title={t("进入知识检索的目录")} description={t("勾选目录及其内容，子目录可以单独取消。网页文件浏览不受影响。")}><div className="scope-tree"><label><input type="checkbox" checked={selectedPath('',draft.include_roots,draft.exclude_roots)} onChange={event=>scopeChange('',event.target.checked)}/> {" "}{t("整个关联目录")}</label><DirectoryTree key={config.root} dirsOnly onScope={scopeChange} include={draft.include_roots} exclude={draft.exclude_roots} onOpen={()=>{}} onFolder={()=>{}} selected="" refresh={0} manage={()=>{}}/></div><p className="setting-detail">{draft.include_roots.length?t("已选：")+draft.include_roots.map(path=>path||t("整个目录")).join('、'):t("未选择目录，知识检索不包含任何资料。")}</p>{!!draft.exclude_roots.length&&<p className="setting-detail">{t("排除：")}{draft.exclude_roots.join('、')} <button className="text-link" onClick={()=>setDraft(value=>({...value,exclude_roots:[]}))}>{t("清除排除项")}</button></p>}</SettingGroup><SettingGroup id="special-folders" title={t("专用目录")}>{(['rules_roots','wiki_roots','estimation_roots'] as const).map((key,index)=><SettingRow key={key} label={[t("规则目录"),t("Wiki 导航目录"),t("工时资料目录")][index]} description={t("每行填写一个相对路径。")}><textarea aria-label={[t("规则目录"),t("Wiki 导航目录"),t("工时资料目录")][index]} rows={2} value={draft[key].join('\n')} onChange={event=>setDraft(value=>({...value,[key]:event.target.value.split('\n')}))}/></SettingRow>)}</SettingGroup><SettingGroup id="model" title={t("本地检索模型")}><SettingRow label="BGE-M3" description={status?.model?.loaded?t("已加载"):status?.model?.prepared?t("已准备"):t("待准备")}><button disabled={!!status?.model?.prepared} onClick={()=>void run(t("准备本地模型"),()=>api('model-prepare',{}),()=>{setMessage(t("已开始准备本地模型"));notify(t("已开始准备本地模型"));})}>{status?.model?.prepared?t("模型已准备"):t("准备模型")}</button></SettingRow></SettingGroup><SettingGroup id="sync" title={t("同步与索引")}><SettingRow label={t(status?.sync?.state||'正在读取同步状态')} description={t("{p0} 篇检索资料 · {p1} 个文件",{p0:status?.num_files||0,p1:status?.catalog_files||0})}><button onClick={()=>void run(t("重新同步索引"),()=>api('reindex',{}),()=>setMessage(t("已安排更新索引")))}>{t("重新同步索引")}</button></SettingRow>{status?.sync?.total>0&&<div className="sync-progress"><progress aria-label={t("索引同步进度")} max={status.sync.total} value={Math.min(status.sync.completed||0,status.sync.total)}/><span>{Math.min(status.sync.completed||0,status.sync.total)} / {status.sync.total}</span></div>}{status?.last_error&&<StatusNotice kind="error">{<Diagnostic message={status.last_error}/>}</StatusNotice>}{status?.watch?.error&&<StatusNotice>{t("文件监听暂不可用，每 10 秒检查文件变化。")}</StatusNotice>}</SettingGroup></>}
      {section==='ai'&&<SkillInstaller run={run}/>}
      {section==='history'&&<RecordsPage key={config.root+'history'+recordPath} root={config.root!} path={recordPath} run={run} onChanged={onChanged}/>}
      {section==='trash'&&<RecordsPage key={config.root+'trash'} root={config.root!} trash run={run} onChanged={onChanged}/>}
     </>}
     </fieldset>}
    </div>
    <footer className="settings-footer">{exit?<div className="settings-exit" role="alert"><strong>{t("有尚未保存的设置")}</strong><p>{t("保存后离开，或放弃此次更改。")}</p><div><button disabled={busy} onClick={()=>setExit(undefined)}>{t("继续编辑")}</button><button disabled={busy} onClick={()=>{discard();completeExit(exit.result);}}>{t("放弃更改")}</button><button className="primary" disabled={busy||externalChange} onClick={async()=>{const result=exit.result,origin=config.root,next=await save();if(next){setExit(undefined);if(result&&next.root!==origin){setMessage(t("已切换知识库，请在新目录中重新选择文件。"));return;}completeExit(result);}}}>{t("保存并离开")}</button></div></div>:<><span role="status">{working?working+'…':dirty?t("有未保存的更改"):t("所有设置已保存")}</span><button disabled={!dirty||busy} onClick={discard}>{t("取消更改")}</button><button className="primary" disabled={!dirty||busy||externalChange} onClick={()=>void save()}>{t("保存设置")}</button></>}</footer>
   </div>
  </div>
 </Modal>;
}
export function Association({config,suggestion,onSaved,notify}:{config:Config,suggestion:string,onSaved:(c:Config)=>void,notify:(s:string)=>void}){
 useLocale();
 const [path,setPath]=useState(suggestion);const [busy,setBusy]=useState(false);
 return <div className="onboarding"><div className="onboarding-card"><div className="brand-mark"><BookOpen size={32}/></div><p className="eyebrow">{t("你的文件，你的知识")}</p><h1>{t("从一个本地目录开始")}</h1><p>{t("浏览笔记、编辑文档、连接知识。")}<br/>{t("所有内容继续保存在原来的文件里。")}</p><label className="field-label">{t("知识库目录")}</label><div className="input-row"><input aria-label={t("知识库目录")} value={path} onChange={e=>setPath(e.target.value)}/><button onClick={async()=>{try{const d=await chooseDirectory();if(d.path)setPath(d.path);}catch(e){notify(String(e));}}}>{t("选择目录")}</button></div><button className="primary full" disabled={busy||!path} onClick={async()=>{setBusy(true);try{onSaved(await api('config',{...config,root:path}));}catch(e){notify(String(e));}finally{setBusy(false);}}}>{busy?t("正在关联…"):t("关联并打开")}</button><p className="hint">{t("之后可以在设置中选择进入知识检索的目录。")}</p></div></div>;
}
