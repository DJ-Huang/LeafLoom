import React,{useEffect,useRef,useState} from 'react';
import {FilePlus,FolderPlus,Upload,FileText,Folder,ArrowUpRight,Trash2,History} from 'lucide-react';
import {api,csrf,Config} from './api';
import {FormDialog} from './ui';
import {VirtualList} from './virtual';
import {SettingsResult,joinTarget} from './settings-model';
import {RunAction,SettingGroup,SettingRow,StatusNotice} from './settings-ui';

export function SkillInstaller({run}:{run:RunAction}){
 const [skill,setSkill]=useState<{path:string,installed:boolean,up_to_date:boolean}>(),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 useEffect(()=>{const controller=new AbortController();setError('');api<typeof skill>('skills/wiki-search',undefined,undefined,{force:true,signal:controller.signal}).then(setSkill).catch(e=>{if(!controller.signal.aborted)setError(e.message);});return()=>controller.abort();},[retry]);
 return <SettingGroup id="skill" title="知识库查询技能" description="让 AI 优先查询你的知识库，返回简短结论与原文链接。"><SettingRow label="wiki-search" description="按知识检索、主题导航与文件检索补齐依据。"><button disabled={!skill||skill.up_to_date} onClick={()=>void run('安装查询技能',()=>api('skills/wiki-search/install',{}),setSkill)}>{!skill?'检查安装状态…':skill.up_to_date?'已安装最新版本':skill.installed?'更新技能':'安装技能'}</button></SettingRow>{skill&&<p className="setting-detail">安装位置：<code>{skill.path}</code></p>}{error&&<StatusNotice kind="error">{error} <button onClick={()=>setRetry(value=>value+1)}>重试</button></StatusNotice>}{skill?.up_to_date&&<StatusNotice kind="success">查询技能已就绪。MCP 连接沿用现有配置。</StatusNotice>}</SettingGroup>;
}

type FileResult=SettingsResult&{error?:string};
export function FileTools({config,folder,run,onOpen,onChanged}:{config:Config,folder:string,run:RunAction,onOpen:(result:SettingsResult)=>void,onChanged:()=>void}){
 const [target,setTarget]=useState(folder),[name,setName]=useState('未命名.md'),[directory,setDirectory]=useState(false),[templateName,setTemplateName]=useState('未命名.md'),[template,setTemplate]=useState('');
 const [templates,setTemplates]=useState<{path:string,title:string}[]>(),[templateError,setTemplateError]=useState(''),[retry,setRetry]=useState(0),[results,setResults]=useState<FileResult[]>([]),[uploadProgress,setUploadProgress]=useState('');
 const input=useRef<HTMLInputElement>(null),resultArea=useRef<HTMLDivElement>(null);
 useEffect(()=>{if(results.length)resultArea.current?.scrollIntoView({block:'nearest'});},[results.length]);
 useEffect(()=>{const controller=new AbortController();setTemplateError('');api<{path:string,title:string}[]>('templates',undefined,undefined,{signal:controller.signal,force:true}).then(value=>{setTemplates(value);setTemplate(value[0]?.path||'');}).catch(e=>{if(!controller.signal.aborted)setTemplateError(e.message);});return()=>controller.abort();},[config.revision,retry]);
 const create=(fromTemplate:boolean)=>void run(fromTemplate?'从模板新建':'创建内容',()=>{
  const path=joinTarget(target,fromTemplate?templateName:name);
  return fromTemplate?api('template',{path,template}):api('create',{path,directory});
 },data=>{setResults(value=>[{path:data.path,directory:!fromTemplate&&directory,edit:fromTemplate||!directory,cursor:data.cursor},...value]);onChanged();});
 const upload=(files:File[])=>{if(!files.length)return;void run('上传文件',async valid=>{
  const uploaded:FileResult[]=[];
  for(let index=0;index<files.length;index++){
   if(!valid())break;
   const file=files[index];setUploadProgress(`${index+1} / ${files.length} · ${file.name}`);
   try{const response=await fetch('/api/upload?folder='+encodeURIComponent(target.trim())+'&name='+encodeURIComponent(file.name),{method:'POST',headers:{'X-Vault-CSRF':csrf},body:file});const data=await response.json();if(!response.ok)throw new Error(data.error||'上传未完成');uploaded.push({path:data.path});}
   catch(error){uploaded.push({path:joinTarget(target,file.name),error:(error as Error).message});}
  }
  return uploaded;
 },uploaded=>{setUploadProgress('');setResults(value=>[...uploaded,...value]);onChanged();});};
 return <>
  <SettingGroup title="目标位置" description="以下操作会写入此目录，路径相对于当前知识库。"><SettingRow label="目标目录" description="留空表示知识库根目录。"><input aria-label="目标目录" value={target} placeholder="知识库根目录" onChange={event=>setTarget(event.target.value)}/></SettingRow></SettingGroup>
  <SettingGroup id="create" title="新建内容"><form onSubmit={event=>{event.preventDefault();create(false);}}><SettingRow label="类型"><select aria-label="新建类型" value={directory?'folder':'file'} onChange={event=>{const folder=event.target.value==='folder';setDirectory(folder);setName(folder?'新目录':'未命名.md');}}><option value="file">笔记</option><option value="folder">目录</option></select></SettingRow><SettingRow label="名称"><div className="input-row"><input aria-label="新建名称" required value={name} onChange={event=>setName(event.target.value)}/><button type="submit" disabled={!name.trim()}>{directory?<FolderPlus size={15}/>:<FilePlus size={15}/>}创建</button></div></SettingRow></form></SettingGroup>
  <SettingGroup id="upload" title="上传文件" description="支持一次选择多个文件，已有同名文件不会被覆盖。"><div className="upload-area"><Upload size={24} strokeWidth={1.5}/><div><strong>将本地文件加入知识库</strong><p>图片、文档、音频与视频会保存到上方指定的目录。</p></div><button onClick={()=>input.current?.click()}>选择文件</button><input ref={input} aria-label="上传文件" type="file" hidden multiple onChange={event=>{upload(Array.from(event.currentTarget.files||[]));event.currentTarget.value='';}}/></div>{uploadProgress&&<StatusNotice kind="busy">正在上传 {uploadProgress}</StatusNotice>}</SettingGroup>
  <SettingGroup id="template-create" title="从模板新建"><form onSubmit={event=>{event.preventDefault();create(true);}}>{templateError?<StatusNotice kind="error">{templateError} <button type="button" onClick={()=>setRetry(value=>value+1)}>重试</button></StatusNotice>:templates===undefined?<p className="hint">正在读取模板…</p>:!templates.length?<p className="setting-empty">暂无模板。请在「模板与写入」中配置模板目录，并放入 Markdown 模板。</p>:<><SettingRow label="模板"><select aria-label="选择模板" value={template} onChange={event=>setTemplate(event.target.value)}>{templates.map(item=><option key={item.path} value={item.path}>{item.title}</option>)}</select></SettingRow><SettingRow label="笔记名称"><div className="input-row"><input aria-label="模板笔记名称" required value={templateName} onChange={event=>setTemplateName(event.target.value)}/><button type="submit" disabled={!templateName.trim()||!template}>创建笔记</button></div></SettingRow></>}</form></SettingGroup>
  {!!results.length&&<SettingGroup title="操作结果"><div ref={resultArea} className="settings-results" role="status">{results.map((result,index)=><div className="settings-result" key={index}>{result.directory?<Folder size={17}/>:<FileText size={17}/>}<div><strong>{result.path}</strong><small className={result.error?'error':''}>{result.error||'已保存到知识库'}</small></div>{!result.error&&<button onClick={()=>onOpen(result)}>打开<ArrowUpRight size={14}/></button>}</div>)}</div></SettingGroup>}
 </>;
}

type RecordItem={id:string,path:string,time:number,destination?:string};
export function RecordsPage({root,trash=false,path,run,onChanged}:{root:string,trash?:boolean,path?:string,run:RunAction,onChanged:()=>void}){
 const [kind,setKind]=useState(trash?'trash':path?'history':'operations'),[filter,setFilter]=useState(path||''),[query,setQuery]=useState(path||''),[data,setData]=useState<RecordItem[]>(),[error,setError]=useState(''),[reload,setReload]=useState(0);
 const [confirmation,setConfirmation]=useState<{record?:RecordItem,clear?:boolean}>();
 const latest=useRef(root);latest.current=root;
 useEffect(()=>{const controller=new AbortController();setData(undefined);setError('');api<RecordItem[]>('records?kind='+kind+(kind==='history'&&query?'&path='+encodeURIComponent(query):''),undefined,undefined,{signal:controller.signal,force:true}).then(setData).catch(e=>{if(!controller.signal.aborted)setError(e.message);});return()=>controller.abort();},[root,kind,query,reload]);
 const requestRoot=root;
 return <SettingGroup id={trash?'trash':'records'} title={trash?'已删除内容':'历史记录'}>
  {!trash&&<><div className="view-tabs settings-record-tabs" aria-label="历史类型"><button aria-pressed={kind==='operations'} className={kind==='operations'?'active':''} onClick={()=>setKind('operations')}>目录操作</button><button aria-pressed={kind==='history'} className={kind==='history'?'active':''} onClick={()=>setKind('history')}>文档版本</button></div>{kind==='history'&&<form className="record-filter" onSubmit={event=>{event.preventDefault();setQuery(filter.trim());setReload(value=>value+1);}}><input aria-label="历史文件路径" placeholder="按文件路径筛选，留空查看全部" value={filter} onChange={event=>setFilter(event.target.value)}/><button>查看</button></form>}</>}
  {error?<StatusNotice kind="error">{error} <button onClick={()=>setReload(value=>value+1)}>重试</button></StatusNotice>:data===undefined?<StatusNotice kind="busy">正在读取记录…</StatusNotice>:data.length?<div className="settings-record-list"><VirtualList items={data} itemKey={record=>record.id} estimate={74} height={390} render={record=><div className="record"><div><strong>{record.path}</strong><small>{new Date(record.time*1000).toLocaleString('zh-CN')}{record.destination?' → '+record.destination:''}</small></div><button onClick={()=>setConfirmation({record})}>恢复</button></div>}/></div>:<div className="setting-empty">{trash?<Trash2 size={28} strokeWidth={1.3}/>:<History size={28} strokeWidth={1.3}/>}<p>{trash?'回收区为空':'暂无历史记录'}</p><span>{trash?'删除的文件会出现在这里。':'文档保存或目录操作后，可以在这里查看记录。'}</span></div>}
  {trash&&<div className="danger-zone"><div><strong>清空回收区</strong><p>永久删除回收区内的全部文件和目录，无法恢复。</p></div><button className="danger" disabled={!data?.length} onClick={()=>setConfirmation({clear:true})}>清空回收区</button></div>}
  {confirmation&&<FormDialog title={confirmation.clear?'清空回收区':'恢复记录'} description={confirmation.clear?'永久删除回收区中的全部文件和目录？此操作无法撤销。':'恢复「'+confirmation.record!.path+'」？文档版本恢复可能覆盖当前内容。'} submitLabel={confirmation.clear?'永久清空':'确认恢复'} danger={confirmation.clear} onClose={()=>setConfirmation(undefined)} onSubmit={async()=>{
   if(latest.current!==requestRoot)return;
   // The dialog owns its busy/error state; run keeps the settings shell from navigating during the write.
   let failure:unknown;
   await run(confirmation.clear?'清空回收区':'恢复记录',async valid=>{
    try{const result=confirmation.clear?await api('trash/clear',{root:requestRoot,confirm:true}):await api('restore',{kind,id:confirmation.record!.id});if(valid()){if(result.path)window.dispatchEvent(new CustomEvent('vault-restored',{detail:result.path}));onChanged();setReload(value=>value+1);}return result;}
    catch(error){failure=error;if(valid())setReload(value=>value+1);throw error;}
   });
   if(failure)throw failure;
  }}/>} 
 </SettingGroup>;
}
