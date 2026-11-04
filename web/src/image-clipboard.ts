import {t} from './i18n';
export const MAX_CLIPBOARD_IMAGE_BYTES=32*1024*1024,MAX_CLIPBOARD_IMAGE_PIXELS=64_000_000;
const cancelled=(signal:AbortSignal)=>signal.throwIfAborted();

async function readImage(url:string,signal:AbortSignal):Promise<Blob>{
 const response=await fetch(url,{signal,credentials:'same-origin'});
 if(!response.ok)throw new Error(t(response.status===404?'design.imageFileMissing':'design.imageReadFailed'));
 if(Number(response.headers.get('content-length'))>MAX_CLIPBOARD_IMAGE_BYTES)throw new Error(t('design.imageCopyTooLarge'));
 const reader=response.body?.getReader();
 if(!reader)throw new Error(t('design.imageReadFailed'));
 const chunks:Uint8Array<ArrayBuffer>[]= [];let size=0;
 try{while(true){const {done,value}=await reader.read();cancelled(signal);if(done)break;size+=value.byteLength;if(size>MAX_CLIPBOARD_IMAGE_BYTES)throw new Error(t('design.imageCopyTooLarge'));chunks.push(new Uint8Array(value));}}
 finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
 return new Blob(chunks,{type:response.headers.get('content-type')||'application/octet-stream'});
}
export async function imagePng(url:string,signal:AbortSignal):Promise<Blob>{
 let blob:Blob;
 try{blob=await readImage(url,signal);}catch(error){cancelled(signal);if(error instanceof Error&&[t('design.imageFileMissing'),t('design.imageReadFailed'),t('design.imageCopyTooLarge')].includes(error.message))throw error;throw new Error(t('design.imageReadFailed'));}
 cancelled(signal);
 let image:ImageBitmap|HTMLImageElement|undefined,objectUrl='';
 try{
  // ImageBitmap takes the first frame of an animated image. SVG needs an
  // image-element fallback in browsers without SVG ImageBitmap decoding.
  try{image=await createImageBitmap(blob);}catch{
   cancelled(signal);objectUrl=URL.createObjectURL(blob);const element=new Image();element.decoding='async';element.src=objectUrl;
   const abort=()=>{element.src='';};signal.addEventListener('abort',abort,{once:true});
   try{await element.decode();image=element;}finally{signal.removeEventListener('abort',abort);}
  }
  cancelled(signal);
  const width=image instanceof HTMLImageElement?image.naturalWidth:image.width,height=image instanceof HTMLImageElement?image.naturalHeight:image.height;
  if(!width||!height)throw new Error(t('design.imageDecodeFailed'));
  if(width*height>MAX_CLIPBOARD_IMAGE_PIXELS)throw new Error(t('design.imageCopyTooLarge'));
  const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
  try{
   const context=canvas.getContext('2d');if(!context)throw new Error(t('design.imageDecodeFailed'));
   context.drawImage(image,0,0);cancelled(signal);
   const png=await new Promise<Blob>((resolve,reject)=>canvas.toBlob(value=>value?resolve(value):reject(new Error(t('design.imageDecodeFailed'))),'image/png'));
   cancelled(signal);if(png.size>MAX_CLIPBOARD_IMAGE_BYTES)throw new Error(t('design.imageCopyTooLarge'));return png;
  }finally{canvas.width=canvas.height=0;}
 }catch(error){cancelled(signal);if(error instanceof Error&&[t('design.imageCopyTooLarge'),t('design.imageReadFailed')].includes(error.message))throw error;throw new Error(t('design.imageDecodeFailed'));}
 finally{if(image&&'close' in image)image.close();if(objectUrl)URL.revokeObjectURL(objectUrl);}
}

// Invoke browser write during the user gesture, supplying pixels asynchronously.
// Desktop writes bypass web permission prompts through the trusted main frame.
export async function writeClipboardImage(png:Promise<Blob>,signal:AbortSignal):Promise<void>{
 let preparationError:unknown;
 const prepared=png.then(value=>{cancelled(signal);if(value.type!=='image/png'||!value.size||value.size>MAX_CLIPBOARD_IMAGE_BYTES)throw new Error(t('design.imageCopyTooLarge'));return value;}).catch(error=>{preparationError=error;throw error;});
 // Unsupported sessions must still consume a failed preparation promise.
 void prepared.catch(()=>{});
 const desktop=window.leafloomDesktop;
 if(desktop){
  if(!desktop.writeClipboardImage)throw new Error(t('design.imageCopyRestart'));
  const value=await prepared,bytes=new Uint8Array(await value.arrayBuffer());cancelled(signal);
  try{await desktop.writeClipboardImage(bytes);}catch{throw new Error(t('design.imageCopyFailed'));}return;
 }
 if(!navigator.clipboard?.write||typeof ClipboardItem==='undefined')throw new Error(t('design.imageClipboardUnavailable'));
 try{await navigator.clipboard.write([new ClipboardItem({'image/png':prepared})]);}catch{if(preparationError)throw preparationError;throw new Error(t('design.imageClipboardUnavailable'));}
}

export class ImageCopyRequest {
 private controller?:AbortController;
 cancel(){this.controller?.abort();this.controller=undefined;}
 async run(operation:(signal:AbortSignal)=>Promise<void>):Promise<boolean>{
  this.cancel();const controller=new AbortController();this.controller=controller;
  try{await operation(controller.signal);return !controller.signal.aborted;}
  catch(error){if(controller.signal.aborted)return false;throw error;}
  finally{controller.abort();if(this.controller===controller)this.controller=undefined;}
 }
}
