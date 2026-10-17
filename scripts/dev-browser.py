"""Run the real browser UI/backend with explicit, separate development state.

Start Vite separately on 127.0.0.1. Use --loopback-ui only when the development
browser cannot open named .localhost origins. Desktop launchers stay unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MARKER = '.leafloom-browser-dev.json'


def port_number(value):
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError('Port must be an integer from 1024 to 65535') from None
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError('Port must be an integer from 1024 to 65535')
    return port


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument('--home', type=Path, required=True,
                       help='Dedicated new/empty developer state directory; never use installed app state')
    value.add_argument('--port', type=port_number, default=36229, help='Loopback backend port (default: 36229)')
    value.add_argument('--dev-server', default='http://127.0.0.1:5173',
                       help='Vite HTTP 127.0.0.1 origin (default: http://127.0.0.1:5173)')
    value.add_argument('--loopback-ui', action='store_true',
                       help='Use literal localhost for the UI; HTML projects keep separate named origins')
    return value


def prepare_config(home, port, *, loopback_ui=False, dev_server='http://127.0.0.1:5173'):
    from vault_rag.dev_frontend import DevFrontend
    from vault_rag.local_state import LocalConfig, atomic_write

    port = port_number(port)
    frontend = DevFrontend(dev_server)  # Validate before creating/changing state.
    if port == urlsplit(frontend.origin).port:
        raise ValueError('Backend and Vite must use different ports')
    home = Path(home).expanduser().resolve()
    expected = {'version': 1, 'port': port, 'ui': 'localhost' if loopback_ui else 'named'}
    marker = home / MARKER
    if home.exists():
        if not home.is_dir():
            raise ValueError('Developer home must be a directory')
        if marker.is_file() and not marker.is_symlink():
            if json.loads(marker.read_text(encoding='utf-8')) != expected:
                raise ValueError('Developer home uses a different port or UI mode; use a new home and browser profile')
        elif any(home.iterdir()):
            raise ValueError('Refusing existing unmarked state; choose a new or empty developer home')
    config = LocalConfig(home)
    if not marker.exists():
        atomic_write(marker, (json.dumps(expected, indent=2) + '\n').encode('utf-8'))
    if config.data.get('port') != port:
        config.save({'port': port})
    return config


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        config = prepare_config(args.home, args.port, loopback_ui=args.loopback_ui,
                                dev_server=args.dev_server)
    except (ValueError, OSError, argparse.ArgumentTypeError) as error:
        parser().error(str(error))
    from vault_rag.web_server import create_app, create_server
    app = create_app(config, dev_server=args.dev_server, dev_ui_loopback=args.loopback_ui)
    print(f'LeafLoom browser development: {app.state.websites.ui_origin}/', flush=True)
    print(f'Dedicated state: {config.directory}', flush=True)
    print('Use a dedicated browser profile. Keep this home, port and UI mode together. '
          'Ctrl+C stops the backend; stop Vite separately.', flush=True)
    if args.loopback_ui:
        print('Named HTML project origins remain isolated and may still be unavailable in this browser. '
              'Do not disable browser security to open them.', flush=True)
    create_server(app, port=args.port).run()


if __name__ == '__main__':
    main()
