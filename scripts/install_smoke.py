"""Real cold-install acceptance in an isolated copy. Preserves logs; never changes linked notes."""
from __future__ import annotations
import argparse
import ast
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reuse-model-from', type=Path)
    parser.add_argument('--output', type=Path, default=Path('_generated/install-validation.json'))
    parser.add_argument('--no-desktop', action='store_true', help='CI-only: validate a child server instead of OS login tasks')
    args = parser.parse_args()
    original = Path(__file__).resolve().parents[1]
    fixture = Path(tempfile.mkdtemp(prefix='VaultRag 中文 cold install '))
    repo = fixture / 'repository'; state = fixture / 'state'
    ignored = shutil.ignore_patterns('.git', '.venv*', '.install.lock', 'node_modules', '_index', '_generated',
                                     'static', '.cache', '__pycache__', '.env', '*.log', '*.tsbuildinfo')
    shutil.copytree(original, repo, ignore=ignored)
    state.mkdir()
    # Read the actual defaults without importing any installed third-party dependency.
    tree = ast.parse((repo / 'vault_rag/local_state.py').read_text(encoding='utf-8'))
    config_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'LocalConfig')
    defaults = next(node for node in config_class.body if isinstance(node, ast.FunctionDef) and node.name == 'defaults')
    config = ast.literal_eval(next(node.value for node in defaults.body if isinstance(node, ast.Return)))
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0)); config['port'] = probe.getsockname()[1]
    (state / 'config.json').write_text(json.dumps(config), encoding='utf-8')
    if args.reuse_model_from:
        source = args.reuse_model_from / 'models'
        def link_or_copy(source_file, destination):
            try: os.link(source_file, destination)
            except OSError: shutil.copy2(source_file, destination)
        shutil.copytree(source, state / 'models', copy_function=link_or_copy,
                        ignore=shutil.ignore_patterns('.cache'))
    assert not (repo / '.venv').exists() and not (repo / 'vault_rag/static').exists() and not (state / 'runtimes').exists()
    env = dict(os.environ, VAULT_RAG_HOME=str(state), PYTHONUTF8='1', PYTHONUNBUFFERED='1')
    # Only OS-shipped tools remain visible; globally installed Python/Node/uv
    # cannot accidentally satisfy an empty-machine prerequisite.
    system = Path(os.environ.get('SystemRoot', 'C:/Windows'))
    env['PATH'] = os.pathsep.join(str(p) for p in (system/'System32',system,system/'System32/WindowsPowerShell/v1.0')) if sys.platform=='win32' else '/usr/bin:/bin:/usr/sbin:/sbin'
    if args.no_desktop: env['VAULT_RAG_INSTALL_TEST_SERVER'] = '1'
    bootstrap = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(repo / 'scripts/setup.ps1'), '-NoOpen'] if sys.platform == 'win32' else ['/bin/bash', str(repo / 'scripts/macos/launch.sh'), 'install', '--no-open']
    python = repo / ('.venv/Scripts/python.exe' if sys.platform == 'win32' else '.venv/bin/python')
    report = {'platform':sys.platform, 'architecture':__import__('platform').machine(), 'fixture':str(fixture),
              'cold_runtime_cache':True, 'global_tools_hidden':True, 'model_reused':bool(args.reuse_model_from), 'desktop_tasks':not args.no_desktop,
              'passed':False, 'started_at':time.time()}
    try:
        subprocess.run(bootstrap, cwd=repo, env=env, check=True)
        subprocess.run([python, '-X','utf8', repo/'scripts/installer.py','--state',state,'--action','check'],cwd=repo,env=env,check=True)
        # The fixture has no linked root, so its server won't load a competing model.
        subprocess.run([python, '-X', 'utf8', '-m', 'vault_rag.cli', 'model-prepare'], cwd=repo, env=env, check=True)
        code = "from vault_rag.embedded_model import EmbeddedModel; from vault_rag.local_state import LocalConfig; import math; m=EmbeddedModel(LocalConfig().directory); rows=m.encode(['一键安装验证']); assert len(rows)==1 and len(rows[0])==1024 and all(math.isfinite(x) for x in rows[0]); print('BGE-M3 inference passed:',m.device)"
        subprocess.run([python,'-X','utf8','-c',code],cwd=repo,env=env,check=True)
        acceptance = repo / 'scripts/install_acceptance.py'
        subprocess.run([python,'-X','utf8',acceptance],cwd=repo,env=env,check=True)
        # A second run uses the actual success marker and dependency/model checks, with no install/download.
        subprocess.run([python,'-X','utf8',repo/'scripts/installer.py','--state',state,'--action','open','--no-open'],cwd=repo,env=env,check=True)
        report['passed'] = True
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        # Remove only this fixture's registered tasks; keep its files/logs for inspection.
        if python.exists():
            subprocess.run([python,'-X','utf8',repo/'scripts/install_actions.py','uninstall'],cwd=repo,env=env,check=False)
        report['finished_at'] = time.time()
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Acceptance report:',args.output.resolve())


if __name__ == '__main__': main()
