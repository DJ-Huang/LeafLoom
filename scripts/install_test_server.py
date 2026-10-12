"""CI child server with cooperative shutdown; does not create OS login tasks."""
import os
from pathlib import Path
import sys
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
assert os.environ.get('VAULT_RAG_INSTALL_TEST_SERVER')=='1'
from vault_rag.local_state import LocalConfig
from vault_rag.web_server import create_app
import uvicorn

config=LocalConfig()
assert not config.data.get('root')
server=uvicorn.Server(uvicorn.Config(create_app(config),host='127.0.0.1',port=config.data['port'],workers=1,access_log=False))
started=config.directory/'test-server.started'
finished=threading.Event()
def watch():
    while not finished.wait(.2):
        if (config.directory/'test-server.stop').exists():server.should_exit=True;return
started.touch()
worker=threading.Thread(target=watch,daemon=True);worker.start()
try:server.run()
finally:
    finished.set();worker.join();started.unlink(missing_ok=True)
