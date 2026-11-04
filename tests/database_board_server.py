"""Disposable board browser fixture with small and 2,400-record task databases."""
import datetime as dt
import json
import os
import threading
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from ruamel.yaml import YAML
from PIL import Image
from vault_rag.local_state import LocalConfig
from vault_rag.knowledge import Runtime
from vault_rag.preferences import Preferences
from vault_rag.databases import Databases
from vault_rag.web_server import create_app

temporary = tempfile.TemporaryDirectory(prefix='leafloom-board-ui-')
home=Path(temporary.name);root=home/'vault';root.mkdir()
port=int(os.environ['LEAFLOOM_BOARD_TEST_PORT'])
if port==18080: raise ValueError('Never use the user service port')
config=LocalConfig(home/'state');config.save({'root':str(root),'port':port,'include_roots':[]})
Preferences(config.directory).save({'locale':'en','guide':{'step':'done','dismissed':True}},root=root)
runtime=Runtime(config);db=Databases(config,runtime)
for path,folder in [('Product roadmap.base','Tasks'),('Large board.base','Many tasks')]:
 db.command(path,{'type':'create','preset':'tasks','folder':folder},config.data['revision'],operation_id=folder.replace(' ','-'))
small=db.config_read('Product roadmap.base');view=small['views'][0]
(root/'Assets').mkdir();Image.new('RGB',(600,320),'#c9d3c2').save(root/'Assets/cover.png')
tasks=[('Define product scope','明确产品范围','open','high',3,'产品'),('Research workflow','整理工作流参考','open','medium',5,'研究'),('Write acceptance criteria','补充验收标准','open','medium',2,'产品'),('Draft documentation','整理使用说明','open','low',8,'文档'),('Design task cards','设计任务卡片','in-progress','high',-2,'设计'),('Build board interactions','实现看板交互','in-progress','high',0,'开发'),('Review responsive layout','检查窄屏布局','in-progress','medium',2,'设计'),('Set up workspace','建立项目空间','done','medium',-4,'开发'),('Align visual language','统一视觉语言','done','low',-1,'设计')]
yaml=YAML()
for index,(slug,title,status,priority,days,category) in enumerate(tasks):
 path=root/'Tasks'/(slug+'.md')
 values={'title':title,'status':status,'priority':priority,'end_date':str(dt.date.today()+dt.timedelta(days=days)),'category':category,'cover':['[[Assets/cover.png]]']}
 import io
 out=io.StringIO();yaml.dump(values,out);path.write_text('---\n'+out.getvalue()+'---\n\n# '+title+'\n\nFictional task body. Preserve this paragraph.\n')
(root/'Tasks/Unassigned.md').write_text('---\ntitle: 尚未分类的想法\n---\n\nOriginal unassigned body.\n')
(root/'Tasks/Legacy.md').write_text('---\ntitle: 保留历史状态\nstatus: retired\n---\n\nOriginal historical body.\n')
for index in range(2400):
 status=['open','in-progress','done'][index%3]
 (root/'Many tasks'/f'{index:04}.md').write_text(f'---\ntitle: Scale task {index:04}\nstatus: {status}\npriority: medium\n---\n\nFictional scale fixture.\n')
(root/'Dashboard.md').write_text('# Team workspace\n\n![[Product roadmap.base#view='+view['id']+']]\n\nParent note remains unchanged.\n')
(root/'Context dashboard.md').write_text('# Record workspace\n\n![[Product roadmap.base#view='+next(v['id'] for v in small['views'] if v['type']=='table')+']]\n\nParent note remains unchanged.\n')
runtime.catalog.scan()
def changed(*paths):
 # Reproduce a configuration save before the background catalog catches up.
 indexed=[p for p in paths if not (os.environ.get('LEAFLOOM_BOARD_DEFER_BASE_CATALOG') and p.endswith('.base'))]
 if indexed: runtime.catalog.apply(indexed)
 runtime.publish('files',list(paths))
if os.environ.get('LEAFLOOM_BOARD_ASYNC_CATALOG'):
 # Run the production file queue without starting models or the RAG worker.
 runtime.root=str(root)
 worker=threading.Thread(target=runtime.loop,name='board-fixture-files',daemon=True)
 runtime.thread=worker;runtime.threads=[worker];worker.start()
else:
 runtime.files.changed=changed
app=create_app(config,runtime,start_background=False,static_dir=Path(sys.argv[1]).resolve())
app.state.websites.ui_host='127.0.0.1';app.state.websites.ui_origin=f'http://127.0.0.1:{port}'
print(json.dumps({'fixture':True,'ui':app.state.websites.ui_origin,'port':port,'view_id':view['id'],'root':str(root)}),flush=True)
uvicorn.run(app,host='127.0.0.1',port=port,log_level='warning')
