'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {Readable, Transform} = require('node:stream');
const {pipeline} = require('node:stream/promises');

const API = 'https://api.github.com/repos/DJ-Huang/LeafLoom/releases/latest';
const RELEASE_ROOT = 'https://github.com/DJ-Huang/LeafLoom/releases/download/';
function version(value) {
  const match = /^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.exec(value);
  if (!match) throw new Error('update.error.release');
  return match.slice(1).map(Number);
}
function newer(latest, current) {
  const a = version(latest), b = version(current);
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] > b[i];
  return false;
}
function assetUrl(asset, tag) {
  const expected = RELEASE_ROOT + encodeURIComponent(tag) + '/' + encodeURIComponent(asset.name);
  if (asset.browser_download_url !== expected) throw new Error('update.error.release');
  return expected;
}
async function checksum(file) {
  const hash = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
  return hash.digest('hex');
}

class Updater {
  constructor({current, platform, arch, directory, packaged = true, fetcher = fetch}) {
    Object.assign(this, {current, platform, arch, directory, packaged, fetcher});
    this.state = {current, latest: '', phase: 'idle', received: 0, total: 0, error: ''};
  }
  status() {return {...this.state};}
  get busy() {return ['checking', 'downloading', 'verifying', 'installing'].includes(this.state.phase);}
  async response(url, timeout = 20000) {
    const response = await this.fetcher(url, {headers: {'User-Agent': 'LeafLoom/' + this.current, Accept: url === API ? 'application/vnd.github+json' : 'application/octet-stream'}, signal: AbortSignal.timeout(timeout)});
    if (!response.ok) throw new Error(response.status === 403 || response.status === 429 ? 'update.error.rate' : 'update.error.network');
    return response;
  }
  fail(error) {
    this.state.phase = 'error';
    this.state.error = /^update\.error\./.test(error.message) ? error.message : ['ENOSPC', 'EACCES', 'EPERM', 'EROFS'].includes(error.code) ? 'update.error.storage' : 'update.error.network';
    return this.status();
  }
  async check() {
    if (this.busy) return this.status();
    this.asset = null; this.file = null;
    Object.assign(this.state, {phase: 'checking', latest: '', received: 0, total: 0, error: ''});
    try {
      const release = await (await this.response(API)).json();
      if (release.draft || release.prerelease) throw new Error('update.error.release');
      version(release.tag_name);
      this.state.latest = release.tag_name.replace(/^v/, '');
      if (!newer(release.tag_name, this.current)) {this.state.phase = 'current'; return this.status();}
      const suffix = this.platform === 'win32' && this.arch === 'x64' ? 'windows-x64-setup.exe' : this.platform === 'darwin' && this.arch === 'arm64' ? 'macos-arm64.dmg' : '';
      if (!suffix) throw new Error('update.error.platform');
      const name = `LeafLoom-${this.state.latest}-${suffix}`;
      const asset = release.assets?.find(item => item.name === name);
      if (!asset || !Number.isSafeInteger(asset.size) || asset.size <= 0 || asset.size > 8 * 1024 ** 3) throw new Error('update.error.asset');
      const url = assetUrl(asset, release.tag_name);
      let digest = /^sha256:([a-f0-9]{64})$/i.exec(asset.digest || '')?.[1];
      if (!digest) {
        const sums = release.assets.find(item => item.name === 'SHA256SUMS.txt');
        if (!sums || sums.size > 65536) throw new Error('update.error.checksum');
        const content = await (await this.response(assetUrl(sums, release.tag_name))).text();
        digest = content.split(/\r?\n/).map(line => /^([a-f0-9]{64})\s+\*?(.+)$/i.exec(line)).find(match => match?.[2] === name)?.[1];
      }
      if (!digest) throw new Error('update.error.checksum');
      this.asset = {name, url, size: asset.size, digest: digest.toLowerCase()};
      Object.assign(this.state, {phase: this.packaged ? 'available' : 'development', total: asset.size});
    } catch (error) {this.fail(error);}
    return this.status();
  }
  download() {
    if (this.busy) return false;
    if (!this.packaged || !this.asset || !['available', 'error', 'ready'].includes(this.state.phase)) throw new Error('update.error.check');
    Object.assign(this.state, {phase: 'downloading', error: '', received: 0});
    return true;
  }
  async transfer() {
    let folder;
    try {
      await fs.promises.mkdir(this.directory, {recursive: true, mode: 0o700});
      folder = await fs.promises.mkdtemp(path.join(this.directory, 'update-'));
      const partial = path.join(folder, this.asset.name + '.partial');
      const response = await this.response(this.asset.url, 2 * 60 * 60 * 1000);
      const hash = crypto.createHash('sha256');
      const meter = new Transform({transform: (chunk, _, callback) => {
        this.state.received += chunk.length;
        if (this.state.received > this.asset.size) {callback(new Error('update.error.checksum')); return;}
        hash.update(chunk); callback(null, chunk);
      }});
      await pipeline(Readable.fromWeb(response.body), meter, fs.createWriteStream(partial, {flags: 'wx', mode: 0o600}));
      this.state.phase = 'verifying';
      if (this.state.received !== this.asset.size || hash.digest('hex') !== this.asset.digest) throw new Error('update.error.checksum');
      this.file = path.join(folder, this.asset.name);
      await fs.promises.rename(partial, this.file);
      this.state.phase = 'ready';
      return true;
    } catch (error) {
      this.file = null;
      if (folder) await fs.promises.rm(folder, {recursive: true, force: true}).catch(() => {});
      this.fail(error); return false;
    }
  }
  async installer() {
    if (this.state.phase !== 'ready' || !this.file) throw new Error('update.error.check');
    this.state.phase = 'verifying';
    try {
      if (await checksum(this.file) !== this.asset.digest) throw new Error('update.error.checksum');
      this.state.phase = 'installing';
      return this.file;
    } catch (error) {this.fail(error); throw error;}
  }
}
module.exports = {Updater, newer};
