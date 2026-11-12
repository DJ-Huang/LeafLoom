"""Send a JSON operation to the installed LeafLoom service on this machine."""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


def state_directory():
    override = os.environ.get('VAULT_RAG_HOME')
    if override:
        return Path(override).expanduser().resolve()
    home = Path.home()
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA') or home / 'AppData/Local') / 'VaultRag'
    if sys.platform == 'darwin':
        return home / 'Library/Application Support/VaultRag'
    return Path(os.environ.get('XDG_DATA_HOME', str(home / '.local/share'))) / 'VaultRag'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(operation, arguments):
    directory = state_directory()
    credential = (directory / 'leafloom-skill-token').read_text(encoding='utf-8').strip()
    config = directory / 'config.json'
    port = json.loads(config.read_text(encoding='utf-8')).get('port', 18080) if config.is_file() else 18080
    if not credential or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid local LeafLoom connection settings')
    url = f'http://127.0.0.1:{port}/api/leafloom/{operation}'
    body = json.dumps(arguments, ensure_ascii=False).encode('utf-8')
    headers = {'Authorization': 'Bearer ' + credential, 'Content-Type': 'application/json'}
    client = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with client.open(Request(url, data=body, headers=headers), timeout=180) as response:
            value = json.load(response)
    except HTTPError as error:
        with error:
            try:
                value = json.load(error)
            except ValueError:
                value = {'error': 'LeafLoom returned an unexpected HTTP response'}
        details = value if isinstance(value, dict) else {'detail': value}
        return {**details, 'ok': False, 'http_status': error.code}, 1
    return value, int(isinstance(value, dict) and value.get('ok') is False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', help='Operation from the LeafLoom skill references')
    parser.add_argument('arguments', nargs='?', default='{}', help='JSON object, or - to read UTF-8 JSON from stdin')
    options = parser.parse_args()
    try:
        # Windows PowerShell can prepend a UTF-8 BOM to a native stdin pipe.
        arguments = json.loads(sys.stdin.buffer.read().decode('utf-8-sig') if options.arguments == '-' else options.arguments)
        if not re.fullmatch(r'[a-z][a-z0-9-]*', options.operation) or not isinstance(arguments, dict):
            raise ValueError('Expected a LeafLoom operation and a JSON object')
        result, exit_code = request(options.operation, arguments)
    except FileNotFoundError:
        result, exit_code = {'ok': False, 'error': 'Open or update the local LeafLoom app to initialize the skill connection'}, 1
    except (URLError, TimeoutError):
        result, exit_code = {'ok': False, 'error': 'The local LeafLoom service did not respond. Check that it is running. Read back before retrying a write.'}, 1
    except (ValueError, OSError) as error:
        result, exit_code = {'ok': False, 'error': str(error)}, 1
    sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False) + '\n').encode('utf-8'))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
