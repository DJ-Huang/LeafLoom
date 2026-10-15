'use strict';
const path = require('node:path');

function localUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' && url.hostname === '127.0.0.1' && !url.username && !url.password && url.pathname === '/' && !url.search && !url.hash;
  } catch { return false; }
}
function trustedPage(value, origin) {
  try { const url = new URL(value); return url.origin === origin && url.pathname === '/'; } catch { return false; }
}
function externalUrl(value) {
  if (typeof value !== 'string' || value.length > 8192) throw new Error('Invalid link');
  const url = new URL(value);
  if (!['https:', 'http:', 'mailto:'].includes(url.protocol) || url.username || url.password) throw new Error('Unsupported link');
  if (url.protocol !== 'mailto:' && (['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) || /^(0|10|127)\.|^192\.168\.|^169\.254\.|^172\.(1[6-9]|2\d|3[01])\./.test(url.hostname))) throw new Error('Local links cannot be opened externally');
  return url.href;
}
function inside(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === '' || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative));
}
function validBounds(value, displays) {
  const width = Math.max(800, Math.min(2400, Number(value?.width) || 1200));
  const height = Math.max(600, Math.min(1800, Number(value?.height) || 850));
  const bounds = {width, height};
  if (Number.isFinite(value?.x) && Number.isFinite(value?.y) && displays.some(({workArea: d}) => value.x + 100 > d.x && value.y + 100 > d.y && value.x < d.x + d.width && value.y < d.y + d.height)) Object.assign(bounds, {x: value.x, y: value.y});
  return bounds;
}
module.exports = {localUrl, trustedPage, externalUrl, inside, validBounds};
