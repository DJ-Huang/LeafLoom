import {Config} from './api';

export const settingsSections = [
 {id:'general',title:'常规',description:'管理关联目录与知识库首页。'},
 {id:'files',title:'文件与导入',description:'在指定目录创建内容，或导入本地文件。'},
 {id:'templates',title:'模板与写入',description:'设置模板、日记与各类资料的默认位置。'},
 {id:'index',title:'检索与索引',description:'选择检索资料，查看模型与同步状态。'},
 {id:'ai',title:'AI 集成',description:'让 AI 从你的本地知识库中查找依据。'},
 {id:'history',title:'操作历史',description:'查看目录操作和文档版本，恢复需要的内容。'},
 {id:'trash',title:'回收区',description:'找回已删除的内容，或永久清空回收区。'},
] as const;
export type SettingsSection=typeof settingsSections[number]['id'];
export type SettingsLocation={section:SettingsSection,path?:string,targetId?:string};
export type SettingsResult={path:string,directory?:boolean,edit?:boolean,cursor?:number};
export const settingsEntries:{section:SettingsSection,id:string,title:string,description:string}[]=[
 {section:'general',id:'root',title:'关联目录',description:'选择或切换本地知识库文件夹'},
 {section:'general',id:'homepage',title:'知识库首页',description:'默认首页文件路径'},
 {section:'files',id:'create',title:'新建笔记与目录',description:'创建文件、新建目录、文件夹、目标位置'},
 {section:'files',id:'upload',title:'上传文件',description:'导入本地文件、附件'},
 {section:'files',id:'template-create',title:'从模板新建',description:'选择模板创建笔记'},
 {section:'templates',id:'templates',title:'模板与日记目录',description:'模板目录、今日笔记、日记位置'},
 {section:'templates',id:'write-targets',title:'默认写入位置',description:'知识正文、规则、主题导航、工时资料'},
 {section:'index',id:'scope',title:'检索目录',description:'索引范围、勾选目录、子目录排除'},
 {section:'index',id:'special-folders',title:'专用目录',description:'规则目录、Wiki 导航目录、工时资料目录'},
 {section:'index',id:'model',title:'本地检索模型',description:'BGE-M3 模型准备与加载状态'},
 {section:'index',id:'sync',title:'同步与索引',description:'重新同步、进度、文件数量、错误'},
 {section:'ai',id:'skill',title:'知识库查询技能',description:'安装或更新 wiki-search'},
 {section:'history',id:'records',title:'操作与版本历史',description:'目录操作历史、文档版本、恢复'},
 {section:'trash',id:'trash',title:'回收区',description:'垃圾箱、恢复已删除文件、永久清空'},
];
export function searchSettings(query:string){
 const words=query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
 return words.length?settingsEntries.filter(item=>{
  const section=settingsSections.find(section=>section.id===item.section)!;
  const haystack=[section.title,section.description,item.title,item.description].join(' ').toLocaleLowerCase();
  return words.every(word=>haystack.includes(word));
 }):[];
}
export const copyConfig=(config:Config):Config=>JSON.parse(JSON.stringify(config));
export function configChanged(a:Config,b:Config){
 const {revision:ar,...left}=a,{revision:br,...right}=b;
 return JSON.stringify(left)!==JSON.stringify(right);
}
export const parentFolder=(path:string)=>path.includes('/')?path.slice(0,path.lastIndexOf('/')):'';
export const joinTarget=(folder:string,name:string)=>[folder.trim().replace(/\/$/,''),name.trim()].filter(Boolean).join('/');
