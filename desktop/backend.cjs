'use strict';
const {EventEmitter} = require('node:events');
const {spawn} = require('node:child_process');
const {createInterface} = require('node:readline');
const fs = require('node:fs');
const path = require('node:path');
const {localUrl} = require('./policy.cjs');

class Backend extends EventEmitter {
  constructor({python, home, appPath, spawnProcess = spawn}) {
    super(); this.python = python; this.home = home; this.appPath = appPath;
    this.child = null; this.stopping = false; this.ready = null;
    this.spawnProcess = spawnProcess;
  }
  start() {
    if (this.child) throw new Error('Backend already running');
    this.stopping = false;
    const logs = path.join(this.home, 'logs'); fs.mkdirSync(logs, {recursive: true});
    const log = fs.openSync(path.join(logs, 'desktop-backend.log'), 'a');
    const env = {...process.env, VAULT_RAG_HOME: this.home, PYTHONUTF8: '1', PYTHONUNBUFFERED: '1', PYTHONDONTWRITEBYTECODE: '1', TOKENIZERS_PARALLELISM: 'false', NO_PROXY: '127.0.0.1,localhost', no_proxy: '127.0.0.1,localhost'};
    for (const key of ['PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'CONDA_PREFIX']) delete env[key];
    // Finder has a minimal PATH; include user CLI installs without invoking a shell.
    const home = require('node:os').homedir();
    const additions = process.platform === 'win32'
      ? [path.join(process.env.APPDATA || home, 'npm'), path.join(home, '.local', 'bin')]
      : [path.join(home, '.local', 'bin'), path.join(home, '.npm-global', 'bin'), '/opt/homebrew/bin', '/usr/local/bin'];
    const pathKey = Object.keys(env).find(key => key.toUpperCase() === 'PATH') || 'PATH';
    env[pathKey] = [...additions, env[pathKey] || ''].join(path.delimiter);
    try {
      this.child = this.spawnProcess(this.python, ['-I', '-B', '-X', 'utf8', '-m', 'vault_rag.desktop_entry'], {cwd: this.home, env, windowsHide: true, stdio: ['pipe', 'pipe', log]});
    } finally { fs.closeSync(log); }
    const child = this.child;
    child.stdin.on('error', () => {});
    const lines = createInterface({input: child.stdout});
    lines.on('line', line => {
      let value; try { value = JSON.parse(line); } catch { return; }
      if (value.type === 'ready') {
        if (!localUrl(value.url)) { this.emit('failure', new Error('Invalid backend address')); void this.stop(); return; }
        this.ready = value; this.emit('ready', value);
      } else if (value.type === 'error') this.emit('failure', new Error(value.message));
      else if (value.type === 'committed') this.emit('committed');
    });
    child.once('error', error => this.emit('failure', error));
    child.once('close', (code, signal) => {
      lines.close(); this.child = null; this.ready = null;
      this.emit('exit', {code, signal, expected: this.stopping});
    });
  }
  send(type) {
    if (!this.child || this.child.stdin.destroyed) throw new Error('Backend unavailable');
    this.child.stdin.write(JSON.stringify({type}) + '\n');
  }
  async stop() {
    const child = this.child; if (!child) return;
    this.stopping = true;
    await new Promise(resolve => {
      const timer = setTimeout(() => {
        // Only our child PID. Python EOF supervises its owned AI process trees.
        child.kill();
      }, 30000);
      const force = setTimeout(() => { child.kill('SIGKILL'); }, 35000);
      child.once('close', () => { clearTimeout(timer); clearTimeout(force); resolve(); });
      try { this.send('shutdown'); child.stdin.end(); } catch { child.kill(); }
    });
  }
}
module.exports = {Backend};
