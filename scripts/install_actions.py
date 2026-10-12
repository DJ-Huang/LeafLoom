"""Post-install checks/actions. Only this stage imports application dependencies."""
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def check():
    import vault_rag
    import lancedb
    import numpy
    import pandas
    import torch
    from sentence_transformers import SentenceTransformer
    from vault_rag import web_server
    if sys.platform == 'win32':
        import pystray
    assert sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32
    assert torch.tensor([1.0, 2.0], device='cpu').sum().item() == 3.0
    print(f'Native dependency check passed: Python 3.12, PyTorch {torch.__version__}, LanceDB {lancedb.__version__}')


def check_runtime():
    # Installation already checked native DLLs. Daily launch only detects missing
    # packages, without loading another PyTorch/transformers instance.
    import importlib.util
    names = ('vault_rag', 'lancedb', 'numpy', 'pandas', 'torch',
             'sentence_transformers', 'fastapi', 'uvicorn', 'mcp', 'httpx')
    if sys.platform == 'win32': names += ('pystray', 'PIL', 'msvc_runtime')
    missing = [name for name in names if importlib.util.find_spec(name) is None]
    if missing: raise RuntimeError('运行依赖缺失：' + ', '.join(missing))
    assert sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32


def verify():
    import urllib.request
    from vault_rag.local_state import LocalConfig
    from vault_rag.service_control import ensure_ready, request, base_url
    config = LocalConfig()
    ensure_ready(config)
    status = request('/api/status', config=config)
    assert status['model']['prepared'], 'Model is not prepared'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(base_url(config) + '/', timeout=10) as response:
        html = response.read().decode('utf-8')
    import re
    resources = re.findall(r'(?:src|href)="(/assets/[^"?#]+)', html)
    assert resources, 'Web assets are missing'
    for path in resources:
        with opener.open(base_url(config) + path, timeout=10) as response:
            assert response.status == 200
    print('Authenticated service and web resources verified.')


def main(action):
    if action == 'check': return check()
    if action == 'check-runtime': return check_runtime()
    if action == 'verify': return verify()
    if os.environ.get('VAULT_RAG_INSTALL_TEST_SERVER') == '1':
        return test_server(action)
    from vault_rag.service_control import control
    control(action)
    if sys.platform == 'darwin' and action == 'install':
        import runpy
        runpy.run_path(str(Path(__file__).resolve().parent / 'macos/install_menu.py'), run_name='__main__')
    if sys.platform == 'darwin' and action == 'open':
        import subprocess
        from vault_rag.local_state import LocalConfig
        repo = Path(__file__).resolve().parents[1]
        logs = LocalConfig().directory / 'logs'
        with (logs / 'menubar.log').open('a', encoding='utf-8') as stream:
            subprocess.Popen(['/bin/bash', str(repo / 'scripts/macos/start_menu.sh'), str(repo), str(LocalConfig().directory)],
                             stdin=subprocess.DEVNULL, stdout=stream, stderr=stream, start_new_session=True)


def test_server(action):
    """CI lacks an interactive desktop; never label this as login-task verification."""
    import subprocess
    import time
    from vault_rag.local_state import LocalConfig
    from vault_rag.service_control import health, ensure_ready
    config = LocalConfig()
    if action == 'install':
        assert not config.data.get('root'), 'Test server requires isolated, unassociated state'
        (config.directory / 'test-server.stop').unlink(missing_ok=True)
        logs = config.directory / 'logs'; logs.mkdir(exist_ok=True)
        with (logs / 'test-server.log').open('a', encoding='utf-8') as stream:
            subprocess.Popen([sys.executable, '-X', 'utf8', str(Path(__file__).with_name('install_test_server.py'))],
                             stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                             **({'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {'start_new_session':True}))
        ensure_ready(config)
    elif action == 'uninstall':
        (config.directory / 'test-server.stop').touch()
        deadline = time.monotonic() + 60
        while (config.directory / 'test-server.started').exists():
            if time.monotonic() > deadline: raise RuntimeError('CI server did not stop normally')
            time.sleep(.2)
    elif action == 'open':
        ensure_ready(config)
    else:
        raise ValueError('Unsupported CI server action: ' + action)


if __name__ == '__main__':
    main(sys.argv[1])
