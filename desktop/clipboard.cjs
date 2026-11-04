'use strict';

// Only the management window's trusted main frame may copy plain text.
function registerClipboardIpc(ipcMain, authorize, clipboard) {
  ipcMain.handle('leafloom:clipboard-write-text', async (event, text) => {
    authorize(event);
    if (typeof text !== 'string' || text.length > 1024 * 1024) throw new Error('Invalid clipboard text');
    await clipboard.writeText(text);
  });
}

module.exports = {registerClipboardIpc};
