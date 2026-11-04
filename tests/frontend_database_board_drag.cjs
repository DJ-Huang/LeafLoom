// Repeat real pointer drags without remounting, including both save/refresh orders.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),net=require('node:net'),{spawn}=require('node:child_process');
const root=path.resolve(__dirname,'..'),asynchronous=!!process.env.LEAFLOOM_BOARD_ASYNC_CATALOG;
const {chromium}=require(path.join(root,'desktop/node_modules/playwright-core'));
const executable=process.env.CHROMIUM_PATH||['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge','/usr/bin/chromium'].find(p=>fs.existsSync(p));
let browser,server,page,logs='';
(async()=>{
 const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const value=s.address().port;s.close(()=>resolve(value));});});
 server=spawn(process.env.LEAFLOOM_TEST_PYTHON||path.join(root,'.venv/bin/python'),['-u','tests/database_board_server.py','vault_rag/static'],{cwd:root,env:{...process.env,LEAFLOOM_BOARD_TEST_PORT:String(port),LEAFLOOM_BOARD_DEFER_BASE_CATALOG:'1'},stdio:['ignore','pipe','pipe']});
 server.stdout.on('data',d=>logs+=d);server.stderr.on('data',d=>logs+=d);
 let info;for(let i=0;i<200;i++){const line=logs.split('\n').find(l=>l.startsWith('{"fixture": true'));if(line){info=JSON.parse(line);try{await fetch(info.ui);break;}catch{}}if(server.exitCode!==null)throw new Error(logs);await new Promise(r=>setTimeout(r,100));}assert.ok(info,logs);
 browser=await chromium.launch({executablePath:executable,headless:true,args:['--no-sandbox','--no-proxy-server']});
 page=await browser.newPage({baseURL:info.ui,viewport:{width:1480,height:1000}});page.setDefaultTimeout(10000);
 const errors=[],checks=[];page.on('pageerror',e=>errors.push(e.message));
 const column=value=>page.locator('.database:visible [data-board-group='+JSON.stringify(JSON.stringify(value))+']');
 const card=name=>page.locator('.database:visible [data-board-card='+JSON.stringify('Tasks/'+name+'.md')+']');
 const read=async name=>(await(await page.request.get('/api/file?path='+encodeURIComponent('Tasks/'+name+'.md'))).json());
 const config=async()=>(await(await page.request.get('/api/bases/config?path=Product%20roadmap.base')).json());
 const ready=async()=>{await page.locator('.database:visible .db-board-card').first().waitFor();await page.waitForFunction(()=>{const board=[...document.querySelectorAll('.database')].find(e=>e.getBoundingClientRect().width>0),buttons=board?.querySelectorAll('.db-board-title');return buttons?.length&&[...buttons].every(b=>!b.disabled);},{},{timeout:5000});};
 const drag=async(name,destination)=>{
  await ready();const source=card(name),target=typeof destination==='string'?column(destination):destination;await source.scrollIntoViewIfNeeded();const a=await source.boundingBox(),b=await target.boundingBox();
  await page.mouse.move(a.x+65,a.y+24);await page.mouse.down();await page.mouse.move(a.x+75,a.y+30,{steps:3});await page.locator('.db-board-drag-overlay').waitFor();await page.mouse.move(b.x+Math.min(b.width/2,120),b.y+(typeof destination==='string'?58:10),{steps:10});
  const response=page.waitForResponse(r=>r.url().endsWith('/api/bases/commands')&&r.request().postDataJSON()?.command?.type==='record.move');await page.mouse.up();const result=await response;if(!result.ok())console.error('MOVE FAILED',result.status(),await result.text(),JSON.stringify(result.request().postDataJSON()));return result;
 };
 await page.goto('/?note=Product%20roadmap.base');await ready();
 // File events can refresh every column while the HTTP command is still in flight.
 const refreshed=new Set();let savedRevision='',release,observed;
 const held=new Promise(resolve=>release=resolve),saved=new Promise(resolve=>observed=resolve);
 page.on('response',async r=>{if(!r.url().endsWith('/api/bases/query')||!r.ok())return;try{const body=await r.json(),key=r.request().postDataJSON()?.group_key;if(savedRevision&&key&&body.config_revision===savedRevision)refreshed.add(key);}catch{}});
 await page.route('**/api/bases/commands',async route=>{if(route.request().postDataJSON()?.command?.type!=='record.move')return route.continue();const response=await route.fetch(),result=await response.json();savedRevision=result.config_revision;observed(result);await held;await route.fulfill({response});});
 const first=drag('Define product scope','in-progress');const receipt=await saved;assert.ok(receipt.changed);
 try{for(let i=0;i<100&&!['open','in-progress','done'].every(v=>refreshed.has(JSON.stringify(v)));i++)await page.waitForTimeout(50);assert.ok(['open','in-progress','done'].every(v=>refreshed.has(JSON.stringify(v))),'columns must refresh before the command is acknowledged');}finally{release();}
 assert.ok((await first).ok());await page.unroute('**/api/bases/commands');await ready();
 for(const group of ['done','open','in-progress']){assert.ok((await drag('Define product scope',group)).ok());await ready();assert.equal((await read('Define product scope')).metadata.status,group);}
 checks.push('four consecutive cross-column drags work when columns refresh before the save reply');
 // Reordering changes only .base; its catalog notification may arrive later.
 const before=await read('Write acceptance criteria');
 for(let i=0;i<3;i++){
  const firstName=await column('open').locator('[data-board-card]').first().getAttribute('data-board-card');
  const moving=firstName==='Tasks/Write acceptance criteria.md'?'Research workflow':'Write acceptance criteria';
  const neighbor=firstName==='Tasks/Write acceptance criteria.md'?'Write acceptance criteria':path.basename(firstName,'.md');
  const response=await drag(moving,card(neighbor));assert.ok(response.ok(),await response.text());await ready();
  assert.equal(await column('open').locator('[data-board-card]').first().getAttribute('data-board-card'),'Tasks/'+moving+'.md');
 }
 assert.equal((await read('Write acceptance criteria')).etag,before.etag);
 checks.push(asynchronous?'three consecutive in-column drags use the production catalog queue without note writes':'three consecutive in-column drags work without a catalog version change or note writes');
 const undo=page.locator('.database:visible .db-board-actions').getByRole('button',{name:'Undo',exact:true});await undo.click();await ready();assert.ok((await drag('Write acceptance criteria',card('Draft documentation'))).ok());await ready();
 checks.push('undo releases the board for another drag');
 await page.locator('.database:visible .db-search').click();await page.locator('.database:visible .db-search input').fill('明确产品范围');await ready();
 for(const group of ['done','open','in-progress','open']){assert.ok((await drag('Define product scope',group)).ok());await ready();assert.equal((await read('Define product scope')).metadata.status,group);assert.equal(await column(group).locator('[data-board-card]').count(),1);assert.equal(await page.locator('.database:visible [data-board-card]').count(),1);}
 await page.locator('.database:visible .db-search input').fill('');await ready();
 checks.push('a single filtered card moves repeatedly across otherwise empty columns');
 // Run the same lifecycle inside the editable stable-view embed.
 await page.goto('/?note=Dashboard.md');await ready();const parent=await(await page.request.get('/api/file?path=Dashboard.md')).json();
 for(const group of ['done','open','in-progress']){assert.ok((await drag('Research workflow',group)).ok());await ready();assert.equal((await read('Research workflow')).metadata.status,group);}
 assert.equal((await(await page.request.get('/api/file?path=Dashboard.md')).json()).etag,parent.etag);
 checks.push('three consecutive embedded drags preserve the parent note');
 assert.equal(await page.locator('.database:visible .db-error,.database:visible .db-board-error').count(),0);assert.deepEqual(errors,[]);console.log(JSON.stringify({asynchronous,checks,errors},null,2));
})().catch(e=>{console.error(e.stack);console.error(logs.slice(-1500));process.exitCode=1;}).finally(async()=>{await browser?.close();server?.kill('SIGTERM');});
