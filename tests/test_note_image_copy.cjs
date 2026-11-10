'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const root=path.resolve(__dirname,'..');
let api;
test.before(async()=>{
 const outfile=path.join(root,'.cache/note-image-copy/unit.cjs');fs.mkdirSync(path.dirname(outfile),{recursive:true});
 await require('../web/node_modules/esbuild').build({
  stdin:{contents:"export * from './note-image-copy';",resolveDir:path.join(root,'web/src'),loader:'ts'},
  outfile,bundle:true,platform:'node',format:'cjs',
  plugins:[{name:'stubs',setup(build){
   build.onResolve({filter:/^\.\/i18n$/},()=>({path:'i18n',namespace:'fixture'}));
   build.onResolve({filter:/^\.\/api$/},()=>({path:'api',namespace:'fixture'}));
   build.onLoad({filter:/.*/,namespace:'fixture'},args=>{
    if(args.path==='i18n')return {contents:'export const t=key=>key;'};
    return {contents:`
      const calls=[];
      export const media=(path,download,root)=>'/api/media?path='+encodeURIComponent(path)+(root?'&root='+encodeURIComponent(root):'');
      export async function api(url){calls.push(url);if(url.includes('missing'))return {candidates:[]};if(url.includes('ambiguous'))return {candidates:['a.png','b.png']};return {candidates:['_attachments/shot.png']};}
      export const __calls=()=>calls;
    `};
   });
  }}]
 });
 api=require(outfile);
});

test('note image URLs reuse /api/media paths and resolve vault targets',async()=>{
 global.location={origin:'http://leafloom.test'};
 const signal=new AbortController().signal;
 assert.equal(await api.noteImageMediaUrl({url:'http://leafloom.test/api/media?path=_attachments%2Fshot.png',notePath:'Daily/note.md',root:'D:/vault'},signal),
  '/api/media?path=_attachments%2Fshot.png&root=D%3A%2Fvault');
 assert.equal(await api.noteImageMediaUrl({url:'https://cdn.example/x.png',notePath:'Daily/note.md'},signal),'https://cdn.example/x.png');
 assert.equal(await api.noteImageMediaUrl({target:'_attachments/shot.png',notePath:'Daily/note.md',root:'D:/vault'},signal),
  '/api/media?path=_attachments%2Fshot.png&root=D%3A%2Fvault');
 await assert.rejects(api.noteImageMediaUrl({target:'missing.png',notePath:'Daily/note.md'},signal),/note.imageUnresolved/);
 await assert.rejects(api.noteImageMediaUrl({notePath:'Daily/note.md'},signal),/note.imageUnresolved/);
});
