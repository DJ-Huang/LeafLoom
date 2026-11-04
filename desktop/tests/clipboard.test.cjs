'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {registerClipboardIpc} = require('../clipboard.cjs');
class ClipboardItem {constructor(data){this.data=data;}}

test('clipboard writes require authorization and reject invalid or oversized text', async () => {
  let handler; const writes = [], trusted = {};
  registerClipboardIpc({handle(name, fn) {if(name==='leafloom:clipboard-write-text')handler = fn;}},
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
  registerClipboardIpc({handle(name, fn) {if(name==='leafloom:clipboard-write-text')handler = fn;}}, () => {},
    {writeText: () => new Promise(resolve => {finish = resolve;})});
  let done = false; const pending = handler({}, 'context').then(() => {done = true;});
  await Promise.resolve(); assert.equal(done, false);
  finish(); await pending; assert.equal(done, true);
  registerClipboardIpc({handle(name, fn) {if(name==='leafloom:clipboard-write-text')handler = fn;}}, () => {},
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
    await api.writeClipboardImage(new Uint8Array([1,2,3]));
    assert.equal(calls[1][0], 'leafloom:clipboard-write-image');
    assert.deepEqual(Array.from(calls[1][1]), [1,2,3]);
    assert.equal(api.readClipboardImage, undefined);
    assert.equal(api.readClipboardText, undefined);
  }
});

test('image writes authorize first and validate PNG bounds before native decoding', async () => {
  const handlers = {}, writes = []; let decodes = 0;
  const image = {isEmpty: () => false, getSize: () => ({width:1,height:1})};
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6HgAAAAAASUVORK5CYII=', 'base64');
  registerClipboardIpc({handle(name, handler) {handlers[name]=handler;}}, event => {if (!event.trusted) throw Error('Untrusted');},
    {write: async items => {assert.equal(items.length,1);assert.ok(items[0] instanceof ClipboardItem);const blob=items[0].data['image/png'];assert.equal(blob.type,'image/png');assert.deepEqual(Buffer.from(await blob.arrayBuffer()),png);writes.push(items[0]);}}, {createFromBuffer: bytes => {decodes++;assert.deepEqual(bytes,png);return image;}}, ClipboardItem);
  const write = handlers['leafloom:clipboard-write-image'];
  await assert.rejects(write({},png), /Untrusted/);
  for (const invalid of [null, {}, png.buffer, new Uint8Array(32*1024*1024+1), new Uint8Array(34)]) await assert.rejects(write({trusted:true},invalid), /Invalid/);
  const huge=Buffer.from(png);huge.writeUInt32BE(100000,16);huge.writeUInt32BE(100000,20);
  await assert.rejects(write({trusted:true},huge), /Invalid.*size/);
  assert.equal(decodes,0);assert.deepEqual(writes,[]);
  // Bytes outside a supplied typed-array slice must never be decoded/copied.
  const padded=Buffer.concat([Buffer.alloc(9),png,Buffer.alloc(7)]);
  await write({trusted:true},padded.subarray(9,9+png.length));
  assert.equal(decodes,1);assert.equal(writes.length,1);
});

test('invalid decoded images and native clipboard failures do not report success', async () => {
  let write;const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6HgAAAAAASUVORK5CYII=','base64');
  for(const image of [{isEmpty:()=>true},{isEmpty:()=>false,getSize:()=>({width:2,height:1})}]){
    registerClipboardIpc({handle(name,handler){if(name.endsWith('write-image'))write=handler;}},()=>{},
      {write:()=>assert.fail('invalid image must not reach the clipboard')},{createFromBuffer:()=>image},ClipboardItem);
    await assert.rejects(write({},png),/Invalid/);
  }
  registerClipboardIpc({handle(name,handler){if(name.endsWith('write-image'))write=handler;}},()=>{},
    {write:async()=>{throw Error('Native failure');}},{createFromBuffer:()=>({isEmpty:()=>false,getSize:()=>({width:1,height:1})})},ClipboardItem);
  await assert.rejects(write({},png),/Native failure/);
});

// Match Electron 44's async Clipboard API; a legacy writeImage-only test double
// would conceal an API mismatch with the pinned desktop runtime.
test('image IPC awaits the asynchronous PNG clipboard commit', async () => {
  let handler, finish;const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6HgAAAAAASUVORK5CYII=','base64');
  registerClipboardIpc({handle(name,fn){if(name.endsWith('write-image'))handler=fn;}},()=>{},
    {write:()=>new Promise(resolve=>{finish=resolve;})},
    {createFromBuffer:()=>({isEmpty:()=>false,getSize:()=>({width:1,height:1})})},ClipboardItem);
  let done=false;const pending=handler({},png).then(()=>{done=true;});
  await Promise.resolve();assert.equal(done,false);finish();await pending;assert.equal(done,true);
});
