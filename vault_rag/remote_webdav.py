"""Bounded WebDAV transport. Never uses ambient proxies, cookies or redirects."""
from __future__ import annotations

from contextlib import contextmanager,nullcontext
import email.utils
import hashlib
import ipaddress
import logging
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import time
import uuid
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

import httpx

from vault_rag.attachment_scan_policy import normalize_scan_roots
from vault_rag.remote_ignore import IGNORE_NAME,MAX_IGNORE_BYTES,RemoteIgnore,IgnoreRuleError

logger=logging.getLogger(__name__)
_SHARED_IPV4 = ipaddress.ip_network('100.64.0.0/10')


def is_private_http_host(host):
    """Allow numeric local/private hosts, including RFC 6598 VPN addresses."""
    try:address=ipaddress.ip_address(host)
    except (ValueError,TypeError):return False
    return (not address.is_unspecified and not address.is_multicast and
            (address.is_loopback or address.is_private or address in _SHARED_IPV4))


class RemoteStorageError(Exception):
    def __init__(self, code, state='invalid_service', *, reason='', operation=''):
        super().__init__(code)
        self.code = code
        self.state = state
        self.reason = reason
        self.operation = operation


def remote_path(value, *, allow_empty=True):
    if not isinstance(value, str) or len(value) > 4096 or '\\' in value or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid remote attachment path')
    if value.startswith('/') or any(p in {'.', '..'} or p.startswith('.') for p in value.split('/') if p):
        raise ValueError('Invalid remote attachment path')
    if any(p in {'..', '.'} for p in unquote(value).split('/')):
        raise ValueError('Encoded remote traversal is not allowed')
    result = PurePosixPath(value).as_posix() if value else ''
    if result == '.':result = ''
    if not allow_empty and not result:raise ValueError('Select a remote attachment file')
    return result


def validate_source(source):
    if isinstance(source,dict) and (source.get('type')=='smb' or str(source.get('base_url','')).startswith(('smb://','\\\\'))):
        from vault_rag.remote_smb import validate_smb_source
        return validate_smb_source(source)
    allowed = {'id','name','type','base_url','remote_root','username','enabled','upload_directory','metadata_directory','secret_ref','allow_private_http','connection_hint','revision','scan_roots','scan_paused'}
    if not isinstance(source, dict) or set(source) - allowed:
        raise ValueError('Unsupported attachment source setting')
    result = dict(source)
    if result.get('type', 'webdav') != 'webdav':raise ValueError('Unsupported attachment source')
    try:result['id']=uuid.UUID(str(result.get('id',''))).hex
    except (ValueError,AttributeError):raise ValueError('Attachment source ID must be a UUID') from None
    try:
        url = urlsplit(result.get('base_url', ''))
        if url.username is not None or url.password is not None or url.query or url.fragment or not url.hostname:
            raise ValueError
        if url.scheme != 'https':
            if url.scheme != 'http' or result.get('allow_private_http') is not True:
                raise ValueError
            if not is_private_http_host(url.hostname):
                raise ValueError
        if url.port is not None and not 1 <= url.port <= 65535:raise ValueError
        base = unquote(url.path)
        if '\\' in base or any(p in {'.','..'} for p in base.split('/')) or any(ord(c) < 32 for c in base):
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError('Use HTTPS, or explicitly allow an IP address on the private HTTP network') from None
    result.update(type='webdav', base_url=urlunsplit((url.scheme, url.netloc, quote(base.rstrip('/') + '/', safe='/'), '', '')),
                  remote_root=remote_path(str(result.get('remote_root','')).strip('/')),
                  enabled=result.get('enabled',True),username=result.get('username',''),name=result.get('name',result['id']),
                  upload_directory=remote_path(result.get('upload_directory', 'Incoming')),
                  connection_hint=result.get('connection_hint', 'direct'))
    if result['connection_hint'] not in {'direct','official-client'}:raise ValueError('Invalid connection hint')
    result['scan_roots']=normalize_scan_roots(result.get('scan_roots',['']))
    result['scan_paused']=result.get('scan_paused',False)
    if type(result['scan_paused'])is not bool:raise ValueError('Invalid automatic scan setting')
    if type(result['enabled'])is not bool:raise ValueError('Invalid source enabled setting')
    writable=result['upload_directory']
    result['metadata_directory']=remote_path(result.get('metadata_directory','/'.join(p for p in (writable,'LeafLoomCatalog/v1') if p)),allow_empty=False)
    if writable and not result['metadata_directory'].startswith(writable+'/'):raise ValueError('Metadata directory must be inside the upload directory')
    for key in ('name','secret_ref','username'):
        if key in result and (not isinstance(result[key],str) or len(result[key])>200):raise ValueError('Invalid source setting')
    return result


class WebDAVSource:
    def __init__(self, source, credentials=None, *, transport=None, guard=None, on_error=None):
        self.source = validate_source(source)
        self.credentials = credentials
        self.transport = transport
        self.guard = guard or (lambda: None)
        self.on_error = on_error
        self._session_client = None

    def _failed(self, code, state='invalid_service', *, reason='', operation=''):
        error=RemoteStorageError(code,state,reason=reason,operation=operation)
        if self.on_error is not None:self.on_error(error)
        raise error from None

    def url(self, path):
        parts=[part for part in (self.source['remote_root'],remote_path(path)) if part]
        return self.source['base_url'] + quote('/'.join(parts), safe='/')

    def fork(self):
        return type(self)(self.source,self.credentials,transport=self.transport,guard=self.guard,on_error=self.on_error)

    def _client(self,*,keepalive=True):
        options={} if keepalive else {'limits':httpx.Limits(max_keepalive_connections=0)}
        return httpx.Client(auth=httpx.BasicAuth(*self.credentials) if self.credentials else None,
                            trust_env=False, follow_redirects=False, timeout=httpx.Timeout(30, connect=8),
                            transport=self.transport, headers={'Accept-Encoding':'identity'},**options)

    @contextmanager
    def session(self):
        """Opt-in HTTP client reuse for one guarded, serial metadata batch."""
        if self._session_client is not None:
            yield self;return
        # The official desktop bridge can terminate reused PROPFIND sockets.
        # Retain the bounded batch client/TLS setup, but open fresh sockets for
        # this opt-in transport only; ordinary attachment requests are unchanged.
        manager=self._client(keepalive=False) if self.source['connection_hint']=='official-client' else self._client()
        with manager as client:
            self._session_client=client
            try:yield self
            finally:self._session_client=None

    def _status(self, response, allowed=(200,)):
        if 300 <= response.status_code < 400:raise RemoteStorageError('redirect_refused')
        if response.status_code in {401,403}:self._failed('authentication_required','auth_required')
        if response.status_code in {502,503,504}:self._failed('service_temporarily_unavailable','unreachable')
        if response.status_code in {404,410} and response.status_code not in allowed:raise RemoteStorageError('remote_not_found')
        if response.status_code not in allowed:raise RemoteStorageError('unexpected_http_status')

    def _request(self, method, path, *, headers=None, content=None, allowed=(200,), limit=2*1024*1024, retry_timeouts=0):
        for attempt in range(retry_timeouts+1):
            self.guard()
            try:
                target=self.url(path)
                if method=='PROPFIND':target=target.rstrip('/')+'/'
                with (nullcontext(self._session_client) if self._session_client is not None else self._client()) as client:
                    # A reused connection must never turn a Set-Cookie response into
                    # ambient authentication on a later metadata request.
                    client.cookies.clear()
                    try:
                        with client.stream(method,target,headers=headers,content=content) as response:
                            self._status(response, allowed)
                            data = bytearray()
                            for chunk in response.iter_bytes():
                                self.guard()
                                data.extend(chunk)
                                if len(data)>limit:raise RemoteStorageError('response_too_large')
                            return response.status_code, dict(response.headers), bytes(data)
                    finally:client.cookies.clear()
            except httpx.HTTPError as error:
                if isinstance(error, httpx.TimeoutException) and attempt < retry_timeouts:
                    logger.warning('WebDAV timeout method=%s type=%s retry=%s',method,type(error).__name__,attempt+1)
                    time.sleep(0.5 * (attempt+1))
                    continue
                logger.warning('WebDAV transport failure method=%s type=%s',method,type(error).__name__)
                reason=('server_connect_timeout' if isinstance(error,httpx.ConnectTimeout) else
                        'server_read_timeout' if isinstance(error,httpx.ReadTimeout) else
                        'server_connection_busy' if isinstance(error,httpx.PoolTimeout) else
                        'server_connection_interrupted' if isinstance(error,(httpx.ReadError,httpx.RemoteProtocolError)) else
                        'server_connect_failed' if isinstance(error,httpx.ConnectError) else 'connection_unavailable')
                self._failed('connection_unavailable','unreachable',reason=reason,operation=method)

    @staticmethod
    def _metadata(path, headers):
        try:size=int(headers.get('content-length',0))
        except (ValueError,TypeError):raise RemoteStorageError('invalid_content_length') from None
        if size<0:raise RemoteStorageError('invalid_content_length')
        return {'path':path,'name':PurePosixPath(path).name,'size':size,'etag':headers.get('etag',''),
                'mtime':headers.get('last-modified',''),'metadata_origin':'head','mime':headers.get('content-type','').split(';')[0] or mimetypes.guess_type(path)[0] or 'application/octet-stream','is_dir':False}

    def stat(self,path):
        path=remote_path(path,allow_empty=False)
        _,headers,_=self._request('HEAD',path,limit=0)
        return self._metadata(path,headers)

    def _propfind(self,path,*,retry_timeouts=0):
        body=b'<?xml version="1.0"?><propfind xmlns="DAV:"><prop><resourcetype/><getcontentlength/><getlastmodified/><getetag/><getcontenttype/></prop></propfind>'
        _,_,data=self._request('PROPFIND',path,headers={'Depth':'1','Content-Type':'application/xml'},content=body,allowed=(207,),limit=16*1024*1024,retry_timeouts=retry_timeouts)
        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():raise RemoteStorageError('unsafe_xml')
        try:tree=ET.fromstring(data)
        except ET.ParseError:raise RemoteStorageError('invalid_webdav_xml') from None
        if tree.tag!='{DAV:}multistatus':raise RemoteStorageError('invalid_webdav_xml')
        origin=urlsplit(self.url(''));base=unquote(origin.path).rstrip('/')+'/'
        result=[];self_seen=False
        def status_code(value):
            match=re.match(r'^HTTP/\S+\s+(\d{3})(?:\s|$)',value.strip())
            if not match:raise RemoteStorageError('incomplete_webdav_listing')
            return int(match[1])
        def reject_status(code):
            if code in {401,403}:self._failed('authentication_required','auth_required')
            if code>=500:self._failed('incomplete_webdav_listing','unreachable')
        for item in tree.findall('{DAV:}response'):
            href=item.findtext('{DAV:}href','')
            if not href:raise RemoteStorageError('incomplete_webdav_listing')
            response_status=item.findtext('{DAV:}status','')
            if response_status:
                code=status_code(response_status);reject_status(code)
                if not 200<=code<300:raise RemoteStorageError('incomplete_webdav_listing')
            parsed=urlsplit(urljoin(self.url(path).rstrip('/')+'/',href))
            if parsed.query or parsed.fragment or parsed.username or parsed.password:raise RemoteStorageError('out_of_scope_href')
            if parsed.netloc and (parsed.scheme.lower(),parsed.netloc.lower())!=(origin.scheme.lower(),origin.netloc.lower()):
                raise RemoteStorageError('out_of_scope_href')
            absolute=unquote(parsed.path)
            if absolute.rstrip('/')==base.rstrip('/'):rel=''
            else:
                if not absolute.startswith(base):raise RemoteStorageError('out_of_scope_href')
                remainder=absolute[len(base):].rstrip('/')
                if any(part.startswith('.') and part not in {'.','..'} for part in remainder.split('/')):continue
                try:rel=remote_path(remainder)
                except ValueError:raise RemoteStorageError('out_of_scope_href') from None
            props=ET.Element('{DAV:}prop');failed_required=False
            for propstat in item.findall('{DAV:}propstat'):
                code=status_code(propstat.findtext('{DAV:}status',''));reject_status(code)
                block=propstat.find('{DAV:}prop')
                if block is None:raise RemoteStorageError('incomplete_webdav_listing')
                if code==200:
                    for prop in block:
                        previous=props.find(prop.tag)
                        if previous is not None and ET.tostring(previous)!=ET.tostring(prop):raise RemoteStorageError('invalid_webdav_metadata')
                        if previous is None:props.append(prop)
                elif block.find('{DAV:}resourcetype') is not None:failed_required=True
            resource_type=props.find('{DAV:}resourcetype')
            if failed_required or resource_type is None:raise RemoteStorageError('incomplete_webdav_listing')
            directory=props.find('{DAV:}resourcetype/{DAV:}collection') is not None
            if rel==path:
                if not directory:raise RemoteStorageError('incomplete_webdav_listing')
                self_seen=True
            if not directory and props.find('{DAV:}getcontentlength') is None:raise RemoteStorageError('incomplete_webdav_listing')
            size=props.findtext('{DAV:}getcontentlength','0')
            try:size=int(size)
            except ValueError:raise RemoteStorageError('invalid_webdav_metadata') from None
            if size<0:raise RemoteStorageError('invalid_webdav_metadata')
            entry={'path':rel,'name':PurePosixPath(rel).name,'size':size,'mtime':props.findtext('{DAV:}getlastmodified',''),
                   'metadata_origin':'propfind','mime':props.findtext('{DAV:}getcontenttype','') or mimetypes.guess_type(rel)[0] or 'application/octet-stream','is_dir':directory}
            etag=props.findtext('{DAV:}getetag','')
            if etag:entry['etag']=etag
            result.append(entry)
        if not self_seen:raise RemoteStorageError('incomplete_webdav_listing')
        return result

    def test(self):
        entries=self._propfind('')
        return {'state':'ready','read_verified':True,'upload_verified':False,'entries':len(entries)}

    def _ignore_bytes(self,path,*,expected_etag=''):
        headers={'If-Match':expected_etag} if expected_etag else {}
        _,reply,data=self._request('GET',path,headers=headers,limit=MAX_IGNORE_BYTES)
        if 'text/html' in reply.get('content-type','').lower():raise RemoteStorageError('ignore_rules_login_page')
        if expected_etag and reply.get('etag',expected_etag)!=expected_etag:raise RemoteStorageError('ignore_rules_changed')
        length=reply.get('content-length')
        if length is not None and length!=str(len(data)):raise RemoteStorageError('ignore_rules_invalid_length')
        return data

    def read_bytes(self,path,*,max_bytes=256*1024):
        _,headers,data=self._request('GET',path,limit=max_bytes)
        if 'text/html' in headers.get('content-type','').lower():raise RemoteStorageError('unexpected_login_page')
        if 'content-length' in headers and headers['content-length']!=str(len(data)):raise RemoteStorageError('invalid_content_length')
        return data

    def ensure_directory(self,path,*,verified=None):
        """Create only descendants of the configured writable upload folder."""
        path=remote_path(path,allow_empty=False);writable=self.source['upload_directory']
        if writable and not path.startswith(writable+'/'):raise ValueError('Directory is outside the writable attachment area')
        parts=path.split('/');start=len(writable.split('/')) if writable else 0
        self.guard()
        for depth in range(start+1,len(parts)+1):
            current='/'.join(parts[:depth])
            if verified is not None and current in verified:continue
            status,_,_=self._request('MKCOL',current,allowed=(201,405,409) if verified is not None else (201,405),limit=65536)
            if status==409:raise RemoteStorageError('metadata_parent_missing')
            if not any(item['path']==current and item['is_dir'] for item in self._propfind(current)):
                raise RemoteStorageError('metadata_directory_unavailable')
            if verified is not None:verified.add(current)

    def put_immutable(self,path,data,*,max_bytes=2*1024*1024,verified_directories=None):
        """Create a bounded immutable object, acknowledging only exact readback."""
        path=remote_path(path,allow_empty=False)
        if not isinstance(data,bytes) or len(data)>max_bytes:raise ValueError('Metadata object is too large')
        for attempt in range(2 if verified_directories is not None else 1):
            try:
                if verified_directories is not None:self.ensure_directory(str(PurePosixPath(path).parent),verified=verified_directories)
                status,_,_=self._request('HEAD',path,allowed=(200,404),limit=0)
                if status==404:
                    written,_,_=self._request('PUT',path,headers={'If-None-Match':'*','Content-Type':'application/octet-stream','Content-Length':str(len(data))},
                                             content=data,allowed=(201,204,409,412),limit=65536)
                    if written==409 and verified_directories is not None:raise RemoteStorageError('metadata_parent_missing')
                actual=self.read_bytes(path,max_bytes=max_bytes)
                if len(actual)!=len(data) or hashlib.sha256(actual).digest()!=hashlib.sha256(data).digest():
                    raise RemoteStorageError('immutable_object_conflict')
                return hashlib.sha256(actual).hexdigest()
            except RemoteStorageError as error:
                if verified_directories is None or error.code not in {'remote_not_found','metadata_parent_missing'}:raise
                verified_directories.clear()
                if attempt:raise

    def verify_ignore(self):
        for path,digest in getattr(self,'ignore_checks',[]):
            try:changed=hashlib.sha256(self._ignore_bytes(path)).hexdigest()!=digest
            except RemoteStorageError as error:
                if error.code!='remote_not_found':raise
                changed=True
            if changed:
                checkpoint=getattr(self,'scan_checkpoint',None)
                if checkpoint is not None:checkpoint.invalidate(path.rpartition('/')[0])
                raise RemoteStorageError('ignore_rules_changed')

    def _scan_ancestor_rules(self, roots, ignore):
        parents=set()
        for root in roots:
            parts=root.split('/') if root else []
            parents.update('/'.join(parts[:depth]) for depth in range(len(parts)))
        for directory in sorted(parents,key=lambda p:(p.count('/'),p)):
            path='/'.join(p for p in (directory,IGNORE_NAME) if p)
            try:data=self._ignore_bytes(path)
            except RemoteStorageError as error:
                if error.code=='remote_not_found':continue
                raise
            try:ignore.add(directory,data)
            except IgnoreRuleError as error:raise RemoteStorageError(str(error)) from None
            self.ignore_checks.append((path,hashlib.sha256(data).hexdigest()))

    def scan(self,path='',*,max_files=100000,max_depth=32,on_batch=None,ignore=None,prune_reserved=True,read_ignore=True,checkpoint=None,roots=None):
        if checkpoint is not None:return checkpoint.scan(self,path,max_files=max_files,max_depth=max_depth,on_batch=on_batch,ignore=ignore,prune_reserved=prune_reserved,read_ignore=read_ignore,roots=roots)
        path=remote_path(path);pending=[(p,0) for p in (normalize_scan_roots(roots) if roots is not None else [path])];seen=set();result=[]
        reserved=(self.source['metadata_directory'],) if prune_reserved else ()
        ignore=ignore or RemoteIgnore(reserved);self.ignore_checks=[];excluded=0
        if roots is not None and read_ignore:self._scan_ancestor_rules(roots,ignore)
        while pending:
            current,depth=pending.pop()
            if current in seen:continue
            seen.add(current)
            if depth>max_depth:raise RemoteStorageError('directory_depth_limit')
            batch=[];entries=self._propfind(current,retry_timeouts=2)
            for item in entries:
                rel=item['path']
                if rel==current:continue
                if current and not rel.startswith(current+'/'):raise RemoteStorageError('out_of_scope_href')
                child=rel[len(current)+1:] if current else rel
                if '/' in child:raise RemoteStorageError('out_of_scope_href')
            for item in entries:
                if read_ignore and item['path']!=current and not item['is_dir'] and item['name']==IGNORE_NAME:
                    if item['size']>MAX_IGNORE_BYTES:raise RemoteStorageError('ignore_rules_too_large')
                    try:data=self._ignore_bytes(item['path'],expected_etag=item.get('etag',''))
                    except RemoteStorageError as error:
                        if error.code=='remote_not_found':continue
                        raise
                    try:ignore.add(current,data)
                    except IgnoreRuleError as error:raise RemoteStorageError(str(error)) from None
                    self.ignore_checks.append((item['path'],hashlib.sha256(data).hexdigest()))
            for item in entries:
                rel=item['path']
                if rel==current:continue
                if current and not rel.startswith(current+'/'):raise RemoteStorageError('out_of_scope_href')
                if any(rel==prefix or rel.startswith(prefix+'/') for prefix in reserved):continue
                if item['is_dir']:pending.append((rel,depth+1))
                else:
                    item={**item,'excluded':ignore.excluded(rel),'ignore_control':item['name']==IGNORE_NAME}
                    excluded+=int(item['excluded'])
                    result.append(item);batch.append(item)
                if len(result)+len(pending)>max_files:raise RemoteStorageError('directory_count_limit')
            if on_batch is not None:
                on_batch(batch,{'scanned':len(result),'directories':len(seen),'pending_directories':len(pending),'excluded':excluded})
        return result

    def read_range(self,path,start=0,end=None,*,max_bytes=8*1024*1024,expected_etag=None,expected_size=None):
        meta=self.stat(path);size=meta['size']
        if expected_etag and meta['etag']!=expected_etag:raise RemoteStorageError('remote_version_changed')
        if expected_size is not None and size!=expected_size:raise RemoteStorageError('remote_version_changed')
        if type(start)is not int or start<0 or (end is not None and (type(end)is not int or end<start)):
            raise ValueError('Invalid attachment byte range')
        if size==0:
            if start:raise ValueError('Range is outside the attachment')
            return b'',meta
        if start>=size:raise ValueError('Range is outside the attachment')
        end=min(size-1,end if end is not None else size-1)
        if end-start+1>max_bytes:raise ValueError('Attachment byte range is too large')
        headers={'Range':f'bytes={start}-{end}'}
        if meta['etag']:headers['If-Match']=meta['etag']
        _,reply,data=self._request('GET',path,headers=headers,allowed=(206,),limit=max_bytes)
        if 'text/html' in reply.get('content-type','').lower() and Path(path).suffix.lower() not in {'.html','.htm'}:
            raise RemoteStorageError('unexpected_login_page')
        if reply.get('content-range')!=f'bytes {start}-{end}/{size}' or len(data)!=end-start+1:
            raise RemoteStorageError('invalid_range_response')
        if meta['etag'] and reply.get('etag',meta['etag'])!=meta['etag']:raise RemoteStorageError('remote_version_changed')
        return data,meta

    def download(self,path,destination,*,expected_size=None,expected_etag=None,max_bytes=None):
        meta=self.stat(path)
        if expected_size is not None and meta['size']!=expected_size:raise RemoteStorageError('remote_version_changed')
        if expected_etag and meta['etag']!=expected_etag:raise RemoteStorageError('remote_version_changed')
        if max_bytes is not None and meta['size']>max_bytes:raise RemoteStorageError('cache_object_too_large')
        headers={'If-Match':meta['etag']} if meta['etag'] else {}
        digest=hashlib.sha256();total=0;destination=Path(destination);created=False
        try:
            with self._client() as client, client.stream('GET',self.url(path),headers=headers) as response:
                self._status(response)
                if response.headers.get('content-length')!=str(meta['size']):raise RemoteStorageError('invalid_content_length')
                if meta['etag'] and response.headers.get('etag',meta['etag'])!=meta['etag']:raise RemoteStorageError('remote_version_changed')
                if 'text/html' in response.headers.get('content-type','').lower() and Path(path).suffix.lower() not in {'.html','.htm'}:
                    raise RemoteStorageError('unexpected_login_page')
                with destination.open('xb') as output:
                    created=True
                    for chunk in response.iter_bytes():
                        self.guard();total+=len(chunk)
                        if total>meta['size'] or (max_bytes is not None and total>max_bytes):raise RemoteStorageError('invalid_content_length')
                        digest.update(chunk);output.write(chunk)
                    output.flush();os.fsync(output.fileno())
            if total!=meta['size']:raise RemoteStorageError('incomplete_download')
            after=self.stat(path)
            if (after['size'],after['etag'],after['mtime'])!=(meta['size'],meta['etag'],meta['mtime']):raise RemoteStorageError('remote_version_changed')
            return {**meta,'sha256':digest.hexdigest()}
        except httpx.HTTPError:
            if created:destination.unlink(missing_ok=True)
            self._failed('connection_unavailable','unreachable')
        except Exception:
            if created:destination.unlink(missing_ok=True)
            raise

    def upload(self,path,local_path,*,expected_sha256):
        path=remote_path(path,allow_empty=False)
        status,_,_=self._request('HEAD',path,allowed=(404,),limit=0)
        source=Path(local_path)
        try:
            descriptor=os.open(source,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
            with os.fdopen(descriptor,'rb') as stream:
                info=os.fstat(stream.fileno());size=info.st_size
                import stat
                if not stat.S_ISREG(info.st_mode):raise ValueError('Upload source must be a regular file')
                def chunks():
                    remaining=size
                    while remaining:
                        self.guard();chunk=stream.read(min(1024*1024,remaining))
                        if not chunk:raise RemoteStorageError('upload_source_changed')
                        remaining-=len(chunk);yield chunk
                self._request('PUT',path,headers={'If-None-Match':'*','Content-Type':'application/octet-stream','Content-Length':str(size)},content=chunks(),allowed=(201,204),limit=65536)
        except httpx.HTTPError:self._failed('connection_unavailable','unreachable')
        # Read back and hash in memory-sized chunks; a multi-GB upload must not
        # require a second multi-GB verification copy on the local disk.
        return self.checksum(path,expected_size=size,expected_sha256=expected_sha256)

    def checksum(self,path,*,expected_size=None,expected_sha256=''):
        meta=self.stat(path)
        if expected_size is not None and meta['size']!=expected_size:raise RemoteStorageError('remote_version_changed')
        headers={'If-Match':meta['etag']} if meta['etag'] else {}
        digest=hashlib.sha256();total=0
        try:
            with self._client() as client,client.stream('GET',self.url(path),headers=headers) as response:
                self._status(response)
                if response.headers.get('content-length')!=str(meta['size']):raise RemoteStorageError('invalid_content_length')
                if 'text/html' in response.headers.get('content-type','').lower() and Path(path).suffix.lower() not in {'.html','.htm'}:
                    raise RemoteStorageError('unexpected_login_page')
                if meta['etag'] and response.headers.get('etag',meta['etag'])!=meta['etag']:raise RemoteStorageError('remote_version_changed')
                for chunk in response.iter_bytes():
                    self.guard();total+=len(chunk)
                    if total>meta['size']:raise RemoteStorageError('invalid_content_length')
                    digest.update(chunk)
            if total!=meta['size']:raise RemoteStorageError('incomplete_download')
            after=self.stat(path)
            if (after['size'],after['etag'],after['mtime'])!=(meta['size'],meta['etag'],meta['mtime']):raise RemoteStorageError('remote_version_changed')
            actual=digest.hexdigest()
            if expected_sha256 and actual!=expected_sha256:raise RemoteStorageError('upload_readback_mismatch')
            return {**meta,'sha256':actual}
        except httpx.HTTPError:self._failed('connection_unavailable','unreachable')
