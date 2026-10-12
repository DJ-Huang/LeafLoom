import React,{useEffect,useRef} from 'react';
import {createRoot,Root} from 'react-dom/client';
import {EditorState} from '@codemirror/state';
import {EditorView,Decoration,WidgetType,keymap} from '@codemirror/view';
import {defaultKeymap,history,historyKeymap} from '@codemirror/commands';
import {search,searchKeymap,openSearchPanel} from '@codemirror/search';
import {markdown} from '@codemirror/lang-markdown';
import {OpenNote} from './api';
import {MarkdownPreview} from './reader';
export {openSearchPanel};
class WikiLinkWidget extends WidgetType{
 constructor(readonly target:string,readonly label:string,readonly open:OpenNote){super();}
 eq(other:WikiLinkWidget){return other.target===this.target&&other.label===this.label;}
 toDOM(){const a=document.createElement('a');a.textContent=this.label;a.href='#';a.className='live-wikilink';a.onclick=e=>{e.preventDefault();e.stopPropagation();this.open(this.target);};return a;}
 ignoreEvent(){return true;}
}

class MarkdownWidget extends WidgetType{
 root?:Root;
 constructor(readonly text:string,readonly path:string,readonly open:OpenNote,readonly from:number,readonly task:(pos:number)=>void){super();}
 eq(other:MarkdownWidget){return other.text===this.text&&other.path===this.path&&other.from===this.from;}
 toDOM(){const div=document.createElement('div');div.className='live-widget';this.root=createRoot(div);this.root.render(<MarkdownPreview text={this.text} path={this.path} onOpen={this.open} onTask={i=>{const matches=[...this.text.matchAll(/^[ \t]*[-*+] \[([ xX])\]/gm)];if(matches[i])this.task(this.from+matches[i].index!+matches[i][0].indexOf('[')+1);}}/>);return div;}
 destroy(){const root=this.root;queueMicrotask(()=>root?.unmount());}
 ignoreEvent(){return true;}
}

export function LiveEditor({initial,path,onChange,onOpen,source,onReady,onRelease}:{initial:string,path:string,onChange:(text:string)=>void,onOpen:OpenNote,source:boolean,onReady?:(view:EditorView)=>void,onRelease?:(view:EditorView)=>void}){
 const host=useRef<HTMLDivElement>(null);const view=useRef<EditorView|null>(null);const callbacks=useRef({onChange,onOpen});callbacks.current={onChange,onOpen};
 useEffect(()=>{
  if(!host.current)return;
  const open:OpenNote=(target,anchor)=>callbacks.current.onOpen(target,anchor);
  const makeDecorations=(v:EditorView)=>{
   const ranges:any[]=[];const builder={add:(from:number,to:number,d:Decoration)=>ranges.push(d.range(from,to)),finish:()=>Decoration.set(ranges,true)};if(source)return builder.finish();const doc=v.state.doc;const cursor=v.state.selection.main;let line=1;
   const task=(pos:number)=>{const editor=view.current;if(!editor)return;const current=editor.state.doc.sliceString(pos,pos+1);editor.dispatch({changes:{from:pos,to:pos+1,insert:current===' '? 'x':' '}});};
   while(line<=doc.lines){const start=doc.line(line);let end=line;let block=false;
    if(start.text.startsWith('```')||start.text.trim()==='$$'){const marker=start.text.startsWith('```')?'```':'$$';while(end<doc.lines){end++;if(doc.line(end).text.startsWith(marker))break;}block=end>line;}
    else if(start.text.startsWith('|')&&line<doc.lines&&/^\s*\|?[\s:|-]+\|/.test(doc.line(line+1).text)){while(end<doc.lines&&doc.line(end+1).text.startsWith('|'))end++;block=true;}
    else if(/^!\[\[.*\]\]$/.test(start.text.trim())||/^[ \t]*[-*+] \[[ xX]\]/.test(start.text))block=true;
    else if(start.text.trim()==='---'&&line===1){block=true;while(end<doc.lines){end++;if(doc.line(end).text.trim()==='---')break;}}
    const last=doc.line(end);const active=cursor.from<=last.to&&cursor.to>=start.from;
    if(block&&!active){const text=doc.sliceString(start.from,last.to);builder.add(start.from,last.to,Decoration.replace({widget:new MarkdownWidget(text,path,open,start.from,task),block:true}));line=end+1;continue;}
    const heading=/^(#{1,6}) /.exec(start.text);if(heading){builder.add(start.from,start.to,Decoration.mark({class:'cm-heading cm-h'+heading[1].length}));if(!active)builder.add(start.from,start.from+heading[0].length,Decoration.replace({}));}
    // Decorations must be ordered; inline ranges are collected then sorted.
    if(!active){const ranges:{from:number,to:number,dec:Decoration}[]=[];for(const m of start.text.matchAll(/(?<!!)\[\[([^\]\n]+)\]\]/g)){const [target,...aliases]=m[1].split('|');const pos=start.from+m.index!;ranges.push({from:pos,to:pos+m[0].length,dec:Decoration.replace({widget:new WikiLinkWidget(target,aliases.join('|')||target.split('/').pop()||target,open)})});}for(const m of start.text.matchAll(/\*\*([^*]+)\*\*/g)){const pos=start.from+m.index!;ranges.push({from:pos,to:pos+2,dec:Decoration.replace({})},{from:pos+2,to:pos+m[0].length-2,dec:Decoration.mark({class:'cm-bold'})},{from:pos+m[0].length-2,to:pos+m[0].length,dec:Decoration.replace({})});}ranges.sort((a,b)=>a.from-b.from);for(const x of ranges)builder.add(x.from,x.to,x.dec);}
    line++;
   }
   return builder.finish();
  };
  // Block decorations are a direct state facet, not viewport decorations.
  const plugin=EditorView.decorations.compute(['doc','selection'],state=>makeDecorations({state} as EditorView));
  const bold={key:'Mod-b',run:(v:EditorView)=>{const s=v.state.selection.main;v.dispatch({changes:{from:s.from,to:s.to,insert:'**'+v.state.doc.sliceString(s.from,s.to)+'**'}});return true;}};
  const state=EditorState.create({doc:initial,extensions:[markdown(),history(),search(),keymap.of([bold,...searchKeymap,...defaultKeymap,...historyKeymap]),EditorState.phrases.of({'Find':'查找','Replace':'替换','next':'下一个','previous':'上一个','all':'全部','match case':'区分大小写','regexp':'正则表达式','by word':'整词','close':'关闭','replace':'替换','replace all':'全部替换'}),EditorView.lineWrapping,plugin,EditorView.updateListener.of(update=>{if(update.docChanged)callbacks.current.onChange(update.state.doc.toString());}),EditorView.theme({'&':{fontSize:'16px'},'.cm-content':{fontFamily:'inherit',padding:'32px',minHeight:'65vh'},'.cm-focused':{outline:'none'}})]});
  const editor=new EditorView({state,parent:host.current});view.current=editor;onReady?.(editor);
  return()=>{onRelease?.(editor);view.current=null;editor.destroy();};
 },[path,source]);
 return <div className={'live-editor'+(source?' source-editor':'')} ref={host}/>;
}
