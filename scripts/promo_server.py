"""Isolated real app for screenshots. No real vault, model downloads or AI calls."""
import argparse
import json
import secrets
import tempfile
import time
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vault_rag.local_state import LocalConfig, digest
from vault_rag.demo import create_demo
from vault_rag.preferences import Preferences
from vault_rag.knowledge import Runtime
from vault_rag.web_server import create_app,create_server

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=18089);args=parser.parse_args()
    if args.port==18080:raise ValueError('Never use the normal service port')
    with tempfile.TemporaryDirectory(prefix='leafloom-demo-') as temp:
        config=LocalConfig(Path(temp)/'state');config.save({'port':args.port})
        runtime=Runtime(config);app=create_app(config,runtime,start_background=True)
        app.state.demo=True
        class DemoAdapter:
            peer=None
            def __init__(self,provider,ai):pass
            def available(self):return False
            async def close(self,*args):pass
        # Disable external CLI execution in the capture fixture.
        app.state.ai.adapters={p:DemoAdapter(p,app.state.ai) for p in ('codex','codely')}
        app.state.ai.providers=lambda:[{'id':p,'name':p.title(),'available':False,'connected':False} for p in ('codex','codely')]
        from fastapi import Request
        @app.post('/api/promo/seed')
        async def seed(request:Request):
            options=await request.json();language=options['locale']
            sample=create_demo(config.directory,language)
            if options.get('reset_recording'):
                source=Path(__file__).resolve().parents[1]/'vault_rag/examples'/language/'Notes/01-Capture.md'
                (Path(sample['root'])/'Notes/01-Capture.md').write_bytes(source.read_bytes())
            config.save({'root':sample['root'],'include_roots':[''],'exclude_roots':[],'homepage':sample['homepage']})
            runtime.configuration_changed();runtime.catalog.scan()
            manifest=json.loads((Path(__file__).resolve().parents[1]/'vault_rag/examples'/language/'manifest.json').read_text(encoding='utf-8'))
            Preferences(config.directory).save({'locale':language,'guide':{'step':'done','checked':[],'dismissed':False}},sample['root'])
            ai=app.state.ai;topic=ai.create('codex','DEMO · LeafLoom')
            ai.execute('INSERT INTO turns(id,conversation_id,request_id,payload_hash,question,references_json,contexts_json,answer,state,created) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (secrets.token_hex(16),topic['id'],secrets.token_hex(16),'demo',manifest['question'],'[]','[]',manifest['answer'],'complete',time.time()))
            return {'topic':topic['id'],'root':sample['root'],'query':manifest['query'],'homepage':sample['homepage']}
        @app.post('/api/promo/proposal')
        async def proposal(request:Request):
            # A clearly fictional suggestion; accepting it exercises the real draft flow.
            topic=(await request.json())['topic'];ai=app.state.ai
            disk=runtime.files.read('Notes/01-Capture.md')
            turn=ai.rows('SELECT id FROM turns WHERE conversation_id=? ORDER BY created DESC LIMIT 1',(topic,))[0]['id']
            ai.execute('UPDATE turns SET question=?,answer=? WHERE id=?',
                ('Suggest one next step for my reading corner.',
                 '**Demo suggestion**\n\nAdd a small weekly ritual. Review the change below before saving.',turn))
            key=secrets.token_hex(16)
            ai.execute('INSERT INTO proposals(id,conversation_id,turn_id,path,original,text,base_hash,etag,create_note) VALUES(?,?,?,?,?,?,?,?,?)',
                (key,topic,turn,disk['path'],disk['text'],disk['text']+'\n## Next step\nReview one idea every Sunday.\n',digest(disk['text']),disk['etag'],0))
            return {'ok':True}
        create_server(app,port=args.port).run()

if __name__=='__main__':main()
