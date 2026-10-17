// Fast creation contracts against the real component handlers. No browser/build.
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const ts=require('../web/node_modules/typescript');
const root=path.resolve(__dirname,'..');
function component(file,{api=async()=>({}),seed=[]}={}){
 const slots=[...seed];let cursor=0;
 const react={useState(initial){const index=cursor++;if(!(index in slots))slots[index]=typeof initial==='function'?initial():initial;return[slots[index],value=>{slots[index]=typeof value==='function'?value(slots[index]):value;}];},useRef(initial){const index=cursor++;if(!(index in slots))slots[index]={current:initial};return slots[index];},useId:()=> 'create-folder-test-hint',useEffect(){},useCallback:value=>value,useMemo:fn=>fn()};
 react.default=react;
 const jsx=(type,props)=>({type,props:props||{}});
 const modules={'react':react,'react/jsx-runtime':{jsx,jsxs:jsx},'./api':{api},'./i18n':{t:value=>value,useLocale(){},Diagnostic:'Diagnostic'},'./ui':{Modal:'Modal'},'./tree':{DirectoryTree:'DirectoryTree'},'./virtual':{VirtualList:'VirtualList'},'./design-projects':{DesignProjects:'DesignProjects'},'./design-workbench':{DesignWorkbench:'DesignWorkbench'}};
 const source=fs.readFileSync(path.join(root,'web/src',file),'utf8');
 const javascript=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 const exported={};vm.runInNewContext(javascript,{exports:exported,require:id=>modules[id]||{},window:{},URL,URLSearchParams,AbortController,console,setTimeout,clearTimeout});
 return {render(name,props){cursor=0;return exported[name](props);}};
}
function all(node,predicate){if(!node||typeof node!=='object')return[];if(Array.isArray(node))return node.flatMap(value=>all(value,predicate));const children=node.type==='VirtualList'?node.props.items.map(node.props.render):node.props.children;return[...(predicate(node)?[node]:[]),...all(children,predicate)];}
const find=(node,predicate)=>{const matches=all(node,predicate);assert.equal(matches.length,1,'Expected exactly one matching element');return matches[0];};
const text=node=>typeof node==='string'?node:Array.isArray(node)?node.map(text).join(''):node&&typeof node==='object'?text(node.props.children):'';
const button=(node,label)=>find(node,item=>item.type==='button'&&text(item)===label);
const field=(node,label)=>find(find(node,item=>item.type==='label'&&text(item).startsWith(label)),item=>item.type==='input');
const clickEvent=(valid=true)=>({currentTarget:{form:{reportValidity:()=>valid}}});
async function main(){
 const picked=[],opened=[],managed=[];
 const tree=component('tree.tsx',{seed:[{'':[{path:'Projects',name:'Projects',directory:true},{path:'note.md',name:'note.md',directory:false}],Projects:[{path:'Projects/Child',name:'Child',directory:true}],'Projects/Child':[]},new Set(),'']});
 const treeProps={onFolder:value=>picked.push(value),onOpen:value=>opened.push(value),selected:'',refresh:0,manage:(...args)=>managed.push(args)};
 let view=tree.render('DirectoryTree',treeProps);
 for(const control of all(view,item=>item.type==='button'))assert.equal(control.props.type,'button','Tree controls must never implicitly submit their containing form');
 button(view,'Projects').props.onClick();view=tree.render('DirectoryTree',treeProps);button(view,'Child').props.onClick();
 button(view,'note.md').props.onClick();find(view,item=>item.props.className==='tree-more'&&item.props['aria-label']==='管理 Projects').props.onClick({currentTarget:{focus(){}}});
 assert.deepEqual(picked,['Projects','Projects/Child']);assert.deepEqual(opened,['note.md']);assert.deepEqual(managed,[['menu','Projects']]);
 const directoryOnly=tree.render('DirectoryTree',{...treeProps,dirsOnly:true});assert.equal(all(directoryOnly,item=>item.props.className==='tree-more').length,0);assert.equal(all(directoryOnly,item=>item.type==='button'&&text(item)==='note.md').length,0);
 for(const template of ['blank','forma']){
  const requests=[],notices=[];let resolveCreate,rejectCreate;
  const api=(endpoint,body)=>{requests.push({endpoint,body});if(body)return new Promise((resolve,reject)=>{resolveCreate=resolve;rejectCreate=reject;});return Promise.resolve({projects:[{directory:'Projects/Child/MyProject',name:'My project',managed:true}],selected:null});};
  const studio=component('design-studio.tsx',{api}),props={root:'/vault',active:true,initialFolder:'',onOpenNote(){},onOpenFolder(){},notify:value=>notices.push(value),refresh:0};
  let view=studio.render('DesignStudio',props);
  const render=()=>view=studio.render('DesignStudio',props);
  find(view,item=>item.type==='DesignProjects').props.onCreate();render();
  const createForm=()=>find(view,item=>item.type==='form');
  const create=()=>button(view,'创建并打开设计工作台');
  const modal=()=>find(view,item=>item.type==='Modal');
  let prevented=0;createForm().props.onSubmit({preventDefault(){prevented++;}});assert.equal(prevented,1);assert.equal(requests.length,0,'Implicit submission must not create');
  for(const parent of ['Projects','Projects/Child','','Projects/Child']){find(view,item=>item.type==='DirectoryTree').props.onFolder(parent);render();assert.equal(requests.length,0);}
  field(view,'项目文件夹名称（英文或中文目录名）').props.onChange({target:{value:'MyProject'}});field(view,'项目显示名称').props.onChange({target:{value:'My project'}});render();
  find(view,item=>item.type==='input'&&item.props.name==='design-template'&&item.props.value===template).props.onChange();render();
  assert.deepEqual(all(view,item=>item.type==='code').map(text),['/Projects/Child','/Projects/Child/MyProject']);
  for(const invalid of ['','  ','.','..','nested/folder','nested\\folder']){
   field(view,'项目文件夹名称（英文或中文目录名）').props.onChange({target:{value:invalid}});render();assert.equal(create().props.disabled,true,'Reject invalid folder name '+JSON.stringify(invalid));await create().props.onClick(clickEvent());assert.equal(requests.length,0);
  }
  field(view,'项目文件夹名称（英文或中文目录名）').props.onChange({target:{value:'MyProject'}});render();
  assert.equal(create().props.type,'button');await create().props.onClick(clickEvent(false));assert.equal(requests.length,0,'Native form validity must be respected');
  // Invoke the same closure twice without a render: state alone cannot guard it.
  const handler=create().props.onClick,first=handler(clickEvent()),duplicate=handler(clickEvent());
  assert.equal(requests.length,1,'Same-tick duplicate create is blocked by synchronous guard');
  assert.equal(requests[0].body.directory,'Projects/Child/MyProject');assert.equal(requests[0].body.name,'My project');assert.equal(requests[0].body.template_id,template==='forma'?'forma':undefined);
  render();assert.equal(createForm().props['aria-busy'],true);
  assert.equal(find(view,item=>item.type==='fieldset'&&item.props.className==='pad design-create-form').props.disabled,true);
  assert.equal(button(view,'正在创建…').props.disabled,true);assert.equal(button(view,'取消').props.disabled,true);
  modal().props.onClose();render();assert.equal(all(view,item=>item.type==='Modal').length,1,'Pending create cannot be dismissed');
  rejectCreate(new Error('Recoverable test failure'));await Promise.all([first,duplicate]);render();
  assert.equal(create().props.disabled,false,'Failure releases the in-flight guard');assert.equal(createForm().props['aria-busy'],false);
  const retry=create().props.onClick(clickEvent());assert.equal(requests.filter(item=>item.body).length,2,'An explicit retry can create after failure');
  resolveCreate({project:{directory:'Projects/Child/MyProject',name:'My project'}});await retry;render();
  assert.equal(all(view,item=>item.type==='Modal').length,0);assert.equal(notices.length,1);
  assert.equal(requests.filter(item=>item.body).length,2);
  find(view,item=>item.type==='DesignWorkbench').props.onBack();render();find(view,item=>item.type==='DesignProjects').props.onCreate();render();button(view,'取消').props.onClick();render();assert.equal(all(view,item=>item.type==='Modal').length,0);
  assert.equal(requests.filter(item=>item.body).length,2,'Cancel is read-only');
 }
 console.log('Studio tree button types, explicit creation, path validation, same-tick duplicate guard, frozen fields and retry contracts passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
