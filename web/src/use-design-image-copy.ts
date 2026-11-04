import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {media,Change} from './api';
import {t} from './i18n';
import {DesignImageSource} from './design-image-source';
import {ImageCopyState} from './design-image-card';
import {ImageCopyRequest,imagePng,writeClipboardImage} from './image-clipboard';

export function useDesignImageCopy(root:string,directory:string,notify:(message:string)=>void){
 const requests=useMemo(()=>new ImageCopyRequest(),[root,directory]),sequence=useRef(0);
 const [state,setState]=useState<ImageCopyState&{path?:string}>({status:'idle'});
 useEffect(()=>{
  const cancel=()=>{sequence.current++;requests.cancel();};
  const changed=(event:Event)=>{const change=(event as CustomEvent<Change>).detail;if(change.reset||change.type==='config'||change.root&&change.root!==root){cancel();setState({status:'idle'});}};
  window.addEventListener('vault-data-changed',changed);
  return()=>{cancel();window.removeEventListener('vault-data-changed',changed);};
 },[requests,root]);
 const copy=useCallback((source:DesignImageSource)=>{
  const id=++sequence.current;
  if(source.error||!source.path){requests.cancel();notify(t(source.error||'design.imageSourceMissing'));return;}
  setState({status:'copying',path:source.path});
  void requests.run(signal=>writeClipboardImage(imagePng(media(source.path!,false,root),signal),signal)).then(copied=>{
   if(copied&&sequence.current===id){setState({status:'copied',path:source.path});notify(t('design.imageCopied'));}
  }).catch(error=>{if(sequence.current===id){setState({status:'failed',path:source.path,error:(error as Error).message});notify((error as Error).message);}});
 },[requests,root,notify]);
 return {state,copy};
}
