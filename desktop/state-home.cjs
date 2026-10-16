'use strict';
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

function resolveStateHome({env = process.env, argv = process.argv, platform = process.platform, userHome = os.homedir()} = {}) {
  const defaultHome = platform === 'win32'
    ? path.join(env.LOCALAPPDATA || path.join(userHome, 'AppData', 'Local'), 'VaultRag')
    : path.join(userHome, 'Library', 'Application Support', 'VaultRag');
  const registrationHome = env.LEAFLOOM_REGISTRATION_HOME || defaultHome;
  let savedHome;
  try {
    const registered = JSON.parse(fs.readFileSync(path.join(registrationHome, 'desktop-current-home.json'), 'utf8'));
    if (registered?.schema === 1 && typeof registered.home === 'string' && path.isAbsolute(registered.home) && fs.existsSync(path.join(registered.home, 'desktop-install.json'))) savedHome = registered.home;
  } catch {}
  const homeArgument = argv.indexOf('--home');
  if (homeArgument >= 0 && (!argv[homeArgument + 1] || !path.isAbsolute(argv[homeArgument + 1]))) throw new Error('--home requires an absolute state directory');
  const home = path.resolve((homeArgument >= 0 && argv[homeArgument + 1]) || env.VAULT_RAG_HOME || savedHome || defaultHome);
  return {home, registrationHome};
}

module.exports = {resolveStateHome};
