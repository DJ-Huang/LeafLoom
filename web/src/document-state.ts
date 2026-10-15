import {api,Note} from './api';
import {createEditHistory,EditHistory,EditMeta,historyText,recordEdit} from './edit-history';
export type DocumentState={root:string,path:string,key:string,text:string,etag:string,note?:Note,dirty:boolean,manualSave:boolean,stale?:boolean,pending?:Promise<void>,timer?:ReturnType<typeof setTimeout>,state:string,error:string,version:number,externalEpoch:number,readGeneration:number,listeners:Set<()=>void>,touched:number};
const sessions=new Map<string,DocumentState>();
const histories=new WeakMap<DocumentState,EditHistory>();
export function documentHistory(session:DocumentState){let history=histories.get(session);if(!history){history=createEditHistory();histories.set(session,history);}return history;}
export const draftKey=(root:string,path:string)=>'draft:'+root+'\n'+path;
function emit(session:DocumentState){session.version++;session.touched=Date.now();for(const listener of session.listeners)listener();}
function persist(session:DocumentState){try{if(session.dirty)localStorage.setItem(session.key,JSON.stringify({text:session.text,etag:session.etag,manualSave:session.manualSave}));else localStorage.removeItem(session.key);}catch{if(session.dirty)session.error='本地草稿存储不可用；当前内容仍在页面中，请保存或下载草稿';}}
function trim(retain?:DocumentState){
 let size=0;for(const session of sessions.values())size+=session.text.length*2;
 for(const [key,session] of [...sessions].sort((a,b)=>a[1].touched-b[1].touched)){
  if(sessions.size<=64&&size<=32*1024*1024)break;
  if(session===retain||session.listeners.size||session.pending||session.timer)continue;
  persist(session);size-=session.text.length*2;sessions.delete(key);
 }
}
export function documentState(root:string,path:string){
 const key=draftKey(root,path);let session=sessions.get(key);
 if(!session){let draft:any;try{draft=JSON.parse(localStorage.getItem(key)||'null');}catch{}
  session={root,path,key,text:draft?.text||'',etag:draft?.etag||'',dirty:typeof draft?.text==='string',manualSave:draft?.manualSave===true,state:draft?.manualSave?'AI 草稿 · 请手动保存':draft?'草稿待保存':'已保存',error:'',version:0,externalEpoch:0,readGeneration:0,listeners:new Set(),touched:Date.now()};sessions.set(key,session);
 }session.touched=Date.now();trim(session);return session;
}
export async function loadDocument(session:DocumentState,signal?:AbortSignal,force=false){
 const generation=++session.readGeneration;
 try{
  const note=await api<Note>('file?path='+encodeURIComponent(session.path),undefined,undefined,{signal,force});
  if(generation!==session.readGeneration||signal?.aborted)return;
  session.note=note;session.error='';session.stale=false;
  if(session.dirty){if(!session.pending&&session.etag&&session.etag!==note.etag){session.state='保存冲突 · 外部修改，草稿仍保留';session.error='磁盘正文已变化，请核对后合并；当前草稿不会被覆盖';}}
  else{if(session.text!==note.text){session.externalEpoch++;histories.delete(session);}session.text=note.text;session.etag=note.etag;session.state='已保存';}
  emit(session);
 }catch(error){if((error as Error).name!=='AbortError'&&generation===session.readGeneration){session.error=(error as Error).message;emit(session);}}
}
export function changeDocument(session:DocumentState,text:string,meta:EditMeta={}){if(session.text===text)return;recordEdit(documentHistory(session),session.text,text,meta);session.text=text;session.dirty=true;session.state=session.manualSave?'AI 草稿 · 请手动保存':'待保存';persist(session);emit(session);clearTimeout(session.timer);session.timer=undefined;if(!session.manualSave)session.timer=setTimeout(()=>{session.timer=undefined;void saveDocument(session,false);},1000);}
export function travelDocument(session:DocumentState,direction:'undo'|'redo'){
 const history=documentHistory(session),result=historyText(history,session.text,direction);if(!result)return false;
 history.replaying=true;try{changeDocument(session,result.text);session.externalEpoch++;emit(session);}finally{history.replaying=false;}return true;
}
export async function saveDocument(session:DocumentState,explicit=true){
 if(session.manualSave&&!explicit)return;
 if(session.pending)return session.pending;
 if(!session.dirty||!session.etag)return;
 clearTimeout(session.timer);session.timer=undefined;session.readGeneration++;
 const text=session.text,etag=session.etag;session.state='保存中…';emit(session);
 session.pending=(async()=>{
  let success=false;
  try{const note=await api<Note>('file',{path:session.path,root:session.root,text,etag},'PUT');session.readGeneration++;session.note=note;session.etag=note.etag;session.dirty=session.text!==text;if(!session.dirty)session.manualSave=false;session.error='';session.state=session.dirty?(session.manualSave?'AI 草稿 · 请手动保存':'待保存'):'已保存';success=true;persist(session);}
  catch(error){session.state=(error as any).conflict?'保存冲突 · 内容仍保留':'保存失败 · 内容仍保留';session.error=(error as Error).message;persist(session);}
  finally{session.pending=undefined;emit(session);if(success&&session.dirty&&!session.manualSave){clearTimeout(session.timer);session.timer=setTimeout(()=>{session.timer=undefined;void saveDocument(session,false);},400);}trim();}
 })();return session.pending;
}
export function applyProperties(session:DocumentState,note:Note){
 if(session.dirty)return false;
 recordEdit(documentHistory(session),session.text,note.text,{kind:'external'});
 session.note=note;if(session.text!==note.text)session.externalEpoch++;session.text=note.text;session.etag=note.etag;session.state='已保存';emit(session);return true;
}
export function acceptDiskVersion(session:DocumentState,etag:string){session.etag=etag;persist(session);}
export function applyAiChange(session:DocumentState,original:string,text:string,etag:string){
 if(session.pending||session.text!==original||session.etag!==etag)throw new Error('原文或草稿已改变，未应用建议；请重新生成或手动合并');
 if(text===original)return;
 clearTimeout(session.timer);session.timer=undefined;session.manualSave=true;session.externalEpoch++;
 changeDocument(session,text);
}
export async function discardAiDraft(session:DocumentState){
 clearTimeout(session.timer);session.timer=undefined;if(session.pending)await session.pending;
 const before=session.text;
 const note=await api<Note>('file?path='+encodeURIComponent(session.path),undefined,undefined,{force:true});
 if(session.text!==before)throw new Error('草稿又有修改，请重新确认后丢弃');
 session.note=note;session.text=note.text;session.etag=note.etag;session.dirty=false;session.manualSave=false;session.error='';session.state='已保存';session.externalEpoch++;histories.delete(session);persist(session);emit(session);
}
window.addEventListener('beforeunload',event=>{if([...sessions.values()].some(session=>session.dirty)){event.preventDefault();event.returnValue='';}});
// Never auto-accept an AI draft. Dirty/conflicting content remains guarded by
// beforeunload and persisted locally if the user explicitly exits anyway.
window.leafloomPrepareQuit=async()=>{
 await Promise.all([...sessions.values()].map(async session=>{
  clearTimeout(session.timer);session.timer=undefined;
  if(session.pending)await session.pending;
  if(session.dirty&&!session.manualSave)await saveDocument(session,false);
  persist(session);
 }));
};
