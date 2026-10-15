"""HTTP contracts for isolated websites and lossless browser-origin migration."""
import html
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch

from starlette.testclient import TestClient
from vault_rag.knowledge import Runtime
from vault_rag.local_state import LocalConfig
from vault_rag.web_server import create_app
from vault_rag.local_dns import LocalDns


class LocalDnsTests(unittest.TestCase):
    def test_admin_timeout_retains_a_retryable_diagnostic(self):
        resolver=LocalDns('a'*32,18080)
        with patch('vault_rag.local_dns.sys.platform','darwin'),patch('vault_rag.local_dns.subprocess.run',side_effect=subprocess.TimeoutExpired('osascript',180)):
            with self.assertRaisesRegex(ValueError,'系统授权等待超时'):resolver.configure(True)

    def test_resolver_answers_only_its_own_installation(self):
        resolver=LocalDns('a'*32,18080)
        def query(name,kind=1):
            return struct.pack('!6H',7,0x100,1,0,0,0)+b''.join(bytes([len(label)])+label.encode() for label in name.split('.'))+b'\0'+struct.pack('!2H',kind,1)
        reply=resolver.answer(query('app.'+resolver.zone))
        self.assertEqual(struct.unpack('!6H',reply[:12]),(7,0x8500,1,1,0,0))
        self.assertTrue(reply.endswith(b'\x7f\0\0\x01'))
        self.assertEqual(struct.unpack('!6H',resolver.answer(query('p-'+'b'*32+'.'+resolver.zone,28))[:12])[3],0)
        for name in ['example.com','localhost','app.'+'b'*32+'.localhost',resolver.zone+'.evil.com']:
            self.assertEqual(resolver.answer(query(name))[3]&15,5)
        for packet in [b'',query('app.'+resolver.zone)[:-2],b'\0'*12,struct.pack('!6H',7,0x100,1,0,0,0)+b'\xc0\x0c\0\1\0\1']:
            self.assertIsNone(resolver.answer(packet))
        self.assertIn('nameserver 127.0.0.1\nport 18080\n',resolver.resolver_text())
        self.assertIn('/etc/resolver/'+resolver.zone,resolver.install_command(True))
        self.assertNotIn('/etc/resolv.conf',resolver.install_command(True))
        self.assertNotIn('/etc/hosts',resolver.install_command(True))
        with self.assertRaises(ValueError):LocalDns('../../bad',18080)


class WebsiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.root = self.home / 'vault'
        self.root.mkdir()
        self.root = self.root.resolve()
        self.config = LocalConfig(self.home / 'state')
        self.config.save({'root': str(self.root)})
        self.put('site/index.html', b'<!doctype html><meta charset="gbk"><h1>\xc4\xe3\xba\xc3</h1><iframe src="nested.html"></iframe>')
        self.put('site/nested.html', b'<h1>nested</h1>')
        self.put('site/assets/app.mjs', b'export const value=42;')
        self.put('site/assets/module.wasm', b'\0asm\x01\0\0\0')
        self.put('site/api/data.json', b'{"value":42}')
        self.put('outside.txt', b'not in project')
        self.static = self.home / 'static'; self.static.mkdir()
        (self.static / 'index.html').write_text('<html>shared app</html>')
        self.runtime = Runtime(self.config)
        self.app = create_app(self.config, self.runtime, start_background=False, static_dir=self.static)
        self.client = TestClient(self.app, base_url='http://127.0.0.1:18080')
        self.client.__enter__()
        self.ui = self.app.state.websites.ui_origin
        self.token = (self.config.directory / 'auth-token').read_text().strip()
        self.auth = {'Authorization': 'Bearer ' + self.token}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def put(self, path, value):
        p = self.root / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(value)
        return p

    def project(self, **extra):
        response = self.client.post('/api/html-projects', headers=self.auth,
            json={'root': str(self.root), 'directory': 'site', 'entry': 'site/index.html', **extra})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def session(self, project=None, **extra):
        project = project or self.project()
        response = self.client.post('/api/html-sessions', headers=self.auth,
            json={'root': str(self.root), 'path': 'site/index.html', 'project_id': project['id'], **extra})
        self.assertEqual(response.status_code, 200, response.text)
        session = response.json()
        opened = self.client.get(session['url'])
        self.assertEqual(opened.status_code, 200, opened.text)
        return session

    def test_original_bytes_mime_nested_frames_and_root_paths(self):
        s = self.session(); origin = s['origin']
        response = self.client.get(origin + '/index.html')
        self.assertEqual(response.content, (self.root / 'site/index.html').read_bytes())
        self.assertEqual(response.headers['content-type'], 'text/html')
        self.assertNotIn('sandbox', response.headers['content-security-policy'])
        self.assertIn(self.ui, response.headers['content-security-policy'])
        self.assertEqual(self.client.get(origin + '/nested.html').status_code, 200)
        self.assertEqual(self.client.get(origin + '/assets/app.mjs').headers['content-type'], 'text/javascript')
        self.assertEqual(self.client.get(origin + '/assets/module.wasm').headers['content-type'], 'application/wasm')
        self.assertEqual(self.client.get(origin + '/api/data.json').json(), {'value':42})
        response = self.client.get(origin + '/assets/app.mjs', headers={'Range': 'bytes=0-5'})
        self.assertEqual(response.status_code, 206); self.assertEqual(response.content, b'export')
        self.put('site/assets/media.bin',bytes(range(256))*20)
        response=self.client.get(origin+'/assets/media.bin',headers={'Range':'bytes=0-2047','Accept-Encoding':'gzip'})
        self.assertEqual(response.content,(bytes(range(256))*20)[:2048])
        self.assertNotIn('content-encoding',response.headers)

    def test_cookie_blocked_viewer_uses_capability_and_same_origin_resources(self):
        s=self.session();origin=s['origin'];self.client.cookies.clear()
        self.assertEqual(self.client.get(origin+'/index.html').status_code,410)
        self.assertEqual(self.client.get(origin+'/index.html',headers={'Sec-Fetch-Site':'cross-site','Referer':self.ui+'/'}).status_code,410)
        self.assertEqual(self.client.get(origin+'/__leafloom__/viewer?session=invalid').status_code,410)
        viewer=origin+'/__leafloom__/viewer?session='+s['id']
        self.assertEqual(self.client.get(viewer).status_code,200)
        self.client.cookies.clear()  # Safari rejects this embedded Set-Cookie too.
        self.assertEqual(self.client.get(origin+'/index.html',headers={'Sec-Fetch-Site':'same-origin'}).status_code,200)
        self.assertEqual(self.client.get(origin+'/assets/app.mjs',headers={'Referer':viewer}).status_code,200)
        self.assertEqual(self.client.get(origin+'/api/bootstrap',headers={'Sec-Fetch-Site':'same-origin'}).status_code,404)
        self.assertEqual(self.client.get(viewer+'&path=//evil.example/').status_code,400)
        self.client.delete('/api/html-sessions/'+s['id'],headers=self.auth)
        self.assertEqual(self.client.get(viewer).status_code,410)
        self.assertEqual(self.client.get(origin+'/index.html',headers={'Sec-Fetch-Site':'same-origin'}).status_code,410)

    def test_authority_does_not_cross_project_or_management_origins(self):
        s = self.session(); origin = s['origin']
        for resource in ['/api/bootstrap', '/mcp', '/ai-mcp', '/outside.txt', '/%2e%2e/outside.txt']:
            self.assertEqual(self.client.get(origin + resource, headers=self.auth).status_code, 404, resource)
        self.assertEqual(self.client.post(origin + '/api/create', headers=self.auth, json={'path':'attack.md'}).status_code, 405)
        self.assertFalse((self.root/'attack.md').exists())
        self.assertEqual(self.client.get(self.ui + '/api/session', headers={'Origin':origin, **self.auth}).status_code, 403)
        self.assertEqual(self.client.get(origin + '/api/session', headers={'Host':'evil.example', **self.auth}).status_code, 403)
        anonymous = TestClient(self.app)
        self.assertEqual(anonymous.get(origin + '/index.html', headers=self.auth).status_code, 410)
        self.client.get(self.ui + '/')
        managed = [c for c in self.client.cookies.jar if c.name=='vault_session']
        self.assertEqual(len(managed), 1); self.assertEqual(managed[0].domain, urlsplit(self.ui).hostname)
        self.assertEqual(self.client.post(self.ui + '/api/html-projects', json={}).status_code, 403)
        try:(self.root/'site/escape').symlink_to(self.root, target_is_directory=True)
        except OSError:pass
        else:self.assertEqual(self.client.get(origin + '/escape/outside.txt').status_code, 404)
        self.put('site/.git/config', b'private')
        self.assertEqual(self.client.get(origin + '/.git/config').status_code, 404)

    def test_draft_is_temporary_and_never_overwrites_source_or_saved_storage(self):
        p = self.project(); saved = self.session(p)
        original = (self.root/'site/index.html').read_bytes()
        draft = self.session(p, draft='<h1>unsaved draft</h1>')
        self.assertNotEqual(saved['origin'], draft['origin'])
        self.assertEqual(self.client.get(draft['origin'] + '/index.html').text, '<h1>unsaved draft</h1>')
        self.assertEqual(self.client.get(draft['origin'] + '/nested.html').text, '<h1>nested</h1>')
        self.assertEqual((self.root/'site/index.html').read_bytes(), original)
        self.client.delete('/api/html-sessions/' + draft['id'], headers=self.auth)
        self.assertEqual(self.client.get(draft['origin'] + '/index.html').status_code, 410)
        self.assertEqual(self.client.get(saved['origin'] + '/index.html').status_code, 200)
        self.assertEqual(self.session(p)['origin'], saved['origin'])

    def test_spa_only_falls_back_for_document_navigation(self):
        s = self.session(self.project(spa=True)); base = s['origin']
        self.assertEqual(self.client.get(base + '/chapter/1', headers={'Accept':'text/html'}).status_code, 200)
        self.assertEqual(self.client.get(base + '/missing.mjs', headers={'Accept':'text/html'}).status_code, 404)
        self.assertEqual(self.client.get(base + '/chapter/1', headers={'Accept':'application/json'}).status_code, 404)

    def test_configuration_change_revokes_sessions_before_cache_validation(self):
        s = self.session(); response = self.client.get(s['origin'] + '/assets/app.mjs')
        etag = response.headers['etag']
        self.assertEqual(self.client.get(s['origin'] + '/assets/app.mjs', headers={'If-None-Match':etag}).status_code, 304)
        other = self.home/'other'; other.mkdir(); self.config.save({'root':str(other)})
        self.assertEqual(self.client.get(s['origin'] + '/assets/app.mjs', headers={'If-None-Match':etag}).status_code, 410)
        self.config.save({'root':str(self.root)})
        self.assertEqual(self.client.get(s['origin'] + '/index.html').status_code, 410)

    def test_registry_and_project_origin_survive_backend_restart(self):
        p = self.project(); old = self.session(p)
        from vault_rag.html_projects import HtmlProjects
        restarted = HtmlProjects(self.config, 18080)
        self.assertEqual(restarted.list(str(self.root), 'site/nested.html')['selected']['id'], p['id'])
        self.assertEqual(restarted.create(str(self.root), 'site/index.html', p['id'])['origin'], old['origin'])
        self.assertNotEqual(restarted._signature(urlsplit(old['origin']).hostname), self.app.state.websites._signature(urlsplit(old['origin']).hostname))

    def test_external_websites_use_their_original_url_without_a_proxy(self):
        response=self.client.post('/api/html-sessions',headers=self.auth,json={'root':str(self.root),'url':'http://127.0.0.1:3000/app?x=1#state'})
        self.assertEqual(response.json(),{'id':None,'url':'http://127.0.0.1:3000/app?x=1#state','mode':'external'})
        for url in [self.ui+'/', 'javascript:alert(1)', 'https://user:pass@example.com/']:
            self.assertEqual(self.client.post('/api/html-sessions',headers=self.auth,json={'root':str(self.root),'url':url}).status_code,400)

    def test_storage_migration_is_bounded_origin_checked_and_acknowledged(self):
        page = self.client.get('/')
        settings = json.loads(html.unescape(re.search('data-settings="([^"]+)"', page.text)[1]))
        data = {'local':[['draft:test','unsaved']], 'session':[['view:test','42']], 'returnTo':'?file=a#x'}
        url = '/__leafloom__/transfer?nonce=' + settings['nonce']
        self.assertEqual(self.client.post(url, json=data, headers={'Origin':'https://evil.example'}).status_code, 403)
        response = self.client.post(url, json=data, headers={'Origin':'http://127.0.0.1:18080'})
        self.assertEqual(response.status_code, 200, response.text)
        target = response.json()['url']; ticket = urlsplit(target).query
        read = self.ui + '/__leafloom__/transfer?' + ticket
        self.assertEqual(self.client.get(read).json()['local'], data['local'])
        self.assertEqual(self.client.get('/__leafloom__/transfer?' + ticket).status_code, 403)
        self.assertEqual(self.client.post(url, json=data, headers={'Origin':'http://127.0.0.1:18080'}).status_code, 400)
        self.assertEqual(self.client.delete(read).status_code, 200)
        self.assertEqual(self.client.get(read).status_code, 400)
        receipt=ticket.split('=',1)[1]
        self.assertTrue(self.client.get('/__leafloom__/migration-state?receipt='+receipt).json()['completed'])
        from vault_rag.browser_storage import BrowserStorageMigration
        self.assertTrue(BrowserStorageMigration(self.ui,18080,self.config.directory).completed(receipt))

    def test_resolver_installation_requires_csrf_or_one_use_legacy_capability(self):
        settings=json.loads(html.unescape(re.search('data-settings="([^"]+)"',self.client.get('/').text)[1]))
        dns=self.app.state.local_dns
        with patch.object(dns,'configure',return_value={'configured':True}) as configure,patch.object(dns,'socket',object()):
            url='/__leafloom__/local-resolver';body={'nonce':settings['nonce']}
            self.assertEqual(self.client.post(url,json=body).status_code,400)
            self.assertEqual(self.client.post(url,json=body,headers={'Origin':'https://evil.example'}).status_code,403)
            self.assertEqual(self.client.post(url,json=body,headers={'Origin':'http://127.0.0.1:18080'}).status_code,200)
            self.assertEqual(self.client.post(url,json=body,headers={'Origin':'http://127.0.0.1:18080'}).status_code,400)
            configure.assert_called_once_with(True)
            self.assertEqual(self.client.post('/api/local-resolver',json={'enabled':True}).status_code,401)
            self.client.get(self.ui+'/')
            self.assertEqual(self.client.post(self.ui+'/api/local-resolver',json={'enabled':True}).status_code,403)
            self.assertEqual(self.client.post(self.ui+'/api/local-resolver',json={'enabled':False},headers={'X-Vault-CSRF':self.app.state.csrf}).status_code,200)


if __name__=='__main__':unittest.main()
