// Run with Electron. Uses a disposable home, native safeStorage and real HTTP.
'use strict';
const {app, safeStorage} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const assert = require('node:assert/strict');
const {Backend} = require('../backend.cjs');
const {TunnelSettings} = require('../tunnel.cjs');
const home = process.env.LEAFLOOM_TEST_HOME || fs.mkdtempSync(path.join(os.tmpdir(), 'LeafLoom-native-tunnel-'));
app.setPath('userData', path.join(home, 'electron'));
let backend;
function waitEvent(name, predicate = () => true) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {backend.off(name, receive); reject(new Error('Timed out: ' + name));}, 30000);
    function receive(value) {if (predicate(value)) {clearTimeout(timer); backend.off(name, receive); resolve(value);}}
    backend.on(name, receive);
  });
}
app.whenReady().then(async () => {
  assert.ok(process.env.LEAFLOOM_TEST_PYTHON, 'Set LEAFLOOM_TEST_PYTHON to the private bundled interpreter');
  assert.ok(safeStorage.isEncryptionAvailable(), 'System credential encryption unavailable');
  const settings = new TunnelSettings(home, safeStorage);
  const key = 'sk-test-leafloom-native-only';
  settings.save({tunnelId: 'tunnel_' + 'a'.repeat(32), appKey: key, enabled: true});
  const restored = new TunnelSettings(home, safeStorage);
  assert.equal(restored.command('/missing/runtime').apiKey, key);
  assert.ok(!fs.readFileSync(settings.file, 'utf8').includes(key));
  assert.ok(!JSON.stringify(restored.status()).includes(key));
  const listener = net.createServer(); await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
  const port = listener.address().port; await new Promise(resolve => listener.close(resolve));
  const vault = path.join(home, 'vault'); fs.mkdirSync(vault);
  fs.writeFileSync(path.join(home, 'config.json'), JSON.stringify({root: vault, port, include_roots: [], exclude_roots: [], rules_roots: [], wiki_roots: [], estimation_roots: [], write_targets: {notes: 'Notes'}, homepage: '', templates: 'Templates', daily_folder: 'Daily'}));
  backend = new Backend({python: process.env.LEAFLOOM_TEST_PYTHON, home});
  backend.on('failure', () => {});
  const readyEvent = waitEvent('ready'); backend.start(); const ready = await readyEvent;
  const committed = waitEvent('committed'); backend.send('commit'); await committed;
  const call = async (method, params) => {
    const result = await fetch(ready.url + '/mcp', {method: 'POST', headers: {'Content-Type': 'application/json', Accept: 'application/json, text/event-stream'}, body: JSON.stringify({jsonrpc: '2.0', id: 1, method, params})});
    assert.equal(result.status, 200); return result.json();
  };
  assert.ok((await call('initialize', {protocolVersion: '2025-06-18', capabilities: {}, clientInfo: {name: 'native-smoke', version: '1'}})).result);
  assert.ok((await call('tools/list', {})).result.tools.some(tool => tool.name === 'vault_index_status'));
  const result = (await call('tools/call', {name: 'vault_index_status', arguments: {}})).result;
  assert.ok(!result.isError);
  assert.equal(JSON.parse(result.content[0].text).ok, true);
  // Missing binary is detected before any network request or credential use.
  const failed = waitEvent('tunnel-state', value => value.error === 'tunnel.error.binary');
  backend.send('tunnel-configure', restored.command(path.join(home, 'missing-runtime')));
  await failed;
  assert.equal((await fetch(ready.url + '/healthz')).status, 200);
  settings.disable(); backend.send('tunnel-configure', {enabled: false});
  await backend.stop();
  assert.equal(backend.child, null);
  settings.clear(); assert.equal(settings.status().keySaved, false);
  console.log('Native credential encryption, private control pipe, unauthenticated MCP, failure isolation and quit cleanup passed.');
}).then(() => {
  app.exit(0); // The launcher removes the fixture after Electron releases locks.
}).catch(async () => {
  // Do not print thrown objects from a credential-handling test.
  await backend?.stop(); console.error('Native Tunnel smoke failed; no credentials exported.'); app.exit(1);
});
