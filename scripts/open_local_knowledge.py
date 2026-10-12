"""Open the existing shared local service, starting its LaunchAgent if needed."""
import json,subprocess,time,urllib.request
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
def main():
 config=Path.home()/'Library/Application Support/VaultRag/config.json'
 port=json.loads(config.read_text()).get('port',18080) if config.exists() else 18080
 url=f'http://127.0.0.1:{port}'
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 def ready():
  try:
   with opener.open(url+'/healthz',timeout=1) as r:return json.load(r).get('service')=='vault-rag'
  except Exception:return False
 if not ready():
  subprocess.run([str(REPO/'.venv/bin/python'),'-m','vault_rag.cli','service','start'],cwd=REPO,check=True)
  for _ in range(30):
   if ready():break
   time.sleep(1)
 if not ready():raise RuntimeError('服务未响应，请查看本地知识库服务日志')
 subprocess.run(['/usr/bin/open',url+'/'],check=True)
if __name__=='__main__':
 try:main()
 except Exception:
  subprocess.run(['/usr/bin/osascript','-e','display alert "本地知识库暂时无法启动" message "请检查服务状态与 ~/Library/Application Support/VaultRag/logs/ 中的日志。" as critical'])
  raise
