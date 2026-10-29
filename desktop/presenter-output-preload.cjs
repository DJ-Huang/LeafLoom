'use strict';
const {contextBridge, ipcRenderer} = require('electron');
if (process.isMainFrame) contextBridge.exposeInMainWorld('leafloomAudience', Object.freeze({
  ready: () => ipcRenderer.invoke('leafloom:presentation-output-ready'),
  report: value => ipcRenderer.send('leafloom:presentation-output-report', value),
  subscribe: callback => {const listener = (_event, value) => callback(value); ipcRenderer.on('leafloom:presentation-output', listener); return () => ipcRenderer.removeListener('leafloom:presentation-output', listener);}
}));
