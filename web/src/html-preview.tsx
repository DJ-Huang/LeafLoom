import {t,useLocale} from './i18n';
import React,{useEffect,useRef,useState} from 'react';
import {ArrowLeft,ArrowRight,ExternalLink,Maximize,Minimize,RefreshCw,Settings,Globe} from 'lucide-react';
import {api,Change} from './api';
import {Modal,FormDialog} from './ui';
import {chooseDirectory} from './desktop';

type Project={id:string,vault:string,directory:string,entry:string,spa:boolean};
type WebSession={id:string|null,url:string,origin?:string,entry?:string,mode:'saved'|'draft'|'external'};

export function HtmlPreview({path,root,draft,active}:{path:string,root:string,draft?:string,active:boolean}){
 useLocale();
 const frame=useRef<HTMLIFrameElement>(null),current=useRef<WebSession|null>(null);
 const [project,setProject]=useState<Project|null>(null),[checked,setChecked]=useState(false),[setup,setSetup]=useState(false);
 const [directory,setDirectory]=useState(''),[spa,setSpa]=useState(false),[saving,setSaving]=useState(false),[setupError,setSetupError]=useState('');
 const [session,setSession]=useState<WebSession|null>(null),[location,setLocation]=useState('');
 const [full,setFull]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[revision,setRevision]=useState(0);
 const [address,setAddress]=useState(''),[urlDialog,setUrlDialog]=useState(false),[externalNote,setExternalNote]=useState(false);
 const command=(value:string)=>{const s=current.current;if(s?.id&&s.origin)frame.current?.contentWindow?.postMessage({session:s.id,command:value},s.origin);};
 useEffect(()=>{
  let alive=true;setChecked(false);setProject(null);setError('');setAddress('');
  if(!path){setChecked(true);setSetup(false);return;}
  api<{selected:Project|null,suggested_directory:string}>('html-projects?'+new URLSearchParams({root,path}),undefined,undefined,{force:true}).then(result=>{
   if(!alive)return;setProject(result.selected);setDirectory(result.selected?.directory??result.suggested_directory);setSpa(result.selected?.spa??false);setChecked(true);setSetup(!result.selected);
  }).catch(e=>{if(alive){setError(e.message);setChecked(true);}});
  return()=>{alive=false;};
 },[path,root]);
 useEffect(()=>{
  if(!active||!checked||(!project&&!address))return;
  let alive=true,created:WebSession|null=null;setBusy(true);setError('');setSession(null);setExternalNote(!!address);
  api<WebSession>('html-sessions',address?{root,url:address}:{root,path,project_id:project!.id,...(draft===undefined?{}:{draft})}).then(result=>{
   created=result;if(!alive){if(result.id)void api('html-sessions/'+result.id,undefined,'DELETE').catch(()=>{});return;}
   current.current=result;setSession(result);setLocation(result.entry&&result.origin?result.origin+result.entry:result.url);
  }).catch(e=>{if(alive){setError(e.message);setBusy(false);}});
  return()=>{alive=false;current.current=null;if(created?.id)void api('html-sessions/'+created.id,undefined,'DELETE').catch(()=>{});};
 },[root,path,project?.id,checked,draft,active,revision,address]);
 useEffect(()=>{
  const listener=(event:MessageEvent)=>{
   const s=current.current;if(!s?.id||event.source!==frame.current?.contentWindow||event.origin!==s.origin||event.data?.session!==s.id)return;
   const data=event.data;
   if(data.type==='leafloom-web-ready')setBusy(false);
   if(data.type==='leafloom-web-external')setExternalNote(true);
   if(data.type==='leafloom-web-expired'){setBusy(false);setError(t('网页会话已失效，请重新打开。'));}
   if(data.type==='leafloom-web-location'&&typeof data.url==='string')try{const next=new URL(data.url);if(next.origin===s.origin)setLocation(next.href);}catch{}
  };
  const escape=(event:KeyboardEvent)=>{if(event.key==='Escape')setFull(false);};
  window.addEventListener('message',listener);window.addEventListener('keydown',escape);
  return()=>{window.removeEventListener('message',listener);window.removeEventListener('keydown',escape);};
 },[]);
 useEffect(()=>{
  if(!active)return;
  const changed=(event:Event)=>{const change=(event as CustomEvent<Change>).detail;if(change.reset||change.type==='config')setRevision(n=>n+1);};
  window.addEventListener('vault-data-changed',changed);return()=>window.removeEventListener('vault-data-changed',changed);
 },[active]);
 useEffect(()=>{if(!active)setFull(false);},[active]);
 useEffect(()=>{
  if(!session||!busy)return;
  const timer=setTimeout(()=>{setBusy(false);if(session.mode==='external')setExternalNote(true);else setError(t('尚未确认网页加载完成，请重试或检查项目目录。'));},15000);
  return()=>clearTimeout(timer);
 },[session,busy]);
 const saveProject=async(event:React.FormEvent)=>{
  event.preventDefault();if(saving)return;setSaving(true);setSetupError('');
  try{const p=await api<Project>('html-projects',{root,directory,entry:project?.entry||path,spa,...(project?{id:project.id}:{})});setProject(p);setAddress('');setSetup(false);setChecked(true);setRevision(n=>n+1);}
  catch(e){setSetupError((e as Error).message);}finally{setSaving(false);}
 };
 const selectDirectory=async()=>{
  try{const selected=await chooseDirectory();if(!selected.path)return;const normal=(s:string)=>s.replace(/\\/g,'/').replace(/\/$/,'');const base=normal(root),chosen=normal(selected.path);const compare=(s:string)=>/^[A-Za-z]:/.test(s)?s.toLowerCase():s;if(compare(chosen)!==compare(base)&&!compare(chosen).startsWith(compare(base)+'/'))throw new Error(t('请选择知识库内的项目文件夹'));setDirectory(chosen.slice(base.length).replace(/^\//,''));}catch(e){setSetupError((e as Error).message);}
 };
 const standalone=(()=>{if(!session?.id||!session.origin||!location)return location;const target=new URL(location);return session.origin+'/__leafloom__/viewer?'+new URLSearchParams({session:session.id,path:target.pathname+target.search+target.hash});})();
 return <section className={'html-preview'+(full?' html-preview-full':'')} hidden={!active} aria-label={t('HTML 网页浏览')}>
  <div className="html-preview-toolbar">
   <span>{session?.mode==='draft'?t('未保存草稿'):t('网页浏览')}</span>
   <button title={t('后退')} disabled={!session?.id} onClick={()=>command('back')}><ArrowLeft size={15}/></button>
   <button title={t('前进')} disabled={!session?.id} onClick={()=>command('forward')}><ArrowRight size={15}/></button>
   <button title={t('刷新网页')} disabled={!session} onClick={()=>{if(error||session?.mode==='external')setRevision(n=>n+1);else command('reload');}}><RefreshCw size={15}/>{t('刷新')}</button>
   {path&&<button onClick={()=>{setSetupError('');setSetup(true);}}><Settings size={15}/>{t('项目设置')}</button>}
   <button onClick={()=>setUrlDialog(true)}><Globe size={15}/>{t('打开网址')}</button>
   {address&&<button onClick={()=>setAddress('')}>{t('返回项目')}</button>}
   {!window.leafloomDesktop&&standalone&&<a className="button" href={standalone} target="_blank" rel="noopener noreferrer"><ExternalLink size={15}/>{t('独立标签页')}</a>}
   <button title={full?t('退出全屏阅读'):t('全屏阅读')} onClick={()=>setFull(x=>!x)}>{full?<Minimize size={15}/>:<Maximize size={15}/>} {full?t('退出全屏'):t('全屏阅读')}</button>
  </div>
  {(busy||error)&&<div className={'html-preview-message'+(error?' error':'')} role={error?'alert':'status'}>{error||t('正在打开网页…')}{error&&<button onClick={()=>setRevision(n=>n+1)}>{t('重试')}</button>}</div>}
  {externalNote&&<div className="html-preview-message">{t('外部网站可能限制嵌入或要求登录；未显示内容不代表加载成功。')}</div>}
  {!session&&!busy&&!error&&!setup&&<div className="empty-state"><Globe size={32}/><p>{t('输入网站地址，或从目录打开 HTML 项目。')}</p><button onClick={()=>setUrlDialog(true)}>{t('打开网址')}</button></div>}
  {session&&<iframe key={session.url} ref={frame} className="html-preview-frame" title={t('网页 · ')+path.split('/').pop()} src={session.url} allow="fullscreen; clipboard-read; clipboard-write; autoplay; camera; microphone; geolocation; display-capture" allowFullScreen onLoad={()=>{if(session.mode==='external')setBusy(false);}}/>}
  {setup&&<Modal title={t('HTML 项目设置')} onClose={()=>setSetup(false)}><form onSubmit={saveProject}>
   <div className="pad"><p>{t('确认一次项目文件夹，之后自动复用。网页的 / 对应该文件夹，配套资源必须位于其中。')}</p>
    <label className="setting-field">{t('项目文件夹（相对知识库，留空为知识库根目录）')}<input autoFocus value={directory} onChange={e=>setDirectory(e.target.value)}/></label>
    <button type="button" onClick={()=>void selectDirectory()}>{t('选择文件夹')}</button>
    <label className="setting-field"><span><input type="checkbox" checked={spa} onChange={e=>setSpa(e.target.checked)}/> {t('SPA 路由：页面路径不存在时打开项目入口')}</span></label>
    {setupError&&<p className="error" role="alert">{setupError}</p>}
   </div><footer className="modal-footer"><button type="button" disabled={saving} onClick={()=>setSetup(false)}>{t('取消')}</button><button className="primary" disabled={saving}>{t('保存并打开')}</button></footer>
  </form></Modal>}
  {urlDialog&&<FormDialog title={t('打开网站或开发服务')} description={t('使用现有 HTTP/HTTPS 地址，不安装或启动网站后台。')} fields={[{name:'url',label:t('网站地址'),value:address||'https://',required:true}]} onClose={()=>setUrlDialog(false)} onSubmit={async values=>{const target=new URL(values.url);if(!['http:','https:'].includes(target.protocol)||target.username||target.password)throw new Error(t('请输入 HTTP 或 HTTPS 网站地址'));setAddress(target.href);}}/>}
 </section>;
}
