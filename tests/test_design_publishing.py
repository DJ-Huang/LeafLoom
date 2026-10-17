"""Immutable batch publication limits, offline rendering and native result intake."""
import copy
import io
import json
import os
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from vault_rag.design_publishing import DesignPublisher, plan, render_item, renderer_available, validate_static_media
from vault_rag.local_state import LocalConfig, Files, ConflictError


def document():
    return {'id':'doc','name':'Test','pages':[{'id':'one','name':'One','width':200,'height':100,
            'nodes':[{'id':'text','type':'text','props':{'text':'Hello'},'style':{'x':0,'y':0,'width':100,'height':30}}]},
            {'id':'two','name':'Two','width':160,'height':80,'nodes':[]}],
            'components':{},'assets':{},'styles':{},'scripts':{},'bindings':{},'variants':{}}


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)/'vault'; self.root.mkdir()
        self.config=LocalConfig(Path(self.temp.name)/'config')
        self.config.save({'root':str(self.root),'include_roots':['Projects']})
        self.files=Files(self.config)
        self.doc=document()
        workspace=SimpleNamespace(config=self.config,files=self.files,
                                  documents=SimpleNamespace(read=lambda _: {'document':copy.deepcopy(self.doc),'revision':'rev'}))
        self.publisher=DesignPublisher(workspace)
        self.body={'directory':'Projects/Design','expected_revision':'rev','page_ids':['one','two'],'renderer':'native','format':'png'}

    def tearDown(self):
        self.publisher.pool.shutdown(wait=True)
        self.temp.cleanup()

    def test_animated_media_rejected_without_changing_source(self):
        import base64
        for data in (b'GIF89a',b'\x89PNG\r\n\x1a\nacTL',b'RIFF0000WEBPANIM',b'<svg><animate attributeName="x"/></svg>'):
            with self.assertRaisesRegex(ValueError,'static'):
                validate_static_media(data)
        self.doc['pages'][0]['nodes'][0]['props']['src']='data:image/svg+xml;base64,'+base64.b64encode(b'<svg><set attributeName="x"/></svg>').decode()
        before=copy.deepcopy(self.doc)
        with self.assertRaisesRegex(ValueError,'static SVG'):
            plan(self.doc,['one'])
        self.assertEqual(before,self.doc)
        self.doc['pages'][0]['nodes'][0]['props']['src']='data:image/png;base64,iVBORw0KGgo='
        plan(self.doc,['one'])

    def test_limits_and_order(self):
        items,pixels=plan(self.doc,['two','one'])
        self.assertEqual([i['page_id'] for i in items],['two','one'])
        self.assertEqual(pixels,32800)
        for scale in (0,5,True,float('nan')):
            with self.assertRaises(ValueError): plan(self.doc,['one'],scale=scale)
        for pages in ([],['one','one'],['missing']):
            with self.assertRaises(ValueError): plan(self.doc,pages)
        self.doc['pages'][0]['width']=8193
        with self.assertRaises(ValueError): plan(self.doc,['one'])

    def test_stale_revision_does_not_start_job(self):
        with self.assertRaises(ConflictError): self.publisher.start({**self.body,'expected_revision':'old'})
        self.assertFalse(self.publisher.jobs)

    def test_native_manifest_is_frozen_and_root_bound(self):
        job=self.publisher.start(self.body)
        self.doc['pages'][0]['nodes'][0]['props']['text']='Changed'
        manifest=self.publisher.native_manifest(job['job_id'])
        self.assertEqual(manifest['pages'][0]['document']['pages'][0]['nodes'][0]['props']['text'],'Hello')
        other=Path(self.temp.name)/'other'; other.mkdir()
        self.config.save({'root':str(other),'include_roots':['Projects']})
        with self.assertRaises(ValueError): self.publisher.get(job['job_id'])
        with self.assertRaises(ValueError): self.publisher.native_manifest(job['job_id'])

    def test_partial_job_retry_preserves_success_and_creates_archive(self):
        import base64
        job=self.publisher.start(self.body); id=job['job_id']
        # Intake validates signature and dimensions; native renderer supplies real PNG.
        png=b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',200,100)
        self.publisher.native_result(id,{'item_id':'1','data_base64':base64.b64encode(png).decode()})
        failed=self.publisher.native_result(id,{'item_id':'2','error':'Image failed'})
        self.assertEqual((failed['status'],failed['completed']),('partial',1))
        path,_,_=self.publisher.download(id)
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(set(archive.namelist()),{'001.png','manifest.json'})
        retry=self.publisher.retry(id)
        self.assertEqual(retry['items'][0]['status'],'completed')
        self.assertEqual([p['id'] for p in self.publisher.native_manifest(id)['pages']],['2'])
        self.assertEqual(self.publisher.jobs[id]['_outputs']['1'],png)

    def test_native_rejects_mismatched_output(self):
        import base64
        job=self.publisher.start(self.body)
        for data in (b'not png',b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',9000,9000)):
            with self.assertRaises(ValueError):
                self.publisher.native_result(job['job_id'],{'item_id':'1','data_base64':base64.b64encode(data).decode()})

    def test_asset_path_cannot_escape_project(self):
        self.doc['assets']={'bad':{'path':'../secret.png'}}
        with self.assertRaises(ValueError): self.publisher.start(self.body)

    def test_multipage_pdf_assembly_preserves_selected_order(self):
        import base64
        from pypdf import PdfReader, PdfWriter
        job=self.publisher.start({**self.body,'format':'pdf','page_ids':['two','one']})
        for item in job['items']:
            writer=PdfWriter(); writer.add_blank_page(width=item['width']*.75,height=item['height']*.75)
            out=io.BytesIO(); writer.write(out)
            result=self.publisher.native_result(job['job_id'],{'item_id':item['id'],'data_base64':base64.b64encode(out.getvalue()).decode()})
        self.assertEqual(result['status'],'completed')
        path,mime,name=self.publisher.download(job['job_id'])
        pdf=PdfReader(path)
        self.assertEqual([float(page.mediabox.width) for page in pdf.pages],[120,150])
        self.assertEqual(mime,'application/pdf')
        self.assertEqual(name,'publication.pdf')

    def test_symlink_asset_is_rejected(self):
        target=self.root/'Projects/Design/Design/Assets'; target.mkdir(parents=True)
        outside=Path(self.temp.name)/'secret'; outside.write_bytes(b'secret')
        (target/'linked.png').symlink_to(outside)
        self.doc['assets']={'bad':{'path':'Design/Assets/linked.png'}}
        with self.assertRaises(ValueError): self.publisher.start(self.body)

    def test_shared_item_job_and_session_output_limits(self):
        one=self.publisher.start(self.body)['job_id']
        two=self.publisher.start(self.body)['job_id']
        job=self.publisher.jobs[one]
        with patch('vault_rag.design_publishing.MAX_ITEM_OUTPUT',8):
            with self.assertRaisesRegex(ValueError,'page exceeds'):
                self.publisher._check_output(job,'1',b'x'*9)
        job['_outputs']['1']=b'x'*6
        with patch('vault_rag.design_publishing.MAX_JOB_OUTPUT',8):
            with self.assertRaisesRegex(ValueError,'batch limit'):
                self.publisher._check_output(job,'2',b'x'*3)
        self.publisher.jobs[two]['_outputs']['1']=b'x'*6
        with patch('vault_rag.design_publishing.MAX_SESSION_OUTPUT',14):
            with self.assertRaisesRegex(ValueError,'session output'):
                self.publisher._check_output(job,'2',b'x'*3)
            # Replacing a retained output counts only its delta.
            self.publisher._check_output(job,'1',b'x'*7)

    def test_headless_output_limit_becomes_retryable_item_error(self):
        with patch('vault_rag.design_publishing.renderer_available',return_value=True), \
             patch('vault_rag.design_publishing.render_item',return_value=b'x'*9), \
             patch('vault_rag.design_publishing.MAX_ITEM_OUTPUT',8):
            job=self.publisher.start({**self.body,'renderer':'headless','page_ids':['one']})
            self.publisher.pool.shutdown(wait=True)
        result=self.publisher.get(job['job_id'])
        self.assertEqual(result['status'],'failed')
        self.assertIn('page exceeds',result['items'][0]['error'])
        self.assertFalse(self.publisher.jobs[job['job_id']]['_outputs'])

    def test_assembly_failure_can_retry_without_rerendering(self):
        import base64
        job=self.publisher.start({**self.body,'page_ids':['one']})
        png=b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',200,100)
        with patch('vault_rag.design_publishing.atomic_write',side_effect=OSError('Temporary disk failure')):
            failed=self.publisher.native_result(job['job_id'],{'item_id':'1','data_base64':base64.b64encode(png).decode()})
        self.assertEqual(failed['status'],'failed')
        self.assertEqual(failed['items'][0]['status'],'completed')
        retried=self.publisher.retry(job['job_id'])
        self.assertEqual(retried['status'],'completed')
        self.assertTrue(self.publisher.download(job['job_id'])[0].is_file())

    def test_native_claim_and_inactivity_failure(self):
        job=self.publisher.start(self.body); id=job['job_id']
        self.publisher.native_manifest(id)
        with self.assertRaises(ConflictError): self.publisher.native_manifest(id)
        self.publisher.jobs[id]['_last_progress']-=181
        expired=self.publisher.get(id)
        self.assertEqual(expired['status'],'failed')
        self.assertTrue(all(item['status']=='failed' for item in expired['items']))
        self.publisher.retry(id)
        self.assertEqual(len(self.publisher.native_manifest(id)['pages']),2)
        failed=self.publisher.native_failure(id,'Desktop startup failed')
        self.assertEqual(failed['status'],'failed')

    def test_native_retry_resumes_interrupted_transport(self):
        job=self.publisher.start(self.body)
        self.publisher.native_manifest(job['job_id'])
        retried=self.publisher.retry(job['job_id'])
        self.assertEqual(retried['status'],'queued')
        self.assertEqual(len(self.publisher.native_manifest(job['job_id'])['pages']),2)

    def test_variant_warnings_and_snapshot_bounds(self):
        self.doc['bindings']={'headline':{'key':'headline','kind':'text','value':'Hello','revision':2}}
        self.doc['variants']={'fr':{'id':'fr','values':{'headline':{'value':'Bonjour','sourceRevision':1}}}}
        self.doc['pages'][0]['nodes'][0]['props']['bindingKey']='headline'
        body={**self.body,'variant_ids':['fr']}
        result=self.publisher.preflight(body)
        self.assertTrue(any('need review' in warning for warning in result['warnings']))
        job=self.publisher.start(body)
        self.assertEqual(self.publisher.native_manifest(job['job_id'])['pages'][0]['document']['pages'][0]['nodes'][0]['props']['text'],'Bonjour')
        self.doc['pages'][0]['nodes'][0]['props']['text']='x'*(17*1024*1024)
        with self.assertRaisesRegex(ValueError,'snapshot exceeds'):
            self.publisher.preflight(self.body)

    def test_missing_optional_renderer_is_actionable(self):
        with patch('vault_rag.design_publishing.renderer_available',return_value=False):
            body={**self.body,'renderer':'headless'}
            self.assertFalse(self.publisher.preflight(body)['renderer_available'])
            with self.assertRaisesRegex(ValueError,'publish extra'): self.publisher.start(body)

    @unittest.skipUnless(os.getenv('LEAFLOOM_PUBLISH_BROWSER_TESTS') == '1' and renderer_available('pdf'),'Set LEAFLOOM_PUBLISH_BROWSER_TESTS=1 for real Chromium tests')
    def test_real_static_render_dimensions_scripts_and_pdf(self):
        from pypdf import PdfReader
        self.doc['pages'][0]['script']={'source':"throw Error('MUST NOT RUN')"}
        item=plan(self.doc,['one'])[0][0]
        png=render_item(item,{},'png',2)
        self.assertEqual(struct.unpack('>II',png[16:24]),(400,200))
        pdf=PdfReader(io.BytesIO(render_item(item,{},'pdf',1)))
        self.assertEqual(len(pdf.pages),1)
        self.assertAlmostEqual(float(pdf.pages[0].mediabox.width),150,delta=1)

    @unittest.skipUnless(os.getenv('LEAFLOOM_PUBLISH_BROWSER_TESTS') == '1' and renderer_available(),'Set LEAFLOOM_PUBLISH_BROWSER_TESTS=1 for real Chromium tests')
    def test_remote_image_is_blocked(self):
        self.doc['pages'][0]['nodes']=[{'id':'remote','type':'image','props':{'src':'https://example.com/secret.png'},'style':{'width':30,'height':30}}]
        with self.assertRaises(Exception): render_item(plan(self.doc,['one'])[0][0],{},'png',1)
