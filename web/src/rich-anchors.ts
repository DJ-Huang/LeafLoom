import {Plugin,PluginKey} from '@tiptap/pm/state';
import type {Editor} from '@tiptap/core';
export type RichRange={from:number,to:number};
export const richAnchorKey=new PluginKey<ReadonlyMap<string,RichRange>>('leafloom-anchors');
export const richAnchorPlugin=()=>new Plugin({
 key:richAnchorKey,
 state:{
  init:()=>new Map<string,RichRange>(),
  apply(tr,current){
   const next=new Map<string,RichRange>();
   for(const [id,value] of current){
    let {from,to}=value,removed=false;
    for(const map of tr.mapping.maps){
     map.forEach((start,end)=>{if(end>start&&(from===to?start<=from&&end>=from:start<to&&end>from))removed=true;if(start===end&&from<start&&start<to)removed=true;});
     from=map.map(from,1);to=map.map(to,value.from===value.to?1:-1);
    }
    if(!removed)next.set(id,{from,to});
   }
   const meta=tr.getMeta(richAnchorKey);if(meta?.add)next.set(meta.add.id,meta.add.range);if(meta?.remove)next.delete(meta.remove);if(meta?.clear)next.clear();
   return next;
  }
 }
});
export function trackRichRange(editor:Editor,range:RichRange=editor.state.selection){const id=crypto.randomUUID();editor.view.dispatch(editor.state.tr.setMeta(richAnchorKey,{add:{id,range:{from:range.from,to:range.to}}}));return id;}
export const trackedRichRange=(editor:Editor,id:string)=>richAnchorKey.getState(editor.state)?.get(id);
export function releaseRichRange(editor:Editor,id:string){if(!editor.isDestroyed)editor.view.dispatch(editor.state.tr.setMeta(richAnchorKey,{remove:id}));}
