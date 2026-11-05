import {ClipboardCopy,Image as ImageIcon} from 'lucide-react';
import {t,useLocale} from './i18n';
import {Panel} from './design-controls';
import {DesignImageSource} from './design-image-source';
export type ImageCopyState={status:'idle'|'copying'|'copied'|'failed',error?:string};
export function DesignImageCard({source,url,state,onCopy}:{source:DesignImageSource,url?:string,state:ImageCopyState,onCopy:()=>void}){
 useLocale();
 return <Panel title={t('design.imageSourceTitle')}>
  <div className="dw-image-source" data-testid="studio-image-source">
   <div className="dw-image-source-file">{url?<img key={url} src={url} alt="" onError={event=>{event.currentTarget.style.visibility='hidden';}}/>:<ImageIcon size={28}/>}<div><strong>{source.name||t('design.imageSourceTitle')}</strong>{source.path&&<small title={source.path}>{source.path}</small>}</div></div>
   {source.staticCopy&&<p className="dw-hint">{t('design.imageStaticCopy')}</p>}
   {source.error?<p className="dw-hint" role="status">{t(source.error)}</p>:<>
    <button type="button" className="dw-copy-source-image" data-testid="studio-copy-source-image" onClick={onCopy} aria-busy={state.status==='copying'}><ClipboardCopy size={15}/>{t(state.status==='copying'?'design.imageCopying':state.status==='failed'?'design.imageCopyRetry':'design.copySourceImage')}</button>
    <p className={'dw-hint'+(state.status==='failed'?' error':'')} role="status" aria-live="polite">{state.status==='failed'?state.error:state.status==='copied'?t('design.imageCopied'):t('design.imageOriginalHelp')}</p>
   </>}
  </div>
 </Panel>;
}
