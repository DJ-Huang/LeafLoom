"""Bounded HTTPS streaming for host-provided file references, without ambient credentials."""
from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=30, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def public_target(url):
    if not isinstance(url, str) or len(url) > 16384 or any(ord(c) < 33 for c in url):
        raise ValueError('Invalid file download URL')
    target = urlsplit(url)
    if target.scheme != 'https' or not target.hostname or target.username or target.password or target.port not in (None, 443):
        raise ValueError('File download requires public HTTPS on port 443')
    host = target.hostname.encode('idna').decode('ascii')
    addresses = {row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    def public_address(address):
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast:
            return False
        if isinstance(ip, ipaddress.IPv6Address):
            if ip.sixtofour is not None or ip.teredo is not None:
                return False
            if ip in ipaddress.ip_network('64:ff9b::/96') or ip in ipaddress.ip_network('64:ff9b:1::/48'):
                return False
        return True
    if not addresses or not all(public_address(address) for address in addresses):
        raise ValueError('Private and local file download addresses are not allowed')
    return host, sorted(addresses)[0], target.path or '/', target.query


def download_file(url, stream, *, check, progress, max_size, chunk_size=262144):
    """Validate and pin every hop; never use proxy, cookie, bearer or netrc state."""
    deadline = time.monotonic() + 600
    for redirect in range(4):
        check()
        host, address, path, query = public_target(url)
        connection = PinnedHTTPSConnection(host, address)
        try:
            connection.request('GET', path + ('?' + query if query else ''), headers={'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location or redirect == 3:
                    raise ValueError('Too many file download redirects')
                url = urljoin(url, location)
                continue
            if response.status in (401, 403, 404, 410):
                raise ValueError('File reference expired or is unavailable; provide a fresh file reference')
            if response.status != 200 or response.getheader('Content-Encoding', 'identity') != 'identity':
                raise ValueError('File download failed')
            length = response.getheader('Content-Length')
            if length is not None and (not length.isdecimal() or int(length) > max_size):
                raise ValueError('File exceeds the upload size limit')
            received = 0
            while True:
                check()
                if time.monotonic() >= deadline:
                    raise ValueError('File download timed out')
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                received += len(chunk)
                if received > max_size:
                    raise ValueError('File exceeds the upload size limit')
                progress(received)
                stream.write(chunk)
            if length is not None and received != int(length):
                raise ValueError('Incomplete file download')
            return received
        except (OSError, http.client.HTTPException) as error:
            raise ValueError('File download failed; request a fresh file reference before retrying') from error
        finally:
            connection.close()
