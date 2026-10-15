import {csrf,invalidate} from './api';
import {t} from './i18n';
export const imageFile=(name:string)=>/\.(png|jpe?g|gif|webp|avif|svg)$/i.test(name);
export function attachmentName(file:File){
 const extensions:Record<string,string>={'image/png':'.png','image/jpeg':'.jpg','image/gif':'.gif','image/webp':'.webp','image/avif':'.avif'};
 let name=file.name.replace(/[<>:"/\\|?*\x00-\x1f]/g,'-').replace(/^[. ]+|[. ]+$/g,'')||'image';
 const extension=/\.[a-z0-9]{1,12}$/i.exec(name)?.[0]||extensions[file.type]||'';
 if(extension&&name.endsWith(extension))name=name.slice(0,-extension.length);
 return name.slice(0,100)+'-'+crypto.randomUUID().slice(0,12)+extension;
}
export type UploadedAsset={relative:string,label:string,image:boolean};
export async function uploadEditorAssets(files:File[],options:{root:string,path:string,signal:AbortSignal,alive:()=>boolean,status:(message:string)=>void}){
 const parent=options.path.includes('/')?options.path.slice(0,options.path.lastIndexOf('/')):'',folder=(parent?parent+'/':'')+'attachments',assets:UploadedAsset[]=[];
 for(let i=0;i<files.length;i++){
  if(!options.alive())throw new DOMException('cancelled','AbortError');
  options.status(t('正在上传附件 {current}/{total}…',{current:i+1,total:files.length}));
  const file=files[i],name=attachmentName(file),query=new URLSearchParams({folder,name,root:options.root,create_folder:'true'});
  const response=await fetch('/api/upload?'+query,{method:'POST',credentials:'same-origin',headers:{'X-Vault-CSRF':csrf,'Content-Type':file.type||'application/octet-stream'},body:file,signal:options.signal});
  const result=await response.json();if(!response.ok)throw new Error(result.error||t('附件上传失败'));
  invalidate({paths:[result.path]});
  if(!options.alive())throw new DOMException('cancelled','AbortError');
  assets.push({relative:'attachments/'+encodeURIComponent(name).replace(/\(/g,'%28').replace(/\)/g,'%29'),label:file.name||name,image:imageFile(name)});
 }
 return assets;
}
