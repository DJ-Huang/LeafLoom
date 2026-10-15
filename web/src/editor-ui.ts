import {EditorState,Prec,StateEffect,StateField} from '@codemirror/state';
import {Decoration,EditorView,keymap,showTooltip,Tooltip,ViewPlugin,WidgetType} from '@codemirror/view';
import {completionStatus} from '@codemirror/autocomplete';
import {t} from './i18n';
import {actOnBlock,BlockAction,convertBlock,convertibleIds,formatCommands,InsertId,InsertRange,insertCommands,toggleFormat} from './editor-commands';
import {blockAt,prosePosition,simpleBlockText,topBlocks} from './editor-syntax';
import {matchingCommands,slashRange,wikiRange} from './editor-completion';

type Panel='insert'|'block'|null;
const openPanel=StateEffect.define<Panel>();
const focusChanged=StateEffect.define<boolean>();
export const editorVisible=StateEffect.define<boolean>();
export const refreshEditorUI=StateEffect.define<null>();
export const dismissEditorUI=StateEffect.define<null>();
type UIState={panel:Panel,focused:boolean,active:boolean,dismissed:boolean,revision:number};
const uiState=StateField.define<UIState>({
 create:()=>({panel:null,focused:false,active:true,dismissed:false,revision:0}),
 update(value,tr){
  let next=tr.docChanged||tr.selection?{...value,panel:null,dismissed:false}:value;
  for(const effect of tr.effects){
   if(effect.is(openPanel))next={...next,panel:effect.value,dismissed:false};
   if(effect.is(focusChanged))next={...next,focused:effect.value};
   if(effect.is(editorVisible))next={...next,active:effect.value,panel:null,focused:effect.value&&next.focused};
   if(effect.is(refreshEditorUI))next={...next,revision:next.revision+1};
   if(effect.is(dismissEditorUI))next={...next,panel:null,dismissed:true};
  }
  return next;
 }
});
const close=(view:EditorView)=>view.dispatch({effects:dismissEditorUI.of(null)});
function button(label:string,action:()=>void,visual=label){
 const node=document.createElement('button');node.type='button';node.textContent=visual;node.title=label;node.setAttribute('aria-label',label);
 node.onpointerdown=event=>event.preventDefault();node.onclick=action;return node;
}
function keyboardMenu(dom:HTMLElement,view:EditorView){
 dom.addEventListener('keydown',event=>{
  if(event.isComposing)return;
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(view);view.focus();return;}
  if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
  const items=Array.from(dom.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));
  const i=items.indexOf(document.activeElement as HTMLButtonElement);if(!items.length)return;
  event.preventDefault();items[event.key==='Home'?0:event.key==='End'?items.length-1:(i+(event.key==='ArrowDown'?1:items.length-1))%items.length].focus();
 });
}
class BlockHandle extends WidgetType{
 constructor(readonly revision:number){super();}
 eq(other:BlockHandle){return this.revision===other.revision;}
 toDOM(view:EditorView){
  const dom=document.createElement('span');dom.className='editor-block-handle';dom.contentEditable='false';
  dom.append(button(t('插入内容'),()=>view.dispatch({effects:openPanel.of('insert')}),'+'),button(t('块操作'),()=>view.dispatch({effects:openPanel.of('block')}),'⋮⋮'));
  return dom;
 }
 ignoreEvent(){return true;}
}
class EmptyHint extends WidgetType{
 constructor(readonly revision:number){super();}
 eq(other:EmptyHint){return this.revision===other.revision;}
 toDOM(){const dom=document.createElement('span');dom.className='editor-empty-hint';dom.textContent=t('输入 / 插入内容');dom.setAttribute('aria-hidden','true');return dom;}
}
export function editorUI(run:(id:InsertId,range:InsertRange)=>void){
 const formatTip:Tooltip['create']=view=>{
  const dom=document.createElement('div');dom.className='leafloom-editor-popup editor-format-bar';dom.setAttribute('role','toolbar');dom.setAttribute('aria-label',t('文字格式'));
  for(const command of formatCommands)dom.append(button(t(command.label),()=>toggleFormat(view,command.id),({bold:'B',italic:'I',strike:'S̶',inlineCode:'<>'})[command.id]));
  dom.append(button(t('网页链接'),()=>run('link',view.state.selection.main),'↗'));keyboardMenu(dom,view);
  return {dom};
 };
 const panelTip:Tooltip['create']=view=>{
  const dom=document.createElement('div');dom.className='leafloom-editor-popup editor-block-menu';dom.setAttribute('role','menu');
  const panel=view.state.field(uiState).panel,block=blockAt(view.state);
  dom.setAttribute('aria-label',panel==='insert'?t('插入内容'):t('块操作'));
  let input:HTMLInputElement|undefined;
  const append=(label:string,action:()=>void,disabled=false)=>{const node=button(label,()=>{close(view);action();});node.setAttribute('role','menuitem');node.disabled=disabled;dom.append(node);};
  if(panel==='insert'){
   input=document.createElement('input');input.placeholder=t('搜索命令…');input.setAttribute('aria-label',t('搜索命令…'));dom.append(input);
   const list=document.createElement('div');list.className='editor-command-list';dom.append(list);
   const render=()=>{
    list.replaceChildren();for(const command of matchingCommands(input!.value)){
     const node=button(t(command.label),()=>{close(view);run(command.id,{from:block.to,to:block.to});},command.icon+'  '+t(command.label));node.setAttribute('role','menuitem');list.append(node);
    }
    if(!list.childElementCount){const hint=document.createElement('p');hint.className='editor-menu-hint';hint.textContent=t('没有匹配的命令');list.append(hint);}
   };input.oninput=render;input.onkeydown=event=>{if(event.key==='Enter'&&!event.isComposing){event.preventDefault();list.querySelector<HTMLButtonElement>('button')?.click();}};render();
  }else{
   const convertible=simpleBlockText(view.state,block)!==null;
   if(convertible){
    const title=document.createElement('p');title.className='editor-menu-hint';title.textContent=t('转换为');dom.append(title);
    for(const id of convertibleIds)append(t(insertCommands.find(command=>command.id===id)!.label),()=>convertBlock(view,id,block));
   }
   const blocks=topBlocks(view.state),index=blocks.findIndex(item=>item.from===block.from&&item.to===block.to);
   const actions:{id:BlockAction,label:string,disabled?:boolean}[]=[
    {id:'duplicate',label:'创建副本'},
    {id:'up',label:'上移',disabled:index<=0||blocks[index-1]?.name==='Frontmatter'},
    {id:'down',label:'下移',disabled:index<0||index===blocks.length-1},
    {id:'delete',label:'删除块'}
   ];
   for(const action of actions)append(t(action.label),()=>actOnBlock(view,action.id,block),index<0||action.disabled);
  }
  keyboardMenu(dom,view);
  return {dom,mount(){queueMicrotask(()=>{if(dom.isConnected)(input||dom.querySelector<HTMLButtonElement>('button:not(:disabled)'))?.focus();});}};
 };
 const statusTip=(message:string):Tooltip['create']=>()=>{const dom=document.createElement('div');dom.className='leafloom-editor-popup editor-menu-hint';dom.setAttribute('role','status');dom.textContent=message;return {dom};};
 return [uiState,
  EditorView.decorations.compute(['doc','selection',uiState],state=>{
   const ui=state.field(uiState),s=state.selection.main;
   if(!ui.active||!s.empty)return Decoration.none;
   const block=blockAt(state);if(block.name==='Frontmatter')return Decoration.none;
   const ranges=[Decoration.widget({widget:new BlockHandle(ui.revision),side:-1}).range(state.doc.lineAt(block.from).from)];
   const line=state.doc.lineAt(s.head);
   if(line.text===''&&prosePosition(state,s.head))ranges.push(Decoration.widget({widget:new EmptyHint(ui.revision),side:1}).range(line.from));
   return Decoration.set(ranges,true);
  }),
  showTooltip.computeN([uiState,'doc','selection'],state=>{
   const ui=state.field(uiState),s=state.selection.main;if(!ui.active||ui.dismissed)return [];
   if(ui.panel)return [{pos:s.head,create:view=>panelTip(view)}];
   if(!ui.focused)return [];
   if(!s.empty&&prosePosition(state,s.from))return [{pos:s.from,end:s.to,above:true,create:view=>formatTip(view)}];
   const wiki=wikiRange(state),slash=slashRange(state);
   if(wiki&&!wiki.query.trim())return [{pos:s.head,create:statusTip(t('输入笔记名称以搜索'))}];
   if(slash&&!matchingCommands(slash.query).length)return [{pos:s.head,create:statusTip(t('没有匹配的命令'))}];
   return [];
  }),
  Prec.high(keymap.of([
   {key:'Escape',run:view=>{const ui=view.state.field(uiState);if(view.composing||completionStatus(view.state))return false;if(ui.panel||!view.state.selection.main.empty||wikiRange(view.state)||slashRange(view.state)){close(view);return true;}return false;}},
   {key:'Alt-Shift-b',run:view=>{if(blockAt(view.state).name==='Frontmatter')return false;view.dispatch({effects:openPanel.of('block')});return true;}},
   {key:'Alt-Shift-f',run:()=>{const toolbar=document.querySelector<HTMLButtonElement>('.editor-format-bar button');toolbar?.focus();return !!toolbar;}}
  ])),
  ViewPlugin.fromClass(class{
   outside=(event:PointerEvent)=>{const target=event.target as HTMLElement;if(!this.view.dom.contains(target)&&!target.closest('.leafloom-editor-popup'))close(this.view);};
   constructor(readonly view:EditorView){document.addEventListener('pointerdown',this.outside);}
   destroy(){document.removeEventListener('pointerdown',this.outside);}
  }),
  EditorView.domEventHandlers({
   focus(_event,view){queueMicrotask(()=>{if(view.dom.isConnected)view.dispatch({effects:focusChanged.of(true)});});},
   blur(event,view){if(!(event.relatedTarget as HTMLElement|null)?.closest('.leafloom-editor-popup'))queueMicrotask(()=>{if(view.dom.isConnected)view.dispatch({effects:focusChanged.of(false)});});}
  })
 ];
}
