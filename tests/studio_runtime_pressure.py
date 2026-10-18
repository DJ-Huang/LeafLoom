"""Explicit synthetic browser measurements; not a substitute for app acceptance.

Run with ``python tests/studio_runtime_pressure.py``. Uses the same Chromium
setup as studio_runtime_browser.py and prints a machine-readable report.
"""
from __future__ import annotations

import json
import math

from studio_runtime_browser import StudioRuntimeBrowserTests


def metrics(session):
    return {item["name"]: item["value"] for item in session.send("Performance.getMetrics")["metrics"]}


def metrics_delta(before, after):
    names = ("LayoutCount", "RecalcStyleCount", "LayoutDuration", "RecalcStyleDuration", "ScriptDuration", "TaskDuration")
    return {name + ("Ms" if name.endswith("Duration") else ""): round((after[name] - before[name]) * (1000 if name.endswith("Duration") else 1), 4) for name in names}


def main():
    fixture = StudioRuntimeBrowserTests()
    fixture.setUpClass()
    fixture.setUp()
    try:
        page = fixture.page
        session = page.context.new_cdp_session(page)
        session.send("Performance.enable")
        result = page.evaluate("""async () => {
          const nodes=Array.from({length:2000},(_,i)=>({id:'node-'+i,type:'shape',style:{x:(i%50)*36,y:Math.floor(i/50)*36,width:30,height:30,background:i%2?'#6f91ef':'#a9bcfa'},props:{}}));
          nodes[0].script={source:'export function mount(ctx){ctx.on(\\'click\\',()=>{});ctx.setInterval(()=>{},10000);ctx.onFrame(()=>{});return ()=>{};}'};
          nodes[0].animation={preset:'breathe',iterations:'Infinity'};
          const assets=Object.fromEntries(Array.from({length:5000},(_,i)=>['asset-'+i,{id:'asset-'+i,name:'Image '+i,path:'Design/Assets/Imported/image-'+i+'.png',width:512,height:512,tags:['synthetic']} ]));
          const document={schemaVersion:1,id:'pressure',name:'Pressure',assets,components:{},styles:{},scripts:{},pages:Array.from({length:100},(_,i)=>({id:'page-'+i,name:'Page '+i,width:1800,height:1600,nodes:i?[]:nodes}))};
          if(window.instance) window.instance.dispose();
          window.events=[];
          const start=performance.now();
          window.instance=LeafLoomStudio.mount(window.document.getElementById('studio-root'),document,{pageId:'page-0',mode:'edit',onMessage:event=>events.push(event)});
          await window.document.fonts.ready;
          await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
          const coldMountMs=performance.now()-start;
          const switches=[];
          for(let i=0;i<12;i++){
            instance.navigate('page-1');
            const start=performance.now();instance.navigate('page-0');
            await new Promise(resolve=>requestAnimationFrame(resolve));switches.push(performance.now()-start);
          }
          const before=instance.debugStats;
          let previewPeak=null;
          for(let i=0;i<12;i++){
            instance.setMode('preview','node-0');
            const deadline=performance.now()+1000;
            while(!instance.debugStats.timers&&performance.now()<deadline) await new Promise(resolve=>setTimeout(resolve,5));
            if(!instance.debugStats.timers) throw new Error('Preview script did not mount: '+JSON.stringify(events));
            previewPeak=instance.debugStats;
            instance.setMode('edit');
          }
          const after=instance.debugStats;
          const node=window.document.querySelector('[data-studio-select-id="node-0"]');
          const rect=node.getBoundingClientRect();
          window.sampleFrames=async(count,move)=>{
            const intervals=[];let previous;
            await new Promise(resolve=>requestAnimationFrame(function tick(now){
              if(previous!=null) intervals.push(now-previous);previous=now;
              if(move)move(intervals.length);
              if(intervals.length<count)requestAnimationFrame(tick);else resolve();
            }));
            return intervals;
          };
          window.pressureReport={coldMountMs,switches,before,previewPeak,after,nodeCount:2000,assetCount:5000,pageCount:100};
          return {x:rect.x+rect.width/2,y:rect.y+rect.height/2};
        }""")
        page.evaluate("window.baselineIntervalsPromise=sampleFrames(120);null")
        baseline = page.evaluate("baselineIntervalsPromise")
        page.mouse.move(result["x"], result["y"])
        page.mouse.down()
        page.evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
        ipc_before = metrics(session)
        page.evaluate("window.frameIntervals=[];window.lastFrame=performance.now();window.frameTracking=true;requestAnimationFrame(function tick(now){if(!frameTracking)return;frameIntervals.push(now-lastFrame);lastFrame=now;requestAnimationFrame(tick);});")
        for index in range(60):
            page.mouse.move(result["x"] + index * .3, result["y"] + index * .2)
            page.evaluate("new Promise(resolve=>requestAnimationFrame(resolve))")
        ipc_after = metrics(session)
        ipc_stats = page.evaluate("instance.debugStats")
        page.mouse.up()
        page.evaluate("window.frameTracking=false")
        rect = page.locator('[data-studio-select-id="node-0"]').bounding_box()
        local_x, local_y = rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2
        page.mouse.move(local_x, local_y)
        page.evaluate("document.querySelector('.studio-viewport').addEventListener('pointerdown',e=>window.pressurePointerId=e.pointerId,{once:true})")
        page.mouse.down()
        page.evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
        local_before = metrics(session)
        local_intervals = page.evaluate("""async ({x,y})=>{
          const node=document.querySelector('[data-studio-select-id="node-0"]');
          return sampleFrames(120,index=>node.dispatchEvent(new PointerEvent('pointermove',{pointerId:pressurePointerId,pointerType:'mouse',button:0,buttons:1,bubbles:true,clientX:x+index*.15,clientY:y+index*.1})));
        }""", {"x": local_x, "y": local_y})
        page.evaluate("new Promise(resolve=>requestAnimationFrame(resolve))")
        local_after = metrics(session)
        local_stats = page.evaluate("instance.debugStats")
        page.mouse.up()
        report = page.evaluate("""() => {
          const p95=values=>[...values].sort((a,b)=>a-b)[Math.max(0,Math.ceil(values.length*.95)-1)];
          return {...pressureReport,warmPageSwitchP95Ms:p95(pressureReport.switches),automationDragFrameP95Ms:p95(frameIntervals.slice(1)),automationDragFrames:frameIntervals.length,commits:events.filter(e=>e.type==='studio-commit').length,final:instance.debugStats,userAgent:navigator.userAgent};
        }""")
        p95 = lambda values: sorted(values)[max(0, math.ceil(len(values) * .95) - 1)]
        report.update(baselineFrameP95Ms=p95(baseline), baselineFrameSamples=len(baseline),
                      browserLocalDragFrameP95Ms=p95(local_intervals), browserLocalDragFrames=len(local_intervals),
                      automationDragWorkP95Ms=ipc_stats["gestureWorkP95Ms"], browserLocalDragWorkP95Ms=local_stats["gestureWorkP95Ms"],
                      automationBrowserWork=metrics_delta(ipc_before, ipc_after), browserLocalBrowserWork=metrics_delta(local_before, local_after))
        report["budgets"] = {"rawDrag20MsMet": report["browserLocalDragFrameP95Ms"] <= 20 and report["automationDragFrameP95Ms"] <= 20,
                             "baselineBelow20Ms": report["baselineFrameP95Ms"] <= 20,
                             "dragWork16MsMet": report["browserLocalDragWorkP95Ms"] <= 16,
                             "dragWithinIdleBaselinePlus1Ms": report["browserLocalDragFrameP95Ms"] <= report["baselineFrameP95Ms"] + 1}
        print(json.dumps(report, indent=2))
        assert report["commits"] == 2, report
        assert local_stats["gestureWorkSamples"] >= 100, report
        assert report["budgets"]["dragWork16MsMet"], report
        assert report["browserLocalBrowserWork"]["LayoutCount"] == 0, report
        assert report["before"]["handles"] == 0, report
        for key in ("listeners", "timers", "frames", "animations", "objectUrls", "previewGroups"):
            assert report["after"][key] == 0, (key, report)
    finally:
        fixture.tearDown()
        fixture.tearDownClass()


if __name__ == "__main__":
    main()
