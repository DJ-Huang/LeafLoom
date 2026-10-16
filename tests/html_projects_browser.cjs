// Focused real-browser contracts. No writes to an existing --vault.
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net');
const {spawn}=require('node:child_process');
const execFile=require('node:util').promisify(require('node:child_process').execFile);
const {chromium,firefox,webkit,_electron}=require('../desktop/node_modules/playwright-core');
const root=path.resolve(__dirname,'..');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function freePort(){const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const p=s.address().port;await new Promise(r=>s.close(r));return p;}
async function ready(url){for(let i=0;i<150;i++){try{if((await fetch(url+'/healthz')).ok)return;}catch{}await sleep(100);}throw new Error('Fixture server failed to start');}
async function systemLookup(hostname){
 let failure;
 for(let attempt=0;attempt<50;attempt++){
  try{return await require('node:dns').promises.lookup(hostname);}
  catch(error){failure=error;await sleep(200);}
 }
 throw new Error(`System DNS did not resolve ${hostname} after scoped resolver installation: ${failure?.message||'unknown error'}`);
}
async function loadUi(page,navigate){
 // A mounted React root precedes bootstrap completion. Finish these requests
 // before the next top-level navigation so WebKit does not report teardown
 // cancellations as page errors. Keep the pageerror assertion strict.
 const bootstrap=Promise.all(['tree','status','preferences'].map(async endpoint=>{
  const response=await page.waitForResponse(r=>new URL(r.url()).pathname==='/api/'+endpoint&&r.ok());
  const failure=await response.finished();assert.equal(failure,null);
 }));
 await Promise.all([bootstrap,navigate()]);await page.locator('#root main').waitFor();
}
async function checkDesign(page,url,downloadFile){
 await page.evaluate(url=>{const frame=document.createElement('iframe');frame.id='website-test';frame.src=url;frame.style='width:1500px;height:1100px';document.body.replaceChildren(frame);},url);
 const website=page.frameLocator('#website-test').frameLocator('iframe');
 await website.locator('[data-open="game"]').first().click();
 const board=website.frameLocator('#viewer-prototype');
 await board.locator('#artboard .game-header').waitFor();
 await website.locator('#layer-tree [role="treeitem"]').first().waitFor({timeout:20000});
 await board.locator('.game-header').click({position:{x:100,y:40}});
 await website.locator('#state-options [data-state]').nth(1).click();
 await website.locator('#state-options [data-state].active').filter({hasText:'教学'}).waitFor();
 if(downloadFile){
  await website.locator('#download-board').click();const deadline=Date.now()+5000;
  while(!fs.existsSync(downloadFile)&&Date.now()<deadline)await sleep(100);
  assert.equal(fs.readFileSync(downloadFile).subarray(0,8).toString('hex'),'89504e470d0a1a0a');
 }else{
  const downloaded=page.waitForEvent('download');await website.locator('#download-board').click();const download=await downloaded;
  assert.match(download.suggestedFilename(),/^萌宠安家-.*\.png$/);assert.equal(await download.failure(),null);
 }
 await website.locator('#state-options [data-state]').first().click();await board.locator('#artboard .game-header').waitFor();
 await website.getByRole('button',{name:'页面演示',exact:true}).click();
 await board.locator('.game-settings').click();await board.locator('.settings-modal').waitFor();
}
async function main(){
 const temp=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'leafloom-web-contracts-'))),port=await freePort();
 const python=process.env.LEAFLOOM_PYTHON||path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
 const args=[path.join(__dirname,'html_projects_server.py'),'--directory',temp,'--port',String(port)];
 const realVault=process.env.HTML_TEST_VAULT;if(realVault)args.push('--vault',realVault);
 if(process.env.HTML_TEST_DNS_ID){assert.equal(process.platform,'darwin');assert.equal(process.env.HTML_TEST_RESOLVER||'','');args.push('--identity',process.env.HTML_TEST_DNS_ID);}
 const log=fs.openSync(path.join(temp,'server.log'),'a');
 const server=spawn(python,args,{cwd:root,stdio:['ignore','ignore',log]});fs.closeSync(log);
 let browser,app,debugPage,resolverArgs;const checks=[];
 try{
  await ready('http://127.0.0.1:'+port);
  const info=JSON.parse(fs.readFileSync(path.join(temp,'info.json'))),token=fs.readFileSync(path.join(info.state,'auth-token'),'utf8').trim();
  if(process.platform==='darwin'&&process.env.HTML_TEST_RESOLVER){
   resolverArgs=['-m','vault_rag.local_dns','--identity',new URL(info.ui).hostname.split('.')[1],'--port',String(port),...(process.env.HTML_TEST_RESOLVER==='sudo'?['--sudo']:[])];
   const installed=await execFile(python,[...resolverArgs,'install'],{cwd:root,timeout:190000});assert.equal(JSON.parse(installed.stdout).configured,true);
   const lookup=await systemLookup(new URL(info.ui).hostname);assert.equal(lookup.address,'127.0.0.1');checks.push('macos-scoped-system-resolution');
  }
  const api=async(endpoint,body)=>{const r=await fetch(info.url+'/api/'+endpoint,{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();assert.ok(r.ok,JSON.stringify(d));return d;};
  const engine=process.env.HTML_TEST_BROWSER||'chrome';
  browser=await (engine==='firefox'?firefox:engine==='webkit'?webkit:chromium).launch({headless:true,...(engine==='firefox'?{firefoxUserPrefs:{'network.proxy.allow_hijacking_localhost':false}}:{}),...(['chrome','msedge'].includes(engine)?{channel:engine}:{})});
  const context=await browser.newContext({acceptDownloads:true,locale:'zh-CN'}),page=await context.newPage();const errors=[];debugPage=page;page.on('requestfailed',r=>console.error('Network failure: '+new URL(r.url()).hostname+new URL(r.url()).pathname+' '+r.failure()?.errorText));page.on('pageerror',e=>{errors.push(e.message);console.error('Browser page error:',e.stack);});
  // Seed the old origin without executing its migration page, then perform a real top-level handoff.
  await page.goto(info.url+'/healthz');
  await page.evaluate(()=>{localStorage.setItem('draft:fixture','unsaved original');sessionStorage.setItem('view:fixture','99');});
  if(realVault)await page.goto(info.url+'/');else await loadUi(page,()=>page.goto(info.url+'/'));
  await page.waitForURL(url=>url.origin===info.ui&&url.pathname==='/',{timeout:20000});
  assert.equal(await page.evaluate(()=>localStorage.getItem('draft:fixture')),'unsaved original');
  assert.equal(await page.evaluate(()=>sessionStorage.getItem('view:fixture')),'99');checks.push('top-level-storage-migration');
  if(!realVault){
   await page.evaluate(()=>localStorage.setItem('draft:fixture','newer destination'));
   await page.goto(info.url+'/healthz');await page.evaluate(()=>localStorage.setItem('draft:fixture','updated legacy draft'));
   await loadUi(page,()=>page.goto(info.url+'/'));
   await page.waitForURL(url=>url.origin===info.ui&&url.pathname==='/');
   assert.equal(await page.evaluate(()=>localStorage.getItem('draft:fixture')),'newer destination');
   assert.equal(await page.evaluate(()=>localStorage.getItem('leafloom:migration-conflicts')),'true');
   checks.push('migration-conflicts-retain-both');
  }
  if(realVault){
   const entry=process.env.HTML_TEST_ENTRY,directory=process.env.HTML_TEST_DIRECTORY;assert.ok(entry&&directory);
   const project=await api('html-projects',{root:info.root,directory,entry});
   const session=await api('html-sessions',{root:info.root,path:entry,project_id:project.id});
   await checkDesign(page,session.url);
   checks.push('actual-design-board-layers-selection-state-navigation-and-download');
   if(process.env.HTML_TEST_ELECTRON){
    // Read-only engine acceptance uses a minimal native host. The real desktop
    // lifecycle is covered separately with the disposable project fixture.
    const main=path.join(temp,'readonly-electron.cjs');fs.writeFileSync(main,`const {app,BrowserWindow}=require('electron');app.setPath('userData',${JSON.stringify(path.join(temp,'native-profile'))});app.whenReady().then(()=>{const w=new BrowserWindow({width:1600,height:1200,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true}});w.loadURL(${JSON.stringify(info.ui)});});`);
    app=await _electron.launch({executablePath:process.env.HTML_TEST_ELECTRON,args:[main]});
    const target=path.join(temp,'design-download.png');await app.evaluate(({session},p)=>session.defaultSession.on('will-download',(_event,item)=>item.setSavePath(p)),target);
    const nativePage=await app.firstWindow();await nativePage.waitForURL(info.ui+'/');
    const nativeSession=await api('html-sessions',{root:info.root,path:entry,project_id:project.id});
    await checkDesign(nativePage,nativeSession.url,target);checks.push('actual-design-electron-engine-and-download');await app.close();app=null;
   }
  }else{
   // The actual shared React UI registers a project and opens the same runtime in both hosts.
   await loadUi(page,()=>page.goto(info.ui+'/?note='+encodeURIComponent('site/index.html')));
   await page.getByRole('button',{name:/^(保存并打开|Save and open)$/}).click();
   const content=page.frameLocator('.html-preview-frame').frameLocator('iframe');
   await content.locator('#result').filter({hasText:'ready'}).waitFor({timeout:20000});
   assert.deepEqual(await content.locator('body').evaluate(()=>window.fixture),{value:42,worker:43,wasm:true,storage:'retained',indexedDB:true,secure:true});
   assert.equal(await content.locator('#heading').evaluate(e=>getComputedStyle(e).color),'rgb(23, 45, 67)');
   await content.frameLocator('#nested').getByRole('button',{name:'Nested board'}).waitFor();
   assert.equal(await content.locator('body').evaluate(()=>{try{void top.leafloomDesktop;return false}catch{return true}}),true);
   const download=page.waitForEvent('download');await content.locator('#download').click();assert.equal((await download).suggestedFilename(),'file.bin');
   checks.push('shared-react-project-registration','module-fetch-worker-wasm-storage-serviceworker','nested-frame-and-origin-isolation','project-download');
   const before=await content.locator('body').evaluate(()=>location.origin);
   await page.getByRole('button',{name:/^(刷新|Refresh)$/}).click();await content.locator('#result').filter({hasText:'ready'}).waitFor();
   assert.equal(await content.locator('body').evaluate(()=>location.origin),before);checks.push('stable-project-origin');
   const standaloneOpened=page.waitForEvent('popup');await page.locator('.html-preview-toolbar a[target="_blank"]').click();const standalone=await standaloneOpened;
   await standalone.frameLocator('iframe').locator('#result').filter({hasText:'ready'}).waitFor();
   assert.equal(await standalone.frameLocator('iframe').locator('body').evaluate(()=>location.origin),before);await standalone.close();checks.push('standalone-tab-with-cookie-blocking');
   const disk=await (await fetch(info.url+'/api/file?path=site%2Findex.html',{headers:{Authorization:'Bearer '+token}})).json();
   await page.evaluate(({root,etag})=>localStorage.setItem('draft:'+root+'\nsite/index.html',JSON.stringify({text:'<h1 id="draft-content">Unsaved HTML</h1>',etag,manualSave:true})),{root:info.root,etag:disk.etag});
   await loadUi(page,()=>page.reload());const draftContent=page.frameLocator('.html-preview-frame').frameLocator('iframe');
   await draftContent.locator('#draft-content').waitFor();
   assert.notEqual(await draftContent.locator('body').evaluate(()=>location.origin),before);
   assert.equal(fs.readFileSync(path.join(info.root,'site/index.html'),'utf8'),disk.text);
   checks.push('unsaved-draft-origin-and-disk-preservation');

  }
  assert.deepEqual(errors,[]);
  await browser.close();browser=null;
  if(process.env.HTML_TEST_ELECTRON&&!realVault){
   server.kill();await new Promise(r=>server.once('exit',r));
   fs.writeFileSync(path.join(info.state,'desktop-preferences.json'),JSON.stringify({openAtLogin:false}));
   app=await _electron.launch({executablePath:process.env.HTML_TEST_ELECTRON,args:[path.join(root,'desktop')],env:{...process.env,LEAFLOOM_PYTHON:python,VAULT_RAG_HOME:info.state,LEAFLOOM_REGISTRATION_HOME:path.join(temp,'registration')},timeout:40000});
   await app.evaluate(({session},downloadPath)=>{session.defaultSession.on('will-download',(_event,item)=>item.setSavePath(downloadPath));},path.join(temp,'electron-download.bin'));
   const p=await app.firstWindow();p.on('pageerror',e=>console.error('Electron page error: '+e.message));p.on('console',m=>{if(m.type()==='error')console.error('Electron console: '+m.text());});await p.waitForURL(url=>url.origin===info.ui&&url.pathname==='/',{timeout:30000});
   await p.goto(info.ui+'/?note='+encodeURIComponent('site/index.html'));

   const content=p.frameLocator('.html-preview-frame').frameLocator('iframe');await content.locator('#result').filter({hasText:'ready'}).waitFor({timeout:20000});
   assert.equal(await content.locator('body').evaluate(()=>typeof window.leafloomDesktop),'undefined');
   await content.locator('#download').click();
   const downloadPath=path.join(temp,'electron-download.bin'),deadline=Date.now()+5000;
   while(!fs.existsSync(downloadPath)&&Date.now()<deadline)await sleep(100);
   assert.equal(fs.readFileSync(downloadPath,'utf8'),'download fixture');
   checks.push('actual-electron-shared-ui-runtime-and-download');
   await p.evaluate(()=>window.leafloomDesktop.quit());await new Promise(r=>app.process().exitCode!==null?r():app.process().once('exit',r));app=null;
  }
  console.log(JSON.stringify({browser:engine,checks}));
 }finally{if(app){try{for(const p of app.windows())console.error('Electron state',p.url(),await p.locator('body').innerText({timeout:2000}));}catch{}app.process().kill('SIGKILL');}if(browser){try{console.error('Browser state: '+debugPage.url(),await debugPage.locator('body').innerText({timeout:2000}));}catch{}await browser.close();}try{if(resolverArgs){const removed=await execFile(python,[...resolverArgs,'remove'],{cwd:root,timeout:190000});assert.equal(JSON.parse(removed.stdout).configured,false);console.error('Scoped test resolver removed.');}}finally{if(server.exitCode===null)server.kill();console.error('Browser fixture: '+temp);}}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
