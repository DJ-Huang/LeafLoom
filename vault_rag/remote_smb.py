"""SMB2/3 transport with explicit credentials and operation-scoped connections."""
from contextlib import contextmanager
import hashlib
import mimetypes
import os
from pathlib import Path
import stat
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from vault_rag.remote_webdav import RemoteStorageError, WebDAVSource, remote_path


def validate_smb_source(source):
    # Reuse the common bounds, IDs and writable-directory validation without
    # changing the normalization of any existing WebDAV source.
    from vault_rag.remote_webdav import validate_source
    value = dict(source)
    address = value.get('base_url', '')
    if isinstance(address, str) and address.startswith('\\\\'):
        address = 'smb://' + address[2:].replace('\\', '/')
    try:
        if not isinstance(address,str) or any(ord(c)<32 for c in address):raise ValueError
        url = urlsplit(address)
        parts = unquote(url.path).strip('/').split('/')
        if (url.scheme != 'smb' or not url.hostname or not parts[0] or
                url.username is not None or url.password is not None or url.query or url.fragment or
                (url.port is not None and not 1 <= url.port <= 65535)):
            raise ValueError
        for part in parts:
            if not part or part.startswith('.') or any(c in part for c in '\\:*?"<>|') or any(ord(c)<32 for c in part):raise ValueError
        tail = '/'.join(parts[1:])
        existing = value.get('remote_root', '').strip('/')
        root = '/'.join(p for p in (tail, existing) if p)
        fake = {**value, 'type':'webdav', 'base_url':'https://smb.invalid/', 'remote_root':root, 'connection_hint':'direct'}
        result = validate_source(fake)
        result.update(type='smb', base_url=urlunsplit(('smb', url.netloc, '/' + quote(parts[0], safe='') + '/', '', '')))
        return result
    except (TypeError, AttributeError, ValueError):
        raise ValueError('Use smb://host/share with an optional subdirectory') from None


class SMBSource(WebDAVSource):
    """Reuse bounded discovery/ignore rules; all byte operations stay SMB native."""
    def __init__(self, source, credentials=None, *, transport=None, guard=None, on_error=None):
        self.source = validate_smb_source(source)
        self.credentials = credentials
        self.guard = guard or (lambda: None)
        self.on_error = on_error
        self.pool = {}
        self.depth = 0
        self.client = transport  # Optional filesystem-shaped test peer.
        self.transport = transport

    @contextmanager
    def session(self):
        if self.client is None:
            import smbclient
            self.client = smbclient
        self.depth += 1
        try:
            self.guard()
            if not self.credentials or not self.source['username']:self._failed('credentials_required','auth_required')
            yield self
        except Exception as error:
            from smbprotocol.exceptions import SMBAuthenticationError, SMBResponseException, SMBLinkRedirectionError
            if isinstance(error, SMBLinkRedirectionError):raise RemoteStorageError('out_of_scope_href') from None
            code = getattr(error, 'winerror', None)
            status = getattr(error, 'status', None)
            if isinstance(error, FileNotFoundError) or code in (2, 3) or status in (0xC0000034,0xC000003A):raise RemoteStorageError('remote_not_found') from None
            if isinstance(error, FileExistsError) or code == 183 or status == 0xC0000035:raise RemoteStorageError('immutable_object_conflict') from None
            if isinstance(error, (PermissionError, SMBAuthenticationError)) or code in (5,86,1326) or status in (0xC0000022,0xC000006D):self._failed('authentication_required','auth_required')
            if isinstance(error, (OSError, SMBResponseException)):self._failed('connection_unavailable','unreachable')
            raise
        finally:
            self.depth -= 1
            if not self.depth:self.client.reset_connection_cache(connection_cache=self.pool, fail_on_error=False)

    def _options(self):
        url = urlsplit(self.source['base_url'])
        return dict(username=self.source['username'], password=self.credentials[1] if self.credentials else None,
                    port=url.port or 445, auth_protocol='ntlm', connection_timeout=8, connection_cache=self.pool)

    def _path(self, path):
        path = remote_path(path)
        self.guard()
        root = self.source['remote_root']
        parts = [p for p in (root + '/' + path).split('/') if p]
        if any(any(c in p for c in ':*?"<>|') or p.endswith((' ', '.')) for p in parts):raise ValueError('Invalid SMB attachment path')
        url = urlsplit(self.source['base_url'])
        return '\\\\' + url.hostname + '\\' + unquote(url.path).strip('/') + ('\\' + '\\'.join(parts) if parts else '')

    def _check_path(self, path):
        # Do not follow server symlinks, junctions or DFS reparse points, including
        # ancestors. Each operation is confined to this explicitly configured tree.
        from smbprotocol.tree import TreeConnect
        server=urlsplit(self.source['base_url']).hostname
        session=self.client.register_session(server,**self._options())
        share='\\\\'+server+'\\'+unquote(urlsplit(self.source['base_url']).path).strip('/')
        tree=next((t for t in session.tree_connect_table.values() if t.share_name==share),None)
        if tree is None:
            tree=TreeConnect(session,share);tree.connect()
        if tree.is_dfs_share:raise RemoteStorageError('out_of_scope_href')
        parts = self._path(path).split('\\')
        for depth in range(4, len(parts)+1):
            info = self.client.stat('\\'.join(parts[:depth]), follow_symlinks=False, **self._options())
            if getattr(info, 'st_file_attributes', 0) & 0x400:raise RemoteStorageError('out_of_scope_href')
        if any(getattr(tree, 'is_dfs_share', False) for tree in getattr(session, 'tree_connect_table', {}).values()):
            raise RemoteStorageError('out_of_scope_href')

    @staticmethod
    def _meta(path, info):
        version = f'{info.st_ino}:{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}'
        return dict(path=path, name=path.rsplit('/',1)[-1], size=info.st_size,
                    mtime=str(info.st_mtime_ns), etag=hashlib.sha256(version.encode()).hexdigest(),
                    mime=mimetypes.guess_type(path)[0] or 'application/octet-stream',
                    is_dir=stat.S_ISDIR(info.st_mode), metadata_origin='head')

    def stat(self, path):
        with self.session():
            self._check_path(path)
            return self._meta(path, self.client.stat(self._path(path), follow_symlinks=False, **self._options()))

    def scan(self, *args, **kwargs):
        # One explicitly scoped connection pool for the bounded directory walk.
        with self.session():return super().scan(*args, **kwargs)

    def _propfind(self, path, **_):
        with self.session():
            self._check_path(path)
            entries = [self.stat(path)]
            with self.client.scandir(self._path(path), **self._options()) as listing:
                for entry in listing:
                    self.guard()
                    if entry.name.startswith('.'):continue
                    rel = '/'.join(p for p in (path, entry.name) if p)
                    remote_path(rel)
                    info = entry.stat(follow_symlinks=False)
                    if getattr(info, 'st_file_attributes', 0) & 0x400:continue
                    entries.append(self._meta(rel, info))
                    if len(entries)>100001:raise RemoteStorageError('directory_count_limit')
            return entries

    def _open(self, path, mode):
        self.guard()
        parent = path.rsplit('/',1)[0] if '/' in path else ''
        self._check_path(parent if mode=='xb' else path)
        return self.client.open_file(self._path(path), mode=mode, share_access='r', create_options=0x00200000, **self._options())

    def read_bytes(self, path, *, max_bytes=256*1024):
        with self.session(), self._open(path, 'rb') as stream:
            data = stream.read(max_bytes+1)
            if len(data)>max_bytes:raise RemoteStorageError('response_too_large')
            return data

    def _ignore_bytes(self, path, *, expected_etag=''):
        from vault_rag.remote_ignore import MAX_IGNORE_BYTES
        data, _ = self.read_range(path, max_bytes=MAX_IGNORE_BYTES, expected_etag=expected_etag)
        return data

    def read_range(self, path, start=0, end=None, *, max_bytes=8*1024*1024, expected_etag=None, expected_size=None):
        with self.session():
            meta = self.stat(path)
            if expected_etag and meta['etag']!=expected_etag or expected_size is not None and meta['size']!=expected_size:raise RemoteStorageError('remote_version_changed')
            if type(start)is not int or start<0 or end is not None and (type(end)is not int or end<start):raise ValueError('Invalid attachment byte range')
            if start>=meta['size'] and (start or meta['size']):raise ValueError('Range is outside the attachment')
            length = max(0, min(meta['size']-1, end if end is not None else meta['size']-1)-start+1)
            if length>max_bytes:raise ValueError('Attachment byte range is too large')
            with self._open(path,'rb') as stream:
                stream.seek(start);data=stream.read(length)
            self.guard()
            if len(data)!=length or self.stat(path)['etag']!=meta['etag']:raise RemoteStorageError('remote_version_changed')
            return data,meta

    def _copy(self, path, output=None, *, expected_size=None, expected_etag=None, max_bytes=None):
        with self.session():
            meta=self.stat(path)
            if expected_size is not None and meta['size']!=expected_size or expected_etag and meta['etag']!=expected_etag:raise RemoteStorageError('remote_version_changed')
            if max_bytes is not None and meta['size']>max_bytes:raise RemoteStorageError('cache_object_too_large')
            digest=hashlib.sha256();total=0
            with self._open(path,'rb') as stream:
                while True:
                    self.guard();chunk=stream.read(min(1024*1024,meta['size']-total+1))
                    if not chunk:break
                    total+=len(chunk)
                    if total>meta['size']:raise RemoteStorageError('remote_version_changed')
                    digest.update(chunk)
                    if output is not None:output.write(chunk)
            if total!=meta['size'] or self.stat(path)['etag']!=meta['etag']:raise RemoteStorageError('remote_version_changed')
            return {**meta,'sha256':digest.hexdigest()}

    def download(self, path, destination, **options):
        target=Path(destination);created=False
        try:
            with target.open('xb') as output:
                created=True;result=self._copy(path,output,**options);output.flush();os.fsync(output.fileno())
            return result
        except BaseException:
            if created:target.unlink(missing_ok=True)
            raise

    def checksum(self, path, *, expected_size=None, expected_sha256=''):
        result=self._copy(path,expected_size=expected_size)
        if expected_sha256 and result['sha256']!=expected_sha256:raise RemoteStorageError('checksum_mismatch')
        return result

    def ensure_directory(self, path, *, verified=None):
        path=remote_path(path,allow_empty=False);writable=self.source['upload_directory']
        if writable and not (path==writable or path.startswith(writable+'/')):raise ValueError('Directory is outside the writable attachment area')
        with self.session():
            parts=path.split('/')
            for depth in range(1,len(parts)+1):
                current='/'.join(parts[:depth])
                if verified is not None and current in verified:continue
                self._check_path('/'.join(parts[:depth-1]))
                try:self.client.mkdir(self._path(current),**self._options())
                except FileExistsError:pass
                if not self.stat(current)['is_dir']:raise RemoteStorageError('metadata_directory_unavailable')
                if verified is not None:verified.add(current)

    def put_immutable(self, path, data, *, max_bytes=2*1024*1024, verified_directories=None):
        if not isinstance(data,bytes) or len(data)>max_bytes:raise ValueError('Metadata object is too large')
        if verified_directories is not None:self.ensure_directory(path.rsplit('/',1)[0],verified=verified_directories)
        writable=self.source['upload_directory']
        if writable and not path.startswith(writable+'/'):raise ValueError('File is outside the writable attachment area')
        with self.session():
            try:
                with self._open(path,'xb') as output:output.write(data)
            except FileExistsError:pass
            actual=self.read_bytes(path,max_bytes=max_bytes)
            if actual!=data:raise RemoteStorageError('immutable_object_conflict')
            return hashlib.sha256(actual).hexdigest()

    def upload(self, path, local_path, *, expected_sha256):
        writable=self.source['upload_directory']
        if writable and not path.startswith(writable+'/'):raise ValueError('File is outside the writable attachment area')
        descriptor=os.open(local_path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
        with os.fdopen(descriptor,'rb') as source, self.session():
            info=os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):raise ValueError('Upload source must be a regular file')
            with self._open(path,'xb') as output:
                while True:
                    self.guard();chunk=source.read(1024*1024)
                    if not chunk:break
                    output.write(chunk)
            return self.checksum(path,expected_size=info.st_size,expected_sha256=expected_sha256)
