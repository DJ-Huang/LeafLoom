import {t} from './i18n';
import {Config} from './api';

export const settingsSections = [
 {id:'general',get title(){return t("常规");},get description(){return t("管理关联目录与知识库首页。");}},
 {id:'connection',get title(){return t('mcp.connectionTitle');},get description(){return t('mcp.connectionDescription');}},
 {id:'files',get title(){return t("文件与导入");},get description(){return t("在指定目录创建内容，或导入本地文件。");}},
 {id:'templates',get title(){return t("模板与写入");},get description(){return t("设置模板、日记与各类资料的默认位置。");}},
 {id:'index',get title(){return t("检索与索引");},get description(){return t("选择检索资料，查看模型与同步状态。");}},
 {id:'ai',get title(){return t("Skill");},get description(){return t("让 AI 从你的本地知识库中查找依据。");}},
 {id:'history',get title(){return t("操作历史");},get description(){return t("查看目录操作和文档版本，恢复需要的内容。");}},
 {id:'trash',get title(){return t("回收区");},get description(){return t("找回已删除的内容，或永久清空回收区。");}},
] as const;
export type SettingsSection=typeof settingsSections[number]['id'];
export type SettingsLocation={section:SettingsSection,path?:string,targetId?:string};
export type SettingsResult={path:string,directory?:boolean,edit?:boolean,cursor?:number};
export const settingsEntries:{section:SettingsSection,id:string,title:string,description:string}[]=[
 {section:'connection',id:'mcp',get title(){return t('mcp.title');},get description(){return t('mcp.scope');}},
 {section:'connection',id:'feishu',get title(){return t('feishu.title');},get description(){return t('feishu.description');}},
 {section:'connection',id:'tunnel',get title(){return t('tunnel.title');},get description(){return t('tunnel.search');}},
 {section:'general',id:'root',get title(){return t("关联目录");},get description(){return t("选择或切换本地知识库文件夹");}},
 {section:'general',id:'homepage',get title(){return t("知识库首页");},get description(){return t("默认首页文件路径");}},
 {section:'general',id:'app-update',get title(){return t('update.title');},get description(){return t('update.search');}},
 {section:'files',id:'create',get title(){return t("新建笔记与目录");},get description(){return t("创建文件、新建目录、文件夹、目标位置");}},
 {section:'files',id:'upload',get title(){return t("上传文件");},get description(){return t("导入本地文件、附件");}},
 {section:'files',id:'template-create',get title(){return t("从模板新建");},get description(){return t("选择模板创建笔记");}},
 {section:'templates',id:'templates',get title(){return t("模板与日记目录");},get description(){return t("模板目录、今日笔记、日记位置");}},
 {section:'templates',id:'write-targets',get title(){return t("默认写入位置");},get description(){return t("知识正文、规则、主题导航、工时资料");}},
 {section:'index',id:'scope',get title(){return t("检索目录");},get description(){return t("索引范围、勾选目录、子目录排除");}},
 {section:'index',id:'special-folders',get title(){return t("专用目录");},get description(){return t("规则目录、Wiki 导航目录、工时资料目录");}},
 {section:'index',id:'model',get title(){return t("本地检索模型");},get description(){return t("BGE-M3 模型准备与加载状态");}},
 {section:'index',id:'sync',get title(){return t("同步与索引");},get description(){return t("重新同步、进度、文件数量、错误");}},
 {section:'ai',id:'skill',get title(){return t("知识库查询技能");},get description(){return t("安装或更新 wiki-search");}},
 {section:'history',id:'records',get title(){return t("操作与版本历史");},get description(){return t("目录操作历史、文档版本、恢复");}},
 {section:'trash',id:'trash',get title(){return t("回收区");},get description(){return t("垃圾箱、恢复已删除文件、永久清空");}},
];
export function searchSettings(query:string){
 const words=query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
 return words.length?settingsEntries.filter(item=>{
  if(item.id==='app-update'&&!window.leafloomDesktop)return false;
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
