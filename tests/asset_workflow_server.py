"""Disposable delivery/settings UI fixture. Never connects to user data or services."""
import json
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vault_rag.local_state import LocalConfig
from vault_rag.preferences import Preferences
from vault_rag.web_server import create_app
from vault_rag.file_commands import DeliverAsset
import uvicorn

context=tempfile.TemporaryDirectory(prefix='leafloom-asset-ui-')
home=Path(context.name).resolve();root=home/'vault';root.mkdir()
(root/'石头.fbx').write_bytes(b'fictional asset')
from PIL import Image
(root/'NoteAttachments').mkdir()
Image.new('RGB',(8,8),'blue').save(root/'NoteAttachments/reference.png')
(root/'note.md').write_text('![](NoteAttachments/reference.png)')
port=int(os.environ['LEAFLOOM_ATTACHMENT_TEST_PORT'])
if port==18080:raise ValueError('Never use the user service port')
config=LocalConfig(home/'state');config.save({'root':str(root),'port':port})
Preferences(config.directory).save({'locale':'en','guide':{'step':'done','dismissed':True}},root=root)
app=create_app(config,start_background=False,static_dir=Path(sys.argv[1]).resolve())
app.state.websites.ui_host='127.0.0.1';app.state.websites.ui_origin=f'http://127.0.0.1:{port}'
f=app.state.file_operations;f.runtime.catalog.scan();f.runtime.files.attachments.refresh()
f.attachment_groups.update(str(root),'create',{'name':'Asset models','search_enabled':True,'rules':{'formats':['fbx']}})
f.asset_deliveries.configure(str(home/'output'),'initial')
source=f._stat('石头.fbx',f.notes.workspace_revision)
f.asset_deliveries.create(DeliverAsset(action='deliver_asset',path='石头.fbx',expected_revision=source['revision']),
    f.notes.workspace_revision,'fixture-delivery','local',lambda:None)
print(json.dumps({'fixture':True,'ui':app.state.websites.ui_origin,'root':str(root),'output':str(home/'output')}),flush=True)
uvicorn.run(app,host='127.0.0.1',port=port,log_level='warning')
