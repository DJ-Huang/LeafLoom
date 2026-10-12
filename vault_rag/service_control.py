"""User-level macOS launch agent and authenticated CLI management."""
from __future__ import annotations
import json, os, plistlib, subprocess, sys, time, webbrowser
from pathlib import Path
from vault_rag.local_state import LocalConfig,atomic_write

LABEL='com.djhuang.vault-rag'

def agent_path():return Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
def control(action):
    config=LocalConfig();target=f'gui/{os.getuid()}/{LABEL}';path=agent_path()
    if action=='install':
        logs=config.directory/'logs';logs.mkdir(exist_ok=True);path.parent.mkdir(parents=True,exist_ok=True)
        repo=Path(__file__).resolve().parents[1]
        data={'Label':LABEL,'ProgramArguments':[str(Path(sys.executable).absolute()),'-m','vault_rag.web_server_entry'],'WorkingDirectory':str(repo),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,'StandardOutPath':str(logs/'service.log'),'StandardErrorPath':str(logs/'service-error.log'),'EnvironmentVariables':{'VAULT_RAG_HOME':str(config.directory),'TOKENIZERS_PARALLELISM':'false','PYTHONDONTWRITEBYTECODE':'1','NO_PROXY':'localhost,127.0.0.1','no_proxy':'localhost,127.0.0.1'}}
        atomic_write(path,plistlib.dumps(data));path.chmod(0o600)
        subprocess.run(['launchctl','bootout',target],capture_output=True)
        subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(path)],check=True);print('已安装并启动本地知识库服务')
    elif action=='start':
        if not path.exists():return control('install')
        result=subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(path)],capture_output=True)
        if result.returncode:subprocess.run(['launchctl','kickstart',target],check=True)
    elif action=='stop':subprocess.run(['launchctl','bootout',target],capture_output=True)
    elif action=='restart':subprocess.run(['launchctl','kickstart','-k',target],check=True)
    elif action=='uninstall':control('stop');path.unlink(missing_ok=True)
    elif action=='status':
        result=subprocess.run(['launchctl','print',target],capture_output=True,text=True)
        print(result.stdout if result.returncode==0 else '服务未运行')
    elif action=='open':webbrowser.open(f'http://127.0.0.1:{config.data.get("port",18080)}/')
    else:raise ValueError('支持 install/start/stop/restart/status/uninstall/open')

def request(path,body=None):
    import httpx
    config=LocalConfig();token=(config.directory/'auth-token').read_text().strip();base=f'http://127.0.0.1:{config.data.get("port",18080)}'
    with httpx.Client(trust_env=False,timeout=60) as client:
        r=client.request('POST' if body is not None else 'GET',base+path,json=body,headers={'Authorization':'Bearer '+token});r.raise_for_status();return r.json()
