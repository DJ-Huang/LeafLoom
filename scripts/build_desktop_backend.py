"""Build a relocatable onedir backend in the native CI environment."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', default='0.2.0-beta.1')
    args = parser.parse_args()
    supported = (sys.platform == 'darwin' and platform.machine() == 'arm64') or (
        sys.platform == 'win32' and platform.machine().lower() in ('amd64', 'x86_64'))
    if not supported:
        raise SystemExit('仅支持 macOS ARM64 或 Windows x64 原生构建')
    generated = ROOT / '_generated'
    generated.mkdir(exist_ok=True)
    model = json.loads((ROOT / 'desktop/model.json').read_text())
    (generated / 'desktop-build.json').write_text(json.dumps({
        'version': args.version, 'model_revision': model['revision'],
    }), encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                    '--distpath', str(ROOT / '_generated/backend'),
                    '--workpath', str(ROOT / '_generated/pyinstaller'),
                    str(ROOT / 'scripts/desktop_backend.spec')], cwd=ROOT, check=True,
                   env={**os.environ, 'PYINSTALLER_CONFIG_DIR': str(generated / 'pyinstaller-cache')})
    executable = generated / 'backend/vault-rag-backend' / ('vault-rag-backend.exe' if sys.platform == 'win32' else 'vault-rag-backend')
    subprocess.run([str(executable), 'self-check'], cwd=generated, check=True)


if __name__ == '__main__':
    main()
