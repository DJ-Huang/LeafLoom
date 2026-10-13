"""Build inputs once; synchronize all release versions without editing lock files."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', default='0.2.0-beta.1')
    parser.add_argument('--skip-web-build', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?', args.version):
        raise SystemExit('版本必须是 SemVer，例如 0.2.0-beta.1')
    package_path = ROOT / 'desktop/package.json'
    package = json.loads(package_path.read_text(encoding='utf-8'))
    package['version'] = args.version
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lock_path = ROOT / 'desktop/package-lock.json'
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    lock['version'] = args.version
    lock['packages']['']['version'] = args.version
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    npm = 'npm.cmd' if sys.platform == 'win32' else 'npm'
    if not args.skip_web_build:
        subprocess.run([npm, '--prefix', str(ROOT / 'web'), 'run', 'build'], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/build_desktop_backend.py'), '--version', args.version], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/desktop_licenses.py')], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
