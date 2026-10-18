export type AiReference={root:string,path:string,text:string,kind?:'design',label?:string};
export type AiSelectionEvent={reference:AiReference};
export function addAiReference(reference:AiReference){window.dispatchEvent(new CustomEvent<AiSelectionEvent>('vault-ai-reference',{detail:{reference}}));}
