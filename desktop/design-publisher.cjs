'use strict';
// Only immutable, backend-prepared documents enter this renderer. It has no
// preload, credentials, filesystem or live backend/network access.
const {randomUUID} = require('node:crypto');
const ORIGIN = 'https://studio-export.invalid';
const MAX_BYTES = 256 * 1024 * 1024;
const CSP = "default-src 'none'; script-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
function jobId(value) {
  if (typeof value !== 'string' || !/^[a-zA-Z0-9_-]{16,80}$/.test(value)) throw new Error('Invalid publishing job');
  return value;
}
function prepareManifest(input, id) {
  if (!input || input.job_id !== id || !['png', 'pdf'].includes(input.format) || !Array.isArray(input.pages) || !input.pages.length || input.pages.length > 64) throw new Error('Invalid publishing manifest');
  if (!Number.isFinite(input.scale) || input.scale < 1 || input.scale > 4 || typeof input.runtime_js !== 'string' || input.runtime_js.length > 2000000 || typeof input.runtime_css !== 'string' || input.runtime_css.length > 2000000) throw new Error('Invalid publishing runtime');
  const resources = new Map(), ids = new Set(); let bytes = 0, pixels = 0;
  const add = (url, mime, body) => {
    bytes += body.length;
    if (bytes > MAX_BYTES || resources.has(url)) throw new Error('Publishing resources exceed limits');
    resources.set(url, {mime, body});
  };
  const pages = input.pages.map((page, index) => {
    if (!page || typeof page.id !== 'string' || page.id.length > 160 || ids.has(page.id) || !page.document || typeof page.document !== 'object' || typeof page.page_id !== 'string' || !Number.isInteger(page.width) || !Number.isInteger(page.height) || page.width < 1 || page.height < 1 || page.width > 8192 || page.height > 8192 || page.width * page.height > 32000000) throw new Error('Invalid publishing page');
    ids.add(page.id); pixels += Math.ceil(page.width * input.scale) * Math.ceil(page.height * input.scale);
    if (pixels > 128000000) throw new Error('Publishing pixel budget exceeded');
    const url = `${ORIGIN}/pages/${index}.html`;
    if (Math.ceil(page.width * input.scale) * Math.ceil(page.height * input.scale) > 32000000) throw new Error('Publishing page pixel budget exceeded');
    add(url, 'text/html; charset=utf-8', Buffer.from('<!doctype html><meta charset="utf-8"><div id="studio-root"></div>'));
    return {id: page.id, width: page.width, height: page.height, pageId: page.page_id, document: page.document, url};
  });
  if (!Array.isArray(input.resources) || input.resources.length > 2000) throw new Error('Invalid publishing resources');
  for (const resource of input.resources) {
    if (!resource || typeof resource.path !== 'string' || !resource.path || resource.path.startsWith('/') || /[\\?#\x00-\x1f]/.test(resource.path) || resource.path.split('/').some(part => part === '..' || part === '.') || typeof resource.mime !== 'string' || !/^[a-zA-Z0-9!#$&^_.+-]+\/[a-zA-Z0-9!#$&^_.+-]+$/.test(resource.mime) || typeof resource.data_base64 !== 'string' || resource.data_base64.length > MAX_BYTES * 1.4 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(resource.data_base64)) throw new Error('Invalid publishing resource');
    add(ORIGIN + '/' + resource.path.split('/').map(encodeURIComponent).join('/'), resource.mime, Buffer.from(resource.data_base64, 'base64'));
  }
  return {format: input.format, scale: input.scale, runtimeJs: input.runtime_js, runtimeCss: input.runtime_css, pages, resources};
}
async function boundedJson(response) {
  if (!response.ok) throw new Error(`Publishing service returned ${response.status}`);
  if (Number(response.headers.get('content-length')) > MAX_BYTES * 1.4) throw new Error('Publishing response too large');
  const chunks = []; let length = 0;
  for await (const chunk of response.body) {
    length += chunk.length;
    if (length > MAX_BYTES * 1.4) {throw new Error('Publishing response too large');}
    chunks.push(Buffer.from(chunk));
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}
function timeout(promise, ms, message) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => {timer = setTimeout(() => reject(new Error(message)), ms);})]).finally(() => clearTimeout(timer));
}
async function renderManifest({BrowserWindow, session}, manifest, submit) {
  const isolated = session.fromPartition('publish-' + randomUUID(), {cache: false});
  isolated.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  isolated.setPermissionCheckHandler(() => false);
  isolated.on('will-download', event => event.preventDefault());
  let blocked = false;
  isolated.webRequest.onBeforeRequest((details, callback) => {const cancel = !manifest.resources.has(details.url); if (cancel) blocked = true; callback({cancel});});
  isolated.protocol.handle('https', request => {
    const resource = manifest.resources.get(request.url);
    if (request.method !== 'GET' || !resource) return new Response('', {status: 403});
    return new Response(resource.body, {headers: {'Content-Type': resource.mime, 'Content-Security-Policy': CSP, 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store'}});
  });
  let win;
  try {
    for (const page of manifest.pages) {
      blocked = false;
      let output, pageError, preflight;
      try {
        const scale = manifest.format === 'png' ? manifest.scale : 1;
        const outputWidth = Math.ceil(page.width * scale), outputHeight = Math.ceil(page.height * scale);
        win = new BrowserWindow({show: false, width: outputWidth, height: outputHeight, useContentSize: true,
          webPreferences: {session: isolated, offscreen: true, nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true, devTools: false, spellcheck: false, backgroundThrottling: false}});
        const contents = win.webContents;
        contents.setWindowOpenHandler(() => ({action: 'deny'}));
        contents.on('will-navigate', event => event.preventDefault());
        contents.on('will-redirect', event => event.preventDefault());
        contents.on('will-attach-webview', event => event.preventDefault());
        contents.setZoomFactor(scale);
        await timeout(win.loadURL(page.url), 20000, 'Publishing page load timed out');
        await contents.executeJavaScript(`window.__publishErrors=[]; document.addEventListener('securitypolicyviolation', () => window.__publishErrors.push('A resource was blocked by the offline publishing policy')); true`);
        await contents.insertCSS(manifest.runtimeCss);
        await timeout(contents.executeJavaScript(manifest.runtimeJs), 5000, 'Publishing runtime timed out');
        await timeout(contents.executeJavaScript(`window.__publishInstance=LeafLoomStudio.mount(document.querySelector('#studio-root'), ${JSON.stringify(page.document)}, {mode:'static', alreadyResolved:true, pageId:${JSON.stringify(page.pageId)}, assetBase:${JSON.stringify(ORIGIN + '/')}, onMessage:m=>{if(m.type==='studio-error') window.__publishErrors.push(m.message)}}); true`), 10000, 'Publishing layout timed out');
        await contents.insertCSS(`@page { size: ${page.width}px ${page.height}px; margin: 0; } html, body { margin: 0 !important; width: ${page.width}px !important; height: ${page.height}px !important; overflow: hidden !important; } *, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }`);
        // This fixed main-process script only awaits resources; design scripts are
        // blocked by CSP. A broken image/font fails the export instead of silently
        // producing a partially loaded deliverable.
        await timeout(contents.executeJavaScript(`(async () => { await window.__publishInstance.readyForStatic({timeoutMs:15000,maxResources:512}); if (window.__publishErrors.length) throw Error(window.__publishErrors.join('; ')); if(document.querySelector('iframe,.studio-missing')) throw Error('Embedded HTML frames or missing references cannot be published statically'); return true; })()`), 17000, 'Publishing resources did not become ready');
        preflight = await timeout(contents.executeJavaScript('window.__publishInstance.preflight()'), 15000, 'Publishing preflight timed out');
        if (blocked) throw new Error('A publishing resource was blocked. Import external resources as project assets.');
        if (manifest.format === 'pdf') output = await timeout(contents.printToPDF({printBackground: true, preferCSSPageSize: true, margins: {top: 0, bottom: 0, left: 0, right: 0}, pageSize: {width: page.width / 96, height: page.height / 96}}), 30000, 'PDF rendering timed out');
        else {
          let capture = await timeout(contents.capturePage({x: 0, y: 0, width: outputWidth, height: outputHeight}), 15000, 'PNG rendering timed out');
          const size = capture.getSize();
          if (size.width !== outputWidth || size.height !== outputHeight) capture = capture.resize({width: outputWidth, height: outputHeight, quality: 'best'});
          output = capture.toPNG();
        }
        if (!output.length || output.length > 32 * 1024 * 1024) throw new Error('Rendered page exceeds publishing limits');
      } catch (error) {pageError = String(error.message || error).slice(0, 2000);}
      finally {if (win && !win.isDestroyed()) win.destroy(); win = null;}
      // Never retry an uncertain result upload as a contradictory failure.
      await submit(page.id, pageError ? null : output, pageError, preflight);
    }
  } finally {
    if (win && !win.isDestroyed()) win.destroy();
    isolated.protocol.unhandle('https');
    // Electron keeps partition sessions alive: release closures holding snapshots.
    isolated.webRequest.onBeforeRequest(null);
    isolated.removeAllListeners('will-download');
    isolated.setPermissionRequestHandler(null);
    isolated.setPermissionCheckHandler(null);
    await isolated.clearStorageData();
    await isolated.closeAllConnections();
  }
}
let activeJob = null;
async function publishJob(electron, serviceUrl, token, id, fetcher = fetch) {
  jobId(id);
  if (!require('./policy.cjs').localUrl(serviceUrl)) throw new Error('Publishing service unavailable');
  const base = serviceUrl.replace(/\/$/, '') + '/api/design/publish/' + id;
  const request = async (suffix, body) => boundedJson(await fetcher(base + suffix, {
    method: body ? 'POST' : 'GET', redirect: 'error', signal: AbortSignal.timeout(30000),
    headers: {Authorization: 'Bearer ' + token, ...(body ? {'Content-Type': 'application/json'} : {})},
    ...(body ? {body: JSON.stringify(body)} : {}),
  }));
  if (activeJob) {
    const error = new Error('Another desktop publication is still running');
    if (activeJob !== id) await request('/native-failure', {error: error.message}).catch(() => {});
    throw error;
  }
  activeJob = id;
  try {
    const manifest = prepareManifest(await request('/native-manifest'), id);
    let result;
    await renderManifest(electron, manifest, async (itemId, output, error, preflight) => {
      result = await request('/native-result', {item_id: itemId, ...(preflight ? {preflight} : {}), ...(error ? {error} : {data_base64: output.toString('base64')})});
    });
    return result;
  } catch (error) {
    // Server only fails still-pending items; an accepted but unacknowledged
    // result remains completed, so this never reverses a successful upload.
    await request('/native-failure', {error: String(error.message || error).slice(0, 1000)}).catch(() => {});
    throw error;
  } finally {activeJob = null;}
}
module.exports = {publishJob, jobId, prepareManifest, boundedJson, renderManifest, ORIGIN, CSP};
