'use strict';
const fs = require('node:fs');
const path = require('node:path');
const bundleFile = path.join(__dirname, 'resources/backend/bundle.json');
const bundle = fs.existsSync(bundleFile) ? JSON.parse(fs.readFileSync(bundleFile, 'utf8')) : {};
module.exports = {
  appId: 'com.djhuang.leafloom', productName: 'LeafLoom',
  electronDist: process.env.LEAFLOOM_ELECTRON_DIST || undefined,
  directories: {output: '../dist/desktop'},
  files: ['*.cjs', 'status.html', 'status.css', 'package.json', '!electron-builder.config.cjs'],
  asar: true,
  extraResources: [
    {from: 'resources/backend', to: 'backend', filter: ['**/*', '!**/__pycache__/**', '!**/*.pyc']},
    {from: '../assets/brand', to: 'brand', filter: ['*.png', '*.ico']},
    {from: '../LICENSE', to: 'LICENSE'}, {from: '../THIRD_PARTY_NOTICES.md', to: 'THIRD_PARTY_NOTICES.md'},
  ],
  beforePack: async () => {
    const fs = require('node:fs'); const path = require('node:path');
    const root = path.join(__dirname, 'resources/backend');
    const receipt = JSON.parse(fs.readFileSync(path.join(root, 'bundle.json'), 'utf8'));
    const expected = process.platform === 'win32' ? 'windows-x64' : 'macos-arm64';
    if (receipt.platform !== expected || receipt.version !== require('./package.json').version) throw new Error('Build the matching private backend first');
  },
  win: {target: [{target: 'nsis', arch: ['x64']}], icon: '../assets/brand/leafloom.ico', artifactName: 'LeafLoom-${version}-windows-${arch}-setup.${ext}'},
  nsis: {oneClick: false, perMachine: false, allowElevation: false, allowToChangeInstallationDirectory: true, createDesktopShortcut: true, deleteAppDataOnUninstall: false},
  mac: {target: [{target: 'dmg', arch: ['arm64']}], icon: 'resources/leafloom.icns', category: 'public.app-category.productivity', minimumSystemVersion: '14.0', hardenedRuntime: true,
    binaries: (bundle.mac_binaries || []).map(file => 'Contents/Resources/backend/python/' + file),
    entitlements: 'entitlements.mac.plist', entitlementsInherit: 'entitlements.mac.plist',
    artifactName: 'LeafLoom-${version}-macos-${arch}.${ext}', notarize: Boolean(process.env.APPLE_API_KEY || process.env.APPLE_ID)},
};
