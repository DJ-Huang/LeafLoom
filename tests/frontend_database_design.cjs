// Visual acceptance on fictional content; never opens the user's vault or application.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),net=require('node:net'),{spawn}=require('node:child_process');
const root=path.resolve(__dirname,'..'),output=path.join(root,'.cache/database-design');fs.mkdirSync(output,{recursive:true});
const {chromium}=require(path.join(root,'desktop/node_modules/playwright-core'));
const executable=process.env.CHROMIUM_PATH||['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge','/usr/bin/chromium'].find(p=>fs.existsSync(p));
let browser,server,logs='';
(async()=>{
 const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
 server=spawn(process.env.LEAFLOOM_TEST_PYTHON||path.join(root,'.venv/bin/python'),['-u','tests/database_ui_server.py','vault_rag/static'],{cwd:root,env:{...process.env,LEAFLOOM_DATABASE_TEST_PORT:String(port),LEAFLOOM_DATABASE_DESIGN:'1'},stdio:['ignore','pipe','pipe']});server.stdout.on('data',d=>logs+=d);server.stderr.on('data',d=>logs+=d);
 let info;for(let i=0;i<150;i++){const line=logs.split('\n').find(l=>l.startsWith('{"fixture": true'));if(line){info=JSON.parse(line);try{await fetch(info.ui);break;}catch{}}if(server.exitCode!==null)throw new Error(logs);await new Promise(r=>setTimeout(r,100));}assert.ok(info,logs);
 browser=await chromium.launch({executablePath:executable,headless:true,args:['--no-sandbox','--no-proxy-server']});
 const page=await browser.newPage({baseURL:info.ui,viewport:{width:1480,height:980},deviceScaleFactor:1});page.setDefaultTimeout(12000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const capture=async name=>{await page.screenshot({path:path.join(output,name+'.png'),fullPage:true});};
 await page.goto('/?note=Studio%20notes.base');await page.locator('.db-status').filter({hasText:'8 / 8'}).waitFor();
 assert.deepEqual(await page.locator('.db-view-tabs button>span').allTextContents(),['Table','List','Gallery','Timeline']);assert.equal(await page.locator('.database input[type=range]').count(),0);
 const session=await(await page.request.get('/api/session')).json(),headers={'X-Vault-CSRF':session.csrf};
 await capture('table-en');
 // Resize is a column-edge interaction, with a keyboard alternative and persistent width.
 const separator=page.getByRole('separator',{name:'Column width title',exact:true});const before=Number(await separator.getAttribute('aria-valuenow'));await separator.focus();await separator.press('ArrowRight');
 await page.waitForFunction(async expected=>{const c=await(await fetch('/api/bases/config?path=Studio%20notes.base')).json();return c.views[0].leafloom.widths.title===expected;},before+16);
 await page.waitForFunction(()=>!document.querySelector('.db-new-button').disabled);const edge=await separator.boundingBox();await page.mouse.move(edge.x+edge.width/2,edge.y+edge.height/2);await page.mouse.down();await page.mouse.move(edge.x+edge.width/2+32,edge.y+edge.height/2,{steps:5});await page.mouse.up();await page.waitForFunction(async expected=>{const c=await(await fetch('/api/bases/config?path=Studio%20notes.base')).json();return c.views[0].leafloom.widths.title===expected;},before+48);
 await page.getByRole('button',{name:'Fields',exact:true}).click();await page.locator('.db-property-list').waitFor();const bounds=await page.locator('.db-settings-modal').boundingBox();assert.ok(bounds.width<=420&&bounds.x>=0&&bounds.x+bounds.width<=1480);await capture('properties-en');await page.locator('dialog>header button').click();
 await page.locator('.db-view-tabs button').filter({hasText:'Gallery'}).click();await page.locator('.db-card img').first().evaluate(i=>i.decode());await capture('gallery-en');
 await page.locator('.db-view-tabs button').filter({hasText:'List'}).click();await page.locator('.db-list-row').first().waitFor();await capture('list-en');
 await page.locator('.db-view-tabs button').filter({hasText:'Timeline'}).click();await page.locator('.db-date-bar').first().waitFor();await capture('timeline-en');
 await page.request.put('/api/preferences',{headers,data:{locale:'zh-CN'}});await page.goto('/?note=Ideas.base');await page.locator('.db-status').filter({hasText:'1 / 1'}).waitFor();await page.locator('.db-view-tabs').getByText('表格',{exact:true}).waitFor();
 assert.equal(await page.locator('.db-date-cell input').first().evaluate(e=>getComputedStyle(e).opacity),'0');await capture('sparse-zh');
 await page.goto('/?note=Studio%20notes.base');await page.locator('.db-status').filter({hasText:'8 / 8'}).waitFor();await capture('table-zh');
 await page.locator('.db-view-tabs button').filter({hasText:'画廊'}).click();await page.locator('.db-card img').first().evaluate(i=>i.decode());await capture('gallery-zh');
 await page.setViewportSize({width:390,height:844});await page.waitForTimeout(200);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'page must not overflow on mobile');await capture('gallery-mobile-zh');
 const mobileQuery=page.waitForResponse(r=>r.url().endsWith('/api/bases/query'));await page.locator('.db-view-tabs button').filter({hasText:'表格'}).click();await(await mobileQuery).finished();await page.locator('.db-status').filter({hasText:'8 / 8'}).waitFor();await page.locator('.db-title-cell').first().waitFor();assert.ok(await page.locator('.db-title-cell').count()>0);await capture('table-mobile-zh');
 assert.deepEqual(errors,[]);console.log('Database visual acceptance passed. Screenshots: '+output);
})().catch(e=>{console.error(e.stack);console.error(logs.slice(-2200));process.exitCode=1;}).finally(async()=>{await browser?.close();server?.kill('SIGTERM');});
