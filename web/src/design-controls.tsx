import React, {useEffect, useRef, useState} from 'react';
import {RotateCcw} from 'lucide-react';
import {t} from './i18n';

/** Mixed is deliberately distinct from an unset value. Blurring it never writes a value. */
export const MIXED = Symbol('mixed');
export type InspectorValue = string | number | boolean | undefined | null | typeof MIXED;
export function commonValue<T>(items:T[], read:(item:T)=>any):any {
  if (!items.length) return undefined;
  const first = read(items[0]);
  return items.every(item => read(item) === first || (typeof read(item)!=='symbol' && typeof first!=='symbol' && JSON.stringify(read(item)) === JSON.stringify(first))) ? first : MIXED;
}

export function Field({label,value,onCommit,type='text',min,max,step,testId,placeholder,disabled=false}:{label:string,value:any,onCommit:(value:any)=>void,type?:string,min?:number,max?:number,step?:number|string,testId?:string,placeholder?:string,disabled?:boolean}) {
  const mixed = value === MIXED, initial = mixed || value == null ? '' : String(value);
  const [draft,setDraft] = useState(initial), [invalid,setInvalid] = useState(false);
  const dirty = useRef(false);
  useEffect(() => {setDraft(initial);setInvalid(false);dirty.current=false;}, [initial,mixed]);
  const apply = () => {
    if (!dirty.current) return;
    if (type === 'number') {
      if (!draft.trim()) {setDraft(initial);dirty.current=false;setInvalid(false);return;}
      const number = Number(draft);
      if (!Number.isFinite(number) || (min != null && number < min) || (max != null && number > max)) {setInvalid(true);return;}
      if (mixed || number !== Number(value)) onCommit(number);
    } else if (mixed || draft !== initial) onCommit(draft);
    dirty.current=false;setInvalid(false);
  };
  return <label className={'dw-field'+(mixed?' is-mixed':'')}><span>{label}</span><input aria-label={label} data-testid={testId} aria-invalid={invalid || undefined} type={type} value={draft} min={min} max={max} step={step} disabled={disabled} placeholder={mixed?t('混合值'):placeholder} onChange={event=>{dirty.current=true;setDraft(event.target.value);setInvalid(false);}} onBlur={apply} onKeyDown={event=>{if(event.key==='Enter')event.currentTarget.blur();if(event.key==='Escape'){dirty.current=false;setDraft(initial);setInvalid(false);event.currentTarget.blur();}}}/>{invalid&&<small className="dw-field-error">{t('请输入范围内的有效数值')}</small>}</label>;
}

export function TextField({label,value,onCommit,rows=3,testId}:{label:string,value:any,onCommit:(value:string)=>void,rows?:number,testId?:string}) {
  const initial = value === MIXED ? '' : String(value??'');
  const [draft,setDraft] = useState(initial),dirty = useRef(false);
  useEffect(()=>{setDraft(initial);dirty.current=false;},[initial,value===MIXED]);
  return <label className={'dw-field'+(value===MIXED?' is-mixed':'')}><span>{label}</span><textarea aria-label={label} data-testid={testId} rows={rows} value={draft} placeholder={value===MIXED?t('混合值'):undefined} onChange={event=>{dirty.current=true;setDraft(event.target.value);}} onBlur={()=>{if(dirty.current&&(value===MIXED||draft!==initial))onCommit(draft);dirty.current=false;}} onKeyDown={event=>{if(event.key==='Escape'){dirty.current=false;setDraft(initial);event.currentTarget.blur();}}}/></label>;
}

export function SelectField({label,value,onCommit,options,testId}:{label:string,value:any,onCommit:(value:string)=>void,options:[string,string][],testId?:string}) {
  const current = value === MIXED ? '__mixed__' : String(value??'');
  return <label className={'dw-field'+(value===MIXED?' is-mixed':'')}><span>{label}</span><select aria-label={label} data-testid={testId} value={current} onChange={event=>onCommit(event.target.value)}>{value===MIXED&&<option value="__mixed__" disabled>{t('混合值')}</option>}{value!==MIXED&&!options.some(([key])=>key===current)&&<option value={current}>{current||t('继承')}</option>}{options.map(([key,text])=><option key={key} value={key}>{text}</option>)}</select></label>;
}

export function CheckField({label,value,onCommit,testId}:{label:string,value:any,onCommit:(value:boolean)=>void,testId?:string}) {
  const input=useRef<HTMLInputElement>(null);
  useEffect(()=>{if(input.current)input.current.indeterminate=value===MIXED;},[value]);
  return <label className="dw-check"><input ref={input} type="checkbox" data-testid={testId} aria-label={label} checked={value===MIXED?false:!!value} onChange={event=>onCommit(event.target.checked)}/>{label}{value===MIXED&&<small>{t('混合值')}</small>}</label>;
}

export function ColorField({label,value,onCommit,testId}:{label:string,value:any,onCommit:(value:string)=>void,testId?:string}) {
  const color = typeof value==='string'&&/^#[\da-f]{6}$/i.test(value)?value:typeof value==='string'&&/^#[\da-f]{3}$/i.test(value)?'#'+value.slice(1).split('').map(char=>char+char).join(''):'#808080';
  const [draft,setDraft]=useState(color),changed=useRef(false);
  useEffect(()=>{setDraft(color);changed.current=false;},[color]);
  return <div className="dw-color-field"><label className={'dw-color-swatch'+(value===MIXED?' is-mixed':'')} title={label} style={{background:value===MIXED?undefined:typeof value==='string'?value:undefined}}><input type="color" aria-label={label+' '+t('拾色器')} value={draft} onChange={event=>{changed.current=true;setDraft(event.target.value);}} onBlur={()=>{if(changed.current){onCommit(draft);changed.current=false;}}} onPointerUp={()=>{if(changed.current){onCommit(draft);changed.current=false;}}}/></label><Field label={label} value={value} onCommit={onCommit} testId={testId} placeholder={t('继承')}/></div>;
}

export function RangeField({label,value,onCommit,min=0,max=100,step=1,testId,suffix=''}:{label:string,value:any,onCommit:(value:number)=>void,min?:number,max?:number,step?:number,testId?:string,suffix?:string}) {
  const initial=value===MIXED?min:Number(value??min),[draft,setDraft]=useState(initial),dirty=useRef(false);
  useEffect(()=>{setDraft(initial);dirty.current=false;},[initial,value===MIXED]);
  const commit=()=>{if(dirty.current){onCommit(draft);dirty.current=false;}};
  return <label className="dw-range-field"><span>{label}<output>{value===MIXED&&!dirty.current?t('混合值'):Math.round(draft*100)/100+suffix}</output></span><input type="range" aria-label={label} data-testid={testId} min={min} max={max} step={step} value={draft} onChange={event=>{dirty.current=true;setDraft(Number(event.target.value));}} onPointerUp={commit} onKeyUp={commit} onBlur={commit}/></label>;
}

export function Panel({title,children,advanced=false,open=true,badge}:{title:string,children:React.ReactNode,advanced?:boolean,open?:boolean,badge?:React.ReactNode}) {
  return <details className={'dw-inspector-section dw-panel'+(advanced?' dw-advanced':'')} open={open||undefined}><summary><h4>{title}</h4>{badge&&<small>{badge}</small>}</summary><div className="dw-panel-content">{children}</div></details>;
}
export function ResetButton({label=t('恢复继承'),onClick,disabled=false,testId}:{label?:string,onClick:()=>void,disabled?:boolean,testId?:string}) {
  return <button type="button" className="dw-reset" title={label} aria-label={label} disabled={disabled} data-testid={testId} onClick={onClick}><RotateCcw size={12}/>{label}</button>;
}
