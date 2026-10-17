"""Private stdio fixture bridge for the real Electron publishing smoke test."""
import base64
import copy
import json
import struct
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_publishing_fixture import ART_SVG, fixture_document
from vault_rag.design_publishing import DesignPublisher
from vault_rag.local_state import LocalConfig, Files

with tempfile.TemporaryDirectory(prefix='leafloom-native-publish-') as directory:
    root = Path(directory) / 'vault'
    asset = root / 'Projects/Fixture/Design/Assets/shared-art.svg'
    asset.parent.mkdir(parents=True)
    asset.write_text(ART_SVG)
    config = LocalConfig(Path(directory) / 'config')
    config.save({'root': str(root), 'include_roots': ['Projects']})
    document = fixture_document()
    workspace = SimpleNamespace(config=config, files=Files(config), documents=SimpleNamespace(
        read=lambda _: {'document': copy.deepcopy(document), 'revision': 'fixture-revision'}))
    publisher = DesignPublisher(workspace)
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                command = request['command']
                if command == 'start':
                    blocked = request.get('blocked', False)
                    job = publisher.start({'directory': 'Projects/Fixture', 'expected_revision': 'fixture-revision',
                        'page_ids': ['page-1'] if blocked else [f'page-{i}' for i in range(1, 6)],
                        'variant_ids': ['en'] if blocked else ['en', 'ja', 'zh'], 'scale': request.get('scale', 1),
                        'renderer': 'native', 'format': request['format']})
                    result = publisher.native_manifest(job['job_id'])
                elif command == 'result':
                    result = publisher.native_result(request['job_id'], request['body'])
                elif command == 'verify':
                    job = publisher.get(request['job_id'])
                    assert job['status'] == 'completed', job
                    path, _, _ = publisher.download(request['job_id'])
                    if job['format'] == 'pdf':
                        from pypdf import PdfReader
                        pages = PdfReader(path).pages
                        assert len(pages) == 15
                        for page in pages:
                            assert abs(float(page.mediabox.width) - 540) < 2
                            assert abs(float(page.mediabox.height) - 675) < 2
                        assert 'Creative collection 1' in pages[0].extract_text()
                        result = {'pages': len(pages), 'format': 'pdf'}
                    else:
                        with zipfile.ZipFile(path) as archive:
                            names = [name for name in archive.namelist() if name.endswith('.png')]
                            assert len(names) == 15
                            for name in names:
                                data = archive.read(name)
                                assert struct.unpack('>II', data[16:24]) == (1440, 1800)
                            assert 'manifest.json' in archive.namelist()
                        result = {'pages': len(names), 'format': 'png'}
                else:
                    raise ValueError('Unknown test command')
                print(json.dumps({'ok': True, 'result': result}), flush=True)
            except Exception as error:
                print(json.dumps({'ok': False, 'error': str(error)}), flush=True)
    finally:
        publisher.pool.shutdown(wait=True)
