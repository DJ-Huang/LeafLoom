'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {randomUUID} = require('node:crypto');
const {localUrl} = require('./policy.cjs');

const MAX_PASSWORD_BYTES = 4096;
const MAX_FILE_BYTES = 32 * 1024 * 1024;
const UUID = /^(?:[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})$/i;
const errors = Object.freeze({
  input: 'Invalid attachment credential',
  encryption: 'System encryption is unavailable for attachment credentials',
  storage: 'Attachment credential storage is unavailable',
});

function storageId(value) {
  if (typeof value !== 'string' || !UUID.test(value)) throw new Error(errors.input);
  return value.replaceAll('-', '').toLowerCase();
}
function passwordValid(value) {
  return typeof value === 'string' && value.length > 0 && Buffer.byteLength(value, 'utf8') <= MAX_PASSWORD_BYTES && !value.includes('\0');
}
function inputId(input, saving) {
  const keys = saving ? ['storage_id', 'password'] : ['storage_id'];
  if (!input || typeof input !== 'object' || Array.isArray(input) ||
      Object.keys(input).length !== keys.length || keys.some(key => !Object.hasOwn(input, key)) ||
      (saving && !passwordValid(input.password))) throw new Error(errors.input);
  return storageId(input.storage_id);
}
function checkedEntries(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(errors.storage);
  const entries = Object.create(null);
  for (const [id, entry] of Object.entries(value)) {
    if (storageId(id) !== id || !entry || typeof entry !== 'object' || Array.isArray(entry) ||
        Object.keys(entry).length !== 2 || !Object.hasOwn(entry, 'password') || !Object.hasOwn(entry, 'revision') ||
        !passwordValid(entry.password) || typeof entry.revision !== 'string' || !UUID.test(entry.revision)) throw new Error(errors.storage);
    entries[id] = {password: entry.password, revision: entry.revision};
  }
  return entries;
}

// Only this main-process store decrypts credentials. The renderer receives a
// redacted acknowledgement, and the backend receives an in-memory replacement.
class AttachmentSecrets {
  constructor(home, safeStorage, {fetcher = globalThis.fetch, schedule = setTimeout, cancel = clearTimeout, now = Date.now, retryDelays = [1000, 3000, 10000, 30000], onState = () => {}} = {}) {
    this.file = path.join(home, 'desktop-attachment-credentials.json');
    this.storage = safeStorage;
    this.fetcher = fetcher;
    this.schedule = schedule;
    this.cancel = cancel;
    this.now = now;
    this.retryDelays = retryDelays;
    this.onState = onState;
    this.retryTimer = null;
    this.nextRetryAt = null;
    this.target = null;
    this.state = 'waiting_for_backend';
    this.syncSequence = 0;
    this.pending = Promise.resolve();
    this.ciphertext = null;
    this.readError = false;
    this.readCredentialsFile(true);
  }
  readCredentialsFile(allowMissing = false) {
    try {
      if (fs.statSync(this.file).size > MAX_FILE_BYTES) throw new Error();
      const data = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      if (!data || data.schema !== 1 || typeof data.encrypted_entries !== 'string' || !data.encrypted_entries ||
          !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(data.encrypted_entries)) throw new Error();
      this.ciphertext = data.encrypted_entries;
      this.readError = false;
    } catch (error) {
      if (allowMissing && error.code === 'ENOENT') return;
      this.readError = error.code ? 'io' : 'invalid';
    }
  }
  async encryptionAvailable() {
    try {
      if (typeof this.storage.getSelectedStorageBackend === 'function' && this.storage.getSelectedStorageBackend() === 'basic_text') return false;
      return Boolean(typeof this.storage.isAsyncEncryptionAvailable === 'function'
        ? await this.storage.isAsyncEncryptionAvailable() : this.storage.isEncryptionAvailable());
    } catch {return false;}
  }
  async entries() {
    if (this.readError) throw new Error(errors.storage);
    if (this.ciphertext === null) return Object.create(null);
    if (!await this.encryptionAvailable()) throw new Error(errors.encryption);
    try {
      const encrypted = Buffer.from(this.ciphertext, 'base64');
      const plaintext = typeof this.storage.decryptStringAsync === 'function'
        ? (await this.storage.decryptStringAsync(encrypted)).result : this.storage.decryptString(encrypted);
      // Restoring never rewrites the saved ciphertext, including when the OS
      // reports key rotation. Explicit saves use the current encryption API.
      return checkedEntries(JSON.parse(plaintext));
    } catch {throw new Error(errors.encryption);}
  }
  async write(entries) {
    if (!await this.encryptionAvailable()) throw new Error(errors.encryption);
    let encrypted;
    try {
      const value = typeof this.storage.encryptStringAsync === 'function'
        ? await this.storage.encryptStringAsync(JSON.stringify(entries)) : this.storage.encryptString(JSON.stringify(entries));
      if (!Buffer.isBuffer(value) || !value.length) throw new Error();
      encrypted = value.toString('base64');
    } catch {throw new Error(errors.encryption);}
    const body = JSON.stringify({schema: 1, encrypted_entries: encrypted});
    if (Buffer.byteLength(body) > MAX_FILE_BYTES) throw new Error(errors.storage);
    const temp = this.file + '.' + process.pid + '.' + randomUUID() + '.tmp';
    let fd;
    try {
      fd = fs.openSync(temp, 'wx', 0o600);
      fs.writeFileSync(fd, body);
      fs.fsyncSync(fd);
      fs.closeSync(fd); fd = undefined;
      fs.renameSync(temp, this.file);
      this.ciphertext = encrypted;
      this.readError = false;
    } catch {throw new Error(errors.storage);}
    finally {
      if (fd !== undefined) {try {fs.closeSync(fd);} catch {}}
      try {fs.unlinkSync(temp);} catch {}
    }
  }
  enqueue(work) {
    const result = this.pending.then(work);
    this.pending = result.catch(() => {});
    return result;
  }
  enqueueRestore(target, reread = false) {
    if (!target || target !== this.target) return Promise.resolve('waiting_for_backend');
    // Keychain initialization can remain pending while macOS requests access.
    // Coalesce retries instead of queueing more OS requests behind that one.
    if (target.restorePromise) return target.restorePromise;
    const result = this.enqueue(() => {
      if (target !== this.target) return 'waiting_for_backend';
      if (reread && this.readError) this.readCredentialsFile();
      return this.sync(target);
    });
    target.restorePromise = result;
    const clear = () => {if (target.restorePromise === result) target.restorePromise = null;};
    void result.then(clear, clear);
    return result;
  }
  disconnectBackend() {
    this.clearRetry();
    this.target?.controller.abort();
    this.target = null;
    this.state = 'waiting_for_backend';
  }
  clearRetry() {
    if (this.retryTimer !== null) this.cancel(this.retryTimer);
    this.retryTimer = null;
    this.nextRetryAt = null;
  }
  status() {
    return {state: this.state, saved: this.ciphertext !== null, attempts: this.target?.attempts || 0,
      retry_scheduled: this.retryTimer !== null, next_retry_at: this.nextRetryAt};
  }
  reportState() {
    // Diagnostics contain only fixed states and counters, never decrypted
    // entries, local service tokens, URLs or remote response/error text.
    try {this.onState(this.status());} catch {}
  }
  scheduleRetry(target) {
    if (target !== this.target || this.retryTimer !== null || target.retries >= this.retryDelays.length) return;
    const delay = this.retryDelays[target.retries++];
    this.nextRetryAt = this.now() + delay;
    this.retryTimer = this.schedule(() => {
      this.retryTimer = null;
      this.nextRetryAt = null;
      if (target === this.target) void this.enqueueRestore(target);
    }, delay);
    this.retryTimer?.unref?.();
  }
  retryRestore() {
    const target = this.target;
    if (!target || this.state === 'ready') return Promise.resolve(this.status());
    if (target.restorePromise) return target.restorePromise.then(() => this.status());
    this.clearRetry();
    // Unlock/resume and an explicit retry start a fresh, bounded local restore
    // cycle. They never retry a NAS password or modify the encrypted file.
    target.retries = 0;
    return this.enqueueRestore(target, true).then(() => this.status());
  }
  restoreBackend(serviceUrl, token) {
    if (!localUrl(serviceUrl) || typeof token !== 'string' || !token || /[\r\n\0]/.test(token)) throw new Error('Attachment credential service is unavailable');
    this.disconnectBackend();
    const target = {url: new URL('/api/attachments/storage/credentials', serviceUrl).href, token, controller: new AbortController(), attempts: 0, retries: 0};
    this.target = target;
    return this.enqueueRestore(target);
  }
  async sync(target = this.target) {
    if (!target || target !== this.target) return 'waiting_for_backend';
    target.attempts++;
    let entries;
    if (this.readError === 'io') this.readCredentialsFile();
    try {entries = await this.entries();}
    catch (error) {
      if (target !== this.target) return 'waiting_for_backend';
      this.state = error.message === errors.encryption ? 'encryption_unavailable' : 'storage_unavailable';
      if (this.state === 'encryption_unavailable' || this.readError === 'io') this.scheduleRetry(target);
      this.reportState();
      return this.state;
    }
    // The OS operation cannot be cancelled. A retired backend must never
    // receive a credential after a delayed decryption finishes.
    if (target !== this.target) return 'waiting_for_backend';
    try {
      const response = await this.fetcher(target.url, {
        method: 'POST', redirect: 'error', signal: AbortSignal.any([AbortSignal.timeout(10000), target.controller.signal]),
        headers: {Authorization: 'Bearer ' + target.token, 'Content-Type': 'application/json'},
        body: JSON.stringify({replace: true, entries, sync_sequence: ++this.syncSequence}),
      });
      // Never forward a server response/error body, which could echo a secret.
      if (response.body) await response.body.cancel().catch(() => {});
      if (!response.ok) throw new Error();
      if (target === this.target) {this.state = 'ready'; target.retries = 0; this.clearRetry();}
    } catch {
      if (target === this.target) {this.state = 'sync_failed'; this.scheduleRetry(target);}
    }
    if (target === this.target) this.reportState();
    return target === this.target ? this.state : 'waiting_for_backend';
  }
  save(input) {
    const id = inputId(input, true), password = input.password;
    return this.enqueue(async () => {
      const entries = await this.entries();
      entries[id] = {password, revision: randomUUID()};
      await this.write(entries);
      return {password_saved: true, state: await this.sync()};
    });
  }
  clear(input) {
    const id = inputId(input, false);
    return this.enqueue(async () => {
      const entries = await this.entries();
      if (Object.hasOwn(entries, id)) {
        delete entries[id];
        await this.write(entries);
      }
      return {password_saved: false, state: await this.sync()};
    });
  }
}

function registerAttachmentCredentialIpc(ipcMain, assertTrusted, secrets) {
  for (const [name, method] of [['attachment-credential-save', 'save'], ['attachment-credential-clear', 'clear']]) {
    ipcMain.handle('leafloom:' + name, (event, ...args) => {
      assertTrusted(event);
      if (args.length !== 1) throw new Error(errors.input);
      return secrets[method](args[0]);
    });
  }
  for (const [name, method] of [['attachment-credential-status', 'status'], ['attachment-credential-retry', 'retryRestore']]) {
    ipcMain.handle('leafloom:' + name, (event, ...args) => {
      assertTrusted(event);
      if (args.length !== 0) throw new Error(errors.input);
      return secrets[method]();
    });
  }
}

module.exports = {AttachmentSecrets, registerAttachmentCredentialIpc};
