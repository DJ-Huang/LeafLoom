// Actual browser acceptance against editor_ui_server.py's disposable vault.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('../desktop/node_modules/playwright-core');
const base=process.env.LEAFLOOM_EDITOR_TEST_URL||'http://127.0.0.1:18087';
if(new URL(base).hostname!=='127.0.0.1'||new URL(base).port==='18080')throw Error('Use the isolated editor fixture');
const note='Notes/Editor.md',out=path.resolve(__dirname,'../.cache/rich-editor-qa');
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6HgAAAAAASUVORK5CYII=','base64');
let browser;
(async()=>{
 browser=await chromium.launch({headless:true,channel:process.env.LEAFLOOM_BROWSER_CHANNEL||'msedge'});
 const page=await browser.newPage({viewport:{width:1380,height:960}}),errors=[],checks=[],failed=[];page.setDefaultTimeout(10000);fs.mkdirSync(out,{recursive:true});
 page.on('pageerror',error=>errors.push(error.message));
 page.on('dialog',dialog=>dialog.accept());
 page.on('console',message=>{if(message.type()==='error'&&!message.text().includes('Failed to load resource'))errors.push(message.text());});
 const prose=()=>page.locator('.document:visible .rich-prose');
 const api=(resource,body,method)=>page.evaluate(async({resource,body,method})=>{
  const fixture=await(await fetch('/api/editor-fixture')).json();if(!fixture.fixture)throw Error('Not an isolated fixture');
  const s=await(await fetch('/api/session')).json(),response=await fetch('/api/'+resource,{method:method||(body===undefined?'GET':'POST'),headers:{'Content-Type':'application/json','X-Vault-CSRF':s.csrf},body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok)throw Error(await response.text());return response.json();
 },{resource,body,method});
 const markdown=()=>page.evaluate(async note=>{
   const fixture=await(await fetch('/api/editor-fixture')).json();if(!fixture.fixture)throw Error('Unsafe fixture');
  const root=(await(await fetch('/api/session')).json()).config.root,key='draft:'+root+'\n'+note,draft=JSON.parse(localStorage.getItem(key)||'null');return (draft?.text??(await(await fetch('/api/file?path='+encodeURIComponent(note))).json()).text);
 },note);
 const normalized=async()=>(await markdown()).replace(/\r\n/g,'\n');
 const expectMarkdown=async expected=>{const end=Date.now()+6000;let value;do{value=await normalized();if(typeof expected==='string'?value===expected:expected(value))return value;await page.waitForTimeout(60);}while(Date.now()<end);assert.equal(value,typeof expected==='string'?expected:'matching predicate');};
 const reset=async text=>{
  const before=await api('file?path='+encodeURIComponent(note));await api('file',{path:note,root:before.root,etag:before.etag,text},'PUT');
  await page.evaluate(({root,note})=>{localStorage.removeItem('draft:'+root+'\n'+note);sessionStorage.removeItem('view:'+root+'\n'+note+':mode');}, {root:before.root,note});
  await page.reload();await prose().waitFor();await prose().evaluate(dom=>dom.editor.state.doc.check());
 };
 const select=async(needle,all=true)=>{await prose().evaluate((dom,{needle,all})=>{
  const editor=dom.editor;let found;
  editor.state.doc.descendants((node,pos)=>{if(found||!node.isText)return;const i=node.text.indexOf(needle);if(i>=0)found={from:pos+i,to:pos+i+(all?needle.length:0)};});
  if(!found)throw Error('Text not found: '+needle);editor.commands.setTextSelection(found);editor.view.focus();
 },{needle,all});};
 const end=()=>prose().evaluate(dom=>{const e=dom.editor;e.commands.setTextSelection(e.state.doc.content.size-1);e.view.focus();});
 const type=async text=>{await page.keyboard.insertText(text);};
 const idle=async()=>{await page.keyboard.press('Control+s');await page.locator('.document:visible .save-state').filter({hasText:'已保存'}).waitFor();};
 const check=async(name,fn)=>{if(process.env.LEAFLOOM_RICH_CHECK&&!new RegExp(process.env.LEAFLOOM_RICH_CHECK).test(name))return;try{await fn();checks.push(name);console.log('PASS '+name);}catch(error){failed.push({name,error:String(error)});console.error('FAIL '+name,{markdown:await markdown().catch(()=>''),html:(await prose().innerHTML().catch(()=>'')).slice(-1200),errors});await page.screenshot({path:path.join(out,'failure-'+failed.length+'.png')}).catch(()=>{});}finally{await page.unroute('**/api/upload?**');}};
 await page.goto(base+'/?note='+encodeURIComponent(note));await api('editor-fixture');await api('preferences',{locale:'zh-CN'},'PUT');await page.reload();await prose().waitFor();
 await check('open, focus and source inspection never rewrite Markdown',async()=>{
  const original='---\ntitle: Untouched\ncustom: [a, b]\n---\n\nA **bold** and _italic_ paragraph.\n\n**`code` and [[Target|Alias]] and $x^2$**\n\n- [ ] task\n  - nested\n\n| Name | Value |\n| :--- | ---: |\n| A | 2 |\n\n~~~js\nconst a = 1;\n~~~\n\n$$\nx^2\n$$\n\n```mermaid\ngraph LR\n A --> B\n```\n\n![[Target.md]]\n\n```dataview\nLIST\n```\n\n[reference]: https://example.com\n';
  await reset(original);const before=await api('file?path='+encodeURIComponent(note));
  await select('bold');await page.getByRole('toolbar',{name:'文字格式'}).waitFor();
  assert.equal(await prose().locator('strong').first().innerText(),'bold');assert.equal(await prose().locator('table').count(),1);
  await page.locator('.source-toggle').click();await page.locator('.cm-content').waitFor();
  assert.equal(await page.locator('.cm-content').evaluate(dom=>dom.cmTile.root.view.state.doc.toString()),before.text.replace(/\r\n/g,'\n'));
  await page.locator('.source-toggle').click();await prose().waitFor();await page.waitForTimeout(1100);
  const after=await api('file?path='+encodeURIComponent(note));assert.equal(after.text,before.text);assert.equal(after.etag,before.etag);
  assert.equal(await page.getByRole('button',{name:'编辑',exact:true}).count(),0);
 });
 await check('editing one block preserves all other original source',async()=>{
  const original='---\ntitle: Exact\n---\n\nSetext heading\n==============\n\nChange me.\n\n* one\n    * nested\n\n~~~python\nx = 1\n~~~\n\n[id]: https://example.com\n';
  await reset(original);const before=await markdown();await select('Change me.');await type('Changed.');await expectMarkdown(value=>value.includes('Changed.'));
  assert.equal(await markdown(),before.replace('Change me.','Changed.'));await idle();
 });
 await check('slash menu, keyboard choice and undo retain insertion boundaries',async()=>{
  await reset('');await end();await type('/h2');await page.getByRole('option',{name:/二级标题/}).waitFor();
  await page.keyboard.press('Enter');await expectMarkdown('## ');assert.equal(await prose().locator('h2').count(),1);
  await page.keyboard.press('Control+z');await expectMarkdown('/h2');await page.keyboard.press('Control+Shift+z');await expectMarkdown('## ');
  await type('Heading');assert.equal(await prose().locator('h2').innerText(),'Heading');
  await reset('keep /h2 tail');await select('/h2');await page.keyboard.press('ArrowRight');await page.getByRole('option',{name:/二级标题/}).waitFor();await page.keyboard.press('Enter');
  await expectMarkdown(value=>value.startsWith('keep  tail\n\n## '));
 });
 await check('slash guards, no results and Escape preserve literal text',async()=>{
  for(const value of ['https://example.com/','C:/notes/','`/todo`','```js\n/todo\n```','prefix ` /todo','$x /todo']){
   await reset(value);await end();await page.waitForTimeout(100);assert.equal(await page.locator('.rich-command-popup').count(),0,value);
  }
  await reset('');await end();await type('/nonsenseXYZ');await page.getByText('没有匹配的命令',{exact:true}).waitFor();await page.keyboard.press('Escape');assert.equal(await normalized(),'/nonsenseXYZ');
 });
 await check('format state, cross-block selection and URL paste',async()=>{
  await reset('first paragraph\n\nsecond paragraph');
  await prose().evaluate(dom=>{const e=dom.editor;e.commands.setTextSelection({from:1,to:e.state.doc.content.size-1});e.view.focus();});
  await page.getByRole('button',{name:'加粗',exact:true}).click();assert.equal(await prose().locator('strong').count(),2);
  assert.match(await normalized(),/\*\*first paragraph\*\*[\s\S]*\*\*second paragraph\*\*/);
  await page.getByRole('button',{name:'加粗',exact:true}).click();assert.equal(await prose().locator('strong').count(),0);
  await select('first');await prose().evaluate(dom=>{const data=new DataTransfer();data.setData('text/plain','https://example.com/a(b)');dom.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));});
  await expectMarkdown(value=>value.includes('[first](https://example.com/a%28b%29)'));
 });
 await check('Wiki completion keeps distinct paths and rendered labels',async()=>{
  await reset('');await end();await type('[[Target');await page.getByRole('option',{name:/Other\/Target.md/}).waitFor();assert.equal(await page.getByRole('option',{name:/Target.md/}).count(),2);
  await page.getByRole('option',{name:/Other\/Target.md/}).click();await expectMarkdown(value=>value.includes('[[Other/Target.md'));
  assert.equal(await prose().locator('a[data-wiki-target]').getAttribute('data-wiki-target'),'Other/Target.md');
 });
 await check('link panels confirm, edit, remove and cancel with original text',async()=>{
  await reset('label');await select('label');await page.keyboard.press('Control+Shift+k');await page.getByRole('dialog',{name:'网页链接',exact:true}).waitFor();
  await page.getByRole('textbox',{name:'链接地址',exact:true}).fill('https://example.com');await page.getByRole('button',{name:'保存',exact:true}).click();await expectMarkdown('[label](https://example.com)');
  await prose().locator('a').click();await page.locator('.rich-link-popup').waitFor();await page.getByRole('button',{name:'移除链接',exact:true}).click();await expectMarkdown('label');
  await reset('');await end();await type('/link');await page.getByRole('option',{name:/网页链接/}).click();await page.getByRole('button',{name:'取消',exact:true}).click();await expectMarkdown('/link');
 });
 await check('table cell input, Tab growth, alignment and row controls',async()=>{
  await reset('| Name | Value |\n| --- | --- |\n| A | 1 |');await prose().locator('td').first().click();await page.keyboard.press('Control+a');
  // Select only the current cell text; Ctrl+A normally selects the whole page.
  await select('A');await type('B');await expectMarkdown(value=>value.includes('| B | 1 |'));assert.equal(await prose().locator('table').count(),1);
  await prose().locator('td').last().click();await page.keyboard.press('Tab');assert.equal(await prose().locator('tr').count(),3);
  await page.getByRole('button',{name:'右对齐',exact:true}).click();await expectMarkdown(value=>value.includes('---:'));
  await page.getByRole('button',{name:'在右侧添加列',exact:true}).click();assert.equal(await prose().locator('tr').first().locator('th,td').count(),3);
  await page.getByRole('button',{name:'删除列',exact:true}).click();assert.equal(await prose().locator('tr').first().locator('th,td').count(),2);
 });
 await check('nested lists keep structure through indent and block moves',async()=>{
  await reset('- parent\n  - child\n\nlast');await select('child',false);await page.keyboard.press('Shift+Tab');assert.equal(await prose().locator('ul ul').count(),0);
  await page.keyboard.press('Tab');assert.equal(await prose().locator('ul ul').count(),1);
  await prose().locator('ul ul li').first().locator('p').first().hover({position:{x:10,y:10}});await page.getByRole('button',{name:'块操作',exact:true}).waitFor();await page.getByRole('button',{name:'块操作',exact:true}).click();
  await page.getByRole('menuitem',{name:'创建副本',exact:true}).click();assert.equal(((await normalized()).match(/child/g)||[]).length,2);
 });
 await check('block drag reorders complete rendered blocks',async()=>{
  await reset('# First\n\nMiddle paragraph\n\n# Last');await prose().locator('h1').first().hover();await page.locator('.rich-drag-grip').waitFor();
  await page.locator('.rich-drag-grip').dragTo(prose().locator('h1').last(),{targetPosition:{x:10,y:30}});await page.waitForTimeout(150);
  const value=await normalized();assert.ok(value.indexOf('# First')>value.indexOf('Middle paragraph'),value);
 });
 await check('source and page share undo, redo and cursor mapping',async()=>{
  await reset('start');await end();await type(' alpha');await expectMarkdown('start alpha');await page.locator('.source-toggle').click();await page.locator('.cm-content').waitFor();
  await page.locator('.cm-content').click();await page.keyboard.press('Control+End');await type(' beta');await expectMarkdown('start alpha beta');
  await page.locator('.source-toggle').click();await prose().waitFor();await prose().evaluate(dom=>dom.editor.view.focus());await page.keyboard.press('Control+z');await expectMarkdown('start alpha');
  await page.keyboard.press('Control+z');await expectMarkdown('start');await page.keyboard.press('Control+Shift+z');await expectMarkdown('start alpha');
 });
 await check('source edits and saves preserve mixed line endings outside the change',async()=>{
  const original='---\r\ntitle: Source\r\n---\r\n\r\nFirst\n\nChange me\r\n\r\nLast\n';await reset(original);const before=await markdown();assert.ok(before.includes('\r\n')&&before.replace(/\r\n/g,'').includes('\n'));
  await page.locator('.source-toggle').click();await page.locator('.cm-content').waitFor();await page.locator('.cm-content').evaluate(dom=>{const view=dom.cmTile.root.view,from=view.state.doc.toString().indexOf('Change me');view.dispatch({selection:{anchor:from,head:from+9}});view.focus();});
  await type('Changed');assert.equal(await markdown(),before.replace('Change me','Changed'));await idle();assert.equal((await api('file?path='+encodeURIComponent(note))).text,before.replace('Change me','Changed'));
  await page.locator('.source-toggle').click();await prose().waitFor();
 });
 await check('IME confirmation cannot execute a slash option',async()=>{
  await reset('');await end();await type('/h2');await page.getByRole('option',{name:/二级标题/}).waitFor();
  await prose().evaluate(dom=>{dom.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));dom.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',isComposing:true,bubbles:true,cancelable:true}));});
  assert.equal(await normalized(),'/h2');await prose().evaluate(dom=>dom.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true})));await page.waitForTimeout(100);await page.keyboard.press('Enter');await expectMarkdown('## ');
 });
 await check('image upload follows typing and inserts a relative image',async()=>{
  await reset('before ');await end();await page.route('**/api/upload?**',async route=>{await new Promise(resolve=>setTimeout(resolve,300));await route.continue();});
  await prose().evaluate((dom,bytes)=>{const data=new DataTransfer();data.items.add(new File([new Uint8Array(bytes)],'截图 (一).png',{type:'image/png'}));dom.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));},[...png]);
  await page.keyboard.press('Control+Home');await type('prefix ');await expectMarkdown(value=>value.includes('attachments/')&&value.startsWith('prefix '));
  await page.unroute('**/api/upload?**');assert.equal(await prose().locator('img[data-vault-src]').count(),1);
 });
 await check('upload failure and switching source cannot insert into a stale target',async()=>{
  await reset('keep');await end();await page.route('**/api/upload?**',route=>route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'fixture upload failed'})}));
  await prose().evaluate((dom,bytes)=>{const data=new DataTransfer();data.items.add(new File([new Uint8Array(bytes)],'fail.png',{type:'image/png'}));dom.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));},[...png]);
  await page.getByRole('status').filter({hasText:'fixture upload failed'}).waitFor();await expectMarkdown('keep');await page.unroute('**/api/upload?**');
  await page.route('**/api/upload?**',async route=>{await new Promise(resolve=>setTimeout(resolve,600));try{await route.continue();}catch{}});
  await prose().evaluate((dom,bytes)=>{const data=new DataTransfer();data.items.add(new File([new Uint8Array(bytes)],'cancel.png',{type:'image/png'}));dom.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));},[...png]);
  await page.locator('.source-toggle').click();await page.waitForTimeout(800);await expectMarkdown('keep');await page.unroute('**/api/upload?**');await page.locator('.source-toggle').click();await prose().waitFor();
 });
 await check('deleted upload targets and a changed vault cancel pending insertion',async()=>{
  const paste=()=>prose().evaluate((dom,bytes)=>{const data=new DataTransfer();data.items.add(new File([new Uint8Array(bytes)],'pending.png',{type:'image/png'}));dom.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));},[...png]);
  await reset('remove me');await end();await page.route('**/api/upload?**',async route=>{await new Promise(resolve=>setTimeout(resolve,600));try{await route.continue();}catch{}});await paste();
  await page.keyboard.press('Control+a');await page.keyboard.press('Backspace');await page.waitForTimeout(750);await expectMarkdown('');await page.unroute('**/api/upload?**');
  await reset('keep in original vault');await end();const fixture=await api('editor-fixture'),config=(await api('session')).config;
  await page.route('**/api/upload?**',async route=>{await new Promise(resolve=>setTimeout(resolve,600));try{await route.continue();}catch{}});await paste();
  try{await api('config',{root:fixture.other,include_roots:[''],exclude_roots:[]});await page.waitForFunction(()=>!document.querySelector('.rich-prose'));await page.waitForTimeout(750);}
  finally{await api('config',config);await page.unroute('**/api/upload?**');await page.goto(base+'/?note='+encodeURIComponent(note));await prose().waitFor();}
  assert.equal((await api('file?path='+encodeURIComponent(note))).text,'keep in original vault');
 });
 await check('equations and Mermaid remain rendered while edited through panels',async()=>{
  await reset('An equation $x^2$.\n\n$$\nx + y\n$$\n\n```mermaid\ngraph LR\n A --> B\n```');
  await prose().locator('.rich-inline-math .katex').waitFor();await prose().locator('.mermaid svg').waitFor();
  await prose().locator('[data-kind=math]').hover();await prose().locator('[data-kind=math]').getByRole('button',{name:'修改',exact:true}).click();
  await page.getByRole('textbox',{name:'公式内容',exact:true}).fill('a^2 + b^2');await page.getByRole('button',{name:'保存',exact:true}).click();await expectMarkdown(value=>value.includes('a^2 + b^2'));
  assert.equal(await prose().locator('[data-kind=math]').count(),1);
 });
 await check('long notes parse in a worker and only the edited block changes',async()=>{
  const workers=[];const worker=instance=>workers.push(instance.url());page.on('worker',worker);
  const value='# Long note\n\n'+Array.from({length:700},(_,i)=>'Paragraph '+i+': '+('local writing '.repeat(20))).join('\n\n');await reset(value);page.off('worker',worker);
  assert.ok(workers.some(url=>url.includes('rich-markdown.worker')),workers.join(','));const before=await markdown();await select('Paragraph 350:');await type('Edited paragraph 350:');await expectMarkdown(text=>text.includes('Edited paragraph 350:'));
  const after=await markdown(),oldBlock=/Paragraph 350:[^\r\n]*/.exec(before)[0],newBlock=/Edited paragraph 350:[^\r\n]*/.exec(after)[0];assert.equal(after.replace(newBlock,oldBlock),before);
  await idle();const external=after.replace('Paragraph 500:','Externally revised paragraph 500:');
  await page.route('**/rich-markdown.worker-*.js',async route=>{const response=await route.fetch();await route.fulfill({status:200,contentType:'application/javascript',headers:{'Cache-Control':'no-store'},body:'const __fixtureReply=self.postMessage.bind(self);self.postMessage=(...args)=>setTimeout(()=>__fixtureReply(...args),300);\n'+await response.text()});});
  try{
   const disk=await api('file?path='+encodeURIComponent(note));await api('file',{path:note,root:disk.root,etag:disk.etag,text:external},'PUT');
   await page.waitForFunction(()=>document.querySelector('.rich-prose')?.getAttribute('contenteditable')==='false');await type('must-not-replace-newer-content');
   await page.waitForFunction(()=>document.querySelector('.rich-prose')?.getAttribute('contenteditable')==='true');await expectMarkdown(text=>text.includes('Externally revised paragraph 500:'));await page.waitForTimeout(1100);assert.equal((await api('file?path='+encodeURIComponent(note))).text,external);
  }finally{await page.unroute('**/rich-markdown.worker-*.js');}
 });
 await check('localized visuals, narrow placement and stable editor identity',async()=>{
  await reset('# A calmer place to write\n\nWrite directly on the page. Select words to format them.\n\n- [ ] A useful task\n- [x] A completed task\n\n| Topic | Notes |\n| --- | --- |\n| Writing | Clear and local |\n\n');
  await prose().evaluate(dom=>{window.__fixtureEditor=dom.editor;});
  for(const locale of ['zh-CN','en','ja']){
   await page.locator('.sidebar-tools > button').first().click();await page.locator('.settings-modal .locale-picker select').selectOption(locale);await page.waitForFunction(locale=>document.documentElement.lang===locale,locale);await page.locator('.settings-page-heading button').last().click();
   await prose().waitFor();await end();await type('/');await page.locator('.rich-command-popup').waitFor();await page.screenshot({path:path.join(out,locale+'-slash.png')});
   await page.keyboard.press('Escape');await page.keyboard.press('Backspace');await prose().evaluate(dom=>{if(dom.editor!==window.__fixtureEditor)throw Error('Editor recreated');});
  }
  await page.setViewportSize({width:520,height:780});await end();await type('/');await page.locator('.rich-command-popup').waitFor();const rect=await page.locator('.rich-command-popup').boundingBox();assert.ok(rect.x>=0&&rect.x+rect.width<=520&&rect.y>=0&&rect.y+rect.height<=780);await page.screenshot({path:path.join(out,'narrow-slash.png')});
 });
 const report={browser:browser.version(),checks,failed,errors};fs.writeFileSync(path.join(out,'validation.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));assert.deepEqual(errors,[]);assert.deepEqual(failed,[]);
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>browser?.close());
