import {api,media} from './api';
import {t} from './i18n';
import {ImageCopyRequest,imagePng,writeClipboardImage} from './image-clipboard';

export type NoteImageSource={url?:string,target?:string,notePath:string,root?:string};

/** Resolve a note image to a same-origin `/api/media` URL (or keep an absolute http(s) URL). */
export async function noteImageMediaUrl(source:NoteImageSource,signal:AbortSignal):Promise<string>{
 if(source.url){
  try{
   const parsed=new URL(source.url,location.origin);
   if(parsed.origin===location.origin&&parsed.pathname==='/api/media'){
    const path=parsed.searchParams.get('path');
    if(path)return media(path,false,source.root);
   }
   if(/^https?:$/i.test(parsed.protocol))return source.url;
  }catch{/* fall through to target */}
 }
 const target=(source.target||'').trim();
 if(!target)throw new Error(t('note.imageUnresolved'));
 if(/^https?:/i.test(target))return target;
 const result=await api<{candidates:string[]}>('resolve?target='+encodeURIComponent(target)+'&source='+encodeURIComponent(source.notePath),undefined,undefined,{signal});
 if(result.candidates.length!==1)throw new Error(t('note.imageUnresolved'));
 return media(result.candidates[0],false,source.root);
}

/** Start clipboard write during the user gesture; PNG bytes resolve asynchronously. */
export function copyNoteImage(source:NoteImageSource,signal:AbortSignal):Promise<void>{
 return writeClipboardImage(noteImageMediaUrl(source,signal).then(url=>imagePng(url,signal)),signal);
}

export {ImageCopyRequest};
