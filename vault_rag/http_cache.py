"""Private conditional file reads, evaluated only after route access checks."""
from __future__ import annotations

from email.utils import parsedate_to_datetime
import hashlib
from starlette.responses import FileResponse, Response


def conditional_file(path, request=None, *, headers=None, identity='', **kwargs):
    response = FileResponse(path, stat_result=path.stat(), **kwargs)
    if identity:response.headers['ETag']='"'+hashlib.sha256((identity+response.headers['etag']).encode()).hexdigest()+'"'
    response.headers['Cache-Control'] = 'private, no-cache'
    if headers:
        response.headers.update(headers)
    if request is None or request.method not in ('GET', 'HEAD') or 'range' in request.headers:
        return response
    match = request.headers.get('if-none-match')
    unchanged = False
    if match:
        unchanged = any(tag.strip().removeprefix('W/') in ('*', response.headers['etag'])
                        for tag in match.split(','))
    elif not identity and request.headers.get('if-modified-since'):
        try:
            unchanged = (parsedate_to_datetime(request.headers['if-modified-since']) >=
                         parsedate_to_datetime(response.headers['last-modified']))
        except (TypeError, ValueError, OverflowError):
            pass
    if unchanged:
        return Response(status_code=304, headers={key: value for key, value in response.headers.items()
                        if key not in ('content-length', 'content-type')})
    return response
