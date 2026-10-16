'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {resolveStateHome} = require('../state-home.cjs');
const {reuseLegacyModels} = require('../../scripts/dev-state.cjs');

function fixture(work) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'leafloom-shared-data-'));
  try {return work(root);} finally {
    assert.equal(path.dirname(fs.realpathSync(root)), fs.realpathSync(os.tmpdir()));
    fs.rmSync(root, {recursive: true, force: true});
  }
}
function write(file, value) {fs.mkdirSync(path.dirname(file), {recursive: true});fs.writeFileSync(file, value);}

test('source and packaged launchers resolve the same platform user data directory', () => fixture(root => {
  const env = {LOCALAPPDATA: path.join(root, 'local')}, userHome = path.join(root, 'user');
  assert.equal(resolveStateHome({env, argv: [], platform: 'win32', userHome}).home, path.join(env.LOCALAPPDATA, 'VaultRag'));
  assert.equal(resolveStateHome({env: {}, argv: [], platform: 'darwin', userHome}).home, path.join(userHome, 'Library', 'Application Support', 'VaultRag'));
  assert.equal(fs.existsSync(userHome), false);
}));

test('registered installation location, explicit home and environment retain precedence', () => fixture(root => {
  const registrationHome = path.join(root, 'registration'), installed = path.join(root, 'installed');
  const env = {LEAFLOOM_REGISTRATION_HOME: registrationHome};
  write(path.join(registrationHome, 'desktop-current-home.json'), JSON.stringify({schema: 1, home: installed}));
  write(path.join(installed, 'desktop-install.json'), '{}');
  assert.equal(resolveStateHome({env, argv: []}).home, installed);
  const custom = path.join(root, 'custom'), argument = path.join(root, 'argument');
  assert.equal(resolveStateHome({env: {...env, VAULT_RAG_HOME: custom}, argv: []}).home, custom);
  assert.equal(resolveStateHome({env: {...env, VAULT_RAG_HOME: custom}, argv: ['--home', argument]}).home, argument);
  assert.throws(() => resolveStateHome({env, argv: ['--home', 'relative']}), /absolute/);
  fs.unlinkSync(path.join(installed, 'desktop-install.json'));
  assert.notEqual(resolveStateHome({env, argv: []}).home, installed);
}));

test('reusing old Dev models preserves installed config, credentials and legacy originals', () => fixture(root => {
  const legacy = path.join(root, 'legacy'), home = path.join(root, 'app');
  write(path.join(legacy, 'models', 'model-lock.json'), '{"revision":"fixture"}');
  write(path.join(legacy, 'models', 'bge-m3', 'model.safetensors'), 'fixture weights');
  write(path.join(legacy, 'models', 'bge-m3', '.cache', 'download', 'partial'), 'partial');
  write(path.join(legacy, 'config.json'), 'old dev config');
  write(path.join(home, 'config.json'), 'installed config');
  write(path.join(home, 'auth-token'), 'installed fixture credential');
  assert.equal(reuseLegacyModels(legacy, home, () => {}), true);
  assert.equal(fs.readFileSync(path.join(home, 'config.json'), 'utf8'), 'installed config');
  assert.equal(fs.readFileSync(path.join(home, 'auth-token'), 'utf8'), 'installed fixture credential');
  assert.equal(fs.readFileSync(path.join(home, 'models', 'bge-m3', 'model.safetensors'), 'utf8'), 'fixture weights');
  assert.equal(fs.existsSync(path.join(home, 'models', 'bge-m3', '.cache')), false);
  assert.equal(fs.existsSync(path.join(legacy, 'models', 'bge-m3', 'model.safetensors')), true);
  assert.equal(reuseLegacyModels(legacy, home, () => {}), false);
  assert.equal(fs.readdirSync(home).some(name => name.startsWith('.model-import-')), false);
}));

test('existing model directories and overlapping source/target paths are never replaced', () => fixture(root => {
  const legacy = path.join(root, 'legacy'), home = path.join(root, 'app');
  write(path.join(legacy, 'models', 'model-lock.json'), '{}');
  write(path.join(home, 'models', 'model-lock.json'), 'installed model');
  assert.equal(reuseLegacyModels(legacy, home, () => {}), false);
  assert.equal(fs.readFileSync(path.join(home, 'models', 'model-lock.json'), 'utf8'), 'installed model');
  assert.equal(reuseLegacyModels(legacy, path.join(legacy, 'models', 'nested'), () => {}), false);
  assert.equal(fs.existsSync(path.join(legacy, 'models', 'nested')), false);
}));

test('a failed copy leaves the destination unpublished and the source intact', () => fixture(root => {
  const legacy = path.join(root, 'legacy'), home = path.join(root, 'app');
  write(path.join(legacy, 'models', 'model-lock.json'), '{}');
  const original = fs.cpSync;
  fs.cpSync = (source, staging) => {write(path.join(staging, 'partial'), 'fixture');throw new Error('fixture disk full');};
  try {assert.throws(() => reuseLegacyModels(legacy, home, () => {}), /disk full/);} finally {fs.cpSync = original;}
  assert.equal(fs.existsSync(path.join(home, 'models')), false);
  assert.equal(fs.existsSync(path.join(legacy, 'models', 'model-lock.json')), true);
  assert.deepEqual(fs.readdirSync(home), []);
}));
