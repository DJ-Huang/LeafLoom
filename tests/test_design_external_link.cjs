'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const root=path.resolve(__dirname,'..'),session={id:'preview-session',origin:'http://p-project.localhost:18080'},source={};
let api;
test.before(async()=>{
 const outfile=path.join(root,'.cache/design-external-link/unit.cjs');fs.mkdirSync(path.dirname(outfile),{recursive:true});
 await require('../web/node_modules/esbuild').build({entryPoints:[path.join(root,'web/src/design-external-link.ts')],outfile,bundle:true,platform:'node',format:'cjs'});
 api=require(outfile);
});
const message=()=>({source,origin:session.origin,data:{session:session.id,type:'studio-open-external',url:'https://github.com/DJ-Huang'}});
const setup=()=>{
 const opened=[],errors=[];
 global.window={navigator:{userActivation:{isActive:true}},leafloomDesktop:{openExternal:async url=>{opened.push(url);}}};
 return {opened,errors,open:(event=message(),enabled=true)=>api.openDesignExternalLink(event,source,session,enabled,error=>errors.push(error))};
};
test('only public HTTP(S) addresses can leave the isolated design',()=>{
 assert.equal(api.designExternalUrl('https://github.com/DJ-Huang'),'https://github.com/DJ-Huang');
 assert.equal(api.designExternalUrl('http://example.org/docs#topic'),'http://example.org/docs#topic');
 for(const value of [null,'relative/page.html','javascript:alert(1)','file:///private/data','data:text/html,hi','mailto:test@example.org','https://name:secret@example.org','http://localhost:18080','http://p-project.localhost:18080','http://localhost.:18080','http://printer.local','http://intranet','http://127.1','http://0x7f000001','http://10.0.0.1','http://192.168.1.1','http://172.20.0.1','http://169.254.169.254','http://[::1]','https://example.org/'+ 'x'.repeat(8192)])assert.equal(api.designExternalUrl(value),null,String(value).slice(0,80));
});
test('a live preview click opens the exact address once through the native host',()=>{
 const f=setup();assert.equal(f.open(),true);assert.deepEqual(f.opened,['https://github.com/DJ-Huang']);assert.deepEqual(f.errors,[]);
});
test('stale frames, forged origins/sessions, edit mode and inactive gestures cannot open links',()=>{
 const f=setup();
 for(const event of [{...message(),source:{}},{...message(),origin:'https://evil.example'}, {...message(),data:{...message().data,session:'old'}},{...message(),data:{...message().data,type:'other'}},{...message(),data:{...message().data,url:'file:///tmp/test'}}])assert.equal(f.open(event),false);
 assert.equal(f.open(message(),false),false);
 assert.equal(api.openDesignExternalLink(message(),null,session,true,()=>{}),false);
 window.navigator.userActivation.isActive=false;assert.equal(f.open(),false);
 assert.deepEqual(f.opened,[]);
});
test('browser fallback and presenter relay preserve the validated address',()=>{
 const f=setup();delete window.leafloomDesktop;window.open=(...args)=>{f.opened.push(args);return null;};
 assert.equal(f.open(),true);assert.deepEqual(f.opened,[['https://github.com/DJ-Huang','_blank','noopener,noreferrer']]);
 const relayed=[];api.openDesignExternalLink(message(),source,session,true,()=>{},url=>relayed.push(url));assert.deepEqual(relayed,['https://github.com/DJ-Huang']);
});
test('native failures reach the host error surface without an unhandled rejection',async()=>{
 const f=setup();window.leafloomDesktop.openExternal=async()=>{throw Error('browser unavailable');};
 assert.equal(f.open(),true);await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(f.errors,['browser unavailable']);
});
