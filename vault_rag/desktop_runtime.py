"""Packaged service entry: no source checkout, installer, or global Python required."""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
from pathlib import Path
import sys
import threading

PROTOCOL_VERSION = 1


def build_info():
    path = Path(__file__).with_name('desktop-build.json')
    if path.exists():
        info = json.loads(path.read_text(encoding='utf-8'))
    else:
        info = {'version': '0.1.0', 'model_revision': None}
    return {'app_version': info['version'], 'desktop_protocol_version': PROTOCOL_VERSION,
            'distribution': 'desktop', 'model_revision': info.get('model_revision')}


@contextlib.contextmanager
def service_instance(directory):
    from vault_rag.platform_support import is_windows
    if is_windows():
        from vault_rag.windows_native import Instance
        with Instance(directory, 'service') as instance:
            if not instance.primary:
                raise RuntimeError('本地知识库服务已运行')
            yield
    else:
        import fcntl
        with (directory / 'desktop-service.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError('本地知识库服务已运行') from error
            yield


def self_check():
    import torch
    import lancedb
    import sentence_transformers
    from mcp.server.fastmcp import FastMCP
    from vault_rag.skill_install import skill_source
    from vault_rag.web_server import create_app
    from vault_rag.i18n import catalogue
    if not (Path(__file__).parent / 'static/index.html').is_file():
        raise RuntimeError('安装包缺少界面资源')
    if not skill_source().is_file():
        raise RuntimeError('安装包缺少技能资源')
    for language in ('en', 'zh-CN', 'ja'):
        if not catalogue(language) or not (Path(__file__).parent / 'examples' / language / 'manifest.json').is_file():
            raise RuntimeError('安装包缺少语言或示例资源：' + language)
    value = float((torch.ones(2) + torch.ones(2)).sum())
    if value != 4:
        raise RuntimeError('模型运行环境检查失败')
    # Exercise the native database extension, not just its Python import.
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        db = lancedb.connect(temp)
        table = db.create_table('smoke', [{'id': 1, 'vector': [1., 0.]}])
        if table.count_rows() != 1:
            raise RuntimeError('数据库运行环境检查失败')
    return {**build_info(), 'ok': True, 'torch': torch.__version__, 'lancedb': lancedb.__version__}


def serve(directory):
    import uvicorn
    from vault_rag.local_state import LocalConfig
    from vault_rag.platform_support import is_windows
    from vault_rag.web_server import create_app
    config = LocalConfig(directory)
    info = {**build_info(), 'desktop_instance_id': os.environ.get('VAULT_RAG_DESKTOP_OWNER')}
    if info['model_revision']:
        os.environ['VAULT_RAG_MODEL_REVISION'] = info['model_revision']
    with service_instance(config.directory):
        app = create_app(config, desktop_info=info)
        server = uvicorn.Server(uvicorn.Config(
            app, host='127.0.0.1', port=config.data.get('port', 18080), workers=1,
            access_log=False, loop='asyncio:SelectorEventLoop' if is_windows() else 'asyncio',
            timeout_graceful_shutdown=20))

        def stop():
            app.state.runtime.request_stop()
            server.should_exit = True

        def control_pipe():
            try:
                for line in sys.stdin:
                    try:
                        message = json.loads(line)
                    except ValueError:
                        continue
                    if message == {'command': 'shutdown'}:
                        break
            finally:
                # EOF also covers an Electron crash. Do not orphan the model.
                stop()

        threading.Thread(target=control_pipe, name='desktop-control', daemon=True).start()
        server.run()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['serve', 'self-check', 'model-check', 'version', 'inspect-legacy', 'migrate-legacy'])
    parser.add_argument('--home', type=Path)
    args = parser.parse_args(argv)
    if args.home:
        os.environ['VAULT_RAG_HOME'] = str(args.home.resolve())
    if args.action == 'version':
        print(json.dumps(build_info()))
        return
    if args.action == 'self-check':
        print(json.dumps(self_check()))
        return
    from vault_rag.local_state import LocalConfig
    config = LocalConfig(args.home)
    if args.action == 'model-check':
        import math
        from vault_rag.embedded_model import EmbeddedModel
        model = EmbeddedModel(config.directory)
        rows = model.encode(['安装包模型验收'])
        if len(rows) != 1 or len(rows[0]) != 1024 or not all(math.isfinite(value) for value in rows[0]):
            raise RuntimeError('安装包模型推理检查失败')
        print(json.dumps({'ok': True, 'dimension': len(rows[0]), 'device': model.device}))
        return
    if args.action.endswith('legacy'):
        from vault_rag.desktop_migration import inspect_legacy, migrate_legacy
        value = inspect_legacy(config) if args.action == 'inspect-legacy' else migrate_legacy(config)
        print(json.dumps(value, ensure_ascii=False))
        return
    from logging.handlers import RotatingFileHandler
    logs = config.directory / 'logs'
    logs.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(
        logs / 'desktop-backend.log', maxBytes=5_000_000, backupCount=3, encoding='utf-8')], force=True)
    serve(config.directory)


if __name__ == '__main__':
    main()
