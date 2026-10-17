// Focused, disposable project-creation regression. No canvas iframe or TLS dependency.
// Run after `npm run build --prefix web` (CI uses desktop's pinned Playwright).
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net'),crypto=require('node:crypto');
const {spawn}=require('node:child_process');
const {chromium}=require(process.env.LEAFLOOM_PLAYWRIGHT||'../desktop/node_modules/playwright-core');
const root=path.resolve(__dirname,'..'),evidence=path.join(root,'.cache/studio-qa');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function freePort(){const server=net.createServer();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const port=server.address().port;await new Promise(resolve=>server.close(resolve));return port;}
// Include directories as well as file hashes, so an empty accidental project is visible.
// Workspace bookkeeping is separate from the user's files and is expected to change.
function snapshot(directory){const result={};function visit(folder){for(const item of fs.readdirSync(folder,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){if(folder===directory&&item.name==='.vault-rag')continue;const file=path.join(folder,item.name),relative=path.relative(directory,file);result[relative]=item.isDirectory()?'directory':crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');if(item.isDirectory())visit(file);}}visit(directory);return result;}
async function main(){
 const temp=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'leafloom-studio-create-'))),port=await freePort();
 fs.mkdirSync(evidence,{recursive:true});
 const log=fs.openSync(path.join(temp,'server.log'),'a');
 const server=spawn(process.env.LEAFLOOM_PYTHON||path.join(root,'.venv/bin/python'),[path.join(__dirname,'html_projects_server.py'),'--directory',temp,'--port',String(port)],{cwd:root,stdio:['ignore',log,log]});fs.closeSync(log);
 let browser,page;const checks=[],pageErrors=[],creationRequests=[];
 try{
  let started=false;for(let attempt=0;attempt<150;attempt++){try{if((await fetch('http://127.0.0.1:'+port+'/healthz')).ok){started=true;break;}}catch{}await sleep(100);}assert.ok(started,'Disposable service did not start; inspect '+path.join(temp,'server.log'));
  const info=JSON.parse(fs.readFileSync(path.join(temp,'info.json'))),token=fs.readFileSync(path.join(info.state,'auth-token'),'utf8').trim();
  const request=async(endpoint,body)=>{const response=await fetch(info.url+'/api/'+endpoint,{method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const value=await response.json();assert.ok(response.ok,JSON.stringify(value));return value;};
  for(const folder of ['Projects/BranchA/Deep','Projects/BranchB','Other'])fs.mkdirSync(path.join(info.root,folder),{recursive:true});
  fs.writeFileSync(path.join(info.root,'Projects/retain.txt'),'User files must remain unchanged.\n');
  await request('design/projects',{root:info.root,managed:true,directory:'ExistingStudio',name:'Existing studio',width:800,height:600});
  const existingBefore=snapshot(path.join(info.root,'ExistingStudio'));
  const launch={headless:true};if(process.env.LEAFLOOM_BROWSER_EXECUTABLE)launch.executablePath=process.env.LEAFLOOM_BROWSER_EXECUTABLE;else launch.channel=process.env.LEAFLOOM_BROWSER_CHANNEL||'chrome';
  browser=await chromium.launch(launch);
  const context=await browser.newContext({viewport:{width:1450,height:1100},locale:'zh-CN'});
  await context.addInitScript(()=>localStorage.setItem('leafloom-locale','zh-CN'));
  page=await context.newPage();page.setDefaultTimeout(15000);
  page.on('pageerror',error=>pageErrors.push(error.message));
  page.on('request',request=>{if(new URL(request.url()).pathname==='/api/design/projects'&&request.method()==='POST')creationRequests.push(request.postDataJSON());});
  // The host UI, server API and on-disk project are real. The isolated canvas is
  // irrelevant to this dialog regression and must not gate it on local TLS/DNS.
  await page.route('**/*',route=>route.request().isNavigationRequest()&&route.request().frame()!==page.mainFrame()?route.abort():route.continue());
  await page.goto(info.ui);await page.locator('.sidebar').getByRole('button',{name:'设计工作台',exact:true}).click();
  const home=()=>page.locator('.design-home-heading').getByRole('button',{name:'新建设计项目',exact:true});
  const dialog=()=>page.getByRole('dialog');
  const folder=()=>dialog().getByLabel('项目文件夹名称（英文或中文目录名）',{exact:true});
  const displayName=()=>dialog().getByLabel('项目显示名称',{exact:true});
  const treeButton=name=>dialog().locator('.design-folder-tree').getByRole('button',{name,exact:true});
  const rootButton=()=>dialog().getByRole('button',{name:'知识库根目录 /',exact:true});
  const parent=()=>dialog().locator('.design-target-preview code').first();
  const target=()=>dialog().locator('.design-target-preview code').last();
  const open=async(template,slug)=>{await home().click();await dialog().locator('[data-template-id="'+template+'"]').click();await folder().fill(slug);await displayName().fill('Creation regression '+template);await treeButton('Projects').waitFor();};
  const unchanged=async(before,label,count=0)=>{await page.waitForTimeout(100);assert.equal(creationRequests.length,count,label+': no creation request');assert.deepEqual(snapshot(info.root),before,label+': no filesystem changes');};
  for(const template of ['blank','forma']){
   for(const dismissal of ['cancel','escape']){
    const slug='Uncreated-'+template+'-'+dismissal,before=snapshot(info.root);
    await open(template,slug);
    for(const name of ['Projects','BranchA','Deep','BranchA','BranchA','BranchB']){
     await treeButton(name).click();await unchanged(before,template+' click '+name);
    }
    await treeButton('BranchB').focus();await page.keyboard.press('Enter');await unchanged(before,template+' directory Enter');
    await treeButton('BranchA').focus();await page.keyboard.press('Space');await unchanged(before,template+' directory Space');
    await rootButton().click();assert.equal(await parent().innerText(),'/');assert.equal(await target().innerText(),'/'+slug);await unchanged(before,template+' root selection');
    await rootButton().focus();await page.keyboard.press('Enter');await page.keyboard.press('Space');await unchanged(before,template+' root keyboard selection');
    // A text field Enter is also not an explicit request to create a project.
    await displayName().focus();await page.keyboard.press('Enter');await unchanged(before,template+' field Enter');
    await page.screenshot({path:path.join(evidence,'create-'+template+'-'+dismissal+'.png'),fullPage:true});
    if(dismissal==='cancel')await dialog().getByRole('button',{name:'取消',exact:true}).click();else await page.keyboard.press('Escape');
    await dialog().waitFor({state:'detached'});await unchanged(before,template+' '+dismissal);
    checks.push(template+'-directory-mouse-keyboard-root-field-enter-'+dismissal+'-zero-creates');
   }
  }
  for(const [index,template] of ['blank','forma'].entries()){
   const slug='Created-'+template,directory='Projects/BranchA/'+slug;
   await open(template,slug);await treeButton('Projects').click();await treeButton('BranchA').click();
   assert.equal(await parent().innerText(),'/Projects/BranchA');assert.equal(await target().innerText(),'/'+directory);
   await page.screenshot({path:path.join(evidence,'create-'+template+'-selected-parent.png'),fullPage:true});
   let release;const gate=new Promise(resolve=>{release=resolve;});let arrived;const received=new Promise(resolve=>{arrived=resolve;});
   const hold=async route=>{if(route.request().method()!=='POST')return route.continue();arrived();await gate;await route.continue();};
   await page.route('**/api/design/projects',hold);
   const submit=dialog().getByRole('button',{name:'创建并打开设计工作台',exact:true});
   const createdEvent=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/design/projects'&&response.request().method()==='POST');createdEvent.catch(()=>{});
   try{
    // The explicit create control remains keyboard-accessible. Same-tick
    // duplicate handlers are separately covered by test_studio_create.cjs.
    await submit.focus();await page.keyboard.press(template==='blank'?'Enter':'Space');
    await Promise.race([received,sleep(15000).then(()=>{throw new Error('Explicit create did not reach the server');})]);
    await dialog().locator('.modal-footer .primary').evaluate(button=>{button.click();button.click();});
    await page.waitForTimeout(100);assert.equal(creationRequests.length,index+1,'One explicit create, despite duplicate activation');
    assert.equal(creationRequests.at(-1).directory,directory);
    assert.equal(creationRequests.at(-1).template_id,template==='forma'?'forma':undefined);
    assert.equal(await folder().isDisabled(),true);assert.equal(await displayName().isDisabled(),true);
    assert.equal(await rootButton().isDisabled(),true);assert.equal(await treeButton('BranchA').isDisabled(),true);
    for(const input of await dialog().locator('input, select').all())assert.equal(await input.isDisabled(),true,'All creation fields stay frozen while request is in flight');
    await page.keyboard.press('Escape');assert.equal(await dialog().isVisible(),true,'Escape must not dismiss an in-flight creation');
    await page.screenshot({path:path.join(evidence,'create-'+template+'-pending.png'),fullPage:true});
   }finally{release();}
   const response=await createdEvent;assert.ok(response.ok(),await response.text());await page.unroute('**/api/design/projects',hold);
   await dialog().waitFor({state:'detached'});await page.locator('.dw-toolbar strong').filter({hasText:'Creation regression '+template}).waitFor();
   assert.equal(creationRequests.length,index+1);
   const saved=await request('design/document?directory='+encodeURIComponent(directory));
   assert.equal(saved.document.name,'Creation regression '+template);assert.equal(saved.document.pages.length,template==='forma'?4:1);
   assert.ok(fs.existsSync(path.join(info.root,directory)));
   await page.locator('.dw-toolbar').getByRole('button',{name:'返回项目',exact:true}).click();
   const all=await request('design/projects');assert.equal(all.projects.filter(project=>project.directory===directory).length,1);
   checks.push(template+'-explicit-create-once-at-final-path-frozen-inputs-and-double-click-guard');
  }
  const afterCreation=snapshot(info.root);
  await page.locator('.design-project-title').getByText('Existing studio',{exact:true}).click();
  await page.locator('.dw-toolbar strong').filter({hasText:'Existing studio'}).waitFor();
  await page.locator('.dw-toolbar').getByRole('button',{name:'返回项目',exact:true}).click();
  await unchanged(afterCreation,'Open existing project',2);
  assert.deepEqual(snapshot(path.join(info.root,'ExistingStudio')),existingBefore,'Existing project bytes are unchanged');
  checks.push('existing-project-open-keeps-files-and-does-not-create');
  assert.deepEqual(pageErrors,[]);
  const result={ok:true,checks,creationRequests,pageErrors,temp};
  fs.writeFileSync(path.join(evidence,'create-regression.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
 }catch(error){if(page)try{await page.screenshot({path:path.join(evidence,'create-failure.png'),fullPage:true});fs.writeFileSync(path.join(temp,'failure.html'),await page.content());}catch{}console.error('Creation fixture retained at '+temp);throw error;}
 finally{await browser?.close();server.kill('SIGTERM');}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
