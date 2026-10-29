export type PresenterNotes={overview:string,cues:Record<string,string>};
export type PresenterPage={id:string,name:string,width:number,height:number,background?:string,nodes:any[],presenterNotes?:PresenterNotes,[key:string]:any};
export type PresenterDocument={schemaVersion:number,id:string,name:string,pages:PresenterPage[],[key:string]:any};
export type PresenterDisplay={id:number,label:string,bounds:{x:number,y:number,width:number,height:number},workArea:{x:number,y:number,width:number,height:number},scaleFactor:number,current:boolean};
export type PresenterState={pageId?:string,stepId?:string,stepIndex?:number,stepCount?:number,contextId?:string,contextLabel?:string,label?:string,parameter?:string,playing?:boolean,paused?:boolean,black?:boolean,inputFocused?:boolean,supported?:boolean};
export type PresenterEvent={type:'frame'|'state'|'ended'|'displays',id?:string,state?:PresenterState,suspended?:boolean,reason?:string,seq?:number,jpeg?:Uint8Array,width?:number,height?:number,displays?:PresenterDisplay[]};
export type PresenterCommand={action:'next'|'previous'|'page'|'pause'|'resume'|'black'|'reopen'|'swap',pageId?:string,enabled?:boolean,displayId?:number};
export type PresenterInput={kind:'move'|'down'|'up'|'wheel'|'key',x?:number,y?:number,button?:number,buttons?:number,clickCount?:number,dx?:number,dy?:number,key?:string,code?:string,phase?:'down'|'up',shift?:boolean,alt?:boolean};
export type PresenterSession={id:string,origin:string,url?:string};
export type PresenterDesktop={
 displays:()=>Promise<PresenterDisplay[]>,identify:()=>Promise<void>,
 start:(input:{document:PresenterDocument,pageId:string,pageIds?:string[],session:PresenterSession,displayId:number,controllerDisplayId?:number,fullscreen:boolean})=>Promise<{id:string,displayId:number}>,
 command:(id:string,command:PresenterCommand)=>Promise<void>,input:(id:string,input:PresenterInput)=>Promise<void>,
 ack:(id:string,seq:number)=>Promise<void>,heartbeat:(id:string)=>Promise<void>,stop:(id:string)=>Promise<void>,
 subscribe:(callback:(value:PresenterEvent)=>void)=>()=>void
};
export function audienceDocument(document:PresenterDocument):PresenterDocument {
 const value=structuredClone(document);
 for(const page of value.pages)delete page.presenterNotes;
 return value;
}
