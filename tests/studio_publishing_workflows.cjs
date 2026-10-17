// Real UI publishing acceptance. Uses only the disposable harness vault.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const {performance}=require('node:perf_hooks');
module.exports=async function publishingWorkflows({page,request,info,checks}){
 const root=path.resolve(__dirname,'..'),python=process.env.LEAFLOOM_PYTHON||path.join(root,'.venv/bin/python'),directory='PublishingWorkflow',evidence=path.join(root,'.cache/studio-qa');
 fs.mkdirSync(evidence,{recursive:true});
 const fixture=JSON.parse(execFileSync(python,['-c',"import json,sys;sys.path.insert(0,'tests');from studio_publishing_fixture import fixture_document,ART_SVG;print(json.dumps({'document':fixture_document(),'art':ART_SVG}))"],{cwd:root,encoding:'utf8'}));
 await request('design/projects',{root:info.root,managed:true,directory,name:'Publishing Workflow',width:720,height:900});
 const read=()=>request('design/document?directory='+directory);
 let saved=await read();fixture.document.id=saved.document.id;fixture.document.name='Publishing Workflow';
 fs.mkdirSync(path.join(info.root,directory,'Design/Assets'),{recursive:true});fs.writeFileSync(path.join(info.root,directory,'Design/Assets/shared-art.svg'),fixture.art);
 await request('design/operations',{root:info.root,directory,expected_revision:saved.revision,operation_id:'publishing-fixture',label:'Synthetic publishing fixture',commands:[{type:'document.replace',document:fixture.document}]});
 await page.locator('.dw-toolbar').getByRole('button',{name:'返回项目',exact:true}).click();
 await page.reload();await page.locator('.sidebar').getByRole('button',{name:'设计工作台',exact:true}).click();await page.locator('.design-project-title').getByText('Publishing Workflow',{exact:true}).click();
 const inspector=()=>page.locator('.dw-inspector'),canvas=()=>page.frameLocator('.dw-runtime'),node=id=>canvas().locator('[data-studio-node="'+id+'"]').first();
 await node('title-1').waitFor();
 const mutate=async (action,endpoint='design/operations')=>{const result=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/'+endpoint&&response.request().method()==='POST');result.catch(()=>{});await action();const response=await result;assert.ok(response.ok(),await response.text());await page.locator('.dw-save-status').filter({hasText:'已保存'}).waitFor();};
 const field=async(label,value)=>{const input=inspector().getByLabel(label,{exact:true});if(await input.inputValue()===String(value))return;await mutate(async()=>{await input.fill(String(value));await input.blur();});};
 const dataTab=()=>inspector().getByRole('button',{name:'数据',exact:true}).click();
 const variant=async id=>{await inspector().getByTestId('studio-variant').selectOption(id);await page.waitForTimeout(100);};
 const select=async name=>{await page.locator('.dw-layer-select').filter({hasText:name}).first().click();await dataTab();};
 const openPublish=async()=>{await page.getByTestId('studio-batch-publish').click();await page.getByRole('dialog').getByText('批量发布',{exact:true}).waitFor();};
 const closePublish=()=>page.getByRole('dialog').getByRole('button',{name:'关闭',exact:true}).click();
 // Author an independent stable binding through the inspector, then a generic variant.
 await select('Independent editable caption');await inspector().getByTestId('studio-new-binding-key').fill('campaign.caption');
 await mutate(()=>inspector().getByTestId('studio-create-binding').click());saved=await read();assert.equal(saved.document.pages[0].nodes[2].props.bindingKey,'campaign.caption');
 await inspector().getByTestId('studio-new-variant-name').fill('Retail audience');await mutate(()=>inspector().getByTestId('studio-create-variant').click());
 saved=await read();const audience=Object.values(saved.document.variants).find(item=>item.name==='Retail audience');assert.ok(audience);
 await field('变体上下文 JSON',JSON.stringify({audience:'retail',channel:'poster'}));await field('campaign.caption · 变体值','Retail caption');
 saved=await read();assert.equal(saved.document.variants[audience.id].values['campaign.caption'].value,'Retail caption');assert.equal(saved.document.bindings['campaign.caption'].value,'Studio sample 1');
 checks.push('publishing-real-ui-stable-binding-and-generic-variant');
 // Source changes mark translations stale and review is an explicit undoable action.
 await variant('');await field('page.1.title · 源数据','New collection source');await variant('ja');
 await inspector().getByText('源数据已更新，请复核此变体',{exact:true}).waitFor();
 await mutate(()=>inspector().getByRole('button',{name:'确认已复核',exact:true}).click());saved=await read();assert.equal(saved.document.variants.ja.values['page.1.title'].sourceRevision,saved.document.bindings['page.1.title'].revision);
 checks.push('publishing-source-revision-stale-review');
 // The variant layout editor changes only the variant; toolbar history still works.
 await select('Editable collection title');const sourceStyle=JSON.stringify((await read()).document.pages[0].nodes[1].style);
 await field('宽度',550);saved=await read();assert.equal(saved.document.variants.ja.layout['title-1'].width,550);assert.equal(JSON.stringify(saved.document.pages[0].nodes[1].style),sourceStyle);
 await mutate(()=>page.locator('.dw-toolbar').getByRole('button',{name:/^撤销/}).click(),'design/history');assert.equal((await read()).document.variants.ja.layout['title-1'].width,undefined);
 await mutate(()=>page.locator('.dw-toolbar').getByRole('button',{name:/^重做/}).click(),'design/history');assert.equal((await read()).document.variants.ja.layout['title-1'].width,550);
 await node('title-1').filter({hasText:'クリエイティブ'}).waitFor();await page.getByTestId('studio-mode-preview').click();await page.waitForFunction(()=>document.querySelector('[data-testid="studio-mode-preview"]')?.getAttribute('aria-pressed')==='true');await node('title-1').filter({hasText:'クリエイティブ'}).waitFor();await page.getByTestId('studio-mode-edit').click();await page.waitForFunction(()=>document.querySelector('[data-testid="studio-mode-edit"]')?.getAttribute('aria-pressed')==='true');
 await variant('zh');await node('title-1').filter({hasText:'创意作品集'}).waitFor();
 checks.push('publishing-variant-layout-history-and-preview-projection');
 // An explicit fit request must respect both limits, or leave content unchanged.
 await field('page.1.title · 变体值','Long publishing title '.repeat(12));await field('高度',30);
 await openPublish();await page.getByRole('dialog').getByRole('button',{name:'检查当前画布',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'按边界适配文字',exact:true}).first().waitFor();
 const beforeFit=(await read()).document.variants.zh.layout['title-1'].fontSize;
 await page.evaluate(()=>{window.__publishingFitResult=null;const receive=event=>{const frame=document.querySelector('.dw-runtime');if(event.source===frame?.contentWindow&&event.data?.type==='studio-fit-text-result'){window.__publishingFitResult=event.data;window.removeEventListener('message',receive);}};window.addEventListener('message',receive);});
 await page.getByRole('dialog').getByRole('button',{name:'按边界适配文字',exact:true}).first().click();await page.waitForFunction(()=>window.__publishingFitResult!==null);
 const fitResult=await page.evaluate(()=>window.__publishingFitResult);assert.equal(fitResult.nodeId,'title-1');
 if(fitResult.patch){await page.locator('.dw-save-status').filter({hasText:'已保存'}).waitFor();assert.ok(fitResult.patch.style.fontSize>=12&&fitResult.patch.style.fontSize>=beforeFit*.8);}else assert.ok(fitResult.warnings?.length,'An unsuccessful fit must explain its readable limits');
 const afterFit=(await read()).document.variants.zh.layout['title-1'].fontSize;assert.ok(afterFit>=12&&afterFit>=beforeFit*.8);assert.equal(JSON.stringify((await read()).document.pages[0].nodes[1].style),sourceStyle);
 await page.screenshot({path:path.join(evidence,'publishing-preflight.png'),fullPage:true});await closePublish();
 await field('page.1.title · 变体值','创意作品集 1');await field('高度',190);
 checks.push('publishing-overflow-scan-and-explicit-bounded-fit');
 // A failed durable save prevents publication; retry uses normal workbench recovery.
 await variant('');await page.route('**/api/design/operations',route=>route.abort('failed'));
 const input=inspector().getByLabel('campaign.caption · 源数据',{exact:true});await input.fill('Queued source caption');await input.blur();await page.locator('.dw-conflict').waitFor();
 await openPublish();assert.equal(await page.getByTestId('publish-check').isDisabled(),true);assert.equal(await page.getByTestId('publish-start').isDisabled(),true);await closePublish();await page.unroute('**/api/design/operations');
 await page.locator('.dw-conflict').getByRole('button',{name:'重试原操作',exact:true}).click();await page.locator('.dw-save-status').filter({hasText:'已保存'}).waitFor();
 checks.push('publishing-failed-save-gate-and-recovery');
 // Exercise a transient server response at the client boundary. This does not claim
 // renderer failure coverage; the real renderer and files are checked below.
 await openPublish();const dialog=page.getByRole('dialog');await dialog.getByRole('button',{name:'全选',exact:true}).click();
 for(const id of ['en','ja','zh'])await dialog.getByTestId('publish-variant-'+id).check();await dialog.getByTestId('publish-variant-source').uncheck();
 await dialog.getByTestId('publish-check').click();await dialog.getByText('发布检查通过',{exact:true}).waitFor({timeout:30000});
 const fake={job_id:'test-transient-ui',status:'failed',format:'png',completed:0,total:1,items:[{id:'test-item',page_id:'page-1',variant_id:'en',status:'failed',error:'Synthetic transient renderer interruption'}]};
 await page.route('**/api/design/publish',route=>route.request().method()==='POST'?route.fulfill({json:fake}):route.continue());await dialog.getByTestId('publish-start').click();await dialog.getByText(fake.items[0].error,{exact:true}).waitFor();
 let retryBody;await page.route('**/api/design/publish/test-transient-ui/retry',route=>{retryBody=route.request().postDataJSON();return route.fulfill({json:{...fake,status:'completed',completed:1,items:[{...fake.items[0],status:'completed',error:undefined}]}});});
 await dialog.getByRole('button',{name:'重试失败项',exact:true}).click();await dialog.locator('progress').evaluate(el=>new Promise(resolve=>{const tick=()=>el.value===1?resolve():requestAnimationFrame(tick);tick();}));assert.equal(retryBody.root,info.root);assert.equal(retryBody.expected_revision,undefined);
 await page.unroute('**/api/design/publish');await page.unroute('**/api/design/publish/test-transient-ui/retry');checks.push('publishing-simulated-transient-status-and-frozen-retry-ui');
 // Real 5-page x 3-locale PNG batch, with every PNG header inspected.
 const timings={},started={};
 const download=async(filename,format)=>{
  await dialog.getByRole('link',{name:'下载发布文件',exact:true}).waitFor({timeout:180000});
  const ready=performance.now(),event=page.waitForEvent('download');await dialog.getByRole('link',{name:'下载发布文件',exact:true}).click();
  const file=await event;assert.equal(await file.failure(),null);const destination=path.join(evidence,filename);await file.saveAs(destination);
  const finished=performance.now();timings[format]={...timings[format],publishElapsedMs:Math.round(ready-started[format]),downloadElapsedMs:Math.round(finished-ready),totalElapsedMs:Math.round(finished-started[format])};
  return destination;
 };
 const startReal=async format=>{
  const previous=await dialog.locator('.dw-publish-job a').count()?await dialog.locator('.dw-publish-job a').getAttribute('href'):null;
  const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/design/publish'&&r.request().method()==='POST');
  started[format]=performance.now();const startedAt=new Date().toISOString();await dialog.getByTestId('publish-start').click();
  const accepted=await response;assert.ok(accepted.ok(),await accepted.text());const job=await accepted.json();
  timings[format]={startedAt,jobId:job.job_id,outputs:job.total,renderer:'headless',scope:'Submit click to artifact visible; includes polling latency. Download measured separately.'};
  await page.waitForFunction(old=>{const link=document.querySelector('.dw-publish-job a');return !link||link.getAttribute('href')!==old;},previous);
 };
 await startReal('png');const zip=await download('publishing-5x3.zip','png');
 const pngResult=JSON.parse(execFileSync(python,['-c',"import sys,json,zipfile,struct;z=zipfile.ZipFile(sys.argv[1]);names=[n for n in z.namelist() if n.endswith('.png')];print(json.dumps([{'name':n,'size':struct.unpack('>II',z.read(n)[16:24])} for n in names]))",zip],{encoding:'utf8'}));assert.equal(pngResult.length,15);assert.ok(pngResult.every(item=>item.size[0]===720&&item.size[1]===900));
 await page.screenshot({path:path.join(evidence,'publishing-5x3-completed.png'),fullPage:true});await closePublish();await openPublish();assert.equal(await page.getByRole('dialog').getByRole('link',{name:'下载发布文件',exact:true}).count(),1);
 checks.push('publishing-real-15-png-dimensions-and-modal-reopen');
 fs.writeFileSync(path.join(evidence,'publishing-report.json'),JSON.stringify({png:pngResult,timings,fit:{beforeFit,afterFit},checks:checks.filter(item=>item.startsWith('publishing-'))},null,2));
 // One real multipage PDF in variant/page selection order.
 await dialog.getByLabel('输出格式',{exact:true}).selectOption('pdf');await dialog.getByTestId('publish-check').click();await dialog.getByText('发布检查通过',{exact:true}).waitFor({timeout:30000});
 await startReal('pdf');const pdf=await download('publishing-5x3.pdf','pdf');
 const pdfResult=JSON.parse(execFileSync(python,['-c',"import sys,json;from pypdf import PdfReader;r=PdfReader(sys.argv[1]);print(json.dumps({'pages':len(r.pages),'sizes':[[float(p.mediabox.width),float(p.mediabox.height)] for p in r.pages]}))",pdf],{encoding:'utf8'}));assert.equal(pdfResult.pages,15);assert.ok(pdfResult.sizes.every(([w,h])=>Math.abs(w-540)<1&&Math.abs(h-675)<1));
 checks.push('publishing-real-multipage-pdf-count-and-dimensions');
 fs.writeFileSync(path.join(evidence,'publishing-report.json'),JSON.stringify({png:pngResult,pdf:pdfResult,timings,fit:{beforeFit,afterFit},checks:checks.filter(item=>item.startsWith('publishing-'))},null,2));
 await closePublish();
};
