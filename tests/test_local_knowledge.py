from __future__ import annotations
import json, tempfile, unittest
from pathlib import Path
from starlette.testclient import TestClient
from vault_rag.local_state import LocalConfig,Files,ConflictError
from vault_rag.catalog import Catalog,render_template
from vault_rag.knowledge import Runtime
from vault_rag.web_server import create_app

class FakeModel:
    ready=True;fingerprint='test-model';model_id='test'
    def encode(self,texts):return [[1.0]+[0.0]*1023 for _ in texts]
    def status(self):return {'prepared':True,'loaded':True}

class LocalKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name);self.root=self.home/'vault';self.root.mkdir();(self.root/'RAG/Notes').mkdir(parents=True);(self.root/'RAG/Navigation').mkdir();(self.root/'RAG/Rules').mkdir();(self.root/'RAG/EstimationDB').mkdir();(self.root/'Outside').mkdir()
        self.config=LocalConfig(self.home/'state');self.config.save({'root':str(self.root)})
        self.runtime=Runtime(self.config);self.runtime.model=FakeModel();self.runtime.knowledge.model=self.runtime.model;self.files=self.runtime.files
    def tearDown(self):self.temp.cleanup()
    def put(self,path,text):p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p
    def populate(self):
        self.put('RAG/Notes/a.md','---\nid: a\nname: 能量流接口\nverified_status: limited\n---\n# 能量流接口\n信号调试')
        self.put('RAG/Notes/out.md','---\nrag_index: false\n---\n# 已退出\n信号调试')
        self.put('RAG/Rules/rule.md','---\nrule_id: dcc/test\ndomain: dcc\n---\n# Blender 规则\n模型尺度')
        self.put('RAG/EstimationDB/est.md','---\ntype: estimation\ndomain: estimation\n---\n# 能量流工时\n2 + (车型数-1)*0.5')
        self.put('Outside/secret.md','# 目录外内容\n信号调试')
        self.put('RAG/Navigation/topic.md','# 能量流主题\n[[a]] [[out]] [[Outside/secret]]')
        self.runtime.catalog.scan();self.runtime.knowledge.build()
    def test_scope_lexical_wiki_and_immediate_withdrawal(self):
        self.populate();k=self.runtime.knowledge
        self.put('RAG/_archive/old.md','# 信号调试 旧归档');self.assertFalse(self.config.eligible('RAG/_archive/old.md'))
        result=k.search('信号调试',mode='keyword');self.assertEqual([r['file_path'] for r in result['results']],['RAG/Notes/a.md'])
        self.assertEqual(k.search('能量流',mode='wiki')['results'][0]['file_path'],'RAG/Notes/a.md')
        self.assertEqual(k.search('工时',domain='estimation',mode='keyword')['results'][0]['file_path'],'RAG/EstimationDB/est.md')
        self.assertFalse(k.search('工时',mode='keyword')['results'])
        self.config.save({'exclude_roots':['RAG/Notes']});self.assertFalse(k.search('信号调试',mode='keyword')['results']);self.assertFalse(k.get_chunk(result['results'][0]['chunk_id'])['ok'])
        self.config.save({'include_roots':[],'exclude_roots':[]});self.assertFalse(k.search('能量流',mode='wiki')['results'])
    def test_crlf_unknown_frontmatter_conflict_and_history(self):
        p=self.root/'RAG/Notes/a.md';p.write_bytes(b'---\r\nid: a\r\n# keep comment\r\nunknown: "original"\r\n---\r\nbody\r\n')
        read=self.files.read('RAG/Notes/a.md');saved=self.files.properties('RAG/Notes/a.md',{'status':'done'},read['etag'])
        self.assertIn(b'# keep comment',p.read_bytes());self.assertIn(b'unknown: "original"',p.read_bytes());self.assertTrue(p.read_bytes().endswith(b'body\r\n'))
        with self.assertRaises(ConflictError):self.files.save('RAG/Notes/a.md','overwrite',read['etag'])
        records=self.files.records('history','RAG/Notes/a.md');self.assertEqual(len(records),1);self.files.restore('history',records[0]['id']);self.assertEqual(self.files.read('RAG/Notes/a.md')['etag'],read['etag'])
    def test_move_renames_references_preserves_code_and_restores(self):
        self.put('RAG/Notes/a.md','# A\n[[b]]\n[image](../pic.png)\n');self.put('RAG/Notes/b.md','# B\n[[a|Alias]]\n```text\n[[a]]\n```\n');self.put('RAG/pic.png','image')
        result=self.files.move('RAG/Notes/a.md','RAG/renamed.md');text=(self.root/'RAG/Notes/b.md').read_text();self.assertIn('[[RAG/renamed|Alias]]',text);self.assertIn('```text\n[[a]]',text);self.assertIn('[image](pic.png)',(self.root/'RAG/renamed.md').read_text())
        self.files.restore('operations',result['operation_id']);self.assertTrue((self.root/'RAG/Notes/a.md').is_file());self.assertIn('[[a|Alias]]',(self.root/'RAG/Notes/b.md').read_text())
        deleted=self.files.delete('RAG/Notes/a.md');self.assertFalse((self.root/'RAG/Notes/a.md').exists());self.files.restore('trash',deleted['id']);self.assertTrue((self.root/'RAG/Notes/a.md').exists())
    def test_paths_and_symlinks_never_escape(self):
        (self.root/'escape').symlink_to(self.home,target_is_directory=True)
        for path in ['../other','/etc/passwd','escape/file','.vault-rag/status.json']:
            with self.assertRaises(ValueError):self.config.path_for(path,writable=True)
        self.assertNotIn('escape',[r['name'] for r in self.files.tree()])
        self.put('RAG/Notes/a.md','same');read=self.files.read('RAG/Notes/a.md');other=self.home/'other';(other/'RAG/Notes').mkdir(parents=True);(other/'RAG/Notes/a.md').write_text('same');self.config.save({'root':str(other)})
        with self.assertRaises(ConflictError):self.files.save('RAG/Notes/a.md','old draft',read['etag'],expected_root=read['root'])
        self.assertEqual((other/'RAG/Notes/a.md').read_text(),'same')
    def test_existing_query_and_safe_base_template(self):
        self.put('RAG/Notes/a.md','---\ncategory: Pitfall\nseverity: high\nverified_status: limited\ntags: [type/pitfall, task]\nstatus: open\nproject: Test\n---\n# A\n')
        self.runtime.catalog.scan();d=self.runtime.catalog.query('TABLE length(rows) AS 数量\nFROM "RAG/Notes"\nGROUP BY category\nSORT 数量 DESC');self.assertEqual(d['rows'][0]['values']['数量'],1)
        self.put('view.base','filters:\n  and:\n    - file.hasTag("task")\n    - project == "Test"\nviews:\n  - type: tasknotesKanban\n    name: Tasks\n');self.assertEqual(len(self.runtime.catalog.base('view.base')['views'][0]['rows']),1)
        rendered=render_template('<% tp.date.now("YYYY-MM-DD") %> <% tp.file.cursor %>');self.assertNotIn('<%',rendered['text'])
        with self.assertRaises(ValueError):self.runtime.catalog.query('LIST\nWHERE eval("danger")')
    def test_atomic_failure_keeps_snapshot_and_caches_embeddings(self):
        self.populate();k=self.runtime.knowledge;previous=k.snapshot['status']['generation'];self.put('RAG/Notes/new.md','# Different\nNew text')
        self.runtime.catalog.scan();self.runtime.model.encode=lambda _:(_ for _ in ()).throw(RuntimeError('model failed'));k.build()
        self.assertEqual(k.snapshot['status']['generation'],previous);self.assertEqual(json.loads((self.root/'.vault-rag/current.json').read_text())['generation'],previous)
    def test_model_unavailable_current_keywords_and_revision_checks(self):
        self.populate();k=self.runtime.knowledge
        self.put('RAG/Navigation/sources.md','---\nsources: [a]\n---\n# 能量流导航');self.runtime.catalog.scan();k.build()
        original=k.search('信号调试',mode='keyword')['results'][0]
        self.runtime.model.ready=False
        self.put('RAG/Notes/a.md','# 当前正文\n新证据闪烁栅格')
        self.put('RAG/Notes/new.md','# 新笔记\n新证据闪烁栅格')
        self.runtime.catalog.scan();k.build()
        found=k.search('闪烁栅格',mode='hybrid',top_k=5)
        self.assertEqual({r['file_path'] for r in found['results']},{'RAG/Notes/a.md','RAG/Notes/new.md'})
        self.assertTrue(found['degraded']);self.assertTrue(all(r['index_pending'] for r in found['results']))
        self.assertFalse(k.get_chunk(original['chunk_id'])['ok'])
        wiki=k.search('能量流',mode='wiki');source=next(v for v in wiki['navigation'] if v['file_path']=='RAG/Navigation/sources.md');self.assertTrue(source['stale']);self.assertEqual(source['excerpt'],'')
        for row in found['results']:self.assertIn('闪烁栅格',k.get_chunk(row['chunk_id'])['text'])
        self.assertEqual(k.search('闪烁栅格',mode='keyword',compact=False)['results'][0]['ranking'],'backfill')
        k.snapshot={'nodes':[],'docs':[]}
        self.assertTrue(k.search('闪烁栅格',mode='keyword')['results'])

    def test_html_preview_snapshot_resources_and_api_isolation(self):
        from urllib.parse import urljoin
        original='<!doctype html><meta charset="utf-8"><h1>磁盘版本</h1>'
        path='网页 示例/index.html';p=self.put(path,original)
        self.put('网页 示例/样式.css','h1 { color: red }')
        self.put('网页 示例/app.js','document.querySelector("h1").textContent="已运行"')
        self.put('网页 示例/文章.md','# 正文')
        self.put('网页 示例/next.htm','<!doctype html><h1>下一页</h1>')
        self.put('common.json','{"value":1}')
        app=create_app(self.config,self.runtime,start_background=False)
        token=(self.config.directory/'auth-token').read_text()
        with TestClient(app,base_url='http://127.0.0.1:18080') as client:
            payload={'path':path,'root':str(self.config.root),'text':'<!doctype html><h1>草稿版本</h1>'}
            self.assertEqual(client.post('/api/html-preview',json=payload).status_code,401)
            client.cookies.set('vault_session',token)
            self.assertEqual(client.post('/api/html-preview',json=payload).status_code,403)
            headers={'x-vault-csrf':app.state.csrf}
            response=client.post('/api/html-preview',json=payload,headers=headers)
            self.assertEqual(response.status_code,200);url=response.json()['url']
            self.assertIn('%E7',url);self.assertIn('%20',url)
            client.cookies.clear()
            response=client.get(url,headers={'origin':'null'})
            self.assertEqual(response.status_code,200);self.assertIn('草稿版本',response.text)
            self.assertEqual(p.read_text(),original)
            policy=response.headers['content-security-policy']
            self.assertIn('sandbox allow-scripts',policy);self.assertNotIn('allow-same-origin',policy)
            self.assertNotIn("script-src 'self'",policy);self.assertIn('/files/',policy)
            self.assertEqual(response.headers['cache-control'],'no-store')
            for resource in ('样式.css','app.js','next.htm','../common.json'):
                r=client.get(urljoin(url,resource),headers={'origin':'null'})
                self.assertEqual(r.status_code,200,resource)
                self.assertEqual(r.headers['access-control-allow-origin'],'null')
            r=client.get(urljoin(url,'文章.md'));self.assertIn('attachment',r.headers['content-disposition'])
            self.assertEqual(client.head(url).status_code,200)
            self.assertEqual(client.post(url,headers={'origin':'null'}).status_code,403)
            self.assertEqual(client.get(url,headers={'origin':'https://evil.example'}).status_code,403)
            self.assertEqual(client.get(url,headers={'host':'evil.example'}).status_code,403)
            client.cookies.set('vault_session',token)
            self.assertEqual(client.get('/api/bootstrap',headers={'origin':'null'}).status_code,403)
            self.assertEqual(client.post('/api/create',json={'path':'attack.md'},headers={'origin':'null',**headers}).status_code,403)
            self.assertFalse((self.root/'attack.md').exists())
            self.assertEqual(client.get('/api/media',params={'path':path}).headers['content-security-policy'].split(';')[0],'sandbox')
            self.assertEqual(client.get('/api/media',params={'path':'网页 示例/next.htm'}).headers['content-security-policy'].split(';')[0],'sandbox')
            prefix=url.split('/files/')[0]+'/files/'
            (self.root/'escape').symlink_to(self.home,target_is_directory=True)
            for forbidden in ('.vault-rag/status.json','escape/file','%2e%2e/other','%2Fetc/passwd'):
                self.assertEqual(client.get(prefix+forbidden,headers={'origin':'null'}).status_code,400,forbidden)
            self.assertEqual(client.get('/html-preview/unknown/files/index.html').status_code,410)
            self.assertEqual(client.post('/api/html-preview',json={},headers=headers).status_code,400)
            self.assertEqual(client.post('/api/html-preview',json={**payload,'root':'/other'},headers=headers).status_code,409)
            # Restarted processes cannot recover in-memory preview credentials.
            restarted=create_app(self.config,self.runtime,start_background=False)
            with TestClient(restarted,base_url='http://127.0.0.1:18080') as fresh:
                self.assertEqual(fresh.get(url).status_code,410)
            other=self.home/'other';other.mkdir();self.config.save({'root':str(other)})
            expired=client.get(url);self.assertEqual(expired.status_code,410)
            self.assertIn('vault-html-preview-expired',expired.text)
            self.config.save({'root':str(self.root)})
            self.assertEqual(client.get(url).status_code,410)

    def test_http_browser_session_csrf_host_origin_and_ranges(self):
        self.populate();app=create_app(self.config,self.runtime,start_background=False)
        token=(self.config.directory/'auth-token').read_text();headers={'host':'127.0.0.1:18080','authorization':'Bearer '+token}
        self.put('test.mp4','0123456789')
        with TestClient(app,headers=headers) as client:
            self.assertEqual(client.get('/api/status').status_code,200)
            self.assertEqual(client.get('/api/status',headers={'origin':'https://evil.example'}).status_code,403)
            self.assertEqual(client.get('/api/status',headers={'host':'evil.example'}).status_code,403)
            r=client.get('/api/media?path=test.mp4',headers={'range':'bytes=2-5'});self.assertEqual(r.status_code,206);self.assertEqual(r.content,b'2345')
            client.headers.pop('authorization');client.cookies.set('vault_session',token)
            self.assertEqual(client.post('/api/create',json={'path':'blocked.md'}).status_code,403)
            csrf=client.get('/api/bootstrap').json()['csrf'];self.assertEqual(client.post('/api/create',json={'path':'created.md'},headers={'x-vault-csrf':csrf}).status_code,200)
            r=client.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'test','version':'1'}}},headers={'authorization':'Bearer '+token,'accept':'application/json, text/event-stream'});self.assertEqual(r.status_code,200)

if __name__=='__main__':unittest.main()
