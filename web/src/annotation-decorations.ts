import {Extension} from '@tiptap/core';
import {Plugin} from '@tiptap/pm/state';
import {Decoration,DecorationSet} from '@tiptap/pm/view';
import {Range} from '@codemirror/state';
import {Decoration as CmDecoration,EditorView as CmEditorView} from '@codemirror/view';
import type {MarkdownBridge} from './rich-markdown';
import {editorOffset} from './source-offsets';
import {Annotation,resolveAnchor} from './annotations';

export type AnnotationDisplay={source:string,annotations:Annotation[]};
const classes=(item:Annotation)=>'leafloom-annotation leafloom-'+item.type+' leafloom-'+item.color+
 (item.status==='resolved'?' leafloom-resolved':'');

/** Decorations never enter Tiptap document JSON or the Markdown serializer. */
export function richAnnotationExtension(
 get:()=>AnnotationDisplay,bridge:()=>MarkdownBridge|undefined,onOpen:(id:string)=>void
){
 const compute=(doc:import('@tiptap/pm/model').Node)=>{
  const current=bridge();if(!current)return DecorationSet.empty;
  const {source,annotations}=get(),marks:Decoration[]=[];
  for(const item of annotations){
   const range=resolveAnchor(source,item.anchor);
   if(!range)continue;
   const start=current.toEditor(doc,range.from),end=current.toEditor(doc,range.to);
   if(start>=end)continue;
   doc.nodesBetween(start,end,(node,pos)=>{
    if(!node.isTextblock)return true;
    const from=Math.max(start,pos+1),to=Math.min(end,pos+1+node.content.size);
    if(from<to)marks.push(Decoration.inline(from,to,{
     class:classes(item),'data-leafloom-annotation':item.id,
     title:item.type==='comment'?'查看评论':'查看标注'
    }));
    return false;
   });
  }
  return DecorationSet.create(doc,marks);
 };
 return Extension.create({name:'leafloomAnnotationLayer',addProseMirrorPlugins(){
  let plugin:Plugin<DecorationSet>;
  plugin=new Plugin<DecorationSet>({
   state:{
    init:(_,state)=>compute(state.doc),
    apply:(tr,previous,_old,next)=>tr.getMeta('leafloomAnnotationRefresh')?
      compute(next.doc):tr.docChanged?previous.map(tr.mapping,next.doc):previous
   },
   props:{
    decorations(state){return plugin.getState(state)||DecorationSet.empty;},
    handleClick(_view,_pos,event){
     const target=event.target instanceof Element?event.target:null;
     const hit=target?.closest<HTMLElement>('[data-leafloom-annotation]');
     if(hit?.dataset.leafloomAnnotation){onOpen(hit.dataset.leafloomAnnotation);return false;}
     return false;
    }
   }
  });
  return [plugin];
 }});
}

/** Source mode positions use source-offsets for CRLF and UTF-16 consistency. */
export function sourceAnnotationExtensions(get:()=>AnnotationDisplay,onOpen:(id:string)=>void){
 return [
  CmEditorView.decorations.compute(['doc'],state=>{
   const {source,annotations}=get(),ranges:Range<CmDecoration>[]=[],length=state.doc.length;
   for(const item of annotations){
    const range=resolveAnchor(source,item.anchor);
    if(!range)continue;
    const from=Math.min(length,editorOffset(source,range.from));
    const to=Math.min(length,editorOffset(source,range.to));
    if(from<to)ranges.push(CmDecoration.mark({class:classes(item),attributes:{
      'data-leafloom-annotation':item.id
    }}).range(from,to));
   }
   return CmDecoration.set(ranges,true);
  }),
  CmEditorView.domEventHandlers({click(event){
   const node=event.target instanceof Element?event.target.closest<HTMLElement>('[data-leafloom-annotation]'):null;
   if(node?.dataset.leafloomAnnotation)onOpen(node.dataset.leafloomAnnotation);
   return false;
  }})
 ];
}
