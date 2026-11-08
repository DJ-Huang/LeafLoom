'use strict';
// Only the main process owns delivery. Renderer reloads cannot duplicate notices.
class CalendarNotifications {
  constructor({Notification, request, open, text, current=()=>true}) {
    Object.assign(this,{Notification,request,open,text,current});this.active=new Set();this.scope='';this.busy=false;this.stopped=false;
  }
  async poll() {
    if(this.busy||this.stopped||!this.current())return;
    this.busy=true;
    try {
      const session=await this.request('/api/calendar/reminders/state');
      if(this.stopped||!this.current())return;
      const scope=JSON.stringify([session.config.root,session.config.revision]);
      if(scope!==this.scope){for(const n of this.active)n.close();this.active.clear();this.scope=scope;}
      if(!session.config.root)return;
      const owner={root:session.config.root,workspace_revision:session.config.revision};
      const page=await this.request('/api/calendar/reminders/claim',owner);
      if(this.stopped||!this.current()||page.root!==owner.root)return;
      const rows=page.results;
      if(!rows.length)return;
      // Recovery after sleep/restart produces one catch-up notification.
      const late=rows.filter(r=>r.late), groups=[...rows.filter(r=>!r.late).map(r=>[r]),...(late.length?[late]:[])];
      for(const group of groups){
        if(this.stopped||!this.current()||this.scope!==scope)break;
        const row=group[0],labels=this.text();
        const summary=group.length>1||row.late;
        const options={title:labels.calendarTitle,body:summary?labels.calendarMissed.replace('{count}',String(group.length)):row.kind==='summary'?labels.calendarSummary.replace('{count}',String(row.count)).replace('{overdue}',String(row.overdue)):String(row.title).slice(0,500)};
        const ack=state=>Promise.allSettled(group.map(r=>this.request('/api/calendar/reminders/ack',{...owner,id:r.id,state})));
        if(!this.Notification.isSupported()){await ack('failed');continue;}
        let notification;
        try{
          notification=new this.Notification(options);this.active.add(notification);
          notification.once('show',()=>void ack('sent'));
          notification.once('failed',()=>{this.active.delete(notification);void ack('failed');});
          notification.once('close',()=>this.active.delete(notification));
          notification.once('click',()=>void (async()=>{
            if(this.stopped||!this.current()||this.scope!==scope)return;
            const fresh=await this.request('/api/calendar/reminders/state');
            if(fresh.config.root!==owner.root||fresh.config.revision!==owner.workspace_revision)return;
            if(!/^\d{4}-\d{2}-\d{2}$/.test(row.date))return;
            await this.open({root:owner.root,date:row.date,...(!summary&&row.item_id?{item_id:row.item_id}:{})});
          })().catch(()=>{}));
          notification.show();
        }catch{if(notification)this.active.delete(notification);await ack('failed');}
      }
    }catch{/* The durable inbox remains available during backend restart or permission failure. */}
    finally{this.busy=false;}
  }
  start(){void this.poll();this.timer=setInterval(()=>void this.poll(),15000);this.timer.unref?.();}
  stop(){this.stopped=true;clearInterval(this.timer);for(const n of this.active)n.close();this.active.clear();}
}
module.exports={CalendarNotifications};
