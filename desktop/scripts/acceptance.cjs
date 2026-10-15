// Actual Electron-window acceptance, using only a disposable vault and state.
'use strict';
const {_electron} = require('playwright-core');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');

async function port() {
  const server = net.createServer(); await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const number = server.address().port; await new Promise(resolve => server.close(resolve)); return number;
}
async function main() {
  const tempRoot = process.platform === 'win32' ? path.join(process.env.LOCALAPPDATA, 'Temp') : os.tmpdir();
  const root = fs.realpathSync(fs.mkdtempSync(path.join(tempRoot, 'LeafLoom desktop 中文 ')));
  const state = path.join(root, 'state'), vault = path.join(root, 'Knowledge 中文');
  const out = path.resolve(__dirname, '../../.cache/desktop-acceptance'); fs.mkdirSync(out, {recursive: true});
  fs.mkdirSync(state); fs.mkdirSync(vault);
  fs.writeFileSync(path.join(vault, 'Welcome.md'), '# Welcome\n\nA local knowledge note. [[Second]]\n');
  fs.writeFileSync(path.join(vault, 'Second.md'), '# Second\n\nBack to [[Welcome]].\n');
  const p = await port();
  fs.writeFileSync(path.join(state, 'config.json'), JSON.stringify({root: vault, include_roots: [], exclude_roots: [], rules_roots: [], wiki_roots: [], estimation_roots: [], write_targets: {notes: 'Notes'}, homepage: 'Welcome.md', templates: 'Templates', daily_folder: 'Daily', port: p}));
  fs.writeFileSync(path.join(state, 'preferences.json'), JSON.stringify({locale: 'en', onboarding: {}}));
  // OS login items are global to the app ID, not VAULT_RAG_HOME. Never toggle
  // the user's real login setting during this disposable window acceptance.
  fs.writeFileSync(path.join(state, 'desktop-preferences.json'), JSON.stringify({openAtLogin: false}));
  const packaged = process.env.LEAFLOOM_DESKTOP_EXECUTABLE;
  const executablePath = packaged ? path.resolve(packaged) : require('electron');
  const env = {...process.env, VAULT_RAG_HOME: state, LEAFLOOM_REGISTRATION_HOME: path.join(root, 'registration')}; delete env.ELECTRON_RUN_AS_NODE;
  // Remove developer runtimes from discovery. The desktop must use its payload.
  env.PATH = process.platform === 'win32' ? [process.env.SystemRoot + '\\System32', process.env.SystemRoot, process.env.SystemRoot + '\\System32\\WindowsPowerShell\\v1.0'].join(';') : '/usr/bin:/bin:/usr/sbin:/sbin';
  const args = packaged ? [] : [path.resolve(__dirname, '..')];
  const errors = [], checks = [];
  let application, appProcess;
  try {
    application = await _electron.launch({executablePath, args, env, timeout: 120000});
    appProcess = application.process();
    const page = await application.firstWindow();
    page.on('pageerror', e => errors.push(e.message));
    await page.waitForURL(url => /^app\.[a-f0-9]{32}\.localhost$/.test(url.hostname) && url.port === String(p) && url.pathname === '/', {timeout: 110000});
    await page.getByRole('button', {name: 'Settings', exact: true}).waitFor({timeout: 60000});
    assert.equal(await application.evaluate(({BrowserWindow}) => {const p=BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences(); return p.nodeIntegration === false && p.contextIsolation === true && p.sandbox === true && p.webSecurity === true;}), true);
    const info = await page.evaluate(() => window.leafloomDesktop.appInfo()); assert.equal(info.version, require('../package.json').version);
    const status = await page.evaluate(async () => (await fetch('/api/status')).json()); assert.equal(status.model.prepared, false); assert.equal(status.model.load_count, 0);
    checks.push('private-runtime-no-model');
    await page.screenshot({path: path.join(out, 'desktop-home.png')});
    await page.locator('.tree-label').filter({hasText: 'Welcome.md'}).click();
    await page.locator('.document-pane,.document-workspace,.reader').first().waitFor({timeout: 15000}).catch(async () => {await page.getByRole('heading', {name: 'Welcome', exact: true}).first().waitFor();});
    const editor=page.locator('.rich-prose').first(); await editor.waitFor();
    await editor.locator('p').first().click();await page.keyboard.press('Home');
    await page.keyboard.insertText('Saved from the desktop editor. ');
    const savedUntil=Date.now()+15000;
    while(!fs.readFileSync(path.join(vault,'Welcome.md'),'utf8').includes('Saved from the desktop editor.')) {
      if(Date.now()>savedUntil)throw new Error('Desktop editor did not save the original file');
      await page.waitForTimeout(100);
    }
    assert.equal(await page.getByRole('button', {name:'View source',exact:true}).count(),1);
    checks.push('editor-saves-original-file');
    await page.screenshot({path: path.join(out, 'desktop-note.png')});
    await page.getByRole('button', {name: 'Knowledge graph', exact: true}).click();
    await page.locator('canvas').first().waitFor({timeout: 20000}).catch(async () => {await page.locator('.graph-page,.graph').first().waitFor();});
    await page.screenshot({path: path.join(out, 'desktop-graph.png')});
    checks.push('note-and-graph');
    await page.getByRole('button', {name: 'Settings', exact: true}).click();
    await page.getByText('Desktop app', {exact: true}).waitFor();
    await page.screenshot({path: path.join(out, 'desktop-settings.png')});
    await application.evaluate(({dialog}, folder) => {dialog.showOpenDialog = async () => ({canceled: false, filePaths: [folder]});}, vault);
    assert.equal((await page.evaluate(() => window.leafloomDesktop.chooseDirectory())).path, vault);
    checks.push('native-directory-bridge');
    // Model the Windows API's argument-sensitive lookup without touching OS
    // login registration. An omitted args lookup incorrectly reports false.
    await application.evaluate(({app}) => {
      let setting = null;
      app.setLoginItemSettings = value => {setting=value;};
      app.getLoginItemSettings = (options={}) => ({openAtLogin: Boolean(setting?.openAtLogin) && JSON.stringify(options.args)===JSON.stringify(setting.args)});
    });
    assert.equal((await page.evaluate(() => window.leafloomDesktop.setOpenAtLogin(true))).openAtLogin, true);
    assert.equal((await page.evaluate(() => window.leafloomDesktop.appInfo())).openAtLogin, true);
    await page.evaluate(() => window.leafloomDesktop.setOpenAtLogin(false));
    checks.push('login-option-roundtrip');
    // A preview's CSP creates an opaque origin. It cannot borrow the parent's
    // native bridge, and preloads never expose a bridge to child frames.
    await page.evaluate(() => {const frame=document.createElement('iframe');frame.id='desktop-test-frame';frame.src='/html-preview/invalid/files/index.html';document.body.append(frame);});
    await page.locator('#desktop-test-frame').waitFor();
    const previewFrame = await (await page.locator('#desktop-test-frame').elementHandle()).contentFrame();
    await previewFrame.waitForLoadState('domcontentloaded');
    assert.equal(await previewFrame.evaluate(() => typeof window.leafloomDesktop), 'undefined');
    assert.equal(await previewFrame.evaluate(() => {try {void parent.leafloomDesktop; return false;} catch {return true;}}), true);
    checks.push('preview-ipc-denied');
    await page.evaluate(() => document.getElementById('desktop-test-frame').remove());
    const manualEnv={...env}; delete manualEnv.VAULT_RAG_HOME;
    const second = spawn(executablePath, args, {env: manualEnv, stdio: 'ignore', windowsHide: true});
    await new Promise((resolve,reject) => {const timer=setTimeout(()=>reject(new Error('Second instance did not exit')),10000);second.once('exit', code=>{clearTimeout(timer);code===0?resolve():reject(new Error('Second instance failed: '+code));});});
    assert.equal((await application.windows()).length, 1); checks.push('single-instance');
    await application.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].close());
    assert.equal(await application.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].isVisible()), false);
    const token = fs.readFileSync(path.join(state, 'auth-token'), 'utf8').trim();
    assert.equal((await fetch('http://127.0.0.1:' + p + '/api/status', {headers:{Authorization:'Bearer '+token}})).status, 200);
    checks.push('close-retains-service');
    await application.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].show());
    // Simulate an unsaved settings/draft guard and choose Return in the real
    // desktop quit flow. The service and window must remain intact.
    await page.evaluate(() => {window.__desktopBlockUnload = event=>{event.preventDefault();event.returnValue='';};window.addEventListener('beforeunload',window.__desktopBlockUnload);});
    await application.evaluate(({dialog}) => {dialog.showMessageBox = async () => ({response:0,checkboxChecked:false});});
    await application.evaluate(({Menu}) => Menu.getApplicationMenu().items[0].submenu.items.find(item=>item.accelerator==='CmdOrCtrl+Q').click());
    await page.waitForTimeout(600);
    assert.equal((await application.windows()).length, 1); checks.push('unsaved-quit-cancel');
    await page.evaluate(() => window.removeEventListener('beforeunload',window.__desktopBlockUnload));
    await page.evaluate(() => {void window.leafloomDesktop.quit();});
    await new Promise((resolve,reject) => {const child=appProcess;if(child.exitCode!==null)return resolve();const timer=setTimeout(()=>reject(new Error('Quit did not stop app')),40000);child.once('exit',()=>{clearTimeout(timer);resolve();});});
    await assert.rejects(() => fetch('http://127.0.0.1:' + p + '/healthz'));
    checks.push('quit-stops-service');
    assert.deepEqual(errors, []);
    const report = {platform: process.platform, packaged: Boolean(packaged), checks, rendererErrors: errors, screenshots: out};
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify(report,null,2)); console.log(JSON.stringify(report));
  } finally {
    if (application && appProcess?.exitCode === null) await application.close();
    // Test-owned temp only. Retain it on failure for logs and draft inspection.
    if (checks.includes('quit-stops-service')) fs.rmSync(root,{recursive:true,force:true});
    else console.error('Acceptance fixture retained:', root);
  }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
