"""Hash installer artifacts and save an inventory for the release draft."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
directory = ROOT / 'desktop/release'
files = sorted(file for file in directory.iterdir() if file.suffix in ('.exe', '.dmg'))
if not files:
    raise SystemExit('没有安装包，不能写发布校验清单')
checksums = []
for file in files:
    with file.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    checksums.append({'name': file.name, 'sha256': checksum, 'bytes': file.stat().st_size})
(directory / 'SHA256SUMS.txt').write_text(''.join(f"{item['sha256']}  {item['name']}\n" for item in checksums), encoding='utf-8')
(directory / 'artifacts.json').write_text(json.dumps(checksums, indent=2), encoding='utf-8')
