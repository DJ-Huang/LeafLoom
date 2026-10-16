'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {randomUUID} = require('node:crypto');

// Adopt a complete model directory as a unit; never merge revisions or replace
// installed settings/credentials. Keep the original Dev data for recovery.
function reuseLegacyModels(legacyHome, home, report = console.log) {
  const source = path.resolve(legacyHome, 'models'), target = path.resolve(home, 'models');
  const relative = path.relative(source, target);
  if (relative === '' || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative))) return false;
  if (source === target || !fs.existsSync(path.join(source, 'model-lock.json')) || fs.existsSync(target)) return false;
  const state = path.resolve(home);
  fs.mkdirSync(state, {recursive: true, mode: 0o700});
  const staging = path.join(state, '.model-import-' + randomUUID());
  report('Reusing model files from the previous Dev directory…');
  try {
    fs.cpSync(source, staging, {recursive: true, force: false, errorOnExist: true,
      filter: candidate => {
        if (fs.lstatSync(candidate).isSymbolicLink()) throw new Error('Model import cannot follow symbolic links: ' + candidate);
        return !path.relative(source, candidate).split(path.sep).includes('.cache');
      }});
    // Another instance may have prepared its own directory while we copied.
    if (fs.existsSync(target)) return false;
    fs.renameSync(staging, target);
    return true;
  } finally {
    if (path.dirname(staging) === state && path.basename(staging).startsWith('.model-import-')) fs.rmSync(staging, {recursive: true, force: true});
  }
}

module.exports = {reuseLegacyModels};
