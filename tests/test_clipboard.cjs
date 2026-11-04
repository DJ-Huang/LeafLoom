'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const ts = require('../web/node_modules/typescript');
const source = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../web/src/clipboard.ts'), 'utf8'),
  {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText;

function fixture({desktop, web = async () => {}, legacy = true} = {}) {
  const state = {fields: [], writes: [], focus: [], ranges: []}, savedRange = {};
  const selection = {rangeCount: 1, getRangeAt: () => ({cloneRange: () => savedRange}),
    removeAllRanges() {state.ranges = [];}, addRange(range) {state.ranges.push(range);}};
  const previous = {isConnected: true, focus() {state.focus.push('previous');}};
  const document = {activeElement: previous, getSelection: () => selection,
    createElement: () => ({style: {}, focus() {state.focus.push('field');}, select() {},
      remove() {state.fields.splice(state.fields.indexOf(this), 1);}}),
    body: {appendChild(field) {state.fields.push(field);}},
    execCommand(command) {assert.equal(command, 'copy'); if (legacy) state.writes.push(state.fields[0].value); return legacy;}};
  const exports = {};
  vm.runInNewContext(source, {exports, window: {leafloomDesktop: desktop}, navigator: {clipboard: {writeText: web}}, document});
  return {...state, state, savedRange, copy: exports.writeClipboardText};
}

test('desktop copying succeeds while web clipboard permission is denied', async () => {
  const writes = [];
  const f = fixture({desktop: {writeClipboardText: async text => {writes.push(text);}},
    web: async () => {throw new Error('Web clipboard denied');}});
  const text = '{\n  "path": "/fictional/项目/Design/studio/project.json"\n}';
  await f.copy(text); assert.deepEqual(writes, [text]); assert.deepEqual(f.state.focus, []);
});

test('a desktop with the old preload copies synchronously and restores focus and selection', async () => {
  let webCalls = 0;
  const f = fixture({desktop: {}, web: async () => {webCalls++; throw new Error('Denied');}});
  const pending = f.copy('控件路径');
  assert.deepEqual(f.state.writes, ['控件路径']);
  await pending; assert.equal(webCalls, 0); assert.deepEqual(f.state.fields, []);
  assert.deepEqual(f.state.focus, ['field', 'previous']); assert.deepEqual(f.state.ranges, [f.savedRange]);
});

test('browser copies use the web API and fall back when permission is denied', async () => {
  const writes = [], f = fixture({web: async text => {writes.push(text);}});
  await f.copy('web location'); assert.deepEqual(writes, ['web location']); assert.deepEqual(f.state.focus, []);
  const denied = fixture({web: async () => {throw new Error('Denied');}});
  await denied.copy('fallback location'); assert.deepEqual(denied.state.writes, ['fallback location']); assert.deepEqual(denied.state.fields, []);
});

test('failed copying never reports success and still removes temporary fields', async () => {
  const f = fixture({legacy: false, web: async () => {throw new Error('Denied');}});
  await assert.rejects(f.copy('not copied'), /Denied/);
  assert.deepEqual(f.state.writes, []); assert.deepEqual(f.state.fields, []);
  const native = fixture({desktop: {writeClipboardText: async () => {throw new Error('Native failed');}}});
  await assert.rejects(native.copy('not copied'), /Native failed/); assert.deepEqual(native.state.writes, []);
});
