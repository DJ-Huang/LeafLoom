// Focused, disposable image-copy acceptance. Native clipboard IPC is intercepted;
// a separate case exercises the real browser clipboard and Markdown paste flow.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),net=require('node:net'),{spawn}=require('node:child_process');
const {chromium}=require('../desktop/node_modules/playwright-core');
const root=path.resolve(__dirname,'..'),out=path.join(root,'.cache/design-image-copy');fs.mkdirSync(out,{recursive:true});
const executable=process.env.CHROMIUM_PATH||['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'].find(p=>fs.existsSync(p));
let server,browser,logs='';const checks=[],modifier=process.platform==='darwin'?'Meta':'Control';
(async()=>{
 const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const port=s.address().port;s.close(()=>resolve(port));});});
 server=spawn(process.env.LEAFLOOM_TEST_PYTHON||path.join(root,'.cache/desktop-dev/.venv/bin/python'),['-u','tests/attachment_workspace_server.py','vault_rag/static'],{cwd:root,env:{...process.env,LEAFLOOM_ATTACHMENT_TEST_PORT:String(port)},stdio:['ignore','pipe','pipe']});
 server.stdout.on('data',chunk=>logs+=chunk);server.stderr.on('data',chunk=>logs+=chunk);
 let info;for(let i=0;i<200;i++){const line=logs.split('\n').find(line=>line.startsWith('{"fixture": true'));if(line){info=JSON.parse(line);try{await fetch(info.ui);break;}catch{}}if(server.exitCode!==null)throw Error(logs);await new Promise(resolve=>setTimeout(resolve,100));}assert.ok(info,logs);
 browser=await chromium.launch({executablePath:executable,headless:true,args:['--no-proxy-server']});
 const context=await browser.newContext({viewport:{width:1480,height:1000}}),page=await context.newPage(),errors=[];page.setDefaultTimeout(15000);page.on('pageerror',error=>errors.push(error.message));
 await page.route('https://fixture.invalid/**',route=>route.abort());
 await page.goto(info.ui+'/?view=design');
 const session=await(await page.request.get(info.ui+'/api/session')).json(),headers={'X-Vault-CSRF':session.csrf};
 const request=async(endpoint,body)=>{const response=await page.request[body===undefined?'get':'post'](info.ui+'/api/'+endpoint,{headers,...(body===undefined?{}:{data:body})});assert.ok(response.ok(),await response.text());return response.json();};
 await page.request.put(info.ui+'/api/preferences',{headers,data:{locale:'zh-CN'}});
 const directory='Projects/ImageCopy';await request('design/projects',{root:session.config.root,directory,managed:true,name:'Source image fixture',width:800,height:600});
 const read=()=>request('design/document?directory='+encodeURIComponent(directory));let saved=await read();const pageId=saved.document.pages[0].id;
 const png=Buffer.from(await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=128;canvas.height=96;const ctx=canvas.getContext('2d');ctx.fillStyle='#ff0000';ctx.fillRect(0,0,64,48);return canvas.toDataURL().split(',')[1];}),'base64');
 async function upload(name,bytes,mime){const response=await page.request.post(info.ui+'/api/design/assets?'+new URLSearchParams({root:session.config.root,directory,name,expected_revision:saved.revision,operation_id:'fixture-'+name}),{headers:{...headers,'Content-Type':mime},data:bytes});assert.ok(response.ok(),await response.text());saved=await response.json();return Object.values(saved.document.assets).find(asset=>asset.name===name).id;}
 const first=await upload('transparent-source.png',png,'image/png');
 const second=await upload('variant-source.svg',Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="3"><rect width="2" height="2" fill="blue"/></svg>'),'image/svg+xml');
 const gif=await upload('animated-source.gif',Buffer.from('R0lGODlhAwACAIEAAP8AAAAAAAAAAAAAACH/C05FVFNDQVBFMi4wAwEAAAAh+QQACgAAACwAAAAAAwACAAAIBgABCBwYEAAh+QQBCgABACwAAAAAAwACAIEAAP8AAAAAAAAAAAAIBgABCBwYEAA7','base64'),'image/gif');
 const image=(id,name,props,extra={})=>{const index=['photo','locked','bound','animated','external'].indexOf(id);return {id,name,type:'image',style:{x:32+(index%3)*250,y:40+Math.floor(index/3)*260,width:200,height:150,rotate:12,borderRadius:24},props,...extra};};
 const commands=[
  {type:'node.create',page_id:pageId,node:image('photo','Source photo',{assetId:first,fit:'cover'})},
  {type:'node.create',page_id:pageId,node:image('locked','Locked photo',{assetId:first},{locked:true})},
  {type:'node.create',page_id:pageId,node:image('bound','Bound photo',{assetId:first,bindingKey:'photo'})},
  {type:'node.create',page_id:pageId,node:image('animated','Animated photo',{assetId:gif})},
  {type:'node.create',page_id:pageId,node:image('external','External photo',{src:'https://fixture.invalid/source.png'})},
  {type:'node.create',page_id:pageId,node:{id:'text',name:'Text layer',type:'text',style:{x:300,y:300,width:200,height:40},props:{text:'Fixture text'}}},
  {type:'binding.set',key:'photo',kind:'image',value:first},
  {type:'variant.set',variant:{id:'alternate',name:'Alternate',values:{photo:{value:second,sourceRevision:1}}}}
 ];
 saved=await request('design/operations',{root:session.config.root,directory,expected_revision:saved.revision,operation_id:'fixture-nodes',commands});const revision=saved.revision;
 await page.reload();await page.locator('.design-project-title').getByText('Source image fixture',{exact:true}).click();await page.frameLocator('.dw-runtime').locator('.studio-stage').waitFor();
 await page.evaluate(()=>{window.fixtureCopies=[];window.fixtureTextCopies=[];window.leafloomDesktop={writeClipboardImage:async bytes=>{if(window.fixtureImageFailure)throw Error('Clipboard failed');window.fixtureCopies.push(Array.from(bytes));},writeClipboardText:async text=>window.fixtureTextCopies.push(text)};});
 const layer=async name=>{await page.locator('.dw-layer-select').filter({hasText:name}).click();await page.locator('.dw-inspector>.dw-tabs').getByRole('button',{name:'设计',exact:true}).click();};
 const button=()=>page.getByTestId('studio-copy-source-image');
 const count=()=>page.evaluate(()=>window.fixtureCopies.length);
 const copy=async()=>{const before=await count();await button().click();await page.waitForFunction(n=>window.fixtureCopies.length===n+1,before);};
 const pixels=()=>page.evaluate(async()=>{const bitmap=await createImageBitmap(new Blob([new Uint8Array(window.fixtureCopies.at(-1))],{type:'image/png'})),canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;const ctx=canvas.getContext('2d');ctx.drawImage(bitmap,0,0);return {width:bitmap.width,height:bitmap.height,first:Array.from(ctx.getImageData(0,0,1,1).data),last:Array.from(ctx.getImageData(bitmap.width-1,bitmap.height-1,1,1).data)};});
 await layer('Source photo');await copy();assert.deepEqual(await pixels(),{width:128,height:96,first:[255,0,0,255],last:[0,0,0,0]});checks.push('source-size-alpha-no-canvas-styling');
 const before=await count();await page.locator('.dw-layer-select').filter({hasText:'Source photo'}).focus();await page.keyboard.press(modifier+'+c');await page.waitForFunction(n=>window.fixtureCopies.length===n+1,before);checks.push('layer-copy-shortcut');
 await page.frameLocator('.dw-runtime').locator('[data-studio-select-id="photo"]').click();const canvasBefore=await count();await page.keyboard.press(modifier+'+c');await page.waitForFunction(n=>window.fixtureCopies.length===n+1,canvasBefore);checks.push('canvas-copy-shortcut');
 await layer('Source photo');await page.getByTestId('studio-image-source').screenshot({path:path.join(out,'image-source-card.png')});
 const input=page.locator('.dw-inspector').getByLabel('名称',{exact:true});await input.focus();await page.keyboard.press(modifier+'+a');const textBefore=await count();await page.keyboard.press(modifier+'+c');assert.equal(await count(),textBefore);checks.push('inspector-text-copy-is-not-image-copy');
 await layer('Locked photo');assert.equal(await button().isEnabled(),true);await copy();checks.push('locked-image-copies');
 await layer('Bound photo');await page.locator('.dw-inspector>.dw-tabs').getByRole('button',{name:'数据',exact:true}).click();await page.getByTestId('studio-variant').selectOption('alternate');await page.locator('.dw-inspector>.dw-tabs').getByRole('button',{name:'设计',exact:true}).click();assert.match(await page.getByTestId('studio-image-source').innerText(),/variant-source.svg/);assert.equal(await button().isEnabled(),true);await copy();assert.deepEqual(await pixels(),{width:4,height:3,first:[0,0,255,255],last:[0,0,0,0]});checks.push('readonly-variant-resolves-and-rasterizes-svg');
 await page.locator('.dw-inspector>.dw-tabs').getByRole('button',{name:'数据',exact:true}).click();await page.getByTestId('studio-variant').selectOption('');await layer('Animated photo');await copy();assert.equal((await pixels()).width,3);assert.deepEqual((await pixels()).first,[255,0,0,255]);checks.push('animated-source-first-frame');
 await layer('External photo');assert.match(await page.getByTestId('studio-image-source').innerText(),/导入/);assert.equal(await button().count(),0);checks.push('external-source-actionable-error');
 await layer('Source photo');const sourcePath=directory+'/'+saved.document.assets[first].path;
 await page.route('**/api/media?**',route=>new URL(route.request().url()).searchParams.get('path')===sourcePath?route.fulfill({status:404,body:'missing'}):route.continue());
 const missingBefore=await count();await button().click();await page.getByTestId('studio-image-source').getByRole('status').filter({hasText:'找不到源图片'}).waitFor();assert.equal(await count(),missingBefore);await page.unroute('**/api/media?**');await copy();checks.push('missing-original-fails-and-retry-recovers');
 await page.evaluate(()=>window.fixtureImageFailure=true);const failureBefore=await count();await button().click();await page.getByTestId('studio-image-source').getByRole('status').filter({hasText:'图片复制失败'}).waitFor();assert.equal(await count(),failureBefore);await page.evaluate(()=>window.fixtureImageFailure=false);await copy();checks.push('native-copy-failure-and-retry');
 await layer('Text layer');const textCopies=await page.evaluate(()=>window.fixtureTextCopies.length);await page.getByRole('button',{name:'复制控件定位信息',exact:true}).click();assert.equal(await page.evaluate(()=>window.fixtureTextCopies.length),textCopies+1);checks.push('element-location-copy-retained');
 assert.equal((await read()).revision,revision);checks.push('copy-does-not-save-or-change-history');
 // The browser branch uses a PNG ClipboardItem, not the desktop test interceptor.
 await layer('Source photo');await page.evaluate(()=>delete window.leafloomDesktop);await context.grantPermissions(['clipboard-read','clipboard-write'],{origin:info.ui});await button().click();await page.getByTestId('studio-image-source').getByRole('status').filter({hasText:'图片已复制'}).waitFor();
 assert.equal(await page.evaluate(async()=>{const items=await navigator.clipboard.read();return items.some(item=>item.types.includes('image/png'));}),true);checks.push('browser-image-clipboard');
 await request('create',{path:'Campaign/Copied image.md',directory:false});await page.goto(info.ui+'/?note='+encodeURIComponent('Campaign/Copied image.md'));await page.locator('.rich-prose').waitFor();await page.locator('.rich-prose').click();await page.keyboard.press(modifier+'+v');
 await page.waitForFunction(async()=>{const response=await fetch('/api/file?path='+encodeURIComponent('Campaign/Copied image.md'));return /!\[.*\]\(/.test((await response.json()).text);});checks.push('browser-clipboard-pastes-as-note-attachment');
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'browser-report.json'),JSON.stringify({checks,errors},null,2));console.log(JSON.stringify({checks,errors}));
})().catch(error=>{console.error(error);fs.writeFileSync(path.join(out,'browser-report.json'),JSON.stringify({checks,error:String(error)},null,2));if(logs)fs.writeFileSync(path.join(out,'server.log'),logs);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)server.kill('SIGTERM');});
