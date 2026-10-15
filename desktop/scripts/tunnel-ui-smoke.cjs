// Packaged app workflow in an isolated, hidden window. No screenshots or remote calls.
'use strict';
const {_electron} = require('playwright-core');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const assert = require('node:assert/strict');

async function main() {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'LeafLoom-tunnel-ui-')));
  const home = path.join(root, 'state'), vault = path.join(root, 'vault');
  fs.mkdirSync(home); fs.mkdirSync(vault);
  fs.writeFileSync(path.join(vault, 'Welcome.md'), '# Welcome\n');
  const listener = net.createServer(); await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
  const port = listener.address().port; await new Promise(resolve => listener.close(resolve));
  fs.writeFileSync(path.join(home, 'config.json'), JSON.stringify({root: vault, port, include_roots: [], exclude_roots: [], rules_roots: [], wiki_roots: [], estimation_roots: [], write_targets: {notes: 'Notes'}, homepage: 'Welcome.md', templates: 'Templates', daily_folder: 'Daily'}));
  fs.writeFileSync(path.join(home, 'preferences.json'), JSON.stringify({locale: 'en', guide: {dismissed: true}}));
  // OS login settings are global; never migrate them from a test home.
  fs.writeFileSync(path.join(home, 'desktop-preferences.json'), JSON.stringify({openAtLogin: false}));
  const env = {...process.env, VAULT_RAG_HOME: home, LEAFLOOM_REGISTRATION_HOME: path.join(root, 'registration')};
  delete env.ELECTRON_RUN_AS_NODE;
  const executablePath = path.resolve(process.env.LEAFLOOM_DESKTOP_EXECUTABLE);
  const key = 'sk-test-local-ui-never-sent';
  let application, stage = 'launch';
  const errors = [];
  async function launch() {
    application = await _electron.launch({executablePath, args: ['--background'], env, timeout: 60000});
    const page = await application.firstWindow();
    page.on('pageerror', () => errors.push('renderer-error'));
    await page.waitForURL(`http://127.0.0.1:${port}/`, {timeout: 20000});
    await page.getByRole('button', {name: 'Settings', exact: true}).click();
    await page.getByRole('button', {name: 'ChatGPT connection', exact: true}).click();
    return page;
  }
  try {
    let page = await launch();
    stage = 'save-disabled-credentials';
    await page.getByRole('textbox', {name: 'Tunnel ID', exact: true}).fill('tunnel_' + 'a'.repeat(32));
    await page.getByLabel('App Key (Tunnel runtime key)', {exact: true}).fill(key);
    await page.getByRole('checkbox', {name: 'Enable and connect when the app starts', exact: true}).uncheck();
    await page.getByRole('button', {name: 'Save connection settings', exact: true}).click();
    await page.waitForFunction(async () => (await window.leafloomDesktop.tunnelStatus()).keySaved, null, {polling: 100, timeout: 15000});
    await page.waitForFunction(() => document.querySelector('input[type="password"]')?.value === '', null, {polling: 100, timeout: 15000});
    assert.equal(await page.getByLabel('App Key (Tunnel runtime key)', {exact: true}).inputValue(), '');
    assert.ok(!fs.readFileSync(path.join(home, 'desktop-tunnel.json'), 'utf8').includes(key));
    assert.equal((await page.evaluate(() => window.leafloomDesktop.tunnelStatus())).enabled, false);
    await application.close(); application = null;
    stage = 'restart-and-clear';
    page = await launch();
    const restored = await page.evaluate(() => window.leafloomDesktop.tunnelStatus());
    assert.equal(restored.keySaved, true); assert.equal(restored.enabled, false);
    assert.ok(!JSON.stringify(restored).includes(key));
    await page.getByRole('button', {name: 'Clear settings', exact: true}).click();
    await page.waitForFunction(async () => !(await window.leafloomDesktop.tunnelStatus()).keySaved, null, {polling: 100, timeout: 15000});
    stage = 'tray-and-quit';
    await application.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].close());
    assert.equal(await application.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].isVisible()), false);
    assert.equal((await fetch(`http://127.0.0.1:${port}/healthz`)).status, 200);
    await application.close(); application = null;
    assert.deepEqual(errors, []);
    const checks = ['packaged-ui', 'encrypted-save', 'redacted-status', 'restart-restores-disabled-credentials', 'clear-settings', 'close-keeps-service', 'quit'];
    const report = path.resolve(__dirname, '../../.cache/tunnel-ui-smoke.json');
    fs.writeFileSync(report, JSON.stringify({passed: true, checks}, null, 2));
    console.log('Packaged Tunnel UI checks passed: ' + checks.join(', '));
  } catch (error) {
    const pageText = application ? await application.windows()[0]?.locator('body').innerText().catch(() => '') : '';
    const backendLog = path.join(home, 'logs', 'desktop-backend.log');
    const tail = fs.existsSync(backendLog) ? fs.readFileSync(backendLog, 'utf8').slice(-2200) : '';
    const diagnostic = [String(error.message || error), pageText, tail].join('\n').replaceAll(key, '[redacted]');
    fs.writeFileSync(path.resolve(__dirname, '../../.cache/tunnel-ui-failure.log'), diagnostic);
    throw new Error('Packaged Tunnel UI check failed at: ' + stage + ': ' + diagnostic);
  } finally {
    await application?.close().catch(() => {});
    fs.rmSync(root, {recursive: true, force: true, maxRetries: 3});
  }
}
main().catch(error => {console.error(error.message); process.exitCode = 1;});
