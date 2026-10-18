'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {EventEmitter} = require('node:events');
const {prepareManifest, jobId, renderManifest, ORIGIN, CSP, publishJob} = require('../design-publisher.cjs');
const id = 'a'.repeat(32);
const manifest = () => ({job_id: id, format: 'png', scale: 2, runtime_js: '/* trusted runtime */', runtime_css: '',
  pages: [{id: '1', page_id: 'p', width: 100, height: 200, document: {pages: []}}],
  resources: [{path: 'Design/Assets/图 a.png', mime: 'image/png', data_base64: 'eA=='}]});
test('desktop publishing only takes an opaque job ID, never arbitrary URLs or paths', () => {
  assert.equal(jobId(id), id);
  for (const value of ['http://127.0.0.1/admin', '../private', {url: 'https://evil.test'}, '', 'x'.repeat(81)]) assert.throws(() => jobId(value));
});
test('immutable manifests enforce dimensions, budget, IDs and resource paths', () => {
  assert.ok(prepareManifest(manifest(), id).resources.has(ORIGIN + '/Design/Assets/%E5%9B%BE%20a.png'));
  for (const mutate of [m => {m.job_id = 'other';}, m => {m.scale = 5;}, m => {m.pages[0].width = 9000;}, m => {m.pages[0].width = 8192; m.pages[0].height = 8192;}, m => {m.pages.push(m.pages[0]);}, m => {m.resources[0].data_base64 = '!';}]) {
    const m = manifest(); mutate(m); assert.throws(() => prepareManifest(m, id));
  }
  for (const path of ['../secret', '/api/status', '//example.test/a', 'a/../b', 'a\\b', 'a?b', 'a#b']) {
    const m = manifest(); m.resources[0].path = path; assert.throws(() => prepareManifest(m, id));
  }
  assert.match(CSP, /script-src 'none'/); assert.match(CSP, /connect-src 'none'/);
});
function fakeElectron({fail = false, blocked = false} = {}) {
  const isolated = new EventEmitter(), state = {windows: [], captures: [], pdf: [], scripts: []};
  Object.assign(isolated, {setPermissionRequestHandler: fn => {if (fn) state.permission = fn;}, setPermissionCheckHandler: fn => {if (fn) state.check = fn;},
    webRequest: {onBeforeRequest: fn => {if (fn) state.network = fn; else state.networkReleased = true;}},
    protocol: {handle: (scheme, fn) => {state.protocol = fn;}, unhandle: () => {state.unhandled = true;}},
    clearStorageData: async () => {state.cleared = true;}, closeAllConnections: async () => {state.closed = true;}});
  class Window {
    constructor(options) {
      state.windows.push(options); this.dead = false;
      this.webContents = Object.assign(new EventEmitter(), {
        setWindowOpenHandler: fn => {state.popup = fn;}, setZoomFactor: value => {state.zoom = value;},
        insertCSS: async () => {}, executeJavaScript: async code => {state.scripts.push(code);},
        capturePage: async rect => {state.captures.push(rect); return {getSize: () => ({width: rect.width, height: rect.height}), toPNG: () => Buffer.from('PNG')};},
        printToPDF: async options => {state.pdf.push(options); return Buffer.from('%PDF-');},
      });
    }
    async loadURL(url) {state.url = url; if (blocked) state.network({url: 'file:///private'}, () => {}); if (fail) throw Error('Load failed');}
    destroy() {this.dead = true; state.destroyed = true;}
    isDestroyed() {return this.dead;}
  }
  return {state, BrowserWindow: Window, session: {fromPartition: (partition, options) => {assert.ok(!partition.startsWith('persist:')); assert.equal(options.cache, false); return isolated;}}};
}
test('native PNG rendering is isolated, exact scaled size, and denies external requests and permissions', async () => {
  const electron = fakeElectron(), results = [];
  await renderManifest(electron, prepareManifest(manifest(), id), async (...args) => results.push(args));
  const state = electron.state, prefs = state.windows[0].webPreferences;
  assert.equal(prefs.sandbox, true); assert.equal(prefs.contextIsolation, true); assert.equal(prefs.nodeIntegration, false); assert.equal(prefs.preload, undefined); assert.equal(prefs.offscreen, true);
  assert.equal(state.check(), false); let permission; state.permission(null, 'media', value => {permission = value;}); assert.equal(permission, false);
  assert.deepEqual(state.popup(), {action: 'deny'});
  for (const url of ['http://127.0.0.1/api/status', 'file:///private', 'https://evil.test/', ORIGIN + '/unknown']) state.network({url}, result => assert.equal(result.cancel, true));
  state.network({url: state.url}, result => assert.equal(result.cancel, false));
  const response = state.protocol({url: state.url, method: 'GET'}); assert.equal(response.headers.get('content-security-policy'), CSP);
  assert.deepEqual(state.captures[0], {x: 0, y: 0, width: 200, height: 400});
  assert.ok(state.scripts.some(code => code.includes('readyForStatic({timeoutMs:15000,maxResources:512})')));
  assert.equal(state.zoom, 2); assert.equal(results[0][0], '1'); assert.equal(results[0][1].toString(), 'PNG');
  assert.ok(state.destroyed && state.unhandled && state.cleared && state.closed);
});
test('native PDF uses selected CSS page size and reports page failure without abandoning remaining items', async () => {
  const m = manifest(); m.format = 'pdf';
  const electron = fakeElectron(); await renderManifest(electron, prepareManifest(m, id), async () => {});
  assert.deepEqual(electron.state.pdf[0].pageSize, {width: 100 / 96, height: 200 / 96});
  assert.equal(electron.state.zoom, 1);
  for (const option of [{fail: true}, {blocked: true}]) {
    const failure = fakeElectron(option), results = [];
    await renderManifest(failure, prepareManifest(manifest(), id), async (...args) => results.push(args));
    assert.equal(results[0][1], null); assert.ok(results[0][2]); assert.ok(failure.state.destroyed && failure.state.cleared);
  }
});
test('job requests stay on authenticated configured loopback endpoints', async () => {
  const electron = fakeElectron(), requests = [];
  const result = await publishJob(electron, 'http://127.0.0.1:18080/', 'secret', id, async (url, options) => {
    requests.push({url, options}); return Response.json(url.endsWith('native-manifest') ? manifest() : {status: 'succeeded'});
  });
  assert.equal(result.status, 'succeeded'); assert.equal(requests.length, 2);
  for (const request of requests) {assert.ok(request.url.startsWith('http://127.0.0.1:18080/api/design/publish/' + id)); assert.equal(request.options.redirect, 'error'); assert.equal(request.options.headers.Authorization, 'Bearer secret');}
  assert.deepEqual(JSON.parse(requests[1].options.body), {item_id: '1', data_base64: Buffer.from('PNG').toString('base64')});
  await assert.rejects(publishJob(electron, 'https://evil.test/', 'secret', id), /unavailable/);
});

test('an uncertain result upload is not retried as a page failure', async () => {
  const electron = fakeElectron(); let submits = 0;
  await assert.rejects(renderManifest(electron, prepareManifest(manifest(), id), async () => {submits++; throw Error('Connection lost');}), /Connection lost/);
  assert.equal(submits, 1); assert.ok(electron.state.networkReleased && electron.state.destroyed);
});

test('fatal native setup reports pending failure instead of leaving a running job', async () => {
  const requests = [];
  await assert.rejects(publishJob(fakeElectron(), 'http://127.0.0.1:18080/', 'secret', id, async (url, options) => {
    requests.push({url, options}); return Response.json(url.endsWith('native-manifest') ? {...manifest(), scale: 99} : {status: 'failed'});
  }), /Invalid publishing runtime/);
  assert.equal(requests.length, 2); assert.ok(requests[1].url.endsWith('/native-failure'));
  assert.match(JSON.parse(requests[1].options.body).error, /Invalid publishing runtime/);
});
