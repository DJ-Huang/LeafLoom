"""One process-local BGE-M3 model; normal inference never downloads weights."""
from __future__ import annotations
import json, os, threading, time
from pathlib import Path
from vault_rag.local_state import atomic_write,digest

class EmbeddedModel:
    model_id='BAAI/bge-m3'
    def __init__(self,directory):
        self.directory=Path(directory);self.path=self.directory/'models/bge-m3';self.manifest=self.directory/'models/model-lock.json'
        self.model=None;self.lock=threading.RLock();self.loading=False;self.error=None;self.device=None;self.loads=0;self.load_seconds=None;self.download_state=None;self.warmed=False;self.warmup_seconds=None;self.warming=False
    @property
    def ready(self):return self.manifest.is_file() and (self.path/'config.json').is_file() and ((self.path/'model.safetensors').is_file() or (self.path/'pytorch_model.bin').is_file())
    @property
    def fingerprint(self):
        if not self.ready:return None
        m=json.loads(self.manifest.read_text())
        return digest(json.dumps({'model':self.model_id,'revision':m['revision'],'pooling':'official-sentence-transformers','normalize':True,'dimension':1024,'backend':'torch','dtype':'float32','input_version':1},sort_keys=True))
    def status(self):return {'model':self.model_id,'prepared':self.ready,'loaded':self.model is not None,'loading':self.loading,'error':self.error,'device':self.device,'load_count':self.loads,'load_seconds':self.load_seconds,'download':self.download_state,'fingerprint':self.fingerprint,'warmed':self.warmed,'warming':self.warming,'warmup_seconds':self.warmup_seconds}
    def prepare(self):
        with self.lock:
            if self.ready:return self.status()
            self.download_state='下载模型中';self.error=None
            try:
                os.environ.setdefault('HF_HUB_DISABLE_XET','1')
                from huggingface_hub import HfApi,snapshot_download
                revision=HfApi().model_info(self.model_id).sha
                self.path.mkdir(parents=True,exist_ok=True)
                snapshot_download(self.model_id,revision=revision,local_dir=self.path,allow_patterns=['*.json','*.safetensors','*.bin','*.model','*.txt'])
                atomic_write(self.manifest,json.dumps({'model':self.model_id,'revision':revision,'prepared_at':time.time()},indent=2).encode())
                self.download_state='模型已准备';return self.status()
            except Exception as e:self.error=str(e);self.download_state='下载失败';raise
    def load(self):
        with self.lock:
            if self.model is not None:return
            if not self.ready:raise RuntimeError('请先准备本地 BGE-M3 模型')
            self.loading=True;start=time.perf_counter()
            try:
                import torch
                from sentence_transformers import SentenceTransformer
                self.device='mps' if torch.backends.mps.is_available() else 'cpu'
                try:self.model=SentenceTransformer(str(self.path),device=self.device,local_files_only=True,trust_remote_code=False)
                except Exception:
                    if self.device!='mps':raise
                    self.device='cpu';self.model=SentenceTransformer(str(self.path),device='cpu',local_files_only=True,trust_remote_code=False)
                self.model.max_seq_length=8192;self.loads+=1;self.load_seconds=time.perf_counter()-start;self.error=None
            except Exception as e:self.error=str(e);raise
            finally:self.loading=False
    def warmup(self):
        if self.warmed:return
        self.warming=True;start=time.perf_counter()
        try:
            self.encode(['知识库检索 工时评估 Markdown Unity Blender 模型预热'])
            self.warmed=True;self.warmup_seconds=time.perf_counter()-start
        finally:self.warming=False
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
