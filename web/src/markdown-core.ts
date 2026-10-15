import MarkdownIt from 'markdown-it';
import taskLists from 'markdown-it-task-lists';
export const stripFrontmatter=(text:string)=>text.replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/,'');
export type Block=({kind:'html',html:string}|{kind:'query',query:string})&{from:number,to:number};
export function createMarkdown(){
 const md=new MarkdownIt({html:false,linkify:true}).use(taskLists,{enabled:true,label:false});
 const fence=md.renderer.rules.fence!;
 md.renderer.rules.fence=(tokens,index,options,env,self)=>tokens[index].info.trim()==='mermaid'?'<pre class="mermaid" data-diagram="'+md.utils.escapeHtml(tokens[index].content)+'">'+md.utils.escapeHtml(tokens[index].content)+'</pre>':fence(tokens,index,options,env,self);
 md.inline.ruler.before('link','wikilink',(state,silent)=>{
  const match=/^(!?)\[\[([^\]\n]+)\]\]/.exec(state.src.slice(state.pos));if(!match)return false;
  if(!silent){const token=state.push('html_inline','',0);const [target,...alias]=match[2].replace(/\\\|/g,'|').split('|');token.content=match[1]?`<span class="embed-placeholder" data-embed="${md.utils.escapeHtml(target)}"></span>`:`<a class="wikilink" href="#" data-note="${md.utils.escapeHtml(target)}">${md.utils.escapeHtml(alias.join('|')||target.split('/').pop()||target)}</a>`;}
  state.pos+=match[0].length;return true;
 });
 const image=md.renderer.rules.image!;
 md.renderer.rules.image=(tokens,index,options,env,self)=>{const token=tokens[index];token.attrSet('data-vault-src',token.attrGet('src')||'');token.attrSet('src','');token.attrSet('loading','lazy');token.attrSet('decoding','async');return image(tokens,index,options,env,self);};
 return md;
}
export function blocks(md:MarkdownIt,text:string):Block[]{
 const out:Block[]=[];const body=stripFrontmatter(text),prefix=text.length-body.length,offsets=[prefix];for(let i=0;i<body.length;i++)if(body[i]==='\n')offsets.push(prefix+i+1);offsets.push(text.length);
 const tokens=md.parse(body,{});let group:typeof tokens=[];
 const flush=()=>{if(!group.length)return;const html=md.renderer.render(group,md.options,{});group=[];
  out.push({kind:'html',html,from:start,to:end});};
 let start=prefix,end=prefix;
 for(const token of tokens){
  if(token.type==='fence'&&token.info.trim()==='dataview'){flush();out.push({kind:'query',query:token.content,from:offsets[token.map?.[0]||0],to:offsets[token.map?.[1]||0]});continue;}
  if(!group.length)start=offsets[token.map?.[0]||0];if(token.map)end=offsets[token.map[1]];
  group.push(token);if(token.level===0&&token.nesting!==1)flush();
 }flush();return out;
}
export const hasMath=(text:string)=>/\$\$|\$[^\s$][^\n$]*\$/.test(text);
