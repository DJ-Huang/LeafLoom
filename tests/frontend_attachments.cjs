// Isolated attachment UI contract test; no user's vault or running service is used.
// PLAYWRIGHT_MODULE may point to a shared playwright-core installation.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const root=path.resolve(__dirname,'..'),out=path.join(root,'.cache/attachment-ui');fs.mkdirSync(out,{recursive:true});
require(path.join(root,'web/node_modules/esbuild')).buildSync({stdin:{contents:"import React from 'react';import {createRoot} from 'react-dom/client';import {Attachments} from './src/attachments';import {setLocale} from './src/i18n';setLocale('en');const root=createRoot(document.getElementById('app'));let key=0;window.mount=()=>root.render(<Attachments root={'fixture-'+key} key={++key} onClose={()=>root.render(null)}/>);window.mount();",resolveDir:path.join(root,'web'),loader:'tsx'},outfile:path.join(out,'test.js'),bundle:true,format:'iife',jsx:'automatic'});
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(root,'desktop/node_modules/playwright-core'));
const server=http.createServer((req,res)=>{if(req.url==='/test.js'){res.setHeader('Content-Type','text/javascript');res.end(fs.readFileSync(path.join(out,'test.js')));}else if(req.url==='/test.css'){res.setHeader('Content-Type','text/css');res.end(fs.readFileSync(path.join(out,'test.css')));}else{res.setHeader('Content-Type','text/html');res.end('<link rel="stylesheet" href="/test.css"><div id="app"></div><script src="/test.js"></script>');}});
let browser;
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 const page=await browser.newPage(),errors=[],calls=[];page.on('pageerror',error=>errors.push(error.message));
 let migration,plans=0,executions=0;
 let delayed=[],fail=false,refreshes=0,initializations=0,statusChecks=0,indexState='uninitialized',buildChecks=0;
 const item=path=>({path,name:path.split('/').pop(),size:123,mtime:1700000000,mime:'text/html'});
 await page.route('**/api/attachments**',async route=>{
  const request=route.request(),url=new URL(request.url());calls.push(url.search);
  if(url.pathname.endsWith('/migrations')){if(request.method()==='POST'){plans++;indexState='ready';migration={id:'fixture-job',root:request.postDataJSON().root,destination:'_attachments',state:'ready',summary:{files:1,bytes:123,notes:1},moves:[{source:'old.png',destination:'_attachments/old.png',size:123}],blockers:[]};await route.fulfill({json:migration});}else await route.fulfill({json:{jobs:[]}});return;}
  if(url.pathname.endsWith('/fixture-job/execute')){assert.equal(request.postDataJSON().confirm,true);executions++;migration={...migration,state:'completed'};await route.fulfill({json:migration});return;}
  if(url.pathname.endsWith('/fixture-job')){await route.fulfill({json:migration});return;}
  if(url.pathname.endsWith('/status')){statusChecks++;if(indexState==='building'&&++buildChecks>1)indexState='ready';await route.fulfill({json:{state:indexState,schema_version:indexState==='uninitialized'?null:indexState==='needs_upgrade'?0:1,current_version:1,usable:indexState==='ready',progress:{done:3},last_scanned_at:refreshes}});return;}
  if(url.pathname.endsWith('/initialize')){initializations++;indexState='building';buildChecks=0;await route.fulfill({json:{state:'building'}});return;}
  if(url.pathname.endsWith('/rebuild')){refreshes++;indexState='building';buildChecks=0;await route.fulfill({json:{state:'building'}});return;}
  if(url.pathname.endsWith('/index-cancel')){indexState='cancelled';await route.fulfill({json:{state:'cancelled'}});return;}
  const query=url.searchParams.get('query'),after=url.searchParams.get('after');
  if(query==='slow'){delayed.push(route);return;}
  if(fail){fail=false;await route.fulfill({status:500,json:{error:'fixture failed'}});return;}
  const items=query?[item(query+'.html')]:after?[item('last.html')]:Array.from({length:100},(_,i)=>item('assets/'+String(i).padStart(3,'0')+'.html'));
  await route.fulfill({json:{items,total:query?1:101,next_cursor:!query&&!after?'assets/099.html':null}});
 });
 await page.goto('http://127.0.0.1:'+server.address().port);
 const rows=page.locator('.attachments-list li'),search=page.getByRole('searchbox');
 await page.getByText('Advanced: index-only maintenance',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Initialize / upgrade and organize attachments',exact:true}).waitFor();
 assert.equal(await page.getByRole('button',{name:'Initialize attachment database',exact:true}).isVisible(),false);
 assert.ok(statusChecks>0);assert.equal(await rows.count(),0);assert.equal(calls.filter(value=>value.includes('limit=')).length,0);
 await page.getByRole('button',{name:'Initialize / upgrade and organize attachments',exact:true}).click();
 await rows.first().waitFor();assert.equal(initializations,0);assert.equal(plans,1);assert.equal(await rows.count(),100);
 const execute=page.getByRole('button',{name:'Confirm and execute migration',exact:true});assert.ok(await execute.isDisabled());
 await page.getByRole('checkbox').check();await execute.click();await page.getByText('Migration completed',{exact:true}).waitFor();assert.equal(executions,1);
 assert.match(await rows.first().locator('a').getAttribute('href'),/download=true/);assert.equal(await page.locator('iframe').count(),0);
 await page.getByRole('button',{name:'Next page',exact:true}).click();await page.getByText('last.html',{exact:true}).first().waitFor();assert.equal(await rows.count(),1);assert.ok(await page.getByRole('button',{name:'Next page',exact:true}).isDisabled());
 await page.getByRole('button',{name:'First page',exact:true}).click();await page.getByText('000.html',{exact:true}).waitFor();assert.equal(await rows.count(),100);
 await search.fill('slow');await page.getByRole('button',{name:'Search',exact:true}).click();await page.getByText(/Reading attachment metadata/).waitFor();
 const count=calls.length;await page.getByRole('button',{name:'Search',exact:true}).click();assert.equal(calls.length,count);
 await search.fill('new');await page.getByRole('button',{name:'Search',exact:true}).click();await page.getByText('new.html',{exact:true}).first().waitFor();
 for(const route of delayed.splice(0))await route.fulfill({json:{items:[item('stale.html')],total:1,next_cursor:null}}).catch(()=>{});
 assert.equal(await page.getByText('stale.html',{exact:true}).count(),0);
 await search.fill('slow');await page.getByRole('button',{name:'Search',exact:true}).click();await page.getByRole('button',{name:'Cancel',exact:true}).click();await page.getByText(/Stopped waiting/).waitFor();assert.equal(await rows.count(),0);
 // A new keyed root must not show results from the cancelled old root.
 await page.evaluate(()=>window.mount());await page.getByText('000.html',{exact:true}).waitFor();
 for(const route of delayed.splice(0))await route.fulfill({json:{items:[item('old-root.html')],total:1,next_cursor:null}}).catch(()=>{});
 assert.equal(await page.getByText('old-root.html',{exact:true}).count(),0);
 fail=true;await search.fill('retry');await page.getByRole('button',{name:'Search',exact:true}).click();await page.getByRole('alert').waitFor();await page.getByRole('button',{name:'Retry',exact:true}).click();await page.getByText('retry.html',{exact:true}).first().waitFor();
 await page.getByText('Advanced: index-only maintenance',{exact:true}).click();await page.getByRole('button',{name:'Refresh attachment index',exact:true}).click();await page.getByText('retry.html',{exact:true}).first().waitFor();assert.equal(refreshes,1);
 await page.getByRole('button',{name:'Close',exact:true}).click();assert.equal(await page.locator('dialog').count(),0);
 indexState='unsupported';await page.evaluate(()=>window.mount());await page.getByText(/This database version is unsupported/).waitFor();assert.equal(await rows.count(),0);assert.equal(await page.getByRole('button',{name:'Initialize attachment database',exact:true}).count(),0);
 indexState='needs_upgrade';await page.evaluate(()=>window.mount());await page.getByText('Advanced: index-only maintenance',{exact:true}).click();await page.getByRole('button',{name:'Upgrade attachment database',exact:true}).click();await rows.first().waitFor();assert.equal(initializations,1);
 assert.deepEqual(errors,[]);console.log('Attachment UI passed: bounded pages, download safety, search races, repeated clicks, cancellation, root remount, retry, refresh, close.');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{await browser?.close();server.close();});
