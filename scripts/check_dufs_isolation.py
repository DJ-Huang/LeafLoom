#!/usr/bin/env python3
"""Check a DUFS binary with disposable accounts on loopback; never use a real NAS.

Run with the same binary version as the server. Uses only synthetic passwords,
temporary files and a random local port. A nonzero exit blocks account rollout.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import uuid
import zipfile
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler, Request


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def verify(binary: Path | None = None, image: str | None = None):
    version_command = (['docker', 'run', '--rm', '--network', 'none', image, '--version']
                       if image else [str(binary), '--version'])
    version = subprocess.check_output(version_command, text=True).strip()
    template = Path(__file__).resolve().parents[1] / 'templates/dufs/config.yaml.example'
    checks = []

    def check(name, success):
        checks.append({'check': name, 'passed': bool(success)})

    # These accounts have no relationship to the operator's actual credentials.
    passwords = {'DJ': 'fictional-dj-password', 'Peer': 'fictional-peer-password'}
    hashes = {}
    for user, password in passwords.items():
        hashes[user] = subprocess.check_output(['openssl', 'passwd', '-6', '-stdin'],
            input=password + '\n', text=True).strip()
        if not hashes[user].startswith('$6$'):
            raise RuntimeError('OpenSSL did not produce a SHA-512 crypt password')

    with tempfile.TemporaryDirectory(prefix='leafloom-dufs-isolation-') as temporary:
        home = Path(temporary).resolve()
        data = home / 'data'
        for user in passwords:
            incoming = data / user / 'Incoming'
            incoming.mkdir(parents=True)
            (incoming / (user + '-sentinel.txt')).write_text(user + '-private-content')
        (home / 'outside.txt').write_text('outside-private-content')
        (data / 'DJ/Incoming/outside-link.txt').symlink_to('../../../outside.txt')
        (data / 'DJ/Incoming/peer-link.txt').symlink_to('../../Peer/Incoming/Peer-sentinel.txt')
        (data / 'DJ/Incoming/peer-dir').symlink_to('../../Peer', target_is_directory=True)
        (data / 'DJ/Incoming/own-link.txt').symlink_to('DJ-sentinel.txt')
        (data / 'DJ/Incoming/dangling-link.txt').symlink_to('../../Peer/Incoming/not-created.txt')

        content = template.read_text().replace('$6$REPLACE_WITH_EXISTING_SHA512_CRYPT_HASH', hashes['DJ'])
        content = content.replace('# Add one rule', "  - 'Peer:" + hashes['Peer'] + "@/Peer:rw'\n# Add one rule")
        config = home / 'config.yaml'
        config.write_text(content)
        config.chmod(0o600)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        opener = build_opener(ProxyHandler({}), NoRedirect())

        def request(method, path, user=None, body=None, headers=None):
            values = dict(headers or {})
            if user:
                values['Authorization'] = 'Basic ' + base64.b64encode(
                    (user + ':' + passwords[user]).encode()).decode()
            req = Request(base + path, data=body, method=method, headers=values)
            try:
                with opener.open(req, timeout=3) as response:
                    return response.status, response.read()
            except HTTPError as error:
                return error.code, error.read()

        # Enable the optional operations in this fixture to exercise their ACLs,
        # even when an installed server keeps them globally disabled.
        with (home / 'server.log').open('wb') as log:
            container = 'leafloom-dufs-isolation-' + uuid.uuid4().hex
            command = (['docker', 'run', '--rm', '--name', container,
                '--publish', f'127.0.0.1:{port}:5000', '--volume', f'{home}:/fixture', image,
                '--config', '/fixture/config.yaml', '/fixture/data',
                '--bind', '0.0.0.0', '--port', '5000'] if image else
                [str(binary), '--config', str(config), str(data), '--bind', '127.0.0.1', '--port', str(port)])
            process = subprocess.Popen(command + ['--allow-search', '--allow-delete', '--allow-archive'],
                                       stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 10
                while True:
                    if process.poll() is not None:
                        raise RuntimeError('DUFS stopped before the fixture was ready')
                    try:
                        if request('GET', '/__dufs__/health')[0] == 200:
                            break
                    except (URLError, TimeoutError):
                        pass
                    if time.monotonic() >= deadline:
                        raise RuntimeError('DUFS fixture did not become ready')
                    time.sleep(.05)

                check('anonymous access rejected', request('GET', '/DJ/')[0] == 401)
                for user, other in (('DJ', 'Peer'), ('Peer', 'DJ')):
                    own = f'/{user}/Incoming/{user}-sentinel.txt'
                    foreign = f'/{other}/Incoming/{other}-sentinel.txt'
                    check(user + ' own read', request('GET', own, user) == (200, (user + '-private-content').encode()))
                    check(user + ' own PROPFIND', request('PROPFIND', f'/{user}/', user,
                          headers={'Depth': '1'})[0] == 207)
                    target = f'/{user}/Incoming/upload.txt'
                    check(user + ' own upload', request('PUT', target, user, b'fixture-upload')[0] == 201)
                    check(user + ' uploaded readback', request('GET', target, user) == (200, b'fixture-upload'))
                    for method in ('GET', 'HEAD', 'PROPFIND', 'PUT', 'DELETE'):
                        status, _ = request(method, foreign, user,
                            body=b'forbidden' if method == 'PUT' else None, headers={'Depth': '0'})
                        check(user + ' foreign ' + method, status in (401, 403))
                    check(user + ' foreign MKCOL', request('MKCOL', f'/{other}/Incoming/new-dir', user)[0] in (401, 403))
                    check(user + ' foreign archive', request('GET', f'/{other}/?zip', user)[0] in (401, 403))
                    for method in ('COPY', 'MOVE'):
                        status, _ = request(method, own, user, headers={
                            'Destination': base + f'/{other}/Incoming/stolen.txt', 'Overwrite': 'F'})
                        check(user + ' foreign destination ' + method, status in (401, 403))
                        status, _ = request(method, foreign, user, headers={
                            'Destination': base + f'/{user}/Incoming/stolen.txt', 'Overwrite': 'F'})
                        check(user + ' foreign source ' + method, status in (401, 403))
                    for query in ('?json', '?json&q=sentinel'):
                        status, listing = request('GET', '/' + query, user)
                        check(user + ' filtered listing ' + query,
                              status == 200 and other.encode() not in listing)
                    status, _ = request('GET', f'/{user}/%2e%2e/{other}/Incoming/{other}-sentinel.txt', user)
                    check(user + ' encoded traversal rejected', status in (400, 401, 403, 404))
                check('DJ originals remain read-only', request('PUT', '/DJ/new.txt', 'DJ', b'forbidden')[0] in (401, 403))
                check('outside-root symlink rejected', request('GET', '/DJ/Incoming/outside-link.txt', 'DJ')[0] in (401, 403, 404))
                check('cross-account symlink rejected', request('GET', '/DJ/Incoming/peer-link.txt', 'DJ')[0] in (401, 403, 404))
                check('same-account symlink rejected', request('GET', '/DJ/Incoming/own-link.txt', 'DJ')[0] in (401, 403, 404))
                for method in ('GET', 'HEAD', 'PROPFIND', 'PUT', 'PATCH', 'DELETE', 'MKCOL'):
                    target = '/DJ/Incoming/peer-dir/Incoming/Peer-sentinel.txt'
                    if method == 'MKCOL':
                        target = '/DJ/Incoming/peer-dir/Incoming/new-dir'
                    status, _ = request(method, target, 'DJ', body=b'forbidden' if method in ('PUT', 'PATCH') else None,
                                        headers={'Depth': '1', 'X-Update-Range': 'append'})
                    check('symlink ancestor ' + method, status in (400, 401, 403, 404))
                check('dangling symlink upload rejected', request('PUT', '/DJ/Incoming/dangling-link.txt',
                      'DJ', b'forbidden')[0] in (400, 401, 403, 404))
                for method in ('COPY', 'MOVE'):
                    status, _ = request(method, '/DJ/Incoming/DJ-sentinel.txt', 'DJ', headers={
                        'Destination': base + '/DJ/Incoming/peer-dir/Incoming/stolen.txt', 'Overwrite': 'F'})
                    check('symlink destination ' + method, status in (400, 401, 403, 404))
                    status, _ = request(method, '/DJ/Incoming/peer-link.txt', 'DJ', headers={
                        'Destination': base + '/DJ/Incoming/stolen.txt', 'Overwrite': 'F'})
                    check('symlink source ' + method, status in (400, 401, 403, 404))
                for method, query in (('GET', '?json'), ('GET', '?json&q=sentinel'), ('PROPFIND', '')):
                    status, listing = request(method, '/DJ/Incoming/' + query, 'DJ', headers={'Depth': '1'})
                    check('symlinks hidden from ' + method + query,
                          status in (200, 207) and b'Peer' not in listing and b'peer-link' not in listing and b'peer-dir' not in listing)
                status, archive = request('GET', '/DJ/?zip', 'DJ')
                archive_safe = False
                if status == 200:
                    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
                        archive_safe = all('peer-' not in name and '-link' not in name for name in zipped.namelist())
                        archive_safe = archive_safe and all(b'Peer-private-content' not in zipped.read(name)
                            for name in zipped.namelist() if not name.endswith('/'))
                check('archive excludes linked data', archive_safe)
                check('foreign originals unchanged', (data / 'Peer/Incoming/Peer-sentinel.txt').read_text() == 'Peer-private-content'
                      and (data / 'DJ/Incoming/DJ-sentinel.txt').read_text() == 'DJ-private-content'
                      and not (data / 'Peer/Incoming/not-created.txt').exists()
                      and not (data / 'Peer/Incoming/stolen.txt').exists()
                      and not (data / 'Peer/Incoming/new-dir').exists())
            finally:
                if image:
                    subprocess.run(['docker', 'rm', '--force', container], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=10, check=False)
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    return {'version': version, 'passed': all(item['passed'] for item in checks), 'checks': checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--dufs', type=Path, help='Path to the same-version DUFS binary')
    target.add_argument('--docker-image', help='Test the exact Linux image before NAS deployment')
    args = parser.parse_args()
    result = verify(args.dufs.expanduser().resolve() if args.dufs else None, args.docker_image)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
