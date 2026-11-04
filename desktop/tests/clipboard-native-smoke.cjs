'use strict';
// Run with the pinned Electron executable, not node. All windows/storage are
// disposable. Clipboard contents are materialized in memory and restored; no
// existing clipboard content is printed or saved to disk.
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),http=require('node:http');
const {app,BrowserWindow,ipcMain,clipboard,nativeImage,ClipboardItem}=require('electron');
const {registerClipboardIpc}=require('../clipboard.cjs');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'leafloom-clipboard-smoke-'));
app.setPath('userData',temporary);app.setPath('sessionData',path.join(temporary,'session'));
app.setAppLogsPath(path.join(temporary,'logs'));
let window,server,backup,changed=false,fixturePixels;
const readPng=async()=>{
 const entries=await clipboard.read(),item=entries.find(item=>item.types.includes('image/png'));
 if(!item)return null;
 return Buffer.from(await(await item.getType('image/png')).arrayBuffer());
};
app.whenReady().then(async()=>{
 app.dock?.hide();
 // Materialize every advertised format before any fixture write. Clipboard read
 // items may otherwise lazily refer to the clipboard we are about to replace.
 backup=await Promise.all((await clipboard.read()).map(async item=>new ClipboardItem(Object.fromEntries(await Promise.all(item.types.map(async type=>[type,await item.getType(type)]))))));
 server=http.createServer((_,response)=>{response.writeHead(200,{'Content-Type':'text/html','Permissions-Policy':'clipboard-write=()'});response.end('<!doctype html><title>Disposable clipboard fixture</title><p>Fictional image clipboard verification</p>');});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const origin='http://127.0.0.1:'+server.address().port;
 window=new BrowserWindow({show:false,webPreferences:{preload:path.resolve(__dirname,'../preload.cjs'),contextIsolation:true,sandbox:true,nodeIntegration:false}});
 registerClipboardIpc(ipcMain,event=>{
  assert.equal(event.sender,window.webContents);assert.equal(event.senderFrame,window.webContents.mainFrame);assert.equal(new URL(event.senderFrame.url).origin,origin);
 },clipboard,nativeImage,ClipboardItem);
 await window.loadURL(origin);
 const bitmap=Buffer.from([0,0,255,255,0,0,0,0,0,255,0,255,0,0,0,0]);
 const image=nativeImage.createFromBitmap(bitmap,{width:2,height:2,scaleFactor:1}),png=image.toPNG();fixturePixels=image.toBitmap();
 assert.equal(typeof clipboard.writeImage,'undefined','The fixture must exercise the modern Electron Clipboard API');
 changed=true;
 await window.webContents.executeJavaScript('window.leafloomDesktop.writeClipboardImage(new Uint8Array('+JSON.stringify(Array.from(png))+'))');
 const result=await readPng();assert.ok(result,'PNG must be available in the actual OS clipboard');
 const actual=nativeImage.createFromBuffer(result);assert.deepEqual(actual.getSize(),{width:2,height:2});assert.ok(actual.toBitmap().equals(fixturePixels),'Fixture colors and transparency must survive preload → IPC → clipboard → PNG readback');
 console.log(JSON.stringify({electron:process.versions.electron,platform:process.platform,checks:['real-preload-and-IPC','modern-async-clipboard-write','OS-PNG-readback','original-pixels-and-alpha']}));
}).catch(error=>{console.error(error.message);process.exitCode=1;}).finally(async()=>{
 try{
  if(changed){
   // Avoid replacing a newer user copy if the clipboard changed during the test.
   const now=await readPng();
   if(now&&fixturePixels&&nativeImage.createFromBuffer(now).toBitmap().equals(fixturePixels)){
    if(backup.length)await clipboard.write(backup);else clipboard.clear();
    console.log('Original clipboard restored.');
   }
  }
 }catch{console.error('Could not restore the original clipboard.');process.exitCode=1;}
 if(window&&!window.isDestroyed())window.destroy();
 if(server)await new Promise(resolve=>server.close(resolve));
 app.exit(process.exitCode||0);
});
