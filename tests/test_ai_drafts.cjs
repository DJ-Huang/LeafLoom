// Exercise the real document state module with deterministic storage, timers and file API.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('../web/node_modules/typescript');
const original = fs.readFileSync('web/src/document-state.ts', 'utf8').replace("import {api,Note} from './api';", 'type Note=any; const api=globalThis.__test.api;');
const javascript = ts.transpileModule(original, {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
const historyJavascript=ts.transpileModule(fs.readFileSync('web/src/edit-history.ts','utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
const storage = new Map();
const timers = new Map();
let timerId = 0, writes = 0, disk = {text:'原文',etag:'v1',path:'a.md'}, pendingWrite;
const root = 'test-vault';
function moduleInstance() {
 const historyModule={exports:{}};vm.runInNewContext(historyJavascript,historyModule);
 const sandbox = {exports:{},setTimeout:fn=>{const id=++timerId;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id),
  require:name=>{assert.equal(name,'./edit-history');return historyModule.exports;},
  localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
  window:{addEventListener:()=>{}},__test:{api:async(path,body,method)=>{
   if(method==='PUT') {writes++;if(pendingWrite)await pendingWrite;if(body.etag!==disk.etag)throw Object.assign(new Error('外部修改'),{conflict:true});disk={...disk,text:body.text,etag:'v'+writes};}
   return {...disk};
  }}};
 vm.runInNewContext(javascript,sandbox);return sandbox.exports;
}
async function flushTimers(){const callbacks=[...timers.values()];timers.clear();for(const fn of callbacks)fn();await new Promise(resolve=>setImmediate(resolve));}
(async()=>{
 let state=moduleInstance(),doc=state.documentState(root,'a.md');await state.loadDocument(doc);
 state.changeDocument(doc,'人工编辑');assert.equal(timers.size,1);await flushTimers();assert.equal(writes,1);assert.equal(disk.text,'人工编辑');
 state.applyAiChange(doc,doc.text,doc.text,doc.etag);assert(!doc.manualSave);assert(!doc.dirty);
 state.applyAiChange(doc,'人工编辑','AI 修改',doc.etag);assert.equal(timers.size,0);assert.equal(writes,1);assert(doc.manualSave);
 state.changeDocument(doc,'AI 修改后继续编辑');await flushTimers();assert.equal(writes,1);assert.equal(disk.text,'人工编辑');
 assert(state.travelDocument(doc,'undo'));assert.equal(doc.text,'AI 修改');assert(doc.manualSave);await flushTimers();assert.equal(writes,1);
 assert(state.travelDocument(doc,'redo'));assert.equal(doc.text,'AI 修改后继续编辑');await flushTimers();assert.equal(writes,1);
 state=moduleInstance();doc=state.documentState(root,'a.md');await state.loadDocument(doc);assert(doc.manualSave);assert.equal(doc.text,'AI 修改后继续编辑');
 await state.saveDocument(doc,false);assert.equal(writes,1,'automatic saves must not publish AI drafts');
 await state.saveDocument(doc);assert.equal(writes,2);assert.equal(disk.text,'AI 修改后继续编辑');assert(!doc.manualSave);
 state.applyAiChange(doc,doc.text,'第二次 AI 修改',doc.etag);disk={...disk,text:'外部修改',etag:'external'};
 await state.saveDocument(doc);assert(doc.manualSave);assert(doc.dirty);assert.equal(doc.text,'第二次 AI 修改');assert.equal(disk.text,'外部修改');
 assert.throws(()=>state.applyAiChange(doc,'旧内容','错误替换',doc.etag));
 await state.discardAiDraft(doc);assert.equal(doc.text,'外部修改');assert(!doc.manualSave);assert(!doc.dirty);
 assert.equal(state.travelDocument(doc,'undo'),false);
 // Editing while an explicit save is in flight must leave the newer AI draft manual.
 state.applyAiChange(doc,doc.text,'准备保存',doc.etag);let finish;pendingWrite=new Promise(resolve=>finish=resolve);
 const saving=state.saveDocument(doc);state.changeDocument(doc,'保存期间的新修改');finish();await saving;pendingWrite=undefined;
 assert(doc.manualSave);assert(doc.dirty);assert.equal(timers.size,0);assert.equal(doc.text,'保存期间的新修改');
 console.log('AI draft tests passed: normal autosave, manual AI edits, refresh, conflicts, discard and in-flight edits.');
})().catch(error=>{console.error(error);process.exitCode=1;});
