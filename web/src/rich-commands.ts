import type {Editor,JSONContent} from '@tiptap/core';
import type {Node as PMNode} from '@tiptap/pm/model';
import {NodeSelection,TextSelection} from '@tiptap/pm/state';
import {insertCommands,InsertId} from './editor-catalog';
import {t} from './i18n';
import type {RichRange} from './rich-anchors';

export type CommandContext={kind:'slash'|'wiki',query:string,from:number,to:number};
export function richContext(editor:Editor):CommandContext|null{
 const {selection}=editor.state;if(!selection.empty||editor.view.composing)return null;
 const {$from}=selection;
 if(!$from.parent.isTextblock||$from.parent.type.name==='codeBlock'||$from.marks().some(mark=>mark.type.name==='code'))return null;
 const before=$from.parent.textBetween(0,$from.parentOffset,'\n','\ufffc');
 const unfinished=(text:string)=>{const value=text.replace(/\\./g,'').replace(/(`+)[\s\S]*?\1/g,'').replace(/\$[^$]*\$/g,'');return value.includes('`')||value.includes('$');};
 const wiki=/\[\[([^\]\n|]*)$/.exec(before);
 if(wiki)return unfinished(before.slice(0,wiki.index))?null:{kind:'wiki',query:wiki[1],from:$from.start()+wiki.index,to:selection.from};
 if(unfinished(before))return null;
 for(let depth=$from.depth;depth>0;depth--)if(['tableCell','tableHeader'].includes($from.node(depth).type.name))return null;
 const slash=/(?:^|\s)\/([^\s/\\]*)$/.exec(before);
 if(!slash)return null;
 const from=selection.from-slash[1].length-1;
 if(/\[\[[^\]]*$/.test(before.slice(0,from-$from.start())))return null;
 return {kind:'slash',query:slash[1],from,to:selection.from};
}
export function matchingRichCommands(query:string){
 const term=query.toLocaleLowerCase().trim();return insertCommands.filter(command=>(t(command.label)+' '+command.aliases+' '+t(command.description)).toLocaleLowerCase().includes(term));
}
export type BlockTarget={node:PMNode,pos:number};
export function richBlock(editor:Editor,position=editor.state.selection.from):BlockTarget|null{
 const {doc}=editor.state;position=Math.min(position,doc.content.size);
 if(editor.state.selection instanceof NodeSelection&&editor.state.selection.from===position)return {node:editor.state.selection.node,pos:position};
 const $pos=doc.resolve(position);
 for(let depth=$pos.depth;depth>0;depth--)if(['listItem','taskItem'].includes($pos.node(depth).type.name))return {node:$pos.node(depth),pos:$pos.before(depth)};
 if($pos.depth)return {node:$pos.node(1),pos:$pos.before(1)};
 const node=doc.nodeAt(position);return node?{node,pos:position}:null;
}
export function commandNode(editor:Editor,id:InsertId):PMNode{
 const schema=editor.schema,p=schema.nodes.paragraph;
 if(/^h[123]$/.test(id))return schema.nodes.heading.create({level:Number(id[1])});
 if(id==='bullet')return schema.nodes.bulletList.create(null,schema.nodes.listItem.create(null,p.create()));
 if(id==='ordered')return schema.nodes.orderedList.create(null,schema.nodes.listItem.create(null,p.create()));
 if(id==='todo')return schema.nodes.taskList.create(null,schema.nodes.taskItem.create({checked:false},p.create()));
 if(id==='quote')return schema.nodes.blockquote.create(null,p.create());
 if(id==='divider')return schema.nodes.horizontalRule.create();
 if(id==='code')return schema.nodes.codeBlock.create();
 if(id==='table'){
  const rows=Array.from({length:3},(_,row)=>schema.nodes.tableRow.create(null,Array.from({length:2},()=>schema.nodes[row===0?'tableHeader':'tableCell'].create(null,p.create()))));
  return schema.nodes.table.create(null,rows);
 }
 if(id==='math')return schema.nodes.specialBlock.create({kind:'math',raw:'$$\n\n$$',content:''});
 if(id==='mermaid')return schema.nodes.specialBlock.create({kind:'mermaid',raw:'```mermaid\ngraph LR\n  A --> B\n```',content:'graph LR\n  A --> B'});
 return p.create();
}
export function insertRichCommand(editor:Editor,id:InsertId,range:RichRange,after?:number){
 if(editor.view.composing)return false;
 const tr=editor.state.tr;tr.setMeta('leafloomEdit','command');if(range.to>range.from)tr.delete(range.from,range.to);
 const at=tr.mapping.map(after??range.from),$at=tr.doc.resolve(Math.min(at,tr.doc.content.size));
 if(id==='wiki'){
  if($at.parent.inlineContent){tr.insertText('[[',at);tr.setSelection(TextSelection.create(tr.doc,at+2));}
  else{const p=editor.schema.nodes.paragraph.create(null,editor.schema.text('[['));tr.insert(at,p);tr.setSelection(TextSelection.create(tr.doc,at+3));}
 }else{
  const node=commandNode(editor,id);let position:number;
  if(after!==undefined){position=at;tr.insert(position,node);}
  else if($at.parent.type.name==='paragraph'&&$at.parent.content.size===0){position=$at.before();tr.replaceWith(position,$at.after(),node);}
  else{position=$at.depth?$at.after(1):at;tr.insert(position,node);}
  const selected=TextSelection.near(tr.doc.resolve(Math.min(position+1,tr.doc.content.size)),1);tr.setSelection(selected);
  // Atomic blocks have no text cursor of their own. Leave a place to continue.
  if(node.isAtom){const end=position+node.nodeSize;if(!tr.doc.nodeAt(end))tr.insert(end,editor.schema.nodes.paragraph.create());tr.setSelection(NodeSelection.create(tr.doc,position));}
 }
 editor.view.dispatch(tr.scrollIntoView());editor.commands.focus();return true;
}
export function convertRichBlock(editor:Editor,id:InsertId){
 const chain=editor.chain().focus();
 if(id==='bullet')return chain.toggleBulletList().run();if(id==='ordered')return chain.toggleOrderedList().run();if(id==='todo')return chain.toggleTaskList().run();if(id==='quote')return chain.toggleBlockquote().run();
 if(id==='text'||/^h[123]$/.test(id)){
  if(editor.isActive('taskList'))chain.liftListItem('taskItem');else if(editor.isActive('bulletList')||editor.isActive('orderedList'))chain.liftListItem('listItem');
  if(editor.isActive('blockquote'))chain.lift('blockquote');
  return id==='text'?chain.setParagraph().run():chain.setHeading({level:Number(id[1]) as 1|2|3}).run();
 }
 return false;
}
export function blockAction(editor:Editor,action:'duplicate'|'delete'|'up'|'down',target=richBlock(editor)){
 if(!target||target.node.attrs.kind==='definitions')return false;
 const {node,pos}=target,{$from}=editor.state.selection,tr=editor.state.tr.setMeta('leafloomEdit','command'),$pos=editor.state.doc.resolve(pos);
 let destination=pos;
 if(action==='duplicate'){destination=pos+node.nodeSize;tr.insert(destination,node);}
 else if(action==='delete')tr.delete(pos,pos+node.nodeSize);
 else{
  const index=$pos.index(),parent=$pos.parent,other=parent.maybeChild(index+(action==='up'?-1:1));
  if(!other||other.attrs.kind==='definitions')return false;
  destination=action==='up'?pos-other.nodeSize:pos+other.nodeSize;tr.delete(pos,pos+node.nodeSize);tr.insert(destination,node);
 }
 tr.setSelection(TextSelection.near(tr.doc.resolve(Math.max(0,Math.min(tr.doc.content.size,destination+(action==='delete'?0:1))))));
 editor.view.dispatch(tr.scrollIntoView());editor.commands.focus();return true;
}
export function setRichLink(editor:Editor,range:RichRange,url:string,label:string){
 const tr=editor.state.tr.setMeta('leafloomEdit','command'),mark=editor.schema.marks.link.create({href:url});
 const text=editor.schema.text(label||url,[mark]),$at=tr.doc.resolve(range.from);
 if($at.parent.inlineContent)tr.replaceWith(range.from,range.to,text);
 else tr.replaceWith(range.from,range.to,editor.schema.nodes.paragraph.create(null,text));
 tr.setSelection(TextSelection.near(tr.doc.resolve(Math.min(tr.doc.content.size,range.from+text.nodeSize))));editor.view.dispatch(tr);editor.commands.focus();
}
export function insertRichAssets(editor:Editor,range:RichRange,assets:{relative:string,label:string,image:boolean}[]){
 const $from=editor.state.doc.resolve(range.from);let inTable=false;for(let depth=$from.depth;depth>0;depth--)if(['tableCell','tableHeader'].includes($from.node(depth).type.name))inTable=true;
 if(inTable){const nodes:PMNode[]=[];for(const asset of assets){if(nodes.length)nodes.push(editor.schema.text(' '));nodes.push(asset.image?editor.schema.nodes.vaultImage.create({src:asset.relative,alt:asset.label}):editor.schema.text(asset.label,[editor.schema.marks.link.create({href:asset.relative})]));}const tr=editor.state.tr.replaceWith(range.from,range.to,nodes).setMeta('leafloomEdit','command');editor.view.dispatch(tr);return;}
 const content:JSONContent[]=assets.map(asset=>({type:'paragraph',content:[asset.image?{type:'vaultImage',attrs:{src:asset.relative,alt:asset.label}}:{type:'text',text:asset.label,marks:[{type:'link',attrs:{href:asset.relative}}]}]}));
 editor.chain().focus().insertContentAt(range,content).run();
}
export function selectedRowAsHeader(editor:Editor){
 const {$from}=editor.state.selection;let depth=$from.depth;while(depth&&$from.node(depth).type.name!=='table')depth--;if(!depth)return false;
 const table=$from.node(depth),index=$from.index(depth),rows:PMNode[]=[];table.forEach(row=>rows.push(row));
 const chosen=rows.splice(index,1)[0];rows.unshift(chosen);
 const content=rows.map((row,i)=>row.type.create(row.attrs,(row.content as any).content.map((cell:PMNode)=>editor.schema.nodes[i===0?'tableHeader':'tableCell'].create(cell.attrs,cell.content))));
 const pos=$from.before(depth),tr=editor.state.tr.replaceWith(pos,pos+table.nodeSize,table.type.create(table.attrs,content)).setMeta('leafloomEdit','command');
 tr.setSelection(TextSelection.near(tr.doc.resolve(pos+3)));editor.view.dispatch(tr);return true;
}
export function alignRichTable(editor:Editor,align:'left'|'center'|'right'){
 const {$from}=editor.state.selection;
 for(let depth=$from.depth;depth>1;depth--)if(['tableCell','tableHeader'].includes($from.node(depth).type.name)){
  const column=$from.index(depth-1),tableDepth=depth-2,table=$from.node(tableDepth),tablePos=$from.before(tableDepth),tr=editor.state.tr.setMeta('leafloomEdit','command');
  table.forEach((row,rowOffset)=>row.forEach((cell,cellOffset,index)=>{if(index===column)tr.setNodeMarkup(tablePos+1+rowOffset+1+cellOffset,undefined,{...cell.attrs,align});}));editor.view.dispatch(tr);return true;
 }
 return false;
}
