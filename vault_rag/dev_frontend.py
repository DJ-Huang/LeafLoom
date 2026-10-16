"""Explicit desktop-development bridge; production never opts into this."""
from urllib.parse import urlsplit

import httpx
from starlette.responses import Response


class DevFrontend:
    def __init__(self, origin):
        url = urlsplit(origin)
        if (url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port
                or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment):
            raise ValueError('Development frontend must be an HTTP 127.0.0.1 origin')
        self.origin = f'http://127.0.0.1:{url.port}'
        self.websocket = f'ws://127.0.0.1:{url.port}'

    @staticmethod
    def asset(path):
        return path.startswith(('/@', '/src/', '/node_modules/', '/assets/')) or path == '/favicon.svg'

    async def response(self, path, query=''):
        # Never forward application credentials or cookies to the dev server.
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
                upstream = await client.get(self.origin + path + ('?' + query if query else ''))
            return Response(upstream.content, status_code=upstream.status_code,
                            headers={'Content-Type': upstream.headers.get('content-type', 'application/octet-stream'),
                                     'Cache-Control': 'no-store'})
        except httpx.HTTPError:
            return Response('Development frontend unavailable; restart Dev.cmd.', status_code=503)
