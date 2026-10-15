import {parseRichMarkdown} from './rich-markdown';
self.onmessage=(event:MessageEvent<{text:string}>)=>{
 try{self.postMessage({parsed:parseRichMarkdown(event.data.text)});}catch(error){self.postMessage({error:String(error)});}
};
