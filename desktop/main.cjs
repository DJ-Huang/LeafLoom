'use strict';
const {app, BrowserWindow, Tray, Menu, ipcMain, dialog, shell, nativeImage} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {Backend} = require('./lib/backend.cjs');
const {localApp, preview, external, preferences} = require('./lib/security.cjs');
const {createTranslator} = require('./lib/i18n.cjs');

const APP_ID = 'com.djhuang.vault-rag.desktop';
const home = path.resolve(process.env.VAULT_RAG_HOME || (process.platform === 'win32'
  ? path.join(process.env.LOCALAPPDATA || app.getPath('home'), 'VaultRag')
  : path.join(app.getPath('home'), 'Library/Application Support/VaultRag')));
const desktopHome = path.join(home, 'desktop');
const t = createTranslator(home, app.isPackaged ? path.join(process.resourcesPath, 'locales') : path.resolve(__dirname, '../vault_rag/locales'), () => app.getLocale());
fs.mkdirSync(desktopHome, {recursive: true, mode: 0o700});
app.setPath('userData', desktopHome);
app.setAppUserModelId(APP_ID);
app.enableSandbox();
const settingsFile = path.join(desktopHome, 'settings.json');
function readSettings() { return fs.existsSync(settingsFile) ? JSON.parse(fs.readFileSync(settingsFile, 'utf8')) : {}; }
function writeSettings(settings) {
  const temporary = settingsFile + '.' + crypto.randomUUID() + '.tmp';
  fs.writeFileSync(temporary, JSON.stringify(settings, null, 2), {mode: 0o600});
  fs.renameSync(temporary, settingsFile);
}
function autostart(enabled) {
  const options = {path: process.execPath, args: ['--background']};
  if (app.getLoginItemSettings(options).openAtLogin !== enabled) {
    app.setLoginItemSettings({openAtLogin: enabled, ...options});
    if (app.getLoginItemSettings(options).openAtLogin !== enabled) {
      throw new Error(t('无法设置登录启动，请在系统设置中检查 LeafLoom 的权限。'));
    }
  }
  const settings = readSettings(); writeSettings({...settings, autostart: enabled});
}
function loginEnabled() {return app.getLoginItemSettings({path: process.execPath, args: ['--background']}).openAtLogin;}

const maintenance = process.argv.includes('--prepare-update') || process.argv.includes('--prepare-uninstall');
const requestId = crypto.randomUUID();
const ownLock = app.requestSingleInstanceLock(maintenance ? {maintenance: {id: requestId,
  uninstall: process.argv.includes('--prepare-uninstall')}} : {});
if (!ownLock) {
  if (maintenance) {
    const resultFile = path.join(desktopHome, 'maintenance-' + requestId + '.json');
    const deadline = Date.now() + 150000;
    const poll = setInterval(() => {
      if (fs.existsSync(resultFile)) {
        const result = JSON.parse(fs.readFileSync(resultFile, 'utf8')); fs.unlinkSync(resultFile);
        clearInterval(poll); app.exit(result.ok ? 0 : 1);
      } else if (Date.now() > deadline) { clearInterval(poll); app.exit(1); }
    }, 250);
  } else app.quit();
} else {
  let mainWindow, tray, backend, origin, quitting = false, quitBusy = false, crashBusy = false;
  const quitResponses = new Map();
  const previews = new Set();
  const executable = app.isPackaged ? path.join(process.resourcesPath, 'backend', process.platform === 'win32' ? 'vault-rag-backend.exe' : 'vault-rag-backend')
    : path.resolve(__dirname, '../_generated/backend/vault-rag-backend', process.platform === 'win32' ? 'vault-rag-backend.exe' : 'vault-rag-backend');
  function trusted(event) {
    if (!mainWindow || event.sender !== mainWindow.webContents || event.senderFrame !== mainWindow.webContents.mainFrame || !localApp(event.senderFrame.url, origin)) throw new Error('桌面操作来源不允许');
  }
  function show() { if (!mainWindow) return; if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.show(); mainWindow.focus(); }
  function message(text) {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    const script = `document.getElementById('message')?.replaceChildren(document.createTextNode(${JSON.stringify(text)}))`;
    if (mainWindow.webContents.getURL().startsWith('file:')) void mainWindow.webContents.executeJavaScript(script);
  }
  async function startup(text) {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    await mainWindow.loadFile(path.join(__dirname, 'assets/startup.html')); message(text);
  }
  function protect(window, isPreview = false) {
    const content = window.webContents;
    content.on('will-navigate', (event, url) => {
      if (isPreview ? preview(url, origin) : localApp(url, origin)) return;
      event.preventDefault();
      let destination; try { destination = new URL(url); } catch { return; }
      if (!isPreview && destination.origin === origin && destination.pathname === '/api/media' && destination.searchParams.get('download') === 'true') {
        content.downloadURL(url); return;
      }
      if (external(url) && destination.origin !== origin) void shell.openExternal(url);
    });
    content.on('will-redirect', (event, url) => {
      if (!(isPreview ? preview(url, origin) : localApp(url, origin))) event.preventDefault();
    });
    content.setWindowOpenHandler(({url}) => {
      if (preview(url, origin)) {
        const window = new BrowserWindow({title: t('网页预览'), width: 1000, height: 780,
          webPreferences: {...preferences, partition: 'vault-preview-' + crypto.randomUUID()}});
        previews.add(window); window.on('closed', () => previews.delete(window));
        protect(window, true); void window.loadURL(url);
      } else if (external(url) && new URL(url).origin !== origin) void shell.openExternal(url);
      return {action: 'deny'};
    });
    content.session.setPermissionRequestHandler((_, __, callback) => callback(false));
    content.session.setPermissionCheckHandler(() => false);
    content.session.on('will-download', (_, item) => item.setSaveDialogOptions({title: t('保存文件')}));
    content.on('will-prevent-unload', event => {
      // Hiding a window never discards drafts; actual quit is handled by the handshake.
      if (quitting) event.preventDefault();
    });
  }
  function menu() {
    tray.setContextMenu(Menu.buildFromTemplate([
      {label: t('打开 LeafLoom'), click: show},
      {label: t('重启服务'), enabled: !quitBusy, click: async () => {
        try {
          if (!(await prepareQuit())) return;
          await startup(t('正在重启本地服务…')); await backend.stop(); await backend.start(); await mainWindow.loadURL(origin + '/');
        } catch (error) { await failure(error); }
      }},
      {label: t('查看日志'), click: () => shell.openPath(path.join(home, 'logs'))},
      {label: t('登录时启动'), type: 'checkbox', checked: loginEnabled(), click: async item => {
        try {autostart(item.checked);} catch (error) {await dialog.showMessageBox(mainWindow, {type: 'warning', message: error.message});}
        menu();
      }},
      {type: 'separator'}, {label: t('退出'), click: () => void requestQuit()}
    ]));
  }
  async function prepareQuit() {
    if (!mainWindow || !localApp(mainWindow.webContents.getURL(), origin)) return true;
    const id = crypto.randomUUID();
    const answer = new Promise(resolve => {
      const timer = setTimeout(() => { quitResponses.delete(id); resolve(false); }, 60000);
      quitResponses.set(id, value => { clearTimeout(timer); resolve(value); });
    });
    show(); mainWindow.webContents.send('desktop:before-quit', id);
    const ready = await answer;
    if (!ready) await dialog.showMessageBox(mainWindow, {type: 'warning', message: t('尚未退出'),
      detail: t('请先处理未保存的设置或文档。保存冲突的草稿仍保留在 App 中。')});
    return ready;
  }
  async function requestQuit(maintenanceRequest) {
    const complete = ok => {
      if (maintenanceRequest && /^[0-9a-f-]{36}$/.test(maintenanceRequest.id)) {
        fs.writeFileSync(path.join(desktopHome, 'maintenance-' + maintenanceRequest.id + '.json'), JSON.stringify({ok}), {mode: 0o600});
      }
    };
    if (quitBusy) { complete(false); return; }
    quitBusy = true;
    try {
      if (!(await prepareQuit())) { complete(false); return; }
      await startup(t('正在保存并停止本地服务…'));
      if (backend) await backend.stop();
      if (maintenanceRequest?.uninstall) autostart(false);
      quitting = true;
      // Acknowledge only after Electron releases its files and singleton lock.
      app.once('will-quit', () => complete(true));
      app.quit();
    } catch (error) { complete(false); await failure(error); }
    finally { quitBusy = false; }
  }
  async function failure(error) {
    await startup(String(error.message || error) + '\n日志位置：' + path.join(home, 'logs'));
    tray?.setToolTip(t('本地知识库：服务需要处理')); show();
  }
  app.on('second-instance', (_, argv, cwd, additional) => {
    if (additional?.maintenance) void requestQuit(additional.maintenance); else show();
  });
  app.on('activate', show);
  app.on('window-all-closed', () => {});
  app.on('before-quit', event => { if (!quitting) { event.preventDefault(); void requestQuit(); } });
  ipcMain.handle('desktop:choose-directory', async event => {
    trusted(event); const result = await dialog.showOpenDialog(mainWindow, {title: t('关联本地知识目录'), properties: ['openDirectory']});
    return result.canceled ? {cancelled: true} : {path: result.filePaths[0]};
  });
  ipcMain.handle('desktop:get-autostart', event => { trusted(event); return loginEnabled(); });
  ipcMain.handle('desktop:set-autostart', (event, enabled) => {
    trusted(event); if (typeof enabled !== 'boolean') throw new Error('登录启动设置无效');
    autostart(enabled); menu(); return enabled;
  });
  ipcMain.on('desktop:quit-result', (event, id, ready) => {
    try { trusted(event); } catch { return; }
    const resolve = quitResponses.get(id); if (!resolve) return;
    quitResponses.delete(id); resolve(ready === true);
  });
  app.whenReady().then(async () => {
    if (maintenance) { if (process.argv.includes('--prepare-uninstall')) autostart(false); quitting = true; app.quit(); return; }
    mainWindow = new BrowserWindow({title: 'LeafLoom', width: 1240, height: 860, minWidth: 700, minHeight: 500,
      show: !process.argv.includes('--background'), webPreferences: {...preferences, preload: path.join(__dirname, 'preload.cjs')}});
    mainWindow.on('close', event => { if (!quitting) { event.preventDefault(); mainWindow.hide(); } });
    protect(mainWindow);
    const icon = nativeImage.createFromPath(path.join(__dirname, 'assets/tray.png'));
    if (process.platform === 'darwin') icon.setTemplateImage(true);
    tray = new Tray(icon); tray.setToolTip('LeafLoom'); tray.on('double-click', show); menu();
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      {label: 'LeafLoom', submenu: [{label: t('关于 LeafLoom'), role: 'about'}, {type: 'separator'},
        {label: t('退出 LeafLoom'), accelerator: 'CmdOrCtrl+Q', click: () => void requestQuit()}]},
      {label: t('编辑'), submenu: [{role: 'undo'}, {role: 'redo'}, {type: 'separator'}, {role: 'cut'}, {role: 'copy'}, {role: 'paste'}, {role: 'selectAll'}]},
      {label: t('窗口'), submenu: [{role: 'minimize'}, {role: 'zoom'}, {label: t('打开主窗口'), click: show}]}
    ]));
    await startup(t('正在检查本地服务…'));
    backend = new Backend({executable, home, version: app.getVersion()}); origin = backend.origin;
    let settings = readSettings();
    if (!settings.migrationComplete) {
      const legacy = await backend.run('inspect-legacy');
      if (legacy.legacy) {
        show();
        const choice = await dialog.showMessageBox(mainWindow, {type: 'info', message: t('接管旧版本地知识库'),
          detail: t('请先在旧浏览器保存尚未保存的草稿。继续后会备份旧启动项，保留配置、模型和知识库数据，并切换到桌面 App。'),
          buttons: [t('已保存，继续'), t('稍后')], defaultId: 0, cancelId: 1});
        if (choice.response !== 0) throw new Error(t('旧版本迁移尚未完成；保存浏览器草稿后，退出并重新打开 App'));
      }
      const migration = await backend.run('migrate-legacy');
      settings = {...settings, migrationComplete: true, migrationBackup: migration.backup,
        autostart: legacy.legacy ? migration.autostart : false};
      writeSettings(settings);
    }
    let loginError;
    try {autostart(!!settings.autostart);} catch (error) {loginError = error.message;}
    menu();
    fs.watch(home, {persistent: false}, (_, file) => {if(String(file)==='preferences.json')menu();});
    let readyOnce = false;
    backend.on('crash', async error => {
      if (!readyOnce || quitBusy || crashBusy) return;
      crashBusy = true;
      try {
        tray.setToolTip(t('本地知识库：后台正在重新启动'));
        // Keep the editor alive; its existing SSE reconnect restores the service session.
        while (true) {
          try { await backend.restartAfterCrash(); break; }
          catch (error) { if (backend.child || backend.restarts >= 3) throw error; }
        }
        tray.setToolTip('LeafLoom');
        if (!localApp(mainWindow.webContents.getURL(), origin)) await mainWindow.loadURL(origin + '/');
      } catch (restartError) { await failure(restartError); }
      finally { crashBusy = false; }
    });
    await backend.start(); readyOnce = true; await mainWindow.loadURL(origin + '/');
    if (loginError) void dialog.showMessageBox(mainWindow, {type: 'warning', message: loginError});
  }).catch(error => { if (mainWindow) void failure(error); else { dialog.showErrorBox(t('本地知识库启动失败'), error.message); app.exit(1); } });
}
