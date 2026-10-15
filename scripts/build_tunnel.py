"""Fetch checksum-locked official runtime payloads; no end-user downloads."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import platform
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(base, name, digest, cache):
    target = cache / name
    if target.is_file() and sha256(target) == digest: return target
    partial = target.with_suffix('.part')
    try:
        with urllib.request.urlopen(base + name, timeout=60) as response, partial.open('wb') as stream:
            while block := response.read(1024 * 1024): stream.write(block)
        if sha256(partial) != digest: raise RuntimeError('Tunnel download checksum mismatch: ' + name)
        partial.replace(target)
    finally: partial.unlink(missing_ok=True)
    return target


def build(key):
    manifest = json.loads((ROOT / 'scripts/tunnel-runtime.json').read_text(encoding='utf-8'))
    spec = manifest['platforms'][key]
    cache = ROOT / '.cache/tunnel-build'
    cache.mkdir(parents=True, exist_ok=True)
    base = f'https://github.com/openai/tunnel-client/releases/download/v{manifest["version"]}/'
    archive = download(base, spec['asset'], spec['sha256'], cache)
    licenses = download(base, spec['licenses'], spec['licenses_sha256'], cache)
    output = ROOT / 'desktop/resources/tunnel' / key
    output.mkdir(parents=True, exist_ok=True)
    # Select individual verified members; never extract archive paths blindly.
    with zipfile.ZipFile(archive) as bundle:
        entries = {Path(name).name: name for name in bundle.namelist() if not name.endswith('/')}
        if spec['binary'] not in entries: raise RuntimeError('Tunnel binary missing from official archive')
        selected = [spec['binary'], *[name for name in entries if name.upper().startswith(('LICENSE', 'NOTICE', 'COPYING'))]]
        for name in selected:
            (output / name).write_bytes(bundle.read(entries[name]))
    (output / 'THIRD_PARTY_LICENSES.txt').write_bytes(licenses.read_bytes())
    binary = output / spec['binary']
    binary.chmod(0o755)
    receipt = {'version': manifest['version'], 'platform': key, 'archive_sha256': spec['sha256'],
               'binary': spec['binary'], 'binary_sha256': sha256(binary),
               'files': {p.name: sha256(p) for p in output.iterdir() if p.is_file() and p.name != 'bundle.json'}}
    (output / 'bundle.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(f'Tunnel {manifest["version"]} verified: {key}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    native = 'windows-x64' if platform.system() == 'Windows' else 'macos-arm64'
    parser.add_argument('--platform', choices=('windows-x64', 'macos-arm64', 'all'), default=native)
    args = parser.parse_args()
    for key in ('windows-x64', 'macos-arm64') if args.platform == 'all' else (args.platform,): build(key)
