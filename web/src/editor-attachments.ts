import {EditorView,ViewPlugin} from '@codemirror/view';
import {csrf,invalidate} from './api';
import {t} from './i18n';
import {editAnnotations,InsertRange,linkMarkdown,insertLink,safeLink} from './editor-commands';
import {removeAnchor,trackedRange,trackRange} from './editor-anchors';
import {prosePosition} from './editor-syntax';

export const imageFile=(name:string)=>/\.(png|jpe?g|gif|webp|avif|svg)$/i.test(name);
export function attachmentName(file:File){
 const mimeExtension:Record<string,string>={'image/png':'.png','image/jpeg':'.jpg','image/gif':'.gif','image/webp':'.webp','image/avif':'.avif'};
 let name=file.name.replace(/[<>:"/\\|?*\x00-\x1f]/g,'-').replace(/^[. ]+|[. ]+$/g,'')||'image';
 const extension=/\.[a-z0-9]{1,12}$/i.exec(name)?.[0]||mimeExtension[file.type]||'';
 if(name.endsWith(extension)&&extension)name=name.slice(0,-extension.length);
 return name.slice(0,100)+'-'+crypto.randomUUID().slice(0,12)+extension;
}
export type AttachmentOptions={root:string,path:string,active:()=>boolean,status:(message:string,error?:boolean)=>void};
export function attachmentController(view:EditorView,options:AttachmentOptions){
 let destroyed=false;const pending=new Map<string,AbortController>();
 const alive=(id:string)=>!destroyed&&options.active()&&!!trackedRange(view,id);
 const cancel=()=>{for(const [id,controller] of pending)if(!alive(id)){controller.abort();pending.delete(id);if(!destroyed)view.dispatch({effects:removeAnchor.of(id)});}};
 const abortAll=()=>{for(const [id,controller] of pending){controller.abort();if(!destroyed)view.dispatch({effects:removeAnchor.of(id)});}pending.clear();};
 const change=(event:Event)=>{const detail=(event as CustomEvent).detail;if(detail.reset||detail.type==='config'||detail.root&&detail.root!==options.root)abortAll();};
 window.addEventListener('vault-data-changed',change);
 const upload=async(files:File[],range:InsertRange,id=trackRange(view,range))=>{
  if(!files.length||!alive(id)){view.dispatch({effects:removeAnchor.of(id)});return;}
  const controller=new AbortController();pending.set(id,controller);
  const parent=options.path.includes('/')?options.path.slice(0,options.path.lastIndexOf('/')):'';
  const folder=(parent?parent+'/':'')+'attachments';
  const links:string[]=[];
  try{
   for(let i=0;i<files.length;i++){
    if(!alive(id))throw new DOMException('cancelled','AbortError');
    options.status(t('正在上传附件 {current}/{total}…',{current:i+1,total:files.length}));
    const file=files[i],name=attachmentName(file);
    const query=new URLSearchParams({folder,name,root:options.root,create_folder:'true'});
    const response=await fetch('/api/upload?'+query,{method:'POST',credentials:'same-origin',headers:{'X-Vault-CSRF':csrf,'Content-Type':file.type||'application/octet-stream'},body:file,signal:controller.signal});
    const result=await response.json();if(!response.ok)throw new Error(result.error||t('附件上传失败'));
    invalidate({paths:[result.path]});
    if(!alive(id))throw new DOMException('cancelled','AbortError');
    const relative='attachments/'+encodeURIComponent(name).replace(/\(/g,'%28').replace(/\)/g,'%29');
    links.push((imageFile(name)?'!':'')+linkMarkdown(file.name||name,relative));
   }
   const target=trackedRange(view,id);if(!target||!alive(id))throw new DOMException('cancelled','AbortError');
   const before=view.state.doc.sliceString(view.state.doc.lineAt(target.from).from,target.from),after=view.state.doc.sliceString(target.to,view.state.doc.lineAt(target.to).to);
   const insert=(before.trim()?'\n\n':'')+links.join('\n\n')+(after.trim()?'\n\n':'');
   pending.delete(id);
   view.dispatch({changes:{from:target.from,to:target.to,insert},effects:removeAnchor.of(id),annotations:editAnnotations});
   options.status(t('附件已插入'));
  }catch(error){
   if(!destroyed)options.status((error as Error).name==='AbortError'?t('附件插入已取消'):(error as Error).message,true);
  }finally{
   pending.delete(id);if(!destroyed)view.dispatch({effects:removeAnchor.of(id)});
  }
 };
 const choose=(images:boolean,range:InsertRange)=>{
  const input=document.createElement('input');input.type='file';input.multiple=true;if(images)input.accept='image/png,image/jpeg,image/gif,image/webp,image/avif,image/svg+xml';
  const id=trackRange(view,range),controller=new AbortController();pending.set(id,controller);
  input.onchange=()=>{pending.delete(id);if(!destroyed)void upload(Array.from(input.files||[]),range,id);input.remove();};
  input.oncancel=()=>{pending.delete(id);if(!destroyed)view.dispatch({effects:removeAnchor.of(id)});input.remove();};
  controller.signal.addEventListener('abort',()=>input.remove(),{once:true});
  input.hidden=true;view.dom.append(input);input.click();
 };
 return {upload,choose,cancel,abortAll,destroy(){abortAll();destroyed=true;window.removeEventListener('vault-data-changed',change);}};
}
export function attachmentEvents(get:()=>ReturnType<typeof attachmentController>|undefined){
 return [ViewPlugin.fromClass(class{
  constructor(readonly view:EditorView){}
  update(){queueMicrotask(()=>get()?.cancel());}
 }),EditorView.domEventHandlers({
  paste(event,view){
   if(view.composing||!prosePosition(view.state,view.state.selection.main.from))return false;
   const clipboard=event.clipboardData;if(!clipboard)return false;
   const files=Array.from(clipboard.files);if(files.length){event.preventDefault();void get()?.upload(files,view.state.selection.main);return true;}
   const url=clipboard.getData('text/plain').trim();
   if(!view.state.selection.main.empty&&safeLink(url)){event.preventDefault();return insertLink(view,view.state.selection.main,url);}
   return false;
  },
  dragover(event){if(event.dataTransfer?.types.includes('Files')){event.preventDefault();return true;}return false;},
  drop(event,view){
   const files=Array.from(event.dataTransfer?.files||[]);if(!files.length)return false;
   event.preventDefault();const pos=view.posAtCoords({x:event.clientX,y:event.clientY});
   if(pos!==null&&prosePosition(view.state,pos))void get()?.upload(files,{from:pos,to:pos});return true;
  }
 })];
}
