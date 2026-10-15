// History belongs to the Markdown document, not to either editor's DOM/state.
export type TextSelection={from:number,to:number};
export type EditMeta={kind?:'typing'|'command'|'source'|'external',group?:string,before?:TextSelection,after?:TextSelection};
export type TextChange={from:number,to:number,insert:string};
type Step={forward:TextChange,backward:TextChange};
type Entry={steps:Step[],kind:string,group?:string,time:number,before:TextSelection,after:TextSelection};
export type EditHistory={undo:Entry[],redo:Entry[],bookmark?:TextSelection,replaying:boolean,sealed:boolean,bytes:number};
export const createEditHistory=():EditHistory=>({undo:[],redo:[],replaying:false,sealed:false,bytes:0});
export function textChange(before:string,after:string):TextChange|null{
 if(before===after)return null;
 let from=0,end=before.length,nextEnd=after.length;
 while(from<end&&from<nextEnd&&before[from]===after[from])from++;
 // Keep a UTF-16 surrogate pair in the same edit.
 if(from>0&&/[\uD800-\uDBFF]/.test(before[from-1]))from--;
 while(end>from&&nextEnd>from&&before[end-1]===after[nextEnd-1]){end--;nextEnd--;}
 if(end<before.length&&/[\uDC00-\uDFFF]/.test(before[end])){end++;nextEnd++;}
 return {from,to:end,insert:after.slice(from,nextEnd)};
}
export const applyTextChange=(text:string,change:TextChange)=>text.slice(0,change.from)+change.insert+text.slice(change.to);
export function recordEdit(history:EditHistory,before:string,after:string,meta:EditMeta={}){
 const forward=textChange(before,after);if(!forward||history.replaying)return;
 const time=Date.now(),kind=meta.kind||'command',last=history.undo.at(-1);
 const backward={from:forward.from,to:forward.from+forward.insert.length,insert:before.slice(forward.from,forward.to)};
 const start=meta.before||{from:forward.from,to:forward.to},end=meta.after||{from:backward.to,to:backward.to};
 const sameComposition=!!meta.group&&last?.group===meta.group;
 const typing=!meta.group&&!last?.group&&(kind==='typing'||kind==='source')&&last?.kind===kind&&time-last.time<800&&last.after.from===start.from&&last.after.to===start.to;
 if(last&&!history.sealed&&(sameComposition||typing)){last.steps.push({forward,backward});last.after=end;last.time=time;}
 else history.undo.push({steps:[{forward,backward}],kind,group:meta.group,time,before:start,after:end});
 history.bytes-=history.redo.reduce((n,entry)=>n+entry.steps.reduce((m,step)=>m+(step.forward.insert.length+step.backward.insert.length)*2,0),0);
 history.redo=[];history.sealed=false;history.bookmark=end;history.bytes+=(forward.insert.length+backward.insert.length)*2;
 // A long open document must not retain an unbounded second copy of its text.
 while(history.undo.length>200||history.bytes>8*1024*1024&&history.undo.length>1){
  const removed=history.undo.shift()!;history.bytes-=removed.steps.reduce((n,s)=>n+(s.forward.insert.length+s.backward.insert.length)*2,0);
 }
}
export function historyText(history:EditHistory,text:string,direction:'undo'|'redo'){
 const entry=history[direction].pop();if(!entry)return null;
 const steps=direction==='undo'?[...entry.steps].reverse():entry.steps;
 for(const step of steps)text=applyTextChange(text,direction==='undo'?step.backward:step.forward);
 history[direction==='undo'?'redo':'undo'].push(entry);
 history.bookmark=direction==='undo'?entry.before:entry.after;
 history.sealed=true;
 return {text,selection:history.bookmark};
}
