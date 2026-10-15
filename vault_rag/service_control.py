"""Platform-dispatched user service management and authenticated local requests."""
from __future__ import annotations
import json, os, plistlib, subprocess, sys, time, webbrowser
from pathlib import Path
from vault_rag.local_state import LocalConfig,atomic_write
from vault_rag.platform_support import is_windows

LABEL='com.djhuang.vault-rag'

def agent_path():return Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
def control(action, config=None):
    config = config or LocalConfig()
    if action in ('open', 'start', 'stop', 'install'):
        from vault_rag.desktop import forward
        if forward('stop' if action == 'stop' else 'open', config.directory):return
    if action == 'open':
        if health(config) != 'ready':control('start', config)
        ensure_ready(config)
        if is_windows():
            from vault_rag.windows_service import start_tray
            start_tray(config)
        if not webbrowser.open(base_url(config) + '/'):
            raise RuntimeError('无法打开默认浏览器，请手动打开 ' + base_url(config))
        return
    if is_windows():
        from vault_rag.windows_service import control as windows_control
        return windows_control(action, config)
    if sys.platform != 'darwin':
        raise ValueError('此系统请使用 vault-rag serve 手动运行服务')
    return macos_control(action, config)

def macos_control(action, config):
    target=f'gui/{os.getuid()}/{LABEL}';path=agent_path()
    if action=='install':
        logs=config.directory/'logs';logs.mkdir(exist_ok=True);path.parent.mkdir(parents=True,exist_ok=True)
        repo=Path(__file__).resolve().parents[1]
        previous=plistlib.loads(path.read_bytes()) if path.exists() else {}
        enabled=previous.get('RunAtLoad',True)
        data={'Label':LABEL,'ProgramArguments':[str(Path(sys.executable).absolute()),'-m','vault_rag.web_server_entry'],'WorkingDirectory':str(repo),'RunAtLoad':enabled,'KeepAlive':enabled,'ThrottleInterval':10,'StandardOutPath':str(logs/'service.log'),'StandardErrorPath':str(logs/'service-error.log'),'EnvironmentVariables':{'VAULT_RAG_HOME':str(config.directory),'TOKENIZERS_PARALLELISM':'false','PYTHONDONTWRITEBYTECODE':'1','NO_PROXY':'localhost,127.0.0.1','no_proxy':'localhost,127.0.0.1'}}
        atomic_write(path,plistlib.dumps(data));path.chmod(0o600)
        subprocess.run(['launchctl','bootout',target],capture_output=True)
        subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(path)],check=True)
        subprocess.run(['launchctl','kickstart',target],check=True);print('已安装并启动本地知识库服务')
    elif action=='start':
        if not path.exists():return control('install', config)
        result=subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(path)],capture_output=True)
        if result.returncode:subprocess.run(['launchctl','kickstart',target],check=True)
    elif action=='stop':subprocess.run(['launchctl','bootout',target],capture_output=True)
    elif action=='restart':subprocess.run(['launchctl','kickstart','-k',target],check=True)
    elif action=='uninstall':control('stop', config);path.unlink(missing_ok=True)
    elif action=='status':
        result=subprocess.run(['launchctl','print',target],capture_output=True,text=True)
        print(result.stdout if result.returncode==0 else '服务未运行')
    else:raise ValueError('支持 install/start/stop/restart/status/uninstall/open')

def base_url(config):
    return f'http://127.0.0.1:{config.data.get("port",18080)}'

def health(config):
    """Distinguish this installation from another app (including another VaultRag)."""
    import urllib.request, urllib.error
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        # Windows loopback refusal can take about two seconds. A one-second
        # timeout misclassified a normally stopped service as unresponsive.
        with opener.open(base_url(config) + '/healthz', timeout=3) as response:
            if json.load(response).get('service') != 'vault-rag':return 'other'
        token = (config.directory / 'auth-token').read_text(encoding='utf-8').strip()
        req = urllib.request.Request(base_url(config) + '/api/status', headers={'Authorization':'Bearer '+token})
        with opener.open(req, timeout=1) as response:
            return 'ready' if response.status == 200 else 'other'
    except urllib.error.HTTPError:
        return 'other'
    except urllib.error.URLError as error:
        return 'stopped' if isinstance(error.reason, ConnectionRefusedError) else 'unresponsive'
    except (TimeoutError, ConnectionError):
        return 'unresponsive'
    except (ValueError, OSError):
        return 'other'

def ensure_ready(config, timeout=60):
    deadline = time.monotonic() + timeout
    while True:
        state = health(config)
        if state == 'ready':return
        if state == 'other':raise RuntimeError('配置端口被其他程序或另一安装实例占用')
        if time.monotonic() >= deadline:
            raise RuntimeError(f'服务未能在 {timeout} 秒内就绪，请查看 {config.directory / "logs"}')
        time.sleep(.25)

def request(path,body=None,*,config=None,timeout=60):
    import httpx
    config=config or LocalConfig();token=(config.directory/'auth-token').read_text(encoding='utf-8').strip();base=f'http://127.0.0.1:{config.data.get("port",18080)}'
    with httpx.Client(trust_env=False,timeout=timeout) as client:
        r=client.request('POST' if body is not None else 'GET',base+path,json=body,headers={'Authorization':'Bearer '+token});r.raise_for_status();return r.json()
