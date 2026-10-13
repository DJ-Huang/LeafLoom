"""Collect third-party declarations and license texts from the exact build environment."""
from importlib import metadata
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / '_generated/desktop-licenses'


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'LICENSE', OUTPUT / 'LEAFLOOM-LICENSE.txt')
    shutil.copyfile(ROOT / 'THIRD_PARTY_NOTICES.md', OUTPUT / 'THIRD_PARTY_NOTICES.md')
    packages = []
    for dist in metadata.distributions():
        name = dist.metadata.get('Name', 'unknown')
        item = {'ecosystem': 'python', 'name': name, 'version': dist.version,
                'license': dist.metadata.get('License-Expression') or dist.metadata.get('License', ''), 'files': []}
        for file in dist.files or []:
            if file.name.lower().startswith(('license', 'copying', 'notice')) and dist.locate_file(file).is_file():
                target = OUTPUT / 'python' / name / str(file)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(dist.locate_file(file), target)
                item['files'].append(target.relative_to(OUTPUT).as_posix())
        packages.append(item)
    for manifest in (ROOT / 'desktop/node_modules').rglob('package.json'):
        if '/node_modules/' not in str(manifest) or not manifest.parent.name or manifest.parent.name.startswith('.'):
            continue
        try:
            info = json.loads(manifest.read_text())
        except (ValueError, UnicodeDecodeError):
            continue
        if not info.get('name') or not info.get('version'):
            continue
        files = []
        for file in manifest.parent.iterdir():
            if file.is_file() and file.name.lower().startswith(('license', 'copying', 'notice')):
                target = OUTPUT / 'npm' / info['name'] / info['version'] / file.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, target)
                files.append(target.relative_to(OUTPUT).as_posix())
        packages.append({'ecosystem': 'npm', 'name': info['name'], 'version': info['version'], 'license': info.get('license', ''), 'files': files})
    python_license = Path(sys.base_prefix) / 'LICENSE'
    if python_license.is_file():
        shutil.copyfile(python_license, OUTPUT / 'PYTHON-LICENSE.txt')
    (OUTPUT / 'dependencies.json').write_text(json.dumps(packages, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUTPUT / 'MODEL-NOTICE.txt').write_text('BGE-M3, BAAI, MIT. Model weights downloaded separately.\nhttps://huggingface.co/BAAI/bge-m3\n', encoding='utf-8')


if __name__ == '__main__':
    main()
