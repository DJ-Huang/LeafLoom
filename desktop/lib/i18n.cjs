'use strict';
const fs = require('node:fs');
const path = require('node:path');
function resolveLocale(value) {
  value = String(value || 'en').toLowerCase();
  return value.startsWith('zh') ? 'zh-CN' : value.startsWith('ja') ? 'ja' : 'en';
}
function createTranslator(home, catalogues, systemLocale) {
  const loaded = new Map();
  return message => {
    let preference = 'auto';
    try { preference = JSON.parse(fs.readFileSync(path.join(home, 'preferences.json'), 'utf8')).locale || 'auto'; } catch {}
    const language = resolveLocale(preference === 'auto' ? systemLocale() : preference);
    if (!loaded.has(language)) loaded.set(language, JSON.parse(fs.readFileSync(path.join(catalogues, language + '.json'), 'utf8')));
    return loaded.get(language)[message] || message;
  };
}
module.exports = {createTranslator, resolveLocale};
