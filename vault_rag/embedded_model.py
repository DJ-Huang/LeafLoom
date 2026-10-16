"""One process-local BGE-M3 model; normal inference never downloads weights."""
from __future__ import annotations
import hashlib, io, json, os, threading, time, uuid
from pathlib import Path
from vault_rag.local_state import atomic_write,digest

class EmbeddedModel:
    model_id='BAAI/bge-m3'
    def __init__(self,directory):
        self.directory=Path(directory);self.path=self.directory/'models/bge-m3';self.manifest=self.directory/'models/model-lock.json'
        self.model_path=str(self.path.resolve())
        self.model=None;self.lock=threading.RLock();self.loading=False;self.error=None;self.device=None;self.loads=0;self.load_seconds=None;self.download_state=None;self.warmed=False;self.warmup_seconds=None;self.warming=False
        self._prepared=False;self._status_fingerprint=None;self.integrity_checked_at=None;self.preparation=None;self.progress_lock=threading.Lock()
    def _stage(self,state,**extra):
        now=time.time()
        with self.progress_lock:self.preparation={**(self.preparation or {}),'state':state,'updated_at':now,**extra}
    def _download_progress(self):
        # Hub's public tqdm hook reports file completion and actual byte transfer.
        # Keep it silent: stdout is the worker's control channel, not a terminal.
        from tqdm.auto import tqdm
        model=self
        received_base=(self.preparation or {}).get('downloaded_bytes',0)
        class Progress(tqdm):
            def __init__(self,*args,**kwargs):
                self.byte_progress=kwargs.get('unit')=='B'
                self.reconstruction=str(kwargs.get('desc','')).startswith('Reconstruct')
                kwargs.pop('name',None);kwargs['disable']=False;kwargs['file']=io.StringIO()
                super().__init__(*args,**kwargs)
                self.last_report=time.time();self.last_bytes=self.n;self.initial_bytes=self.n
            def display(self,*args,**kwargs):pass
            def update(self,n=1):
                result=super().update(n)
                now=time.time()
                if not self.reconstruction and (now-self.last_report>=.2 or self.n==self.total):
                    if self.byte_progress:
                        rate=max(0,self.n-self.last_bytes)/max(.001,now-self.last_report)
                        model._stage('downloading',downloaded_bytes=received_base+max(0,int(self.n-self.initial_bytes)),bytes_per_second=rate)
                        self.last_bytes=self.n
                    else:model._stage('downloading',completed_files=int(self.n))
                    self.last_report=now
                return result
        return Progress
    @property
    def ready(self):
        try:
            receipt=json.loads(self.manifest.read_text(encoding='utf-8'))
            if receipt.get('model')!=self.model_id or not receipt.get('revision'):return False
            files=receipt.get('files',{})
            if not files:return False
            for name,info in files.items():
                path=self.path/name
                if not path.resolve().is_relative_to(self.path.resolve()) or not path.is_file() or path.stat().st_size!=info['size']:return False
                # Check small config/tokenizer files; don't reread gigabytes on every status poll.
                if info.get('sha256') and info['size']<=1024*1024 and hashlib.sha256(path.read_bytes()).hexdigest()!=info['sha256']:return False
            return self._required_files()
        except (OSError,ValueError,KeyError,TypeError):return False
    def _required_files(self):
        weights=self.path/'model.safetensors'
        if not weights.is_file():weights=self.path/'pytorch_model.bin'
        tokenizer=any((self.path/name).is_file() and (self.path/name).stat().st_size>0 for name in ('tokenizer.json','sentencepiece.bpe.model','spiece.model'))
        return (self.path/'config.json').is_file() and (self.path/'tokenizer_config.json').is_file() and weights.is_file() and weights.stat().st_size>0 and tokenizer
    def _receipt(self,revision,names,verified=None):
        files={}
        for name in names:
            path=self.path/name
            if path.is_file():
                checksum=(verified or {}).get(name)
                if not checksum:
                    with path.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
                files[name]={'size':path.stat().st_size,'sha256':checksum}
        atomic_write(self.manifest,json.dumps({'model':self.model_id,'revision':revision,'prepared_at':time.time(),'files':files},indent=2).encode())
        self.refresh_status()
    @property
    def fingerprint(self):
        if not self.ready:return None
        return self._fingerprint()
    def _fingerprint(self):
        m=json.loads(self.manifest.read_text(encoding='utf-8'))
        return digest(json.dumps({'model':self.model_id,'revision':m['revision'],'pooling':'official-sentence-transformers','normalize':True,'dimension':1024,'backend':'torch','dtype':'float32','input_version':1},sort_keys=True))
    def refresh_status(self):
        prepared=self.ready
        try:fingerprint=self._fingerprint() if prepared else None
        except (OSError,ValueError,KeyError):prepared=False;fingerprint=None
        self._prepared=prepared;self._status_fingerprint=fingerprint;self.integrity_checked_at=time.time()
        return self.status()
    def status(self):return {'model':self.model_id,'path':self.model_path,'prepared':self._prepared,'loaded':self.model is not None,'loading':self.loading,'error':self.error,'device':self.device,'load_count':self.loads,'load_seconds':self.load_seconds,'download':self.download_state,'preparation':dict(self.preparation) if self.preparation else None,'fingerprint':self._status_fingerprint,'warmed':self.warmed,'warming':self.warming,'warmup_seconds':self.warmup_seconds,'integrity_checked_at':self.integrity_checked_at}
    def prepare(self):
        with self.lock:
            self.preparation={'state':'checking','started_at':time.time(),'updated_at':time.time()}
            self.download_state='下载模型中';self.error=None
            try:
                if self.ready:
                    self.refresh_status();self._stage('ready');self.download_state='模型已准备';return self.status()
                previous={}
                try:previous=json.loads(self.manifest.read_text(encoding='utf-8'))
                except (OSError,ValueError):pass
                # Adopt complete legacy downloads locally, without fetching a new model revision.
                if previous.get('revision') and not previous.get('files') and self._required_files():
                    names=[p.relative_to(self.path).as_posix() for p in self.path.rglob('*') if p.is_file() and '.cache' not in p.parts]
                    self._stage('verifying',total_files=len(names),completed_files=0)
                    self._receipt(previous['revision'],names)
                    self._stage('ready');self.download_state='模型已准备';return self.status()
                os.environ.setdefault('HF_HUB_DISABLE_XET','1')
                from huggingface_hub import HfApi,snapshot_download,hf_hub_download
                pending=self.directory/'models/model-download.json'
                try:pending_data=json.loads(pending.read_text())
                except (OSError,ValueError):pending_data={}
                revision=previous.get('revision') or pending_data.get('revision')
                self._stage('connecting')
                info=HfApi().model_info(self.model_id,revision=revision,files_metadata=True)
                revision=info.sha
                atomic_write(pending,json.dumps({'model':self.model_id,'revision':revision}).encode())
                has_safe=any(item.rfilename=='model.safetensors' for item in info.siblings)
                suffixes=('.json','.safetensors','.model','.txt') if has_safe else ('.json','.bin','.model','.txt')
                names=[item.rfilename for item in info.siblings if item.rfilename.endswith(suffixes)]
                self.path.mkdir(parents=True,exist_ok=True)
                self._stage('downloading',total_files=len(names),completed_files=0,downloaded_bytes=0)
                snapshot_download(self.model_id,revision=revision,local_dir=self.path,allow_patterns=names,tqdm_class=self._download_progress())
                self._stage('verifying',completed_files=0)
                verified={}
                for index,item in enumerate(item for item in info.siblings if item.rfilename in names):
                    self._stage('verifying',current_file=item.rfilename,completed_files=index)
                    path=self.path/item.rfilename
                    if not path.resolve().is_relative_to(self.path.resolve()):raise RuntimeError('模型文件路径越界')
                    expected=item.lfs.sha256 if item.lfs else previous.get('files',{}).get(item.rfilename,{}).get('sha256')
                    def valid():
                        if not path.is_file() or (item.size is not None and path.stat().st_size!=item.size):return False
                        if not expected:return True
                        with path.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
                        if checksum==expected:verified[item.rfilename]=checksum
                        return checksum==expected
                    if not valid():
                        # Hub metadata can report an already-downloaded, damaged file as
                        # cached. Preserve it outside the active model and fetch it again.
                        if path.exists():
                            backup=self.directory/'models'/('damaged-'+uuid.uuid4().hex)/item.rfilename
                            backup.parent.mkdir(parents=True,exist_ok=True);path.rename(backup)
                        self._stage('downloading',current_file=item.rfilename)
                        hf_hub_download(self.model_id,item.rfilename,revision=revision,local_dir=self.path,force_download=True,tqdm_class=self._download_progress())
                        self._stage('verifying',current_file=item.rfilename)
                        if not valid():raise RuntimeError('模型文件校验失败：'+item.rfilename)
                if not self._required_files():raise RuntimeError('模型缺少权重或 tokenizer，下载未完成')
                self._stage('saving',completed_files=len(names),current_file=None)
                self._receipt(revision,names,verified)
                pending.unlink(missing_ok=True)
                self._stage('ready');self.download_state='模型已准备';return self.status()
            except Exception as e:self.error=str(e);self._stage('failed',failed_stage=self.preparation['state']);self.download_state='下载失败';raise
    def load(self):
        with self.lock:
            if self.model is not None:return
            if not self.ready:raise RuntimeError('请先准备本地 BGE-M3 模型')
            self.loading=True;start=time.perf_counter()
            try:
                import torch
                torch.set_num_threads(2)
                try:torch.set_num_interop_threads(2)
                except RuntimeError:pass  # Another torch user may already have started work.
                os.environ.setdefault('RAYON_NUM_THREADS','2')
                from sentence_transformers import SentenceTransformer
                self.device='mps' if torch.backends.mps.is_available() else 'cpu'
                try:self.model=SentenceTransformer(str(self.path),device=self.device,local_files_only=True,trust_remote_code=False)
                except Exception:
                    if self.device!='mps':raise
                    self.device='cpu';self.model=SentenceTransformer(str(self.path),device='cpu',local_files_only=True,trust_remote_code=False)
                self.model.max_seq_length=8192;self.loads+=1;self.load_seconds=time.perf_counter()-start;self.error=None
            except Exception as e:self.error=str(e);raise
            finally:self.loading=False;self.refresh_status()
    def warmup(self):
        if self.warmed:return
        self.warming=True;start=time.perf_counter()
        try:
            self.encode(['知识库检索 工时评估 Markdown Unity Blender 模型预热'])
            self.warmed=True;self.warmup_seconds=time.perf_counter()-start
        finally:self.warming=False
    def tokenizer(self):
        # Chunking needs token boundaries, not a loaded multi-gigabyte model.
        if not hasattr(self,'_tokenizer'):
            from transformers import AutoTokenizer
            self._tokenizer=AutoTokenizer.from_pretrained(str(self.path),local_files_only=True,trust_remote_code=False)
        return self._tokenizer
    def encode(self,texts):
        with self.lock:
            self.load()
            try:return self.model.encode(texts,batch_size=4,normalize_embeddings=True,show_progress_bar=False).tolist()
            except Exception as e:
                if self.device=='mps':
                    self.model.to('cpu');self.device='cpu'
                    return self.model.encode(texts,batch_size=2,normalize_embeddings=True,show_progress_bar=False).tolist()
                self.error=str(e);raise

# Compatibility adapter for CLI/LlamaIndex consumers; only the shared HTTP service
# should be used by normal clients so this model does not get duplicated.
def llama_embedding(directory):
    from llama_index.core.base.embeddings.base import BaseEmbedding
    from pydantic import PrivateAttr
    class LocalEmbedding(BaseEmbedding):
        _local:EmbeddedModel=PrivateAttr()
        def __init__(self):super().__init__(model_name='BAAI/bge-m3');self._local=EmbeddedModel(directory)
        def _get_query_embedding(self,query):return self._local.encode([query])[0]
        def _get_text_embedding(self,text):return self._local.encode([text])[0]
        def _get_text_embeddings(self,texts):return self._local.encode(texts)
        async def _aget_query_embedding(self,query):
            import asyncio
            return await asyncio.to_thread(self._get_query_embedding,query)
    return LocalEmbedding()
