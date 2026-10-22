import {Diagnostic} from './i18n';
import {t,useLocale} from './i18n';
import {getLocale} from './i18n';
import React,{useEffect,useRef,useState} from 'react';
import {FilePlus,FolderPlus,Upload,FileText,Folder,ArrowUpRight,Trash2,History} from 'lucide-react';
import {api,csrf,Config} from './api';
import {FormDialog} from './ui';
import {VirtualList} from './virtual';
import {SettingsResult,joinTarget} from './settings-model';
import {RunAction,SettingGroup,SettingRow,StatusNotice} from './settings-ui';

export function SkillInstaller({run}:{run:RunAction}){
 useLocale();
 const [skill,setSkill]=useState<{path:string,installed:boolean,up_to_date:boolean}>(),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 useEffect(()=>{const controller=new AbortController();setError('');api<typeof skill>('skills/wiki-search',undefined,undefined,{force:true,signal:controller.signal}).then(setSkill).catch(e=>{if(!controller.signal.aborted)setError(e.message);});return()=>controller.abort();},[retry]);
 return <SettingGroup id="skill" title={t("知识库查询技能")} description={t("让 AI 优先查询你的知识库，返回简短结论与原文链接。")}><SettingRow label="wiki-search" description={t("按知识检索、主题导航与文件检索补齐依据。")}><button disabled={!skill||skill.up_to_date} onClick={()=>void run(t("安装查询技能"),()=>api('skills/wiki-search/install',{}),setSkill)}>{!skill?t("检查安装状态…"):skill.up_to_date?t("已安装最新版本"):skill.installed?t("更新技能"):t("安装技能")}</button></SettingRow>{skill&&<p className="setting-detail">{t("安装位置：")}<code>{skill.path}</code></p>}{error&&<StatusNotice kind="error">{<Diagnostic message={error}/>} <button onClick={()=>setRetry(value=>value+1)}>{t("重试")}</button></StatusNotice>}{skill?.up_to_date&&<StatusNotice kind="success">{t("查询技能已就绪。MCP 连接沿用现有配置。")}</StatusNotice>}</SettingGroup>;
}

type FileResult=SettingsResult&{error?:string,pending?:boolean,remote_saved?:boolean,job_id?:string,state?:string};
const remotePendingStates=new Set(['queued','waiting_for_connection','waiting_for_auth','waiting_for_authorization','running','uploading','verifying']);
export function FileTools({config,folder,run,onOpen,onChanged}:{config:Config,folder:string,run:RunAction,onOpen:(result:SettingsResult)=>void,onChanged:()=>void}){
 useLocale();
 const [target,setTarget]=useState(folder),[name,setName]=useState(t("未命名.md")),[directory,setDirectory]=useState(false),[templateName,setTemplateName]=useState(t("未命名.md")),[template,setTemplate]=useState('');
 const [templates,setTemplates]=useState<{path:string,title:string}[]>(),[templateError,setTemplateError]=useState(''),[retry,setRetry]=useState(0),[results,setResults]=useState<FileResult[]>([]),[uploadProgress,setUploadProgress]=useState('');
 const input=useRef<HTMLInputElement>(null),resultArea=useRef<HTMLDivElement>(null);
 const pendingJobs=[...new Set(results.filter(result=>result.job_id&&!result.error&&result.remote_saved!==true).map(result=>result.job_id!))].join('\n');
 useEffect(()=>{if(results.length)resultArea.current?.scrollIntoView({block:'nearest'});},[results.length]);
 useEffect(()=>{
  if(!pendingJobs||!config.root)return;
  const controller=new AbortController(),root=config.root,jobs=pendingJobs.split('\n');let polling=false;
  const poll=async()=>{
   if(polling||controller.signal.aborted)return;polling=true;
   try{await Promise.allSettled(jobs.map(async jobId=>{
    const job=await api<{state:string,remote_saved?:boolean}>('attachments/storage/jobs/'+encodeURIComponent(jobId)+'?'+new URLSearchParams({root}),undefined,'GET',{signal:controller.signal,force:true});
    if(controller.signal.aborted)return;
    const failed=['failed','cancelled','conflict'].includes(job.state);
    setResults(current=>current.map(result=>result.job_id===jobId?{...result,state:job.state,pending:job.remote_saved!==true&&!failed,remote_saved:job.remote_saved===true,...(failed?{error:t('as.job.'+job.state)}:{})}:result));
   }));}finally{polling=false;}
  };
  void poll();const timer=window.setInterval(()=>void poll(),1500);
  return()=>{controller.abort();window.clearInterval(timer);};
 },[config.root,pendingJobs]);
 useEffect(()=>{const controller=new AbortController();setTemplateError('');api<{path:string,title:string}[]>('templates',undefined,undefined,{signal:controller.signal,force:true}).then(value=>{setTemplates(value);setTemplate(value[0]?.path||'');}).catch(e=>{if(!controller.signal.aborted)setTemplateError(e.message);});return()=>controller.abort();},[config.revision,retry]);
 const create=(fromTemplate:boolean)=>void run(fromTemplate?t("从模板新建"):t("创建内容"),()=>{
  const path=joinTarget(target,fromTemplate?templateName:name);
  return fromTemplate?api('template',{path,template}):api('create',{path,directory});
 },data=>{setResults(value=>[{path:data.path,directory:!fromTemplate&&directory,edit:fromTemplate||!directory,cursor:data.cursor},...value]);onChanged();});
 const upload=(files:File[])=>{if(!files.length)return;void run(t("上传文件"),async valid=>{
  const uploaded:FileResult[]=[];
  for(let index=0;index<files.length;index++){
   if(!valid())break;
   const file=files[index];setUploadProgress(`${index+1} / ${files.length} · ${file.name}`);
   try{const response=await fetch('/api/upload?'+new URLSearchParams({root:config.root||'',folder:target.trim(),name:file.name}),{method:'POST',headers:{'X-Vault-CSRF':csrf},body:file});const data=await response.json();if(!response.ok)throw new Error(data.error||t("上传未完成"));uploaded.push({path:data.path,pending:data.pending,remote_saved:data.remote_saved,job_id:data.job_id,state:data.state});}
   catch(error){uploaded.push({path:joinTarget(target,file.name),error:(error as Error).message});}
  }
  return uploaded;
 },uploaded=>{setUploadProgress('');setResults(value=>[...uploaded,...value]);onChanged();});};
 return <>
  <SettingGroup title={t("目标位置")} description={t("以下操作会写入此目录，路径相对于当前知识库。")}><SettingRow label={t("目标目录")} description={t("留空表示知识库根目录。")}><input aria-label={t("目标目录")} value={target} placeholder={t("知识库根目录")} onChange={event=>setTarget(event.target.value)}/></SettingRow></SettingGroup>
  <SettingGroup id="create" title={t("新建内容")}><form onSubmit={event=>{event.preventDefault();create(false);}}><SettingRow label={t("类型")}><select aria-label={t("新建类型")} value={directory?'folder':'file'} onChange={event=>{const folder=event.target.value==='folder';setDirectory(folder);setName(folder?t("新目录"):t("未命名.md"));}}><option value="file">{t("笔记")}</option><option value="folder">{t("目录")}</option></select></SettingRow><SettingRow label={t("名称")}><div className="input-row"><input aria-label={t("新建名称")} required value={name} onChange={event=>setName(event.target.value)}/><button type="submit" disabled={!name.trim()}>{directory?<FolderPlus size={15}/>:<FilePlus size={15}/>}{t("创建")}</button></div></SettingRow></form></SettingGroup>
  <SettingGroup id="upload" title={t("上传文件")} description={t("支持一次选择多个文件，已有同名文件不会被覆盖。")}><div className="upload-area"><Upload size={24} strokeWidth={1.5}/><div><strong>{t("将本地文件加入知识库")}</strong><p>{t("图片、文档、音频与视频会保存到上方指定的目录。")}</p></div><button onClick={()=>input.current?.click()}>{t("选择文件")}</button><input ref={input} aria-label={t("上传文件")} type="file" hidden multiple onChange={event=>{upload(Array.from(event.currentTarget.files||[]));event.currentTarget.value='';}}/></div>{uploadProgress&&<StatusNotice kind="busy">{t("正在上传")}{" "}{uploadProgress}</StatusNotice>}</SettingGroup>
  <SettingGroup id="template-create" title={t("从模板新建")}><form onSubmit={event=>{event.preventDefault();create(true);}}>{templateError?<StatusNotice kind="error">{templateError} <button type="button" onClick={()=>setRetry(value=>value+1)}>{t("重试")}</button></StatusNotice>:templates===undefined?<p className="hint">{t("正在读取模板…")}</p>:!templates.length?<p className="setting-empty">{t("暂无模板。请在「模板与写入」中配置模板目录，并放入 Markdown 模板。")}</p>:<><SettingRow label={t("模板")}><select aria-label={t("选择模板")} value={template} onChange={event=>setTemplate(event.target.value)}>{templates.map(item=><option key={item.path} value={item.path}>{item.title}</option>)}</select></SettingRow><SettingRow label={t("笔记名称")}><div className="input-row"><input aria-label={t("模板笔记名称")} required value={templateName} onChange={event=>setTemplateName(event.target.value)}/><button type="submit" disabled={!templateName.trim()||!template}>{t("创建笔记")}</button></div></SettingRow></>}</form></SettingGroup>
  {!!results.length&&<SettingGroup title={t("操作结果")}><div ref={resultArea} className="settings-results" role="status">{results.map((result,index)=><div className="settings-result" key={index}>{result.directory?<Folder size={17}/>:<FileText size={17}/>}<div><strong>{result.path}</strong><small className={result.error?'error':''}>{result.error||t(result.pending||result.remote_saved===false||result.job_id&&result.remote_saved!==true?remotePendingStates.has(result.state||'')?'as.job.'+result.state:'as.job.queued':result.remote_saved===true?'as.job.completed':'已保存到知识库')}</small></div>{!result.error&&<button onClick={()=>onOpen(result)}>{t("打开")}<ArrowUpRight size={14}/></button>}</div>)}</div></SettingGroup>}
 </>;
}

type RecordItem={id:string,path:string,time:number,destination?:string};
export function RecordsPage({root,trash=false,path,run,onChanged}:{root:string,trash?:boolean,path?:string,run:RunAction,onChanged:()=>void}){
 useLocale();
 const [kind,setKind]=useState(trash?'trash':path?'history':'operations'),[filter,setFilter]=useState(path||''),[query,setQuery]=useState(path||''),[data,setData]=useState<RecordItem[]>(),[error,setError]=useState(''),[reload,setReload]=useState(0);
 const [confirmation,setConfirmation]=useState<{record?:RecordItem,clear?:boolean}>();
 const latest=useRef(root);latest.current=root;
 useEffect(()=>{const controller=new AbortController();setData(undefined);setError('');api<RecordItem[]>('records?kind='+kind+(kind==='history'&&query?'&path='+encodeURIComponent(query):''),undefined,undefined,{signal:controller.signal,force:true}).then(setData).catch(e=>{if(!controller.signal.aborted)setError(e.message);});return()=>controller.abort();},[root,kind,query,reload]);
 const requestRoot=root;
 return <SettingGroup id={trash?'trash':'records'} title={trash?t("已删除内容"):t("历史记录")}>
  {!trash&&<><div className="view-tabs settings-record-tabs" aria-label={t("历史类型")}><button aria-pressed={kind==='operations'} className={kind==='operations'?'active':''} onClick={()=>setKind('operations')}>{t("目录操作")}</button><button aria-pressed={kind==='history'} className={kind==='history'?'active':''} onClick={()=>setKind('history')}>{t("文档版本")}</button></div>{kind==='history'&&<form className="record-filter" onSubmit={event=>{event.preventDefault();setQuery(filter.trim());setReload(value=>value+1);}}><input aria-label={t("历史文件路径")} placeholder={t("按文件路径筛选，留空查看全部")} value={filter} onChange={event=>setFilter(event.target.value)}/><button>{t("查看")}</button></form>}</>}
  {error?<StatusNotice kind="error">{<Diagnostic message={error}/>} <button onClick={()=>setReload(value=>value+1)}>{t("重试")}</button></StatusNotice>:data===undefined?<StatusNotice kind="busy">{t("正在读取记录…")}</StatusNotice>:data.length?<div className="settings-record-list"><VirtualList items={data} itemKey={record=>record.id} estimate={74} height={390} render={record=><div className="record"><div><strong>{record.path}</strong><small>{new Date(record.time*1000).toLocaleString(getLocale())}{record.destination?' → '+record.destination:''}</small></div><button onClick={()=>setConfirmation({record})}>{t("恢复")}</button></div>}/></div>:<div className="setting-empty">{trash?<Trash2 size={28} strokeWidth={1.3}/>:<History size={28} strokeWidth={1.3}/>}<p>{trash?t("回收区为空"):t("暂无历史记录")}</p><span>{trash?t("删除的文件会出现在这里。"):t("文档保存或目录操作后，可以在这里查看记录。")}</span></div>}
  {trash&&<div className="danger-zone"><div><strong>{t("清空回收区")}</strong><p>{t("永久删除回收区内的全部文件和目录，无法恢复。")}</p></div><button className="danger" disabled={!data?.length} onClick={()=>setConfirmation({clear:true})}>{t("清空回收区")}</button></div>}
  {confirmation&&<FormDialog title={confirmation.clear?t("清空回收区"):t("恢复记录")} description={confirmation.clear?t("永久删除回收区中的全部文件和目录？此操作无法撤销。"):t("恢复「")+confirmation.record!.path+t("」？文档版本恢复可能覆盖当前内容。")} submitLabel={confirmation.clear?t("永久清空"):t("确认恢复")} danger={confirmation.clear} onClose={()=>setConfirmation(undefined)} onSubmit={async()=>{
   if(latest.current!==requestRoot)return;
   // The dialog owns its busy/error state; run keeps the settings shell from navigating during the write.
   let failure:unknown;
   await run(confirmation.clear?t("清空回收区"):t("恢复记录"),async valid=>{
    try{const result=confirmation.clear?await api('trash/clear',{root:requestRoot,confirm:true}):await api('restore',{kind,id:confirmation.record!.id});if(valid()){if(result.path)window.dispatchEvent(new CustomEvent('vault-restored',{detail:result.path}));onChanged();setReload(value=>value+1);}return result;}
    catch(error){failure=error;if(valid())setReload(value=>value+1);throw error;}
   });
   if(failure)throw failure;
  }}/>} 
 </SettingGroup>;
}
