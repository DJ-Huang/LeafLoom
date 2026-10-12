import {blocks,createMarkdown,hasMath} from './markdown-core';
self.onmessage=async(event:MessageEvent<{text:string}>)=>{
 try{const md=createMarkdown();if(hasMath(event.data.text)){const plugin=await import('@traptitech/markdown-it-katex');md.use(plugin.default,{throwOnError:false});}self.postMessage({blocks:blocks(md,event.data.text)});}
 catch(error){self.postMessage({error:String(error)});}
};
