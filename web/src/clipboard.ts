function copyWithSelection(text:string):boolean{
 const previous=document.activeElement as HTMLElement|null,selection=document.getSelection();
 const ranges=selection?Array.from({length:selection.rangeCount},(_,index)=>selection.getRangeAt(index).cloneRange()):[];
 const field=document.createElement('textarea');
 field.value=text;field.readOnly=true;field.style.cssText='position:fixed;left:-9999px;top:0;opacity:0';
 document.body.appendChild(field);
 try{field.focus({preventScroll:true});field.select();return document.execCommand('copy');}
 catch{return false;}
 finally{
  field.remove();if(previous?.isConnected)previous.focus({preventScroll:true});
  if(selection){selection.removeAllRanges();ranges.forEach(range=>selection.addRange(range));}
 }
}

export async function writeClipboardText(text:string):Promise<void>{
 const desktop=window.leafloomDesktop;
 if(desktop?.writeClipboardText){await desktop.writeClipboardText(text);return;}
 // A running desktop may still have the previous preload until it restarts.
 if(desktop&&copyWithSelection(text))return;
 try{await navigator.clipboard.writeText(text);}
 catch(error){if(!copyWithSelection(text))throw error;}
}
