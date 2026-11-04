import React from 'react';
import {AlignLeft,Calendar,CheckSquare,ChevronDown,FileText,Hash,Image,LayoutGrid,Link,Link2,List,Paperclip,Table2,Tags,Text,Clock3,GitCommitHorizontal,Columns3} from 'lucide-react';
import {Field,View,labelOf} from './database-model';
import {t} from './i18n';
export const viewIcons={table:Table2,list:List,cards:LayoutGrid,leafloomTimeline:GitCommitHorizontal,Columns3};
export function ViewIcon({type,size=15}:{type:string,size?:number}){const Icon=viewIcons[type as keyof typeof viewIcons]||Table2;return <Icon size={size} strokeWidth={1.65} aria-hidden="true"/>;}
export function FieldIcon({field,fieldKey,size=15}:{field?:Field,fieldKey?:string,size?:number}){
 const Icon=fieldKey==='title'?Text:fieldKey?.startsWith('file.')?Clock3:({text:AlignLeft,number:Hash,date:Calendar,checkbox:CheckSquare,url:Link,select:ChevronDown,multiselect:Tags,attachment:Paperclip}[field?.type||'text']||AlignLeft);
 return <Icon size={size} strokeWidth={1.65} aria-hidden="true"/>;
}
export const optionLabel=(value:string,field?:Field)=>field?.optionMeta?.[value]?.label||(field?.optionMeta?.[value]?.labelKey?t(field.optionMeta[value].labelKey!):value);
export function Tag({value,field}:{value:string,field?:Field}){let hash=0;for(const c of value)hash=(hash*31+c.charCodeAt(0))>>>0;const color=field?.optionMeta?.[value]?.color;return <span className={'db-tag '+(color?'db-tag-color-'+color:'db-tag-'+hash%6)}>{optionLabel(value,field)}</span>;}
export function FieldLabel({fieldKey,field}:{fieldKey:string,field?:Field}){return <><FieldIcon fieldKey={fieldKey} field={field}/><span>{t(labelOf(fieldKey,field))}</span></>;}
export {FileText,Image,Link2};

export function RecentBadge({row}:{row:{recent?:boolean}}){return row.recent?<span className="db-created-badge">{t('db.justCreated')}</span>:null;}
