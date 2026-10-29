"""The collection CLI uses only a mocked local API, never user state or a site."""
from contextlib import redirect_stderr,redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import collect_unity_catalog as cli


class CollectUnityCatalogTests(unittest.TestCase):
    def test_loopback_auth_boundary_and_partial_chinese_idempotency(self):
        for value in ('https://assetstore.unity.com','http://localhost:18080','http://127.0.0.1.evil.test',
                      'http://127.0.0.1@evil.test','http://user:password@127.0.0.1:18080',
                      'http://127.0.0.1:18080/','http://127.0.0.1:18080?','http://127.0.0.1:18080#',
                      'http://[::1%25en0]:18080','http://127.0.0.1:0','http://127.0.0.1:18080\n'):
            with self.subTest(origin=value),self.assertRaises(cli.CollectionError):cli.api_origin(value)
        self.assertEqual(cli.api_origin('http://[::1]:18080'),'http://[::1]:18080')
        with self.assertRaises(cli.CollectionError):
            cli.NoRedirect().redirect_request(None,None,302,'Found',{},'https://external.invalid/')
        secret='synthetic-test-token'
        official={'summary_zh':'适合移动项目的渲染工具。','summary_status':'provided','categories_zh':['渲染'],
                  'keywords_zh':['移动端'],'url':'https://assetstore.unity.com/packages/tools/tool-123'}
        revision='a'*64;next_revision='b'*64;requests=[];handlers=[];current={'value':{'title':'Tool'},'revision':revision}
        class Response(io.BytesIO):
            status=200
            headers={'Content-Type':'application/json; charset=utf-8'}
        class Opener:
            def open(self,request,timeout):
                self_outer.assertEqual(request.get_header('Authorization'),'Bearer '+secret)
                self_outer.assertTrue(request.full_url.startswith('http://127.0.0.1:18080/api/'))
                requests.append(request)
                if request.method=='GET':
                    value={'product_id':'123','revision':current['revision'],
                           'official':current['value'],'personal':{'tags':['keep-personal']},'token':secret}
                else:
                    body=json.loads(request.data)
                    self_outer.assertEqual(set(body),{'root','action','product_id','official','expected_revision','operation_id'})
                    self_outer.assertEqual(body['action'],'official')
                    self_outer.assertEqual(body['official'],official)
                    self_outer.assertEqual(body['expected_revision'],revision)
                    self_outer.assertEqual(body['operation_id'],cli.chinese_operation_id('123',official,revision))
                    value={'product_id':'123','revision':next_revision,'official':official,'personal':{'tags':['keep-personal']},'token':secret}
                return Response(json.dumps(value).encode())
        self_outer=self
        def opener(*values):handlers.extend(values);return Opener()
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);token=directory/'auth-token';token.write_text(secret)
            input_path=directory/'chinese.json';input_path.write_text(json.dumps([{'product_id':'123','official':official}]))
            report=directory/'report.json';output=io.StringIO()
            arguments=['--root',str(directory/'vault'),'--token-file',str(token),'--apply-chinese',str(input_path),'--report',str(report)]
            with patch.object(cli,'build_opener',side_effect=opener),redirect_stdout(output),redirect_stderr(output):
                self.assertEqual(cli.main(arguments),0)
                self.assertEqual(cli.main(arguments),0,'A lost response can retry the same content/base revision with the same operation ID')
                bodies=[json.loads(request.data) for request in requests if request.method=='POST']
                self.assertEqual(bodies[0],bodies[1])
                current['value']=dict(official)
                current['revision']=next_revision
                self.assertEqual(cli.main(arguments),0)
                self.assertEqual(sum(request.method=='POST' for request in requests),2,'An already-applied partial update must not create a new event')
                saved=json.loads(report.read_text())
                self.assertEqual((saved['state'],saved['applied'],saved['unchanged']),('completed',0,1))
                self.assertNotIn(secret,report.read_text()+output.getvalue())
                self.assertNotIn('keep-personal',report.read_text())
                self.assertNotIn(str(directory/'vault'),report.read_text())
                input_path.write_text(json.dumps([{'product_id':'123','official':official,'expected_revision':revision}]))
                self.assertEqual(cli.main(arguments),0,'An already-applied input remains a no-op even with its original snapshot revision')
                current['value']={'title':'New official facts'}
                self.assertEqual(cli.main(arguments),1,'A supplied snapshot revision must reject changed product facts')
                self.assertEqual(sum(request.method=='POST' for request in requests),2)
                before=token.read_bytes()
                self.assertEqual(cli.main(['--root',str(directory),'--token-file',str(token),'--report',str(token)]),1)
                self.assertEqual(token.read_bytes(),before,'Even an error report must not replace the credential file')
            self.assertTrue(any(isinstance(handler,cli.ProxyHandler) and handler.proxies=={} for handler in handlers))
            self.assertTrue(any(isinstance(handler,cli.NoRedirect) for handler in handlers))
            response=Response(b'<html>Login</html>');response.headers={'Content-Type':'text/html'}
            with patch.object(cli,'build_opener') as build:
                build.return_value.open.return_value=response
                with self.assertRaisesRegex(cli.CollectionError,'non-JSON'):
                    cli.LocalAPI('http://127.0.0.1:18080',secret).status(str(directory))


if __name__=='__main__':unittest.main()
