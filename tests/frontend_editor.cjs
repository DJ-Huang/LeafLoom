// Pure editing contracts: no browser or user vault is accessed.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),cache=path.join(root,'.cache/editor-tests');fs.mkdirSync(cache,{recursive:true});
fs.writeFileSync(path.join(cache,'entry.ts'),[
 "export * from '../../web/src/editor-syntax';",
 "export * from '../../web/src/editor-commands';",
 "export * from '../../web/src/editor-completion';",
 "export * from '../../web/src/editor-anchors';",
 "export {EditorState} from '@codemirror/state';",
 "export {history,undo,redo} from '@codemirror/commands';"
].join('\n'));
require(path.join(root,'web/node_modules/esbuild')).buildSync({entryPoints:[path.join(cache,'entry.ts')],outfile:path.join(cache,'entry.cjs'),bundle:true,platform:'node',format:'cjs',nodePaths:[path.join(root,'web/node_modules')]});
global.window=new EventTarget();global.document={documentElement:{lang:'',style:{}},title:''};
global.localStorage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
const e=require(path.join(cache,'entry.cjs'));
function editor(text,pos=text.length){
 let state=e.EditorState.create({doc:text,selection:{anchor:pos},extensions:[e.editingMarkdown(),e.history(),e.pendingAnchors]});
 return {get state(){return state;},dispatch(spec){state=state.update(spec).state;},focus(){},get text(){return state.doc.toString();}};
}
let checks=0;function check(name,fn){try{fn();checks++;}catch(error){error.message=name+': '+error.message;throw error;}}
check('slash context, including unfinished syntax',()=>{
 for(const text of ['/','hello /h2','  /待办'])assert(e.slashRange(editor(text).state),text);
 for(const text of ['https://example.com/','C:/folder/','a/b','/usr/bin','` /todo','` /todo `','$$\n/todo','---\nkey: /todo','[url](https://x/','[[note /todo'])assert.equal(e.slashRange(editor(text).state),null,text);
 assert.equal(e.slashRange(editor('$$x /todo$$',9).state),null);
});
check('vault parser preserves complete blocks',()=>{
 const doc='---\ntitle: Test\n---\n\n# Hello\n\n- one\n  - nested\n- two\n\n```js\n/a\n```\n\n$$\nx+y\n$$\n\n| A | B |\n| --- | --- |\n| 1 | 2 |';
 const view=editor(doc),blocks=e.topBlocks(view.state,true);
 assert.deepEqual(blocks.map(b=>b.name),['Frontmatter','ATXHeading1','BulletList','FencedCode','MathBlock','Table']);
 assert.equal(e.blockAt(view.state,doc.indexOf('nested')).name,'BulletList');
 assert.equal(e.blockAt(editor('```\n\n```').state,4).name,'FencedCode');
});
check('slash insertion keeps surrounding text and one-step undo',()=>{
 const view=editor('before /h2 after');e.insertSnippet(view,'h2',{from:7,to:10});
 assert.equal(view.text,'before  after\n\n## ');
 assert(e.undo(view));assert.equal(view.text,'before /h2 after');assert(e.redo(view));assert.equal(view.text,'before  after\n\n## ');
 const empty=editor('/todo');e.insertSnippet(empty,'todo',{from:0,to:5});assert.equal(empty.text,'- [ ] ');
 const tight=editor('# Title /quote\nparagraph',14);e.insertSnippet(tight,'quote',{from:8,to:14});assert.equal(tight.text,'# Title \n\n> \n\nparagraph');
});
check('formatting toggles and preserves selection',()=>{
 for(const id of ['bold','italic','strike','inlineCode']){
  const view=editor('hello');view.dispatch({selection:{anchor:0,head:5}});assert(e.toggleFormat(view,id));
  assert(e.toggleFormat(view,id));assert.equal(view.text,'hello',id);assert.equal(view.state.selection.main.from,0);assert.equal(view.state.selection.main.to,5);
 }
 const nested=editor('hello');nested.dispatch({selection:{anchor:0,head:5}});e.toggleFormat(nested,'bold');e.toggleFormat(nested,'italic');assert.equal(nested.text,'***hello***');e.toggleFormat(nested,'italic');assert.equal(nested.text,'**hello**');e.toggleFormat(nested,'bold');assert.equal(nested.text,'hello');
 const part=editor('**one two three**');part.dispatch({selection:{anchor:6,head:9}});e.toggleFormat(part,'bold');assert.equal(part.text,'**one** two **three**');
});
check('links preserve selected text, escape destinations and reject scripts',()=>{
 const view=editor('label');assert(e.insertLink(view,{from:0,to:5},'https://example.com/a(b)'));
 assert.equal(view.text,'[label](https://example.com/a%28b%29)');assert.equal(e.safeLink('javascript:alert(1)'),null);
 assert.equal(e.linkMarkdown('a[b]','attachments/a%20b.png'),'[a\\[b\\]](attachments/a%20b.png)');
});
check('list moves as a unit and metadata is protected',()=>{
 const initial='---\ntitle: Safe\n---\n\nfirst\n\n- parent\n  - child\n\nlast';
 const view=editor(initial,initial.indexOf('child'));
 assert(e.actOnBlock(view,'down'));assert.equal(view.text,'---\ntitle: Safe\n---\n\nfirst\n\nlast\n\n- parent\n  - child');
 assert(e.undo(view));assert.equal(view.text,initial);
 view.dispatch({selection:{anchor:0}});assert.equal(e.actOnBlock(view,'delete'),false);
 const tight=editor('> quote\n# heading\nparagraph',2);e.actOnBlock(tight,'down');assert.deepEqual(e.topBlocks(tight.state,true).map(b=>b.name),['ATXHeading1','Blockquote','Paragraph']);
});
check('safe conversions and complex block rejection',()=>{
 const view=editor('# title');assert(e.convertBlock(view,'todo'));assert.equal(view.text,'- [ ] title');
 const nested=editor('- parent\n  - child');assert.equal(e.convertBlock(nested,'h1'),false);
 const code=editor('```\nabc\n```');assert.equal(e.convertBlock(code,'quote'),false);
});
check('anchors track typing and are invalidated by target deletion',()=>{
 const view=editor('first\n\nsecond');let id=e.trackRange(view,{from:7,to:7});
 view.dispatch({changes:{from:0,insert:'prefix '}});assert.deepEqual(e.trackedRange(view,id),{from:14,to:14});
 view.dispatch({changes:{from:14,insert:'typed '}});assert.deepEqual(e.trackedRange(view,id),{from:20,to:20});
 view.dispatch({changes:{from:14,to:26,insert:''}});assert.equal(e.trackedRange(view,id),undefined);
 const slash=editor('/image');id=e.trackRange(slash,{from:0,to:6});slash.dispatch({changes:{from:2,to:3,insert:'x'}});assert.equal(e.trackedRange(slash,id),undefined);
});
console.log(`Editor contracts passed: ${checks} scenarios.`);
