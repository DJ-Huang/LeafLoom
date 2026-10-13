import {forceSimulation,forceManyBody,forceLink,forceCollide,forceX,forceY,SimulationNodeDatum} from 'd3-force';
import {GraphData} from './graph-model';
type Node=SimulationNodeDatum&{id:string,degree:number};
// Layout is isolated from rendering: a new filter terminates the old worker.
self.onmessage=(event:MessageEvent<GraphData>)=>{
 const degree=new Map(event.data.nodes.map(node=>[node.id,0]));
 for(const link of event.data.links){degree.set(link.source,(degree.get(link.source)||0)+1);degree.set(link.target,(degree.get(link.target)||0)+1);}
 const nodes:Node[]=event.data.nodes.map(node=>({id:node.id,degree:degree.get(node.id)||0}));
 const links=event.data.links.filter(link=>link.source!==link.target).map(link=>({...link}));
 const simulation=forceSimulation(nodes).stop().force('charge',forceManyBody<Node>().strength(-150).distanceMax(1800))
  .force('link',forceLink<Node,typeof links[number]>(links).id(node=>node.id).distance(65).strength(.45))
  .force('collide',forceCollide<Node>().radius(node=>11+Math.sqrt(node.degree)*1.5).iterations(2))
  .force('x',forceX(0).strength(.025)).force('y',forceY(0).strength(.025));
 for(let i=0;i<240;i++)simulation.tick();
 self.postMessage(nodes.map(node=>({id:node.id,x:node.x!,y:node.y!})));
};
