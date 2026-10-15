import {EditorState} from '@codemirror/state';
import {ensureSyntaxTree, syntaxTree} from '@codemirror/language';
import {markdown, markdownLanguage} from '@codemirror/lang-markdown';
import type {MarkdownConfig} from '@lezer/markdown';

// Teach the incremental parser about vault-specific opaque content. Commands and
// decorations share these boundaries instead of independently guessing with regexes.
const vaultMarkdown: MarkdownConfig = {
 defineNodes: [{name:'Frontmatter',block:true},{name:'MathBlock',block:true},'MathInline','WikiLink'],
 parseBlock: [{
  name:'Frontmatter',before:'HorizontalRule',
  parse(cx,line){
   if(cx.lineStart!==0 || line.text.trim()!=='---')return false;
   const from=cx.lineStart;let to=line.text.length;
   while(cx.nextLine()){
    to=cx.lineStart+line.text.length;
    if(line.text.trim()==='---'){cx.nextLine();break;}
   }
   cx.addElement(cx.elt('Frontmatter',from,to));return true;
  }
 },{
  name:'MathBlock',before:'FencedCode',
  parse(cx,line){
   if(cx.depth!==1 || !line.text.trimStart().startsWith('$$'))return false;
   const from=cx.lineStart;let to=from+line.text.length;
   if(line.text.trim().length>4 && line.text.trimEnd().endsWith('$$'))cx.nextLine();
   else while(cx.nextLine()){
    to=cx.lineStart+line.text.length;
    if(line.text.trimEnd().endsWith('$$')){cx.nextLine();break;}
   }
   cx.addElement(cx.elt('MathBlock',from,to));return true;
  },
  endLeaf(_cx,line){return line.text.trimStart().startsWith('$$');}
 }],
 parseInline:[{
  name:'WikiLink',before:'Link',
  parse(cx,next,pos){
   if(next!==91 || cx.char(pos+1)!==91)return -1;
   const tail=cx.slice(pos,cx.end),match=/^\[\[[^\]\n]+\]\]/.exec(tail);
   return match?cx.addElement(cx.elt('WikiLink',pos,pos+match[0].length)):-1;
  }
 },{
  name:'MathInline',before:'Escape',
  parse(cx,next,pos){
   if(next!==36 || /\s/.test(cx.slice(pos+1,pos+2)))return -1;
   const match=/^\$[^\n$]+\$/.exec(cx.slice(pos,cx.end));
   return match?cx.addElement(cx.elt('MathInline',pos,pos+match[0].length)):-1;
  }
 }]
};
export const editingMarkdown=()=>markdown({base:markdownLanguage,extensions:[vaultMarkdown],pasteURLAsLink:false});
export type MarkdownBlock={from:number,to:number,name:string};
export function topBlocks(state:EditorState,complete=false):MarkdownBlock[]{
 const tree=complete?ensureSyntaxTree(state,state.doc.length,40):syntaxTree(state);
 if(!tree)return [];
 const blocks:MarkdownBlock[]=[];
 for(let node=tree.topNode.firstChild;node;node=node.nextSibling)blocks.push({from:node.from,to:node.to,name:node.name});
 return blocks;
}
export function blockAt(state:EditorState,pos=state.selection.main.head):MarkdownBlock{
 const line=state.doc.lineAt(pos);
 // A position at the end of a block belongs to that block, not the next one.
 let node=syntaxTree(state).resolveInner(pos,-1);
 while(node.parent && node.parent.name!=='Document')node=node.parent;
 if(!line.text.trim()&&node.name==='Document')return {from:line.from,to:line.to,name:'Empty'};
 return node.name!=='Document'?{from:node.from,to:node.to,name:node.name}:{from:line.from,to:line.to,name:'Paragraph'};
}
const opaque=/^(Frontmatter|MathBlock|MathInline|FencedCode|CodeBlock|InlineCode|HTMLBlock|HTMLTag|Link|Image|Autolink|URL|WikiLink)$/;
export function prosePosition(state:EditorState,pos:number,allowWiki=false){
 for(let node=syntaxTree(state).resolveInner(pos,-1);node;node=node.parent!){
  if(opaque.test(node.name) && !(allowWiki&&node.name==='WikiLink'))return false;
 }
 const prefix=state.doc.sliceString(state.doc.lineAt(pos).from,pos);
 // Also keep menus quiet while a code/math span is still being typed.
 const plain=prefix.replace(/\\./g,'').replace(/(`+)[\s\S]*?\1/g,'').replace(/\$[^$]*\$/g,'');
 return !plain.includes('`')&&!plain.includes('$');
}
export function simpleBlockText(state:EditorState,block:MarkdownBlock):string|null{
 const text=state.doc.sliceString(block.from,block.to);
 if(block.name==='Empty'||block.name==='Paragraph')return text;
 if(/^ATXHeading/.test(block.name))return text.replace(/^#{1,6}\s+/,'').replace(/\s+#+\s*$/,'');
 if(/^SetextHeading/.test(block.name))return text.replace(/\n[=-]+\s*$/,'');
 if(block.name==='Blockquote' && text.split('\n').every(line=>/^> ?(?!>|[-*+] |\d+[.)] |#{1,6} |```|~~~)/.test(line)))return text.replace(/^> ?/gm,'');
 if(/^(BulletList|OrderedList)$/.test(block.name) && text.split('\n').every(line=>/^(?:[-*+]|\d+[.)]) (?:\[[ xX]\] )?\S/.test(line)))return text.replace(/^(?:[-*+]|\d+[.)]) (?:\[[ xX]\] )?/gm,'');
 return null;
}
