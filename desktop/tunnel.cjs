'use strict';
const fs = require('node:fs');
const path = require('node:path');

// The renderer never receives the stored ciphertext or the decrypted key.
class TunnelSettings {
  constructor(home, safeStorage) {
    this.file = path.join(home, 'desktop-tunnel.json');
    this.storage = safeStorage;
    this.state = {state: 'unconfigured', error: ''};
    this.error = '';
    try {
      this.value = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      if (!this.value || this.value.schema !== 1 || typeof this.value.tunnelId !== 'string' || typeof this.value.enabled !== 'boolean' || (this.value.encryptedKey !== undefined && typeof this.value.encryptedKey !== 'string')) throw new Error('Invalid settings');
      this.state.state = this.value.enabled ? 'waiting' : this.value.tunnelId ? 'disabled' : 'unconfigured';
    }
    catch (error) {
      this.value = {tunnelId: '', enabled: false};
      if (error.code !== 'ENOENT') this.error = 'tunnel.error.storage';
    }
  }
  status() {
    return {tunnelId: this.value.tunnelId || '', enabled: Boolean(this.value.enabled),
      keySaved: Boolean(this.value.encryptedKey), ...this.state,
      ...(!this.value.tunnelId && this.state.state === 'disabled' ? {state: 'unconfigured'} : {}),
      ...(this.error ? {state: 'failed', error: this.error} : {})};
  }
  write(value) {
    const temp = this.file + '.tmp';
    try {
      fs.writeFileSync(temp, JSON.stringify(value), {mode: 0o600});
      fs.renameSync(temp, this.file);
      this.value = value; this.error = '';
    } catch { throw new Error('tunnel.error.storage'); }
    finally { if (fs.existsSync(temp)) fs.unlinkSync(temp); }
  }
  save(input) {
    if (!input || typeof input.tunnelId !== 'string' || !/^tunnel_[a-zA-Z0-9_-]{1,120}$/.test(input.tunnelId.trim()) || typeof input.enabled !== 'boolean') throw new Error('tunnel.error.config');
    if (input.appKey !== undefined && (typeof input.appKey !== 'string' || input.appKey.length > 4096 || /[\r\n\0]/.test(input.appKey))) throw new Error('tunnel.error.key');
    let encryptedKey = this.value.encryptedKey;
    if (input.appKey?.trim()) {
      if (!this.storage.isEncryptionAvailable()) throw new Error('tunnel.error.encryption');
      try { encryptedKey = this.storage.encryptString(input.appKey.trim()).toString('base64'); }
      catch { throw new Error('tunnel.error.encryption'); }
    }
    if (input.enabled && !encryptedKey) throw new Error('tunnel.error.key');
    this.write({schema: 1, tunnelId: input.tunnelId.trim(), enabled: input.enabled, encryptedKey});
    return this.status();
  }
  command(binary) {
    if (!this.value.enabled) return {enabled: false};
    try {
      if (!this.storage.isEncryptionAvailable()) throw new Error();
      const apiKey = this.storage.decryptString(Buffer.from(this.value.encryptedKey, 'base64'));
      if (!apiKey) throw new Error();
      this.error = '';
      return {enabled: true, binary, tunnelId: this.value.tunnelId, apiKey};
    } catch { this.error = 'tunnel.error.encryption'; return {enabled: false}; }
  }
  disable() { this.write({...this.value, enabled: false}); this.state = {state: 'disabled', error: ''}; return this.status(); }
  clear() { this.write({schema: 1, tunnelId: '', enabled: false}); this.state = {state: 'unconfigured', error: ''}; return this.status(); }
}
module.exports = {TunnelSettings};
