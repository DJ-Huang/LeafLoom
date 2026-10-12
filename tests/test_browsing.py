"""Incremental browsing contracts; all writes use temporary vaults."""
import json
import asyncio
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from starlette.testclient import TestClient
from vault_rag.local_state import LocalConfig
from vault_rag.knowledge import Runtime
from vault_rag.events import Changes
from vault_rag.embedded_model import EmbeddedModel
from vault_rag.web_server import create_app


class BrowsingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.root = self.home / 'vault'; self.root.mkdir()
        self.config = LocalConfig(self.home / 'state'); self.config.save({'root': str(self.root),'include_roots':['']})
        self.runtime = Runtime(self.config)

    def tearDown(self):
        self.runtime.stop(); self.temp.cleanup()

    def put(self,path,text):
        file=self.root/path; file.parent.mkdir(parents=True,exist_ok=True); file.write_text(text,encoding='utf-8'); return file

    def wait_for(self,condition):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if condition():return
            time.sleep(.02)
        self.assertTrue(condition())

    def test_incremental_assets_references_and_sqlite(self):
        self.put('a.md','---\nid: stable-id\naliases: [Alias]\n---\n# A')
        self.put('source.md','[[stable-id]] [[Alias]] ![[image.png]]')
        self.put('image.png','binary'); self.put('code.js','[[Alias]]')
        catalog=self.runtime.catalog; catalog.scan()
        self.assertEqual(len(catalog.links),3)
        self.assertEqual(catalog.entries['code.js']['text'],'')
        before=catalog.entries['source.md']; db=sqlite3.connect(self.root/'.vault-rag/catalog.sqlite')
        rowid=db.execute("SELECT rowid FROM files WHERE path='source.md'").fetchone()
        self.put('image.png','changed')
        with patch.object(self.runtime.files,'walk',side_effect=AssertionError('full scan')),patch.object(Path,'read_bytes',side_effect=AssertionError('asset read')):
            catalog.apply(['image.png'])
        self.assertIs(catalog.entries['source.md'],before)
        self.assertEqual(db.execute("SELECT rowid FROM files WHERE path='source.md'").fetchone(),rowid); db.close()
        self.assertFalse(self.runtime._needs_index(['image.png','code.js']))
        self.put('generated.md','---\nmanaged_by: vault-rag\n---\n# Generated');catalog.apply(['generated.md'])
        self.assertFalse(self.runtime._needs_index(['generated.md']))
        self.put('a.md','---\nid: new-id\n---\n# A'); catalog.apply(['a.md'])
        self.assertEqual(catalog.links,[{'source':'source.md','target':'image.png'}])
        (self.root/'image.png').unlink(); catalog.apply(['image.png']); self.assertEqual(catalog.links,[])
        self.put('new/target.md','# New');catalog.apply(['new'])
        (self.root/'new').rename(self.root/'renamed');catalog.apply(['new','renamed'])
        self.assertNotIn('new/target.md',catalog.entries);self.assertIn('renamed/target.md',catalog.entries)
        with patch.object(Path,'iterdir',side_effect=AssertionError('directory scanned')):
            self.assertEqual(catalog.tree('renamed')[0]['name'],'target.md')
        (self.root/'empty').mkdir();catalog.apply(['empty']);self.assertIn('empty',[row['name'] for row in catalog.tree()])

    def test_watch_publishes_during_blocked_index_and_switches_root(self):
        self.put('a.md','# A');entered=threading.Event();release=threading.Event()
        def blocked():entered.set();release.wait(5)
        self.runtime.knowledge.load=lambda:None;self.runtime.knowledge.build=blocked
        self.runtime.start()
        try:
            self.wait_for(lambda:entered.is_set() and self.runtime.watching)
            time.sleep(.2); start=time.monotonic();self.put('a.md','# External')
            self.wait_for(lambda:self.runtime.catalog.entries.get('a.md',{}).get('text')=='# External')
            self.assertLess(time.monotonic()-start,2)
            messages=self.runtime.events.wait(0,0);self.assertTrue(any(m['type']=='files' for m in messages))
            old_stop=self.runtime.watcher_stop; other=self.home/'other';other.mkdir();(other/'b.md').write_text('# B')
            self.config.save({'root':str(other)});self.runtime.configuration_changed()
            self.wait_for(lambda:self.runtime.catalog.root==str(other))
            self.assertTrue(old_stop.is_set());self.assertNotIn('a.md',self.runtime.catalog.entries)
            self.put('a.md','# Stale root');time.sleep(.3);self.assertNotIn('a.md',self.runtime.catalog.entries)
        finally:release.set()

    def test_session_conditional_reads_range_and_preview_expiry(self):
        self.put('a.md','# A');self.put('site/index.html','<script>fetch("/api/file")</script>');self.put('site/style.css','body{}')
        (self.root/'clip.mp4').write_bytes(bytes(range(256)))
        static=self.home/'static';(static/'assets').mkdir(parents=True);(static/'index.html').write_text('<h1>Test</h1>')
        (static/'assets/test-123.js').write_text('const text="'+('bundle'*2000)+'";')
        self.runtime.catalog.scan();app=create_app(self.config,self.runtime,start_background=False,static_dir=static)
        with TestClient(app,base_url='http://127.0.0.1:18080') as client:
            client.get('/');session=client.get('/api/session');self.assertEqual(session.status_code,200)
            asset=client.get('/assets/test-123.js',headers={'Accept-Encoding':'gzip'})
            self.assertEqual(asset.headers['content-encoding'],'gzip');self.assertIn('immutable',asset.headers['cache-control'])
            self.assertEqual(session.headers['cache-control'],'no-store')
            self.assertIn('service_instance_id',session.json());headers={'X-Vault-CSRF':session.json()['csrf']}
            note=client.get('/api/file?path=a.md');self.assertEqual(client.get('/api/file?path=a.md',headers={'If-None-Match':note.headers['etag']}).status_code,304)
            media=client.get('/api/media?path=clip.mp4');self.assertEqual(client.get('/api/media?path=clip.mp4',headers={'If-None-Match':media.headers['etag']}).status_code,304)
            ranged=client.get('/api/media?path=clip.mp4',headers={'Range':'bytes=4-9','If-None-Match':media.headers['etag']})
            self.assertEqual(ranged.status_code,206);self.assertEqual(ranged.content,bytes(range(4,10)))
            preview=client.post('/api/html-preview',json={'path':'site/index.html','root':str(self.root),'text':'<h1>Preview</h1>'},headers=headers).json()['url']
            entry=client.get(preview);self.assertEqual(entry.headers['cache-control'],'no-store');self.assertIn('sandbox allow-scripts',entry.headers['content-security-policy'])
            resource=preview.replace('index.html','style.css');style=client.get(resource)
            self.assertEqual(client.get(resource,headers={'If-None-Match':style.headers['etag']}).status_code,304)
            self.config.save({'exclude_roots':['site']})
            self.assertEqual(client.get(resource,headers={'If-None-Match':style.headers['etag']}).status_code,410)
            # Identical timestamps and sizes in a new root must not reuse old bytes.
            other=self.home/'other';other.mkdir();(other/'clip.mp4').write_bytes(b'x'*256)
            import os
            stamp=(self.root/'clip.mp4').stat();os.utime(other/'clip.mp4',ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            self.config.save({'root':str(other),'include_roots':[''],'exclude_roots':[]})
            switched=client.get('/api/media?path=clip.mp4',headers={'If-None-Match':media.headers['etag']})
            self.assertEqual(switched.status_code,200);self.assertEqual(switched.content,b'x'*256)
            self.assertEqual(client.get('/api/media?path=../secret',headers={'If-None-Match':'*'}).status_code,400)

    def test_status_avoids_disk_and_event_gaps_reset(self):
        model=EmbeddedModel(self.home/'model-state')
        with patch.object(Path,'stat',side_effect=AssertionError('status touched disk')):
            self.assertFalse(model.status()['prepared'])
            self.assertEqual(self.runtime.status()['watch']['state'],'定期检查')
        changes=Changes()
        for _ in range(70):changes.publish('files',paths=['a.md'])
        self.assertEqual(changes.wait(0,0)[0]['type'],'reset')
        self.assertEqual(len(changes.wait(69,0)),1);changes.close();self.assertEqual(changes.wait(70,0),[])

    def test_sse_waits_do_not_consume_io_threads(self):
        changes=Changes()
        async def verify():
            from contextlib import AsyncExitStack
            async with AsyncExitStack() as stack:
                listeners=[await stack.enter_async_context(changes.listen()) for _ in range(40)]
                self.assertEqual(await asyncio.wait_for(asyncio.to_thread(lambda:42),1),42)
                changes.publish('files',paths=['a.md'])
                for queue,_ in listeners:self.assertEqual((await asyncio.wait_for(queue.get(),1))['paths'],['a.md'])
            self.assertEqual(changes.listeners,{})
        asyncio.run(verify())


if __name__=='__main__':unittest.main()
