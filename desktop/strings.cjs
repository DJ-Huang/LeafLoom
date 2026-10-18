'use strict';
const strings = {
  en: {open: 'Open LeafLoom', login: 'Open at login', logs: 'Open logs folder', quit: 'Quit', starting: 'Starting your local workspace…', offline: 'Reading and editing do not require a model download.', failed: 'Unable to open workspace', retry: 'Retry', retrying: 'Retrying…', unsaved: 'Unsaved changes', unsavedDetail: 'Return to save your changes, or exit keeping local note drafts for next launch. Unsaved settings will be discarded.', back: 'Return', exit: 'Exit'},
  'zh-CN': {open: '打开 LeafLoom', login: '登录时启动', logs: '打开日志文件夹', quit: '退出', starting: '正在打开本地知识库…', offline: '阅读和编辑无需下载模型。', failed: '打开知识库失败', retry: '重试', retrying: '正在重试…', unsaved: '还有未保存的内容', unsavedDetail: '返回保存，或保留本地笔记草稿后退出；未保存的设置将被丢弃。', back: '返回', exit: '退出'},
  ja: {open: 'LeafLoom を開く', login: 'ログイン時に起動', logs: 'ログフォルダーを開く', quit: '終了', starting: 'ローカルワークスペースを開いています…', offline: '閲覧と編集にモデルのダウンロードは不要です。', failed: 'ワークスペースを開けませんでした', retry: '再試行', retrying: '再試行中…', unsaved: '未保存の変更があります', unsavedDetail: '戻って保存するか、ローカルのメモの下書きを残して終了します。未保存の設定は破棄されます。', back: '戻る', exit: '終了'},
};
const menuMessages = require('./menu-messages.cjs');
for (const [language, table] of Object.entries(strings)) Object.assign(table, menuMessages[language]);
module.exports = {strings, resolve: value => String(value).toLowerCase().startsWith('zh') ? 'zh-CN' : String(value).toLowerCase().startsWith('ja') ? 'ja' : 'en'};
