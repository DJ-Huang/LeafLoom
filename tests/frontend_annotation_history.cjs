// Real shared document state/history with an isolated annotation API and deferred writes.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const ts=require('../web/node_modules/typescript');
const compile=source=>ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
const history={exports:{}};vm.runInNewContext(compile(fs.readFileSync('web/src/edit-history.ts','utf8')),history);
const source=fs.readFileSync('web/src/document-state.ts','utf8').replace("import {api,Note} from './api';",'type Note=any;const api=globalThis.__api;');
const storage=new Map(),calls=[],active=new Set();let count=0,delay,failWrite=false,failReplay=false;
const sandbox={exports:{},setTimeout:()=>1,clearTimeout:()=>{},window:{addEventListener:()=>{}},
 localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
 require:name=>{assert.equal(name,'./edit-history');return history.exports;},
 __api:async(endpoint,body,method)=>{
  calls.push({endpoint,body,method});
  if(endpoint==='annotations/history'){
   if(failReplay)throw Error('Concurrent annotation change');
   if(delay)await delay;
   if(body.direction==='undo')active.delete(body.history_id);else active.add(body.history_id);
   return {ok:true};
  }
  if(endpoint.startsWith('annotations')){
   if(delay)await delay;if(failWrite)throw Error('Write failed');
   const id='action-'+(++count);active.add(id);return {history_id:id};
  }
  return {text:'Original',etag:'v1',path:'note.md',root:'fixture'};
 }};
vm.runInNewContext(compile(source),sandbox);
const s=sandbox.exports;
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const travel=async(doc,direction)=>{assert.equal(s.travelDocument(doc,direction),true);await flush();};
(async()=>{
 const doc=s.documentState('fixture','note.md');await s.loadDocument(doc);
 s.changeDocument(doc,'Before highlight');
 const created=await s.changeAnnotation(doc,'annotations',{type:'highlight'});
 s.changeDocument(doc,'After highlight');
 await travel(doc,'undo');assert.equal(doc.text,'Before highlight');assert(active.has(created.history_id));
 await travel(doc,'undo');assert.equal(doc.text,'Before highlight');assert(!active.has(created.history_id));
 await travel(doc,'undo');assert.equal(doc.text,'Original');
 await travel(doc,'redo');await travel(doc,'redo');await travel(doc,'redo');
 assert.equal(doc.text,'After highlight');assert(active.has(created.history_id));
 assert.equal(s.documentState('fixture','note.md'),doc,'tab/mode switches keep the shared session');
 assert.equal(s.documentHistory(s.documentState('other-vault','note.md')).undo.length,0);
 // An async annotation reserves its place before later text edits.
 let finish;delay=new Promise(resolve=>finish=resolve);
 const writing=s.changeAnnotation(doc,'annotations',{type:'comment'});
 s.changeDocument(doc,'Typed while annotation pending');finish();await writing;delay=undefined;
 await travel(doc,'undo');assert.equal(doc.text,'After highlight');
 const top=s.documentHistory(doc).undo.at(-1);
 failReplay=true;await travel(doc,'undo');assert.equal(s.documentHistory(doc).undo.at(-1),top);
 assert.equal(doc.annotationError,'Concurrent annotation change');assert.equal(doc.text,'After highlight');
 failReplay=false;await travel(doc,'undo');assert.equal(doc.annotationError,'');
 const redoLength=s.documentHistory(doc).redo.length;
 failWrite=true;await assert.rejects(s.changeAnnotation(doc,'annotations',{}),/Write failed/);failWrite=false;
 assert.equal(s.documentHistory(doc).redo.length,redoLength,'failed writes preserve redo');
 await travel(doc,'redo');s.changeDocument(doc,'New branch');assert.equal(s.documentHistory(doc).redo.length,0);
 // Ignore duplicate history shortcuts during replay, preserving edits made in flight.
 await s.changeAnnotation(doc,'annotations',{});
 delay=new Promise(resolve=>finish=resolve);
 assert.equal(s.travelDocument(doc,'undo'),true);assert.equal(s.travelDocument(doc,'undo'),false);
 s.changeDocument(doc,'Typing during replay');finish();await flush();delay=undefined;
 assert.equal(doc.text,'Typing during replay');assert.equal(s.documentHistory(doc).redo.length,0);
 assert.equal(s.documentHistory(doc).busy,false);
 // Redo in flight still goes before newly typed text in the undo stack.
 await travel(doc,'undo');
 delay=new Promise(resolve=>finish=resolve);
 assert.equal(s.travelDocument(doc,'redo'),true);
 s.changeDocument(doc,'Text after redo started');finish();await flush();delay=undefined;
 await travel(doc,'undo');assert.equal(doc.text,'Typing during replay');
 // Annotation errors must not erase a separate document save conflict.
 doc.error='Existing save conflict';
 await s.changeAnnotation(doc,'annotations',{});await travel(doc,'undo');
 assert.equal(doc.error,'Existing save conflict');
 assert(calls.filter(call=>call.endpoint==='annotations/history').every(call=>call.body.root==='fixture'&&call.body.path==='note.md'));
 console.log('PASS annotation history: shared text order, undo/redo, session isolation, async writes, conflicts, failed writes and branching');
})().catch(error=>{console.error(error);process.exitCode=1;});
