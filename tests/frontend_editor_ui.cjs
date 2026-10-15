// Run against tests/editor_ui_server.py; Playwright may be supplied through NODE_PATH.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const base=process.env.LEAFLOOM_EDITOR_TEST_URL||'http://127.0.0.1:18087';
if(new URL(base).port==='18080')throw Error('Never run editor fixtures against the user service');
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6HgAAAAAASUVORK5CYII=','base64');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.LEAFLOOM_BROWSER_CHANNEL||'msedge'});
 const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[],passed=[];
 page.setDefaultTimeout(12000);
 page.on('pageerror',error=>errors.push(error.message));
 page.on('console',message=>{if(message.type()==='error'&&!message.text().includes('Failed to load resource'))errors.push(message.text());});
 const content=()=>page.locator('.document:visible .cm-content');
 // This mirrors EditorView.findFromDOM in the pinned CM version. Production
 // exposes no test globals; only the fixture inspects state for exact assertions.
 const text=()=>content().evaluate(dom=>dom.cmTile.root.view.state.doc.toString());
 const reset=async(value,anchor=value.length,head=anchor)=>{
  await content().evaluate((dom,{value,anchor,head})=>{const view=dom.cmTile.root.view;view.dispatch({changes:{from:0,to:view.state.doc.length,insert:value},selection:{anchor,head}});view.focus();},{value,anchor,head});
 };
 const select=async(anchor,head=anchor)=>content().evaluate((dom,{anchor,head})=>{const view=dom.cmTile.root.view;view.dispatch({selection:{anchor,head}});view.focus();},{anchor,head});
 const api=(resource,body,method)=>page.evaluate(async({resource,body,method})=>{
  const fixture=await(await fetch('/api/editor-fixture')).json();if(!fixture.fixture)throw Error('Not an isolated fixture');
  const session=await(await fetch('/api/session')).json();
  const response=await fetch('/api/'+resource,{method:method||(body===undefined?'GET':'POST'),headers:{'Content-Type':'application/json','X-Vault-CSRF':session.csrf},body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok)throw Error(await response.text());return response.json();
 },{resource,body,method});
 const expectText=async(expected)=>{await page.waitForFunction(expected=>document.querySelector('.document:not([hidden]) .cm-content')?.cmTile.root.view.state.doc.toString()===expected,expected,{timeout:5000});};
 const check=async(name,fn)=>{try{await fn();passed.push(name);console.log('PASS '+name);}catch(error){console.error('FAIL '+name,JSON.stringify({text:await text().catch(()=>''),errors}));throw error;}};
 try{
  if(process.env.LEAFLOOM_EDITOR_AUTH_URL)await page.goto(process.env.LEAFLOOM_EDITOR_AUTH_URL);
  await page.goto(base+'/?note=Notes%2FEditor.md');await api('editor-fixture');await page.getByRole('button',{name:'编辑',exact:true}).click();await content().waitFor();
  await check('slash keyboard insertion and undo',async()=>{
   await reset('');await page.keyboard.insertText('/h2');await page.getByRole('option',{name:/二级标题/}).waitFor();await page.waitForTimeout(120);await page.keyboard.press('Enter');await expectText('## ');
   await page.keyboard.press('Control+z');await expectText('/h2');await page.keyboard.press('Control+Shift+Z');await expectText('## ');
  });
  await check('context guards and Escape keep literal input',async()=>{
   for(const value of ['https://example.com/','C:/notes/','```js\n/todo\n```','---\ntitle: /todo\n---','$$\n/todo\n$$']){
    await reset(value,value.includes('/todo')?value.indexOf('/todo')+5:value.length);await page.waitForTimeout(220);assert.equal(await page.locator('.cm-tooltip-autocomplete:visible').count(),0,value);
   }
   await reset('');await page.keyboard.insertText('/');await page.locator('.cm-tooltip-autocomplete').waitFor();await page.keyboard.press('Escape');assert.equal(await text(),'/');
  });
  await check('format toolbar, toggle, link paste and source compatibility',async()=>{
   await reset('selected text',0,8);await page.getByRole('toolbar',{name:'文字格式'}).waitFor();await page.getByRole('button',{name:'加粗',exact:true}).click();await expectText('**selected** text');
   await page.getByRole('button',{name:'加粗',exact:true}).click();await expectText('selected text');
   await select(0,8);await content().evaluate(dom=>{const data=new DataTransfer();data.setData('text/plain','https://example.com/a(b)');dom.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));});
   await expectText('[selected](https://example.com/a%28b%29) text');
   await page.getByRole('button',{name:'源码',exact:true}).click();assert.equal(await content().innerText(),'[selected](https://example.com/a%28b%29) text');assert.equal(await page.locator('.editor-block-handle').count(),0);
   await page.getByRole('button',{name:'编辑',exact:true}).click();
  });
  await check('note completion disambiguates paths',async()=>{
   await reset('');await page.keyboard.insertText('[[Target');await page.getByRole('option',{name:/Notes\/Target.md/}).waitFor();
   assert.equal(await page.getByRole('option',{name:/Target.md/}).count(),2);
   await page.getByRole('option',{name:/Other\/Target.md/}).click();await expectText('[[Other/Target.md]]');
  });
  await check('link dialog confirms or cancels without opening file search',async()=>{
   await reset('label',0,5);await page.keyboard.press('Control+Shift+K');await page.getByRole('dialog',{name:'网页链接',exact:true}).waitFor();
   await page.getByRole('textbox',{name:'链接地址',exact:true}).fill('https://example.com/path');await page.getByRole('button',{name:'插入',exact:true}).click();await expectText('[label](https://example.com/path)');
   await reset('');await page.keyboard.insertText('/link');await page.getByRole('option',{name:/网页链接/}).waitFor();await page.waitForTimeout(100);await page.getByRole('option',{name:/网页链接/}).click();
   await page.getByRole('button',{name:'取消',exact:true}).click();assert.equal(await text(),'/link');
  });
  await check('whole-block operations and conversion',async()=>{
   const initial='first\n\n- parent\n  - child\n\nlast';await reset(initial,initial.indexOf('child'));
   await page.getByRole('button',{name:'块操作',exact:true}).click();await page.getByRole('menuitem',{name:'下移',exact:true}).click();await expectText('first\n\nlast\n\n- parent\n  - child');
   await page.keyboard.press('Control+z');await expectText(initial);
   await reset('a paragraph');await page.getByRole('button',{name:'块操作',exact:true}).click();await page.getByRole('menuitem',{name:'二级标题',exact:true}).click();await expectText('## a paragraph');
   await page.getByRole('button',{name:'插入内容',exact:true}).click();await page.getByRole('textbox',{name:'搜索命令…'}).fill('todo');await page.getByRole('menuitem',{name:'待办事项',exact:true}).click();await expectText('## a paragraph\n\n- [ ] ');
  });
  await check('file picker upload and readable relative image',async()=>{
   await reset('');await page.keyboard.insertText('/image');await page.getByRole('option',{name:/图片/}).waitFor();await page.waitForTimeout(120);
   const chooser=page.waitForEvent('filechooser');await page.keyboard.press('Enter');await(await chooser).setFiles({name:'测试 (1).png',mimeType:'image/png',buffer:png});
   await page.getByText('附件已插入',{exact:true}).waitFor();const value=await text();assert.match(value,/^!\[测试 \(1\)\.png\]\(attachments\/.*\.png\)$/);assert(!value.includes('/image'));
   await page.keyboard.press('Control+End');await page.keyboard.press('Enter');await page.keyboard.press('Enter');
   await page.locator('.live-widget img').waitFor();await page.waitForFunction(()=>{const img=document.querySelector('.live-widget img');return img?.complete&&img.naturalWidth>0;});
  });
  await check('paste image anchor follows typing and supports undo',async()=>{
   await reset('before\n\nafter',8);let release;const gate=new Promise(resolve=>release=resolve);let requested;
   const reached=new Promise(resolve=>requested=resolve);
   await page.route('**/api/upload?**',async route=>{requested();await gate;await route.continue().catch(()=>{});});
   await content().evaluate((dom,data)=>{const clip=new DataTransfer();clip.items.add(new File([Uint8Array.from(atob(data),c=>c.charCodeAt(0))],'paste.png',{type:'image/png'}));dom.dispatchEvent(new ClipboardEvent('paste',{clipboardData:clip,bubbles:true,cancelable:true}));},png.toString('base64'));
   await reached;assert.equal(await text(),'before\n\nafter');await select(0);await page.keyboard.insertText('new ');release();await page.getByText('附件已插入',{exact:true}).waitFor();
   await page.waitForFunction(()=>document.querySelector('.cm-content').cmTile.root.view.state.doc.toString().includes('attachments/'));
   const value=await text();assert(value.startsWith('new before\n\n![paste.png]'));assert(value.endsWith('\n\nafter'));
   await page.keyboard.press('Control+z');await expectText('new before\n\nafter');await page.unroute('**/api/upload?**');
  });
  await check('upload failure and deleted target keep the document',async()=>{
   await reset('safe');await page.route('**/api/upload?**',route=>route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'fixture upload failure'})}));
   await content().evaluate(dom=>{const clip=new DataTransfer();clip.items.add(new File(['x'],'failed.txt'));dom.dispatchEvent(new ClipboardEvent('paste',{clipboardData:clip,bubbles:true,cancelable:true}));});await page.getByText('fixture upload failure',{exact:true}).waitFor();assert.equal(await text(),'safe');await page.unroute('**/api/upload?**');
   await reset('target');let release;const gate=new Promise(resolve=>release=resolve);let requested;const reached=new Promise(resolve=>requested=resolve);
   await page.route('**/api/upload?**',async route=>{requested();await gate;await route.continue().catch(()=>{});});
   await content().evaluate(dom=>{const clip=new DataTransfer();clip.items.add(new File(['x'],'cancelled.txt'));dom.dispatchEvent(new ClipboardEvent('paste',{clipboardData:clip,bubbles:true,cancelable:true}));});await reached;await reset('');release();await page.getByText('附件插入已取消',{exact:true}).waitFor();assert.equal(await text(),'');await page.unroute('**/api/upload?**');
  });
  await check('language change keeps editor, selection and undo; narrow menu fits',async()=>{
   await reset('draft');await page.waitForTimeout(550);await content().evaluate(dom=>{window.fixtureEditor=dom.cmTile.root.view;});await page.keyboard.insertText('!');
   for(const [locale,label,settingsClose] of [['en','Heading 2','Close settings'],['ja','見出し 2','設定を閉じる'],['zh-CN','二级标题','关闭设置']]){
    await page.locator('.sidebar').getByRole('button',{name:/设置|Settings|設定/,exact:true}).click();
    await page.getByRole('combobox').filter({has:page.locator('option[value="ja"]')}).selectOption(locale);
    await page.getByRole('button',{name:settingsClose,exact:true}).first().click();
    assert(await content().evaluate(dom=>dom.cmTile.root.view===window.fixtureEditor));assert.equal(await text(),'draft!');
    await select(0,5);await page.getByRole('toolbar',{name:({'en':'Text formatting','ja':'文字の書式','zh-CN':'文字格式'})[locale]}).waitFor();
   }
   await content().click();await page.keyboard.press('Control+z');await expectText('draft');
   await page.setViewportSize({width:480,height:720});await reset('');await page.keyboard.insertText('/');await page.locator('.cm-tooltip-autocomplete').waitFor();
   const box=await page.locator('.cm-tooltip-autocomplete').boundingBox();assert(box.x>=0&&box.x+box.width<=481,JSON.stringify(box));await page.keyboard.press('Escape');await page.setViewportSize({width:1280,height:900});
  });
  await check('autosave writes plain Markdown',async()=>{
   await reset('# Saved\n\n- [ ] Task');await page.waitForFunction(async()=>{const response=await fetch('/api/file?path=Notes%2FEditor.md');return (await response.json()).text==='# Saved\n\n- [ ] Task';});
  });
  await check('file drop and IME Enter guard',async()=>{
   await reset('drop here');
   await content().evaluate(dom=>{const view=dom.cmTile.root.view,box=view.coordsAtPos(view.state.doc.length),data=new DataTransfer();data.items.add(new File(['attachment'],'drop.txt',{type:'text/plain'}));dom.dispatchEvent(new DragEvent('drop',{dataTransfer:data,clientX:box.left,clientY:(box.top+box.bottom)/2,bubbles:true,cancelable:true}));});
   await page.waitForFunction(()=>document.querySelector('.document:not([hidden]) .cm-content').cmTile.root.view.state.doc.toString().includes('[drop.txt](attachments/'));
   await page.keyboard.press('Control+z');await expectText('drop here');
   await reset('');await page.keyboard.insertText('/todo');await page.getByRole('option',{name:/待办事项/}).waitFor();
   const prevented=await content().evaluate(dom=>{dom.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));const event=new KeyboardEvent('keydown',{key:'Enter',code:'Enter',isComposing:true,bubbles:true,cancelable:true});dom.dispatchEvent(event);dom.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));return event.defaultPrevented;});
   assert.equal(prevented,false);assert.equal(await text(),'/todo');await page.keyboard.press('Escape');
  });
  await check('switching documents cancels pending attachment insertion',async()=>{
   await reset('switch-safe');let release;const gate=new Promise(resolve=>release=resolve);let requested;const reached=new Promise(resolve=>requested=resolve);
   await page.route('**/api/upload?**',async route=>{requested();await gate;await route.continue().catch(()=>{});});
   await content().evaluate(dom=>{const data=new DataTransfer();data.items.add(new File(['attachment'],'switch.txt'));dom.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));});await reached;
   await page.keyboard.press('Control+k');await page.getByRole('combobox',{name:'搜索文件',exact:true}).fill('Target');await page.getByRole('option',{name:/Other\/Target.md/}).click();release();
   await page.waitForTimeout(150);await page.keyboard.press('Control+k');await page.getByRole('combobox',{name:'搜索文件',exact:true}).fill('Editor');await page.getByRole('option',{name:/Notes\/Editor.md/}).click();
   await content().waitFor();assert.equal(await text(),'switch-safe');await page.unroute('**/api/upload?**');
  });
  assert.deepEqual(errors,[]);const report={browser:browser.version(),passed,errors};
  const output=path.resolve(__dirname,'../.cache/editor-tests/browser-validation.json');fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
