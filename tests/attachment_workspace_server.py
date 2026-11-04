"""Disposable attachment-workspace visual and interaction fixture."""
import io
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import wave
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw
from vault_rag.local_state import LocalConfig
from vault_rag.knowledge import Runtime
from vault_rag.preferences import Preferences
from vault_rag.web_server import create_app
import uvicorn

home_context=tempfile.TemporaryDirectory(prefix='leafloom-attachment-workspace-')
home=Path(home_context.name).resolve();root=home/'vault';root.mkdir();other=home/'other-vault';other.mkdir()
palette=[('#dadfd6','#617969','#e8b38a'),('#ead9c9','#9b715c','#ece5db'),('#ccd8db','#6f9299','#c2b384'),('#e5dfcf','#a4946e','#e1bc99')]
folders=['Campaign','Brand','References','Research']
first=['Autumn collection','Quiet spaces','Material study','Paper and light','Morning palette','Botanical forms','Field observations','Coastal notes']
for index in range(112):
 bg,ink,accent=palette[index%len(palette)];image=Image.new('RGB',(840,620),bg);draw=ImageDraw.Draw(image)
 if index%4==0:
  draw.rounded_rectangle((125,90,715,530),radius=7,fill='#f4f1e9');draw.rectangle((155,120,400,500),fill=ink);draw.ellipse((205,185,345,325),fill=accent);draw.rectangle((440,160,640,173),fill=ink);draw.rectangle((440,200,610,206),fill='#c1c4bb');draw.rectangle((440,220,660,226),fill='#c1c4bb');draw.rectangle((440,370,560,405),fill=accent)
 elif index%4==1:
  draw.ellipse((160,160,480,480),fill=ink);draw.ellipse((385,80,690,385),fill=accent);draw.rectangle((0,480,840,620),fill='#f5eee5')
 elif index%4==2:
  draw.polygon([(60,540),(365,130),(610,540)],fill=ink);draw.polygon([(340,540),(650,220),(830,540)],fill=accent);draw.ellipse((600,60,700,160),fill='#f8f4e8')
 else:
  for row in range(3):
   for col in range(4):
    color=[ink,accent,'#f6f1e8','#bac2b2'][(row+col)%4];draw.rounded_rectangle((90+col*165,75+row*160,235+col*165,215+row*160),radius=15,fill=color)
 name=(first[index] if index<len(first) else f'Study {index+1:03d}')+'.png';target=root/folders[index%4]/name;target.parent.mkdir(exist_ok=True);image.save(target)
 os.utime(target,(1760000000-index*3600,1760000000-index*3600))
(root/'Documents').mkdir()
content=b'BT /F1 28 Tf 60 750 Td (Field guide) Tj 0 -40 Td /F1 12 Tf (A fictional LeafLoom attachment fixture.) Tj ET'
objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',b'<< /Length '+str(len(content)).encode()+b' >>\nstream\n'+content+b'\nendstream',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
pdf=bytearray(b'%PDF-1.4\n');offsets=[0]
for number,obj in enumerate(objects,1):
 offsets.append(len(pdf));pdf+=str(number).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
xref=len(pdf);pdf+=b'xref\n0 6\n0000000000 65535 f \n'
for offset in offsets[1:]:pdf+=f'{offset:010d} 00000 n \n'.encode()
pdf+=b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(xref).encode()+b'\n%%EOF\n'
(root/'Documents/Field guide.pdf').write_bytes(pdf)
(root/'Audio').mkdir()
with wave.open(str(root/'Audio/Quiet signal.wav'),'wb') as out:
 out.setnchannels(1);out.setsampwidth(2);out.setframerate(8000);out.writeframes(b''.join(struct.pack('<h',int(600*math.sin(i*2*math.pi*220/8000))) for i in range(4000)))
(root/'Site').mkdir();(root/'Site/index.html').write_text('<!doctype html><title>Fixture site</title><img src="../Shared/logo.png">')
(root/'Shared').mkdir();Image.new('RGB',(100,100),'#748e7b').save(root/'Shared/logo.png')
(root/'Notes').mkdir();(root/'Notes/Creative brief.md').write_text('# Creative brief\n\n![[Campaign/Autumn collection.png]]\n')
(root/'Documents/Archive.zip').write_bytes(b'fixture archive')
(root/'References/Broken image.png').write_bytes(b'broken image fixture')
if os.environ.get('LEAFLOOM_TOOLS_DESIGN')=='1':
 for folder,names in {'Notes':['Creative brief','Research journal','Reading notes','Design principles'],
                      'Projects':['Autumn campaign','Editorial system','Launch checklist'],
                      'Topics':['Visual design','Knowledge garden','Materials']}.items():
  for index,name in enumerate(names):
   target=root/folder/(name+'.md');target.parent.mkdir(exist_ok=True)
   links=['Creative brief','Research journal','Design principles','Autumn campaign','Visual design','Materials']
   target.write_text('# '+name+'\n\nA fictional workspace for visual review.\n\n'+' · '.join('[['+link+']]' for n,link in enumerate(links) if link!=name and (n+index)%3!=0)+'\n')
port=int(os.environ['LEAFLOOM_ATTACHMENT_TEST_PORT'])
if port==18080:raise ValueError('Do not use the user service port')
config=LocalConfig(home/'state');config.save({'root':str(root),'port':port,'include_roots':['']})
Preferences(config.directory).save({'locale':'en','guide':{'step':'done','dismissed':True}},root=root)
runtime=Runtime(config);runtime.catalog.scan()
def changed(*paths):
 runtime.catalog.apply(list(paths));runtime.publish('files',list(paths))
runtime.files_changed=changed;runtime.files.changed=changed
app=create_app(config,runtime,start_background=False,static_dir=Path(sys.argv[1]).resolve())
# The fixture uses a literal loopback host so Node's request client needs no local DNS.
app.state.websites.ui_host='127.0.0.1'
app.state.websites.ui_origin=f'http://127.0.0.1:{port}'
if os.environ.get('LEAFLOOM_ATTACHMENT_MODE_TEST')=='1':
    import httpx
    from tests.test_remote_attachments import FakeDAV,SOURCE,SECRET
    (other/'Other local.bin').write_bytes(b'other-local-original')
    fixture_dav=FakeDAV();fixture_dav.files['Incoming/Server specimen.bin']=b'fictional-server-original'
    app.state.remote_attachments.transports[SOURCE]=httpx.MockTransport(fixture_dav)
    @app.post('/api/attachment-fixture/server')
    async def enable_fixture_server():
        current=str(config.root);remote=app.state.remote_attachments
        remote.save(current,{'sources':[{'id':SOURCE,'name':'Fictional NAS','type':'webdav',
            'base_url':'https://files.example.invalid/','username':'leafloom','upload_directory':'Incoming','enabled':True}],
            'default_source':SOURCE})
        remote.set_credentials(SOURCE,'leafloom',SECRET)
        remote.scan(current,SOURCE)
        return {'fixture':True,'storage_id':SOURCE,'remote_path':'_attachments/_remote/'+SOURCE+'/Incoming/Server specimen.bin'}
@app.get('/api/attachment-fixture')
async def fixture():return {'fixture':True,'root':str(root),'other_root':str(other),'ui':app.state.websites.ui_origin,'port':port}
print(json.dumps({'fixture':True,'ui':app.state.websites.ui_origin,'port':port}),flush=True)
uvicorn.run(app,host='127.0.0.1',port=port,log_level='warning')
