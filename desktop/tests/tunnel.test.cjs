'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {TunnelSettings, tunnelBinary} = require('../tunnel.cjs');

const id = 'tunnel_0123456789abcdef0123456789abcdef';
const key = 'test-runtime-key-private';
function fixture() {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'LeafLoom-tunnel-'));
  const storage = {isEncryptionAvailable: () => true,
    encryptString: value => {assert.equal(value, key); return Buffer.from('system-encrypted-value');},
    decryptString: value => {assert.equal(value.toString(), 'system-encrypted-value'); return key;}};
  return {home, storage, settings: new TunnelSettings(home, storage)};
}
test('only encrypted credentials persist; status is redacted and restart restores settings', t => {
  const {home, storage, settings} = fixture(); t.after(() => fs.rmSync(home, {recursive: true, force: true}));
  settings.save({tunnelId: id, appKey: key, enabled: true});
  assert.equal(settings.status().keySaved, true);
  assert.ok(!JSON.stringify(settings.status()).includes(key));
  assert.equal(settings.status().encryptedKey, undefined);
  assert.ok(!fs.readFileSync(settings.file, 'utf8').includes(key));
  const restored = new TunnelSettings(home, storage);
  assert.equal(restored.status().state, 'waiting');
  assert.equal(restored.command('/private/runtime').apiKey, key);
  restored.save({tunnelId: id, enabled: true, appKey: ''});
  assert.equal(restored.command('/private/runtime').apiKey, key);
  restored.disable(); assert.deepEqual(restored.command('/private/runtime'), {enabled: false});
  restored.clear(); assert.equal(restored.status().keySaved, false);
  assert.equal(restored.status().state, 'unconfigured');
});
test('unavailable system encryption fails without storing plaintext or replacing the saved key', t => {
  const {home, storage, settings} = fixture(); t.after(() => fs.rmSync(home, {recursive: true, force: true}));
  storage.isEncryptionAvailable = () => false;
  assert.throws(() => settings.save({tunnelId: id, appKey: key, enabled: true}), /tunnel.error.encryption/);
  assert.equal(fs.existsSync(settings.file), false);
  storage.isEncryptionAvailable = () => true;
  settings.save({tunnelId: id, appKey: key, enabled: true});
  storage.decryptString = () => {throw new Error(key);};
  assert.deepEqual(settings.command('/private/runtime'), {enabled: false});
  assert.equal(settings.status().error, 'tunnel.error.encryption');
  assert.ok(!JSON.stringify(settings.status()).includes(key));
});
test('invalid input and corrupt disk state have fixed errors', t => {
  const {home, storage, settings} = fixture(); t.after(() => fs.rmSync(home, {recursive: true, force: true}));
  assert.throws(() => settings.save({tunnelId: 'anything', appKey: key, enabled: true}), /tunnel.error.config/);
  assert.throws(() => settings.save({tunnelId: id, appKey: key + '\n', enabled: true}), /tunnel.error.key/);
  fs.writeFileSync(settings.file, 'null');
  assert.equal(new TunnelSettings(home, storage).status().error, 'tunnel.error.storage');
});

test('Dev and the installed app select the same registered Tunnel executable', t => {
  const {home} = fixture(); t.after(() => fs.rmSync(home, {recursive: true, force: true}));
  for (const platform of ['win32', 'darwin']) {
    const root = path.join(home, platform);
    const executable = platform === 'win32' ? path.join(root, 'LeafLoom.exe') : path.join(root, 'LeafLoom.app', 'Contents', 'MacOS', 'LeafLoom');
    const resourcesPath = platform === 'win32' ? path.join(root, 'resources') : path.join(root, 'LeafLoom.app', 'Contents', 'Resources');
    const binary = path.join(resourcesPath, 'tunnel', platform === 'win32' ? 'tunnel-client-runtime.exe' : 'tunnel-client-runtime');
    fs.mkdirSync(path.dirname(binary), {recursive: true}); fs.writeFileSync(binary, 'fixture');
    fs.writeFileSync(path.join(home, 'desktop-install.json'), JSON.stringify({schema: 1, executable}));
    const installed = tunnelBinary({packaged: true, resourcesPath, home, platform});
    const dev = tunnelBinary({packaged: false, appPath: path.join(home, 'checkout'), home, platform});
    assert.equal(dev, installed); assert.equal(dev, binary);
  }
});

test('source-only Dev and a removed installation use the verified checkout payload', t => {
  const {home} = fixture(); t.after(() => fs.rmSync(home, {recursive: true, force: true}));
  const appPath = path.join(home, 'checkout');
  const expected = path.join(appPath, 'resources', 'tunnel', 'windows-x64', 'tunnel-client-runtime.exe');
  assert.equal(tunnelBinary({packaged: false, home, appPath, platform: 'win32'}), expected);
  fs.writeFileSync(path.join(home, 'desktop-install.json'), JSON.stringify({schema: 1, executable: path.join(home, 'removed', 'LeafLoom.exe')}));
  assert.equal(tunnelBinary({packaged: false, home, appPath, platform: 'win32'}), expected);
});
