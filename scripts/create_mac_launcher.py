"""Build the clickable macOS launcher (requires Pillow and macOS iconutil)."""
from pathlib import Path
import plistlib,subprocess,tempfile
from PIL import Image,ImageDraw
REPO=Path(__file__).resolve().parents[1]
def build(repo=REPO,destination=None):
 destination=Path(destination) if destination else repo/'本地知识库.app'
 contents=destination/'Contents';(contents/'MacOS').mkdir(parents=True,exist_ok=True);(contents/'Resources').mkdir(exist_ok=True)
 launcher=contents/'MacOS'/'menubar'
 subprocess.run(['swiftc','-target','arm64-apple-macos14.0',str(repo/'scripts/macos/MenuBar.swift'),'-o',str(launcher),'-framework','AppKit','-O'],check=True)
 import shutil
 shutil.copyfile(repo/'scripts/macos/app_launcher.sh',contents/'MacOS'/'launcher')
 (contents/'MacOS'/'launcher').chmod(0o755)
 (contents/'Info.plist').write_bytes(plistlib.dumps({'CFBundleName':'本地知识库','CFBundleDisplayName':'本地知识库','CFBundleIdentifier':'com.djhuang.vault-rag.launcher','CFBundleVersion':'3','CFBundleShortVersionString':'1.2','CFBundlePackageType':'APPL','CFBundleExecutable':'launcher','CFBundleIconFile':'Knowledge.icns','NSHighResolutionCapable':True,'LSUIElement':True,'LSMinimumSystemVersion':'14.0','VaultRagRepository':''}))
 with tempfile.TemporaryDirectory() as tmp:
  folder=Path(tmp)/'Knowledge.iconset';folder.mkdir()
  im=Image.new('RGBA',(1024,1024));d=ImageDraw.Draw(im)
  d.rounded_rectangle((30,30,994,994),radius=205,fill='#315e4b')
  d.rounded_rectangle((190,230,834,795),radius=62,fill='#dbe8ce')
  d.polygon([(512,286),(246,248),(246,722),(512,766)],fill='#faf7e9')
  d.polygon([(512,286),(778,248),(778,722),(512,766)],fill='#edf1df')
  d.line([(512,288),(512,750)],fill='#73927c',width=12)
  for y in (385,466,547):
   d.line([(299,y),(456,y+22)],fill='#9eae94',width=16)
   d.line([(568,y+22),(725,y)],fill='#9eae94',width=16)
  d.ellipse((652,598,848,794),fill='#d9b668');d.line([(701,696),(738,733),(802,659)],fill='#315e4b',width=18)
  for size in (16,32,128,256,512):
   for scale in (1,2): im.resize((size*scale,size*scale),Image.Resampling.LANCZOS).save(folder/f'icon_{size}x{size}{"@2x" if scale==2 else ""}.png')
  subprocess.run(['iconutil','-c','icns',str(folder),'-o',str(contents/'Resources'/'Knowledge.icns')],check=True)
 metadata=plistlib.loads((contents/'Info.plist').read_bytes());metadata['VaultRagMenuRevision']='3'
 (contents/'Info.plist').write_bytes(plistlib.dumps(metadata))
 print(destination)
if __name__=='__main__':build()
