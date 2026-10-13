// Run against tests/settings_ui_server.py and a production frontend build.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('fs'),path=require('path');
const base=process.env.SETTINGS_TEST_URL;
assert.ok(base&&/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(base)&&!base.endsWith(':18080'),'Use an isolated local server');
const out=process.env.SETTINGS_TEST_ARTIFACTS||path.resolve('.cache/graph-ui-artifacts');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch(process.env.GRAPH_TEST_METAL?{args:['--use-angle=metal','--enable-gpu']}:{}),page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));
 const shot=async name=>{await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));await page.screenshot({path:path.join(out,'graph-'+name+'.png')});};
 const ready=()=>page.locator('.graph:visible[aria-busy=false]').waitFor();
 const cy=fn=>page.locator('.graph:visible').evaluate((element,source)=>new Function('cy','return ('+source+')(cy)')(element._cyreg.cy),String(fn));
 const find=async name=>{await page.getByLabel('搜索图谱笔记').fill(name);await page.keyboard.press('Enter');await page.getByRole('complementary',{name:'笔记关联详情'}).waitFor();await ready();};
 try{
  await page.goto(base);const root=await page.evaluate(async()=>(await(await fetch('/api/session')).json()).config.root);assert.ok(root.includes('vault-settings-ui-'));
  await page.locator('.sidebar-tools button').click();assert.equal(await page.locator('.settings-nav nav button').count(),7);assert.equal(await page.locator('.settings-nav nav button').filter({hasText:'关系图'}).count(),0);await page.getByLabel('关闭设置').last().click();
  await page.getByRole('button',{name:'关系图谱',exact:true}).click();await ready();assert.match(page.url(),/view=graph/);assert.equal(await page.locator('dialog[open]').count(),0);checks.push('standalone sidebar route; settings category removed');
  const initial=await cy(c=>({count:c.nodes().length,box:c.nodes().renderedBoundingBox()}));assert.ok(initial.count>2);assert.ok(initial.box.w>150);await shot('fixture-overview');
  await find('项目规划');assert.equal(await page.locator('.graph-inspector h2').innerText(),'项目规划');assert.match(page.url(),/view=graph/);assert.ok(await cy(c=>c.nodes('.spotlight').length));checks.push('search selects/highlights without opening document');
  await page.getByRole('button',{name:'探索连接',exact:true}).click();await ready();await page.getByLabel('连接层级').selectOption('2');await ready();assert.ok(await page.locator('.graph-focus-bar').isVisible());checks.push('local graph and two-level exploration');
  await page.getByRole('button',{name:'打开笔记',exact:true}).click();await page.locator('.document:visible .markdown h1').waitFor();await page.getByRole('button',{name:'返回关系图谱'}).click();await ready();assert.equal(await page.locator('.graph-inspector h2').innerText(),'项目规划');checks.push('open note and return preserves selection/scope');
  await page.getByRole('button',{name:'返回全图'}).click();await ready();await page.getByLabel('关闭笔记详情').count().then(async n=>{if(n)await page.getByLabel('关闭笔记详情').click()});
  await page.getByRole('button',{name:'显示与筛选'}).click();const count=await cy(c=>c.nodes().length);await page.getByLabel('显示独立笔记').check();await ready();assert.ok(await cy(c=>c.nodes().length)>count);
  await page.getByLabel('筛选图谱目录').selectOption('Notes');await ready();assert.ok((await cy(c=>c.nodes().map(n=>n.id()))).every(id=>id.startsWith('Notes/')));
  await page.getByLabel('全部名称',{exact:true}).check();await page.getByLabel('连接方向',{exact:true}).check();await page.waitForFunction(()=>document.querySelector('.graph')?._cyreg?.cy.edges()[0]?.style('target-arrow-shape')==='triangle');assert.equal(await cy(c=>c.edges()[0].style('target-arrow-shape')),'triangle');checks.push('folder/orphan/label/direction filters');
  await page.getByLabel('适应画布',{exact:true}).click();const z=await cy(c=>c.zoom());await page.getByLabel('放大图谱',{exact:true}).click();assert.ok(await cy(c=>c.zoom())>z);await page.locator('.graph:visible').focus();await page.keyboard.press('-');await page.keyboard.press('ArrowRight');await page.keyboard.press('0');
  const before=await cy(c=>c.nodes()[0].position());const pos=await cy(c=>c.nodes()[0].renderedPosition()),rect=await page.locator('.graph:visible').boundingBox();await page.mouse.move(rect.x+pos.x,rect.y+pos.y);await page.mouse.down();await page.mouse.move(rect.x+pos.x+40,rect.y+pos.y+25,{steps:8});await page.mouse.up();assert.notDeepEqual(await cy(c=>c.nodes()[0].position()),before);checks.push('zoom, fit, keyboard pan, node drag');
  await page.locator('.sidebar-tools button').click();await page.getByLabel('关闭设置').last().click();assert.equal(await page.getByLabel('筛选图谱目录').inputValue(),'Notes');checks.push('settings overlay retains graph state');
  await page.getByLabel('筛选图谱目录').selectOption('');await ready();await page.getByRole('button',{name:'显示与筛选'}).click();await find('Markdown 示例');await page.waitForTimeout(300);await shot('fixture-selected');
  await page.setViewportSize({width:390,height:844});await page.getByLabel('关闭笔记详情').click();await page.getByLabel('适应画布',{exact:true}).click();await shot('mobile');assert.ok(await page.locator('.graph-page').evaluate(e=>e.scrollWidth<=e.clientWidth));await find('项目规划');await page.locator('.graph-inspector').scrollIntoViewIfNeeded();await shot('mobile-selected');assert.ok(await page.getByRole('button',{name:'打开笔记',exact:true}).isVisible());checks.push('390px layout and reachable note actions');
  // Use a second page so each response and worker lifecycle starts independently.
  const states=await browser.newPage({viewport:{width:1440,height:1000}});states.on('pageerror',e=>errors.push(e.message));
  let fail=true;await states.route('**/api/graph',route=>route.fulfill(fail?{status:500,json:{error:'模拟：图谱暂不可用'}}:{json:{nodes:[],links:[]}}));await states.goto(base+'/?view=graph');await states.getByRole('alert').waitFor();await states.screenshot({path:path.join(out,'graph-error.png')});fail=false;await states.getByRole('button',{name:'重试',exact:true}).click();await states.getByText('从第一篇笔记开始').waitFor();await states.screenshot({path:path.join(out,'graph-empty.png')});checks.push('request failure retry and empty graph');
  await states.close();
  // Deterministic dense fixture; no user knowledge paths required to reproduce.
  const dense={nodes:[],links:[]};for(let i=0;i<1280;i++){const group=['设计','工程','阅读','研究','工作','随记'][i%6];dense.nodes.push({id:group+'/笔记-'+i+'.md',label:group+'笔记 '+i});if(i>=6&&i<1100)dense.links.push({source:dense.nodes[i].id,target:dense.nodes[i%6].id},{source:dense.nodes[i].id,target:dense.nodes[Math.max(i-6,0)].id});}
  const big=await browser.newPage({viewport:{width:1440,height:1000}});big.on('pageerror',e=>errors.push(e.message));await big.route('**/api/graph',r=>r.fulfill({json:dense}));const started=Date.now();await big.goto(base+'/?view=graph');await big.locator('.graph[aria-busy=false]').waitFor({timeout:30000});const elapsed=Date.now()-started;await big.screenshot({path:path.join(out,'graph-dense.png')});assert.ok(await big.locator('.graph-summary').innerText().then(s=>s.includes('1,100')));checks.push('1,280-node fixture layout completes in '+elapsed+' ms');
  // Validate the gesture contract, not a machine-dependent frame-rate threshold.
  const work=await big.locator('.graph').evaluate(async element=>{
   const c=element._cyreg.cy;await new Promise(r=>setTimeout(r,200));
   let updates=0;const tracked=c.nodes()[0],original=tracked.style;tracked.style=function(value,...rest){if(value&&typeof value==='object'&&'width' in value)updates++;return original.call(this,value,...rest);};
   const z=c.zoom();for(let i=0;i<16;i++){c.zoom(z*(1+i/80));c.panBy({x:2,y:1});await new Promise(requestAnimationFrame);}
   const during=updates;await new Promise(r=>setTimeout(r,220));const settled=updates;
   tracked.style=original;return {during,settled,texture:c.json().textureOnViewport,webgl:!!c.renderer().webgl,visibleLabels:c.nodes('.label-visible').length};
  });assert.equal(work.during,0);assert.ok(work.settled>0);assert.equal(work.texture,!work.webgl);assert.ok(work.visibleLabels<=120);
  checks.push('gesture performs no full-graph geometry updates; settles afterward; GPU or compatible rendering and label limits active');
  await big.getByLabel('搜索图谱笔记').fill('设计笔记 0');await big.keyboard.press('Enter');await big.waitForTimeout(400);
  const highlighted=await big.locator('.graph').evaluate(element=>{const c=element._cyreg.cy,n=c.nodes('.spotlight');return n.length===1&&n.closedNeighborhood().every(e=>!e.hasClass('faded'));});assert.equal(highlighted,true);
  checks.push('selection keeps the complete neighborhood highlighted after deferred display');await big.close();
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'graph-validation.json'),JSON.stringify({checks,errors},null,2));console.log(JSON.stringify({checks,errors},null,2));
 }catch(e){await shot('failure');console.error(e);console.log({checks,errors});process.exitCode=1;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
