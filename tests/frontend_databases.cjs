// Production frontend and API, disposable fictional files, no screenshots or user data.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),net=require('node:net'),{spawn}=require('node:child_process');
const root=path.resolve(__dirname,'..');const {chromium}=require(path.join(root,'desktop/node_modules/playwright-core'));
const executable=process.env.CHROMIUM_PATH||['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge','/usr/bin/chromium'].find(p=>fs.existsSync(p));
let server,browser,logs='';
(async()=>{
 const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
 server=spawn(process.env.LEAFLOOM_TEST_PYTHON||path.join(root,'.venv/bin/python'),['-u','tests/database_ui_server.py','vault_rag/static'],{cwd:root,env:{...process.env,LEAFLOOM_DATABASE_TEST_PORT:String(port)},stdio:['ignore','pipe','pipe']});server.stdout.on('data',d=>logs+=d);server.stderr.on('data',d=>logs+=d);
 let info;for(let i=0;i<150;i++){const line=logs.split('\n').find(l=>l.startsWith('{"fixture": true'));if(line){info=JSON.parse(line);try{await fetch(info.ui);break;}catch{}}if(server.exitCode!==null)throw new Error(logs);await new Promise(r=>setTimeout(r,100));}assert.ok(info,logs);
 browser=await chromium.launch({executablePath:executable,headless:true,args:['--no-sandbox','--no-proxy-server']});
 const page=await browser.newPage({baseURL:info.ui,viewport:{width:1500,height:1000}});page.setDefaultTimeout(12000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/?note=Showcase.base');await page.locator('.db-status').filter({hasText:'100 / 2400'}).waitFor();
 const config=await(await page.request.get('/api/bases/config?path=Showcase.base')).json();const session=await(await page.request.get('/api/session')).json();const headers={'X-Vault-CSRF':session.csrf};
 for(let i=0;i<2;i++){await page.getByRole('button',{name:'Load more',exact:true}).click();await page.locator('.db-status').filter({hasText:((i+2)*100)+' / 2400'}).waitFor();}assert.ok(await page.locator('.db-table-scroll tbody tr[data-index]').count()<100,'table should virtualize loaded records');
 // Editing a property, preserved body and side detail editor.
 const start=page.getByRole('textbox',{name:'Record 0000 Start date'}); // date inputs do not always expose textbox role
 const date=page.locator('input[aria-label="Record 0000 Start date"]');const initial=await date.inputValue();
 const tomorrow=new Date(Date.parse(initial+'T00:00:00Z')+86400000).toISOString().slice(0,10);
 await date.fill(tomorrow);await date.press('Escape');assert.equal(await date.inputValue(),initial);
 await date.fill(tomorrow);const noteBefore=await(await page.request.get('/api/file?path=Showcase/Record%200000.md')).json();
 await page.request.patch('/api/properties',{headers,data:{path:noteBefore.path,root:noteBefore.root,etag:noteBefore.etag,updates:{category:'External update'}}});
 await page.waitForResponse(r=>r.url().endsWith('/api/bases/query'));assert.equal(await date.inputValue(),tomorrow,'property draft must survive refresh');
 await date.focus();await page.locator('.db-toolbar button').first().focus();await page.locator('.db-error').first().waitFor();
 assert.equal((await(await page.request.get('/api/file?path=Showcase/Record%200000.md')).json()).metadata.start_date,initial,'stale property draft must not overwrite the file');
 await date.press('Escape');await page.locator('.db-table-scroll .text-link').first().click();
 await page.locator('.db-record-modal .rich-prose').waitFor();assert.match(await page.locator('.db-record-modal .rich-prose').innerText(),/Original body/);
 await page.locator('.db-record-modal>header button').click();
 // All four renderers, video entry and unavailable cover fallback.
 await page.locator('.db-view-tabs button').filter({hasText:'Gallery'}).click();await page.locator('.db-card').first().waitFor();
 for(let i=0;i<6;i++){await page.getByRole('button',{name:'Load more',exact:true}).click();await page.locator('.db-status').filter({hasText:((i+2)*100)+' / 2400'}).waitFor();}assert.ok(await page.locator('.db-card').count()<100,'gallery should virtualize card rows');
 await page.locator('.db-card').first().locator('img').evaluate(i=>i.decode());
 await page.locator('.db-card').nth(1).getByText('No cover',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Play video Record 0000'}).click();await page.locator('dialog video').waitFor();await page.locator('dialog>header button').click();
 await page.locator('.db-view-tabs button').filter({hasText:'List'}).click();await page.locator('.db-list-row').first().waitFor();
 await page.locator('.db-view-tabs button').filter({hasText:'Timeline'}).click();await page.locator('.db-date-bar').first().waitFor();
 const bar=page.locator('.db-date-bar').first(),box=await bar.boundingBox();await page.mouse.move(box.x+box.width/2,box.y+15);await page.mouse.down();await page.mouse.move(box.x+box.width/2+40,box.y+15,{steps:6});await page.mouse.up();
 await page.waitForFunction(async expected=>{const r=await(await fetch('/api/file?path='+encodeURIComponent('Showcase/Record 0000.md'))).json();return r.metadata.start_date!==expected;},initial);
 const after=await(await page.request.get('/api/file?path=Showcase/Record%200000.md')).json();assert.match(after.text,/Original body/);assert.equal((Date.parse(after.metadata.end_date)-Date.parse(after.metadata.start_date))/86400000,3);
 // Configuration persists and typed fields are available in the UI.
 await page.getByRole('button',{name:'Fields',exact:true}).click();await page.locator('dialog').getByRole('button',{name:'Add field',exact:true}).click();await page.getByRole('textbox',{name:'Property key (fixed after creation)'}).fill('score');await page.getByRole('textbox',{name:'Display name',exact:true}).fill('Score');await page.getByRole('combobox',{name:'Field type'}).selectOption('number');await page.locator('dialog').getByRole('button',{name:'Save',exact:true}).click();await page.waitForFunction(async()=>{const c=await(await fetch('/api/bases/config?path=Showcase.base')).json();return c.fields.score?.type==='number';});assert.equal(await page.locator('dialog [role=alert]').count(),0);await page.locator('dialog>header button').click();
 // Fixed view embed works in the editable parent; interacting does not edit parent source.
 await page.goto('/?note=Dashboard.md');await page.locator('.rich-special .db-card').first().waitFor();
 const parent=await(await page.request.get('/api/file?path=Dashboard.md')).json();
 await page.locator('.rich-special .db-search').click();await page.locator('.rich-special .db-toolbar input').fill('Record 0000');await page.locator('.rich-special .db-status').filter({hasText:'1 / 1'}).waitFor();
 assert.equal((await(await page.request.get('/api/file?path=Dashboard.md')).json()).text,parent.text);
 // A draft blocks property edits; browser keeps the draft rather than accepting stale metadata.
 await page.locator('.db-card-title').first().click();await page.locator('.db-record-modal .rich-prose').waitFor();
 let releaseSave;const saveGate=new Promise(resolve=>releaseSave=resolve);await page.route('**/api/file',async route=>{if(route.request().method()==='PUT')await saveGate;await route.continue();});const pendingSave=page.waitForRequest(r=>r.url().endsWith('/api/file')&&r.method()==='PUT');
 await page.locator('.db-record-modal .rich-prose').click();await page.keyboard.press('ControlOrMeta+End');await page.keyboard.type(' retained draft');await pendingSave;
 await page.locator('.db-record-modal input[aria-label="Record 0000 Start date"]').fill(initial);await page.locator('.db-record-actions button').first().focus();
 await page.locator('.db-record-modal').getByRole('alert').filter({hasText:'unsaved edits'}).first().waitFor();
 const completedSave=page.waitForResponse(r=>r.url().endsWith('/api/file')&&r.request().method()==='PUT');releaseSave();await completedSave;await page.unroute('**/api/file');
 await page.locator('.db-record-modal>header button').click();await page.goto('/?note=Showcase.base');await page.getByRole('button',{name:'New database',exact:true}).click();await page.getByRole('textbox',{name:'Database name',exact:true}).fill('Work');await page.locator('dialog').getByRole('button',{name:'Save',exact:true}).click();await page.locator('.db-header h1').filter({hasText:'Work'}).waitFor();
 await page.getByRole('button',{name:'Add record',exact:false}).click();await page.locator('dialog').getByRole('textbox',{name:'Title',exact:true}).fill('First task');await page.locator('dialog').getByRole('button',{name:'Save',exact:true}).click();await page.locator('.db-status').filter({hasText:'1 / 1'}).waitFor();
 // An open settings panel must not adopt a newer configuration revision silently.
 await page.getByRole('button',{name:'Layout',exact:true}).click();const fresh=await(await page.request.get('/api/bases/config?path=Work.base')).json();await page.request.post('/api/bases/commands',{headers,data:{path:'Work.base',workspace_revision:fresh.workspace_revision,expected_revision:fresh.revision,command:{type:'field.set',key:'external',field:{type:'text'}}}});
 await page.locator('dialog').getByRole('button',{name:'Save',exact:true}).click();await page.locator('dialog [role=alert]').filter({hasText:'Database changed'}).waitFor();
 assert.deepEqual(errors,[]);console.log('Database UI: four views, media, drag, fields, fixed embed, draft guard passed.');
})().catch(e=>{console.error(e.stack);console.error(logs.slice(-2000));process.exitCode=1;}).finally(async()=>{await browser?.close();server?.kill('SIGTERM');});
