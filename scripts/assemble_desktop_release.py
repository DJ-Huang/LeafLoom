"""Keep platform reports/licenses distinct and refuse an incomplete draft."""
import json
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
downloads = root / '_generated/release-downloads'
output = root / '_generated/release-assets'
output.mkdir(exist_ok=True)
checksums = []
for platform in ('darwin', 'win32'):
    source = downloads / ('desktop-' + platform)
    report = source / 'desktop/release' / ('acceptance-' + platform + '.json')
    data = json.loads(report.read_text(encoding='utf-8'))
    if not data.get('passed'):
        raise SystemExit('该平台验收未通过：' + platform)
    release = report.parent
    for file in release.glob('VaultRag-*'):
        if file.suffix in ('.exe', '.dmg'):
            shutil.copyfile(file, output / file.name)
    shutil.copyfile(report, output / report.name)
    checksums.append((release / 'SHA256SUMS.txt').read_text(encoding='utf-8'))
    shutil.make_archive(str(output / ('licenses-' + platform)), 'zip', source / '_generated/desktop-licenses')
(output / 'SHA256SUMS.txt').write_text(''.join(checksums), encoding='utf-8')
if not list(output.glob('*.exe')) or not list(output.glob('*.dmg')):
    raise SystemExit('缺少 Windows 或 macOS 安装包，未准备 release')
