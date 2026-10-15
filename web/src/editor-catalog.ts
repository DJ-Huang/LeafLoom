export type InsertId='text'|'h1'|'h2'|'h3'|'bullet'|'ordered'|'todo'|'quote'|'divider'|'code'|'table'|'image'|'file'|'link'|'wiki'|'math'|'mermaid';
export type InsertCommand={id:InsertId,label:string,description:string,aliases:string,icon:string,group:'basic'|'insert'|'technical',category:'basic'|'lists'|'media'|'advanced'};
export const insertCommands:readonly InsertCommand[]=[
 {id:'text',label:'正文',description:'开始写下你的想法',aliases:'text paragraph 正文 段落',icon:'T',group:'basic',category:'basic'},
 {id:'h1',label:'一级标题',description:'醒目的大标题',aliases:'h1 heading title 标题',icon:'H1',group:'basic',category:'basic'},
 {id:'h2',label:'二级标题',description:'划分章节与主题',aliases:'h2 heading title 标题',icon:'H2',group:'basic',category:'basic'},
 {id:'h3',label:'三级标题',description:'为内容添加小标题',aliases:'h3 heading title 标题',icon:'H3',group:'basic',category:'basic'},
 {id:'bullet',label:'无序列表',description:'用项目符号整理要点',aliases:'bullet list ul 列表',icon:'•',group:'basic',category:'lists'},
 {id:'ordered',label:'有序列表',description:'按顺序记录步骤',aliases:'number ordered list ol 列表',icon:'1.',group:'basic',category:'lists'},
 {id:'todo',label:'待办事项',description:'可勾选的任务清单',aliases:'todo task checkbox 待办 任务',icon:'☑',group:'basic',category:'lists'},
 {id:'quote',label:'引用',description:'突出一段引用或想法',aliases:'quote blockquote 引用',icon:'❝',group:'basic',category:'basic'},
 {id:'divider',label:'分割线',description:'用细线分隔内容',aliases:'divider hr separator 分割线',icon:'―',group:'basic',category:'basic'},
 {id:'code',label:'代码块',description:'保留缩进的代码片段',aliases:'code 代码',icon:'<>',group:'technical',category:'advanced'},
 {id:'table',label:'表格',description:'用行与列组织信息',aliases:'table 表格',icon:'▦',group:'basic',category:'basic'},
 {id:'image',label:'图片',description:'上传图片或粘贴截图',aliases:'image picture 图片 截图',icon:'▧',group:'insert',category:'media'},
 {id:'file',label:'附件',description:'添加本地文件',aliases:'file attachment 附件 文件',icon:'↥',group:'insert',category:'media'},
 {id:'link',label:'网页链接',description:'链接到网页或邮件地址',aliases:'link url 网页 链接',icon:'↗',group:'insert',category:'media'},
 {id:'wiki',label:'笔记链接',description:'关联知识库中的另一篇笔记',aliases:'wiki note link 笔记 双链',icon:'[[',group:'insert',category:'media'},
 {id:'math',label:'公式',description:'用 LaTeX 表达公式',aliases:'math equation latex 公式',icon:'∑',group:'technical',category:'advanced'},
 {id:'mermaid',label:'Mermaid 图表',description:'绘制流程图与关系图',aliases:'mermaid diagram flowchart 图表 流程图',icon:'◇',group:'technical',category:'advanced'}
];
export type FormatId='bold'|'italic'|'strike'|'inlineCode';
export const formatCommands:{id:FormatId,label:string,marker:string,key:string}[]=[
 {id:'bold',label:'加粗',marker:'**',key:'Mod-b'},
 {id:'italic',label:'斜体',marker:'*',key:'Mod-i'},
 {id:'strike',label:'删除线',marker:'~~',key:'Mod-Shift-x'},
 {id:'inlineCode',label:'行内代码',marker:'`',key:'Mod-e'}
];
export function safeLink(value:string){try{const url=new URL(value);return /^(https?:|mailto:)$/.test(url.protocol)?url.href:null;}catch{return null;}}
export function linkMarkdown(label:string,url:string){return '['+label.replace(/[\\[\]]/g,'\\$&')+']('+url.replace(/[()\s]/g,char=>encodeURIComponent(char).replace(/\(/g,'%28').replace(/\)/g,'%29'))+')';}
