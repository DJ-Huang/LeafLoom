"""Serial private model/index worker. EOF is the lifetime of the owning service."""
from __future__ import annotations
import contextlib, itertools, json, logging, os, queue, sys, threading, time
from pathlib import Path

OUTPUT=sys.stdout
write_lock=threading.Lock()
def emit(value):
    with write_lock:OUTPUT.write(json.dumps(value,ensure_ascii=False,default=str)+'\n');OUTPUT.flush()

def main():
    from vault_rag.local_state import LocalConfig
    from vault_rag.embedded_model import EmbeddedModel
    config=LocalConfig();model=EmbeddedModel(config.directory)
    from vault_rag.control_pipe import ControlPipe
    control=ControlPipe(sys.stdin)
    sequence=itertools.count();requests=queue.PriorityQueue();stopping=threading.Event();gate=threading.Event();gate.set();urgent=threading.Event()
    current={'knowledge':None,'state':'idle','stop':threading.Event()}
    def cancel():
        current['stop'].set()
        if current['knowledge']:current['knowledge'].stop_event.set()
    def commands():
        try:
            for line in control.lines():
                value=json.loads(line);kind=value.get('type')
                if kind=='request':
                    if value['operation'] in ('dense','prepare','asset_dense'):urgent.set();cancel()
                    requests.put((0 if value['operation'] in ('dense','prepare','asset_dense') else 1 if value['operation']=='asset_build' else 2,next(sequence),value))
                elif kind=='pause':gate.clear()
                elif kind=='resume':gate.set()
                elif kind=='cancel':cancel()
                elif kind=='shutdown':cancel();stopping.set();gate.set();requests.put((-1,next(sequence),None));return
        finally:
            # The model may be stuck in a native import. Never orphan it after EOF.
            os._exit(0)
    def monitor():
        while not stopping.wait(.5):
            knowledge=current['knowledge']
            emit({'type':'status','state':current['state'],'model':model.status(),'progress':dict(knowledge.progress) if knowledge else {}})
    threading.Thread(target=commands,name='rag-input',daemon=True).start()
    threading.Thread(target=monitor,name='rag-status',daemon=True).start()
    logging.basicConfig(level=logging.INFO,stream=sys.stderr,force=True)
    emit({'type':'status','state':'idle','model':model.status(),'progress':{}})
    while not stopping.is_set():
        _,_,value=requests.get()
        if value is None:break
        identifier=value['id'];operation=value['operation'];current['state']=operation
        current['stop']=threading.Event();current['knowledge']=None
        config.data=dict(value['config'])
        try:
            if operation!='build':urgent.clear()
            elif urgent.is_set():raise InterruptedError('cancelled')
            with contextlib.redirect_stdout(sys.stderr):
                if operation=='prepare':result=model.prepare()
                elif operation in ('asset_build','asset_dense'):
                    from vault_rag.asset_vectors import execute
                    result=execute(config,model,value)
                elif operation=='dense':
                    import lancedb
                    root=config.root;directory=Path(value['directory']).resolve()
                    if not directory.is_relative_to(root/'.vault-rag/generations'):raise ValueError('Invalid index directory')
                    vector=model.encode([value['query']])[0]
                    db=lancedb.connect(str(directory/'lancedb'));table=db.open_table('vault_chunks')
                    paths=[p for p in value['paths'] if config.selected(p)]
                    where='file_path IN ('+','.join("'"+p.replace("'","''")+"'" for p in paths)+')'
                    hits=table.search(vector).distance_type('cosine').where(where,prefilter=True).limit(value['limit']).to_list() if paths else []
                    # Vectors stay private to this process; the service only needs
                    # IDs/distances for fusion, not multi-megabyte vector payloads.
                    result=[{'id':hit['id'],'_distance':float(hit['_distance'])} for hit in hits]
                elif operation=='build':
                    from vault_rag.catalog import Catalog
                    from vault_rag.local_state import Files
                    from vault_rag.knowledge import Knowledge
                    catalog=Catalog(Files(config));catalog.persist=False
                    knowledge=Knowledge(config,catalog,model);knowledge.stop_event=current['stop'];current['knowledge']=knowledge
                    def yield_work():
                        while not gate.wait(.1):
                            if current['stop'].is_set() or urgent.is_set():return False
                        return not current['stop'].is_set() and not urgent.is_set()
                    def publish_allowed():
                        live=json.loads(config.path.read_text(encoding='utf-8'))
                        return live.get('root')==config.data.get('root') and live.get('revision')==config.data.get('revision') and yield_work()
                    knowledge.yield_work=yield_work;knowledge.publish_allowed=publish_allowed
                    if not yield_work():raise InterruptedError('cancelled')
                    catalog.scan_selected();knowledge.load();knowledge.build(force=value.get('force',False))
                    if current['stop'].is_set():raise InterruptedError('cancelled')
                    if knowledge.last_error:raise RuntimeError(knowledge.last_error)
                    result={'progress':knowledge.progress,'generation':knowledge.snapshot.get('status',{}).get('generation')}
                else:raise ValueError('Unknown RAG operation')
            emit({'type':'result','id':identifier,'result':result})
        except InterruptedError:emit({'type':'result','id':identifier,'cancelled':True})
        except Exception as error:
            logging.exception('RAG task failed');emit({'type':'result','id':identifier,'error':str(error)})
        finally:
            current['state']='idle'
            emit({'type':'status','state':'idle','model':model.status(),'progress':dict(current['knowledge'].progress) if current['knowledge'] else {}})

if __name__=='__main__':main()
