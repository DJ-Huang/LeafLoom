// Browser E2E. Requires tests/editor_ui_server.py on 127.0.0.1:18087.
// The server creates a fresh disposable vault; never point at port 18080.
const assert=require('node:assert/strict');
const {chromium}=require('../desktop/node_modules/playwright-core');
const base=process.env.LEAFLOOM_EDITOR_TEST_URL||'http://127.0.0.1:18087';
if(new URL(base).hostname!=='127.0.0.1'||new URL(base).port==='18080')throw Error('Use the isolated test server only');
const note='Notes/Editor.md';
let browser;
(async()=>{
 browser=await chromium.launch({headless:true,channel:process.env.LEAFLOOM_BROWSER_CHANNEL||'msedge'});
 const page=await browser.newPage({viewport:{width:1380,height:960}});
 const errors=[];page.setDefaultTimeout(11000);
 page.on('pageerror',e=>errors.push(e.message));
 page.on('dialog',dialog=>dialog.accept());
 const api=async(resource,body,method)=>page.evaluate(async({resource,body,method})=>{
  const fixture=await(await fetch('/api/editor-fixture')).json();
  if(!fixture.fixture)throw Error('Expected isolated editor fixture');
  const session=await(await fetch('/api/session')).json();
  const response=await fetch('/api/'+resource,{method:method||(!body?'GET':'POST'),
   headers:{'Content-Type':'application/json','X-Vault-CSRF':session.csrf},
   body:body?JSON.stringify(body):undefined});
  if(!response.ok)throw Error(response.status+' '+await response.text());
  return response.json();
 },{resource,body,method});
 const root=async()=>(await api('session')).config.root;
 const url='annotations?path='+encodeURIComponent(note)+'&root=';
 const rows=async()=>(await api(url+encodeURIComponent(await root()))).annotations;
 const waitRows=async(count)=>{
  const end=Date.now()+6000;
  do{const values=await rows();if(values.length===count)return values;await page.waitForTimeout(100);}while(Date.now()<end);
  throw Error('Expected '+count+' annotations, got '+(await rows()).length);
 };
 const prose=()=>page.locator('.document:visible .rich-prose');
 const select=async(needle)=>{
  await prose().evaluate((dom,needle)=>{
   const editor=dom.editor;let found;
   editor.state.doc.descendants((node,pos)=>{
    if(found||!node.isText)return;
    const at=node.text.indexOf(needle);if(at>=0)found={from:pos+at,to:pos+at+needle.length};
   });
   if(!found)throw Error('Missing text '+needle);
   editor.commands.setTextSelection(found);editor.view.focus();
  },needle);
  await page.locator('.rich-format-popup').waitFor();
 };
 await page.goto(base+'/?note='+encodeURIComponent(note));
 await prose().waitFor();
 assert.equal((await api('editor-fixture')).fixture,true);
 await api('preferences',{locale:'zh-CN'},'PUT');
 await page.reload();await prose().waitFor();
 const existing=await api('file?path='+encodeURIComponent(note));
 if(existing.text!=='Editor fixture\\n\\n'){
  await api('file',{path:note,root:existing.root,etag:existing.etag,text:'Editor fixture\\n\\n'},'PUT');
 }
 for(const item of await rows()){
  await api('annotations/'+item.id,{root:await root(),path:note,revision:item.revision},'DELETE');
 }
 await page.reload();await prose().waitFor();
 const before=await api('file?path='+encodeURIComponent(note));
 assert.ok(before.text.includes('Editor fixture'));
 await select('Editor');
 await page.locator('.rich-format-popup .leafloom-color-button.leafloom-yellow').click();
 let a=await waitRows(1);
 assert.equal(a[0].type,'highlight');assert.equal(a[0].anchor.exact,'Editor');
 await page.locator('.document-toolbar [title="评论"]').click();
 await page.getByRole('button',{name:/页面评论/}).click();
 await page.locator('.leafloom-draft textarea').fill('Overall note review');
 await page.getByRole('button',{name:'提交评论'}).click();
 a=await waitRows(2);
 assert.equal(a[1].anchor,null);assert.equal(a[1].messages[0].content,'Overall note review');
 await select('fixture');
 await page.locator('.rich-format-popup [aria-label="添加评论"]').click();
 await page.locator('.leafloom-draft textarea').fill('Explain this fixture');
 await page.getByRole('button',{name:'提交评论'}).click();
 a=await waitRows(3);
 assert.equal(a[2].type,'comment');assert.equal(a[2].anchor.exact,'fixture');
 await page.locator('[data-annotation-card="'+a[2].id+'"] textarea[aria-label="回复评论"]').fill('Noted');
 await page.locator('[data-annotation-card="'+a[2].id+'"] button').filter({hasText:'回复'}).click();
 await page.waitForFunction(async()=>{const session=await(await fetch('/api/session')).json(),r=await fetch('/api/annotations?root='+encodeURIComponent(session.config.root)+'&path=Notes%2FEditor.md'),body=await r.json();return body.annotations?.[2]?.messages?.length===2;});
 a=await rows();assert.equal(a[2].messages.length,2);
 await page.locator('[data-annotation-card="'+a[2].id+'"] button').filter({hasText:'标记为已解决'}).click();
 await page.waitForFunction(async()=>{const session=await(await fetch('/api/session')).json(),r=await fetch('/api/annotations?root='+encodeURIComponent(session.config.root)+'&path=Notes%2FEditor.md'),body=await r.json();return body.annotations?.[2]?.status==='resolved';});
 await page.locator('.source-toggle').click();
 await page.locator('.source-editor .leafloom-annotation').first().waitFor();
 assert.ok(await page.locator('.source-editor .leafloom-annotation').count()>=2);
 await page.locator('.source-toggle').click();await prose().waitFor();
 const after=await api('file?path='+encodeURIComponent(note));
 assert.equal(before.etag,after.etag,'Annotations must not modify Markdown bytes');
 assert.equal(before.text,after.text);
 // Saved quote follows a source insertion before it, without writing Markdown syntax.
 await api('file',{path:note,root:before.root,etag:after.etag,text:'Prefix before text. '+after.text},'PUT');
 await page.reload();await prose().waitFor();
 const highlighted=prose().locator('[data-leafloom-annotation="'+a[0].id+'"]');
 await highlighted.first().waitFor();
 assert.ok((await highlighted.first().innerText()).includes('Editor'));
 // A removed quote is shown as detached, never silently rebound to another range.
 const newer=await api('file?path='+encodeURIComponent(note));
 await api('file',{path:note,root:before.root,etag:newer.etag,text:newer.text.replace('Editor fixture','No matching quoted text')},'PUT');
 await page.reload();await prose().waitFor();
 await page.locator('.document-toolbar [title="评论"]').click();
 await page.getByText('定位已失效').first().waitFor();
 assert.deepEqual(errors,[],'Browser errors: '+errors.join('\n'));
 console.log('PASS annotations E2E: highlight, page and inline threads, replies, status, source decorations, persistence, quote reattachment and detachment');
})().catch(e=>{console.error(e.stack||String(e));process.exitCode=1;}).finally(async()=>browser?.close());
