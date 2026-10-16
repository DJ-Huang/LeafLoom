// Focused real-UI contract: component extraction and master duplication retain
// script-owned child references. Run after the production frontend build.
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net');
const {spawn}=require('node:child_process');
const {chromium}=require('../desktop/node_modules/playwright-core');
const root=path.resolve(__dirname,'..'),sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function freePort(){const server=net.createServer();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const port=server.address().port;await new Promise(resolve=>server.close(resolve));return port;}
async function main(){
 const temp=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'leafloom-component-scripts-'))),port=await freePort();
 const log=fs.openSync(path.join(temp,'server.log'),'a'),server=spawn(process.env.LEAFLOOM_PYTHON||path.join(root,'.venv/bin/python'),[path.join(__dirname,'html_projects_server.py'),'--directory',temp,'--port',String(port)],{cwd:root,stdio:['ignore',log,log]});fs.closeSync(log);
 let browser,page;
 try{
  let ready=false;for(let attempt=0;attempt<150;attempt++){try{if((await fetch('http://127.0.0.1:'+port+'/healthz')).ok){ready=true;break;}}catch{}await sleep(100);}assert.ok(ready);
  const info=JSON.parse(fs.readFileSync(path.join(temp,'info.json'))),token=fs.readFileSync(path.join(info.state,'auth-token'),'utf8').trim();
  const request=async(endpoint,body)=>{const response=await fetch(info.url+'/api/'+endpoint,{method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)}),value=await response.json();assert.ok(response.ok,JSON.stringify(value));return value;};
  await request('design/projects',{root:info.root,managed:true,directory:'ScriptComponents',name:'Script Components',width:800,height:600});
  let saved=await request('design/document?directory=ScriptComponents');
  const childSource="export function mount(ctx) { const untouched='target'; /* ctx.find('target') */ const target=ctx.find('target'); if(!target)throw new Error('Missing copied child'); target.dataset.childReference='resolved'; return()=>{delete target.dataset.childReference;}; }";
  await request('design/operations',{root:info.root,directory:'ScriptComponents',expected_revision:saved.revision,operation_id:'script-fixture',label:'Fixture',commands:[{type:'node.create',page_id:saved.document.pages[0].id,node:{id:'scripted',type:'container',name:'脚本组件',style:{x:40,y:40,width:360,height:260},props:{},script:{source:"export function mount(ctx) { const target=ctx.find('inner'); if(!target)throw new Error('Missing extracted child'); target.dataset.parentReference='resolved'; return()=>{delete target.dataset.parentReference;}; }"},children:[{id:'inner',type:'container',name:'内部组合',style:{x:20,y:20,width:160,height:140},props:{},script:{source:childSource},children:[{id:'target',type:'shape',name:'目标',style:{x:20,y:20,width:70,height:70,background:'#b9d8bb'},props:{},children:[]}]}]}}]});
  browser=await chromium.launch({headless:true,channel:process.env.LEAFLOOM_BROWSER_CHANNEL||'chrome'});
  const context=await browser.newContext({viewport:{width:1560,height:1050},locale:'zh-CN'});await context.addInitScript(()=>localStorage.setItem('leafloom-locale','zh-CN'));page=await context.newPage();
  const errors=[],operations=[];page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>{if(new URL(request.url()).pathname==='/api/design/operations'&&request.method()==='POST')operations.push(request.postDataJSON());});
  await page.goto(info.ui);await page.locator('.sidebar').getByRole('button',{name:'设计工作台',exact:true}).click();await page.locator('.design-project-title').getByText('Script Components',{exact:true}).click();
  const frame=()=>page.frameLocator('.dw-runtime'),toolbar=()=>page.locator('.dw-toolbar');
  await frame().locator('[data-studio-select-id="scripted"]').waitFor();await page.locator('.dw-layer-select').filter({hasText:'脚本组件'}).click();
  const extraction=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/design/operations'&&response.request().method()==='POST');await page.getByRole('button',{name:'创建主组件',exact:true}).click();assert.ok((await extraction).ok());await page.locator('.dw-save-status').filter({hasText:'已保存'}).waitFor();
  saved=await request('design/document?directory=ScriptComponents');let master=Object.values(saved.document.components)[0],inner=master.node.children[0],target=inner.children[0];
  assert.equal(saved.document.pages[0].nodes[0].type,'instance');assert.equal(saved.document.pages[0].nodes[0].script,undefined);
  assert.notEqual(inner.id,'inner');assert.notEqual(target.id,'target');assert.ok(master.node.script.source.includes(inner.id));assert.ok(inner.script.source.includes(target.id));assert.ok(inner.script.source.includes("const untouched='target'"));assert.ok(inner.script.source.includes("/* ctx.find('target') */"));
  await toolbar().getByRole('button',{name:'交互预览',exact:true}).click();await frame().locator('[data-parent-reference="resolved"]').waitFor();await frame().locator('[data-child-reference="resolved"]').waitFor();
  await toolbar().getByRole('button',{name:'停止预览',exact:true}).click();await frame().locator('[data-child-reference="resolved"]').first().waitFor({state:'detached'});
  await page.getByRole('button',{name:'编辑主组件',exact:true}).click();await page.locator('.dw-canvas-heading').getByRole('button',{name:'退出主组件',exact:true}).waitFor();await page.locator('.dw-layer-select').filter({hasText:'内部组合'}).click();
  const duplicate=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/design/operations'&&response.request().method()==='POST');await page.locator('.dw-inspector').getByRole('button',{name:'复制元素',exact:true}).click();assert.ok((await duplicate).ok());await page.locator('.dw-save-status').filter({hasText:'已保存'}).waitFor();
  saved=await request('design/document?directory=ScriptComponents');master=Object.values(saved.document.components)[0];assert.equal(master.node.children.length,2);const copy=master.node.children[1];assert.notEqual(copy.id,inner.id);assert.notEqual(copy.children[0].id,target.id);assert.ok(copy.script.source.includes(copy.children[0].id));assert.ok(!copy.script.source.includes("ctx.find('"+target.id+"')"));assert.ok(copy.script.source.includes("/* ctx.find('target') */"));
  assert.ok(operations.some(body=>body.commands.some(command=>command.type==='component.from_node')));assert.ok(operations.some(body=>body.commands.some(command=>command.type==='component.edit'&&command.commands.some(nested=>nested.type==='node.duplicate'))));
  const expectCount=async(count)=>{await toolbar().getByRole('button',{name:'交互预览',exact:true}).click();await frame().locator('[data-child-reference="resolved"]').nth(count-1).waitFor();assert.equal(await frame().locator('[data-child-reference="resolved"]').count(),count);await toolbar().getByRole('button',{name:'停止预览',exact:true}).click();await frame().locator('[data-child-reference="resolved"]').first().waitFor({state:'detached'});};
  await expectCount(2);await toolbar().getByRole('button',{name:/^撤销/}).click();await page.locator('.dw-save-status').filter({hasText:'已保存'}).waitFor();await expectCount(1);await toolbar().getByRole('button',{name:/^重做/}).click();await page.locator('.dw-save-status').filter({hasText:'已保存'}).waitFor();await expectCount(2);
  assert.deepEqual(errors,[]);assert.equal(await page.locator('.dw-console').filter({hasText:/Missing (copied|extracted) child/}).count(),0);
  console.log(JSON.stringify({ok:true,checks:['ui-extraction-remaps-literal-ctx-find','ui-master-duplicate-uses-canonical-command','copied-scripts-resolve-own-children','undo-redo-preserves-script-references'],temp},null,2));
 }catch(error){if(page)try{await page.screenshot({path:path.join(temp,'failure.png'),fullPage:true});}catch{}console.error('Component script fixture retained at '+temp);throw error;}
 finally{await browser?.close();server.kill('SIGTERM');}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
