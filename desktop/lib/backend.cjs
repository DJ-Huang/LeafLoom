'use strict';
const {spawn, execFile} = require('node:child_process');
const {EventEmitter, once} = require('node:events');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {cliPath} = require('./environment.cjs');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

class Backend extends EventEmitter {
  constructor({executable, home, version}) {
    super(); Object.assign(this, {executable, home, version});
    this.child = null; this.restarts = 0; this.stopping = false; this.starting = null;
    this.origin = `http://127.0.0.1:${this.config().port || 18080}`;
  }
  config() { const file = path.join(this.home, 'config.json'); return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : {port: 18080}; }
  env() { return {...process.env, PATH: cliPath(), VAULT_RAG_HOME: this.home, PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1', TOKENIZERS_PARALLELISM: 'false', NO_PROXY: '127.0.0.1,localhost', no_proxy: '127.0.0.1,localhost'}; }
  run(action) {
    return new Promise((resolve, reject) => execFile(this.executable, [action, '--home', this.home],
      {cwd: this.home, env: this.env(), windowsHide: true, timeout: action === 'migrate-legacy' ? 420000 : 180000, maxBuffer: 2 * 1024 * 1024},
      (error, stdout, stderr) => {
        if (error) return reject(new Error(stderr.trim() || error.message));
        try { resolve(JSON.parse(stdout.trim().split('\n').at(-1))); } catch { reject(new Error('后台返回了无法识别的状态')); }
      }));
  }
  async status() {
    const token = fs.readFileSync(path.join(this.home, 'auth-token'), 'utf8').trim();
    const response = await fetch(this.origin + '/api/status', {headers: {Authorization: 'Bearer ' + token}, signal: AbortSignal.timeout(2000)});
    if (!response.ok) throw new Error('配置端口被其他服务占用');
    return response.json();
  }
  start() {
    if (this.starting) return this.starting;
    this.starting = this.launch().finally(() => { this.starting = null; });
    return this.starting;
  }
  async launch() {
    if (this.child) throw new Error('后台已启动');
    this.stopping = false;
    const owner = crypto.randomUUID();
    const logdir = path.join(this.home, 'logs'); fs.mkdirSync(logdir, {recursive: true});
    const logfile = path.join(logdir, 'desktop-process.log');
    if (fs.existsSync(logfile) && fs.statSync(logfile).size > 5_000_000) fs.renameSync(logfile, logfile + '.previous');
    const log = fs.createWriteStream(logfile, {flags: 'a'});
    const child = spawn(this.executable, ['serve', '--home', this.home], {cwd: this.home,
      env: {...this.env(), VAULT_RAG_DESKTOP_OWNER: owner}, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe']});
    this.child = child;
    let exited = false; let failure;
    child.stdout.pipe(log, {end: false}); child.stderr.pipe(log, {end: false});
    child.stdin.on('error', () => {});
    child.once('error', error => { failure = error; });
    child.once('close', (code) => {
      exited = true; log.end(); if (this.child === child) this.child = null;
      if (!this.stopping) this.emit('crash', failure || new Error(`后台已退出（${code}），请查看日志`));
    });
    const deadline = Date.now() + 90000;
    let lastError;
    while (Date.now() < deadline && !exited) {
      try {
        const status = await this.status();
        if (status.distribution !== 'desktop' || status.app_version !== this.version ||
            status.desktop_protocol_version !== 1 || status.desktop_instance_id !== owner) {
          this.stopping = true; child.stdin.end('{"command":"shutdown"}\n');
          throw new Error('配置端口已被另一实例占用，未连接或停止该实例');
        }
        this.emit('ready', status); return status;
      } catch (error) {
        lastError = error;
        if (this.stopping) throw error;
      }
      await delay(250);
    }
    this.stopping = true;
    if (!exited) child.stdin.end('{"command":"shutdown"}\n');
    throw failure || lastError || new Error('后台未能就绪，请查看日志');
  }
  async restartAfterCrash() {
    if (this.restarts >= 3) throw new Error('后台连续异常退出，已停止自动重试，请查看日志');
    this.restarts++; await delay(1000); return this.start();
  }
  async stop() {
    this.stopping = true;
    const child = this.child;
    if (!child) return;
    // Only signal our own process through its inherited pipe. Never kill a PID.
    const closed = once(child, 'close');
    child.stdin.end('{"command":"shutdown"}\n');
    let timer;
    try { await Promise.race([closed, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('后台仍在收尾，尚未退出；请稍后重试，未强制终止')), 60000);
    })]); } finally { clearTimeout(timer); }
  }
}
module.exports = {Backend};
