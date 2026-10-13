'use strict';
// Used only by the release workflow's explicit signing mode. Secrets stay in CI.
const base = require('./package.json').build;
module.exports = {...base, forceCodeSigning: true, mac: {...base.mac,
  identity: process.env.MAC_SIGNING_IDENTITY || undefined, hardenedRuntime: true, notarize: true}};
