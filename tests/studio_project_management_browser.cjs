// Focused legacy project management: old-service diagnostics and recoverable deletion.
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net'),crypto=require('node:crypto');
const {spawn}=require('node:child_process');
const {chromium}=require('../desktop/node_modules/playwright-core');
const repository=path.resolve(__dirname,'..');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function freePort(){const server=net.createServer();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const port=server.address().port;await new Promise(resolve=>server.close(resolve));return port;}
function snapshot(root){const result={};function visit(directory){for(const item of fs.readdirSync(directory,{withFileTypes:true})){const file=path.join(directory,item.name);if(item.isDirectory())visit(file);else result[path.relative(root,file)]=crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');}}visit(root);return result;}
async function main(){
 const home=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'leafloom-project-management-'))),port=await freePort();
 const log=fs.openSync(path.join(home,'server.log'),'a');
 const server=spawn(path.join(repository,'.venv/bin/python'),[path.join(__dirname,'html_projects_server.py'),'--directory',home,'--port',String(port)],{cwd:repository,stdio:['ignore',log,log]});fs.closeSync(log);
 let browser,page;
 try{
  let started=false;for(let attempt=0;attempt<150;attempt++){try{if((await fetch('http://127.0.0.1:'+port+'/healthz')).ok){started=true;break;}}catch{}await sleep(100);}assert.ok(started);
  const info=JSON.parse(fs.readFileSync(path.join(home,'info.json'))),token=fs.readFileSync(path.join(info.state,'auth-token'),'utf8').trim();
  const response=await fetch(info.url+'/api/design/projects',{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify({root:info.root,directory:'Projects/DeleteFixture',name:'Delete fixture',managed:false})});assert.ok(response.ok,await response.text());
  const project=path.join(info.root,'Projects/DeleteFixture');fs.writeFileSync(path.join(project,'retained.bin'),Buffer.from([0,1,2,255,128]));const before=snapshot(project);
  browser=await chromium.launch({headless:true,channel:'chrome'});const context=await browser.newContext({viewport:{width:1450,height:1000},locale:'zh-CN'});await context.addInitScript(()=>localStorage.setItem('leafloom-locale','zh-CN'));
  page=await context.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/api/design/workspace',route=>route.fulfill({status:404,contentType:'application/json',body:JSON.stringify({detail:'Not Found'})}));
  await page.goto(info.ui);await page.locator('.sidebar').getByRole('button',{name:'设计工作台',exact:true}).click();
  const homeView=page.locator('.design-project-home');await homeView.getByRole('alert').filter({hasText:'当前后台尚未加载项目管理功能'}).waitFor();
  const card=homeView.locator('.design-project-card').filter({hasText:'Delete fixture'});await card.locator('summary').click();
  await assert.equal(await card.getByRole('button',{name:'移到回收站',exact:true}).isDisabled(),true);assert.ok(fs.existsSync(project));
  await page.unroute('**/api/design/workspace');await homeView.getByRole('button',{name:'重试',exact:true}).click();
  await homeView.getByRole('alert').waitFor({state:'detached'});await card.getByRole('button',{name:'移到回收站',exact:true}).click();
  await card.waitFor({state:'detached'});assert.equal(fs.existsSync(project),false);
  await homeView.getByRole('tab',{name:'回收站',exact:true}).click();const deleted=homeView.locator('.design-project-card').filter({hasText:'Delete fixture'});await deleted.getByRole('button',{name:'恢复项目',exact:true}).click();
  await deleted.waitFor({state:'detached'});assert.deepEqual(snapshot(project),before);
  await homeView.getByRole('tab',{name:'最近项目',exact:true}).click();await card.waitFor();assert.deepEqual(errors,[]);
  const evidence=path.join(repository,'.cache/studio-qa');fs.mkdirSync(evidence,{recursive:true});await page.screenshot({path:path.join(evidence,'project-management-fixed.png')});
  console.log(JSON.stringify({ok:true,checks:['missing-workspace-route-restart-message','management-disabled-until-ready','retry-loads-management','legacy-project-delete-and-recycle','restore-preserves-all-files'],pageErrors:errors},null,2));
 }catch(error){if(page)try{await page.screenshot({path:path.join(home,'failure.png')});}catch{}console.error('Fixture retained at '+home);throw error;}
 finally{await browser?.close();server.kill('SIGTERM');}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
