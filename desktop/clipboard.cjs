'use strict';

// Only the management window's trusted main frame may write to the clipboard.
function registerClipboardIpc(ipcMain, authorize, clipboard, nativeImage) {
  ipcMain.handle('leafloom:clipboard-write-text', async (event, text) => {
    authorize(event);
    if (typeof text !== 'string' || text.length > 1024 * 1024) throw new Error('Invalid clipboard text');
    await clipboard.writeText(text);
  });
  ipcMain.handle('leafloom:clipboard-write-image', async (event, png) => {
    authorize(event);
    if (!(png instanceof Uint8Array) || png.byteLength < 33 || png.byteLength > 32 * 1024 * 1024) throw new Error('Invalid clipboard image');
    const bytes = Buffer.from(png.buffer, png.byteOffset, png.byteLength);
    if (!bytes.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10])) || bytes.readUInt32BE(8) !== 13 || bytes.toString('ascii', 12, 16) !== 'IHDR') throw new Error('Invalid clipboard image');
    const width = bytes.readUInt32BE(16), height = bytes.readUInt32BE(20);
    if (!width || !height || width * height > 64_000_000) throw new Error('Invalid clipboard image size');
    const image = nativeImage.createFromBuffer(bytes);
    if (image.isEmpty()) throw new Error('Invalid clipboard image');
    const actual = image.getSize();
    if (actual.width !== width || actual.height !== height) throw new Error('Invalid clipboard image size');
    await clipboard.writeImage(image);
  });
}

module.exports = {registerClipboardIpc};
