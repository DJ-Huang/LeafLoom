'use strict';
const path = require('node:path');
const os = require('node:os');
// Finder/Explorer do not necessarily inherit a terminal's CLI installation paths.
// Add known locations without sourcing shell startup files or changing system PATH.
function cliPath(env = process.env, platform = process.platform, home = os.homedir()) {
  const extra = platform === 'win32'
    ? [env.APPDATA && path.join(env.APPDATA, 'npm'), env.LOCALAPPDATA && path.join(env.LOCALAPPDATA, 'Microsoft/WinGet/Links'), path.join(home, '.local/bin')]
    : ['/opt/homebrew/bin', '/usr/local/bin', path.join(home, '.local/bin'), path.join(home, '.npm-global/bin')];
  return [...new Set([...(env.PATH || '').split(path.delimiter), ...extra].filter(Boolean))].join(path.delimiter);
}
module.exports = {cliPath};
