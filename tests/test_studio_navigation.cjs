// Fast navigation contracts, using the real runtime camera with a minimal DOM.
// Browser contracts in studio_runtime_browser.py cover transforms and pointer input.
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const ts=require('../web/node_modules/typescript');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'web/src/design-workbench.tsx'),'utf8');
const javascript=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const exported={};vm.runInNewContext(javascript+'\nexports.visibleLayers=visibleLayers;', {exports:exported,require:()=>({}),console});
const nodes=[{id:'group',children:[{id:'child',children:[{id:'leaf'}]}]},{id:'sibling'}];
const ids=collapsed=>Array.from(exported.visibleLayers(nodes,collapsed,'page'),item=>item.node.id);
assert.deepEqual(ids(new Set()),['group','child','leaf','sibling']);
assert.deepEqual(ids(new Set(['page:group'])),['group','sibling']);
assert.deepEqual(ids(new Set(['page:child'])),['group','child','sibling']);
assert.deepEqual(ids(new Set(['other:group'])),['group','child','leaf','sibling']);
const rows=exported.visibleLayers(nodes,new Set(),'page');assert.equal(rows[2].parentId,'child');assert.equal(rows[2].depth,2);assert.equal(nodes[0].children.length,1);

// Model the CSSStyleDeclaration methods used by runtime redraw/static cleanup.
// Keep direct camelCase assignments working, as they do in a browser.
class Style {
 constructor(){Object.defineProperty(this,'priorities',{value:new Map()});}
 key(name){return name.replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase());}
 setProperty(name,value,priority=''){this[this.key(name)]=String(value);this.priorities.set(name,priority);}
 getPropertyValue(name){return this[this.key(name)]||'';}
 getPropertyPriority(name){return this.priorities.get(name)||'';}
 removeProperty(name){const previous=this.getPropertyValue(name);delete this[this.key(name)];this.priorities.delete(name);return previous;}
 *[Symbol.iterator](){for(const name of Object.keys(this))yield name.replace(/[A-Z]/g,letter=>'-'+letter.toLowerCase());}
}
const styleContract=new Style();styleContract.animation='spin 1s';assert.equal(styleContract.removeProperty('animation'),'spin 1s');assert.equal(styleContract.getPropertyValue('animation'),'');styleContract.setProperty('background-color','red','important');assert.equal(styleContract.backgroundColor,'red');assert.equal(styleContract.getPropertyPriority('background-color'),'important');assert.equal(styleContract.removeProperty('background-color'),'red');assert.equal(styleContract.getPropertyPriority('background-color'),'');

class Element {
 constructor(doc){this.ownerDocument=doc;this.style=new Style();this.children=[];this.dataset={};this.listeners={};this.clientWidth=1000;this.clientHeight=800;this.captured=new Set();const classes=new Set();this.classList={add:(...items)=>items.forEach(x=>classes.add(x)),remove:(...items)=>items.forEach(x=>classes.delete(x)),contains:item=>classes.has(item),toggle:(item,on)=>on?classes.add(item):classes.delete(item)};}
 setAttribute(){} appendChild(child){this.children.push(child);child.parentElement=this;return child;} prepend(child){this.children.unshift(child);} replaceChildren(...children){this.children=children;children.forEach(child=>child.parentElement=this);} querySelectorAll(){return [];} querySelector(){return null;} addEventListener(type,fn){this.listeners[type]=fn;} removeEventListener(type){delete this.listeners[type];} focus(){} getBoundingClientRect(){return {left:0,top:0,width:this.clientWidth,height:this.clientHeight};} setPointerCapture(id){this.captured.add(id);} hasPointerCapture(id){return this.captured.has(id);} releasePointerCapture(id){this.captured.delete(id);}
}
let resized;
const win={EventTarget,AbortController,location:{href:'https://studio.test/'},URL,console,performance:{now:()=>0},ResizeObserver:class{constructor(callback){resized=callback;}observe(){}disconnect(){}},addEventListener(){},removeEventListener(){},requestAnimationFrame:()=>1,cancelAnimationFrame(){}};
const doc={defaultView:win,createElement:()=>new Element(doc),addEventListener(){},removeEventListener(){}};doc.head=new Element(doc);
const target=new Element(doc),events=[];
vm.runInNewContext(fs.readFileSync(path.join(root,'vault_rag/design_assets/studio/runtime.js'),'utf8'),{window:win,URL,URLSearchParams,console});
const document={id:'project',pages:[{id:'home',width:800,height:600,nodes:[]},{id:'wide',width:2000,height:1000,nodes:[]}],assets:{}};
const instance=win.LeafLoomStudio.mount(target,document,{mode:'edit',onMessage:event=>events.push(event)}),viewport=target.children[0];
assert.equal(instance.camera.zoom,1.15);
instance.setZoom(2);instance.setTool('hand');
viewport.listeners.pointerdown({button:0,pointerId:1,clientX:500,clientY:400,preventDefault(){}});
viewport.listeners.pointermove({pointerId:1,clientX:560,clientY:440});viewport.listeners.pointerup({pointerId:1});
assert.equal(instance.camera.x,370);assert.equal(instance.camera.y,280);assert.equal(instance.camera.zoom,2);
assert.equal(events.filter(e=>e.type==='studio-commit').length,0);
const camera=JSON.stringify(instance.camera);const changed=instance.document;changed.pages[0].name='Renamed';instance.update(changed,{pageId:'home'});assert.equal(JSON.stringify(instance.camera),camera);
viewport.clientWidth=1200;resized();assert.equal(JSON.stringify(instance.camera),camera);
instance.setMode('preview');instance.setMode('edit');assert.equal(JSON.stringify(instance.camera),camera);
instance.navigate('wide');assert.equal(instance.camera.zoom,.56);instance.setZoom(.5);instance.navigate('home');assert.equal(instance.camera.zoom,2);instance.navigate('wide');assert.equal(instance.camera.zoom,.5);
instance.setZoom(NaN);instance.setZoom('1');assert.equal(instance.camera.zoom,.5);instance.setZoom(100);assert.equal(instance.camera.zoom,8);instance.setZoom(-1);assert.equal(instance.camera.zoom,.03);
instance.fit();const wider=instance.document;wider.pages[1].width=4000;instance.update(wider,{pageId:'wide'});assert.equal(instance.camera.zoom,.28);
instance.setZoom(2);const other=instance.document;other.id='different';instance.update(other,{pageId:'home'});assert.equal(instance.camera.zoom,1.2);
instance.setZoom(3);const samePage=instance.document;samePage.id='same-page-new-project';instance.update(samePage,{pageId:'home'});assert.equal(instance.camera.zoom,1.2);
instance.setZoom(1);const previous=instance.camera;viewport.listeners.wheel({ctrlKey:true,deltaY:-20,clientX:700,clientY:400,preventDefault(){}});assert.ok(instance.camera.zoom>1);assert.ok(Math.abs(instance.camera.x+100/instance.camera.zoom-(previous.x+100))<1e-8);
instance.dispose();assert.equal(target.children.length,0);
console.log('Studio layer collapse, per-page camera, pan, zoom, resize and update contracts passed.');

// Keep creation regressions in the established CI contract entry point.
require('node:child_process').execFileSync(process.execPath,[path.join(__dirname,'test_studio_create.cjs')],{stdio:'inherit'});
