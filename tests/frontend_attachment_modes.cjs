// Production UI against disposable local files and a synthetic WebDAV server.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),net=require('node:net'),{spawn}=require('node:child_process');
const root=path.resolve(__dirname,'..'),output=path.join(root,'.cache/attachment-mode-ui');fs.mkdirSync(output,{recursive:true});
const {chromium}=require(path.join(root,'desktop/node_modules/playwright-core'));
const executable=process.env.CHROMIUM_PATH||['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'].find(p=>fs.existsSync(p));
let server,browser,page,logs='';
(async()=>{
 const port=await new Promise(resolve=>{const socket=net.createServer();socket.listen(0,'127.0.0.1',()=>{const port=socket.address().port;socket.close(()=>resolve(port));});});
 server=spawn(process.env.LEAFLOOM_TEST_PYTHON||path.join(root,'.cache/desktop-dev/.venv/bin/python'),['-u',path.join(root,'tests/attachment_workspace_server.py'),path.join(root,'vault_rag/static')],
  {cwd:root,env:{...process.env,LEAFLOOM_ATTACHMENT_TEST_PORT:String(port),LEAFLOOM_ATTACHMENT_MODE_TEST:'1'},stdio:['ignore','pipe','pipe']});
 server.stdout.on('data',data=>logs+=data);server.stderr.on('data',data=>logs+=data);
 let info;
 for(let i=0;i<150;i++){
  const line=logs.split('\n').find(line=>line.startsWith('{"fixture": true'));
  if(line){info=JSON.parse(line);try{await fetch(info.ui);break;}catch{}}
  if(server.exitCode!==null)throw new Error(logs.slice(-1500));
  await new Promise(resolve=>setTimeout(resolve,100));
 }
 assert.ok(info?.fixture,'fixture did not start');
 browser=await chromium.launch({executablePath:executable,headless:true,args:['--no-sandbox','--no-proxy-server']});
 page=await browser.newPage({baseURL:info.ui,viewport:{width:1440,height:960}});page.setDefaultTimeout(15000);
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.goto(info.ui+'/?view=attachments');
 const session=await (await page.request.get('/api/session')).json(),headers={'X-Vault-CSRF':session.csrf};
 const fixture=await (await page.request.get('/api/attachment-fixture')).json();
 const localSetup=()=>page.getByRole('button',{name:'Prepare local catalog',exact:true});
 const search=()=>page.getByRole('searchbox',{name:'File name or relative path'});
 const card=name=>page.locator('.aw-file-open').filter({hasText:name});
 async function searchFor(query,name){
  await search().fill(query);
  await page.waitForFunction(expected=>{const cards=document.querySelectorAll('.aw-card');return cards.length===1&&
   cards[0].querySelector('.aw-file-copy>strong')?.textContent===expected&&document.querySelector('.aw-file-scroll')?.getAttribute('aria-busy')==='false';},name);
 }
 async function showAll(){
  await page.getByRole('combobox',{name:'Attachment source',exact:true}).selectOption('all');await search().fill('');
  await page.waitForFunction(()=>document.querySelectorAll('.aw-card').length===100&&document.querySelector('.aw-file-scroll')?.getAttribute('aria-busy')==='false');
 }
 await localSetup().click();await page.locator('.aw-card').first().waitFor();
 assert.equal(await page.locator('.aw-tasks').count(),0);
 assert.deepEqual((await (await page.request.get('/api/attachments/migrations')).json()).jobs,[]);
 await page.getByText('New attachments save to: local workspace',{exact:true}).waitFor();
 await page.screenshot({path:path.join(output,'local-only.png'),fullPage:true});
 const enabled=await (await page.request.post('/api/attachment-fixture/server',{headers})).json();assert.ok(enabled.fixture);
 await page.reload();await page.getByText('New attachments save to server: Fictional NAS',{exact:true}).waitFor();
 await searchFor('Autumn collection','Autumn collection.png');
 await page.getByRole('combobox',{name:'Attachment source',exact:true}).selectOption('remote');
 await searchFor('Server specimen','Server specimen.bin');
 const opened=await page.request.get('/api/media?'+new URLSearchParams({root:fixture.root,path:enabled.remote_path}));
 assert.equal(await opened.text(),'fictional-server-original');
 await showAll();
 await page.screenshot({path:path.join(output,'server-default-existing-local-retained.png'),fullPage:true});
 async function chooseLocal(){
  await page.getByRole('button',{name:'Settings',exact:true}).click();
  await page.getByRole('button',{name:'Files and import',exact:true}).click();
  await page.getByRole('combobox',{name:'Save new attachments to',exact:true}).selectOption('local');
  const saved=page.waitForResponse(response=>response.url().endsWith('/api/attachments/storage')&&response.request().method()==='PUT'&&response.status()===200);
  await page.getByRole('button',{name:'Save attachment settings',exact:true}).click();await saved;
  await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(button=>button.textContent==='Save attachment settings'&&button.disabled));
  await page.locator('.settings-page-heading').getByRole('button',{name:'Close settings',exact:true}).click();
  await page.locator('.settings-modal').waitFor({state:'hidden'});
  await page.locator('.sidebar-shortcuts').getByRole('button',{name:'Attachments',exact:true}).click();
  await page.getByText('New attachments save to: local workspace',{exact:true}).waitFor();
 }
 await chooseLocal();await searchFor('Server specimen','Server specimen.bin');
 await page.getByRole('combobox',{name:'Attachment source',exact:true}).selectOption('local');
 await searchFor('Autumn collection','Autumn collection.png');await showAll();
 await page.screenshot({path:path.join(output,'local-default-existing-server-retained.png'),fullPage:true});
 // Fresh local folder with a server catalog: no automatic local scan or blocking onboarding.
 const switched=await page.request.post('/api/config',{headers,data:{root:fixture.other_root}});assert.ok(switched.ok());
 assert.ok((await page.request.post('/api/attachment-fixture/server',{headers})).ok());
 await page.goto(info.ui+'/?view=attachments');
 await page.getByText(/The local catalog is not ready/).waitFor();await card('Server specimen.bin').waitFor();
 assert.equal(await page.locator('.aw-onboarding').count(),0);
 const localTotal=page.locator('.aw-stats>div').filter({hasText:'Local attachment originals'});
 assert.equal(await localTotal.locator('strong').innerText(),'—');
 await chooseLocal();await card('Server specimen.bin').waitFor();await page.getByText(/The local catalog is not ready/).waitFor();
 await localSetup().click();await page.getByText(/The local catalog is not ready/).waitFor({state:'hidden'});
 await searchFor('Other local','Other local.bin');
 assert.equal((await (await page.request.get('/api/attachments/migrations')).json()).jobs.length,0);
 assert.deepEqual(errors,[]);
 console.log('Attachment mode UI passed: local setup, both switch directions, retained origins, no implicit migration, incomplete-local notice and explicit local setup.');
})().catch(async error=>{await page?.screenshot({path:path.join(output,'failure.png'),fullPage:true}).catch(()=>{});console.error(error);console.error(logs.slice(-1800));process.exitCode=1;})
 .finally(async()=>{await browser?.close();server?.kill('SIGINT');});
