import React from 'react';
import {createRoot,Root} from 'react-dom/client';
import {Range} from '@codemirror/state';
import {syntaxTree} from '@codemirror/language';
import {Decoration,EditorView,WidgetType} from '@codemirror/view';
import {OpenNote} from './api';
import {MarkdownPreview} from './reader';

class WikiLinkWidget extends WidgetType{
 constructor(readonly target:string,readonly label:string,readonly open:OpenNote){super();}
 eq(other:WikiLinkWidget){return other.target===this.target&&other.label===this.label;}
 toDOM(){const a=document.createElement('a');a.textContent=this.label;a.href='#';a.className='live-wikilink';a.onclick=e=>{e.preventDefault();e.stopPropagation();this.open(this.target);};return a;}
 ignoreEvent(){return true;}
}
class MarkdownWidget extends WidgetType{
 root?:Root;
 constructor(readonly text:string,readonly path:string,readonly open:OpenNote,readonly from:number){super();}
 eq(other:MarkdownWidget){return other.text===this.text&&other.path===this.path&&other.from===this.from;}
 toDOM(view:EditorView){
  const div=document.createElement('div');div.className='live-widget';
  div.onpointerdown=event=>{
   if((event.target as HTMLElement).closest('a,button,input,video,audio,iframe'))return;
   event.preventDefault();const offset=/^(```|~~~|\$\$)/.test(this.text)?this.text.indexOf('\n')+1:0;
   view.dispatch({selection:{anchor:Math.min(this.from+offset,view.state.doc.length)}});view.focus();
  };
  this.root=createRoot(div);this.root.render(<MarkdownPreview text={this.text} path={this.path} onOpen={this.open} onTask={index=>{
   const matches=[...this.text.matchAll(/^[ \t]*[-*+] \[([ xX])\]/gm)],match=matches[index];if(!match)return;
   const pos=this.from+match.index!+match[0].indexOf('[')+1,current=view.state.doc.sliceString(pos,pos+1);
   view.dispatch({changes:{from:pos,to:pos+1,insert:current===' '?'x':' '},userEvent:'input'});
  }}/>);return div;
 }
 destroy(){const root=this.root;queueMicrotask(()=>root?.unmount());}
 ignoreEvent(){return true;}
}
export function liveDecorations(path:string,open:OpenNote){
 return EditorView.decorations.compute(['doc','selection'],state=>{
  const ranges:Range<Decoration>[]=[],tree=syntaxTree(state),selection=state.selection;
  const active=(from:number,to:number)=>selection.ranges.some(s=>s.from<=to&&s.to>=from);
  const add=(from:number,to:number,dec:Decoration)=>{if(to>from)ranges.push(dec.range(from,to));};
  const opaque=/^(FencedCode|CodeBlock|Table|MathBlock|Frontmatter|BulletList|OrderedList|Blockquote|HorizontalRule)$/;
  for(let block=tree.topNode.firstChild;block;block=block.nextSibling){
   const {from,to,name}=block,text=state.doc.sliceString(from,to);
   if(!active(from,to)&&(opaque.test(name)||/^!\[\[.*\]\]$/.test(text.trim())||/^!\[[^\]\n]*\]\([^\n]*\)$/.test(text.trim()))){
    add(from,to,Decoration.replace({widget:new MarkdownWidget(text,path,open,from),block:true}));continue;
   }
   const heading=/^(#{1,6}) /.exec(text);
   if(heading){add(from,to,Decoration.mark({class:'cm-heading cm-h'+heading[1].length}));if(!active(from,to))add(from,from+heading[0].length,Decoration.replace({}));}
   if(active(from,to)||opaque.test(name))continue;
   const cursor=block.cursor();cursor.iterate(node=>{
    if(node.name==='WikiLink'){
     const [target,...aliases]=state.doc.sliceString(node.from+2,node.to-2).split('|');
     add(node.from,node.to,Decoration.replace({widget:new WikiLinkWidget(target,aliases.join('|')||target.split('/').pop()||target,open)}));return false;
    }
    const className:Record<string,string>={StrongEmphasis:'cm-bold',Emphasis:'cm-italic',Strikethrough:'cm-strike',InlineCode:'cm-inline-code'};
    if(className[node.name]){add(node.from,node.to,Decoration.mark({class:className[node.name]}));return;}
    if(node.name==='EmphasisMark'||node.name==='StrikethroughMark'||node.name==='CodeMark')add(node.from,node.to,Decoration.replace({}));
   });
  }
  return Decoration.set(ranges,true);
 });
}
