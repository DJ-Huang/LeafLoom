export let csrf='';
export function setCsrf(value:string){csrf=value;}
export async function api<T=any>(path:string,body?:any,method?:string):Promise<T>{
 const response=await fetch('/api/'+path,{method:method||(body===undefined?'GET':'POST'),headers:{'Content-Type':'application/json','X-Vault-CSRF':csrf},body:body===undefined?undefined:JSON.stringify(body)});
 const data=await response.json();if(!response.ok)throw Object.assign(new Error(data.error||'操作未完成'),{conflict:response.status===409});return data;
}
export const media=(path:string,download=false)=>'/api/media?path='+encodeURIComponent(path)+(download?'&download=true':'');
export type Note={path:string,root?:string,text:string,etag:string,metadata:Record<string,any>};
export type Config={root:string|null,include_roots:string[],exclude_roots:string[],rules_roots:string[],wiki_roots:string[],estimation_roots:string[],write_targets:Record<string,string>,homepage:string,templates:string,daily_folder:string,port:number};
export type OpenNote=(path:string,anchor?:string)=>void;
