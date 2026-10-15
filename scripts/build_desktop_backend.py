"""Build a relocatable, locked Python payload on its native target OS.

Never copies a development venv or user data. We install into the standalone
interpreter's own prefix, so its site-packages move with the application.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=ROOT, env=None, quiet_stdout=False):
    print('Build:', args[0], flush=True)
    subprocess.run([str(a) for a in args], cwd=cwd, env=env, check=True, stdout=subprocess.DEVNULL if quiet_stdout else None)


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def lock_checksum():
    # Git may check this text file out with CRLF on Windows. Line endings do not
    # change the locked dependencies or invalidate an otherwise matching payload.
    return hashlib.sha256((ROOT / 'uv.lock').read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def download(spec, cache):
    archive = cache / ('python-' + spec['sha256'] + '.tar.gz')
    if archive.exists() and checksum(archive).lower() == spec['sha256'].lower():
        return archive
    temp = archive.with_suffix('.part')
    with urllib.request.urlopen(spec['url'], timeout=120) as response, temp.open('wb') as output:
        shutil.copyfileobj(response, output)
    if checksum(temp).lower() != spec['sha256'].lower():
        raise RuntimeError('Standalone Python checksum mismatch')
    temp.replace(archive)
    return archive


def mac_binaries(prefix):
    """Explicitly include Python, extension modules and dylibs in nested signing."""
    result = []
    magic = {bytes.fromhex(s) for s in ('feedface', 'feedfacf', 'cefaedfe', 'cffaedfe', 'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca')}
    for file in prefix.rglob('*'):
        if file.is_file() and not file.is_symlink():
            with file.open('rb') as stream:
                if stream.read(4) in magic:
                    result.append(file.relative_to(prefix).as_posix())
    return sorted(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'desktop/resources/backend')
    parser.add_argument('--runtime-source', type=Path, help='Optional clean standalone Python prefix; never a venv. Locked dependencies are installed separately.')
    parser.add_argument('--uv', type=Path, help='Path to the uv version pinned in scripts/runtimes.json')
    parser.add_argument('--refresh-app', action='store_true', help='Rebuild only the app wheel when the existing private runtime/lock match')
    args = parser.parse_args()
    from installer import platform_key
    key = platform_key()
    uv = str(args.uv.resolve()) if args.uv else shutil.which('uv')
    if not uv:
        raise RuntimeError('Build machines need uv; end users do not.')
    manifest = json.loads((ROOT / 'scripts/runtimes.json').read_text())
    uv_version = subprocess.check_output([uv, '--version'], text=True).split()[1]
    if uv_version != manifest['uv_version']:
        raise RuntimeError(f'Build requires uv {manifest["uv_version"]}; found {uv_version}. Use --uv PATH.')
    version = json.loads((ROOT / 'desktop/package.json').read_text())['version']
    output = args.output.resolve()
    # Output is generated build state; never replace a repository/user-data root.
    allowed = (ROOT / 'desktop/resources').resolve()
    if not output.is_relative_to(allowed) or output == allowed:
        raise ValueError('Backend output must be a child of desktop/resources')
    cache = ROOT / '.cache/desktop-build'
    cache.mkdir(parents=True, exist_ok=True)
    if args.refresh_app:
        receipt = json.loads((output / 'bundle.json').read_text(encoding='utf-8'))
        if receipt['platform'] != key or receipt['python'] != manifest['python'] or receipt['lock_sha256'] not in (lock_checksum(), checksum(ROOT / 'uv.lock')):
            raise RuntimeError('Private runtime/lock changed; run a full backend build')
        wheels = cache / 'app-wheels'
        run(uv, 'build', '--wheel', '--out-dir', wheels)
        app_wheel = wheels / f'vault_rag-{version}-py3-none-any.whl'
        python = output / 'python' / ('python.exe' if key == 'windows-x64' else 'bin/python3')
        run(uv, 'pip', 'install', '--python', python, '--system', '--break-system-packages', '--no-deps', '--reinstall', '--link-mode', 'copy', app_wheel)
        receipt.update(version=version, wheel_sha256=checksum(app_wheel), lock_sha256=lock_checksum())
        (output / 'bundle.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print('Application wheel refreshed; locked native dependencies retained.')
        return
    archive = None
    if not args.runtime_source:
        print('Downloading checksum-locked standalone Python...', flush=True)
        archive = download(manifest['platforms'][key]['python'], cache)
    else:
        source = args.runtime_source.resolve()
        if (source / 'pyvenv.cfg').exists():
            raise ValueError('A development venv cannot be used as the standalone runtime')
        source_python = source / ('python.exe' if key == 'windows-x64' else 'bin/python3')
        info = json.loads(subprocess.check_output([str(source_python), '-I', '-c', 'import json,sys,platform;print(json.dumps([platform.python_version(),sys.platform,platform.machine().lower(),sys.prefix,sys.base_prefix]))'], text=True))
        if info[0] != manifest['python'] or Path(info[3]).resolve() != source or info[3] != info[4]:
            raise ValueError('Standalone source prefix/version mismatch')
        if (key == 'windows-x64' and (info[1] != 'win32' or info[2] not in ('amd64', 'x86_64'))) or (key == 'macos-arm64' and (info[1] != 'darwin' or info[2] != 'arm64')):
            raise ValueError('Standalone source architecture mismatch')
    with tempfile.TemporaryDirectory(prefix='payload-', dir=cache, ignore_cleanup_errors=True) as temporary:
        work = Path(temporary)
        payload = work / 'backend'
        payload.mkdir()
        if archive:
            with tarfile.open(archive) as source_archive:
                source_archive.extractall(payload, filter='data')
        else:
            shutil.copytree(source, payload / 'python', ignore=shutil.ignore_patterns('site-packages', 'Scripts', '__pycache__', '*.pyc'), symlinks=True)
        python = payload / 'python' / ('python.exe' if key == 'windows-x64' else 'bin/python3')
        if not python.is_file():
            raise RuntimeError('Standalone Python archive layout changed')
        wheels = work / 'wheels'
        run(uv, 'build', '--wheel', '--out-dir', wheels)
        app_wheel, = wheels.glob('vault_rag-*.whl')
        requirements = work / 'requirements.txt'
        run(uv, 'export', '--frozen', '--no-dev', '--no-emit-project', '--format', 'requirements-txt', '--output-file', requirements, quiet_stdout=True)
        # Use the exact locked CPU wheel URL rather than searching a second
        # package index for every unrelated dependency.
        if key == 'windows-x64':
            lock = tomllib.loads((ROOT / 'uv.lock').read_text(encoding='utf-8'))
            torch = next(p for p in lock['package'] if p['name'] == 'torch' and '+cpu' in p['version'])
            wheel = next(w for w in torch['wheels'] if 'cp312-cp312-win_amd64.whl' in w['url'])
            lines = requirements.read_text(encoding='utf-8').splitlines(keepends=True)
            selected = []; count = 0; index = 0
            while index < len(lines):
                line = lines[index]
                if line.startswith('torch==') and '+cpu' in line:
                    marker = line.partition(';')[2].replace('\\', '').strip()
                    selected.append(f'torch @ {wheel["url"]} ; {marker} \\\n    --hash={wheel["hash"]}\n')
                    count += 1; index += 1
                    while index < len(lines) and lines[index].lstrip().startswith('--hash='):
                        index += 1
                    continue
                selected.append(line); index += 1
            if count != 1:
                raise RuntimeError('Locked Windows torch requirement not found')
            requirements.write_text(''.join(selected), encoding='utf-8')
        pip_args = [uv, 'pip', 'install', '--python', python, '--system', '--break-system-packages', '--require-hashes', '--no-deps', '--link-mode', 'copy', '-r', requirements]
        try:
            run(*pip_args, '--offline')
        except subprocess.CalledProcessError:
            run(*pip_args)
        run(uv, 'pip', 'install', '--python', python, '--system', '--break-system-packages', '--no-deps', '--link-mode', 'copy', app_wheel)
        # Check outside the repository with isolated imports, before promoting it.
        env = dict(os.environ, VAULT_RAG_HOME=str(work / 'check-state'), PYTHONDONTWRITEBYTECODE='1')
        run(python, '-I', '-B', '-X', 'utf8', '-m', 'vault_rag.desktop_entry', '--check', cwd=work, env=env)
        (payload / 'bundle.json').write_text(json.dumps({'schema': 1, 'platform': key, 'version': version,
            'python': manifest['python'], 'lock_sha256': lock_checksum(),
            'wheel_sha256': checksum(app_wheel), 'runtime_source': 'checksum-locked-archive' if archive else 'verified-standalone-prefix',
            'mac_binaries': mac_binaries(payload / 'python') if key == 'macos-arm64' else []}, indent=2), encoding='utf-8')
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            # No recursive delete; preserve the previously working generated payload.
            backup = output.with_name(output.name + '-previous')
            if backup.exists():
                backup = output.with_name(output.name + '-previous-' + next(tempfile._get_candidate_names()))
            if not backup.resolve().is_relative_to(allowed):
                raise ValueError('Invalid generated backup path')
            output.rename(backup)
        payload.rename(output)
    print('Private backend:', output)
    if sys.platform == 'darwin':
        icons = ROOT / 'desktop/resources/leafloom.iconset'
        icons.mkdir(exist_ok=True)
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                name = f'icon_{size}x{size}' + ('@2x' if scale == 2 else '') + '.png'
                run('sips', '-z', size * scale, size * scale, ROOT / 'assets/brand/logo.png', '--out', icons / name)
        run('iconutil', '-c', 'icns', icons, '-o', ROOT / 'desktop/resources/leafloom.icns')


if __name__ == '__main__':
    main()
