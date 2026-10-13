"""Build the clickable macOS launcher (requires a macOS Swift compiler and generated brand assets)."""
from pathlib import Path
import plistlib,subprocess
REPO=Path(__file__).resolve().parents[1]
def build(repo=REPO,destination=None):
 destination=Path(destination) if destination else repo/'本地知识库.app'
 contents=destination/'Contents';(contents/'MacOS').mkdir(parents=True,exist_ok=True);(contents/'Resources').mkdir(exist_ok=True)
 launcher=contents/'MacOS'/'menubar'
 subprocess.run(['swiftc','-target','arm64-apple-macos14.0',str(repo/'scripts/macos/MenuBar.swift'),'-o',str(launcher),'-framework','AppKit','-O'],check=True)
 import shutil
 shutil.copyfile(repo/'scripts/macos/app_launcher.sh',contents/'MacOS'/'launcher')
 (contents/'MacOS'/'launcher').chmod(0o755)
 (contents/'Info.plist').write_bytes(plistlib.dumps({'CFBundleName':'LeafLoom','CFBundleDisplayName':'LeafLoom','CFBundleIdentifier':'com.djhuang.vault-rag.launcher','CFBundleVersion':'4','CFBundleShortVersionString':'1.3','CFBundlePackageType':'APPL','CFBundleExecutable':'launcher','CFBundleIconFile':'Knowledge.icns','NSHighResolutionCapable':True,'LSUIElement':True,'LSMinimumSystemVersion':'14.0','VaultRagRepository':''}))
 shutil.copytree(repo/'vault_rag/locales',contents/'Resources/locales',dirs_exist_ok=True)
 shutil.copyfile(repo/'assets/brand/icon-64.png',contents/'Resources/LeafLoom.png')
 shutil.copyfile(repo/'assets/brand/leafloom.icns',contents/'Resources/Knowledge.icns')
 metadata=plistlib.loads((contents/'Info.plist').read_bytes());metadata['VaultRagMenuRevision']='4'
 (contents/'Info.plist').write_bytes(plistlib.dumps(metadata))
 print(destination)
 return destination
if __name__=='__main__':build()
