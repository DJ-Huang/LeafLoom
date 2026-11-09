'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),{EventEmitter}=require('node:events');
const {CalendarNotifications}=require('../calendar.cjs');
test('catch-up is grouped, failures acknowledged, and old vault clicks ignored',async()=>{
 const shown=[],acks=[],opened=[];let root='one',rows=[{id:'1',date:'2026-11-06',title:'one',late:true},{id:'2',date:'2026-11-06',title:'two',late:true}];
 class Notification extends EventEmitter{static isSupported(){return true;}constructor(options){super();this.options=options;}show(){shown.push(this);this.emit('show');}close(){this.closed=true;}}
 const request=async(route,body)=>{if(route==='/api/calendar/reminders/state')return {config:{root,revision:'revision'}};if(route.endsWith('/claim')){const result={root,results:rows};rows=[];return result;}acks.push(body);return {};};
 const notifier=new CalendarNotifications({Notification,request,open:v=>opened.push(v),text:()=>({calendarTitle:'Calendar',calendarMissed:'{count} missed',calendarSummary:'{count} today, {overdue} overdue'})});
 await notifier.poll();assert.equal(shown.length,1);assert.equal(shown[0].options.body,'2 missed');assert.equal(acks.length,2);
 await notifier.poll();assert.equal(shown.length,1);
 root='two';shown[0].emit('click');await new Promise(r=>setImmediate(r));assert.equal(opened.length,0);
 await notifier.poll();assert.equal(shown[0].closed,true);
 rows=[{id:'3',date:'2026-11-06',title:'new'}];Notification.isSupported=()=>false;await notifier.poll();assert.equal(acks.at(-1).state,'failed');notifier.stop();
});
