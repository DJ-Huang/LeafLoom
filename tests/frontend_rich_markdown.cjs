// Source preservation, serialization and shared history without a browser/vault.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),cache=path.join(root,'.cache/rich-core-tests');fs.mkdirSync(cache,{recursive:true});
fs.writeFileSync(path.join(cache,'entry.ts'),"export * from '../../web/src/rich-markdown';\nexport * from '../../web/src/edit-history';\nexport * from '../../web/src/source-offsets';\n");
require(path.join(root,'web/node_modules/esbuild')).buildSync({entryPoints:[path.join(cache,'entry.ts')],outfile:path.join(cache,'entry.cjs'),bundle:true,platform:'node',format:'cjs',nodePaths:[path.join(root,'web/node_modules')]});
const e=require(path.join(cache,'entry.cjs'));let count=0;
function check(name,fn){if(process.env.LEAFLOOM_RICH_CORE_CHECK&&!new RegExp(process.env.LEAFLOOM_RICH_CORE_CHECK).test(name))return;fn();count++;console.log('PASS '+name);}
const plain=node=>JSON.parse(JSON.stringify(node,(key,value)=>key==='sourceId'?undefined:value));
check('source spans retain metadata, whitespace, references and opaque content',()=>{
 const values=['','   \r\n','---\r\ntitle: 保留\r\n---\r\n','[id]: https://example.com','A\n\n[id]: https://example.com\n\nB\r\n',
  '---\r\ntitle: 原文\r\n---\r\n\r\nSetext\r\n======\r\n\r\n* first\r\n    * nested\r\n\r\n~~~js\r\nx\r\n~~~\r\n\r\n',
  '$$\nx+y\n\na+b\n$$\n\nNext','![[a.md]]\n\n```dataview\nLIST\n```\n', '| A | B |\n| --- | --- |\n| 1 | 2 |\n'];
 for(const value of values){const p=e.parseRichMarkdown(value);assert.equal(p.prefix+p.blocks.map(b=>b.before+b.raw).join('')+p.suffix,value);assert(p.blocks.every(b=>b.node.attrs.sourceId===b.id));}
});
check('mixed and nested task lists remain structured, including ordered tasks',()=>{
 for(const value of ['- plain\n- [ ] task\n  - [x] child','1. [ ] first\n2. ordinary','- [x] parent\n  - [ ] child']){
  const first=e.parseRichMarkdown(value).doc.content.filter(node=>node.type!=='paragraph'||node.content?.length),serialized=first.map(e.serializeRichNode).join('\n\n');
  const next=e.parseRichMarkdown(serialized).doc.content.filter(node=>node.type!=='paragraph'||node.content?.length);
  assert.deepEqual(plain(next),plain(first),serialized);
 }
 assert.equal(e.parseRichMarkdown('- \\[ ] literal').doc.content[0].type,'bulletList');
 assert.equal(e.parseRichMarkdown('- \\[ ] literal').doc.content[0].content[0].type,'listItem');
});
check('inline code and fenced code round trip embedded backticks',()=>{
 const code={type:'paragraph',content:[{type:'text',text:'a`b',marks:[{type:'code'}]}]};const parsed=e.parseRichMarkdown(e.serializeRichNode(code));assert.equal(parsed.doc.content[0].content[0].text,'a`b');assert.equal(parsed.doc.content[0].content[0].marks[0].type,'code');
 const block={type:'codeBlock',attrs:{language:'md'},content:[{type:'text',text:'```\nexample\n```'}]};assert.equal(e.parseRichMarkdown(e.serializeRichNode(block)).doc.content[0].content[0].text,block.content[0].text);
});
check('table escaping and alignment stay valid Markdown',()=>{
 const p=e.parseRichMarkdown('| A | B |\n| :--- | ---: |\n| x\\|y | `a` |');const table=p.doc.content[0],serialized=e.serializeRichNode(table),round=e.parseRichMarkdown(serialized).doc.content[0];assert.deepEqual(plain(round),plain(table));assert(serialized.includes('x\\|y'));assert(serialized.includes('---:'));
 const wiki=e.parseRichMarkdown('| Link |\n| --- |\n| [[Notes/Target.md\\|Alias]] |').doc.content[0];assert.deepEqual(plain(e.parseRichMarkdown(e.serializeRichNode(wiki)).doc.content[0]),plain(wiki));assert.equal(wiki.content[1].content[0].content[0].content[0].attrs.target,'Notes/Target.md');
});
check('formatted whitespace and marked inline atoms survive Markdown round trips',()=>{
 const node={type:'paragraph',content:[{type:'text',text:'Before '},{type:'text',text:' bold ',marks:[{type:'bold'}]},{type:'text',text:'after'}]},value=e.serializeRichNode(node);
 assert.equal(value,'Before  **bold** after');assert.equal(e.parseRichMarkdown(value).doc.content[0].content.find(n=>n.text==='bold').marks[0].type,'bold');
 const mixed=e.parseRichMarkdown('**`code` and [[Note|Alias]] and $x^2$**').doc.content[0],round=e.parseRichMarkdown(e.serializeRichNode(mixed)).doc.content[0];assert.deepEqual(plain(round),plain(mixed));
});
check('history crosses editor origins and groups a whole IME composition',()=>{
 const h=e.createEditHistory();let text='start';
 e.recordEdit(h,text,text+' A',{kind:'typing',before:{from:5,to:5},after:{from:7,to:7}});text+=' A';
 e.recordEdit(h,text,text+' B',{kind:'source',before:{from:7,to:7},after:{from:9,to:9}});text+=' B';
 text=e.historyText(h,text,'undo').text;assert.equal(text,'start A');text=e.historyText(h,text,'undo').text;assert.equal(text,'start');text=e.historyText(h,text,'redo').text;assert.equal(text,'start A');
 e.recordEdit(h,text,text+'中',{kind:'typing',group:'ime:1'});text+='中';e.recordEdit(h,text,text+'文',{kind:'typing',group:'ime:1'});text+='文';assert.equal(e.historyText(h,text,'undo').text,'start A');
});
check('UTF-16 patches and CRLF offsets preserve untouched source',()=>{
 for(const [a,b] of [['a😀b','a🙂b'],['😀',''],['abc','ab中c'],['x\r\ny','x\r\nY']]){const change=e.textChange(a,b);assert.equal(e.applyTextChange(a,change),b);}
 const raw='a\r\nb\nc\r\nd';for(let logical=0;logical<=e.editorText(raw).length;logical++)assert.equal(e.editorOffset(raw,e.sourceOffset(raw,logical)),logical);
 const start=e.sourceOffset(raw,2),end=e.sourceOffset(raw,3);assert.equal(raw.slice(0,start)+'B'+raw.slice(end),'a\r\nB\nc\r\nd');
});
console.log(JSON.stringify({checks:count}));
