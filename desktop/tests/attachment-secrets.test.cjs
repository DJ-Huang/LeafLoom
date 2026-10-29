'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const vm = require('node:vm');
const {AttachmentSecrets, registerAttachmentCredentialIpc} = require('../attachment-secrets.cjs');

const id = '0eb23ca3-4fea-4546-986b-8ac112cc50f1';
const otherId = 'bdef67f8e032457789b0e20e4b8fe18b';
const normalizedId = id.replaceAll('-', '');
const password = '  attachment secret 密码\n ';
function fixture(t, options = {}) {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'leafloom-attachment-secrets-'));
  t.after(() => fs.rmSync(home, {recursive: true, force: true}));
  const key = crypto.randomBytes(32), requests = [];
  const storage = {
    isEncryptionAvailable: () => true,
    getSelectedStorageBackend: () => 'keychain',
    encryptString(value) {
      const nonce = crypto.randomBytes(12), cipher = crypto.createCipheriv('aes-256-gcm', key, nonce);
      const body = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
      return Buffer.concat([nonce, cipher.getAuthTag(), body]);
    },
    decryptString(value) {
      const decipher = crypto.createDecipheriv('aes-256-gcm', key, value.subarray(0, 12));
      decipher.setAuthTag(value.subarray(12, 28));
      return Buffer.concat([decipher.update(value.subarray(28)), decipher.final()]).toString('utf8');
    },
  };
  const fetcher = async (url, options) => {requests.push({url, options, body: JSON.parse(options.body)}); return {ok: true};};
  return {home, storage, requests, fetcher, secrets: new AttachmentSecrets(home, storage, {fetcher, ...options})};
}
function asynchronousStorage(storage) {
  const encrypt = storage.encryptString.bind(storage), decrypt = storage.decryptString.bind(storage);
  storage.isAsyncEncryptionAvailable = async () => true;
  storage.encryptStringAsync = async value => encrypt(value);
  storage.decryptStringAsync = async value => ({result: decrypt(value), shouldReEncrypt: false});
  // An available async API must not silently retry through blocking methods.
  for (const name of ['isEncryptionAvailable', 'encryptString', 'decryptString']) {
    storage[name] = () => {throw new Error('Synchronous OS storage must not be used');};
  }
  return {encrypt, decrypt};
}

test('async OS encryption saves and restores legacy ciphertext without blocking APIs or rewriting storage', async t => {
  const {home, storage, secrets, requests, fetcher} = fixture(t);
  await secrets.save({storage_id: id, password}); // Existing synchronous-format file.
  const original = fs.readFileSync(secrets.file, 'utf8');
  asynchronousStorage(storage);
  const restored = new AttachmentSecrets(home, storage, {fetcher});
  assert.equal(await restored.restoreBackend('http://127.0.0.1:18080/', 'private-key'), 'ready');
  assert.equal(requests.at(-1).body.entries[normalizedId].password, password);
  const revision = requests.at(-1).body.entries[normalizedId].revision;
  assert.equal(fs.readFileSync(secrets.file, 'utf8'), original);
  await restored.save({storage_id: otherId, password: '  async fixture  '});
  assert.equal(requests.at(-1).body.entries[normalizedId].revision, revision);
  assert.equal(requests.at(-1).body.entries[otherId].password, '  async fixture  ');
  assert.ok(!fs.readFileSync(secrets.file, 'utf8').includes('async fixture'));
});

test('async OS encryption failures never fall back to blocking APIs or replace saved credentials', async t => {
  const {home, storage, secrets, requests, fetcher} = fixture(t, {retryDelays: []});
  await secrets.save({storage_id: id, password});
  const original = fs.readFileSync(secrets.file, 'utf8');
  asynchronousStorage(storage);
  storage.decryptStringAsync = async () => {throw new Error(password);};
  const restored = new AttachmentSecrets(home, storage, {fetcher, retryDelays: []});
  assert.equal(await restored.restoreBackend('http://127.0.0.1:18080/', 'private-key'), 'encryption_unavailable');
  assert.equal(requests.length, 0);
  await assert.rejects(restored.save({storage_id: otherId, password: 'fixture'}), error => !error.message.includes(password));
  assert.equal(fs.readFileSync(secrets.file, 'utf8'), original);
  const empty = fixture(t, {retryDelays: []});
  asynchronousStorage(empty.storage);
  empty.storage.isAsyncEncryptionAvailable = async () => false;
  await assert.rejects(empty.secrets.save({storage_id: id, password}), /System encryption is unavailable/);
  assert.equal(fs.existsSync(empty.secrets.file), false);
  empty.storage.isAsyncEncryptionAvailable = async () => true;
  empty.storage.encryptStringAsync = async () => {throw new Error(password);};
  await assert.rejects(empty.secrets.save({storage_id: id, password}), error => !error.message.includes(password));
  assert.equal(fs.existsSync(empty.secrets.file), false);
});

test('pending async decryption keeps diagnostics responsive, coalesces retries and never sends to a retired backend', async t => {
  const {storage, secrets, requests} = fixture(t, {retryDelays: []});
  await secrets.save({storage_id: id, password});
  const {decrypt} = asynchronousStorage(storage);
  let resolveDecrypt, decryptCalls = 0;
  storage.decryptStringAsync = value => {
    decryptCalls++;
    return new Promise(resolve => {resolveDecrypt = () => resolve({result: decrypt(value), shouldReEncrypt: true});});
  };
  const old = secrets.restoreBackend('http://127.0.0.1:18080/', 'old-key');
  await new Promise(setImmediate);
  assert.equal(decryptCalls, 1);
  assert.equal(requests.length, 0);
  assert.equal(secrets.status().attempts, 1); // Read-only status never queues OS work.
  const retries = [secrets.retryRestore(), secrets.retryRestore(), secrets.retryRestore()];
  const retired = secrets.target;
  const next = secrets.restoreBackend('http://127.0.0.1:18081/', 'new-key');
  assert.equal(retired.controller.signal.aborted, true);
  await new Promise(setImmediate);
  assert.equal(decryptCalls, 1);
  storage.decryptStringAsync = async value => {decryptCalls++; return {result: decrypt(value), shouldReEncrypt: false};};
  resolveDecrypt();
  assert.equal(await old, 'waiting_for_backend');
  assert.equal(await next, 'ready');
  await Promise.all(retries);
  assert.equal(decryptCalls, 2);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, 'http://127.0.0.1:18081/api/attachments/storage/credentials');
  assert.ok(!JSON.stringify(secrets.status()).includes(password));
});

test('encrypted persistence preserves the exact password and credential revision across restart', async t => {
  const {home, storage, requests, fetcher, secrets} = fixture(t);
  const result = await secrets.save({storage_id: id, password});
  assert.deepEqual(result, {password_saved: true, state: 'waiting_for_backend'});
  assert.ok(!JSON.stringify(result).includes(password));
  assert.equal(result.revision, undefined);
  assert.equal(result.password, undefined);
  assert.ok(!fs.readFileSync(secrets.file, 'utf8').includes('attachment secret'));
  if (process.platform !== 'win32') assert.equal(fs.statSync(secrets.file).mode & 0o777, 0o600);
  assert.deepEqual(fs.readdirSync(home), ['desktop-attachment-credentials.json']);
  const restored = new AttachmentSecrets(home, storage, {fetcher});
  assert.equal(await restored.restoreBackend('http://127.0.0.1:18080/', 'private-backend-key'), 'ready');
  const first = requests.at(-1);
  assert.equal(first.url, 'http://127.0.0.1:18080/api/attachments/storage/credentials');
  assert.equal(first.options.method, 'POST');
  assert.equal(first.options.redirect, 'error');
  assert.equal(first.options.headers.Authorization, 'Bearer private-backend-key');
  assert.equal(first.body.replace, true);
  assert.equal(first.body.entries[normalizedId].password, password);
  const revision = first.body.entries[normalizedId].revision;
  assert.match(revision, /^[a-f0-9-]{36}$/);
  await restored.restoreBackend('http://127.0.0.1:18081/', 'next-private-key');
  assert.equal(requests.at(-1).body.entries[normalizedId].revision, revision);
  await restored.save({storage_id: id.toUpperCase(), password: '  '});
  assert.equal(requests.at(-1).body.entries[normalizedId].password, '  ');
  assert.notEqual(requests.at(-1).body.entries[normalizedId].revision, revision);
  const boundary = '密'.repeat(1365) + 'x';
  assert.equal(Buffer.byteLength(boundary), 4096);
  await restored.save({storage_id: id, password: boundary});
  assert.equal(requests.at(-1).body.entries[normalizedId].password, boundary);
});

test('unavailable OS encryption and the plaintext fallback never save a credential', async t => {
  const {storage, secrets} = fixture(t);
  storage.isEncryptionAvailable = () => false;
  await assert.rejects(secrets.save({storage_id: id, password}), /System encryption is unavailable/);
  assert.equal(fs.existsSync(secrets.file), false);
  storage.isEncryptionAvailable = () => true;
  storage.getSelectedStorageBackend = () => 'basic_text';
  await assert.rejects(secrets.save({storage_id: id, password}), /System encryption is unavailable/);
  assert.equal(fs.existsSync(secrets.file), false);
  storage.getSelectedStorageBackend = () => 'keychain';
  storage.encryptString = () => {throw new Error(password);};
  await assert.rejects(secrets.save({storage_id: id, password}), error => !error.message.includes(password) && /System encryption/.test(error.message));
});

test('clear replaces the backend map without changing the remaining credential revision', async t => {
  const {secrets, requests} = fixture(t);
  await secrets.save({storage_id: id, password});
  await secrets.save({storage_id: otherId, password: 'second fixture'});
  await secrets.restoreBackend('http://127.0.0.1:18080/', 'private-key');
  const revision = requests.at(-1).body.entries[otherId].revision;
  assert.deepEqual(await secrets.clear({storage_id: id}), {password_saved: false, state: 'ready'});
  assert.equal(requests.at(-1).body.entries[normalizedId], undefined);
  assert.equal(requests.at(-1).body.entries[otherId].revision, revision);
  await secrets.clear({storage_id: otherId});
  assert.deepEqual(requests.at(-1).body.entries, {});
  assert.equal(requests.at(-1).body.replace, true);
  assert.ok(requests.at(-1).body.sync_sequence > requests[0].body.sync_sequence);
});

test('IPC checks the trusted caller and rejects invalid shapes before storing or forwarding', async t => {
  const {secrets, home, requests} = fixture(t), handlers = new Map();
  registerAttachmentCredentialIpc({handle: (name, fn) => handlers.set(name, fn)}, event => {
    if (event.sender !== 'main' || event.frame !== 'top' || event.origin !== 'workspace') throw new Error('Untrusted desktop caller');
  }, secrets);
  const save = handlers.get('leafloom:attachment-credential-save');
  const clear = handlers.get('leafloom:attachment-credential-clear');
  const trusted = {sender: 'main', frame: 'top', origin: 'workspace'};
  assert.equal(handlers.size, 4);
  for (const event of [{...trusted, frame: 'child'}, {...trusted, origin: 'project'}, {...trusted, sender: 'other'}]) {
    assert.throws(() => save(event, {storage_id: id, password}), /Untrusted desktop caller/);
    assert.throws(() => clear(event, {storage_id: id}), /Untrusted desktop caller/);
  }
  for (const input of [null, [], {}, {storage_id: '../profile', password}, {storage_id: 1, password},
    {storage_id: id, password: null}, {storage_id: id, password: ''}, {storage_id: id, password: 'x\0y'},
    {storage_id: id, password: 'x'.repeat(4097)}, {storage_id: id, password: '密'.repeat(1365) + 'xx'},
    {storage_id: id, password, extra: true}]) assert.throws(() => save(trusted, input), /Invalid attachment credential/);
  assert.throws(() => save(trusted, {storage_id: id, password}, {}), /Invalid attachment credential/);
  assert.throws(() => clear(trusted, {storage_id: id, password}), /Invalid attachment credential/);
  assert.deepEqual(fs.readdirSync(home), []);
  assert.equal(requests.length, 0);
  const response = await save(trusted, {storage_id: id, password});
  assert.deepEqual(Object.keys(response).sort(), ['password_saved', 'state']);
});

test('backend errors are redacted and leave the encrypted credential available for the next restore', async t => {
  const {home, storage, secrets, requests, fetcher} = fixture(t);
  await secrets.restoreBackend('http://127.0.0.1:18080/', 'private-key');
  secrets.fetcher = async () => {throw new Error(password);};
  assert.deepEqual(await secrets.save({storage_id: id, password}), {password_saved: true, state: 'sync_failed'});
  const restored = new AttachmentSecrets(home, storage, {fetcher});
  assert.equal(await restored.restoreBackend('http://127.0.0.1:18081/', 'next-key'), 'ready');
  assert.equal(requests.at(-1).body.entries[normalizedId].password, password);
  for (const url of ['https://example.test/', 'http://127.0.0.1:18080/redirect', 'http://private-key@127.0.0.1:18080/']) {
    assert.throws(() => restored.restoreBackend(url, 'private-key'), /service is unavailable/);
  }
  const count = requests.length;
  restored.disconnectBackend();
  assert.deepEqual(await restored.save({storage_id: id, password: 'offline fixture'}), {password_saved: true, state: 'waiting_for_backend'});
  assert.equal(requests.length, count);
});

test('corrupt or undecryptable storage never replaces the backend with an incomplete map', async t => {
  const {home, storage, secrets, requests, fetcher} = fixture(t);
  await secrets.save({storage_id: id, password});
  const original = fs.readFileSync(secrets.file, 'utf8');
  storage.decryptString = () => {throw new Error(password);};
  const restored = new AttachmentSecrets(home, storage, {fetcher});
  assert.equal(await restored.restoreBackend('http://127.0.0.1:18080/', 'private-key'), 'encryption_unavailable');
  assert.equal(requests.length, 0);
  await assert.rejects(restored.save({storage_id: otherId, password: 'fixture'}), error => !error.message.includes(password));
  assert.equal(fs.readFileSync(secrets.file, 'utf8'), original);
  fs.writeFileSync(secrets.file, '{invalid fixture');
  const corrupt = new AttachmentSecrets(home, storage, {fetcher});
  assert.equal(await corrupt.restoreBackend('http://127.0.0.1:18080/', 'private-key'), 'storage_unavailable');
  assert.equal(requests.length, 0);
});

test('the preload exposes narrow writes and redacted recovery operations to the main frame', async () => {
  const source = fs.readFileSync(path.join(__dirname, '../preload.cjs'), 'utf8');
  for (const isMainFrame of [false, true]) {
    const calls = []; let api;
    const electron = {contextBridge: {exposeInMainWorld: (name, value) => {assert.equal(name, 'leafloomDesktop'); api = value;}},
      ipcRenderer: {invoke: (...args) => {calls.push(args); return Promise.resolve({password_saved: true, state: 'ready'});}}};
    vm.runInNewContext(source, {process: {isMainFrame}, require: name => {assert.equal(name, 'electron'); return electron;}});
    if (!isMainFrame) {assert.equal(api, undefined); continue;}
    const input = {storage_id: id, password};
    await api.saveAttachmentCredential(input);
    await api.clearAttachmentCredential({storage_id: id});
    await api.attachmentCredentialStatus();
    await api.retryAttachmentCredentials();
    assert.deepEqual(calls[0], ['leafloom:attachment-credential-save', input]);
    assert.deepEqual(calls[1], ['leafloom:attachment-credential-clear', {storage_id: id}]);
    assert.deepEqual(calls[2], ['leafloom:attachment-credential-status']);
    assert.deepEqual(calls[3], ['leafloom:attachment-credential-retry']);
    assert.equal(api.getAttachmentCredential, undefined);
  }
});

function scheduler() {
  const timers = [];
  return {timers, schedule(fn, delay) {const timer = {fn, delay, active: true, unref() {}}; timers.push(timer); return timer;},
    cancel(timer) {timer.active = false;},
    async next(secrets) {const timer = timers.find(value => value.active); assert.ok(timer); timer.active = false; timer.fn(); await secrets.pending;}};
}

test('a temporarily locked OS store restores automatically without restarting or changing the credential file', async t => {
  const clock = scheduler(), states = [];
  const {storage, secrets, requests} = fixture(t, {...clock, now: () => 100, retryDelays: [10, 20], onState: value => states.push(value)});
  await secrets.save({storage_id: id, password});
  const original = fs.readFileSync(secrets.file, 'utf8'), decrypt = storage.decryptString;
  storage.decryptString = () => {throw new Error(password);};
  assert.equal(await secrets.restoreBackend('http://127.0.0.1:18080/', 'private-key'), 'encryption_unavailable');
  assert.equal(secrets.status().next_retry_at, 110);
  const attempts = secrets.status().attempts;
  secrets.status();
  assert.equal(secrets.status().attempts, attempts); // A status read does not decrypt or send anything.
  assert.equal(requests.length, 0);
  storage.decryptString = decrypt;
  await clock.next(secrets);
  assert.equal(secrets.status().state, 'ready');
  assert.equal(secrets.status().retry_scheduled, false);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].body.entries[normalizedId].password, password);
  assert.equal(fs.readFileSync(secrets.file, 'utf8'), original);
  for (const value of [secrets.status(), states]) assert.ok(!JSON.stringify(value).includes('attachment secret'));
});

test('local restore retries stop at the budget and unlock retry recovers without replacing corrupt storage', async t => {
  const clock = scheduler();
  const {storage, secrets, requests} = fixture(t, {...clock, retryDelays: [10, 20]});
  await secrets.save({storage_id: id, password});
  storage.isEncryptionAvailable = () => false;
  await secrets.restoreBackend('http://127.0.0.1:18080/', 'private-key');
  await clock.next(secrets); await clock.next(secrets);
  assert.equal(secrets.status().attempts, 3);
  assert.equal(secrets.status().retry_scheduled, false);
  assert.equal(requests.length, 0);
  storage.isEncryptionAvailable = () => true;
  assert.equal((await secrets.retryRestore()).state, 'ready');
  assert.equal(requests.length, 1);
  const before = requests.length;
  await secrets.retryRestore();
  assert.equal(requests.length, before);
  const originalFile = fs.readFileSync(secrets.file, 'utf8');
  fs.writeFileSync(secrets.file, '{invalid fixture');
  secrets.readCredentialsFile();
  assert.equal(await secrets.restoreBackend('http://127.0.0.1:18081/', 'next-key'), 'storage_unavailable');
  assert.equal(secrets.status().retry_scheduled, false);
  assert.equal(requests.length, before);
  fs.writeFileSync(secrets.file, originalFile);
  assert.equal((await secrets.retryRestore()).state, 'ready');
});

test('backend sync retries remain local, cancel on disconnect and preserve the stable credential revision', async t => {
  const clock = scheduler();
  const {secrets, requests, fetcher} = fixture(t, {...clock, retryDelays: [10]});
  await secrets.save({storage_id: id, password});
  secrets.fetcher = async () => {throw new Error(password);};
  await secrets.restoreBackend('http://127.0.0.1:18080/', 'private-key');
  assert.equal(secrets.status().state, 'sync_failed');
  const target = secrets.target;
  secrets.disconnectBackend();
  assert.equal(target.controller.signal.aborted, true);
  assert.equal(clock.timers.some(timer => timer.active), false);
  assert.equal(secrets.status().state, 'waiting_for_backend');
  secrets.fetcher = fetcher;
  await secrets.restoreBackend('http://127.0.0.1:18081/', 'next-key');
  const revision = requests.at(-1).body.entries[normalizedId].revision;
  await secrets.restoreBackend('http://127.0.0.1:18082/', 'third-key');
  assert.equal(requests.at(-1).body.entries[normalizedId].revision, revision);
  assert.ok(requests.every(value => value.url.startsWith('http://127.0.0.1:1808')));
});

test('recovery IPC validates the main frame and accepts no caller-supplied URLs or credentials', async t => {
  const {secrets} = fixture(t), handlers = new Map();
  registerAttachmentCredentialIpc({handle: (name, fn) => handlers.set(name, fn)}, event => {
    if (event !== 'trusted') throw new Error('Untrusted desktop caller');
  }, secrets);
  for (const name of ['status', 'retry']) {
    const handler = handlers.get('leafloom:attachment-credential-' + name);
    assert.throws(() => handler('other'), /Untrusted/);
    assert.throws(() => handler('trusted', {}), /Invalid/);
    const value = await handler('trusted');
    assert.deepEqual(Object.keys(value).sort(), ['attempts', 'next_retry_at', 'retry_scheduled', 'saved', 'state']);
  }
});

test('a retiring backend response cannot change the replacement backend recovery state', async t => {
  const {secrets, fetcher} = fixture(t, {retryDelays: []});
  await secrets.save({storage_id: id, password});
  let resolveOld, oldSignal;
  secrets.fetcher = async (_url, options) => {
    oldSignal = options.signal;
    return new Promise(resolve => {resolveOld = resolve;});
  };
  const old = secrets.restoreBackend('http://127.0.0.1:18080/', 'old-private-key');
  await new Promise(setImmediate);
  secrets.fetcher = fetcher;
  const next = secrets.restoreBackend('http://127.0.0.1:18081/', 'next-private-key');
  assert.equal(oldSignal.aborted, true);
  resolveOld({ok: true}); // Even a transport that ignores abort cannot overwrite state.
  assert.equal(await old, 'waiting_for_backend');
  assert.equal(await next, 'ready');
  assert.equal(secrets.status().state, 'ready');
});

test('failed local HTTP responses release the body without reading or exposing it', async t => {
  let cancelled = 0;
  const {secrets} = fixture(t, {retryDelays: [], fetcher: async () => ({ok: false,
    body: {cancel: async () => {cancelled++;}},
    text: () => {throw new Error('Response body must not be read');},
  })});
  await secrets.save({storage_id: id, password});
  assert.equal(await secrets.restoreBackend('http://127.0.0.1:18080/', 'private-key'), 'sync_failed');
  assert.equal(cancelled, 1);
  assert.ok(!JSON.stringify(secrets.status()).includes('attachment secret'));
});
