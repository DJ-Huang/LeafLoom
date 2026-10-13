const test = require('node:test');
const assert = require('node:assert/strict');
const {localApp, preview, external, preferences} = require('../lib/security.cjs');
const origin = 'http://127.0.0.1:18080';
test('desktop privileges only apply to the workspace page', () => {
  assert.ok(localApp(origin + '/?note=RAG/a.md', origin));
  for (const url of [origin + '/html-preview/x/files/a.html', origin + '.attacker/', 'file:///etc/passwd', 'http://localhost:18080/', origin + '/api/media']) assert.equal(localApp(url, origin), false);
});
test('preview windows and external protocols cannot inherit desktop privileges', () => {
  assert.ok(preview(origin + '/html-preview/key/files/a.html', origin));
  assert.equal(preview(origin + '/api/media?path=x.html', origin), false);
  assert.equal(preview('http://attacker/html-preview/key/files/a.html', origin), false);
  assert.ok(external('https://example.com/'));
  for (const url of ['javascript:alert(1)', 'file:///etc/passwd', 'cmd:run', 'data:text/html,x']) assert.equal(external(url), false);
  assert.equal(preferences.nodeIntegration, false); assert.equal(preferences.sandbox, true); assert.equal(preferences.contextIsolation, true);
});
