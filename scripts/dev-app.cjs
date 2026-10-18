'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const {execFileSync} = require('node:child_process');

// Dock names come from the app bundle, not app.setName(). Keep the npm runtime
// untouched and reuse a branded copy until Electron or the logo changes.
function developmentExecutable(electron, root) {
  if (process.platform !== 'darwin') return electron;
  const source = path.resolve(electron, '../../..');
  const logo = path.join(root, 'assets/brand/logo.png');
  const fingerprint = createHash('sha256').update(JSON.stringify({
    schema: 2, source, executable: fs.statSync(electron).mtimeMs,
  })).update(fs.readFileSync(path.join(source, 'Contents/Info.plist')))
    .update(fs.readFileSync(logo)).digest('hex').slice(0, 20);
  const cache = path.join(root, '.cache/desktop-dev/apps');
  const target = path.join(cache, fingerprint);
  const executable = path.join(target, 'LeafLoom.app/Contents/MacOS/Electron');
  if (fs.existsSync(executable)) return executable;
  fs.mkdirSync(cache, {recursive: true});
  const staging = fs.mkdtempSync(path.join(cache, '.prepare-'));
  try {
    const bundle = path.join(staging, 'LeafLoom.app');
    execFileSync('/usr/bin/ditto', [source, bundle]);
    const plist = path.join(bundle, 'Contents/Info.plist');
    for (const key of ['CFBundleName', 'CFBundleDisplayName']) {
      execFileSync('/usr/bin/plutil', ['-replace', key, '-string', 'LeafLoom', plist]);
    }
    execFileSync('/usr/bin/plutil', ['-replace', 'CFBundleIdentifier', '-string', 'com.djhuang.leafloom.dev', plist]);
    execFileSync('/usr/bin/plutil', ['-replace', 'CFBundleIconFile', '-string', 'leafloom.icns', plist]);
    const icons = path.join(staging, 'leafloom.iconset');
    fs.mkdirSync(icons);
    for (const size of [16, 32, 128, 256, 512]) {
      for (const scale of [1, 2]) {
        execFileSync('/usr/bin/sips', ['-z', String(size * scale), String(size * scale), logo,
          '--out', path.join(icons, `icon_${size}x${size}${scale === 2 ? '@2x' : ''}.png`)], {stdio: 'pipe'});
      }
    }
    execFileSync('/usr/bin/iconutil', ['-c', 'icns', icons, '-o', path.join(bundle, 'Contents/Resources/leafloom.icns')]);
    fs.rmSync(icons, {recursive: true});
    // Sign the cached bundle and its nested helpers, preserving JIT entitlements.
    execFileSync('/usr/bin/codesign', ['--force', '--deep', '--preserve-metadata=entitlements', '--sign', '-', bundle], {stdio: 'pipe'});
    execFileSync('/usr/bin/codesign', ['--verify', '--deep', '--strict', bundle], {stdio: 'pipe'});
    try {fs.renameSync(staging, target);}
    catch (error) {if (!fs.existsSync(executable)) throw error;}
    return executable;
  } finally {fs.rmSync(staging, {recursive: true, force: true});}
}

module.exports = {developmentExecutable};
