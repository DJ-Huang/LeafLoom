// Source resolution follows the runtime projection order: bindings/variants,
// then component-instance overrides. It never changes the authored document.
type ImageNode={id:string,type:string,name?:string,props:Record<string,any>,children?:ImageNode[]};
type ImageDocument={assets:Record<string,{id:string,name:string,path:string}>,components:Record<string,{node:ImageNode}>,bindings?:Record<string,{kind:string,value:string}>,variants?:Record<string,{values?:Record<string,{value:string}>}>};
export type DesignImageSource={name:string,path?:string,error?:string,staticCopy?:boolean};
function projected(node:ImageNode,document:ImageDocument,variantId:string):ImageNode{
 const props={...node.props},binding=props.bindingKey!=null?document.bindings?.[props.bindingKey]:undefined;
 if(props.bindingKey!=null&&!binding)throw new Error('design.imageBindingMissing');
 if(binding?.kind==='image'){
  const override=document.variants?.[variantId]?.values?.[props.bindingKey];
  props.assetId=override&&Object.hasOwn(override,'value')?override.value:binding.value;delete props.src;
 }
 return {...node,props};
}
export function designImageSource(document:ImageDocument,node:ImageNode,directory:string,variantId=''):DesignImageSource|null{
 if(!['image','instance'].includes(node.type)&&!(node.type==='element'&&String(node.props.tag).toLowerCase()==='img'))return null;
 const original=node,seen=new Set<string>();
 try{
  if(variantId&&!document.variants?.[variantId])throw new Error('design.imageBindingMissing');
  node=projected(node,document,variantId);
  while(node.type==='instance'){
   const id=node.props.componentId,component=document.components[id];
   if(!component||seen.has(id))return null;
   seen.add(id);
   const raw=node.props.overrides||{},ids=new Set<string>();
   const collect=(item:ImageNode)=>{ids.add(item.id);item.children?.forEach(collect);};collect(component.node);
   const keyed=Object.entries(raw).some(([key,value]:[string,any])=>ids.has(key)||value&&typeof value==='object'&&(value.style||value.props));
   const root=projected(component.node,document,variantId),patch=keyed?raw[root.id]?.props:raw;
   node={...root,props:{...root.props,...patch}};
  }
  if(node.type!=='image'&&!(node.type==='element'&&String(node.props.tag).toLowerCase()==='img'))return null;
  const asset=node.props.assetId?document.assets[node.props.assetId]:undefined;
  if(node.props.assetId&&!asset)throw new Error('design.imageAssetMissing');
  let path=asset?.path??node.props.src??node.props.path;
  if(typeof path!=='string'||!path)throw new Error('design.imageSourceMissing');
  if(/^(?:[a-z][\w+.-]*:|\/\/)/i.test(path))throw new Error('design.imageExternalSource');
  if(!asset){path=decodeURIComponent(path.split(/[?#]/)[0]).replace(/^__STUDIO_ASSET__\//,'').replace(/^\//,'');}
  const parts=path.split('/');
  if(parts.some((part:string)=>part==='..'||/[\\:\x00-\x1f]/.test(part))||path.startsWith('/'))throw new Error('design.imageSourceInvalid');
  path=parts.filter((part:string)=>part&&part!=='.').join('/');
  if(!path)throw new Error('design.imageSourceMissing');
  return {name:asset?.name||path.split('/').pop()!,path:[directory,path].filter(Boolean).join('/'),staticCopy:/\.(svg|gif|webp|avif)$/i.test(path)};
 }catch(error){return {name:original.name||'',error:error instanceof URIError?'design.imageSourceInvalid':(error as Error).message};}
}
