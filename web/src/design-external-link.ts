type RuntimeSession = {id:string,origin:string};

// Only public web links leave the isolated design. Keep project navigation,
// downloads and system/file protocols inside their existing boundaries.
export function designExternalUrl(value:unknown):string|null {
 if(typeof value!=='string'||value.length>8192)return null;
 try {
  const url=new URL(value),host=url.hostname.replace(/\.$/,'').toLowerCase();
  if(!['http:','https:'].includes(url.protocol)||url.username||url.password)return null;
  if(host==='localhost'||host.endsWith('.localhost')||host.endsWith('.local')||host.startsWith('[')||!host.includes('.')||/^(0|10|127)\.|^192\.168\.|^169\.254\.|^172\.(1[6-9]|2\d|3[01])\./.test(host))return null;
  return url.href;
 }catch{return null;}
}

export function openDesignExternalLink(event:MessageEvent,source:Window|null|undefined,session:RuntimeSession,enabled:boolean,onError:(message:string)=>void,open?:(url:string)=>unknown):boolean {
 if(!enabled||!source||event.source!==source||event.origin!==session.origin||event.data?.session!==session.id||event.data?.type!=='studio-open-external'||!window.navigator.userActivation?.isActive)return false;
 const url=designExternalUrl(event.data.url);if(!url)return false;
 try {
  const result=open?open(url):window.leafloomDesktop?window.leafloomDesktop.openExternal(url):window.open(url,'_blank','noopener,noreferrer');
  void Promise.resolve(result).catch(error=>onError(String(error instanceof Error?error.message:error)));
 }catch(error){onError(String(error instanceof Error?error.message:error));}
 return true;
}
