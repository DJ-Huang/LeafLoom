"""Disposable database UI fixture. Never connects to a user vault or model."""
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from PIL import Image, ImageDraw
from vault_rag.local_state import LocalConfig
from vault_rag.knowledge import Runtime
from vault_rag.preferences import Preferences
from vault_rag.databases import Databases
from vault_rag.web_server import create_app

temporary = tempfile.TemporaryDirectory(prefix='leafloom-database-ui-')
home = Path(temporary.name); root = home/'vault'; root.mkdir()
port = int(os.environ['LEAFLOOM_DATABASE_TEST_PORT'])
if port == 18080: raise ValueError('Do not use the user service port')
config = LocalConfig(home/'state'); config.save({'root': str(root), 'port': port, 'include_roots': []})
Preferences(config.directory).save({'locale': 'en', 'guide': {'step': 'done', 'dismissed': True}}, root=root)
runtime = Runtime(config); db = Databases(config, runtime)
db.command('Showcase.base', {'type': 'create'}, config.data['revision'], operation_id='fixture')
(root/'Assets').mkdir(); Image.new('RGB', (640, 360), '#637f93').save(root/'Assets/cover.png')
(root/'Assets/broken.png').write_bytes(b'not an image'); (root/'Assets/video.mp4').write_bytes(b'video fixture')
base = dt.date.today()
for i in range(8 if os.environ.get('LEAFLOOM_DATABASE_DESIGN') else 2400):
    start = base + dt.timedelta(days=i%12)
    (root/'Showcase'/f'Record {i:04}.md').write_text('---\ntitle: Record '+str(i).zfill(4)+'\ncategory: Demo\nattachments: ["[[Assets/video.mp4]]", "[[Assets/cover.png]]"]\ncover: ["[[Assets/'+('broken.png' if i == 1 else 'cover.png')+']]"]\nstart_date: '+str(start)+'\nend_date: '+str(start+dt.timedelta(days=3))+'\n---\n\n# Original body\n\nFictional database record.\n')
view = db.config_read('Showcase.base')['views'][2]['id']
(root/'Dashboard.md').write_text('# Dashboard\n\n![[Showcase.base#view='+view+']]\n\nParent text remains editable.\n')
if os.environ.get('LEAFLOOM_DATABASE_DESIGN'):
    db.command('Studio notes.base', {'type': 'create'}, config.data['revision'], operation_id='design-studio')
    examples = [
        ('01 — Quiet architecture', 'Architecture', '#d7d4ca', '#738478'),
        ('02 — Objects in warm light', 'Materials', '#d8bd9e', '#6d5547'),
        ('03 — A study in blue', 'Color study', '#e1e8ee', '#6486a4'),
        ('04 — Botanical forms', 'Inspiration', '#cbd6c4', '#637959'),
        ('05 — Soft geometry', 'Materials', '#e6d5cb', '#ad7c69'),
        ('06 — Editorial explorations', 'Inspiration', '#e6e0d2', '#565b54'),
        ('07 — Motion experiments', 'Color study', '#cecbd9', '#756a92'),
        ('08 — Notes on texture', 'Materials', '#e4dfd4', '#908778'),
    ]
    for i, (title, category, background, ink) in enumerate(examples):
        image=Image.new('RGB',(960,600),background); draw=ImageDraw.Draw(image)
        if i%4==0:
            for x in range(100,850,160):
                draw.rectangle((x,80,x+110,600),fill=ink)
                draw.rounded_rectangle((x+20,160,x+90,600),radius=35,fill=background)
            draw.rectangle((0,510,960,600),fill=ink)
        elif i%4==1:
            draw.ellipse((165,95,560,490),fill=ink); draw.rectangle((575,220,790,490),fill='#f4eee5')
            draw.ellipse((150,480,825,540),fill='#bda88f'); draw.ellipse((165,95,560,490),fill=ink)
        elif i%4==2:
            for n,color in enumerate([ink,'#8aa6ba','#bbced8','#f4f1e7']):
                draw.rounded_rectangle((140+n*125,80+n*52,650+n*40,470+n*22),radius=24,fill=color)
        else:
            for x,y in [(300,190),(580,230),(410,390)]:
                draw.ellipse((x-65,y-120,x+65,y+120),fill=ink)
            draw.line((450,600,450,200),fill='#f1ecdf',width=5)
        image.save(root/'Assets'/f'study-{i}.png')
        start=base+dt.timedelta(days=i*2)
        (root/'Studio notes'/f'{i+1:02}.md').write_text('---\ntitle: '+title+'\ncategory: '+category+'\ncover: ["[[Assets/study-'+str(i)+'.png]]"]\nattachments: ["[[Assets/study-'+str(i)+'.png]]"]\nstart_date: '+str(start)+'\nend_date: '+str(start+dt.timedelta(days=4+i%3))+'\n---\n\n# '+title+'\n\nA collection of visual references, experiments and things worth keeping.\n')
    studio=db.config_read('Studio notes.base')
    views=studio['config']['views']; views[1]['order']=['title','category','end_date']; views[2]['order']=['title','category','attachments']
    # Fixture-only authored configuration preserves the same service-generated IDs.
    import io
    from ruamel.yaml import YAML
    stream=io.StringIO(); YAML().dump(studio['config'],stream)
    runtime.files.save('Studio notes.base',stream.getvalue(),studio['revision'],expected_root=studio['root'])
    db.command('Ideas.base', {'type': 'create'}, config.data['revision'], operation_id='design-sparse')
    sparse=db.config_read('Ideas.base')
    db.command('Ideas.base',{'type':'record.create','title':'A little room for a new idea','values':{}},config.data['revision'],sparse['revision'],'design-record')
if os.environ.get('LEAFLOOM_WORKSPACE_DESIGN'):
    (root/'Notes').mkdir(exist_ok=True); (root/'Projects').mkdir(exist_ok=True)
    journal='---\ntitle: Project journal\ntags: [product, notes]\nstatus: Draft\n---\n# Project journal\n\nDesign decisions, working notes and things to revisit.\n\n> A shared place for the work that is still taking shape.\n\n## This week\n\n- [x] Bring references and working notes together\n- [ ] Review the first version with the team\n- [ ] Write down the decisions that matter\n\n## A clearer workspace\n\nKeep useful context close to the work. Link related notes, collect references, and leave a clear next step.\n\nSee [[Projects/Product brief]] for the project scope.\n\n## Working principles\n\n| Principle | In practice |\n| --- | --- |\n| Start small | Give each page one clear purpose |\n| Keep context | Link decisions to their sources |\n| Make room | Leave space for the next idea |\n'
    (root/'Notes/Project journal.md').write_text(journal)
    (root/'Projects/Product brief.md').write_text('# Product brief\n\nA quieter place to read, write and connect ideas.\n\n## Goals\n\n- Make everyday actions easy to find.\n- Keep the interface consistent.\n')
    (root/'Notes/Reading list.md').write_text('# Reading list\n\nA few things worth returning to.\n\n- Interface design\n- Systems thinking\n- Writing clearly\n')
    (root/'Projects/Design decisions.md').write_text('# Design decisions\n\nThe reasoning behind the current direction.\n')
    (root/'Projects/Release checklist.md').write_text('# Release checklist\n\n- [ ] Review content\n- [ ] Check the narrow layout\n')
    (root/'Templates').mkdir(exist_ok=True); (root/'Notes/Daily').mkdir(exist_ok=True)
    (root/'Templates/Meeting.md').write_text('# Meeting notes\n\n## Decisions\n\n## Next steps\n')
    config.save({'homepage':'Notes/Project journal.md','daily_folder':'Notes/Daily'})
runtime.catalog.scan()
def changed(*paths):
    runtime.catalog.apply(list(paths)); runtime.catalog.metadata_ready = True
    runtime.publish('files', list(paths))
runtime.files_changed = changed; runtime.files.changed = changed
app = create_app(config, runtime, start_background=False, static_dir=Path(sys.argv[1]).resolve())
app.state.websites.ui_host = '127.0.0.1'; app.state.websites.ui_origin = f'http://127.0.0.1:{port}'
print(json.dumps({'fixture': True, 'ui': app.state.websites.ui_origin}), flush=True)
uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning')
