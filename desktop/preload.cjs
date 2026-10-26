'use strict';
const {contextBridge, ipcRenderer} = require('electron');
if (process.isMainFrame) {
  const invoke = (name, ...args) => ipcRenderer.invoke('leafloom:' + name, ...args);
  contextBridge.exposeInMainWorld('leafloomDesktop', Object.freeze({
    appInfo: () => invoke('info'),
    publishDesign: jobId => invoke('design-publish', jobId),
    presenter: Object.freeze({
      displays: () => invoke('presenter-displays'),
      identify: () => invoke('presenter-identify'),
      start: input => invoke('presenter-start', input),
      command: (id, command) => invoke('presenter-command', id, command),
      input: (id, input) => invoke('presenter-input', id, input),
      ack: (id, seq) => invoke('presenter-ack', id, seq),
      heartbeat: id => invoke('presenter-heartbeat', id),
      stop: id => invoke('presenter-stop', id),
      subscribe: callback => {const listener = (_event, value) => callback(value); ipcRenderer.on('leafloom:presentation-event', listener); return () => ipcRenderer.removeListener('leafloom:presentation-event', listener);}
    }),
    updateStatus: () => invoke('update-status'),
    checkUpdate: () => invoke('update-check'),
    downloadUpdate: () => invoke('update-download'),
    installUpdate: () => invoke('update-install'),
    tunnelStatus: () => invoke('tunnel-status'),
    saveTunnel: input => invoke('tunnel-save', input),
    reconnectTunnel: () => invoke('tunnel-reconnect'),
    disconnectTunnel: () => invoke('tunnel-disconnect'),
    clearTunnel: () => invoke('tunnel-clear'),
    saveAttachmentCredential: input => invoke('attachment-credential-save', input),
    clearAttachmentCredential: input => invoke('attachment-credential-clear', input),
    attachmentCredentialStatus: () => invoke('attachment-credential-status'),
    retryAttachmentCredentials: () => invoke('attachment-credential-retry'),
    chooseDirectory: () => invoke('choose-directory'),
    revealFile: relative => invoke('reveal-file', relative),
    openExternal: url => invoke('open-external', url),
    setOpenAtLogin: enabled => invoke('login', enabled),
    openLogs: () => invoke('logs'),
    retry: () => invoke('retry'),
    quit: () => invoke('quit'),
  }));
}
