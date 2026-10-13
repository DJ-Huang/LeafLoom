'use strict';
const {contextBridge, ipcRenderer} = require('electron');
contextBridge.exposeInMainWorld('vaultDesktop', {
  chooseDirectory: () => ipcRenderer.invoke('desktop:choose-directory'),
  getAutostart: () => ipcRenderer.invoke('desktop:get-autostart'),
  setAutostart: enabled => ipcRenderer.invoke('desktop:set-autostart', enabled),
  onBeforeQuit: callback => {
    const listener = async (_, id) => {
      try { ipcRenderer.send('desktop:quit-result', id, !!(await callback())); }
      catch { ipcRenderer.send('desktop:quit-result', id, false); }
    };
    ipcRenderer.on('desktop:before-quit', listener);
    return () => ipcRenderer.removeListener('desktop:before-quit', listener);
  }
});
