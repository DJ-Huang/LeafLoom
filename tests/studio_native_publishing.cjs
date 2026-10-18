'use strict';
// Real Electron integration (not part of Node mock unit suite):
// npm rebuild electron --prefix desktop
// macOS: LEAFLOOM_TEST_PYTHON=python desktop/node_modules/.bin/electron tests/studio_native_publishing.cjs
// Linux (with a configured Chromium sandbox): prefix that command with xvfb-run -a
// Uses only synthetic fixture data and a private Python stdio bridge. No servers,
// browser downloads, OS credentials, real projects or external network required.
const {app, BrowserWindow, session} = require('electron');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {createInterface} = require('node:readline');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const {prepareManifest, renderManifest} = require('../desktop/design-publisher.cjs');
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'leafloom-native-electron-'));
app.setPath('userData', profile);
app.disableHardwareAcceleration();
// Each page owns a short-lived offscreen window. Keep the test alive between
// pages, including after destroying the final window before backend verification.
app.on('window-all-closed', () => {});
let bridge;
const pending = [];
async function main() {
  await app.whenReady();
  bridge = spawn(process.env.LEAFLOOM_TEST_PYTHON || 'python', [path.join(__dirname, 'studio_native_publishing_bridge.py')], {stdio: ['pipe', 'pipe', 'inherit']});
  const lines = createInterface({input: bridge.stdout});
  lines.on('line', line => {
    const entry = pending.shift();
    if (!entry) throw Error('Unexpected fixture reply');
    const reply = JSON.parse(line);
    if (reply.ok) entry.resolve(reply.result); else entry.reject(Error(reply.error));
  });
  bridge.on('error', error => {for (const entry of pending.splice(0)) entry.reject(error);});
  bridge.on('exit', code => {for (const entry of pending.splice(0)) entry.reject(Error('Fixture bridge exited: ' + code));});
  const request = data => new Promise((resolve, reject) => {pending.push({resolve, reject}); bridge.stdin.write(JSON.stringify(data) + '\n');});
  for (const format of ['png', 'pdf']) {
    const manifest = await request({command: 'start', format, scale: format === 'png' ? 2 : 1});
    let completed = 0;
    await renderManifest({BrowserWindow, session}, prepareManifest(manifest, manifest.job_id), async (itemId, output, error, preflight) => {
      assert.equal(error, undefined, `Native ${format} item ${itemId}: ${error}`);
      assert.ok(output.length > 100);
      assert.ok(preflight && Array.isArray(preflight.issues));
      await request({command: 'result', job_id: manifest.job_id, body: {item_id: itemId, data_base64: output.toString('base64'), preflight}});
      completed++;
    });
    assert.equal(completed, 15);
    const verification = await request({command: 'verify', job_id: manifest.job_id});
    assert.equal(verification.pages, 15);
    console.log(`Real Electron ${format}: 15 pages and backend artifact validated`);
  }
  const blocked = await request({command: 'start', format: 'png', blocked: true});
  blocked.runtime_css += '\nbody { background-image: url("http://127.0.0.1:9/private"); }';
  let blockedCount = 0;
  await renderManifest({BrowserWindow, session}, prepareManifest(blocked, blocked.job_id), async (itemId, output, error) => {
    assert.equal(output, null); assert.match(error, /blocked|policy/i); blockedCount++;
    await request({command: 'result', job_id: blocked.job_id, body: {item_id: itemId, error}});
  });
  assert.equal(blockedCount, 1);
  console.log('Real Electron external-resource denial validated');
}
const deadline = setTimeout(() => {console.error('Native publishing smoke timed out'); bridge?.kill(); app.exit(1);}, 180000);
main().then(() => {clearTimeout(deadline); bridge.stdin.end(); app.exit(0);}).catch(error => {console.error(error); clearTimeout(deadline); bridge?.kill(); app.exit(1);});
app.on('will-quit', () => {try {fs.rmSync(profile, {recursive: true, force: true});} catch {}});
