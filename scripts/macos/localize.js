// Bootstrap localization before private Python exists. Uses macOS Foundation only.
ObjC.import('Foundation');
function read(path){const data=$.NSData.dataWithContentsOfFile($(path));if(!data)return '';return ObjC.unwrap($.NSString.alloc.initWithDataEncoding(data,$.NSUTF8StringEncoding));}
function run(argv){
 const [repo,state,key]=argv;let language='auto';
 try{language=JSON.parse(read(state+'/preferences.json')).locale||'auto';}catch{}
 if(language==='auto')language=ObjC.unwrap($.NSLocale.preferredLanguages.objectAtIndex(0));
 const code=language.startsWith('zh')?'zh-CN':language.startsWith('ja')?'ja':'en';
 try{return JSON.parse(read(repo+'/vault_rag/locales/'+code+'.json'))[key]||key;}catch{return key;}
}
