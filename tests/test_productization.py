"""Preference changes must not reconfigure indexing; demos never overwrite edits."""
import json
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from vault_rag.local_state import LocalConfig
from vault_rag.preferences import Preferences
from vault_rag.demo import create_demo
from vault_rag.knowledge import Runtime
from vault_rag.web_server import create_app

class ProductizationTests(unittest.TestCase):
    def test_preferences_are_independent_and_private(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp);root=state/'notes';root.mkdir()
            config=LocalConfig(state/'state');config.save({'root':str(root),'include_roots':['']})
            before=config.path.read_bytes();runtime=Runtime(config)
            app=create_app(config,runtime,start_background=False)
            calls=[];runtime.configuration_changed=lambda:calls.append(True)
            with TestClient(app,base_url='http://127.0.0.1:18080') as client:
                client.cookies.set('vault_session',(config.directory/'auth-token').read_text())
                self.assertEqual(client.put('/api/preferences',json={'locale':'ja'}).status_code,403)
                headers={'X-Vault-CSRF':app.state.csrf}
                self.assertEqual(client.put('/api/preferences',headers=headers,json={'locale':'ja','guide':{'step':'scope','checked':['read']}}).status_code,200)
                self.assertEqual(client.get('/api/preferences').json()['locale'],'ja')
                self.assertEqual(client.get('/api/preferences').json()['guide']['step'],'scope')
                self.assertEqual(client.put('/api/preferences',headers=headers,json={'locale':'unknown'}).status_code,400)
            self.assertEqual(calls,[]);self.assertEqual(config.path.read_bytes(),before)
            self.assertNotIn(str(root),json.dumps(Preferences(config.directory).read()))

    def test_existing_configuration_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp);state.joinpath('config.json').write_text(json.dumps({**LocalConfig.defaults(),'include_roots':['RAG'],'homepage':'000-Home.md'}))
            existing=LocalConfig(state)
            self.assertEqual(existing.data['include_roots'],['RAG'])
            self.assertEqual(existing.data['homepage'],'000-Home.md')
            self.assertEqual(LocalConfig.defaults()['include_roots'],[])

    def test_demo_languages_and_returning_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)
            for language in ('zh-CN','en','ja'):
                first=create_demo(directory,language);root=Path(first['root'])
                self.assertTrue(root.is_relative_to(directory.resolve()));self.assertTrue((root/first['homepage']).exists())
                note=root/'Notes/01-Capture.md';note.write_text('my edited example',encoding='utf-8')
                second=create_demo(directory,language)
                self.assertEqual(first,second);self.assertEqual(note.read_text(),'my edited example')
                config=LocalConfig(directory/('state-'+language));config.save({'root':str(root),'include_roots':['']})
                runtime=Runtime(config);runtime.catalog.scan()
                query={'en':'ideas','zh-CN':'想法','ja':'アイデア'}[language]
                self.assertTrue(runtime.knowledge.search(query,mode='keyword')['results'])

if __name__=='__main__':unittest.main()
