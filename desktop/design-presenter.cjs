'use strict';
const {randomUUID} = require('node:crypto');
const path = require('node:path');
const policy = require('./policy.cjs');

function audienceDocument(source) {
  const document = structuredClone(source);
  if (!document || document.schemaVersion !== 1 || !Array.isArray(document.pages) || !document.pages.length) throw new Error('Invalid presentation document');
  for (const page of document.pages) {
    if (!page || typeof page.id !== 'string' || !Array.isArray(page.nodes) || page.loaded === false) throw new Error('Presentation needs a complete saved document');
    delete page.presenterNotes;
  }
  return document;
}
function inputCommand(input, size) {
  if (!input || typeof input !== 'object') throw new Error('Invalid presentation input');
  const modifiers = (input.shift ? 8 : 0) | (input.alt ? 1 : 0);
  if (['move', 'down', 'up', 'wheel'].includes(input.kind)) {
    if (![input.x, input.y].every(v => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 1)) throw new Error('Invalid presentation coordinates');
    const value = {x: input.x * size.width, y: input.y * size.height, modifiers};
    if (input.kind === 'wheel') {
      if (![input.dx, input.dy].every(v => typeof v === 'number' && Number.isFinite(v) && Math.abs(v) <= 10000)) throw new Error('Invalid presentation wheel');
      return {method: 'Input.dispatchMouseEvent', params: {...value, type: 'mouseWheel', deltaX: input.dx, deltaY: input.dy}};
    }
    const button = ['left', 'middle', 'right'][input.button ?? 0];
    if (!button) throw new Error('Invalid presentation button');
    return {method: 'Input.dispatchMouseEvent', params: {...value, type: {move: 'mouseMoved', down: 'mousePressed', up: 'mouseReleased'}[input.kind], button: input.kind === 'move' && !input.buttons ? 'none' : button, buttons: input.buttons || 0, clickCount: input.kind === 'move' ? 0 : Math.min(2, Math.max(1, Number(input.clickCount) || 1))}};
  }
  if (input.kind === 'key') {
    if (typeof input.key !== 'string' || input.key.length > 32 || !['down', 'up'].includes(input.phase)) throw new Error('Invalid presentation key');
    const special = {Enter: 13, Tab: 9, Escape: 27, Backspace: 8, Delete: 46, ArrowLeft: 37, ArrowUp: 38, ArrowRight: 39, ArrowDown: 40, Home: 36, End: 35, PageUp: 33, PageDown: 34, ' ': 32};
    if (input.key.length !== 1 && !Object.hasOwn(special, input.key)) throw new Error('Unsupported presentation key');
    return {method: 'Input.dispatchKeyEvent', params: {type: input.phase === 'up' ? 'keyUp' : input.key.length === 1 ? 'keyDown' : 'rawKeyDown', key: input.key, code: typeof input.code === 'string' ? input.code.slice(0, 32) : '', modifiers, windowsVirtualKeyCode: special[input.key] || input.key.toUpperCase().charCodeAt(0), ...(input.phase === 'down' && input.key.length === 1 ? {text: input.key} : {})}};
  }
  throw new Error('Unsupported presentation input');
}

class DesignPresenter {
  constructor({BrowserWindow, screen, owner, origin, emit, log = () => {}}) {
    Object.assign(this, {BrowserWindow, screen, owner, origin, emit, log});
    this.active = null; this.markers = [];
    this.onDisplays = () => {
      this.emit({type: 'displays', displays: this.displays()});
      const a = this.active;
      if (a && (!this.screen.getAllDisplays().some(d => d.id === a.displayId) || a.fullscreen && this.screen.getDisplayMatching(this.owner().getBounds()).id === a.displayId)) this.suspend('display-lost');
    };
    screen.on?.('display-added', this.onDisplays); screen.on?.('display-removed', this.onDisplays); screen.on?.('display-metrics-changed', this.onDisplays);
  }
  displays() {
    const own = this.owner(), current = own && this.screen.getDisplayMatching(own.getBounds()).id;
    return this.screen.getAllDisplays().map(d => ({id: d.id, label: d.label || String(d.id), bounds: d.bounds, workArea: d.workArea, scaleFactor: d.scaleFactor, current: d.id === current}));
  }
  require(id) {
    if (!this.active || this.active.id !== id || this.active.window.isDestroyed()) throw new Error('Presentation session has ended');
    return this.active;
  }
  focusController() {const own = this.owner(); if (own && !own.isDestroyed()) {own.moveTop?.(); own.focus();}}
  async attachInput(a) {
    const channel = a.window.webContents.debugger;
    if (!channel.isAttached()) channel.attach('1.3');
    // Chromium's native controls need page focus for a drag; this emulates that
    // inside the audience only and never activates an OS window.
    await channel.sendCommand('Emulation.setFocusEmulationEnabled', {enabled: true});
  }
  async start(input) {
    if (this.active) throw new Error('A presentation is already running');
    const document = audienceDocument(input.document);
    const pageIds = input.pageIds || document.pages.map(p => p.id);
    if (!Array.isArray(pageIds) || !pageIds.length || new Set(pageIds).size !== pageIds.length || pageIds.some(id => !document.pages.some(p => p.id === id)) || !pageIds.includes(input.pageId)) throw new Error('Invalid presentation page order');
    if (!document.pages.some(p => p.id === input.pageId)) throw new Error('Presentation page does not exist');
    const origin = this.origin(), session = input.session;
    if (!session || typeof session.id !== 'string' || !policy.projectUrl(session.origin + '/Design/studio/runtime.html', origin)) throw new Error('Invalid presentation runtime');
    const display = this.screen.getAllDisplays().find(d => d.id === input.displayId);
    if (!display) throw new Error('Presentation display is unavailable');
    const owner = this.owner(), current = this.screen.getDisplayMatching(owner.getBounds());
    const controller = input.controllerDisplayId == null ? current : this.screen.getAllDisplays().find(d => d.id === input.controllerDisplayId);
    if (!controller || input.controllerDisplayId != null && controller.id === display.id) throw new Error('Invalid controller display');
    if (display.id === controller.id && input.fullscreen !== false) throw new Error('Use window rehearsal on the controller display');
    const window = new this.BrowserWindow({title: 'LeafLoom · ' + document.name, show: false, ...display.workArea, width: input.fullscreen === false ? Math.min(960, display.workArea.width) : display.bounds.width, height: input.fullscreen === false ? Math.min(600, display.workArea.height) : display.bounds.height, backgroundColor: '#111816', autoHideMenuBar: true,
      webPreferences: {preload: path.join(__dirname, 'presenter-output-preload.cjs'), nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true, backgroundThrottling: false, devTools: false}});
    const a = this.active = {id: randomUUID(), window, document, pageId: input.pageId, session, displayId: display.id, fullscreen: input.fullscreen !== false, ready: false, state: {}, activeUntil: Date.now() + 2000, capture: false, pendingFrame: 0, frameSeq: 0, lastCapture: 0, closing: false, suspended: false, controllerBounds: owner.getBounds(), controllerDisplay: current.id};
    a.pageIds = pageIds;
    a.controllerMuted = owner.webContents?.isAudioMuted();
    owner.webContents?.setAudioMuted(true);
    if (controller.id !== current.id) {a.swapped = true; owner.setBounds({...controller.workArea, width: Math.min(owner.getBounds().width, controller.workArea.width), height: Math.min(owner.getBounds().height, controller.workArea.height)});}
    owner.webContents?.setBackgroundThrottling(false);
    const contents = window.webContents, url = origin + '/?view=presenter-output';
    contents.setZoomFactor(1);
    contents.on('page-title-updated', event => event.preventDefault());
    contents.setWindowOpenHandler(() => ({action: 'deny'}));
    contents.on('will-navigate', (event, target) => {if (target !== url) event.preventDefault();});
    contents.on('will-redirect', event => event.preventDefault());
    contents.on('will-attach-webview', event => event.preventDefault());
    contents.on('render-process-gone', () => this.suspend('output-failed'));
    contents.debugger.on('detach', () => {if (this.active === a && !a.closing) this.suspend('input-disconnected');});
    window.on('close', event => {if (!a.closing) {event.preventDefault(); this.suspend('window-closed');}});
    window.on('closed', () => {if (this.active === a) this.stop(a.id);});
    a.timer = setInterval(() => void this.capture(a), 30);
    a.watchdog = setInterval(() => {if (Date.now() - (a.heartbeat || Date.now()) > 6000) this.suspend('controller-disconnected');}, 2000);
    a.heartbeat = Date.now();
    a.startup = setTimeout(() => {if (this.active === a && !a.ready) this.suspend('output-failed');}, 20000);
    try {
      await window.loadURL(url);
      await this.attachInput(a);
    } catch (error) {this.stop(a.id); throw error;}
    return {id: a.id, displayId: a.displayId};
  }
  isOutput(event) {const a = this.active; return !!a && event.sender === a.window.webContents && event.senderFrame === event.sender.mainFrame && event.senderFrame.url === this.origin() + '/?view=presenter-output';}
  outputReady(event) {
    if (!this.isOutput(event)) throw new Error('Untrusted presentation output');
    const a = this.active;
    event.sender.send('leafloom:presentation-output', {type: 'configure', id: a.id, document: a.document, pageId: a.pageId, pageIds: a.pageIds, session: a.session, initialState: {paused: !!a.state.paused, black: !!a.state.black}});
  }
  outputReport(event, message) {
    if (!this.isOutput(event) || !message || message.id !== this.active.id) throw new Error('Untrusted presentation state');
    const a = this.active;
    if (message.type === 'ready') {
      clearTimeout(a.startup);
      a.ready = true;
      if (a.suspended) return;
      const display = this.screen.getAllDisplays().find(d => d.id === a.displayId);
      if (!display) {this.suspend('display-lost'); return;}
      if (a.fullscreen) {a.window.setBounds(display.bounds); a.window.setFullScreen(true);}
      a.window.showInactive(); this.focusController();
    }
    if (message.type === 'error') {this.suspend('output-failed'); this.log(String(message.error || 'Presentation runtime failed')); return;}
    if (message.type === 'state') {
      const state = message.state || {};
      a.state = Object.fromEntries(['pageId', 'stepId', 'stepIndex', 'stepCount', 'contextId', 'contextLabel', 'label', 'parameter', 'playing', 'paused', 'black', 'inputFocused', 'supported'].filter(k => typeof state[k] === 'string' || typeof state[k] === 'number' || typeof state[k] === 'boolean').map(k => [k, typeof state[k] === 'string' ? state[k].slice(0, 2000) : state[k]]));
      if (a.document.pages.some(p => p.id === a.state.pageId)) a.pageId = a.state.pageId;
      this.emit({type: 'state', id: a.id, state: a.state, suspended: a.suspended, reason: a.reason || ''});
    }
  }
  command(id, command) {
    const a = this.require(id);
    if (!command || !['next', 'previous', 'page', 'pause', 'resume', 'black', 'reopen', 'swap'].includes(command.action)) throw new Error('Unsupported presentation command');
    a.heartbeat = Date.now(); a.activeUntil = Date.now() + 2000;
    if (command.action === 'reopen') {
      const reload = ['output-failed', 'input-disconnected'].includes(a.reason);
      const display = this.screen.getAllDisplays().find(d => d.id === command.displayId);
      if (!display) throw new Error('Presentation display is unavailable');
      const current = this.screen.getDisplayMatching(this.owner().getBounds());
      a.displayId = display.id; a.fullscreen = display.id !== current.id; a.suspended = false; a.reason = '';
      a.window.setFullScreen(false); a.window.setBounds(a.fullscreen ? display.bounds : {...display.workArea, width: Math.min(960, display.workArea.width), height: Math.min(600, display.workArea.height)}); if (a.fullscreen) a.window.setFullScreen(true);
      if (!reload) a.window.showInactive(); this.focusController();
      if (reload) {
        a.ready = false;
        void this.attachInput(a).then(() => a.window.loadURL(this.origin() + '/?view=presenter-output')).catch(() => this.suspend('output-failed'));
      }
      this.emit({type: 'state', id, state: a.state, suspended: false});
      return;
    }
    if (command.action === 'swap') {
      const own = this.owner(), from = this.screen.getDisplayMatching(own.getBounds()), target = this.screen.getAllDisplays().find(d => d.id === a.displayId);
      if (!target || target.id === from.id) return;
      a.swapped = true;
      a.window.setFullScreen(false); own.setBounds({...target.workArea, width: Math.min(own.getBounds().width, target.workArea.width), height: Math.min(own.getBounds().height, target.workArea.height)});
      a.displayId = from.id; a.window.setBounds(from.bounds); a.window.setFullScreen(true); this.focusController(); return;
    }
    if (a.suspended) throw new Error('Reopen the audience window before continuing');
    if (command.action === 'page' && !a.pageIds.includes(command.pageId)) throw new Error('Presentation page does not exist');
    a.window.webContents.send('leafloom:presentation-output', {type: 'command', id, command: {action: command.action, ...(command.action === 'page' ? {pageId: command.pageId} : {}), ...(command.action === 'black' ? {enabled: !!command.enabled} : {})}});
    if (command.action === 'pause') a.state.paused = true;
    if (command.action === 'black') {a.state.black = !!command.enabled; if (command.enabled) a.state.paused = true;}
    if (command.action === 'resume' && !a.state.black) a.state.paused = false;
    a.window.webContents.setAudioMuted(!!(a.state.black || a.state.paused));
  }
  async input(id, input) {
    const a = this.require(id);
    if (a.suspended || a.state.black || a.state.paused) return;
    a.activeUntil = Date.now() + 2000;
    const command = inputCommand(input, a.window.getContentBounds());
    const previous = a.inputTail || Promise.resolve();
    const pending = previous.catch(() => {}).then(() => {
      if (this.active === a && !a.suspended) return a.window.webContents.debugger.sendCommand(command.method, command.params);
    });
    a.inputTail = pending;
    await pending;
  }
  ack(id, seq) {const a = this.require(id); if (seq === a.pendingFrame) a.pendingFrame = 0; a.heartbeat = Date.now();}
  heartbeat(id) {this.require(id).heartbeat = Date.now();}
  async capture(a) {
    const owner = this.owner(), now = Date.now();
    if (this.active !== a || !a.ready || a.suspended || a.capture || a.pendingFrame || !owner || owner.isDestroyed() || owner.isMinimized()) return;
    if (now - a.lastCapture < (a.state.playing || now < a.activeUntil ? 1000 / 15 : 1000 / 3)) return;
    a.capture = true; a.lastCapture = now;
    try {
      let image = await a.window.webContents.capturePage();
      if (this.active !== a || a.suspended) return;
      const size = image.getSize(), scale = Math.min(1, 1280 / Math.max(size.width, size.height));
      if (scale < 1) image = image.resize({width: Math.round(size.width * scale), height: Math.round(size.height * scale)});
      a.pendingFrame = ++a.frameSeq;
      this.emit({type: 'frame', id: a.id, seq: a.pendingFrame, width: image.getSize().width, height: image.getSize().height, jpeg: image.toJPEG(78)});
    } catch (error) {if (this.active === a) {this.log(error); this.suspend('capture-failed');}} finally {a.capture = false;}
  }
  suspend(reason) {
    const a = this.active; if (!a || a.closing) return;
    if (a.suspended && a.reason === reason) return;
    a.suspended = true; a.reason = reason; a.pendingFrame = 0;
    a.state = {...a.state, black: true, paused: true};
    a.window.webContents.setAudioMuted(true);
    a.window.webContents.send('leafloom:presentation-output', {type: 'command', id: a.id, command: {action: 'black', enabled: true}});
    a.window.hide(); this.focusController();
    this.emit({type: 'state', id: a.id, state: {...a.state, black: true, paused: true}, suspended: true, reason});
  }
  identify() {
    this.clearMarkers();
    for (const [index, d] of this.screen.getAllDisplays().entries()) {
      const marker = new this.BrowserWindow({x: d.workArea.x + 32, y: d.workArea.y + 32, width: 320, height: 140, show: false, frame: false, focusable: false, alwaysOnTop: true, webPreferences: {nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true}});
      marker.setMenu(null);
      void marker.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent('<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><style>body{background:#244f3d;color:white;font:48px system-ui;text-align:center}</style><body>' + (index + 1) + ' · ' + d.bounds.width + ' × ' + d.bounds.height));
      marker.once('ready-to-show', () => marker.showInactive()); this.markers.push(marker);
    }
    this.markerTimer = setTimeout(() => this.clearMarkers(), 2500);
  }
  clearMarkers() {clearTimeout(this.markerTimer); for (const w of this.markers) if (!w.isDestroyed()) w.destroy(); this.markers = [];}
  stop(id) {
    const a = this.active; if (!a || id && id !== a.id) return;
    this.active = null; a.closing = true; clearInterval(a.timer); clearInterval(a.watchdog); clearTimeout(a.startup);
    if (!a.window.isDestroyed()) {a.window.webContents.setAudioMuted(true); if (a.window.webContents.debugger.isAttached()) a.window.webContents.debugger.detach(); a.window.destroy();}
    const owner = this.owner();
    if (owner && !owner.isDestroyed()) {
      owner.webContents?.setBackgroundThrottling(true);
      owner.webContents?.setAudioMuted(!!a.controllerMuted);
      if (a.swapped) {
        const b = a.controllerBounds, displays = this.screen.getAllDisplays();
        const visible = displays.some(({workArea: d}) => b.x + 100 > d.x && b.y + 100 > d.y && b.x < d.x + d.width && b.y < d.y + d.height);
        const fallback = displays[0]?.workArea;
        if (visible) owner.setBounds(b);
        else if (fallback) owner.setBounds({...fallback, width: Math.min(b.width, fallback.width), height: Math.min(b.height, fallback.height)});
      }
    }
    this.emit({type: 'ended', id: a.id});
  }
  dispose() {this.stop(); this.clearMarkers(); for (const name of ['display-added', 'display-removed', 'display-metrics-changed']) this.screen.removeListener?.(name, this.onDisplays);}
}
module.exports = {DesignPresenter, audienceDocument, inputCommand};
