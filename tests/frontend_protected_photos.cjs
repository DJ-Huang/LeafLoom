'use strict';
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const net = require('node:net');
const path = require('node:path');
const readline = require('node:readline');
const {chromium} = require('../desktop/node_modules/playwright-core');

const root = path.resolve(__dirname, '..');

async function checkGalleryScroll(page){
 const database=page.locator('[data-database="Showcase.base"]');
 const first=database.locator('.db-card').first();
 const last=database.locator('[data-db-record="Showcase/Record 0007.md"].db-card');
 await first.hover();
 assert.ok((await last.boundingBox()).y>=page.viewportSize().height,'gallery must extend below the viewport');
 await page.mouse.wheel(0,3000);
 await page.waitForFunction(()=>{
  const database=document.querySelector('[data-database="Showcase.base"]');
  const card=database?.querySelector('[data-db-record="Showcase/Record 0007.md"].db-card')?.getBoundingClientRect();
  const footer=database?.querySelector('.db-footer')?.getBoundingClientRect();
  return card&&footer&&card.top>=0&&footer.bottom<=innerHeight;
 },undefined,{timeout:4000});
 await page.mouse.wheel(0,-3000);
 await page.waitForFunction(()=>{
  const first=document.querySelector('[data-database="Showcase.base"] .db-card');
  const bounds=first?.getBoundingClientRect();
  return bounds&&bounds.top>=0&&bounds.top<innerHeight;
 });
}

async function main() {
 const port = await new Promise(resolve => {
  const server=net.createServer();
  server.listen(0,'127.0.0.1',()=>{const port=server.address().port;server.close(()=>resolve(port));});
 });
 const fixture=spawn(process.env.LEAFLOOM_TEST_PYTHON || path.join(root,'.venv/bin/python'),
  ['-u','tests/database_ui_server.py',process.env.LEAFLOOM_TEST_STATIC || 'vault_rag/static'],{cwd:root,env:{...process.env,
   LEAFLOOM_DATABASE_TEST_PORT:String(port), LEAFLOOM_DATABASE_DESIGN:'1',
   LEAFLOOM_DATABASE_ENCRYPTED_PHOTOS:'1', LEAFLOOM_DATABASE_ENCRYPTED_CAPTIONS:'1'},stdio:['ignore','pipe','inherit']});
 const ended=once(fixture,'exit');
 const lines=readline.createInterface(fixture.stdout);
 let browser;
 try {
  const [line]=await Promise.race([once(lines,'line'),ended.then(()=>{throw Error('Fixture exited');})]);
  const info=JSON.parse(line);
  for(let retry=0; retry<50; retry++){
   try{if((await fetch(info.ui+'/healthz')).ok)break;}catch{}
   await new Promise(resolve=>setTimeout(resolve,100));
  }
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH ||
   '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page=await browser.newPage({baseURL:info.ui,viewport:{width:1180,height:640}});
  page.setDefaultTimeout(12000);
  await page.goto('/?note=Showcase.base');
  await page.locator('.db-view-tabs button').filter({hasText:'Gallery'}).click();
  await checkGalleryScroll(page);
  await page.setViewportSize({width:1500,height:1100});
  const card=page.locator('[data-db-record="Showcase/Record 0000.md"].db-card');
  const cover=card.locator('.db-protected-photo');
  await card.getByText('Encrypted caption',{exact:true}).waitFor();
  await cover.getByRole('button',{name:'Unlock photos'}).click();
  await page.getByLabel('Photo passphrase').fill('synthetic photo passphrase');
  await page.locator('dialog').getByRole('button',{name:'Unlock photos',exact:true}).click();
  await cover.locator('img[src^="blob:"]').evaluate(image=>image.decode());
  await card.getByRole('button',{name:'Fixture photo caption',exact:true}).click();
  await page.locator('.db-record-modal .db-protected-record-cover img[src^="blob:"]').evaluate(image=>image.decode());
  const caption=page.locator('.db-record-modal .db-protected-caption');
  await caption.getByRole('button',{name:'Edit caption'}).click();
  await caption.getByLabel('Photo caption').fill('Edited encrypted caption');
  const [saved]=await Promise.all([page.waitForResponse(response=>response.url().includes('/api/photo-vault/caption?')&&response.request().method()==='POST'),
   caption.locator('form button').first().click()]);
  assert.equal(saved.status(),200,await saved.text());
  await caption.filter({hasText:'Edited encrypted caption'}).waitFor();
  await page.locator('.db-record-modal>header button').click();
  await page.getByRole('button',{name:'Lock photos',exact:true}).click();
  await cover.getByRole('button',{name:'Unlock photos'}).waitFor();
  assert.equal(await cover.locator('img').count(),0);
  await card.getByText('Encrypted caption',{exact:true}).waitFor();
  assert.equal(await card.getByText('Edited encrypted caption',{exact:true}).count(),0);

  await page.getByRole('button',{name:'Encrypt database',exact:true}).click();
  const conversion=page.getByRole('dialog',{name:'Encrypt database'});
  await conversion.getByLabel('Existing gallery passphrase').fill('synthetic photo passphrase');
  const password='synthetic database passphrase';
  await conversion.getByLabel('Database passphrase',{exact:true}).fill(password);
  await conversion.getByLabel('Confirm passphrase').fill(password);
  const [converted]=await Promise.all([
   page.waitForResponse(response=>response.url().includes('/api/database-security/convert')),
   conversion.getByRole('button',{name:'Encrypt and lock'}).click(),
  ]);
  assert.equal(converted.status(),200);
  const locked=page.getByRole('region',{name:'Database locked'});
  await locked.waitFor();
  assert.equal(await page.locator('.db-view-tabs').count(),0);
  assert.equal(await page.getByText('Edited encrypted caption',{exact:true}).count(),0);
  await locked.getByLabel('Database passphrase').fill(password);
  await locked.getByRole('button',{name:'Unlock database',exact:true}).click();
  await page.setViewportSize({width:1180,height:640});
  await page.locator('.db-view-tabs button').filter({hasText:'Gallery'}).click();
  await checkGalleryScroll(page);
  await page.setViewportSize({width:1500,height:1100});
  const secured=page.locator('[data-db-record="Showcase/Record 0000.md"].db-card');
  const securedImage=secured.locator('img[src^="blob:"]');
  await securedImage.evaluate(image=>image.decode());
  await secured.getByRole('button',{name:'Edited encrypted caption',exact:true}).click();
  const detail=page.getByRole('dialog',{name:'Edited encrypted caption'});
  const markdown=detail.getByLabel('Record contents (Markdown)');
  await markdown.waitFor();
  await markdown.fill((await markdown.inputValue())+'\n\nNew private body.');
  const [bodySaved]=await Promise.all([
   page.waitForResponse(response=>new URL(response.url()).pathname==='/api/database-security/record'&&response.request().method()==='POST'),
   detail.getByRole('button',{name:'Save',exact:true}).click(),
  ]);
  assert.equal(bodySaved.status(),200);
  await detail.locator('header button').first().click();
  await page.getByRole('button',{name:'Lock database',exact:true}).click();
  await locked.waitFor();
  assert.equal(await page.locator('.db-view-tabs').count(),0);
  assert.equal(await page.locator('img[src^="blob:"]').count(),0);

  await page.goto('/?note=Studio%20notes.base');
  await page.locator('.db-view-tabs button').filter({hasText:'Gallery'}).click();
  const ordinary=page.locator('[data-db-record="Studio notes/01.md"].db-card');
  await ordinary.locator('img').evaluate(image=>image.decode());

  await page.getByRole('button',{name:'New database',exact:true}).click();
  const create=page.getByRole('dialog',{name:'New database'});
  await create.getByLabel('Database name').fill('Private fixture');
  await create.getByLabel('Encrypt database').check();
  await create.getByLabel('Database passphrase',{exact:true}).fill(password);
  await create.getByLabel('Confirm passphrase').fill(password);
  await create.getByRole('button',{name:'New database',exact:true}).click();
  await create.waitFor({state:'hidden'});
  const privateDatabase=page.locator('[data-database$="Private fixture.base"]');
  await privateDatabase.getByRole('button',{name:'Add record',exact:true}).first().click();
  const record=page.getByRole('dialog',{name:'Add record'});
  await record.getByLabel('Title').fill('New private record');
  await record.getByRole('button',{name:'Save',exact:true}).click();
  await privateDatabase.getByText('New private record',{exact:true}).first().waitFor();
  console.log('Legacy gallery conversion, database unlock/lock, private record editing and encrypted creation passed');
 } finally{
  await browser?.close();
  fixture.kill('SIGTERM');
  await ended;
 }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
