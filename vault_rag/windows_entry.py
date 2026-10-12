"""Quiet task/double-click entrypoint; importing this module never loads a model."""
from __future__ import annotations
import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
import sys


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['service', 'tray', 'open', 'stop', 'install'])
    parser.add_argument('--home')
    args = parser.parse_args(argv)
    if args.home:os.environ['VAULT_RAG_HOME'] = args.home
    from vault_rag.platform_support import is_windows, state_directory, show_error
    if not is_windows():raise RuntimeError('此入口仅适用于 Windows')
    logs = state_directory() / 'logs'
    try:
        from vault_rag.local_state import LocalConfig
        config = LocalConfig()
        logs.mkdir(exist_ok=True)
        # pythonw has no standard streams. Supply UTF-8 streams before uvicorn config.
        stream = (logs / (args.action + '-output.log')).open('a', encoding='utf-8', buffering=1)
        sys.stdout = stream; sys.stderr = stream
        handler = RotatingFileHandler(logs / (args.action + '.log'), maxBytes=5_000_000, backupCount=3, encoding='utf-8')
        logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
        if args.action == 'service':
            from vault_rag.windows_native import Instance
            with Instance(config.directory, 'service') as instance:
                if not instance.primary: return
                from vault_rag.web_server import serve
                serve(instance=instance)
        elif args.action == 'tray':
            from vault_rag.windows_tray import run
            run(config)
        else:
            from vault_rag.service_control import control
            control(args.action, config)
    except Exception as error:
        logging.exception('Windows %s failed', args.action)
        if args.action not in ('service', 'tray'):
            show_error(str(error) + '\n日志：' + str(logs))
            raise SystemExit(2) from error  # tell the launcher the error was already shown
        raise


if __name__ == '__main__':main()
