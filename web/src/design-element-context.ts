// Stable IDs and the canonical file are enough to locate an element.
type ContextNode={id:string,children?:ContextNode[]};
type ContextPage={id:string,nodes:ContextNode[]};
type ContextDocument={pages:{id:string}[],components:Record<string,{node:ContextNode}>};
function absolutePath(root:string,path:string){
 const separator=/^(?:[a-z]:\\|\\\\)/i.test(root)?'\\':'/';
 return root+(root.endsWith(separator)?'':separator)+path.replace(/\//g,separator);
}
function containsNode(nodes:ContextNode[],id:string):boolean{
 return nodes.some(node=>node.id===id||containsNode(node.children||[],id));
}

export function elementContext({root,directory,document,page,nodeIds,componentId,variantId,hasPendingChanges}:{root:string,directory:string,document:ContextDocument,page:ContextPage,nodeIds:string[],componentId?:string,variantId?:string,hasPendingChanges:boolean}){
 if(componentId?!document.components[componentId]:!document.pages.some(item=>item.id===page.id))return;
 const ids=[...new Set(nodeIds)];
 if(!ids.length||ids.some(id=>!containsNode(page.nodes,id)))return;
 const documentPath=[directory,'Design/studio/project.json'].filter(Boolean).join('/');
 return {file:absolutePath(root,documentPath),...(componentId?{component_id:componentId}:{page_id:page.id}),...(ids.length===1?{node_id:ids[0]}:{node_ids:ids}),
  ...(variantId?{variant_id:variantId}:{}),...(hasPendingChanges?{has_pending_changes:true}:{})};
}
