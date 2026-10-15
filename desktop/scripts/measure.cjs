// One idle Windows snapshot, no model, no user data or global login changes.
'use strict';
const {_electron}=require('playwright-core');
const fs=require('node:fs'),path=require('node:path'),net=require('node:net');
const {execFileSync}=require('node:child_process');
(async()=>{
 if(process.platform!=='win32')throw new Error('This working-set snapshot uses Windows process counters');
 const root=fs.mkdtempSync(path.join(process.env.LOCALAPPDATA,'Temp','LeafLoom-measure-'));
 const state=path.join(root,'state');fs.mkdirSync(state);
 const listener=net.createServer();await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));const port=listener.address().port;await new Promise(resolve=>listener.close(resolve));
 fs.writeFileSync(path.join(state,'config.json'),JSON.stringify({root:null,port,include_roots:[],exclude_roots:[],rules_roots:[],wiki_roots:[],estimation_roots:[],write_targets:{notes:'Notes'},homepage:'',templates:'Templates',daily_folder:'Daily'}));
 fs.writeFileSync(path.join(state,'desktop-preferences.json'),'{}');
 let application,child;
 try{
  const env={...process.env,VAULT_RAG_HOME:state,LEAFLOOM_REGISTRATION_HOME:path.join(root,'registration')};delete env.ELECTRON_RUN_AS_NODE;
  application=await _electron.launch({executablePath:path.resolve(process.env.LEAFLOOM_DESKTOP_EXECUTABLE),env,timeout:120000});child=application.process();
  const page=await application.firstWindow();await page.waitForURL('http://127.0.0.1:'+port+'/',{timeout:110000});await page.locator('main').waitFor();await page.waitForTimeout(2000);
  const metrics=await application.evaluate(({app})=>app.getAppMetrics());
  const browserPid=await application.evaluate(()=>process.pid);
  const pids=[...new Set([child.pid,...metrics.map(m=>m.pid)])];
  const script=`$TaskAppPids=@(${pids.join(',')}); $TaskBackend=Get-CimInstance Win32_Process -Filter 'ParentProcessId=${browserPid}' | Where-Object Name -eq 'python.exe'; $TaskAppPids+=@($TaskBackend.ProcessId); @($TaskAppPids | Sort-Object -Unique | ForEach-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,WorkingSet64,PrivateMemorySize64 }) | ConvertTo-Json -Compress`;
  const powershell=path.join(process.env.SystemRoot,'System32','WindowsPowerShell','v1.0','powershell.exe');
  const rows=JSON.parse(execFileSync(powershell,['-NoProfile','-NonInteractive','-Command',script],{encoding:'utf8',windowsHide:true}));
  const result={platform:'win32',scenario:'Idle welcome window; retrieval model not loaded',processes:rows,privateCommitBytes:rows.reduce((n,p)=>n+p.PrivateMemorySize64,0),summedWorkingSetBytes:rows.reduce((n,p)=>n+p.WorkingSet64,0),workingSetNote:'Per-process working sets include shared pages; their sum is not unique physical memory.'};
  const out=path.resolve(__dirname,'../../.cache/desktop-acceptance/memory.json');fs.writeFileSync(out,JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  await page.evaluate(()=>{void window.leafloomDesktop.quit();});await new Promise(resolve=>{if(child.exitCode!==null)return resolve();child.once('exit',resolve);});
 }finally{if(application&&child?.exitCode===null)await application.close();fs.rmSync(root,{recursive:true,force:true,maxRetries:5,retryDelay:200});}
})().catch(e=>{console.error(e);process.exitCode=1;});
