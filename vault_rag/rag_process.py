"""Private serial RAG process; heavy imports never execute in the HTTP service."""
from __future__ import annotations
import json, os, queue, subprocess, sys, threading, time, uuid
from pathlib import Path

class RagCancelled(RuntimeError):pass

class RagProcess:
    def __init__(self,config,on_status=None,command=None):
        self.config=config;self.on_status=on_status;self.command=command
        self.process=None;self.pending={};self.lock=threading.RLock();self.write_lock=threading.Lock()
        self.state={'state':'idle','pid':None,'error':None};self.model_status={};self.progress={}
        self.active=None;self.paused=False;self.closed=False
        self.job=None

    def start(self):
        with self.lock:
            if self.closed:raise RuntimeError('RAG service is stopping')
            if self.process and self.process.poll() is None:return
            env=dict(os.environ,VAULT_RAG_HOME=str(self.config.directory),OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',RAYON_NUM_THREADS='2')
            env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
            isolation=['-I'] if Path(__file__).resolve().parent.parent.name=='site-packages' else []
            cmd=self.command or [sys.executable,*isolation,'-B','-X','utf8','-m','vault_rag.rag_worker']
            # Source runs need their checkout; packaged runs resolve installed modules.
            cwd=Path(__file__).resolve().parent.parent
            options={'creationflags':subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS} if os.name=='nt' else {'start_new_session':True}
            log=self.config.directory/'logs/rag-worker.log';log.parent.mkdir(exist_ok=True)
            with log.open('ab') as stream:
                self.process=subprocess.Popen(cmd,cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stream,text=True,encoding='utf-8',bufsize=1,**options)
            from vault_rag.worker_lifetime import WorkerJob
            if self.job:self.job.close()
            self.job=WorkerJob(self.process)
            self.state={'state':'starting','pid':self.process.pid,'error':None}
            from vault_rag.control_pipe import ControlPipe
            control=ControlPipe(self.process.stdout)
            self.reader=threading.Thread(target=self._read,args=(self.process,control),name='rag-control',daemon=True);self.reader.start()
            if self.paused:self.send({'type':'pause'})

    def send(self,message):
        with self.write_lock:
            if self.process and self.process.poll() is None:
                try:self.process.stdin.write(json.dumps(message,ensure_ascii=False)+'\n');self.process.stdin.flush();return True
                except (OSError,ValueError):pass
            return False

    def _read(self,process,control):
        error='RAG worker exited'
        try:
            for line in control.lines():
                try:value=json.loads(line)
                except ValueError:continue
                kind=value.get('type')
                if kind=='status':
                    if self.process is not process:continue
                    self.model_status=value.get('model',{});self.progress=value.get('progress',{})
                    self.state.update(state=value.get('state','idle'))
                    if self.on_status:self.on_status(value)
                elif kind=='result':
                    with self.lock:pending=self.pending.get(value.get('id'))
                    if pending and pending[0] is process:pending[2].put(value)
        except Exception as exc:error=str(exc)
        finally:
            with self.lock:
                owned=self.process is process
                if owned:self.state.update(state='stopped' if self.closed else 'failed',error=None if self.closed else error)
                for child,_,pending in list(self.pending.values()):
                    if child is process:pending.put({'error':error})
            process.stdout.close()
            if owned and self.on_status:self.on_status({'type':'exit','error':error})

    def request(self,operation,**args):
        self.start();identifier=uuid.uuid4().hex;pending=queue.Queue()
        with self.lock:self.pending[identifier]=(self.process,operation,pending)
        try:
            if operation in ('dense','prepare') and any(op=='build' for _,op,_ in self.pending.values()):self.cancel()
            if not self.send({'type':'request','id':identifier,'operation':operation,'config':dict(self.config.data),**args}):raise RuntimeError('RAG worker unavailable')
            value=pending.get(timeout=600)
            if value.get('cancelled'):raise RagCancelled('RAG task cancelled')
            if value.get('error'):raise RuntimeError(value['error'])
            return value.get('result')
        finally:
            with self.lock:self.pending.pop(identifier,None)

    def pause(self,paused):
        if paused!=self.paused:
            self.paused=paused
            self.send({'type':'pause' if paused else 'resume'})

    def cancel(self):self.send({'type':'cancel'})

    def begin_stop(self):
        with self.lock:
            self.closed=True
            for _,_,pending in list(self.pending.values()):pending.put({'error':'RAG service is stopping'})
        try:
            self.send({'type':'shutdown'})
            if self.process:self.process.stdin.close()
        except (OSError,ValueError):pass

    def stop(self):
        self.begin_stop();process=self.process
        if not process:return
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Only the owned worker; it never launches other programs.
            process.kill();process.wait(timeout=5)
        if self.job:self.job.close()
        if hasattr(self,'reader'):self.reader.join(timeout=1)

class RemoteModel:
    model_id='BAAI/bge-m3'
    def __init__(self,config,process):
        from vault_rag.embedded_model import EmbeddedModel
        self.available=EmbeddedModel(config.directory);self.process=process
        self.download_state=None;self.error=None
    @property
    def ready(self):return self.available.status()['prepared']
    @property
    def fingerprint(self):return self.available.status()['fingerprint']
    def refresh_status(self):self.available.refresh_status();return self.status()
    def status(self):
        return {**self.available.status(),**self.process.model_status,'download':self.process.model_status.get('download') or self.download_state,'error':self.process.model_status.get('error') or self.error}
    def prepare(self):
        self.download_state='下载模型中'
        try:return self.process.request('prepare')
        except Exception as error:self.error=str(error);raise
        finally:self.download_state=None;self.refresh_status()
    def dense(self,query,directory,paths,limit):return self.process.request('dense',query=query,directory=directory,paths=paths,limit=limit)
