import {Diagnostic} from './i18n';
import {t,useLocale} from './i18n';
import {getLocale} from './i18n';
import React,{useCallback,useEffect,useRef,useState} from 'react';
import {MessageSquare,Plus,Send,Square,X,History,RefreshCw} from 'lucide-react';
import {api,Config,invalidate,OpenNote} from './api';
import {Action,FormDialog,LazyBoundary} from './ui';
import {MarkdownPreview} from './reader';
import {applyAiChange,changeDocument,documentState,loadDocument,saveDocument} from './document-state';
import {AiReference} from './ai-context';
import './ai.css';

type Topic={id:string,title:string,provider:string,state:string,error:string,native_id?:string,updated:number};
type Turn={id:string,question:string,answer:string,state:string,error:string,references:AiReference[]};
type Proposal={id:string,path:string,original:string,text:string,etag:string,create_note:number,state:string};
type Detail={conversation:Topic,turns:Turn[],proposals:Proposal[]};
type Provider={id:string,name:string,available:boolean,connected:boolean};
type Attempt={topic:string,provider:string,payload:Record<string,unknown>};
type Composer={question:string,references:AiReference[],attempt?:Attempt};
const empty=():Composer=>({question:'',references:[]});
const uuid=()=>crypto.randomUUID().replaceAll('-','');
const get=(key:string,fallback:string)=>{try{return localStorage.getItem(key)||fallback;}catch{return fallback;}};
const put=(key:string,value:string)=>{try{localStorage.setItem(key,value);return true;}catch{return false;}};
const composerKey=(root:string,id:string)=>'ai-compose:'+root+'\n'+(id||'new');
function readComposer(root:string,id:string):Composer{try{const value=JSON.parse(get(composerKey(root,id),'null'));return value&&typeof value.question==='string'&&Array.isArray(value.references)?value:empty();}catch{return empty();}}
export function noteDiff(original:string,next:string){
 const before=original.split('\n'),after=next.split('\n');let start=0,end=0;
 while(start<before.length&&start<after.length&&before[start]===after[start])start++;
 if(start===before.length&&start===after.length)return t("正文没有变化");
 while(end<before.length-start&&end<after.length-start&&before[before.length-1-end]===after[after.length-1-end])end++;
 return [t("@@ 第 {p0} 行起 @@",{p0:start+1}),...before.slice(Math.max(0,start-2),start).map(x=>' '+x),
  ...before.slice(start,before.length-end).map(x=>'- '+x),...after.slice(start,after.length-end).map(x=>'+ '+x),
  ...after.slice(after.length-end,after.length-end+2).map(x=>' '+x)].join('\n');
}

export function AiPanel({config,path,visible,onClose,onOpen,notify,selection,demo=false}:{config:Config,path:string,visible:boolean,onClose:()=>void,onOpen:OpenNote,notify:(message:string)=>void,selection?:{id:string,reference:AiReference},demo?:boolean}){
 useLocale();
 const root=config.root!;
 const [selected,setSelected]=useState(()=>get('ai-topic:'+root,''));
 const [provider,setProvider]=useState(()=>get('ai-provider','codely'));
 const [providers,setProviders]=useState<Provider[]>([]),[topics,setTopics]=useState<Topic[]>([]),[detail,setDetail]=useState<Detail>();
 const [composer,setComposer]=useState<Composer>(()=>readComposer(root,selected));
 const [history,setHistory]=useState(false),[includeContext,setIncludeContext]=useState(true),[sending,setSending]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const [createProposal,setCreateProposal]=useState<Proposal>(),[applying,setApplying]=useState(''),[rename,setRename]=useState<Topic>();
 const input=useRef<HTMLTextAreaElement>(null),scroll=useRef<HTMLDivElement>(null),follow=useRef(true),selectedRef=useRef(selected),alive=useRef(true),reloadTimer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
 const detailGeneration=useRef(0),seenSelection=useRef(''),lastComposerKey=useRef(composerKey(root,selected));
 selectedRef.current=selected;
 const choose=useCallback((id:string)=>{setDetail(undefined);setSelected(id);put('ai-topic:'+root,id);setHistory(false);setError('');setNotice('');follow.current=true;},[root]);
 useEffect(()=>()=>{alive.current=false;},[]);
 useEffect(()=>{const key=composerKey(root,selected);if(key!==lastComposerKey.current){lastComposerKey.current=key;setComposer(readComposer(root,selected));}},[root,selected]);
 const updateComposer=useCallback((update:(current:Composer)=>Composer)=>{setComposer(current=>{const next=update(current);if(!put(composerKey(root,selectedRef.current),JSON.stringify(next)))setError(t("发送框草稿存储不可用，请复制保留当前内容"));return next;});},[root]);
 useEffect(()=>{if(!selection||selection.id===seenSelection.current||selection.reference.root!==root)return;seenSelection.current=selection.id;
  updateComposer(current=>({...current,references:[...current.references,selection.reference]}));setTimeout(()=>input.current?.focus(),0);
 },[selection,root,updateComposer]);
 const loadDetail=useCallback(async()=>{const id=selectedRef.current;if(!id)return;const generation=++detailGeneration.current;
  try{const data=await api<Detail>('ai/conversations/'+id);if(alive.current&&selectedRef.current===id&&generation===detailGeneration.current)setDetail(data);}catch(e){if(alive.current&&selectedRef.current===id)setError((e as Error).message);}
 },[]);
 const loadTopics=useCallback(async()=>{try{const list=await api<Topic[]>('ai/conversations');if(!alive.current)return;setTopics(list);if(selectedRef.current&&!list.some(item=>item.id===selectedRef.current))choose('');}catch(e){if(alive.current)setError((e as Error).message);}},[choose]);
 const loadProviders=useCallback(async()=>{try{const data=await api<Provider[]>('ai/providers');if(alive.current)setProviders(data);}catch(e){if(alive.current)setError((e as Error).message);}},[]);
 useEffect(()=>{if(visible){void loadTopics();void loadProviders();void loadDetail();}},[visible,selected,loadTopics,loadProviders,loadDetail]);
 useEffect(()=>{if(!visible)return;const events=new EventSource('/api/ai/events');
  const schedule=()=>{if(!reloadTimer.current)reloadTimer.current=setTimeout(()=>{reloadTimer.current=undefined;void loadDetail();},120);};
  events.onmessage=event=>{try{const value=JSON.parse(event.data);if(value.type==='closed'){events.close();return;}if(value.type==='reset'){void loadTopics();schedule();return;}
   if(value.type==='topics'||value.type==='state')void loadTopics();
   if(value.conversation_id===selectedRef.current){if(value.type==='notice')setNotice(value.message);schedule();}
  }catch{setError(t("AI 通知暂不可用，请重新连接"));}};
  events.onerror=()=>setNotice(t("AI 连接中断，正在恢复；会话与已收到的回答仍保留"));
  events.onopen=()=>setNotice('');
  return()=>{events.close();clearTimeout(reloadTimer.current);reloadTimer.current=undefined;};
 },[visible,loadTopics,loadDetail]);
 useEffect(()=>{if(follow.current&&scroll.current)scroll.current.scrollTop=scroll.current.scrollHeight;},[detail]);

 const send=async(retry=false)=>{
  if(sending)return;setSending(true);setError('');
  const sourceKey=composerKey(root,selected);
  try{
   let attempt=retry?composer.attempt:undefined;
   if(!attempt){
    if(!composer.question.trim())throw new Error(t("请输入问题"));
    if(selected&&!detail)throw new Error(t("正在读取原会话，请稍后发送"));
    let context:Record<string,unknown>|undefined;
    if(includeContext&&path&&/\.(md|txt)$/i.test(path)){
     const doc=documentState(root,path);if(!doc.note)await loadDocument(doc);
     if(doc.pending)await doc.pending;
     if(doc.dirty&&!doc.manualSave)await saveDocument(doc,false);
     if(!doc.note||doc.error)throw new Error(doc.error||t("当前笔记尚未加载"));
     context={root,path,text:doc.text,etag:doc.etag};
    }
    const topic=selected||uuid(),chosen=detail?.conversation.provider||provider;
    attempt={topic,provider:chosen,payload:{root,question:composer.question,references:composer.references,context,request_id:uuid()}};
    updateComposer(current=>({...current,attempt}));
   }
   await api('ai/conversations',{root,provider:attempt.provider,client_id:attempt.topic});
   await api('ai/conversations/'+attempt.topic+'/messages',attempt.payload);
   if(alive.current){
    const sent=attempt;
    setComposer(current=>{
     const counts=new Map<string,number>();for(const ref of sent.payload.references as AiReference[]){const key=JSON.stringify(ref);counts.set(key,(counts.get(key)||0)+1);}
     const next:Composer={question:current.question===sent.payload.question?'':current.question,references:current.references.filter(ref=>{const key=JSON.stringify(ref),count=counts.get(key)||0;if(count){counts.set(key,count-1);return false;}return true;})};
     put(sourceKey,JSON.stringify(next));put(composerKey(root,sent.topic),JSON.stringify(next));return next;
    });lastComposerKey.current=composerKey(root,attempt.topic);choose(attempt.topic);void loadTopics();setTimeout(()=>void loadDetail(),0);
   }
  }catch(e){if(alive.current)setError((e as Error).message);}
  finally{if(alive.current)setSending(false);}
 };
 const apply=async(proposal:Proposal,newPath?:string)=>{
  if(!selected||applying)return;setApplying(proposal.id);setError('');
  let doc:ReturnType<typeof documentState>|undefined;
  try{
   if(!proposal.create_note){
    doc=documentState(root,proposal.path);if(!doc.note)await loadDocument(doc);if(doc.pending)await doc.pending;
    clearTimeout(doc.timer);doc.timer=undefined;
    if(doc.text!==proposal.original||doc.etag!==proposal.etag)throw new Error(t("原文或草稿已改变；建议仍保留，请重新生成或手动合并"));
   }
   const result=await api('ai/conversations/'+selected+'/proposals/'+proposal.id+'/accept',{root,path:newPath});
   if(result.created){invalidate({paths:[result.path]});onOpen(result.path);notify(t("新笔记已创建"));}
   else if(doc){
    applyAiChange(doc,proposal.original,result.text,result.etag);
    onOpen(proposal.path);notify(t("AI 修改已加入草稿，请核对后手动保存"));
    await api('ai/conversations/'+selected+'/proposals/'+proposal.id+'/applied',{root});
   }
   setCreateProposal(undefined);await loadDetail();
  }catch(e){if(doc?.dirty&&!doc.manualSave)changeDocument(doc,doc.text);setError((e as Error).message);throw e;}
  finally{setApplying('');}
 };
 const running=detail?.conversation.state==='running';
 const available=providers.find(p=>p.id===(detail?.conversation.provider||provider))?.available;
 return <aside className="ai-panel" aria-label={t("AI 对话")} hidden={!visible}>
  {demo&&<div className="ai-demo-banner">{t('演示：此对话使用虚构示例，不连接外部 AI 服务。')}</div>}
  <header className="ai-heading"><strong><MessageSquare size={17}/>{t("AI 对话")}</strong><div>
   <Action title={t("历史会话")} onClick={()=>setHistory(value=>!value)}><History size={16}/></Action>
   <Action title={t("新建 AI 会话")} onClick={()=>{if(!sending){choose('');setTimeout(()=>input.current?.focus(),0);}}}><Plus size={17}/></Action>
   <Action title={t("重新连接 AI")} onClick={()=>{void loadProviders();void loadTopics();void loadDetail();}}><RefreshCw size={15}/></Action>
   <Action title={t("关闭 AI 面板")} onClick={onClose}><X size={17}/></Action>
  </div></header>
  {history&&<div className="ai-history" aria-label={t("历史会话列表")}>{topics.length?topics.map(topic=><div className="ai-topic-row" key={topic.id}><button disabled={sending} className={selected===topic.id?'active':''} onClick={()=>choose(topic.id)}><strong>{topic.title}</strong><span>{topic.provider} · {new Date(topic.updated*1000).toLocaleDateString(getLocale())}{topic.state==='running'?t(" · 正在回答"):''}</span></button><button title={t("重命名会话")} onClick={()=>setRename(topic)}>…</button></div>):<p className="hint">{t("还没有历史会话，首次发送后会保存在这里。")}</p>}</div>}
  <div className="ai-topic-title">{detail?.conversation.title||t("新对话")}<span>{detail?.conversation.provider||provider}</span></div>
  <div className="ai-messages" ref={scroll} onScroll={()=>{const e=scroll.current;if(e)follow.current=e.scrollHeight-e.scrollTop-e.clientHeight<70;}}>
   {!detail?.turns.length&&<div className="ai-empty"><MessageSquare size={26}/><p>{t("围绕你的笔记继续讨论")}</p><span>{t("选中文字后右键“添加到 AI 对话”，或直接输入问题。")}</span></div>}
   {detail?.turns.map(turn=><React.Fragment key={turn.id}><article className="ai-message ai-user"><span className="ai-role">{t("你")}</span><p>{turn.question}</p>{turn.references.map((ref,i)=><details className="ai-reference" key={i}><summary><button onClick={()=>{if(ref.kind!=='design')onOpen(ref.path);}}>{ref.label||ref.path}</button></summary><blockquote>{ref.text}</blockquote></details>)}</article>
    <article className="ai-message ai-answer"><span className="ai-role">AI{turn.state==='running'?t(" · 正在回答…"):''}</span>{turn.answer?<LazyBoundary><MarkdownPreview text={turn.answer} path={path||''} onOpen={onOpen}/></LazyBoundary>:turn.state==='running'?<p className="hint">{t("正在连接并读取上下文…")}</p>:null}{turn.error&&<p className="error">{<Diagnostic message={turn.error}/>}</p>}{turn.state==='interrupted'&&<span className="hint">{t("本轮已停止，原会话保留")}</span>}</article></React.Fragment>)}
   {detail?.proposals.map(proposal=><section className="ai-proposal" key={proposal.id}><strong>{proposal.create_note?t("新笔记建议"):t("修改建议")} · {proposal.path}</strong><details><summary>{t("查看差异预览")}</summary><pre>{noteDiff(proposal.original,proposal.text)}</pre></details>{proposal.state==='pending'?<div><button disabled={!!applying} onClick={()=>proposal.create_note?setCreateProposal(proposal):void apply(proposal).catch(()=>{})}>{applying===proposal.id?t("正在应用…"):proposal.create_note?t("确认创建…"):t("接受到草稿")}</button><button disabled={!!applying} onClick={()=>void api('ai/conversations/'+selected+'/proposals/'+proposal.id+'/reject',{root}).then(loadDetail).catch(e=>setError(e.message))}>{t("拒绝")}</button></div>:<span className="hint">{proposal.state==='accepted'?t("已接受"):t("已拒绝")}</span>}</section>)}
  </div>
  <div className="ai-composer">
   {notice&&<p role="status" className="hint">{notice}</p>}{(error||detail?.conversation.error)&&<p role="alert" className="error">{error||detail?.conversation.error}</p>}
   {!selected&&<label className="ai-provider">{t("使用")}<select aria-label="AI CLI" value={provider} onChange={e=>{setProvider(e.target.value);put('ai-provider',e.target.value);}}><option value="codely">Codely CLI</option><option value="codex">Codex CLI</option></select></label>}
   {composer.references.map((ref,i)=><div className="ai-composer-reference" key={i}><button title={ref.text} onClick={()=>{if(ref.kind!=='design')onOpen(ref.path);}}>{ref.label||ref.path}<span>{ref.text.slice(0,110)}</span></button><Action title={t("移除引用")} onClick={()=>updateComposer(c=>({...c,references:c.references.filter((_,index)=>index!==i)}))}><X size={13}/></Action></div>)}
   {composer.attempt&&<div className="ai-retry"><span>{t("上次发送结果待确认")}</span><button disabled={sending} onClick={()=>void send(true)}>{t("重试这次发送")}</button><button disabled={sending} onClick={()=>updateComposer(c=>({...c,attempt:undefined}))}>{t("重新编辑")}</button></div>}
   <textarea ref={input} aria-label={t("AI 问题")} placeholder={t("询问、总结或改写笔记…")} rows={3} maxLength={32000} disabled={sending||!!composer.attempt} value={composer.question} onChange={e=>updateComposer(c=>({...c,question:e.target.value}))} onKeyDown={e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'&&!e.nativeEvent.isComposing){e.preventDefault();if(!running&&!composer.attempt)void send();}}}/>
   <div className="ai-composer-actions"><label><input type="checkbox" checked={includeContext} onChange={e=>setIncludeContext(e.target.checked)}/>{t("当前笔记")}{path?'':t("（未打开）")}</label>{running?<button onClick={()=>void api('ai/conversations/'+selected+'/stop',{root}).then(loadDetail).catch(e=>setError(e.message))}><Square size={13}/>{t("停止")}</button>:<button disabled={sending||!composer.question.trim()||!!composer.attempt||available===false||(!!selected&&!detail)} onClick={()=>void send()}><Send size={14}/>{sending?t("发送中…"):t("发送")}</button>}</div>
   {available===false&&<p className="hint">{t("未找到本机 CLI，请安装并在终端完成登录后点击重新连接。")}</p>}
  </div>
  {createProposal&&<FormDialog title={t("创建 AI 生成的笔记")} fields={[{name:'path',label:t("文件路径（相对知识库）"),value:createProposal.path,required:true}]} description={t("确认目录与文件名后创建，不会覆盖同名文件。")} onClose={()=>setCreateProposal(undefined)} onSubmit={values=>apply(createProposal,values.path)}/>}
  {rename&&<FormDialog title={t("重命名会话")} fields={[{name:'title',label:t("会话名称"),value:rename.title,required:true}]} onClose={()=>setRename(undefined)} onSubmit={async values=>{await api('ai/conversations/'+rename.id,{root,title:values.title},'PATCH');setRename(undefined);await loadTopics();await loadDetail();}}/>}
 </aside>;
}
