import React,{useEffect,useMemo,useState} from 'react';
import {Image} from 'lucide-react';
import {media} from './api';

type ThumbnailCache={worker:Worker|null,urls:Map<string,string>,waiting:Map<string,{url:string,listeners:Set<(url:string)=>void>}>,failed:Set<string>};
export function useStudioThumbnails(root:string,directory:string){
 const cache=useMemo<ThumbnailCache>(()=>({worker:null,urls:new Map(),waiting:new Map(),failed:new Set()}),[root,directory]);
 useEffect(()=>{
  let worker:Worker;
  try{worker=new Worker(new URL('./studio-thumbnails.worker.ts',import.meta.url),{type:'module'});}catch{return;}
  cache.worker=worker;
  worker.onmessage=event=>{const {key,blob,error}=event.data;const request=cache.waiting.get(key);if(error){cache.failed.add(key);request?.listeners.forEach(listener=>listener(''));}else{
   const url=URL.createObjectURL(blob);cache.urls.set(key,url);request?.listeners.forEach(listener=>listener(url));
   while(cache.urls.size>256){const oldest=cache.urls.keys().next().value!;if(cache.waiting.get(oldest)?.listeners.size){const value=cache.urls.get(oldest)!;cache.urls.delete(oldest);cache.urls.set(oldest,value);if([...cache.urls.keys()].every(item=>cache.waiting.get(item)?.listeners.size))break;}else{URL.revokeObjectURL(cache.urls.get(oldest)!);cache.urls.delete(oldest);cache.waiting.delete(oldest);}}
  }};
  for(const [key,request] of cache.waiting)worker.postMessage({key,url:request.url});
  return()=>{worker.terminate();cache.worker=null;for(const url of cache.urls.values())URL.revokeObjectURL(url);cache.urls.clear();cache.waiting.clear();cache.failed.clear();};
 },[cache]);
 return cache;
}
export function StudioThumbnail({asset,directory,cache}:{asset:{id:string,path:string,sha256?:string},directory:string,cache:ThumbnailCache}){
 const [url,setUrl]=useState(''),key=directory+'/'+(asset.sha256||asset.path),source=media(directory+'/'+asset.path);
 useEffect(()=>{
  if(/\.svg$/i.test(asset.path)){setUrl(source);return;}
  const cached=cache.urls.get(key);let request=cache.waiting.get(key);
  if(!request){request={url:source,listeners:new Set()};cache.waiting.set(key,request);if(!cached&&!cache.failed.has(key))cache.worker?.postMessage({key,url:source});}
  request.listeners.add(setUrl);setUrl(cached||'');
  return()=>{request!.listeners.delete(setUrl);};
 },[cache,key,source]);
 return url?<img src={url} alt=""/>:<Image size={24}/>;
}
