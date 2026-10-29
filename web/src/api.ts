export let csrf='';
export function setCsrf(value:string){csrf=value;}
export type Note={path:string,root?:string,text:string,etag:string,metadata:Record<string,any>};
export type Config={root:string|null,revision?:string,include_roots:string[],exclude_roots:string[],rules_roots:string[],wiki_roots:string[],estimation_roots:string[],write_targets:Record<string,string>,homepage:string,templates:string,daily_folder:string,port:number};
export type OpenNote=(path:string,anchor?:string)=>void;
export type Session={config:Config,csrf:string,suggested_root:string,service_instance_id:string,catalog_version:number,demo?:boolean};
export type Change={type?:string,root?:string,config_revision?:string,service_instance_id?:string,catalog_version?:number,paths?:string[],reset?:boolean,design_transforms?:{directory:string,board_id:string,transforms:Record<string,any>}};
type Cached={value:any,etag?:string,bytes:number,valid:boolean};
type Pending={promise:Promise<any>,controller:AbortController,users:number,settled:boolean};
const cache=new Map<string,Cached>(),requests=new Map<string,Pending>(),versions=new Map<string,number>();
let scope='',bytes=0;
let resourceVersion=0;
const resources=new Map<string,number>();
export function applySession(session:Session){
 const next=JSON.stringify([session.service_instance_id,session.config.root,session.config.revision]);setCsrf(session.csrf);
 if(next===scope)return false;
 scope=next;cache.clear();bytes=0;versions.clear();
 resourceVersion++;
 resources.clear();
 for(const request of requests.values())request.controller.abort();requests.clear();return true;
}
export function affected(path:string,change:Change){
 if(change.reset||change.type==='reset'||change.type==='config'||!change.paths?.length)return true;
 const url=new URL(path,'http://local/'),target=url.searchParams.get('path')||'';
 if(url.pathname==='/file')return change.paths.some(p=>target===p||target.startsWith(p+'/'));
 if(url.pathname==='/tree')return change.paths.some(p=>p===target||p.slice(0,p.lastIndexOf('/')<0?0:p.lastIndexOf('/'))===target||target.startsWith(p+'/'));
 return true;
}
export function invalidate(change:Change={reset:true}){
 resourceVersion++;
 for(const path of resources.keys())if(affected('file?path='+encodeURIComponent(path),change))resources.set(path,resourceVersion);
 for(const [key,value] of cache)if(affected(key.slice(key.indexOf('\n')+1),change)){value.valid=false;versions.set(key,(versions.get(key)||0)+1);}
 for(const key of requests.keys())if(affected(key.slice(key.indexOf('\n')+1).split('\n')[0],change))versions.set(key.slice(0,key.lastIndexOf('\n')),(versions.get(key.slice(0,key.lastIndexOf('\n')))||0)+1);
 window.dispatchEvent(new CustomEvent('vault-data-changed',{detail:change}));
}
function remember(key:string,value:Cached){
 const previous=cache.get(key);if(previous)bytes-=previous.bytes;
 cache.delete(key);cache.set(key,value);bytes+=value.bytes;
 while(cache.size>64||bytes>32*1024*1024){const first=cache.keys().next().value!;bytes-=cache.get(first)!.bytes;cache.delete(first);}
}
function aborted(){return new DOMException("请求已取消",'AbortError');}
function consume<T>(entry:Pending,signal?:AbortSignal):Promise<T>{
 entry.users++;
 return new Promise((resolve,reject)=>{
  let done=false;
  const finish=(fn:(value:any)=>void,value:any)=>{if(done)return;done=true;signal?.removeEventListener('abort',cancel);entry.users--;if(!entry.users&&!entry.settled)entry.controller.abort();fn(value);};
  const cancel=()=>finish(reject,aborted());signal?.addEventListener('abort',cancel,{once:true});
  if(signal?.aborted){cancel();return;}entry.promise.then(value=>finish(resolve,value),error=>finish(reject,error));
 });
}
export async function api<T=any>(path:string,body?:any,method?:string,options:{signal?:AbortSignal,force?:boolean}={}):Promise<T>{
 if(options.signal?.aborted)throw aborted();
 const verb=method||(body===undefined?'GET':'POST'),readable=(verb==='GET'&&!path.startsWith('ai/')&&!/^(session|status|bootstrap|records|preferences|mcp-access|feishu)(\?|$)/.test(path))||(verb==='POST'&&path==='query');
 const databaseQuery=verb==='POST'&&path==='bases/query';
 const resource=path+(verb==='POST'&&(path==='query'||databaseQuery)?'?query='+encodeURIComponent(JSON.stringify(body)):'');
 const key=scope+'\n'+resource,previous=cache.get(key);
 if(readable&&previous?.valid&&!options.force){cache.delete(key);cache.set(key,previous);return previous.value;}
 const generation=versions.get(key)||0,requestKey=key+'\n'+generation;
 if(verb==='GET'||readable||databaseQuery){const pending=requests.get(requestKey);if(pending&&!pending.controller.signal.aborted)return consume<T>(pending,options.signal);}
 const controller=new AbortController();
 const work=async()=>{
  const headers:Record<string,string>={'Content-Type':'application/json','X-Vault-CSRF':csrf};
  if(readable&&previous?.etag)headers['If-None-Match']=previous.etag;
  const fetchRead=()=>fetch('/api/'+path,{method:verb,headers,body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal});
  let response:Response;
  try{response=await fetchRead();}catch(error){if(verb!=='GET'||controller.signal.aborted)throw error;response=await fetchRead();}
  if(response.status===304&&!previous){delete headers['If-None-Match'];response=await fetch('/api/'+path,{headers,signal:controller.signal});}
  let data=response.status===304?previous!.value:await response.json();
  if(verb==='GET'&&response.status===503&&!data.pending){await new Promise(resolve=>setTimeout(resolve,150));response=await fetchRead();data=await response.json();}
  const pendingUntil=Date.now()+60000;
  while(response.status===503&&data.pending&&Date.now()<pendingUntil){
   await new Promise<void>((resolve,reject)=>{
    const cancel=()=>{clearTimeout(timer);reject(aborted());};
    const delay=Math.max(25,Math.min(1000,Number(data.retry_after_ms)||600));
    const timer=setTimeout(()=>{controller.signal.removeEventListener('abort',cancel);resolve();},delay);
    if(controller.signal.aborted){cancel();return;}controller.signal.addEventListener('abort',cancel,{once:true});
   });
   response=await fetchRead();data=await response.json();
  }
  if(!response.ok&&response.status!==304)throw Object.assign(new Error(data.error||(response.status===404&&path==='trash/clear'?"当前后台服务尚未加载清空功能，请重启服务后重试":typeof data.detail==='string'?data.detail:"操作未完成")),{conflict:response.status===409,status:response.status});
  if(readable&&scope+'\n'+resource===key&&(versions.get(key)||0)===generation)remember(key,{value:data,etag:response.headers.get('ETag')||previous?.etag,bytes:typeof data.text==='string'?data.text.length*2+512:JSON.stringify(data).length*2,valid:true});
  if(verb!=='GET'&&verb!=='HEAD'&&!data.dry_run&&data.changed!==false&&!path.startsWith('ai/')&&!path.startsWith('html-')&&!path.startsWith('feishu')&&!['activity','preferences','demo','query','knowledge-search','bases/query','html-preview','choose-directory','model-directory/open','model-prepare','reindex','skills/wiki-search/install'].includes(path)){
   const recordOnly=path==='bases/commands'&&body?.command?.type?.startsWith('record.')&&body.command.type!=='record.move';
   invalidate({type:'write',paths:(recordOnly?[body.command.type==='record.update'||body.command.type==='record.trash'?body.command.path:undefined,data.path]:[body?.path,body?.source,body?.destination,data.path,...(path==='bases/commands'&&body?.command?.type==='board.group.remove'?(body.command.records||[]).map((record:{path:string})=>record.path):[])]).filter(Boolean)});
  }
  return data;
 };
 const entry:Pending={controller,users:0,settled:false,promise:Promise.resolve()};
 entry.promise=work().finally(()=>{entry.settled=true;if(requests.get(requestKey)===entry)requests.delete(requestKey);});
 if(verb==='GET'||readable||databaseQuery)requests.set(requestKey,entry);return consume<T>(entry,options.signal);
}
export const media=(path:string,download=false,root?:string)=>{if(!resources.has(path))resources.set(path,resourceVersion);return '/api/media?path='+encodeURIComponent(path)+'&v='+resources.get(path)+(download?'&download=true':'')+(root?'&root='+encodeURIComponent(root):'');};
