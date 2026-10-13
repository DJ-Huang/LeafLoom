export type GraphNode={id:string,label:string,type?:string};
export type GraphLink={source:string,target:string};
export type GraphData={nodes:GraphNode[],links:GraphLink[]};
export const groupOf=(id:string)=>id.includes('/')?id.split('/')[0]:'根目录';
const colors=['#718db3','#b48aaf','#78a493','#cc9b62','#988cbd','#c78180','#7b9eaa','#a4a16c'];
export function groupColor(group:string){let hash=0;for(const char of group)hash=(hash*31+char.charCodeAt(0))>>>0;return colors[hash%colors.length];}
export function graphIndex(data:GraphData){
 const nodes=new Map(data.nodes.map(node=>[node.id,node])),neighbors=new Map(data.nodes.map(node=>[node.id,new Set<string>()]));
 const seen=new Set<string>(),links=data.links.filter(link=>{
  const key=JSON.stringify([link.source,link.target]);
  if(!nodes.has(link.source)||!nodes.has(link.target)||seen.has(key))return false;
  seen.add(key);if(link.source!==link.target){neighbors.get(link.source)!.add(link.target);neighbors.get(link.target)!.add(link.source);}return true;
 });
 const palette=new Map<string,string>(),used=new Set<string>();
 for(const group of [...new Set(data.nodes.map(node=>groupOf(node.id)))].sort()){let color=groupColor(group);if(used.has(color)&&used.size<colors.length)color=colors.find(value=>!used.has(value))!;palette.set(group,color);used.add(color);}
 return {nodes,neighbors,links,colors:palette};
}
export type GraphIndex=ReturnType<typeof graphIndex>;
export function neighborhood(index:GraphIndex,center:string,depth:number){
 const found=new Set<string>(index.nodes.has(center)?[center]:[]);let frontier=[...found];
 for(let step=0;step<depth;step++){const next:string[]=[];for(const id of frontier)for(const neighbor of index.neighbors.get(id)||[])if(!found.has(neighbor)){found.add(neighbor);next.push(neighbor);}frontier=next;}
 return found;
}
export function graphSlice(index:GraphIndex,{center='',depth=1,group='',orphans=false}:{center?:string,depth?:number,group?:string,orphans?:boolean}){
 const scope=center?neighborhood(index,center,depth):new Set(index.nodes.keys());
 const nodes=[...index.nodes.values()].filter(node=>scope.has(node.id)&&(!group||groupOf(node.id)===group)&&(center||orphans||index.neighbors.get(node.id)!.size));
 const ids=new Set(nodes.map(node=>node.id));return {nodes,links:index.links.filter(link=>ids.has(link.source)&&ids.has(link.target))};
}
