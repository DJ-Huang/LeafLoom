"""Private desktop sidecar. stdout is a control pipe; stderr contains logs."""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time


_emit_lock = threading.Lock()
def emit(kind, **values):
    with _emit_lock:
        print(json.dumps({'type': kind, **values}, ensure_ascii=False), flush=True)


@contextlib.contextmanager
def instance_lock(config, role='service'):
    if sys.platform == 'win32':
        from vault_rag.windows_native import Instance
        with Instance(config.directory, role) as instance:
            if not instance.primary:
                raise RuntimeError('Another LeafLoom service is running')
            yield instance
    else:
        import fcntl
        with (config.directory / ('desktop-' + role + '.lock')).open('a+b') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield None


def run():
    from vault_rag.local_state import LocalConfig
    from vault_rag.desktop import LegacyMigration
    from vault_rag.web_server import create_app, create_server
    from vault_rag import __version__

    config = LocalConfig()
    migration = LegacyMigration(config)
    finished = threading.Event()
    committed = threading.Event()
    startup = time.monotonic()
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, force=True)
    server = None
    tunnel = None
    with instance_lock(config, 'desktop-controller'):
        try:
            autostart = migration.begin()
            with instance_lock(config) as native:
                app = create_app(config)
                options = {'port': config.data.get('port', 18080)}
                if sys.platform == 'win32':
                    options['loop'] = 'asyncio:SelectorEventLoop'
                server = create_server(app, **options)
                from vault_rag.tunnel import TunnelManager
                tunnel = TunnelManager(config.directory, options['port'], emit, mcp_access=app.state.mcp_access)
                from vault_rag.control_pipe import ControlPipe
                control = ControlPipe(sys.stdin)
                def stop():
                    tunnel.close()
                    app.state.runtime.request_stop()
                    server.should_exit = True
                def commands():
                    try:
                        for line in control.lines():
                            command = json.loads(line)
                            if command.get('type') == 'commit':
                                migration.commit()
                                committed.set()
                                emit('committed')
                            elif command.get('type') == 'shutdown':
                                stop()
                                return
                            elif command.get('type') == 'tunnel-configure' and committed.is_set():
                                tunnel.configure(command)
                    except Exception:
                        logging.exception('Desktop control pipe failed')
                    finally:
                        stop()  # EOF means our desktop parent is gone.
                def readiness():
                    while not finished.wait(.1):
                        if native and native.wait_for_stop(0):
                            stop()
                            return
                        if not committed.is_set() and time.monotonic() - startup > 120:
                            logging.error('Desktop startup/commit timed out')
                            stop()
                            return
                        if server.started:
                            emit('ready', url=f'http://127.0.0.1:{options["port"]}',
                                 version=__version__, autostart=autostart, pid=os.getpid())
                            # Continue watching the native stop event after readiness.
                            while not finished.wait(.2):
                                if native and native.wait_for_stop(0):
                                    stop()
                                    return
                                if not committed.is_set() and time.monotonic() - startup > 120:
                                    stop()
                                    return
                            return
                threading.Thread(target=commands, daemon=True).start()
                threading.Thread(target=readiness, daemon=True).start()
                server.run()
        finally:
            finished.set()
            if tunnel: tunnel.close()
            # Release the service lock and close HTTP before restoring legacy agents.
            if not migration.committed:
                migration.rollback()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.check:
        import torch, lancedb, sentence_transformers
        from vault_rag.web_server import create_app
        assert torch.tensor([1, 2]).sum().item() == 3
        emit('checked', python=sys.version.split()[0], torch=torch.__version__, lancedb=lancedb.__version__)
        return
    try:
        run()
    except Exception as error:
        logging.exception('Desktop backend failed')
        emit('error', message=str(error))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
