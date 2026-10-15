'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {EventEmitter, once} = require('node:events');
const {PassThrough} = require('node:stream');
const policy = require('../policy.cjs');
const {Backend} = require('../backend.cjs');

test('only the configured main application origin is privileged', () => {
  assert.ok(policy.localUrl('http://127.0.0.1:18080/'));
  for (const value of ['https://example.com/', 'http://localhost:18080/', 'http://127.0.0.1:18080/html-preview/x', 'http://user@127.0.0.1:18080/']) assert.equal(policy.localUrl(value), false);
  assert.ok(policy.trustedPage('http://127.0.0.1:18080/#note', 'http://127.0.0.1:18080'));
  for (const value of ['http://127.0.0.1:18081/', 'http://127.0.0.1:18080/html-preview/x', 'file:///index.html', 'https://evil.example/']) assert.equal(policy.trustedPage(value, 'http://127.0.0.1:18080'), false);
});
test('external links never invoke arbitrary handlers or loopback services', () => {
  assert.equal(policy.externalUrl('https://example.com/notes'), 'https://example.com/notes');
  for (const value of ['javascript:alert(1)', 'file:///C:/Windows/system.ini', 'data:text/html,x', 'cmd:run', 'http://localhost:18080/', 'http://2130706433/', 'http://[::1]/', 'https://user:pass@example.com/']) assert.throws(() => policy.externalUrl(value));
});
test('website origins are stable loopback siblings with no workspace privilege', () => {
  const install = 'a'.repeat(32), project = 'b'.repeat(32);
  const ui = `http://app.${install}.localhost:18080/`;
  const site = `http://p-${project}.${install}.localhost:18080/index.html`;
  assert.equal(policy.workspaceOrigin(ui, 'http://127.0.0.1:18080/'), new URL(ui).origin);
  assert.ok(policy.projectUrl(site, new URL(ui).origin));
  assert.equal(policy.trustedPage(site, new URL(ui).origin), false);
  for (const url of [site.replace(':18080', ':18081'), site.replace(install, 'c'.repeat(32)), ui]) assert.equal(policy.projectUrl(url, new URL(ui).origin), false);
  for (const url of [site, ui.replace('http:', 'https:'), ui.replace('.localhost', '.localhost.evil.example'), ui + 'other']) assert.throws(() => policy.workspaceOrigin(url, 'http://127.0.0.1:18080/'));
});
test('file reveal boundary is directory-aware and rejects parent/sibling paths', () => {
  const root = path.resolve('fixture', 'vault');
  assert.ok(policy.inside(root, path.join(root, 'a.md')));
  assert.equal(policy.inside(root, root + '-other/a.md'), false);
  assert.equal(policy.inside(root, path.resolve(root, '..', 'secret.txt')), false);
});
test('offscreen window positions are discarded while usable size is retained', () => {
  assert.deepEqual(policy.validBounds({width: 1400, height: 900, x: -9000, y: -9000}, [{workArea: {x: 0, y: 0, width: 1920, height: 1080}}]), {width: 1400, height: 900});
});
test('backend receives isolated paths and shuts down through its private pipe', async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'LeafLoom-node-'));
  const child = new EventEmitter(); child.stdin = new PassThrough(); child.stdout = new PassThrough();
  child.kill = () => {child.emit('close', 0, null);};
  let args, options, input = '';
  child.stdin.on('data', data => {input += data;});
  child.stdin.on('finish', () => setImmediate(() => child.emit('close', 0, null)));
  const backend = new Backend({python: '/private/python', home, spawnProcess: (_, a, o) => {args = a; options = o; return child;}});
  try {
    backend.start();
    assert.ok(args.includes('-I')); assert.equal(options.cwd, home); assert.equal(options.windowsHide, true);
    assert.equal(options.env.VAULT_RAG_HOME, home); assert.equal(options.env.PYTHONPATH, undefined);
    const ready = once(backend, 'ready'); child.stdout.write('{"type":"ready","url":"http://127.0.0.1:18080/"}\n');
    assert.equal((await ready)[0].url, 'http://127.0.0.1:18080/');
    await backend.stop(); assert.match(input, /"type":"shutdown"/); assert.equal(backend.child, null);
  } finally {fs.rmSync(home, {recursive: true, force: true});}
});
test('a failed spawn closes cleanly and can be retried', async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'LeafLoom-node-'));
  const child = new EventEmitter(); child.stdin = new PassThrough(); child.stdout = new PassThrough();
  child.kill = () => child.emit('close', -2, null);
  const backend = new Backend({python: '/missing/python', home, spawnProcess: () => child});
  backend.on('failure', () => {});
  try {
    backend.start(); child.emit('error', new Error('ENOENT')); child.emit('close', -2, null);
    assert.equal(backend.child, null); await backend.stop();
  } finally {fs.rmSync(home, {recursive: true, force: true});}
});
