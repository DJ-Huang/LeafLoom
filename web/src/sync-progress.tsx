import React from 'react';
import {getLocale,t} from './i18n';
import './sync-progress.css';

export function SyncProgress({status}:{status:any}) {
 if(status?.model?.loading)return <div className="index-progress"><div className="index-progress-track" role="progressbar" aria-label={t('正在加载检索模型')}><span/></div><p>{t('首次语义检索正在加载模型，阅读与编辑不受影响。')}</p></div>;
 const warming=status?.model?.warming||status?.sync?.state==='正在预热检索';
 if(warming)return <div className="index-progress"><div className="index-progress-track" role="progressbar" aria-label={t('正在预热检索')} aria-valuetext={t('正在预热检索')}><span/></div><p>{t('正在准备首次检索，可能需要一些时间。阅读与编辑不受影响。')}</p></div>;
 const total=Number(status?.sync?.total);
 if(!Number.isFinite(total)||total<=0)return null;
 const raw=Number(status?.sync?.completed);
 const completed=Math.max(0,Math.min(Number.isFinite(raw)?raw:0,total));
 const percent=Math.floor(completed/total*100);
 return <div className="index-progress"><div className="index-progress-row"><progress aria-label={t('索引同步进度')} max={total} value={completed}/><span>{percent}% · {completed.toLocaleString(getLocale())} / {total.toLocaleString(getLocale())}</span></div></div>;
}
