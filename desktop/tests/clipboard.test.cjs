'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {registerClipboardIpc} = require('../clipboard.cjs');

test('clipboard writes require authorization and reject invalid or oversized text', async () => {
  let handler; const writes = [], trusted = {};
  registerClipboardIpc({handle(name, fn) {assert.equal(name, 'leafloom:clipboard-write-text'); handler = fn;}},
    event => {if (event !== trusted) throw new Error('Untrusted desktop caller');},
    {writeText: text => writes.push(text)});
  await assert.rejects(handler({}, 'private'), /Untrusted/);
  for (const value of [null, {}, 42, 'x'.repeat(1024 * 1024 + 1)]) await assert.rejects(handler(trusted, value), /Invalid clipboard text/);
  assert.deepEqual(writes, []);
  const text = '{\n  "path": "项目/Design/studio/project.json"\n}';
  await handler(trusted, text);
  assert.deepEqual(writes, [text]);
});

test('native write completion and errors propagate to the renderer', async () => {
  let handler, finish;
  registerClipboardIpc({handle(_name, fn) {handler = fn;}}, () => {},
    {writeText: () => new Promise(resolve => {finish = resolve;})});
  let done = false; const pending = handler({}, 'context').then(() => {done = true;});
  await Promise.resolve(); assert.equal(done, false);
  finish(); await pending; assert.equal(done, true);
  registerClipboardIpc({handle(_name, fn) {handler = fn;}}, () => {},
    {writeText: async () => {throw new Error('Native write failed');}});
  await assert.rejects(handler({}, 'context'), /Native write failed/);
});

test('preload exposes text copying only in the main frame and provides no clipboard reader', async () => {
  const source = fs.readFileSync(path.join(__dirname, '../preload.cjs'), 'utf8');
  for (const isMainFrame of [false, true]) {
    let api; const calls = [];
    vm.runInNewContext(source, {process: {isMainFrame}, require: () => ({
      contextBridge: {exposeInMainWorld(name, value) {assert.equal(name, 'leafloomDesktop'); api = value;}},
      ipcRenderer: {invoke: async (...args) => {calls.push(args);}}
    })});
    if (!isMainFrame) {assert.equal(api, undefined); continue;}
    await api.writeClipboardText('location');
    assert.deepEqual(calls, [['leafloom:clipboard-write-text', 'location']]);
    assert.equal(api.readClipboardText, undefined);
  }
});
