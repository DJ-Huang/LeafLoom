"""Install the built menu application and its user-login entry (macOS only)."""
from pathlib import Path
import os,plistlib,subprocess
repo=Path(__file__).resolve().parents[2]
source=repo/'本地知识库.app'
if not (source/'Contents/MacOS/launcher').exists():raise SystemExit('请先运行 scripts/create_mac_launcher.py 构建应用')
installed=Path('/Applications/本地知识库.app')
subprocess.run(['ditto',str(source),str(installed)],check=True)
label='com.djhuang.vault-rag.menubar'
agent=Path.home()/'Library/LaunchAgents'/f'{label}.plist'
agent.parent.mkdir(parents=True,exist_ok=True)
agent.write_bytes(plistlib.dumps({'Label':label,'ProgramArguments':['/usr/bin/open','-g',str(installed)],'RunAtLoad':True,'KeepAlive':False}))
agent.chmod(0o600)
subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/{label}'],capture_output=True)
subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(agent)],check=True)
print('已安装；如旧菜单栏应用仍运行，请退出菜单栏后重新打开应用。')
