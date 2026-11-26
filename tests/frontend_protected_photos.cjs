'use strict';
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const net = require('node:net');
const path = require('node:path');
const readline = require('node:readline');
const {chromium} = require('../desktop/node_modules/playwright-core');

const root = path.resolve(__dirname, '..');

async function main() {
 const port = await new Promise(resolve => {
  const server=net.createServer();
  server.listen(0,'127.0.0.1',()=>{const port=server.address().port;server.close(()=>resolve(port));});
 });
 const fixture=spawn(process.env.LEAFLOOM_TEST_PYTHON || path.join(root,'.venv/bin/python'),
  ['-u','tests/database_ui_server.py','vault_rag/static'],{cwd:root,env:{...process.env,
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
  const page=await browser.newPage({baseURL:info.ui,viewport:{width:1500,height:1100}});
  page.setDefaultTimeout(12000);
  await page.goto('/?note=Showcase.base');
  await page.locator('.db-view-tabs button').filter({hasText:'Gallery'}).click();
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

  await page.goto('/?note=Studio%20notes.base');
  await page.locator('.db-view-tabs button').filter({hasText:'Gallery'}).click();
  await page.getByRole('button',{name:'Enable photo encryption'}).click();
  const setup=page.getByRole('dialog',{name:'Enable photo encryption'});
  await setup.getByRole('button',{name:'Unlock photos'}).click();
  const unlock=page.getByRole('dialog',{name:'Unlock photos'});
  await unlock.getByLabel('Photo passphrase').fill('synthetic photo passphrase');
  await unlock.getByRole('button',{name:'Unlock photos'}).click();
  await setup.getByRole('button',{name:'Enable photo encryption'}).click();
  await setup.waitFor({state:'hidden'});
  const ordinary=page.locator('[data-db-record="Studio notes/01.md"].db-card');
  await ordinary.locator('img').evaluate(image=>image.decode());
  await ordinary.getByRole('button',{name:'01 — Quiet architecture',exact:true}).click();
  const detail=page.locator('.db-record-modal');
  const newCaption=detail.locator('.db-protected-caption');
  await newCaption.getByRole('button',{name:'Edit caption'}).click();
  await newCaption.getByLabel('Photo caption').fill('Protected studio caption');
  const [savedStudio]=await Promise.all([page.waitForResponse(response=>response.url().includes('/api/photo-vault/caption?')&&response.request().method()==='POST'),
   newCaption.getByRole('button',{name:'Save',exact:true}).click()]);
  assert.equal(savedStudio.status(),200,await savedStudio.text());
  await newCaption.filter({hasText:'Protected studio caption'}).waitFor();
  await detail.locator('header button').first().click();
  await ordinary.getByRole('button',{name:'01 — Quiet architecture',exact:true}).waitFor();
  await ordinary.getByText('Protected studio caption',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Lock photos',exact:true}).click();
  await ordinary.getByText('Encrypted caption',{exact:true}).waitFor();
  assert.equal(await ordinary.getByText('Protected studio caption',{exact:true}).count(),0);
  console.log('Legacy gallery and generic photo encryption setup, caption editing and locking passed');
 } finally{
  await browser?.close();
  fixture.kill('SIGTERM');
  await ended;
 }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
