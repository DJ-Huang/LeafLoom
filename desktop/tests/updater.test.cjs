'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const {Updater, newer} = require('../updater.cjs');
const payload = Buffer.from('fictional installer; never execute');
const digest = crypto.createHash('sha256').update(payload).digest('hex');
function release(platform = 'windows-x64-setup.exe') {
  const name = 'LeafLoom-0.2.0-' + platform;
  return {tag_name: 'v0.2.0', assets: [{name, size: payload.length, digest: 'sha256:' + digest, browser_download_url: 'https://github.com/DJ-Huang/LeafLoom/releases/download/v0.2.0/' + name}]};
}
async function fixture(t, metadata = release(), content = payload, options = {}) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'leafloom-update-test-'));
  t.after(() => fs.rm(directory, {recursive: true, force: true}));
  const calls = [];
  const updater = new Updater({current: '0.1.1', platform: 'win32', arch: 'x64', directory, fetcher: async url => {
    calls.push(url);
    return url.endsWith('/latest') ? Response.json(metadata) : new Response(content);
  }, ...options});
  return {updater, calls, directory};
}
test('versions compare numerically and reject prerelease or malformed tags', () => {
  assert.equal(newer('v0.10.0', '0.9.9'), true);
  assert.equal(newer('0.1.1', '0.1.1'), false);
  assert.equal(newer('0.1.0', '0.1.1'), false);
  for (const tag of ['v0.2.0-beta', '../../x', '0.02.0']) assert.throws(() => newer(tag, '0.1.1'));
});
test('a verified download reports progress, avoids duplicates and rechecks before installation', async t => {
  const {updater} = await fixture(t);
  assert.equal((await updater.check()).phase, 'available');
  assert.equal(updater.download(), true);
  assert.equal(updater.download(), false);
  assert.equal(await updater.transfer(), true);
  assert.equal(updater.status().received, payload.length);
  assert.equal(updater.status().phase, 'ready');
  const file = await updater.installer();
  assert.deepEqual(await fs.readFile(file), payload);
  assert.equal(updater.status().phase, 'installing');
});
test('equal and older releases do not offer installation', async t => {
  for (const current of ['0.2.0', '1.0.0']) {
    const {updater} = await fixture(t, release(), payload, {current});
    assert.equal((await updater.check()).phase, 'current');
    assert.throws(() => updater.download());
  }
});
test('macOS selects the matching DMG and development mode cannot install', async t => {
  const {updater} = await fixture(t, release('macos-arm64.dmg'), payload, {platform: 'darwin', arch: 'arm64'});
  assert.equal((await updater.check()).phase, 'available');
  const {updater: dev} = await fixture(t, release(), payload, {packaged: false});
  assert.equal((await dev.check()).phase, 'development');
  assert.throws(() => dev.download());
});
test('missing platform assets, untrusted URLs and prereleases fail closed', async t => {
  for (const mutate of [r => {r.assets = [];}, r => {r.assets[0].browser_download_url = 'https://example.com/installer.exe';}, r => {r.prerelease = true;}, r => {r.draft = true;}, r => {r.assets[0].digest = '';}, r => {r.assets[0].size = -1;}]) {
    const metadata = release(); mutate(metadata);
    const {updater} = await fixture(t, metadata);
    assert.equal((await updater.check()).phase, 'error');
    assert.throws(() => updater.download());
  }
});
test('checksum manifests support older release metadata', async t => {
  const metadata = release(); metadata.assets[0].digest = null;
  metadata.assets.push({name: 'SHA256SUMS.txt', size: 200, browser_download_url: 'https://github.com/DJ-Huang/LeafLoom/releases/download/v0.2.0/SHA256SUMS.txt'});
  const {updater} = await fixture(t, metadata, digest + '  ' + metadata.assets[0].name + '\n');
  assert.equal((await updater.check()).phase, 'available');
});
test('truncated, oversized and corrupt payloads are removed and can be retried', async t => {
  for (const content of [payload.subarray(1), Buffer.concat([payload, payload]), Buffer.alloc(payload.length)]) {
    const {updater, directory} = await fixture(t, release(), content);
    await updater.check(); updater.download();
    assert.equal(await updater.transfer(), false);
    assert.equal(updater.status().error, 'update.error.checksum');
    assert.deepEqual(await fs.readdir(directory), []);
    await assert.rejects(updater.installer());
    assert.equal(updater.download(), true);
  }
});
test('tampering after download prevents launching the installer', async t => {
  const {updater} = await fixture(t);
  await updater.check(); updater.download(); await updater.transfer();
  await fs.writeFile(updater.file, 'modified');
  await assert.rejects(updater.installer(), /update.error.checksum/);
  assert.equal(updater.status().phase, 'error');
});
test('network and rate failures leave a retryable status', async t => {
  for (const status of [403, 429, 500]) {
    const {updater} = await fixture(t, release(), payload, {fetcher: async () => new Response('', {status})});
    assert.equal((await updater.check()).error, status === 500 ? 'update.error.network' : 'update.error.rate');
    updater.fetcher = async () => Response.json(release());
    assert.equal((await updater.check()).phase, 'available');
  }
});
test('checking while downloading preserves the selected release and progress', async t => {
  const {updater, calls} = await fixture(t);
  await updater.check(); updater.download();
  assert.equal((await updater.check()).phase, 'downloading');
  assert.equal(calls.length, 1);
});
