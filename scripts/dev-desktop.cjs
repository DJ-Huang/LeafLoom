'use strict';
// Own Vite and Electron in one terminal. Electron owns its Python sidecar.
const fs = require('node:fs');
const path = require('node:path');
const {spawn, spawnSync} = require('node:child_process');
const {pathToFileURL} = require('node:url');
const {resolveStateHome} = require('../desktop/state-home.cjs');
const {reuseLegacyModels} = require('./dev-state.cjs');
const {developmentExecutable} = require('./dev-app.cjs');
const {consumeDevelopmentRestart} = require('../desktop/restart.cjs');
const {randomUUID} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const {home, registrationHome} = resolveStateHome();
const legacyHome = path.join(root, '.cache', 'desktop-dev');
const environment = path.join(legacyHome, '.venv');
const python = path.join(environment, process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const uvEnvironment = {...process.env, UV_CACHE_DIR: path.join(root, '.cache', 'uv'), UV_PROJECT_ENVIRONMENT: environment};

function run(command, args, cwd = root) {
  const result = spawnSync(command, args, {cwd, env: uvEnvironment, stdio: 'inherit', windowsHide: true});
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} failed (${result.status})`);
}
function npmInstall(directory) {
  if (fs.existsSync(path.join(root, directory, 'node_modules', directory === 'web' ? 'vite' : 'electron', 'package.json'))) return;
  // npm.cmd needs cmd.exe on Windows; no user-controlled command text.
  if (process.platform === 'win32') run(process.env.ComSpec || 'cmd.exe', ['/d', '/s', '/c', 'npm ci'], path.join(root, directory));
  else run('npm', ['ci'], path.join(root, directory));
}

async function main() {
  // Hatch's wheel metadata includes this directory even in editable mode.
  // A fresh checkout needs the directory, but no built frontend files.
  fs.mkdirSync(path.join(root, 'vault_rag', 'static'), {recursive: true});
  // uv sync installs the project editable, updates changed locked dependencies,
  // and only touches this launcher's dedicated environment.
  run('uv', ['sync', '--locked', '--python', '3.12']);
  // An editable install is necessary: the desktop starts Python with -I.
  const sourceCheck = spawnSync(python, ['-I', '-c',
    'import sys; from pathlib import Path; import vault_rag; sys.exit(Path(vault_rag.__file__).resolve().parent != Path(sys.argv[1]).resolve())', path.join(root, 'vault_rag')], {stdio: 'ignore', windowsHide: true});
  if (sourceCheck.status !== 0) run('uv', ['pip', 'install', '--python', python, '--no-deps', '-e', '.']);
  npmInstall('web'); npmInstall('desktop');
  reuseLegacyModels(legacyHome, home);
  const {createServer} = await import(pathToFileURL(path.join(root, 'web/node_modules/vite/dist/node/index.js')).href);
  const vite = await createServer({root: path.join(root, 'web'), server: {
    host: '127.0.0.1', port: 5173, strictPort: true,
    hmr: {host: '127.0.0.1', protocol: 'ws', clientPort: 5173},
  }});
  let child, stopping = false;
  const restartFile = path.join(legacyHome, 'restart-' + process.pid + '-' + randomUUID());
  try {
    await vite.listen();
    let electron;
    const env = {...process.env, LEAFLOOM_PYTHON: python, VAULT_RAG_HOME: home,
      LEAFLOOM_REGISTRATION_HOME: registrationHome, LEAFLOOM_DEV_SERVER: 'http://127.0.0.1:5173',
      LEAFLOOM_DEV_RESTART_FILE: restartFile};
    delete env.ELECTRON_RUN_AS_NODE;
    console.log(`\nLeafLoom development | shared app data: ${home}\nUses the installed app's settings, models and credentials. Quit the running app before switching modes.\nFrontend edits update automatically. Use Restart LeafLoom after backend or desktop edits; Quit stops Dev.\n`);
    // Ask Electron to quit normally so pending edits and the sidecar can settle.
    const quit = () => {
      stopping = true;
      if (!child || child.exitCode !== null) return;
      const request = spawn(electron, [path.join(root, 'desktop'), '--quit'], {cwd: root, env, stdio: 'ignore', windowsHide: true});
      request.on('error', error => console.error(error.message));
    };
    process.on('SIGINT', quit); process.on('SIGTERM', quit);
    try {
      let restarting = false;
      while (true) {
        if (restarting) run('uv', ['sync', '--locked', '--python', '3.12']);
        if (stopping) {process.exitCode = 0; break;}
        electron = developmentExecutable(require(path.join(root, 'desktop/node_modules/electron')), root);
        child = spawn(electron, [path.join(root, 'desktop')], {cwd: root, env, stdio: 'inherit', windowsHide: true});
        const code = await new Promise((resolve, reject) => {child.once('error', reject); child.once('exit', code => resolve(code ?? 1));});
        if (!consumeDevelopmentRestart(restartFile, code) || stopping) {process.exitCode = code; break;}
        restarting = true;
        console.log('Restarting LeafLoom with the current source…');
      }
    } finally {process.off('SIGINT', quit); process.off('SIGTERM', quit);}
  } finally {fs.rmSync(restartFile, {force: true}); await vite.close();}
}
main().catch(error => {console.error(error.message); process.exitCode = 1;});
