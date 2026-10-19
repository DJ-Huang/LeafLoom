// Pure source-anchor regression checks without browser, real vault or network.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),out=path.join(root,'.cache/rich-core-tests/annotation-anchors.cjs');
fs.mkdirSync(path.dirname(out),{recursive:true});
require(path.join(root,'web/node_modules/esbuild')).buildSync({
 entryPoints:[path.join(root,'web/src/annotations.ts')],outfile:out,
 bundle:true,platform:'node',format:'cjs',
});
const {makeAnchor,resolveAnchor}=require(out);
let tests=0;
function check(label,fn){fn();tests++;console.log('PASS',label);}
check('UTF-16 emoji offsets and source prefix relocation',()=>{
 const source='测试🚀 before target after\r\nFooter';
 const index=source.indexOf('target'),anchor=makeAnchor(source,{from:index,to:index+6},'etag1');
 assert.equal(anchor.exact,'target');assert.equal(source.slice(anchor.from,anchor.to),'target');
 assert.deepEqual(resolveAnchor(source,anchor),{from:index,to:index+6});
 const moved='New preface\r\n'+source,next=resolveAnchor(moved,anchor);
 assert.deepEqual(next,{from:moved.indexOf('target'),to:moved.indexOf('target')+6});
});
check('Delete quote detaches cleanly',()=>{
 const source='text before highlighted text after';
 const at=source.indexOf('highlighted'),anchor=makeAnchor(source,{from:at,to:at+11},'v1');
 assert.equal(resolveAnchor(source.replace('highlighted','removed'),anchor),null);
});
check('Do not attach a deleted quote to a sole unrelated occurrence',()=>{
 const source='Original context A: special_text right here.\n\nOther unrelated special_text far away';
 const from=source.indexOf('special_text'),anchor=makeAnchor(source,{from,to:from+12},'v1');
 const edited=source.replace('special_text','removed_text');
 assert.equal(edited.split('special_text').length-1,1);
 assert.equal(resolveAnchor(edited,anchor),null);
});
check('Repeated phrases are disambiguated by adjacent context',()=>{
 const source='First unique before: value, after first!\n\nSecond different before: value, after second!';
 const at=source.indexOf('value'),anchor=makeAnchor(source,{from:at,to:at+5},'v1');
 const edited='Preface text\n'+source;
 assert.deepEqual(resolveAnchor(edited,anchor),{from:edited.indexOf('value'),to:edited.indexOf('value')+5});
});
check('Identical repeated contexts are treated as ambiguous',()=>{
 const section='x'.repeat(70)+' SAME '+'y'.repeat(70);
 const source=section+'\n\n'+section;
 const at=source.indexOf('SAME'),anchor=makeAnchor(source,{from:at,to:at+4},'v1');
 const edited='Inserted prefix\n'+source;
 assert.equal(resolveAnchor(edited,anchor),null);
});
check('Large pathological repetitions are bounded',()=>{
 const source='marker '.repeat(1100),anchor=makeAnchor(source,{from:0,to:6},'v1');
 assert.equal(resolveAnchor(source,anchor),null);
});
check('Invalid or absent selections rejected',()=>{
 assert.equal(makeAnchor('test',{from:2,to:2},'v'),null);
 assert.equal(resolveAnchor('test',null),null);
});
console.log('Annotation anchor tests: '+tests);
