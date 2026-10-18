'use strict';
const fs = require('node:fs');

function restartArguments(argv, home) {
  const args = [];
  for (let index = 1; index < argv.length; index++) {
    const value = argv[index];
    if (value === '--home') {index++; continue;}
    if (value === '--quit' || value === '--background') continue;
    args.push(value);
  }
  return [...args, '--home', home];
}

// Called only from will-quit, after the renderer permits closing and the owned
// backend has stopped. The development supervisor keeps Vite alive until then.
function restartApplication(app, home, {argv = process.argv, env = process.env} = {}) {
  if (!app.isPackaged && env.LEAFLOOM_DEV_RESTART_FILE) {
    fs.writeFileSync(env.LEAFLOOM_DEV_RESTART_FILE, 'restart', {mode: 0o600});
  } else {
    app.relaunch({args: restartArguments(argv, home)});
  }
}

function consumeDevelopmentRestart(file, exitCode) {
  let requested = false;
  try {requested = fs.readFileSync(file, 'utf8') === 'restart';}
  catch (error) {if (error.code !== 'ENOENT') throw error;}
  finally {fs.rmSync(file, {force: true});}
  // An ordinary exit, crash, or killed child never becomes a restart loop.
  return requested && exitCode === 0;
}

module.exports = {restartApplication, restartArguments, consumeDevelopmentRestart};
