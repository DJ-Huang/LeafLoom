// Decode originals away from the editor and retain only small, transparent previews.
type ThumbnailJob={key:string,url:string};
const jobs:ThumbnailJob[]=[];
let running=0;
const cache=new Map<string,Blob>();
const scope=self as unknown as {onmessage:(event:MessageEvent<ThumbnailJob>)=>void,postMessage:(value:unknown)=>void};
async function thumbnail(job:ThumbnailJob){
 let bitmap:ImageBitmap|undefined;
 try{
  let blob=cache.get(job.key);
  if(!blob){
   const response=await fetch(job.url,{credentials:'same-origin'});if(!response.ok)throw new Error('Thumbnail unavailable');
   const original=await response.blob();bitmap=await createImageBitmap(original);
   const ratio=Math.min(1,256/Math.max(bitmap.width,bitmap.height)),canvas=new OffscreenCanvas(Math.max(1,Math.round(bitmap.width*ratio)),Math.max(1,Math.round(bitmap.height*ratio)));
   const context=canvas.getContext('2d');if(!context)throw new Error('Canvas unavailable');context.drawImage(bitmap,0,0,canvas.width,canvas.height);
   blob=await canvas.convertToBlob({type:'image/webp',quality:.8});
   cache.set(job.key,blob);while(cache.size>256)cache.delete(cache.keys().next().value!);
  }
  scope.postMessage({key:job.key,blob});
 }catch{scope.postMessage({key:job.key,error:true});}finally{bitmap?.close();running--;drain();}
}
function drain(){while(running<2&&jobs.length){running++;void thumbnail(jobs.shift()!);}}
scope.onmessage=event=>{jobs.push(event.data);drain();};
