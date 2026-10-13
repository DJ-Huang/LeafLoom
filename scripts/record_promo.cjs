// Record real product operations only on the isolated, fictional demo service.
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process');
const base=process.env.LEAFLOOM_DEMO_URL||'http://127.0.0.1:18089';
assert.equal(base,'http://127.0.0.1:18089');
const output=path.resolve('assets/promo/recordings');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function main(){
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:process.env.LEAFLOOM_BROWSER_CHANNEL||'msedge'});
 const selected=process.env.LEAFLOOM_SCENES?.split(',');
 const errors=[],scenes=selected&&fs.existsSync(path.join(output,'take.json'))?JSON.parse(fs.readFileSync(path.join(output,'take.json'),'utf8')).scenes:[];let fixture;
 const api=async(page,resource,body)=>page.evaluate(async({resource,body})=>{
  const session=await(await fetch('/api/session')).json();if(!session.demo)throw Error('Not the demo fixture');
  const response=await fetch('/api/'+resource,{method:'POST',headers:{'Content-Type':'application/json','X-Vault-CSRF':session.csrf},body:JSON.stringify(body)});
  if(!response.ok)throw Error('Demo request failed');return response.json();
 },{resource,body});
 async function record(name,prepare,perform){
  if(selected&&!selected.includes(name))return;
  const context=await browser.newContext({viewport:{width:1600,height:900},locale:'en',recordVideo:{dir:output,size:{width:1600,height:900}}});
  await context.addInitScript(()=>{
   document.addEventListener('DOMContentLoaded',()=>{
    const style=document.createElement('style');style.textContent=`
     *{cursor:none!important} .brand>div>span,.dashboard-footer>span:last-child{font-size:0!important}
     .brand>div>span::after,.dashboard-footer>span:last-child::after{content:'Demo vault';font-size:11px}
     input.promo-private{color:transparent!important;caret-color:transparent!important}
     .promo-path-label{position:absolute;font:14px system-ui;color:#52574e;pointer-events:none}
     #promo-pointer{position:fixed;width:27px;height:33px;pointer-events:none;z-index:2147483647;filter:drop-shadow(0 2px 3px #0006);left:-80px;top:-80px}
     .promo-click{position:fixed;width:24px;height:24px;border:3px solid #56aa82;border-radius:50%;pointer-events:none;z-index:2147483646;animation:promo-click .48s ease-out forwards}
     @keyframes promo-click{from{transform:translate(-50%,-50%) scale(.4);opacity:1}to{transform:translate(-50%,-50%) scale(2);opacity:0}}
    `;document.head.append(style);
    const cursor=document.createElement('div');cursor.id='promo-pointer';cursor.innerHTML='<svg viewBox="0 0 27 33"><path d="M2 1L2 26L9 21L14 31L20 28L15 18L25 17Z" fill="#245c48" stroke="#fff" stroke-width="2"/></svg>';document.body.append(cursor);
    document.addEventListener('mousemove',e=>{cursor.style.left=e.clientX+'px';cursor.style.top=e.clientY+'px';});
    document.addEventListener('pointerdown',e=>{const dot=document.createElement('i');dot.className='promo-click';dot.style.left=e.clientX+'px';dot.style.top=e.clientY+'px';document.body.append(dot);setTimeout(()=>dot.remove(),500);},true);
    const mask=()=>{for(const input of document.querySelectorAll('input'))if(/^(?:[a-z]:[\\/]|\/(?:Users|home|private|tmp)\/)/i.test(input.value)){
     input.classList.add('promo-private');
    }for(const node of document.querySelectorAll('[title]'))if(/(?:[a-z]:[\\/]|\/Users\/)/i.test(node.title))node.removeAttribute('title');};
    new MutationObserver(mask).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['value']});mask();
   });
  });
  const epoch=Date.now(),page=await context.newPage();page.setDefaultTimeout(30000);page.on('pageerror',e=>errors.push(e.message));
  const goto=page.goto.bind(page);page.goto=(url,options={})=>goto(url,{waitUntil:'domcontentloaded',...options});
  await page.goto(base);await page.locator('main').first().waitFor();
  await prepare(page);
  await page.evaluate(()=>document.fonts.ready);await pause(450);
  if(name==='write')await page.locator('.document:visible .writing-area').evaluate(area=>{
   const line=area.querySelector('.cm-content .cm-line:last-child');
   area.scrollTop+=line.getBoundingClientRect().top-area.getBoundingClientRect().top-area.clientHeight*.48;
  });
  // A two-pixel timing mark is cropped out by the editor. Browser video can
  // begin late, so page-creation wall time is not a reliable source timecode.
  await page.evaluate(()=>{const marker=document.createElement('div');marker.id='promo-timecode';marker.style.cssText='position:fixed;left:0;bottom:0;width:8px;height:2px;background:#ff00ef;z-index:2147483647;pointer-events:none';document.body.append(marker);});
  const start=(Date.now()-epoch)/1000,actions=[];
  const click=async(locator,label)=>{await locator.waitFor({state:'visible'});await locator.scrollIntoViewIfNeeded();const box=await locator.boundingBox();assert(box);const x=box.x+box.width/2,y=box.y+box.height/2;
   await page.mouse.move(x,y,{steps:18});await pause(130);actions.push({time:(Date.now()-epoch)/1000-start,label,x:Math.round(x),y:Math.round(y)});await page.mouse.click(x,y);};
  await perform(page,click);await pause(650);
  const wallDuration=(Date.now()-epoch)/1000-start;
  await page.evaluate(()=>document.getElementById('promo-timecode').remove());
  const visible=await page.locator('body').innerText();assert(!/(?:[a-z]:[\\/]Users[\\/]|\/(?:Users|home)\/)|Bearer\s+[a-f0-9]{20}/i.test(visible));
  await page.screenshot({path:path.join(output,name+'-end.png')});
  const video=page.video();await context.close();await video.saveAs(path.join(output,name+'.webm'));await video.delete();
  const samples=spawnSync('ffmpeg',['-hide_banner','-loglevel','error','-i',path.join(output,name+'.webm'),'-vf','fps=30,crop=8:2:0:898,format=rgb24','-f','rawvideo','pipe:1']);
  assert.equal(samples.status,0);const frames=[];
  for(let at=0;at<samples.stdout.length;at+=48){const rgb=samples.stdout.subarray(at,at+48);let matches=0;for(let p=0;p<48;p+=3)if(rgb[p]>190&&rgb[p+1]<60&&rgb[p+2]>160)matches++;if(matches>=10)frames.push(at/48);}
  assert(frames.length>15,'Missing video timing marker');
  const videoStart=frames[0]/30,duration=(frames.at(-1)+1-frames[0])/30;
  assert(Math.abs(duration-wallDuration)<.5,'Browser recording lost operation time');
  const existing=scenes.findIndex(s=>s.name===name);if(existing>=0)scenes.splice(existing,1);
  scenes.push({name,source:'assets/promo/recordings/'+name+'.webm',start:Number(videoStart.toFixed(3)),duration:Number(duration.toFixed(3)),actions});
  fs.writeFileSync(path.join(output,'take.json'),JSON.stringify({language:'en',viewport:[1600,900],fixture:'Fictional notes; external AI disabled',scenes,errors},null,2)+'\n');
  console.log(name+': '+duration.toFixed(2)+' seconds, '+actions.length+' real clicks');
 }
 try{
  const setup=await browser.newPage();await setup.goto(base,{waitUntil:'domcontentloaded'});fixture=await api(setup,'promo/seed',{locale:'en',reset_recording:!selected||selected.includes('write')});await setup.close();
  await record('write',async page=>{
   await page.goto(base+'/?note=Notes%2F01-Capture.md');await page.locator('.document:visible .markdown h1').waitFor();
   await page.getByRole('button',{name:'Edit',exact:true}).click();
   const editor=page.locator('.document:visible .cm-content');await editor.waitFor();
   // Give the recording's editor enough trailing space to center the caret.
   // This presentation style does not change the application's saved CSS.
   await page.addStyleTag({content:'.document .cm-content, .document .reading-content { padding-bottom:440px !important; }'});
   await editor.click();await page.keyboard.press('Control+End');
   await page.keyboard.type('\n\n## Reading corner\n');
   await pause(1400);
   await page.locator('.document:visible .writing-area').evaluate(area=>{
    const line=area.querySelector('.cm-content .cm-line:last-child');
    area.scrollTop+=line.getBoundingClientRect().top-area.getBoundingClientRect().top-area.clientHeight*.48;
   });
   await pause(250);
  },async(page,click)=>{
   await pause(400);const line=page.locator('.document:visible .cm-line').last();
   const bounds=await line.boundingBox();
   assert(bounds&&bounds.y>250&&bounds.y<600,'Writing must begin near the center');
   await click(line,'Write a note');await page.keyboard.type('Keep one useful idea from every book.\n',{delay:45});
   await pause(1100);await click(page.getByRole('button',{name:'Read',exact:true}),'Read');
   await page.getByRole('heading',{name:'Reading corner',exact:true}).waitFor();await pause(350);
   await page.locator('.document:visible .writing-area').evaluate(area=>{
    const heading=[...area.querySelectorAll('h2')].find(node=>node.textContent==='Reading corner');
    area.scrollTop+=heading.getBoundingClientRect().top-area.getBoundingClientRect().top-area.clientHeight*.48;
   });await pause(950);
   assert(await page.locator('.document:visible').innerText().then(t=>t.includes('Reading corner')));
  });
  await record('search',async page=>{
   await page.getByRole('button',{name:'Knowledge search',exact:true}).click();await page.getByRole('textbox',{name:'Search knowledge',exact:true}).waitFor();
  },async(page,click)=>{
   await pause(400);const query=page.getByRole('textbox',{name:'Search knowledge',exact:true});await click(query,'Search the vault');await query.pressSequentially('reading corner',{delay:68});
   await click(page.getByRole('button',{name:'Search',exact:true}),'Search');await page.locator('.search-result').first().waitFor();await pause(900);
   await click(page.locator('.search-result').filter({hasText:'01-Capture'}).first(),'Open the original');await page.locator('.document:visible .markdown h1').waitFor();await pause(900);
   assert(await page.locator('.document:visible').innerText().then(t=>t.includes('Reading corner')));
  });
  await record('graph',async page=>{
   await page.getByRole('button',{name:'Knowledge graph',exact:true}).click();await page.locator('.graph[aria-busy=false]').waitFor();await pause(900);
  },async(page,click)=>{
   await pause(250);const query=page.getByRole('combobox',{name:'Search graph notes',exact:true});await click(query,'Find a connected idea');await query.pressSequentially('Connect',{delay:65});
   await click(page.getByRole('option').filter({hasText:'Connect the dots'}).first(),'Focus this note');await page.locator('.graph-inspector').waitFor();await pause(650);
   await click(page.getByRole('button',{name:'Explore connections',exact:true}),'Explore connections');await page.locator('.graph[aria-busy=false]').waitFor();await pause(600);
   await click(page.getByRole('button',{name:'Zoom in',exact:true}),'Zoom into the graph');await pause(600);
   const box=await page.locator('.graph').boundingBox();await page.mouse.move(box.x+box.width*.5,box.y+box.height*.5,{steps:12});await page.mouse.down();await page.mouse.move(box.x+box.width*.5+85,box.y+box.height*.5-30,{steps:24});await page.mouse.up();await pause(800);
   assert(await page.locator('.graph-focus-bar').isVisible());
  });
  await record('ai-review',async page=>{
   await api(page,'promo/proposal',{topic:fixture.topic});await page.goto(base+'/?note=Notes%2F01-Capture.md');await page.locator('.document:visible .markdown h1').waitFor();
   await page.evaluate(({root,topic})=>localStorage.setItem('ai-topic:'+root,topic),fixture);
   await page.getByRole('button',{name:'AI chat',exact:true}).click();await page.locator('.ai-proposal').waitFor();
  },async(page,click)=>{
   await pause(300);await click(page.locator('.ai-proposal summary'),'Preview changes');await pause(1050);
   await click(page.getByRole('button',{name:'Accept into draft',exact:true}),'Accept into draft');await page.locator('.ai-draft-banner').waitFor();await pause(900);
   await click(page.getByRole('button',{name:'Close AI panel',exact:true}),'Review the draft');await pause(500);
   assert(await page.locator('.ai-draft-banner').isVisible());
  });
  await record('scope',async page=>{
   await page.getByRole('button',{name:'Settings',exact:true}).click();await page.getByRole('button',{name:'Search and indexing',exact:true}).click();await page.getByRole('checkbox',{name:'Index Notes',exact:true}).waitFor();
  },async(page,click)=>{
   await pause(200);await click(page.getByRole('checkbox',{name:'Entire connected folder',exact:true}),'Choose the search scope');
   await pause(200);await click(page.getByRole('checkbox',{name:'Index Notes',exact:true}),'Include only Notes');await pause(300);
   await click(page.getByRole('button',{name:'Save settings',exact:true}),'Save your choice');await pause(700);
   const config=await page.evaluate(async()=> (await(await fetch('/api/session')).json()).config);assert.deepEqual(config.include_roots,['Notes']);
  });
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(output,'take.json'),JSON.stringify({language:'en',viewport:[1600,900],fixture:'Fictional notes; external AI disabled',scenes,errors},null,2)+'\n');
 }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
