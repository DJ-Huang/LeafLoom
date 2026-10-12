"""Opt-in Windows task/server smoke in isolated state, with no model download."""
from __future__ import annotations
from pathlib import Path
import socket
import sys
import tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
if sys.platform!='win32':raise SystemExit('This check requires an interactive Windows login.')
from vault_rag.local_state import LocalConfig
from vault_rag.service_control import health,request
from vault_rag.windows_service import register,control,installed,scheduler,task_name,NS
from vault_rag.windows_native import Instance,running

with tempfile.TemporaryDirectory(prefix='VaultRag smoke ') as temporary:
    config=LocalConfig(Path(temporary)/'state')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    config.save({'port':port})
    try:
        register(config,autostart=False)
        control('start',config);control('start',config)
        assert health(config)=='ready'
        with Instance(config.directory,'service') as duplicate:assert not duplicate.primary
        status=request('/api/status',config=config)
        assert status['model']['load_count']==0, 'Smoke must not load or download a model'
        for role in ('service','tray'):
            xml=scheduler('/Query','/TN',task_name(config,role),'/XML').stdout
            task=ET.fromstring(xml)
            assert task.find(f'{{{NS}}}Triggers/{{{NS}}}LogonTrigger/{{{NS}}}Enabled').text=='false'
        control('stop',config);assert not running(config.directory)
        control('start',config);control('restart',config);assert health(config)=='ready'
        print('Windows scheduled-service start/reuse/stop/restart smoke passed; no model loaded.')
    finally:
        control('uninstall',config)
