"""Model-install integrity, offline migration and interrupted-download recovery."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from vault_rag.embedded_model import EmbeddedModel


class ModelInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.model=EmbeddedModel(Path(self.temp.name))
        self.payloads={'config.json':b'{}','tokenizer_config.json':b'{}','tokenizer.json':b'{}','model.safetensors':b'fake weights'}
        self.siblings=[SimpleNamespace(rfilename=name,size=len(value),lfs=SimpleNamespace(sha256=hashlib.sha256(value).hexdigest())) for name,value in self.payloads.items()]
        self.info=SimpleNamespace(sha='pinned-revision',siblings=self.siblings)

    def tearDown(self):self.temp.cleanup()

    def files(self,*_,**kwargs):
        self.model.path.mkdir(parents=True,exist_ok=True)
        for name,value in self.payloads.items():(self.model.path/name).write_bytes(value)

    def test_download_checks_files_and_pins_receipt(self):
        with patch('huggingface_hub.HfApi') as api,patch('huggingface_hub.snapshot_download',side_effect=self.files) as download:
            api.return_value.model_info.return_value=self.info
            self.model.prepare()
        self.assertTrue(self.model.ready)
        self.assertEqual(download.call_args.kwargs['revision'],'pinned-revision')
        receipt=json.loads(self.model.manifest.read_text())
        self.assertEqual(receipt['files']['model.safetensors']['size'],len(self.payloads['model.safetensors']))
        self.assertFalse((self.model.directory/'models/model-download.json').exists())

    def test_missing_and_same_size_corrupt_config_are_not_ready(self):
        self.files();self.model._receipt('pinned-revision',self.payloads)
        (self.model.path/'tokenizer.json').write_bytes(b'xx')
        self.assertFalse(self.model.ready)
        self.files();(self.model.path/'model.safetensors').unlink();self.assertFalse(self.model.ready)

    def test_corrupt_download_never_publishes_success_receipt(self):
        def corrupt(*args,**kwargs):
            self.files();(self.model.path/'model.safetensors').write_bytes(b'bad weights!')
        with patch('huggingface_hub.HfApi') as api,patch('huggingface_hub.snapshot_download',side_effect=corrupt),patch('huggingface_hub.hf_hub_download'):
            api.return_value.model_info.return_value=self.info
            with self.assertRaises(RuntimeError):self.model.prepare()
        self.assertFalse(self.model.manifest.exists());self.assertFalse(self.model.ready)

    def test_damaged_cached_file_is_preserved_and_downloaded_again(self):
        self.files();self.model._receipt('pinned-revision',self.payloads)
        (self.model.path/'config.json').write_bytes(b'xx')
        with patch('huggingface_hub.HfApi') as api,patch('huggingface_hub.snapshot_download'),patch('huggingface_hub.hf_hub_download',side_effect=self.files) as download:
            api.return_value.model_info.return_value=self.info
            self.model.prepare()
        self.assertTrue(self.model.ready)
        self.assertTrue(download.call_args.kwargs['force_download'])
        backup=next((self.model.directory/'models').glob('damaged-*/config.json'))
        self.assertEqual(backup.read_bytes(),b'xx')

    def test_interrupted_download_keeps_revision_for_next_attempt(self):
        with patch('huggingface_hub.HfApi') as api,patch('huggingface_hub.snapshot_download',side_effect=ConnectionError('reset')):
            api.return_value.model_info.return_value=self.info
            with self.assertRaises(ConnectionError):self.model.prepare()
        with patch('huggingface_hub.HfApi') as api,patch('huggingface_hub.snapshot_download',side_effect=self.files):
            api.return_value.model_info.return_value=self.info
            self.model.prepare()
            self.assertEqual(api.return_value.model_info.call_args.kwargs['revision'],'pinned-revision')

    def test_complete_legacy_model_is_adopted_without_network_or_new_revision(self):
        self.files();self.model.manifest.write_text(json.dumps({'model':self.model.model_id,'revision':'legacy-revision'}))
        with patch('huggingface_hub.HfApi',side_effect=AssertionError('network called')):
            self.model.prepare();self.model.prepare()
        self.assertTrue(self.model.ready)
        self.assertEqual(json.loads(self.model.manifest.read_text())['revision'],'legacy-revision')


if __name__=='__main__':unittest.main()
