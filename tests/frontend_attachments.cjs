// Real API + production frontend in a disposable workspace. No user service/data.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),net=require('node:net'),{spawn}=require('node:child_process');
const root=path.resolve(__dirname,'..'),output=path.join(root,'.cache/attachment-workspace');fs.mkdirSync(output,{recursive:true});
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(root,'desktop/node_modules/playwright-core'));
const executable=process.env.CHROMIUM_PATH||['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge','/usr/bin/chromium'].find(p=>fs.existsSync(p));
let server,browser,logs='';
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
 const port=await new Promise(resolve=>{const socket=net.createServer();socket.listen(0,'127.0.0.1',()=>{const p=socket.address().port;socket.close(()=>resolve(p));});});
 const python=process.env.LEAFLOOM_TEST_PYTHON||path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
 server=spawn(python,['-u',path.join(root,'tests/attachment_workspace_server.py'),path.join(root,'vault_rag/static')],{cwd:root,env:{...process.env,LEAFLOOM_ATTACHMENT_TEST_PORT:String(port)},stdio:['ignore','pipe','pipe']});
 server.stdout.on('data',data=>{logs+=data;});server.stderr.on('data',data=>{logs+=data;});
 let info;
 for(let i=0;i<150;i++){
  const line=logs.split('\n').find(line=>line.startsWith('{"fixture": true'));
  if(line){info=JSON.parse(line);try{await fetch('http://127.0.0.1:'+port+'/');break;}catch{}}
  if(server.exitCode!==null)throw new Error('Fixture exited: '+logs.slice(-1500));
  await pause(100);
 }
 assert.ok(info?.fixture,'fixture startup failed: '+logs.slice(-1500));
 browser=await chromium.launch({executablePath:executable,headless:true,args:['--no-sandbox','--no-proxy-server']});
 const page=await browser.newPage({baseURL:info.ui,viewport:{width:1440,height:960},deviceScaleFactor:1});page.setDefaultTimeout(12000);
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 let holdPlan=false,plans=0,executions=0;
 await page.route('**/api/attachments/migrations',async route=>{
  if(route.request().method()==='POST'){
   plans++;const response=await route.fetch();holdPlan=true;await route.fulfill({response});
  }else{
   const response=await route.fetch();const data=await response.json();
   if(holdPlan&&data.jobs.length)data.jobs=data.jobs.map((job,index)=>index?job:{...job,state:'planning',phase:'planning',stage:'references',progress:{done:5522,total:0}});
   await route.fulfill({json:data});
  }
 });
 page.on('request',request=>{if(request.method()==='POST'&&/\/migrations\/[^/]+\/execute$/.test(new URL(request.url()).pathname))executions++;});
 await page.goto(info.ui+'/?view=attachments');
 const initialize=page.getByRole('button',{name:'Prepare local catalog',exact:true});await initialize.waitFor();assert.equal(await initialize.count(),1);
 assert.equal(await page.locator('.aw-card').count(),0);assert.equal(plans,0);
 await page.screenshot({path:path.join(output,'onboarding-en.png'),fullPage:true});
 await initialize.click();await page.locator('.aw-card').first().waitFor();
 assert.equal(plans,0);assert.equal(executions,0);assert.equal(await page.locator('.aw-tasks').count(),0);
 await page.getByRole('button',{name:'Organize local attachments',exact:true}).click();
 await page.getByRole('button',{name:'Preview local organization',exact:true}).click();await page.locator('.aw-tasks').waitFor();
 await page.getByText('5,522 items processed',{exact:true}).waitFor();
 assert.equal(await page.locator('.aw-tasks progress').first().getAttribute('value'),null);
 assert.equal(await page.locator('.aw-tasks').getByText(/5,522\s*\/\s*0/).count(),0);assert.equal(plans,1);assert.equal(executions,0);
 await page.reload();await page.getByRole('button',{name:'Tasks',exact:true}).click();
 await page.getByText('5,522 items processed',{exact:true}).waitFor();assert.equal(plans,1);
 holdPlan=false;await page.locator('.aw-job-state.ready').waitFor();
 await page.locator('.aw-tasks').getByRole('button',{name:'Close',exact:true}).click();
 await page.locator('.aw-card').first().waitFor();assert.equal(await page.locator('.aw-card').count(),100);
 const fixture=await (await page.request.get('/api/attachment-fixture')).json();assert.ok(fixture.fixture);
 const session=await (await page.request.get('/api/session')).json();const headers={'X-Vault-CSRF':session.csrf};
 const search=page.getByRole('searchbox',{name:'File name or relative path'});
 const card=name=>page.locator('.aw-file-open').filter({hasText:name});
 await card('Autumn collection.png').click();await page.locator('.aw-preview .aw-image-stage img').waitFor();
 await page.locator('.aw-preview img').evaluate(image=>image.decode());
 await page.screenshot({path:path.join(output,'workspace-en-desktop.png'),fullPage:true});
 assert.match(await page.locator('.aw-preview img').getAttribute('src'),/root=/);
 // Filename/path search, type filtering and stable pagination.
 await search.fill('not present');await page.getByText('No matching attachments.',{exact:true}).waitFor();
 await search.fill('Campaign/Autumn');await card('Autumn collection.png').waitFor();assert.equal(await page.locator('.aw-card').count(),1);
 await search.fill('');await page.locator('.aw-card').nth(99).waitFor();
 await page.getByRole('button',{name:'Next page',exact:true}).click();await page.waitForFunction(()=>document.querySelectorAll('.aw-card').length<100&&document.querySelectorAll('.aw-card').length>0);
 await page.getByRole('button',{name:'Previous page',exact:true}).click();await page.locator('.aw-card').nth(99).waitFor();
 await page.getByRole('checkbox',{name:'Select this page',exact:true}).check();assert.equal(await page.locator('.aw-card.checked').count(),100);
 await page.getByRole('button',{name:'Next page',exact:true}).click();await page.waitForFunction(()=>!document.querySelectorAll('.aw-card.checked').length);
 await page.getByRole('button',{name:'Previous page',exact:true}).click();await page.locator('.aw-card').nth(99).waitFor();
 await page.getByRole('button',{name:'List view',exact:true}).click();assert.ok(await page.locator('.aw-items.list').count());
 await page.getByRole('button',{name:'Grid view',exact:true}).click();
 await page.getByRole('checkbox',{name:'Select this page',exact:true}).check();
 await page.locator('.aw-filters button').nth(1).click();await page.waitForFunction(()=>!document.querySelectorAll('.aw-card.checked').length);
 await search.fill('Campaign/');await page.locator('.aw-toolbar-right select').selectOption('name:asc');
 await page.waitForFunction(()=>{const names=[...document.querySelectorAll('.aw-file-copy>strong')].map(e=>e.textContent);return names.length===28&&names[0]==='Autumn collection.png';});
 await search.fill('');await page.locator('.aw-filters button').first().click();await page.locator('.aw-toolbar-right select').selectOption('modified:desc');await page.locator('.aw-card').nth(99).waitFor();
 // Broken image falls back without crashing; HTML never executes in a management iframe.
 await search.fill('Broken image');await card('Broken image.png').click();await page.getByText('This image cannot be previewed. Download the original to view it.',{exact:true}).waitFor();
 await search.fill('Site/index.html');await card('index.html').click();await page.getByText('Preview unavailable for this format',{exact:true}).waitFor();assert.equal(await page.locator('.aw-preview iframe').count(),0);
 await page.getByText('Project resource or shared dependency: kept in place',{exact:true}).waitFor();assert.ok(await page.locator('.aw-detail-actions').getByRole('button',{name:'Rename',exact:true}).isDisabled());
 // Reference-preserving rename and referenced-file recycling followed by restoration.
 await search.fill('Campaign/Autumn');await card('Autumn collection.png').click();
 await page.waitForFunction(()=>{const b=[...document.querySelectorAll('.aw-detail-actions button')].find(b=>b.textContent==='Rename');return b&&!b.disabled;});
 await page.locator('.aw-detail-actions').getByRole('button',{name:'Rename',exact:true}).click();
 await page.locator('.aw-operation input').fill('Autumn study.png');await page.getByRole('button',{name:'Check & prepare',exact:true}).click();
 await page.locator('.aw-job-state.ready').waitFor();await page.getByText('1 discovered referring notes',{exact:true}).waitFor();
 assert.equal(await page.locator('.aw-tasks input[type=checkbox]').count(),0);
 await page.getByRole('button',{name:'Apply this plan',exact:true}).click();await page.locator('.aw-confirmation').getByRole('button',{name:'Confirm & continue',exact:true}).click();
 await page.locator('.aw-job-state.completed').waitFor();assert.equal(executions,1);
 let note=await (await page.request.get('/api/file?path='+encodeURIComponent('Notes/Creative brief.md'))).json();assert.match(note.text,/Autumn study\.png/);
 await page.locator('.aw-tasks').getByRole('button',{name:'Close',exact:true}).click();
 await card('Autumn study.png').click();await page.waitForFunction(()=>{const b=[...document.querySelectorAll('.aw-detail-actions button')].find(b=>b.textContent==='Recycle');return b&&!b.disabled;});
 await page.locator('.aw-detail-actions').getByRole('button',{name:'Recycle',exact:true}).click();await page.getByRole('button',{name:'Check & prepare',exact:true}).click();
 await page.locator('.aw-job-state.ready').waitFor();await page.getByText('These note links may temporarily stop working. Recycling does not edit notes; restore attachments when needed.',{exact:true}).waitFor();
 await page.locator('.aw-job-actions').getByRole('button',{name:'Confirm recycle',exact:true}).click();await page.locator('.aw-confirmation').getByRole('button',{name:'Confirm recycle',exact:true}).click();
 await page.locator('.aw-job-state.completed').waitFor();
 const unchanged=await (await page.request.get('/api/file?path='+encodeURIComponent('Notes/Creative brief.md'))).json();assert.equal(unchanged.text,note.text);
 await page.getByRole('button',{name:'Restore / undo task',exact:true}).click();await page.locator('.aw-confirmation').getByRole('button',{name:'Confirm & continue',exact:true}).click();
 await page.locator('.aw-job-state.rolled_back').waitFor();await page.locator('.aw-tasks').getByRole('button',{name:'Close',exact:true}).click();
 await card('Autumn study.png').waitFor();
 // PDF, audio lifecycle, unique uploads and ZIP download.
 await search.fill('Field guide.pdf');await card('Field guide.pdf').click();await page.locator('.aw-preview .aw-pdf').waitFor();assert.match(await page.locator('.aw-pdf').getAttribute('src'),/root=/);
 await search.fill('Quiet signal');await card('Quiet signal.wav').click();const audio=await page.locator('audio').elementHandle();await audio.evaluate(element=>element.play());
 await search.fill('Autumn study');await card('Autumn study.png').click();assert.ok(await audio.evaluate(element=>element.paused));
 const payload={name:'Uploaded image.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==','base64')};
 await page.locator('input[type=file]').setInputFiles([payload,payload]);
 await page.waitForFunction(()=>document.querySelectorAll('.aw-upload-row>svg').length>=2);
 await page.locator('.aw-tasks').getByRole('button',{name:'Close',exact:true}).click();await search.fill('Uploaded image');await card('Uploaded image (2).png').waitFor();assert.equal(await page.locator('.aw-card').count(),2);
 await page.getByRole('checkbox',{name:'Select this page',exact:true}).check();await page.locator('.aw-batch-actions').getByRole('button',{name:'Download',exact:true}).click();await page.getByRole('link',{name:'Download ZIP',exact:true}).waitFor();
 const downloaded=page.waitForEvent('download');await page.getByRole('link',{name:'Download ZIP',exact:true}).click();assert.match((await downloaded).suggestedFilename(),/\.zip$/);
 await page.locator('.aw-tasks').getByRole('button',{name:'Close',exact:true}).click();
 // A playable video fixture produced in the browser; no external media is loaded.
 const video=await page.evaluate(async()=>{const canvas=document.createElement('canvas');canvas.width=160;canvas.height=100;const ctx=canvas.getContext('2d');ctx.fillStyle='#748d7e';ctx.fillRect(0,0,160,100);const stream=canvas.captureStream(5),recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'}),chunks=[];recorder.ondataavailable=event=>chunks.push(event.data);const done=new Promise(resolve=>recorder.onstop=resolve);recorder.start();await new Promise(resolve=>setTimeout(resolve,400));recorder.stop();await done;stream.getTracks().forEach(track=>track.stop());const bytes=new Uint8Array(await new Blob(chunks).arrayBuffer());return btoa(String.fromCharCode(...bytes));});
 await page.locator('input[type=file]').setInputFiles({name:'Motion sample.webm',mimeType:'video/webm',buffer:Buffer.from(video,'base64')});
 await page.waitForFunction(()=>[...document.querySelectorAll('.aw-upload-row')].some(row=>row.textContent.includes('Motion sample.webm')&&row.querySelector('svg')));
 await page.locator('.aw-tasks').getByRole('button',{name:'Close',exact:true}).click();await search.fill('Motion sample');await card('Motion sample.webm').click();const movie=await page.locator('.aw-preview video').elementHandle();await movie.evaluate(element=>element.play());
 await search.fill('Autumn study');await card('Autumn study.png').click();assert.ok(await movie.evaluate(element=>element.paused));
 // Desktop and narrow visual acceptance in Chinese, with an additional Japanese check.
 await page.request.put('/api/preferences',{headers,data:{locale:'zh-CN'}});await page.reload();await page.getByRole('searchbox').waitFor();
 await page.getByRole('searchbox').fill('Autumn study');await card('Autumn study.png').click();await page.locator('.aw-preview img').evaluate(image=>image.decode());
 await page.getByRole('searchbox').fill('');await page.locator('.aw-card').nth(99).waitFor();await card('Autumn study.png').click();await page.screenshot({path:path.join(output,'workspace-zh-desktop.png'),fullPage:true});
 await page.getByRole('button',{name:'放大预览',exact:true}).click();await page.locator('.aw-expanded .aw-image-stage img').waitFor();await page.screenshot({path:path.join(output,'preview-zh-expanded.png'),fullPage:true});await page.locator('.aw-expanded').getByRole('button',{name:'关闭',exact:true}).click();
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,'workspace-zh-mobile-preview.png'),fullPage:true});
 assert.ok(await page.locator('.aw-preview').isVisible());await page.getByRole('button',{name:'返回附件列表',exact:true}).click();await page.screenshot({path:path.join(output,'workspace-zh-mobile-files.png'),fullPage:true});
 assert.ok(await page.locator('.aw-browser').isVisible());assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.setViewportSize({width:1440,height:960});await page.request.put('/api/preferences',{headers,data:{locale:'ja'}});await page.reload();await page.locator('.aw-card').first().waitFor();await page.screenshot({path:path.join(output,'workspace-ja-desktop.png'),fullPage:true});
 // Root changes discard pending searches, selection and preview requests.
 const oldRoot=fixture.root;
 await page.getByRole('searchbox').fill('Autumn study');await card('Autumn study.png').click();
 await page.locator('.aw-preview img').waitFor();
 await page.request.post('/api/config',{headers,data:{root:fixture.other_root}});
 await page.waitForFunction(()=>!document.querySelector('.attachment-workspace'));
 await page.locator('.sidebar-shortcuts').getByRole('button',{name:'添付ファイル',exact:true}).click();
 await page.locator('.aw-onboarding').waitFor();assert.equal(await page.locator('.aw-card,.aw-preview img').count(),0);
 assert.equal((await page.request.get('/api/media?'+new URLSearchParams({root:oldRoot,path:'Campaign/Autumn study.png'}))).status(),409);
 assert.deepEqual(errors,[]);console.log('Attachment workspace passed: one-click setup, unknown progress, pagination, previews, protected resources, rename/link repair, referenced recycle/restore, unique upload, ZIP, media cleanup, and desktop/mobile visuals.');
})().catch(async error=>{if(browser){const page=browser.contexts()[0]?.pages()[0];await page?.screenshot({path:path.join(output,'failure.png'),fullPage:true}).catch(()=>{});}console.error(error);console.error(logs.slice(-1800));process.exitCode=1;}).finally(async()=>{await browser?.close();server?.kill('SIGINT');});
