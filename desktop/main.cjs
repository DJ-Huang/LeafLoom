'use strict';
const {app, BrowserWindow, Tray, Menu, dialog, ipcMain, shell, nativeImage, screen, session, safeStorage} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {pathToFileURL} = require('node:url');
const {Backend} = require('./backend.cjs');
const {TunnelSettings} = require('./tunnel.cjs');
const policy = require('./policy.cjs');
const {strings, resolve} = require('./strings.cjs');

function readJson(file) {try {return JSON.parse(fs.readFileSync(file, 'utf8'));} catch {return null;}}
const defaultHome = process.platform === 'win32'
  ? path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'), 'VaultRag')
  : path.join(os.homedir(), 'Library', 'Application Support', 'VaultRag');
const registrationHome = process.env.LEAFLOOM_REGISTRATION_HOME || defaultHome;
const registered = readJson(path.join(registrationHome, 'desktop-current-home.json'));
const savedHome = registered?.schema === 1 && typeof registered.home === 'string' && path.isAbsolute(registered.home) && fs.existsSync(path.join(registered.home, 'desktop-install.json')) ? registered.home : null;
const homeArgument = process.argv.indexOf('--home');
if (homeArgument >= 0 && (!process.argv[homeArgument + 1] || !path.isAbsolute(process.argv[homeArgument + 1]))) throw new Error('--home requires an absolute state directory');
const home = path.resolve((homeArgument >= 0 && process.argv[homeArgument + 1]) || process.env.VAULT_RAG_HOME || savedHome || defaultHome);
fs.mkdirSync(path.join(home, 'desktop-ui'), {recursive: true, mode: 0o700});
app.setPath('userData', path.join(home, 'desktop-ui'));
app.setAppUserModelId('com.djhuang.leafloom');
const statusFile = path.join(__dirname, 'status.html');
const statusUrl = pathToFileURL(statusFile).href;
const control = path.join(home, 'desktop-control');
let window, tray, backend, origin = '', lastOrigin = '', workspaceLoaded = false, quitting = false, quitPending = false, failure = '', retrying = false;
let startupTimer, closeTimer;
const tunnel = new TunnelSettings(home, safeStorage);
let tunnelBackendReady = false;
function configureTunnel() {
  if (!tunnelBackendReady) {
    tunnel.state = {state: tunnel.value.enabled ? 'waiting' : 'disabled', error: ''};
    return tunnel.status();
  }
  const root = app.isPackaged ? path.join(process.resourcesPath, 'tunnel') : path.join(__dirname, 'resources', 'tunnel', process.platform === 'win32' ? 'windows-x64' : 'macos-arm64');
  const binary = path.join(root, process.platform === 'win32' ? 'tunnel-client-runtime.exe' : 'tunnel-client-runtime');
  const command = tunnel.command(binary);
  tunnel.state = {state: command.enabled ? 'starting' : 'disabled', error: ''};
  backend.send('tunnel-configure', command);
  return tunnel.status();
}
let background = process.argv.includes('--background');
const loginOptions = () => process.platform === 'win32' ? {path: process.execPath, args: ['--background', '--home', home]} : {};
const loginSettings = () => app.getLoginItemSettings(loginOptions());
function text() {const choice = readJson(path.join(home, 'preferences.json'))?.locale; return strings[resolve(choice && choice !== 'auto' ? choice : app.getLocale())];}
function atomicJson(file, value) {
  const temp = file + '.' + process.pid + '.tmp';
  try { fs.writeFileSync(temp, JSON.stringify(value, null, 2), {mode: 0o600}); fs.renameSync(temp, file); }
  finally { if (fs.existsSync(temp)) fs.unlinkSync(temp); }
}
function image(name) {
  const root = app.isPackaged ? path.join(process.resourcesPath, 'brand') : path.join(__dirname, '..', 'assets', 'brand');
  return path.join(root, name);
}
function log(error) {
  fs.mkdirSync(path.join(home, 'logs'), {recursive: true});
  fs.appendFileSync(path.join(home, 'logs', 'desktop.log'), new Date().toISOString() + ' ' + String(error?.stack || error) + '\n');
}
function isMain(event, requireApp = true) {
  if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame) throw new Error('Untrusted desktop caller');
  const url = event.senderFrame.url;
  if (!policy.trustedPage(url, origin) && (requireApp || url !== statusUrl)) throw new Error('Desktop access denied');
}
function showWindow() {
  if (quitting) return;
  if (!window || window.isDestroyed()) createWindow();
  window.show(); if (window.isMinimized()) window.restore(); window.focus();
}
function updateMenu() {
  const t = text();
  const openAtLogin = loginSettings().openAtLogin;
  tray.setContextMenu(Menu.buildFromTemplate([
    {label: t.open, click: showWindow},
    {label: t.login, type: 'checkbox', checked: openAtLogin, click: item => {try {setLogin(item.checked);} catch (e) {log(e); dialog.showErrorBox('LeafLoom', e.message); updateMenu();}}},
    {label: t.logs, click: () => void shell.openPath(path.join(home, 'logs'))},
    {label: t.retry, enabled: Boolean(failure) && !retrying, click: () => void startBackend()},
    {type: 'separator'}, {label: t.quit, click: () => void requestQuit()},
  ]));
}
function setLogin(enabled) {
  app.setLoginItemSettings({openAtLogin: enabled, ...loginOptions()});
  if (app.isPackaged && loginSettings().openAtLogin !== enabled) throw new Error('Login setting was not applied; check system settings');
  atomicJson(path.join(home, 'desktop-preferences.json'), {openAtLogin: enabled});
  updateMenu();
}
function createWindow() {
  const saved = readJson(path.join(home, 'desktop-window.json'));
  window = new BrowserWindow({title: 'LeafLoom', ...policy.validBounds(saved, screen.getAllDisplays()), minWidth: 800, minHeight: 600, show: false,
    icon: image('icon-256.png'), webPreferences: {preload: path.join(__dirname, 'preload.cjs'), nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true, spellcheck: false, devTools: !app.isPackaged}});
  const contents = window.webContents;
  let allowDiscard = false;
  const permitted = url => url === statusUrl || policy.trustedPage(url, origin);
  contents.on('will-navigate', (event, url) => {
    if (permitted(url)) return;
    event.preventDefault();
    try {
      const target = new URL(url);
      if (target.origin === origin && target.pathname === '/api/media' && target.searchParams.get('download') === 'true') contents.downloadURL(url);
      else void shell.openExternal(policy.externalUrl(url));
    } catch {}
  });
  contents.on('will-redirect', (event, url) => {if (!permitted(url)) event.preventDefault();});
  contents.setWindowOpenHandler(({url}) => {try {void shell.openExternal(policy.externalUrl(url));} catch {} return {action: 'deny'};});
  contents.on('will-attach-webview', event => event.preventDefault());
  contents.on('render-process-gone', (_, details) => {workspaceLoaded = false; if (!quitting) fail(new Error('Window stopped: ' + details.reason));});
  contents.on('will-prevent-unload', event => {
    if (allowDiscard) {allowDiscard = false; event.preventDefault(); return;}
    // A blocked quit preserves manual AI drafts and failed/conflicting edits.
    if (!quitPending) return;
    quitPending = false;
    showWindow();
    const t = text();
    void dialog.showMessageBox(window, {type: 'warning', title: 'LeafLoom', message: t.unsaved, detail: t.unsavedDetail, buttons: [t.back, t.exit], defaultId: 0, cancelId: 0}).then(choice => {if (choice.response === 1) {
      // Trigger a second unload with a one-use permission instead of relying on
      // an event that expired while the native dialog was awaiting a response.
      allowDiscard = true; quitPending = true; window.close();
    }}).catch(error => {quitPending = false; log(error);});
  });
  window.on('close', event => {
    if (!window.isMaximized() && !window.isMinimized()) atomicJson(path.join(home, 'desktop-window.json'), window.getBounds());
    if (!quitPending && !quitting) {event.preventDefault(); window.hide();}
  });
  window.on('closed', () => {window = null; if (quitPending) void finishQuit();});
  void window.loadFile(statusFile);
  if (!background || failure) window.once('ready-to-show', () => window?.show());
}
async function requestQuit() {
  if (quitting || quitPending) return;
  quitPending = true;
  if (window && !window.isDestroyed()) {
    try { await window.webContents.executeJavaScript('Promise.race([window.leafloomPrepareQuit?.(), new Promise(resolve => setTimeout(resolve, 5000))])'); } catch {}
    window.close();
  } else await finishQuit();
}
async function finishQuit() {
  if (quitting) return; quitting = true;
  clearTimeout(startupTimer); clearInterval(closeTimer);
  await backend?.stop();
  tray?.destroy(); app.quit();
}
function fail(error) {
  if (quitting) return;
  clearTimeout(startupTimer); failure = String(error.message || error); log(error);
  const keepDrafts = workspaceLoaded && window && lastOrigin && policy.trustedPage(window.webContents.getURL(), lastOrigin);
  origin = ''; showWindow(); updateMenu();
  // Keep an existing editor alive if its service fails. The connection banner
  // preserves drafts; Retry in the tray reconnects without reloading the page.
  if (!keepDrafts) void window.loadFile(statusFile).catch(log);
}
async function startBackend() {
  if (retrying || quitting) return; retrying = true;
  try {
    tunnelBackendReady = false;
    await backend?.stop();
    failure = ''; origin = '';
    const python = app.isPackaged
      ? path.join(process.resourcesPath, 'backend', 'python', process.platform === 'win32' ? 'python.exe' : 'bin/python3')
      : process.env.LEAFLOOM_PYTHON;
    if (!python || !fs.existsSync(python)) throw new Error('Private Python is missing. Build the backend, or set LEAFLOOM_PYTHON to its interpreter.');
    backend = new Backend({python, home});
    backend.on('failure', fail);
    backend.on('exit', result => {
      tunnelBackendReady = false;
      tunnel.state = {state: tunnel.value.enabled ? 'waiting' : 'disabled', error: ''};
      if (!result.expected && !quitting) fail(new Error('Local service exited (' + result.code + ').'));
    });
    backend.on('tunnel-state', value => {tunnel.state = {state: value.state, error: value.error};});
    backend.on('ready', async ready => {
      const preferencesPath = path.join(home, 'desktop-preferences.json');
      const previousPreferences = readJson(preferencesPath);
      const previousLogin = loginSettings().openAtLogin;
      const installPath = path.join(home, 'desktop-install.json');
      const registrationPath = path.join(registrationHome, 'desktop-current-home.json');
      const previousInstall = readJson(installPath), previousRegistration = readJson(registrationPath);
      let loginChanged = false, metadataChanged = false;
      try {
        if (ready.version !== app.getVersion()) throw new Error('App/backend version mismatch');
        const token = fs.readFileSync(path.join(home, 'auth-token'), 'utf8').trim();
        const response = await fetch(ready.url + '/api/status', {headers: {Authorization: 'Bearer ' + token}, signal: AbortSignal.timeout(10000)});
        if (!response.ok) throw new Error('Local service authentication failed');
        origin = new URL(ready.url).origin; lastOrigin = origin;
        if (!policy.trustedPage(window.webContents.getURL(), origin)) await window.loadURL(ready.url + '/');
        await window.webContents.executeJavaScript(`new Promise((resolve, reject) => {
          const limit = Date.now() + 15000;
          const poll = () => {
            if (document.querySelector('#root main') && window.leafloomDesktop) return resolve(true);
            if (Date.now() > limit) return reject(new Error('Workspace interface did not become ready'));
            setTimeout(poll, 100);
          }; poll();
        })`);
        workspaceLoaded = true;
        if (!previousPreferences && app.isPackaged) {loginChanged = true; setLogin(Boolean(ready.autostart));}
        if (app.isPackaged) {
          metadataChanged = true;
          atomicJson(installPath, {schema: 1, executable: process.execPath, version: app.getVersion(), home});
          // Finder/login launches cannot inherit VAULT_RAG_HOME. Remember the
          // successful state location without moving any of the existing data.
          fs.mkdirSync(registrationHome, {recursive: true, mode: 0o700});
          atomicJson(registrationPath, {schema: 1, home});
        }
        await new Promise((resolve, reject) => {
          const timer = setTimeout(() => reject(new Error('Migration commit timed out')), 10000);
          backend.once('committed', () => {clearTimeout(timer); resolve();});
          backend.send('commit');
        });
        clearTimeout(startupTimer); updateMenu();
        tunnelBackendReady = true;
        // Tunnel failure must not roll back an otherwise healthy workspace.
        try { configureTunnel(); } catch { tunnel.state = {state: 'failed', error: 'tunnel.error.process'}; }
        if (!background) showWindow();
      } catch (error) {
        fail(error); await backend.stop();
        if (metadataChanged) {
          for (const [file, previous] of [[installPath, previousInstall], [registrationPath, previousRegistration]]) {
            try {if (previous) atomicJson(file, previous); else if (fs.existsSync(file)) fs.unlinkSync(file);} catch (rollbackError) {log(rollbackError);}
          }
        }
        if (loginChanged) {
          try {
            app.setLoginItemSettings({openAtLogin: previousLogin, ...loginOptions()});
            if (previousPreferences) atomicJson(preferencesPath, previousPreferences);
            else if (fs.existsSync(preferencesPath)) fs.unlinkSync(preferencesPath);
            updateMenu();
          } catch (rollbackError) {log(rollbackError);}
        }
      }
    });
    backend.start();
    startupTimer = setTimeout(() => {fail(new Error('Local service startup timed out. See logs and retry.')); void backend.stop();}, 110000);
  } catch (error) {fail(error);} finally {retrying = false; if (tray) updateMenu();}
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', (_, argv) => {if (argv.includes('--quit')) void requestQuit(); else showWindow();});
  app.on('before-quit', event => {if (!quitting) {event.preventDefault(); void requestQuit();}});
  app.on('window-all-closed', () => {});
  app.on('activate', showWindow);
  app.whenReady().then(async () => {
    if (process.platform === 'darwin') background = background || loginSettings().wasOpenedAtLogin;
    if (process.argv.includes('--quit')) {quitting = true; app.quit(); return;}
    if (!((process.platform === 'win32' && process.arch === 'x64') || (process.platform === 'darwin' && process.arch === 'arm64'))) throw new Error('Supported platforms: Windows x64 and Apple Silicon macOS');
    session.defaultSession.setPermissionRequestHandler((_, __, callback) => callback(false));
    session.defaultSession.setPermissionCheckHandler(() => false);
    session.defaultSession.on('will-download', (event, item, contents) => {
      // Backend media responses already enforce the connected-folder boundary.
      if (!window || contents !== window.webContents || !origin || !item.getURL().startsWith(origin + '/api/media?')) event.preventDefault();
    });
    createWindow();
    const trayImage = nativeImage.createFromPath(image(process.platform === 'darwin' ? 'icon-32.png' : 'icon-64.png')).resize({width: process.platform === 'darwin' ? 18 : 32});
    tray = new Tray(trayImage); tray.setToolTip('LeafLoom'); tray.on('click', showWindow); tray.on('right-click', updateMenu); updateMenu();
    const t = text();
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      {label: 'LeafLoom', submenu: [{label: t.open, click: showWindow}, {type: 'separator'}, {label: t.quit, accelerator: 'CmdOrCtrl+Q', click: () => void requestQuit()}]},
      {role: 'editMenu'}, {role: 'viewMenu'}, {role: 'windowMenu'},
    ]));
    const methods = {
      'tunnel-status': () => tunnel.status(),
      'tunnel-save': input => {tunnel.save(input); return configureTunnel();},
      'tunnel-reconnect': () => {if (!tunnel.value.encryptedKey) throw new Error('tunnel.error.key'); tunnel.save({tunnelId: tunnel.value.tunnelId, enabled: true}); return configureTunnel();},
      'tunnel-disconnect': () => {tunnel.disable(); return configureTunnel();},
      'tunnel-clear': () => {tunnel.clear(); return configureTunnel();},
      info: () => ({version: app.getVersion(), platform: process.platform, openAtLogin: loginSettings().openAtLogin, error: failure, text: text()}),
      'choose-directory': async () => {const result = await dialog.showOpenDialog(window, {properties: ['openDirectory']}); return result.canceled ? {cancelled: true} : {path: result.filePaths[0]};},
      'open-external': async url => {await shell.openExternal(policy.externalUrl(url));},
      'reveal-file': async relative => {
        if (typeof relative !== 'string' || !relative || relative.includes('\0') || path.isAbsolute(relative)) throw new Error('Invalid file path');
        const config = readJson(path.join(home, 'config.json'));
        if (!config?.root) throw new Error('No connected folder');
        const root = await fs.promises.realpath(config.root);
        const file = await fs.promises.realpath(path.resolve(root, relative));
        if (!policy.inside(root, file) || relative.split(/[\\/]/).some(p => ['.git', '.vault-rag', '.obsidian', 'node_modules'].includes(p.toLowerCase()))) throw new Error('File is outside the connected folder');
        shell.showItemInFolder(file);
      },
      login: enabled => {if (typeof enabled !== 'boolean') throw new Error('Invalid setting'); setLogin(enabled); return {openAtLogin: enabled};},
      logs: () => shell.openPath(path.join(home, 'logs')),
      retry: () => startBackend(), quit: () => requestQuit(),
    };
    for (const [name, handler] of Object.entries(methods)) ipcMain.handle('leafloom:' + name, (event, ...args) => {isMain(event, !['info', 'logs', 'retry', 'quit'].includes(name)); return handler(...args);});
    // Also support legacy Stop scripts without depending on a Python install.
    fs.mkdirSync(control, {recursive: true});
    try {fs.unlinkSync(path.join(control, 'quit'));} catch {}
    closeTimer = setInterval(() => {if (fs.existsSync(path.join(control, 'quit'))) {fs.unlinkSync(path.join(control, 'quit')); void requestQuit();}}, 500);
    await startBackend();
  }).catch(error => {log(error); dialog.showErrorBox('LeafLoom', String(error.message || error)); quitting = true; app.quit();});
}
