import {api} from './api';

export type DesktopBridge={
 chooseDirectory:()=>Promise<{path?:string,cancelled?:boolean}>;
 getAutostart:()=>Promise<boolean>;
 setAutostart:(enabled:boolean)=>Promise<boolean>;
 onBeforeQuit:(callback:()=>Promise<boolean>)=>()=>void;
};
declare global{interface Window{vaultDesktop?:DesktopBridge}}
export const chooseDirectory=()=>window.vaultDesktop?window.vaultDesktop.chooseDirectory():api<{path?:string,cancelled?:boolean}>('choose-directory',{});
const blockers=new Set<()=>boolean>();
export function registerQuitBlocker(blocker:()=>boolean){blockers.add(blocker);return()=>{blockers.delete(blocker);};}
export function installQuitHandler(){
 return window.vaultDesktop?.onBeforeQuit(async()=>{
  if([...blockers].some(blocker=>blocker()))return false;
  const {flushDocuments}=await import('./document-state');
  return flushDocuments();
 });
}
