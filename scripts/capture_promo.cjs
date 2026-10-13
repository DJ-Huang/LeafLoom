// Run only against scripts/promo_server.py; never against a user's service.
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base=process.env.LEAFLOOM_DEMO_URL||'http://127.0.0.1:18089';
assert(/^http:\/\/127\.0\.0\.1:18089$/.test(base),'Only the isolated demo server is permitted');
const catalogs=Object.fromEntries(['en','zh-CN','ja'].map(l=>[l,require('../vault_rag/locales/'+l+'.json')]));
async function main(){
 const browser=await chromium.launch({headless:true,channel:process.env.LEAFLOOM_BROWSER_CHANNEL||'msedge'}),checks=[],errors=[];
 try{
 for(const language of ['en','zh-CN','ja']){
  const page=await browser.newPage({viewport:{width:1600,height:1000},deviceScaleFactor:1,locale:language});
  page.on('pageerror',error=>errors.push(language+': '+error.message));
  const text=key=>catalogs[language][key]||key;
  const output=path.resolve('assets/screenshots',language);fs.mkdirSync(output,{recursive:true});
  const api=async(resource,body,method)=>page.evaluate(async({resource,body,method})=>{
   const session=await(await fetch('/api/session')).json();
   if(!session.demo)throw Error('This is not the isolated demo fixture');
   const response=await fetch('/api/'+resource,{method:method||(body===undefined?'GET':'POST'),headers:{'Content-Type':'application/json','X-Vault-CSRF':session.csrf},body:body===undefined?undefined:JSON.stringify(body)});
   const result=await response.json();if(!response.ok)throw Error(result.error||'Fixture request failed');return result;
  },{resource,body,method});
  await page.goto(base);await page.locator('main').first().waitFor();
  const original=(await api('session')).config;
  await api('config',{...original,root:null});await api('preferences',{locale:language},'PUT');await page.reload();
  await page.getByRole('button',{name:text('体验演示知识库'),exact:true}).waitFor();
  const shot=async name=>{
   await page.evaluate(async()=>{await document.fonts.ready;});
   await page.evaluate(()=>{
    for(const node of document.querySelectorAll('input'))if(/^(?:[a-z]:[\\/]|\/(?:Users|home|private|tmp)\/)/i.test(node.value)){node.dataset.original=node.value;node.value='Demo vault';}
    for(const node of document.querySelectorAll('.brand>div>span,.dashboard-footer>span:last-child')){node.dataset.originalText=node.textContent;node.textContent='Demo vault';}
   });
   await page.screenshot({path:path.join(output,name+'.png'),animations:'disabled'});
   const visible=await page.locator('body').innerText();assert(!/(?:[a-z]:[\\/]Users[\\/]|\/(?:Users|home)\/)|auth-token|Bearer\s+[a-f0-9]{20}/i.test(visible),'Private data in capture');
   await page.evaluate(()=>{for(const node of document.querySelectorAll('input[data-original]')){node.value=node.dataset.original;delete node.dataset.original;}for(const node of document.querySelectorAll('[data-original-text]')){node.textContent=node.dataset.originalText;delete node.dataset.originalText;}});
  };
  await shot('01-welcome');
  // Exercise the actual welcome, resumable scope and preparation guide.
  await page.getByRole('button',{name:text('体验演示知识库'),exact:true}).click();
  await page.getByRole('heading',{name:text('哪些笔记参与检索？')}).waitFor();await page.reload();
  await page.getByRole('heading',{name:text('哪些笔记参与检索？')}).waitFor();
  await page.getByRole('checkbox',{name:text('整个关联目录'),exact:true}).check();
  await page.getByRole('button',{name:text('保存范围并继续'),exact:true}).click();
  await page.getByRole('button',{name:text('开始探索'),exact:true}).click();
  checks.push(language+': demo setup resumes, explicit search scope and finish');
  const fixture=await api('promo/seed',{locale:language});
  await page.reload();await page.getByRole('heading',{name:text('你的知识库'),exact:true}).waitFor();
  await shot('02-home');
  await page.goto(base+'/?note='+encodeURIComponent('Notes/01-Capture.md'));
  await page.locator('.document:visible .markdown h1').waitFor();
  await shot('03-reading');
  await page.getByRole('button',{name:text('知识检索'),exact:true}).click();
  await page.getByRole('textbox',{name:text('检索知识'),exact:true}).fill(fixture.query);
  await page.getByRole('button',{name:text('检索'),exact:true}).click();
  await page.locator('.search-result').first().waitFor();
  assert(await page.locator('.search-result').count()>0);await shot('04-search');
  await page.locator('.search-result').first().click();await page.locator('.document:visible .markdown h1').waitFor();
  await page.getByRole('button',{name:text('返回检索结果'),exact:true}).click();assert(await page.getByRole('textbox',{name:text('检索知识')}).inputValue()===fixture.query);
  checks.push(language+': real keyword retrieval, source opens, query retained');
  await page.getByRole('button',{name:text('关系图谱'),exact:true}).click();
  await page.locator('.graph[aria-busy=false]').waitFor();await page.waitForTimeout(1600);
  for(let zoom=0;zoom<4;zoom++)await page.getByRole('button',{name:text('放大图谱'),exact:true}).click();await shot('05-graph');
  await page.goto(base+'/?note='+encodeURIComponent('Notes/03-Connect.md'));
  await page.locator('.document:visible .markdown h1').waitFor();
  await page.evaluate(({root,topic})=>localStorage.setItem('ai-topic:'+root,topic),fixture);
  await page.getByRole('button',{name:text('AI 对话'),exact:true}).click();
  await page.locator('.ai-panel:not([hidden])').waitFor();
  await page.locator('.ai-answer .markdown').waitFor();await shot('06-ai');
  await page.getByRole('button',{name:text('关闭 AI 面板'),exact:true}).click();
  await page.getByRole('button',{name:text('设置'),exact:true}).click();
  await page.getByRole('button',{name:text('检索与索引'),exact:true}).click();
  await page.getByRole('heading',{name:text('进入知识检索的目录'),exact:true}).waitFor();await shot('07-settings');
  await page.getByRole('button',{name:text('关闭设置'),exact:true}).first().click();
  // Live language changes must preserve a real unsaved AI/manual draft.
  await page.goto(base+'/?note='+encodeURIComponent('Notes/01-Capture.md'));
  await page.locator('.document:visible .markdown h1').waitFor();
  const scopeBefore=(await api('session')).config.revision;
  await page.getByRole('button',{name:text('设置'),exact:true}).click();
  const nextLanguage=language==='en'?'ja':'en';await page.getByRole('combobox',{name:text('界面语言'),exact:true}).selectOption(nextLanguage);
  await page.waitForFunction(l=>document.documentElement.lang===l,nextLanguage);
  assert.equal((await api('session')).config.revision,scopeBefore);
  await page.getByRole('combobox',{name:catalogs[nextLanguage]['界面语言'],exact:true}).selectOption(language);
  await page.waitForFunction(l=>document.documentElement.lang===l,language);
  await page.getByRole('button',{name:text('关闭设置'),exact:true}).first().click();
  assert(await page.locator('.document:visible .markdown h1').isVisible());checks.push(language+': language switch keeps document and configuration revision');
  await page.setViewportSize({width:390,height:844});await shot('08-mobile');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile horizontal overflow');
  checks.push(language+': responsive layout without horizontal overflow');await page.close();
 }
 assert.deepEqual(errors,[]);
 fs.mkdirSync('.cache/leafloom',{recursive:true});fs.writeFileSync('.cache/leafloom/browser-validation.json',JSON.stringify({checks,errors},null,2));
 console.log(JSON.stringify({screenshots:24,checks,errors}));
 }finally{await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
