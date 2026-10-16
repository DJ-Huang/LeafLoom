// Actual desktop settings, isolated from the user's vault, keys and login items.
'use strict';
const {_electron} = require('../desktop/node_modules/playwright-core');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const assert = require('node:assert/strict');

async function main() {
  assert(process.env.LEAFLOOM_DESKTOP_EXECUTABLE, 'Set LEAFLOOM_DESKTOP_EXECUTABLE to a Tunnel-enabled desktop build');
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'LeafLoom-settings-capture-')));
  const home = path.join(root, 'state'), vault = path.join(root, 'Demo Knowledge');
  fs.mkdirSync(home); fs.mkdirSync(vault);
  fs.writeFileSync(path.join(vault, 'Welcome.md'), '# Welcome\n\nYour local knowledge workspace.\n');
  fs.writeFileSync(path.join(home, 'desktop-preferences.json'), JSON.stringify({openAtLogin: false}));
  const listener = net.createServer();
  await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
  const port = listener.address().port;
  await new Promise(resolve => listener.close(resolve));
  fs.writeFileSync(path.join(home, 'config.json'), JSON.stringify({root: vault, port, include_roots: [], exclude_roots: [], rules_roots: [], wiki_roots: [], estimation_roots: [], write_targets: {notes: 'Notes'}, homepage: 'Welcome.md', templates: 'Templates', daily_folder: 'Daily'}));
  const env = {...process.env, VAULT_RAG_HOME: home, LEAFLOOM_REGISTRATION_HOME: path.join(root, 'registration')};
  delete env.ELECTRON_RUN_AS_NODE;
  let application;
  try {
    for (const locale of ['en', 'zh-CN', 'ja']) {
      console.log('Capturing ' + locale);
      const catalog = require('../vault_rag/locales/' + locale + '.json');
      const text = key => catalog[key] || key;
      fs.writeFileSync(path.join(home, 'preferences.json'), JSON.stringify({locale, onboarding: {}}));
      application = await _electron.launch({executablePath: path.resolve(process.env.LEAFLOOM_DESKTOP_EXECUTABLE), args: ['--background'], env, timeout: 60000});
      await application.evaluate(({BrowserWindow}) => {
        const window = BrowserWindow.getAllWindows()[0];
        window.setContentSize(1440, 1100);
        window.showInactive();
      });
      const page = await application.firstWindow();
      await page.waitForURL(url => /^app\.[a-f0-9]{32}\.localhost$/.test(url.hostname) && url.port === String(port) && url.pathname === '/', {timeout: 25000});
      await page.waitForFunction(locale => document.documentElement.lang === locale, locale, {polling: 100});
      await page.getByRole('button', {name: text('设置'), exact: true}).click();
      await page.getByRole('button', {name: text('mcp.connectionTitle'), exact: true}).click();
      await page.getByRole('button', {name: text('tunnel.saveConnect'), exact: true}).waitFor();
      // Expand the capture layout so the real first-use guidance is also visible.
      await page.addStyleTag({content: '.modal.settings-modal { height: min(1000px, calc(100dvh - 64px)); }'});
      await page.evaluate(async () => {await document.fonts.ready;});
      const modal = page.locator('.settings-modal');
      const visible = await modal.innerText();
      assert(!visible.includes(root), 'Capture must not include an environment path');
      assert.equal(await page.getByLabel(text('tunnel.key'), {exact: true}).inputValue(), '');
      const status = await page.evaluate(() => window.leafloomDesktop.tunnelStatus());
      assert.equal(status.keySaved, false);
      await page.mouse.move(0, 0);
      const output = path.resolve('assets/screenshots', locale, 'showcase-chatgpt-settings.png');
      const bounds = await modal.boundingBox();
      assert(bounds && bounds.width > 600 && bounds.height > 500, 'Settings panel must be fully laid out');
      // Capture the actual panel without RAF-based element stability checks;
      // background Electron windows pause animation frames on Windows.
      await page.screenshot({path: output, clip: bounds, animations: 'disabled'});
      console.log(locale + ': ' + output);
      await application.close(); application = null;
    }
  } finally {
    await application?.close().catch(() => {});
    // This exact directory was created by this invocation above.
    fs.rmSync(root, {recursive: true, force: true, maxRetries: 3});
  }
}
main().catch(error => {console.error(error); process.exitCode = 1;});
