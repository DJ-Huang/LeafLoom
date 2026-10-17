import React from 'react';
import {t} from './i18n';

type FidelityItem={kind?:string,count?:number,description?:string,page_id?:string,page_name?:string,sources?:string[]};
export type FidelityReport={retained?:FidelityItem[],converted?:FidelityItem[],unsupported?:FidelityItem[],warnings?:string[],pages?:number,nodes?:number,source_pages?:number,context_variants?:number,method?:string};
/** Import evidence is shown separately from the editable properties of a layer. */
const reportLabels:Record<string,string>={assets:'已登记的素材引用保持不变',context_variants:'按上下文变化的画面保存为关联页面',source_copy:'原始 HTML、CSS、脚本与素材保留在副本中，原项目不变',authored_nodes:'保留可编辑的 DOM 层级、文字、属性、SVG 与资源引用',stylesheets:'保留可读取的 CSS，并限定到对应画板',navigation:'页面链接已转换为工作台导航',switches:'已识别的开关转换为可编辑脚本',script_runtime:'脚本保留在源文件中；事件监听器、闭包和运行状态不会重放',inline_handlers:'内联事件已移除，需重新编写交互',unreadable_stylesheets:'无法读取的跨域样式表已省略',canvas_bitmap:'画布布局保留，但绘制位图和 WebGL 状态不保留',embedded_documents:'嵌入文档替换为静态容器',shadow_dom:'Shadow DOM 未转换为可编辑图层',live_form_state:'表单结构保留，但脚本或用户更改的值不保留',svg_foreign_object:'SVG 外部对象内容已省略'};
export function ImportFidelity({report,warnings=[]}:{report?:FidelityReport,warnings?:string[]}){
  const groups=[['retained','已保留'],['converted','已转换'],['unsupported','不支持自动还原']] as const;
  const hasReport=groups.some(([key])=>report?.[key]?.length);
  const uniqueWarnings=[...new Set([...(report?.warnings||[]),...warnings])];
  if(!hasReport&&!uniqueWarnings.length)return null;
  return <details className="dw-fidelity" data-testid="import-fidelity"><summary>{t('导入还原报告')}<span className="dw-fidelity-summary">{groups.map(([key,label])=>report?.[key]?.length?<span key={key}>{t(label)} {report[key]!.reduce((sum,item)=>sum+(item.count||1),0)}</span>:null)}{uniqueWarnings.length>0&&<span>{t('转换提示')} {uniqueWarnings.length}</span>}</span></summary>{hasReport&&<div className="dw-fidelity-grid">{groups.map(([key,label])=><section key={key} className={'dw-fidelity-group'+(key==='unsupported'&&report?.[key]?.length?' is-warning':'')}><h4>{t(label)}</h4>{report?.[key]?.length?<ul>{report[key]!.map((item,index)=><li key={index}><span>{reportLabels[item.kind||'']?t(reportLabels[item.kind||'']):item.description||item.kind}{item.count&&item.count>1?' · '+item.count:''}</span>{item.page_name&&<small> · {item.page_name}</small>}</li>)}</ul>:<p className="dw-hint">{t('无报告项')}</p>}</section>)}</div>}{uniqueWarnings.length>0&&<ul>{uniqueWarnings.map((warning,index)=><li key={index}>{warning}</li>)}</ul>}<p className="dw-hint">{t('原始源码会保留；转换后的交互和特殊内容请在预览中复查')}</p></details>;
}
