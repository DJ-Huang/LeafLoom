"""Scoped macOS resolver compatibility, hosted by the existing service process.

Only this installation's random *.localhost namespace is answered. No upstream
DNS, default resolver changes, hosts entries, or privileged background service.
"""
from __future__ import annotations

import argparse
import json
import logging
import platform
from pathlib import Path
import re
import shlex
import socket
import struct
import subprocess
import sys
import threading


class LocalDns:
    def __init__(self, identity, port):
        if not re.fullmatch('[a-f0-9]{32}', identity) or not 1024 <= int(port) <= 65535:
            raise ValueError('Invalid local resolver identity or port')
        self.zone = identity + '.localhost'
        self.port = int(port)
        self.socket = None
        self.thread = None
        self.error = ''

    def answer(self, packet):
        if len(packet) < 12 or len(packet) > 4096:
            return None
        ident, flags, count, _, _, _ = struct.unpack('!6H', packet[:12])
        if flags & 0xf800 or count != 1:
            return None
        end = 12
        labels = []
        while end < len(packet):
            size = packet[end]; end += 1
            if size == 0:
                break
            if size > 63 or end + size > len(packet):
                return None
            try: labels.append(packet[end:end + size].decode('ascii').lower())
            except UnicodeDecodeError: return None
            end += size
        else:
            return None
        if end > 267 or end + 4 > len(packet):
            return None
        kind, cls = struct.unpack('!2H', packet[end:end + 4]); end += 4
        name = '.'.join(labels)
        owned = name == self.zone or name.endswith('.' + self.zone)
        # IPv4 only: AAAA returns NODATA rather than an unreachable ::1 address.
        address = owned and cls == 1 and kind == 1
        header = struct.pack('!6H', ident, 0x8400 | (flags & 0x100) | (0 if owned else 5), 1, int(address), 0, 0)
        result = header + packet[12:end]
        if address:
            result += struct.pack('!HHHIH4s', 0xc00c, 1, 1, 30, 4, socket.inet_aton('127.0.0.1'))
        return result

    def start(self):
        if self.socket is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(('127.0.0.1', self.port)); sock.settimeout(.2)
        except OSError as error:
            sock.close(); self.error = str(error)
            logging.getLogger(__name__).warning('Local Safari resolver unavailable: %s', error)
            return
        self.socket = sock; self.error = ''
        def run():
            while self.socket is sock:
                try:
                    data, peer = sock.recvfrom(4097)
                    reply = self.answer(data)
                    if reply: sock.sendto(reply, peer)
                except socket.timeout: pass
                except OSError: break
        self.thread = threading.Thread(target=run, name='leafloom-local-dns', daemon=True)
        self.thread.start()

    def stop(self):
        sock, self.socket = self.socket, None
        if sock: sock.close()
        if self.thread: self.thread.join(timeout=1)

    @property
    def resolver_path(self):
        return Path('/etc/resolver') / self.zone

    def resolver_text(self):
        return f'# LeafLoom scoped resolver v1 {self.zone}\ndomain {self.zone}\nnameserver 127.0.0.1\nport {self.port}\ntimeout 1\n'

    def status(self):
        try: configured = not self.resolver_path.is_symlink() and self.resolver_path.read_text() == self.resolver_text()
        except OSError: configured = False
        version = platform.mac_ver()[0]
        return {'supported': sys.platform == 'darwin', 'needed': sys.platform == 'darwin' and bool(version) and int(version.split('.')[0]) < 26,
                'configured': configured, 'running': self.socket is not None,
                'zone': self.zone, 'port': self.port, 'error': self.error}

    def install_command(self, enabled):
        # Elevate fixed shell operations only, never a user-writable Python file.
        path = shlex.quote(str(self.resolver_path))
        marker = shlex.quote('# LeafLoom scoped resolver v1 ' + self.zone)
        guard = f'test ! -L /etc/resolver; test ! -L {path}; if test -e {path}; then /usr/bin/grep -Fxq -- {marker} {path}; fi'
        if not enabled:
            return f'set -eu; {guard}; /bin/rm -f {path}'
        return (f'set -eu; {guard}; /bin/mkdir -p /etc/resolver; '
                'tmp=$(/usr/bin/mktemp /etc/resolver/.leafloom.XXXXXX); trap \'/bin/rm -f "$tmp"\' EXIT; '
                f'/usr/bin/printf %s {shlex.quote(self.resolver_text())} > "$tmp"; '
                '/usr/sbin/chown root:wheel "$tmp"; /bin/chmod 644 "$tmp"; '
                f'/bin/mv -f "$tmp" {path}')

    def configure(self, enabled, *, sudo=False):
        if sys.platform != 'darwin':
            raise ValueError('此解析配置仅适用于 macOS')
        if self.status()['configured'] == enabled and (enabled or not self.resolver_path.exists()):
            return self.status()
        command = self.install_command(enabled)
        args = ['/usr/bin/sudo', '-n', '/bin/sh', '-c', command] if sudo else [
            '/usr/bin/osascript', '-e', 'do shell script ' + json.dumps(command) + ' with administrator privileges']
        try: result = subprocess.run(args, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired as error:
            raise ValueError('系统授权等待超时，请重试 Safari 兼容配置。原草稿与系统默认 DNS 保持不变。') from error
        if result.returncode:
            raise ValueError('本机解析配置未完成；原系统 DNS 保持不变。' + (result.stderr.strip() or '请重新尝试系统授权。'))
        return self.status()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'remove', 'status'])
    parser.add_argument('--identity', required=True)
    parser.add_argument('--port', type=int, default=18080)
    parser.add_argument('--sudo', action='store_true', help='Use noninteractive sudo (managed installation / CI only)')
    args = parser.parse_args()
    resolver = LocalDns(args.identity, args.port)
    print(json.dumps(resolver.status() if args.action == 'status' else resolver.configure(args.action == 'install', sudo=args.sudo)))


if __name__ == '__main__':
    main()
