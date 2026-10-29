"""Exercise the SMB transport against an isolated filesystem-shaped peer."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from vault_rag.remote_smb import SMBSource
from vault_rag.remote_webdav import RemoteStorageError, validate_source

class Peer:
    def __init__(self,root):self.root=root;self.calls=[];self.reparse=set();self.closed=[]
    def path(self,path):
        parts=path.split('\\')[4:]
        target=self.root.joinpath(*parts)
        if not target.is_relative_to(self.root):raise AssertionError('escaped share')
        return target
    def record(self,kw):self.calls.append(kw);assert kw['auth_protocol']=='ntlm';assert kw['connection_cache'] is not None
    def register_session(self,host,**kw):
        self.record(kw)
        return SimpleNamespace(tree_connect_table={1:SimpleNamespace(share_name=r'\\nas\share',is_dfs_share=False)})
    def stat(self,path,**kw):
        self.record(kw);info=self.path(path).stat()
        return SimpleNamespace(st_ino=info.st_ino,st_size=info.st_size,st_mtime_ns=info.st_mtime_ns,st_ctime_ns=info.st_ctime_ns,st_mode=info.st_mode,st_file_attributes=0x400 if path in self.reparse else 0)
    def open_file(self,path,mode,**kw):self.record(kw);return self.path(path).open(mode)
    def mkdir(self,path,**kw):self.record(kw);self.path(path).mkdir()
    def reset_connection_cache(self,**kw):self.closed.append(kw['connection_cache'])
    @contextmanager
    def scandir(self,path,**kw):
        self.record(kw)
        with os.scandir(self.path(path)) as entries:yield entries

class SMBTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'Incoming').mkdir();(self.root/'Incoming/test.bin').write_bytes(b'abcdef')
        self.peer=Peer(self.root)
        self.config={'id':'a'*32,'type':'smb','base_url':'smb://nas/share/','username':'alice','upload_directory':'Incoming'}
        self.source=SMBSource(self.config,('alice','test-only-password'),transport=self.peer)

    def test_normalization_and_legacy_dav(self):
        config=validate_source({**self.config,'base_url':r'\\nas\share\Folder'})
        self.assertEqual((config['type'],config['base_url'],config['remote_root']),('smb','smb://nas/share/','Folder'))
        dav=validate_source({'id':'a'*32,'base_url':'https://fixture.invalid/dav/','remote_root':'Folder'})
        self.assertEqual((dav['type'],dav['remote_root']),('webdav','Folder'))
        self.assertEqual(validate_source(config),config)

    def test_rejects_escaping_and_credential_urls(self):
        for url in ['smb://nas/','smb://u:p@nas/share','smb://nas/share/../other','smb://nas/share/%2e%2e','smb://nas/share?x=1','smb://nas/share\\other','smb://nas/share\n']:
            with self.subTest(url=url),self.assertRaises(ValueError):validate_source({**self.config,'base_url':url})
        for path in ['../secret','Incoming/file:stream','Incoming/../secret','Incoming/name.']:
            with self.subTest(path=path),self.assertRaises(ValueError):self.source.stat(path)

    def test_range_download_checksum_and_version(self):
        data,meta=self.source.read_range('Incoming/test.bin',1,3)
        self.assertEqual(data,b'bcd')
        target=self.root/'download.bin';result=self.source.download('Incoming/test.bin',target,expected_etag=meta['etag'],max_bytes=10)
        self.assertEqual(target.read_bytes(),b'abcdef');self.assertEqual(result['sha256'],hashlib.sha256(b'abcdef').hexdigest())
        (self.root/'Incoming/test.bin').write_bytes(b'changed')
        with self.assertRaises(RemoteStorageError):self.source.read_range('Incoming/test.bin',expected_etag=meta['etag'])
        self.assertTrue(self.peer.closed)

    def test_scan_ignore_and_metadata_exclusive_write(self):
        (self.root/'Incoming/note.md').write_text('ignored')
        closed=len(self.peer.closed);rows=self.source.scan()
        self.assertEqual(len(self.peer.closed),closed+1)
        self.assertTrue(next(row for row in rows if row['name']=='note.md')['excluded'])
        self.source.ensure_directory('Incoming/Catalog/events')
        self.source.put_immutable('Incoming/Catalog/events/one.json',b'{}')
        self.source.put_immutable('Incoming/Catalog/events/one.json',b'{}')
        with self.assertRaises(RemoteStorageError):self.source.put_immutable('Incoming/Catalog/events/one.json',b'bad')
        self.assertEqual((self.root/'Incoming/Catalog/events/one.json').read_bytes(),b'{}')

    def test_upload_exclusive_and_no_reparse(self):
        local=self.root/'staged.bin';local.write_bytes(b'upload')
        self.source.upload('Incoming/upload.bin',local,expected_sha256=hashlib.sha256(b'upload').hexdigest())
        with self.assertRaises(RemoteStorageError):self.source.upload('Incoming/upload.bin',local,expected_sha256='')
        self.peer.reparse.add(r'\\nas\share\Incoming')
        with self.assertRaises(RemoteStorageError):self.source.read_range('Incoming/test.bin')

    def test_credentials_and_pool_are_not_shared(self):
        other=SMBSource({**self.config,'username':'bob'},('bob','different-password'),transport=self.peer)
        self.source.stat('Incoming/test.bin');other.stat('Incoming/test.bin')
        calls=self.peer.calls
        self.assertTrue(any(c['username']=='alice' and c['password']=='test-only-password' and c['connection_cache'] is self.source.pool for c in calls))
        self.assertTrue(any(c['username']=='bob' and c['password']=='different-password' and c['connection_cache'] is other.pool for c in calls))
        self.assertIsNot(self.source.pool,other.pool)

    def test_incremental_discovery_reuses_directory_receipts(self):
        from vault_rag.remote_discovery import DirectoryCheckpoints
        database=self.root/'checkpoints.sqlite'
        cache=DirectoryCheckpoints(database,'a'*32,'test-context',lambda:None)
        try:
            rows=self.source.scan('Incoming',checkpoint=cache);cache.complete()
            self.assertEqual([row['name'] for row in rows],['test.bin'])
        finally:cache.close()
        scans=len(self.peer.calls)
        cache=DirectoryCheckpoints(database,'a'*32,'test-context',lambda:None)
        try:
            rows=self.source.scan('Incoming',checkpoint=cache)
            self.assertTrue(all(row['_directory_cached'] for row in rows))
            self.assertEqual(len(self.peer.calls),scans)
        finally:cache.close()
