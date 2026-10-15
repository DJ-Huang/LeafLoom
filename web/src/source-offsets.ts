// CodeMirror counts a line break as one position; Markdown keeps its original
// bytes, including CRLF and mixed line endings outside edited ranges.
export const editorText=(source:string)=>source.replace(/\r\n?/g,'\n');
export const editorOffset=(source:string,position:number)=>editorText(source.slice(0,Math.max(0,position))).length;
export function sourceOffset(source:string,position:number){let logical=0,at=0;while(at<source.length&&logical<position){at+=source[at]==='\r'&&source[at+1]==='\n'?2:1;logical++;}return at;}
