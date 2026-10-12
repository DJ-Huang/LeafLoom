"""Install the built menu application and its user-login entry (macOS only)."""
from pathlib import Path
import os,plistlib,subprocess
repo=Path(__file__).resolve().parents[2]
source=repo/'本地知识库.app'
if not (source/'Contents/MacOS/menubar').exists():raise SystemExit('发布包缺少预编译菜单栏程序；请维护者重建发布包，无需用户安装 Swift。')
installed=Path.home()/'Applications/本地知识库.app'
installed.parent.mkdir(parents=True,exist_ok=True)
subprocess.run(['ditto',str(source),str(installed)],check=True)
from vault_rag.platform_support import state_directory
state=state_directory()
info=installed/'Contents/Info.plist'
metadata=plistlib.loads(info.read_bytes())
metadata['VaultRagRepository']=str(repo)
metadata['VaultRagState']=str(state)
info.write_bytes(plistlib.dumps(metadata))
for name in ('launcher','menubar'):(installed/'Contents/MacOS'/name).chmod(0o755)
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
