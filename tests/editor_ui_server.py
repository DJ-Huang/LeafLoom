"""Isolated editor browser fixture; never opens the configured user vault."""
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vault_rag.local_state import LocalConfig
from vault_rag.knowledge import Runtime
from vault_rag.preferences import Preferences
from vault_rag.web_server import create_app
import uvicorn

temporary = tempfile.TemporaryDirectory(prefix='leafloom-editor-')
home = Path(temporary.name)
root = home / 'vault'
(root / 'Notes').mkdir(parents=True)
(root / 'Other').mkdir()
(root / 'Notes/Target.md').write_text('# Target\n\nFirst target.', encoding='utf-8')
(root / 'Other/Target.md').write_text('# Target\n\nSecond target.', encoding='utf-8')
(root / 'Notes/Editor.md').write_text('Editor fixture\n\n', encoding='utf-8')
other = home / 'other'
other.mkdir()
port = int(os.environ.get('LEAFLOOM_EDITOR_TEST_PORT', '18087'))
if port == 18080:
    raise ValueError('Do not use the production service port')
config = LocalConfig(home / 'state')
config.save({'root': str(root), 'include_roots': [''], 'port': port})
Preferences(config.directory).save({'locale': 'zh-CN'})
runtime = Runtime(config)
runtime.catalog.scan()

def changed(*paths):
    runtime.catalog.apply(list(paths))
    runtime.publish('files', list(paths))

runtime.files.changed = changed
runtime.files_changed = changed
app = create_app(config, runtime, start_background=False, static_dir=Path(sys.argv[1]))

@app.get('/api/editor-fixture')
async def fixture():
    return {'fixture': True, 'root': str(root), 'other': str(other)}

uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning')
