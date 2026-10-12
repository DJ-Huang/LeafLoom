import {useCallback,useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {api,affected,Change} from './api';
export function useApi(path:string,deps:any[]=[],enabled=true){
 const [data,setData]=useState<any>(),[error,setError]=useState('');
 const lifecycle=useRef<AbortController|undefined>(undefined),sequence=useRef(0);
 const refresh=useCallback(async()=>{const controller=lifecycle.current,current=++sequence.current;try{const value=await api(path,undefined,undefined,{force:true,signal:controller?.signal});if(!controller?.signal.aborted&&current===sequence.current){setData(value);setError('');}}catch(error){if((error as Error).name!=='AbortError'&&current===sequence.current)setError((error as Error).message);}},[path]);
 useEffect(()=>{
  if(!enabled)return;const controller=new AbortController();lifecycle.current=controller;let alive=true;
  const load=(force=false)=>{const current=++sequence.current;return api(path,undefined,undefined,{signal:controller.signal,force}).then(value=>{if(alive&&current===sequence.current){setData(value);setError('');}}).catch(e=>{if(alive&&current===sequence.current&&e.name!=='AbortError')setError(e.message);});};
  const changed=(event:Event)=>{if(affected(path,(event as CustomEvent<Change>).detail))void load(true);};
  void load();window.addEventListener('vault-data-changed',changed);
  return()=>{alive=false;sequence.current++;controller.abort();window.removeEventListener('vault-data-changed',changed);};
 },[path,enabled,...deps]);return {data,error,refresh};
}
let status:any;
const listeners=new Set<()=>void>();
export function updateStatus(value:any){status=value;for(const fn of listeners)fn();}
export function useStatus(){return useSyncExternalStore(fn=>{listeners.add(fn);return()=>{listeners.delete(fn);};},()=>status);}
