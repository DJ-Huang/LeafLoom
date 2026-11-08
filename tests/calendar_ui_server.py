"""Small isolated calendar fixture; never reads user settings or starts a model."""
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from vault_rag.local_state import LocalConfig
from vault_rag.knowledge import Runtime
from vault_rag.preferences import Preferences
from vault_rag.databases import Databases
from vault_rag.web_server import create_app

temporary=tempfile.TemporaryDirectory(prefix='leafloom-calendar-ui-')
home=Path(temporary.name);root=home/'vault';root.mkdir()
port=int(os.environ['LEAFLOOM_CALENDAR_TEST_PORT'])
if port==18080:raise ValueError('Never use the user service port')
config=LocalConfig(home/'state');config.save({'root':str(root),'port':port,'include_roots':[]})
Preferences(config.directory).save({'locale':'en','guide':{'step':'done','dismissed':True}},root=root)
runtime=Runtime(config);database=Databases(config,runtime)
database.command('Tasks.base',{'type':'create','preset':'tasks'},config.data['revision'],operation_id='fixture')
c=database.config_read('Tasks.base')
database.command('Tasks.base',{'type':'record.create','title':'Fictional task','values':{c['tasks']['dueField']:dt.date.today().isoformat()}},config.data['revision'],c['revision'],'record')
runtime.catalog.scan()
def changed(*paths):
 runtime.catalog.apply(paths);runtime.publish('files',list(paths))
runtime.files.changed=changed
app=create_app(config,runtime,start_background=False,static_dir=Path(sys.argv[1]).resolve())
calendar=app.state.calendar
identity=calendar.command({'workspace_revision':config.data['revision'],'operation_id':'sync-fixture','command':{'type':'create','item':{'title':'Sync example','date':dt.date.today().isoformat()}}})['id']
with calendar.database() as store:
 row=store.execute('SELECT * FROM sync_heads WHERE entity=?',('item:'+identity,)).fetchone()
 original=calendar.sync.snapshot(store)['item:'+identity]
parents=json.loads(row['heads'])
for title in ('Version A','Version B'):
 value=json.loads(json.dumps(original));value['items'][identity]['data']['title']=title
 calendar.sync.write({'schema':1,'device':uuid.uuid4().hex,'created':0,'changes':[{'entity':'item:'+identity,'parents':parents,'value':value}]})
app.state.websites.ui_host='127.0.0.1';app.state.websites.ui_origin=f'http://127.0.0.1:{port}'
print(json.dumps({'fixture':True,'ui':app.state.websites.ui_origin}),flush=True)
uvicorn.run(app,host='127.0.0.1',port=port,log_level='warning')
