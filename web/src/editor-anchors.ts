import {StateEffect,StateField} from '@codemirror/state';
import {EditorView} from '@codemirror/view';
import type {InsertRange} from './editor-commands';

export const addAnchor=StateEffect.define<{id:string,range:InsertRange}>();
export const removeAnchor=StateEffect.define<string>();
// Pending UI actions keep their location in the document, not in a stale closure.
export const pendingAnchors=StateField.define<ReadonlyMap<string,InsertRange>>({
 create:()=>new Map(),
 update(value,tr){
  const next=new Map<string,InsertRange>();
  for(const [id,range] of value){
   let removed=false;
   tr.changes.iterChanges((from,to)=>{
    if(to>from && (range.from===range.to?from<=range.from&&to>=range.to:from<range.to&&to>range.from))removed=true;
    if(from===to && range.from<from&&from<range.to)removed=true;
   });
   if(!removed)next.set(id,{from:tr.changes.mapPos(range.from,1),to:tr.changes.mapPos(range.to,range.from===range.to?1:-1)});
  }
  for(const effect of tr.effects){
   if(effect.is(addAnchor))next.set(effect.value.id,effect.value.range);
   if(effect.is(removeAnchor))next.delete(effect.value);
  }
  return next;
 }
});
export function trackRange(view:EditorView,range:InsertRange){
 const id=crypto.randomUUID();view.dispatch({effects:addAnchor.of({id,range})});return id;
}
export const trackedRange=(view:EditorView,id:string)=>view.state.field(pendingAnchors,false)?.get(id);
