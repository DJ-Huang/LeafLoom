'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const root=path.resolve(__dirname,'..');
let api;
test.before(async()=>{
 const outfile=path.join(root,'.cache/design-image-copy/unit.cjs');fs.mkdirSync(path.dirname(outfile),{recursive:true});
 await require('../web/node_modules/esbuild').build({stdin:{contents:"export * from './design-image-source'; export * from './image-clipboard';",resolveDir:path.join(root,'web/src'),loader:'ts'},outfile,bundle:true,platform:'node',format:'cjs',plugins:[{name:'translations',setup(build){build.onResolve({filter:/^\.\/i18n$/},()=>({path:'i18n',namespace:'fixture'}));build.onLoad({filter:/.*/,namespace:'fixture'},()=>({contents:'export const t=key=>key;'}));}}]});
 api=require(outfile);
});
const node=(props={},type='image')=>({id:'image',type,name:'Selected',props,style:{}});
const document=()=>({assets:{one:{id:'one',name:'Original.png',path:'Design/Assets/one.png'},two:{id:'two',name:'Variant.svg',path:'Design/Assets/two.svg'}},components:{},bindings:{photo:{kind:'image',value:'one'}},variants:{mobile:{values:{photo:{value:'two'}}}}});

test('source resolution matches binding/variant projection without mutating the project',()=>{
 const doc=document(),selected=node({assetId:'two',src:'stale.png',bindingKey:'photo'}),before=JSON.stringify([doc,selected]);
 assert.equal(api.designImageSource(doc,selected,'Project').path,'Project/Design/Assets/one.png');
 const variant=api.designImageSource(doc,selected,'Project','mobile');assert.equal(variant.path,'Project/Design/Assets/two.svg');assert.equal(variant.name,'Variant.svg');assert.equal(variant.staticCopy,true);
 assert.equal(api.designImageSource(doc,selected,'Project','removed').error,'design.imageBindingMissing');
 assert.equal(JSON.stringify([doc,selected]),before);
});
test('image-root component overrides take precedence over projected master bindings',()=>{
 const doc=document();doc.components.picture={node:node({bindingKey:'photo'})};
 for(const overrides of [{assetId:'one'},{image:{props:{assetId:'one'}}}]){
  const selected=node({componentId:'picture',overrides},'instance');
  assert.equal(api.designImageSource(doc,selected,'Project','mobile').path,'Project/Design/Assets/one.png');
 }
 assert.equal(api.designImageSource(doc,node({text:'text'},'text'),'Project'),null);
});
test('external or escaping paths fail explicitly; local imported image paths resolve',()=>{
 for(const src of ['https://fixture.invalid/image.png','file:///private/image.png','//fixture.invalid/image.png'])assert.equal(api.designImageSource(document(),node({src}),'Project').error,'design.imageExternalSource');
 for(const src of ['../outside.png','%2e%2e/outside.png','assets\\outside.png','bad%ZZ.png'])assert.equal(api.designImageSource(document(),node({src}),'Project').error,'design.imageSourceInvalid');
 assert.equal(api.designImageSource(document(),node({src:'/Pictures/a%20b.png?v=2'}),'Project').path,'Project/Pictures/a b.png');
 assert.equal(api.designImageSource(document(),node({assetId:'missing'}),'Project').error,'design.imageAssetMissing');
 assert.equal(api.designImageSource(document(),node({tag:'img',src:'a.png'},'element'),'Project').path,'Project/a.png');
});
test('latest copy wins; cancelled or failed requests never report a successful copy',async()=>{
 const requests=new api.ImageCopyRequest(),writes=[];let release;
 const first=requests.run(async signal=>{await new Promise(resolve=>release=resolve);signal.throwIfAborted();writes.push('old');});
 const second=requests.run(async signal=>{signal.throwIfAborted();writes.push('new');});
 release();assert.equal(await first,false);assert.equal(await second,true);assert.deepEqual(writes,['new']);
 const cancelled=requests.run(signal=>new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(signal.reason))));requests.cancel();assert.equal(await cancelled,false);
 await assert.rejects(requests.run(async()=>{throw Error('read failed');}),/read failed/);
});
test('desktop image writes bypass web permissions, and old sessions require restart',async()=>{
 const bytes=[];global.window={leafloomDesktop:{writeClipboardImage:async value=>bytes.push(...value)}};
 await api.writeClipboardImage(Promise.resolve(new Blob(['png'],{type:'image/png'})),new AbortController().signal);assert.deepEqual(bytes,[112,110,103]);
 global.window.leafloomDesktop={writeClipboardText:()=>assert.fail('must never substitute text')};
 await assert.rejects(api.writeClipboardImage(Promise.resolve(new Blob(['png'],{type:'image/png'})),new AbortController().signal),/design.imageCopyRestart/);
});
test('browser clipboard write starts inside the gesture, with asynchronous PNG bytes',async()=>{
 global.window={};let release,called=false;
 global.ClipboardItem=class{constructor(data){this.data=data;}};
 Object.defineProperty(global,'navigator',{configurable:true,value:{clipboard:{write:async items=>{called=true;const value=await items[0].data['image/png'];assert.equal(value.type,'image/png');}}}});
 const pending=api.writeClipboardImage(new Promise(resolve=>release=resolve),new AbortController().signal);
 assert.equal(called,true);release(new Blob(['png'],{type:'image/png'}));await pending;
 navigator.clipboard.write=async()=>{throw Error('permission denied');};
 await assert.rejects(api.writeClipboardImage(Promise.resolve(new Blob(['png'],{type:'image/png'})),new AbortController().signal),/design.imageClipboardUnavailable/);
});
