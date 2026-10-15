'use strict';
const {contextBridge, ipcRenderer} = require('electron');
if (process.isMainFrame) {
  const invoke = (name, ...args) => ipcRenderer.invoke('leafloom:' + name, ...args);
  contextBridge.exposeInMainWorld('leafloomDesktop', Object.freeze({
    appInfo: () => invoke('info'),
    chooseDirectory: () => invoke('choose-directory'),
    revealFile: relative => invoke('reveal-file', relative),
    openExternal: url => invoke('open-external', url),
    setOpenAtLogin: enabled => invoke('login', enabled),
    openLogs: () => invoke('logs'),
    retry: () => invoke('retry'),
    quit: () => invoke('quit'),
  }));
}
