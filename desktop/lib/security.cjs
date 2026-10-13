'use strict';
function localApp(url, origin) {
  try { const u = new URL(url); return u.origin === origin && u.pathname === '/'; } catch { return false; }
}
function preview(url, origin) {
  try { const u = new URL(url); return u.origin === origin && /^\/html-preview\/[^/]+\/files\//.test(u.pathname); } catch { return false; }
}
function external(url) {
  try { const u = new URL(url); return ['https:', 'http:', 'mailto:'].includes(u.protocol); } catch { return false; }
}
const preferences = {nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true, webviewTag: false, plugins: true};
module.exports = {localApp, preview, external, preferences};
