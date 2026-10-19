import React,{useEffect,useState} from 'react';
import {MessageCircle,Check,CornerDownRight,MapPin,Trash2} from 'lucide-react';
import {t,useLocale} from './i18n';
import {Annotation,AnnotationMessage,AnnotationSelection,resolveAnchor} from './annotations';
import './annotations.css';

type Props={
 annotations:Annotation[];source:string;selectedId?:string;
 draft: {range:AnnotationSelection|null}|null;
 onDraft:(draft:{range:AnnotationSelection|null}|null)=>void;
 onCreate:(content:string,range:AnnotationSelection|null)=>Promise<void>;
 onReply:(item:Annotation,content:string)=>Promise<void>;
 onEditMessage:(item:Annotation,message:AnnotationMessage,content:string)=>Promise<void>;
 onStatus:(item:Annotation,status:'open'|'resolved')=>Promise<void>;
 onDelete:(item:Annotation)=>Promise<void>;
 onJump:(item:Annotation)=>void;
 onReanchor:(item:Annotation)=>Promise<void>;
 onClose:()=>void;
};
const time=(value:number)=>new Date(value*1000).toLocaleString();
const excerpt=(source:string,item:Annotation)=>item.anchor?.exact||'';
const statusLabel=(item:Annotation)=>item.status==='resolved'?t('重新打开'):t('标记为已解决');

function CommentItem({item,source,selected,props}:{item:Annotation,source:string,selected:boolean,props:Props}){
 const [reply,setReply]=useState(''),[editing,setEditing]=useState<string|null>(null),[editText,setEditText]=useState('');
 const [working,setWorking]=useState(false),[error,setError]=useState('');
 const locate=item.anchor?resolveAnchor(source,item.anchor):null;
 const perform=async(action:()=>Promise<void>)=>{
  setWorking(true);setError('');try{await action();}catch(e){setError(String((e as Error).message||e));}finally{setWorking(false);}
 };
 return <article className={'leafloom-comment-card'+(selected?' selected':'')} data-annotation-card={item.id}>
  <div className="leafloom-comment-card-head">
   <span className={'leafloom-comment-dot leafloom-'+item.color}/>
   <strong>{item.type==='highlight'?t('高亮标注'):item.anchor?t('行内评论'):t('页面评论')}</strong>
   {item.status==='resolved'&&<span className="leafloom-resolved-label">{t('已解决')}</span>}
  </div>
  {item.anchor&&<button className="leafloom-quoted" onClick={()=>props.onJump(item)}>
   {excerpt(source,item).slice(0,280)}{excerpt(source,item).length>280?'…':''}
   {!locate&&<span className="leafloom-lost"> · {t('定位已失效')}</span>}
  </button>}
  {item.type==='comment'&&item.messages.map(message=><div className="leafloom-message" key={message.id}>
   <div className="leafloom-message-meta"><strong>{message.author}</strong><time>{time(message.created_at)}</time></div>
   {editing===message.id?<div className="leafloom-comment-form">
    <textarea aria-label={t('编辑评论')} value={editText} maxLength={20000} onChange={e=>setEditText(e.target.value)}/>
    <div className="leafloom-comment-actions">
     <button disabled={working||!editText.trim()} onClick={()=>void perform(async()=>{await props.onEditMessage(item,message,editText);setEditing(null);})}>{t('保存')}</button>
     <button onClick={()=>setEditing(null)}>{t('取消')}</button>
    </div>
   </div>:<><p>{message.content}</p><button className="leafloom-minor" onClick={()=>{setEditing(message.id);setEditText(message.content);}}>{t('编辑')}</button></>}
  </div>)}
  {item.type==='comment'&&item.status==='open'&&<div className="leafloom-comment-form">
   <textarea aria-label={t('回复评论')} placeholder={t('回复评论…')} value={reply} maxLength={20000} onChange={e=>setReply(e.target.value)}/>
   <button disabled={working||!reply.trim()} onClick={()=>void perform(async()=>{await props.onReply(item,reply);setReply('');})}><CornerDownRight size={13}/>{t('回复')}</button>
  </div>}
  <div className="leafloom-comment-actions">
   {item.type==='comment'&&<button disabled={working} onClick={()=>void perform(()=>props.onStatus(item,item.status==='open'?'resolved':'open'))}><Check size={13}/>{statusLabel(item)}</button>}
   {item.anchor&&!locate&&<button disabled={working} onClick={()=>void perform(()=>props.onReanchor(item))}><MapPin size={13}/>{t('关联到当前选区')}</button>}
   <button disabled={working} title={t('删除标注')} onClick={()=>{if(confirm(t('确定删除这条标注及回复？可在当前会话中撤销。')))void perform(()=>props.onDelete(item));}}><Trash2 size={13}/>{t('删除')}</button>
  </div>
  {error&&<p role="alert" className="leafloom-comment-error">{error}</p>}
 </article>;
}

export function CommentsPanel(props:Props){
 useLocale();
 const [filter,setFilter]=useState<'open'|'all'|'resolved'>('open');
 const [draftText,setDraftText]=useState(''),[submitting,setSubmitting]=useState(false),[error,setError]=useState('');
 useEffect(()=>{setDraftText('');setError('');},[props.draft?.range?.from,props.draft?.range?.to,props.draft===null]);
 const filtered=props.annotations.filter(a=>filter==='all'||a.status===filter);
 const send=async()=>{
  if(!draftText.trim()||submitting||!props.draft)return;
  setSubmitting(true);setError('');
  try{await props.onCreate(draftText,props.draft.range);setDraftText('');props.onDraft(null);}
  catch(e){setError(String((e as Error).message||e));}
  finally{setSubmitting(false);}
 };
 return <aside className="related-panel leafloom-comments-panel" aria-label={t('评论')}>
  <div className="info-heading"><strong><MessageCircle size={16}/>{t('评论')} · {props.annotations.filter(a=>a.status==='open').length}</strong><button className="icon-button" onClick={props.onClose} aria-label={t('关闭评论')}>×</button></div>
  <div className="leafloom-comment-head-actions">
   <select aria-label={t('评论筛选')} value={filter} onChange={e=>setFilter(e.target.value as typeof filter)}>
    <option value="open">{t('未解决')}</option><option value="all">{t('全部')}</option><option value="resolved">{t('已解决')}</option>
   </select>
   <button onClick={()=>props.onDraft({range:null})}>＋ {t('页面评论')}</button>
  </div>
  {props.draft&&<div className="leafloom-comment-card leafloom-draft">
   <strong>{props.draft.range?t('添加行内评论'):t('添加页面评论')}</strong>
   {props.draft.range&&<blockquote className="leafloom-quoted">{props.source.slice(props.draft.range.from,props.draft.range.to).slice(0,200)}</blockquote>}
   <textarea aria-label={t('评论内容')} autoFocus maxLength={20000} value={draftText} placeholder={t('输入评论…')} onChange={e=>setDraftText(e.target.value)} onKeyDown={e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();void send();}}}/>
   <div className="leafloom-comment-actions"><button disabled={!draftText.trim()||submitting} onClick={()=>void send()}>{t('提交评论')}</button><button onClick={()=>props.onDraft(null)}>{t('取消')}</button></div>
   {error&&<p className="leafloom-comment-error" role="alert">{error}</p>}
  </div>}
  <div className="leafloom-comments-scroll">{filtered.map(item=><CommentItem key={item.id} item={item} source={props.source} selected={item.id===props.selectedId} props={props}/>)}
   {!filtered.length&&<p className="hint leafloom-comment-empty">{t('没有匹配的评论或标注')}</p>}
  </div>
 </aside>;
}
