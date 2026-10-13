// Real browser verification of draft and position preservation on language switch.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.LEAFLOOM_BROWSER_CHANNEL||'msedge'});
 const page=await browser.newPage({viewport:{width:1600,height:1000}}),base='http://127.0.0.1:18089',errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 try{
  await page.goto(base);await page.locator('main').first().waitFor();
  const api=async(resource,body,method)=>page.evaluate(async({resource,body,method})=>{
   const session=await(await fetch('/api/session')).json();if(!session.demo)throw Error('Use only the promo fixture');
   const response=await fetch('/api/'+resource,{method:method||(body===undefined?'GET':'POST'),headers:{'Content-Type':'application/json','X-Vault-CSRF':session.csrf},body:body===undefined?undefined:JSON.stringify(body)});
   if(!response.ok)throw Error('Fixture request failed');return response.json();
  },{resource,body,method});
  const fixture=await api('promo/seed',{locale:'en'}),note=await api('file?path=Notes%2F01-Capture.md');
  const marker='LEAFLOOM UNSAVED DRAFT';
  await page.evaluate(({root,note,marker})=>localStorage.setItem('draft:'+root+'\nNotes/01-Capture.md',JSON.stringify({text:note.text+'\n\n'+marker,etag:note.etag,manualSave:true})),{root:fixture.root,note,marker});
  await page.goto(base+'/?note=Notes%2F01-Capture.md');await page.locator('.ai-draft-banner').waitFor();
  const area=page.locator('.document:visible .writing-area');await area.evaluate(el=>el.scrollTop=180);const before=await area.evaluate(el=>el.scrollTop);
  const revision=(await api('session')).config.revision;
  await page.getByRole('button',{name:'Settings',exact:true}).click();await page.getByRole('combobox',{name:'Language',exact:true}).selectOption('ja');
  await page.waitForFunction(()=>document.documentElement.lang==='ja');
  await page.getByRole('button',{name:'設定を閉じる',exact:true}).first().click();
  await page.getByText('AI の下書きはまだファイルに保存されていません',{exact:true}).waitFor();
  assert(await page.locator('.document:visible').innerText().then(text=>text.includes(marker)));
  assert.equal(await area.evaluate(el=>el.scrollTop),before);assert.equal((await api('session')).config.revision,revision);
  assert(!(await api('file?path=Notes%2F01-Capture.md')).text.includes(marker),'Language switch wrote the draft');
  await page.reload();await page.locator('.ai-draft-banner').waitFor();assert(await page.locator('.document:visible').innerText().then(text=>text.includes(marker)));
  assert.deepEqual(errors,[]);const report={checks:['manual draft remains unsaved','memoized document translates immediately','reading position retained','configuration revision unchanged','language and draft survive reload'],errors};
  fs.writeFileSync('.cache/leafloom/draft-language-validation.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
