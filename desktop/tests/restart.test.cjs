'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const {createRequire} = require('node:module');
const {EventEmitter} = require('node:events');
const {restartApplication, restartArguments, consumeDevelopmentRestart} = require('../restart.cjs');
const {strings} = require('../strings.cjs');

function fixture(work) {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'leafloom-restart-'));
  return Promise.resolve().then(() => work(home)).finally(() => fs.rmSync(home, {recursive: true, force: true}));
}
const settle = async () => {for (let i = 0; i < 8; i++) await Promise.resolve();};

// Run the actual desktop quit/restart handlers with native-window and process
// boundaries replaced. Nothing opens Electron or touches the user's app data.
function desktop(home, {managed = false, blocked = false, choice = 0} = {}) {
  const calls = [], app = new EventEmitter();
  app.isPackaged = !managed;
  app.setPath = app.setName = app.setAppUserModelId = () => {};
  app.getLocale = () => 'zh-CN'; app.getVersion = () => '0.1.3';
  app.requestSingleInstanceLock = () => true;
  app.whenReady = () => new Promise(() => {});
  app.relaunch = options => calls.push(['relaunch', options]);
  app.quit = () => {
    const event = {preventDefault() {this.prevented = true;}};
    app.emit('before-quit', event);
    if (!event.prevented) {app.emit('will-quit');calls.push(['quit']);}
  };
  class Window extends EventEmitter {
    constructor() {
      super();this.blocked = blocked;this.destroyed = false;
      this.webContents = new EventEmitter();
      this.webContents.executeJavaScript = async () => {calls.push(['prepare-drafts']);};
      this.webContents.setWindowOpenHandler = () => {};
    }
    isDestroyed() {return this.destroyed;}
    isMaximized() {return false;}
    isMinimized() {return false;}
    getBounds() {return {width: 1000, height: 700};}
    show() {} focus() {} hide() {}
    loadFile() {return Promise.resolve();}
    close() {
      const closing = {preventDefault() {this.prevented = true;}};this.emit('close', closing);
      if (closing.prevented) return;
      if (this.blocked) {
        const unloading = {preventDefault() {this.allowed = true;}};
        this.webContents.emit('will-prevent-unload', unloading);
        if (!unloading.allowed) return;
      }
      this.destroyed = true;this.emit('closed');
    }
  }
  let release;
  const stopped = new Promise(resolve => {release = resolve;});
  const backend = {stop: async () => {calls.push(['stop-service']);await stopped;}};
  const dialog = {showMessageBox: async (_, options) => {calls.push(['unsaved-dialog', options]);return {response: choice};}, showErrorBox: () => {}};
  const localRequire = createRequire(path.resolve(__dirname, '../main.cjs'));
  const load = name => {
    if (name === 'electron') return {app, BrowserWindow: Window, dialog, screen: {getAllDisplays: () => []}};
    if (name === './state-home.cjs') return {resolveStateHome: () => ({home, registrationHome: home})};
    if (name === './tunnel.cjs') return {TunnelSettings: class {}};
    if (name === './updater.cjs') return {Updater: class {constructor() {this.state = {phase: 'idle'};}}};
    return localRequire(name);
  };
  const marker = path.join(home, 'restart-request');
  const env = managed ? {LEAFLOOM_DEV_RESTART_FILE: marker} : {};
  const sandbox = {require: load, __dirname: path.resolve(__dirname, '..'), process: {argv: ['/fixture/LeafLoom', '--background'], env, platform: 'darwin', resourcesPath: home}, console, setTimeout, clearTimeout, setInterval, clearInterval};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../main.cjs'), 'utf8') + '\nglobalThis.hooks = {createWindow, requestRestart, requestQuit, setBackend(value) {backend = value;}, getWindow() {return window;}};', sandbox);
  sandbox.hooks.setBackend(backend);sandbox.hooks.createWindow();
  return {...sandbox.hooks, calls, marker, release};
}

test('restart waits for draft preparation and service shutdown; repeated requests do not duplicate launches', () => fixture(async home => {
  const running = desktop(home);
  await running.requestRestart();await running.requestRestart();await settle();
  assert.deepEqual(running.calls.map(call => call[0]), ['prepare-drafts', 'stop-service']);
  running.release();await settle();
  assert.deepEqual(running.calls.map(call => call[0]), ['prepare-drafts', 'stop-service', 'relaunch', 'quit']);
  assert.deepEqual(running.calls[2][1].args, ['--home', home]);
}));

test('cancelling the unsaved prompt cancels restart and a later ordinary quit stays ordinary', () => fixture(async home => {
  const running = desktop(home, {managed: true, blocked: true});
  await running.requestRestart();await settle();
  assert.equal(running.getWindow().isDestroyed(), false);
  assert.equal(fs.existsSync(running.marker), false);
  assert.ok(running.calls.find(call => call[0] === 'unsaved-dialog')[1].detail.includes('重启'));
  assert.equal(running.calls.some(call => call[0] === 'stop-service'), false);
  running.getWindow().blocked = false;
  await running.requestQuit();running.release();await settle();
  assert.equal(fs.existsSync(running.marker), false);
  assert.equal(running.calls.some(call => call[0] === 'relaunch'), false);
  assert.equal(running.calls.at(-1)[0], 'quit');
}));

test('confirming the unsaved prompt requests one supervised development restart only after shutdown', () => fixture(async home => {
  const running = desktop(home, {managed: true, blocked: true, choice: 1});
  await running.requestRestart();await settle();
  assert.equal(fs.existsSync(running.marker), false);
  assert.equal(running.calls.filter(call => call[0] === 'prepare-drafts').length, 1);
  running.release();await settle();
  assert.equal(consumeDevelopmentRestart(running.marker, 0), true);
  assert.equal(consumeDevelopmentRestart(running.marker, 0), false);
  assert.equal(running.calls.some(call => call[0] === 'relaunch'), false);
}));

test('development supervisor consumes failed exits without restarting, and installer ignores development markers', () => fixture(home => {
  const file = path.join(home, 'request');
  fs.writeFileSync(file, 'restart');
  assert.equal(consumeDevelopmentRestart(file, 1), false);assert.equal(fs.existsSync(file), false);
  assert.equal(consumeDevelopmentRestart(file, 0), false);
  const launches = [];
  restartApplication({isPackaged: true, relaunch: value => launches.push(value)}, home, {argv: ['LeafLoom', '--background'], env: {LEAFLOOM_DEV_RESTART_FILE: file}});
  assert.deepEqual(launches, [{args: ['--home', home]}]);assert.equal(fs.existsSync(file), false);
}));

test('restart keeps source entry and custom arguments, opens in foreground and uses the same home', () => {
  assert.deepEqual(restartArguments(['electron', '/source/desktop', '--background', '--home', '/old', '--quit', '--inspect=9229'], '/fixture home'), ['/source/desktop', '--inspect=9229', '--home', '/fixture home']);
  for (const language of ['en', 'zh-CN', 'ja']) for (const key of ['restart', 'restartDetail', 'restartFailed']) assert.ok(strings[language][key]);
});
