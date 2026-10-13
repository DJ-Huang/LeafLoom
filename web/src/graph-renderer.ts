// Probe once per page; release the probe so it does not consume a GPU context.
// WebGL availability does not prove hardware acceleration: browsers may use software rendering.
let available:boolean|undefined;
export function graphWebGLAvailable(){
 if(available!==undefined)return available;
 try{
  const canvas=document.createElement('canvas'),gl=canvas.getContext('webgl2');
  available=!!gl&&!gl.isContextLost();
  gl?.getExtension('WEBGL_lose_context')?.loseContext();
 }catch{available=false;}
 return available;
}
