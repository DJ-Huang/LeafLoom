"""Install the script-based menu's user-login entry (macOS only)."""
from pathlib import Path
import os,plistlib,subprocess
repo=Path(__file__).resolve().parents[2]
from vault_rag.platform_support import state_directory
state=state_directory()
(state/'logs').mkdir(parents=True,exist_ok=True)
label='com.djhuang.vault-rag.menubar'
agent=Path.home()/'Library/LaunchAgents'/f'{label}.plist'
agent.parent.mkdir(parents=True,exist_ok=True)
previous=plistlib.loads(agent.read_bytes()) if agent.exists() else {}
agent.write_bytes(plistlib.dumps({'Label':label,'ProgramArguments':['/bin/bash',str(repo/'scripts/macos/start_menu.sh'),str(repo),str(state)],
 'RunAtLoad':previous.get('RunAtLoad',True),'KeepAlive':False,'VaultRagState':str(state),
 'EnvironmentVariables':{'VAULT_RAG_HOME':str(state)},
 'StandardOutPath':str(state/'logs/menubar.log'),'StandardErrorPath':str(state/'logs/menubar-error.log')}))
agent.chmod(0o600)
subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/{label}'],capture_output=True)
subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(agent)],check=True)
subprocess.run(['launchctl','kickstart',f'gui/{os.getuid()}/{label}'],check=True)
print('已安装并启动菜单栏。')
