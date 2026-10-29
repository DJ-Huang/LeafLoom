'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const {EventEmitter} = require('node:events');
const {DesignPresenter, audienceDocument, inputCommand} = require('../design-presenter.cjs');
const source = () => ({schemaVersion:1,id:'deck',pages:[{id:'one',nodes:[],presenterNotes:{overview:'PRIVATE',cues:{secret:'PRIVATE'}}},{id:'two',nodes:[]}]});
const origin = 'http://app.'+'a'.repeat(32)+'.localhost:18080';
const runtime = {id:'session',origin:'http://p-'+'b'.repeat(32)+'.'+'a'.repeat(32)+'.localhost:18080'};
function fixture(){
 const events=[],screen=new EventEmitter();let focus=0,captures=0,muted=false,commands=[],windows=[];
 const displays=[1,2].map((id,index)=>({id,label:'Screen '+id,scaleFactor:id,bounds:{x:index*1920,y:0,width:1920,height:1080},workArea:{x:index*1920,y:24,width:1920,height:1056}}));
 screen.getAllDisplays=()=>displays;screen.getDisplayMatching=b=>displays.find(d=>b.x>=d.bounds.x&&b.x<d.bounds.x+d.bounds.width)||displays[0];
 let ownerBounds={x:0,y:24,width:1200,height:800},controllerMuted=false;const owner={webContents:{isAudioMuted:()=>controllerMuted,setAudioMuted:v=>{controllerMuted=v;},setBackgroundThrottling(){}},getBounds:()=>({...ownerBounds}),setBounds:b=>{ownerBounds=b;},focus:()=>focus++,isMinimized:()=>false,isDestroyed:()=>false};
 class Window extends EventEmitter {
  constructor(options){super();this.options=options;this.bounds=options;windows.push(this);let attached=false;this.webContents=Object.assign(new EventEmitter(),{setZoomFactor(){},setWindowOpenHandler(){},setAudioMuted:value=>{muted=value;},send:(name,value)=>commands.push({name,value}),mainFrame:{url:origin+'/?view=presenter-output'},debugger:Object.assign(new EventEmitter(),{isAttached:()=>attached,attach:()=>{attached=true;},detach:()=>{attached=false;},sendCommand:async(method,params)=>commands.push({method,params})}),capturePage:async()=>{captures++;return {getSize:()=>({width:3840,height:2160}),resize:({width,height})=>({getSize:()=>({width,height}),toJPEG:()=>Buffer.from('JPEG')})};}});}
  async loadURL(url){this.url=url;}isDestroyed(){return !!this.dead;}getContentBounds(){return {width:1920,height:1080};}setBounds(b){this.bounds=b;}setFullScreen(v){this.fullscreen=v;}showInactive(){this.visible=true;}hide(){this.visible=false;}destroy(){this.dead=true;this.emit('closed');}setMenu(){}
 }
 const presenter=new DesignPresenter({BrowserWindow:Window,screen,owner:()=>owner,origin:()=>origin,emit:e=>events.push(e)});
 const input=()=>({document:source(),pageId:'one',pageIds:['one','two'],session:runtime,displayId:2,fullscreen:true});
 const event=()=>({sender:windows[0].webContents,senderFrame:windows[0].webContents.mainFrame});
 return {presenter,input,event,events,screen,displays,windows,commands,get focus(){return focus;},get captures(){return captures;},get muted(){return muted;}};
}
test('notes never reach the audience snapshot and input is an allowlisted normalized channel',()=>{
 const s=source();assert.equal(audienceDocument(s).pages[0].presenterNotes,undefined);assert.equal(s.pages[0].presenterNotes.overview,'PRIVATE');
 assert.deepEqual(inputCommand({kind:'move',x:.25,y:.5},{width:1920,height:1080}).params.x,480);
 assert.equal(inputCommand({kind:'key',phase:'down',key:'x',code:'KeyX'},{width:1,height:1}).method,'Input.dispatchKeyEvent');
 for(const input of [{kind:'evaluate',expression:'secret'},{kind:'down',x:NaN,y:0},{kind:'down',x:2,y:0},{kind:'key',key:'F12',phase:'down'},{kind:'wheel',x:0,y:0,dx:Infinity,dy:0}])assert.throws(()=>inputCommand(input,{width:100,height:100}));
});
test('single-screen mode requires window rehearsal; project frames cannot act as the output',async t=>{
 const f=fixture();t.after(()=>f.presenter.dispose());await assert.rejects(f.presenter.start({...f.input(),displayId:1}),/rehearsal/);await assert.rejects(f.presenter.start({...f.input(),session:{...runtime,origin:'http://evil.test'}}),/runtime/);await assert.rejects(f.presenter.start({...f.input(),pageIds:['missing']}),/page order/);
 const session=await f.presenter.start({...f.input(),displayId:1,fullscreen:false});assert.equal(f.windows[0].options.show,false);assert.equal(f.windows[0].options.webPreferences.nodeIntegration,false);assert.throws(()=>f.presenter.outputReady({sender:{}}),/Untrusted/);
 f.presenter.outputReady(f.event());assert.equal(f.commands.at(-1).value.document.pages[0].presenterNotes,undefined);f.presenter.outputReport(f.event(),{id:session.id,type:'ready'});assert.equal(f.windows[0].fullscreen,undefined);
});
test('background input keeps controller focus; bounded frames use acknowledgement backpressure',async t=>{
 const f=fixture();t.after(()=>f.presenter.dispose());const {id}=await f.presenter.start(f.input());f.presenter.outputReport(f.event(),{id,type:'ready'});assert.equal(f.windows[0].fullscreen,true);const before=f.focus;
 assert.ok(f.commands.some(command=>command.method==='Emulation.setFocusEmulationEnabled'&&command.params.enabled));
 await f.presenter.input(id,{kind:'down',x:.2,y:.3,button:0,buttons:1});assert.equal(f.focus,before);assert.equal(f.commands.at(-1).method,'Input.dispatchMouseEvent');
 await f.presenter.capture(f.presenter.active);const first=f.events.find(e=>e.type==='frame');assert.equal(first.width,1280);assert.equal(first.height,720);f.presenter.active.lastCapture=0;await f.presenter.capture(f.presenter.active);assert.equal(f.captures,1);f.presenter.ack(id,first.seq);await f.presenter.capture(f.presenter.active);assert.equal(f.captures,2);
});
test('blackout and disconnect mute and pause; reconnect never resumes media automatically',async t=>{
 const f=fixture();t.after(()=>f.presenter.dispose());const {id}=await f.presenter.start(f.input());f.presenter.command(id,{action:'black',enabled:true});assert.equal(f.muted,true);f.presenter.command(id,{action:'black',enabled:false});assert.equal(f.muted,true);f.presenter.command(id,{action:'resume'});assert.equal(f.muted,false);f.presenter.command(id,{action:'pause'});assert.equal(f.muted,true);
 f.displays.pop();f.screen.emit('display-removed');assert.equal(f.presenter.active.suspended,true);assert.equal(f.windows[0].visible,false);f.presenter.command(id,{action:'reopen',displayId:1});assert.equal(f.muted,true);assert.equal(f.presenter.active.state.paused,true);f.presenter.stop(id);assert.equal(f.windows[0].isDestroyed(),true);assert.equal(f.events.at(-1).type,'ended');
});
test('swap restores controller bounds on end; late ready cannot reveal suspended output',async t=>{
 const f=fixture();t.after(()=>f.presenter.dispose());const {id}=await f.presenter.start(f.input());const initial={...f.presenter.active.controllerBounds};
 f.presenter.command(id,{action:'swap'});assert.equal(f.presenter.active.displayId,1);assert.equal(f.windows[0].bounds.x,0);
 const event=f.event();assert.equal(f.presenter.isOutput({...event,senderFrame:{url:event.senderFrame.url}}),false);
 f.presenter.suspend('controller-disconnected');f.presenter.outputReport(event,{id,type:'ready'});assert.equal(f.windows[0].visible,false);assert.equal(f.muted,true);
 f.presenter.stop(id);assert.deepEqual(f.presenter.owner().getBounds(),initial);
});
test('confirmed startup swap moves the console, fullscreens the original display and restores its position',async t=>{
 const f=fixture();t.after(()=>f.presenter.dispose());const original=f.presenter.owner().getBounds();
 const {id}=await f.presenter.start({...f.input(),displayId:1,controllerDisplayId:2});
 assert.equal(f.presenter.owner().webContents.isAudioMuted(),true);
 assert.equal(f.presenter.owner().getBounds().x,1920);f.presenter.outputReport(f.event(),{id,type:'ready'});assert.equal(f.windows[0].fullscreen,true);
 f.presenter.stop(id);assert.deepEqual(f.presenter.owner().getBounds(),original);assert.equal(f.presenter.owner().webContents.isAudioMuted(),false);
});
test('drag events wait for mouse-down completion and stay in order without activating the controller',async t=>{
 const f=fixture();t.after(()=>f.presenter.dispose());const {id}=await f.presenter.start(f.input()),received=[];let release;
 f.windows[0].webContents.debugger.sendCommand=async(method,params)=>{received.push(params.type);if(params.type==='mousePressed')await new Promise(resolve=>{release=resolve;});};
 const down=f.presenter.input(id,{kind:'down',x:.1,y:.2,button:0,buttons:1});
 const move=f.presenter.input(id,{kind:'move',x:.8,y:.2,button:0,buttons:1});
 const up=f.presenter.input(id,{kind:'up',x:.8,y:.2,button:0,buttons:0});
 await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(received,['mousePressed']);release();await Promise.all([down,move,up]);assert.deepEqual(received,['mousePressed','mouseMoved','mouseReleased']);assert.equal(f.focus,0);
});
