/** Source-file-relative comments. Offsets are UTF-16, like browser editor offsets. */
export type AnnotationColor='yellow'|'green'|'blue'|'pink'|'purple';
export type AnnotationKind='highlight'|'comment';
export type AnnotationAction=AnnotationKind|'clear-highlight';
export type AnnotationAnchor={from:number,to:number,exact:string,prefix:string,suffix:string,etag:string};
export type AnnotationMessage={
 id:string;annotation_id:string;parent_id:string|null;author:string;content:string;
 created_at:number;updated_at:number;revision:number;
};
export type Annotation={
 id:string;document_id:string;type:AnnotationKind;anchor:AnnotationAnchor|null;
 color:AnnotationColor;status:'open'|'resolved';revision:number;
 created_at:number;updated_at:number;messages:AnnotationMessage[];
};
export type AnnotationSelection={from:number,to:number};
export const annotationColors:AnnotationColor[]=['yellow','green','blue','pink','purple'];

export function selectedHighlights(source:string,annotations:Annotation[],selection:AnnotationSelection){
 if(selection.from>=selection.to)return [];
 return annotations.flatMap(item=>{
  const range=item.type==='highlight'?resolveAnchor(source,item.anchor):null;
  return range&&range.from<selection.to&&range.to>selection.from?[{id:item.id,revision:item.revision,...range}]:[];
 });
}

export function makeAnchor(source:string,range:AnnotationSelection,etag:string):AnnotationAnchor|null{
 const from=Math.max(0,Math.min(source.length,range.from));
 const to=Math.max(from,Math.min(source.length,range.to));
 if(from===to||to-from>12000)return null;
 return {from,to,exact:source.slice(from,to),prefix:source.slice(Math.max(0,from-48),from),
  suffix:source.slice(to,to+48),etag};
}

/** Do not silently attach a comment to the wrong repeated quote after an external edit. */
export function resolveAnchor(source:string,anchor:AnnotationAnchor|null):AnnotationSelection|null{
 if(!anchor)return null;
 const {from,to,exact,prefix,suffix}=anchor;
 if(!exact||exact.length>12000||source.length<exact.length)return null;
 const candidates:{from:number,to:number,score:number,context:number}[]=[];
 let at=-1;
 while((at=source.indexOf(exact,at+1))!==-1){
  const before=source.slice(Math.max(0,at-prefix.length),at),after=source.slice(at+exact.length,at+exact.length+suffix.length);
  let p=0,q=0;
  while(p<before.length&&p<prefix.length&&before[before.length-p-1]===prefix[prefix.length-p-1])p++;
  while(q<after.length&&q<suffix.length&&after[q]===suffix[q])q++;
  // Strong context beats raw offset if text is inserted before an annotated selection.
  const score=(p+q)*3-Math.min(48,Math.abs(at-from)/100);
  candidates.push({from:at,to:at+exact.length,score,context:p+q});
  if(candidates.length>1000)return null; // pathological repetition, never guess.
 }
 if(!candidates.length)return null;
 if(candidates.length===1){
  const match=candidates[0],contextLength=prefix.length+suffix.length;
  // A matching phrase at an unrelated position is not proof it is the original passage.
  if(match.from!==from&&(contextLength<4||match.context<Math.min(4,contextLength)))return null;
  return {from:match.from,to:match.to};
 }
 candidates.sort((a,b)=>b.score-a.score);
 if(candidates[0].context<4||candidates[0].score-candidates[1].score<6)return null;
 return {from:candidates[0].from,to:candidates[0].to};
}
