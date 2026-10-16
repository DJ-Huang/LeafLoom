"""Optional, local lark-cli adapter. Credentials and login belong to the CLI."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading

from vault_rag.local_state import atomic_write
from vault_rag.note_operations import NoteError
from vault_rag.platform_support import private_file_mode


class FeishuError(NoteError):
    pass


def _text(value, name, *, empty=False, maximum=4096):
    if not isinstance(value, str) or '\0' in value or len(value.encode('utf-8')) > maximum or (not empty and not value.strip()):
        raise ValueError(f'Invalid {name}')
    return value


def _clean(value):
    # Resource tokens (base_token, document_token, page_token) are public API coordinates.
    secrets = {'access_token', 'refresh_token', 'app_secret', 'client_secret', 'authorization',
               'accesstoken', 'refreshtoken', 'appsecret', 'clientsecret'}
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k.lower() not in secrets and k != '_notice'}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def run_cli(binary, args, *, profile='', content=None, timeout=45, output_limit=2 * 1024 * 1024):
    """No shell/shims; bounded concurrent pipe readers, with stdin for document text."""
    argv = [str(binary), *(['--profile=' + profile] if profile else []), *args]
    if os.name == 'nt' and len(subprocess.list2cmdline(argv)) > 30000:
        raise FeishuError('invalid_request', 'CLI arguments exceed the Windows limit; narrow the query or field map')
    env = {**os.environ, 'LARKSUITE_CLI_NO_UPDATE_NOTIFIER': '1', 'LARKSUITE_CLI_NO_SKILLS_NOTIFIER': '1'}
    try:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   shell=False, env=env, cwd=str(Path(binary).parent),
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except OSError as error:
        raise FeishuError('cli_unavailable', 'The native lark-cli executable could not be started') from error
    streams = [bytearray(), bytearray()]
    overflow = threading.Event()
    def read(pipe, target):
        try:
            while chunk := pipe.read(8192):
                if len(target) + len(chunk) > output_limit:
                    overflow.set(); process.kill(); break
                target.extend(chunk)
        finally:
            pipe.close()
    def write():
        try:
            if content is not None:
                process.stdin.write(content.encode('utf-8'))
        except (BrokenPipeError, OSError):
            pass
        finally:
            process.stdin.close()
    readers = [threading.Thread(target=read, args=(pipe, data), daemon=True)
               for pipe, data in zip((process.stdout, process.stderr), streams)]
    for reader in readers: reader.start()
    writer = threading.Thread(target=write, daemon=True); writer.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        process.kill(); process.wait()
        raise FeishuError('cli_timeout', 'lark-cli timed out; a write may have completed. Read the resource before retrying') from error
    finally:
        for thread in [*readers, writer]: thread.join(timeout=2)
    if overflow.is_set():
        raise FeishuError('output_limit', 'lark-cli output exceeded the limit; narrow the query before retrying')
    return process.returncode, *(bytes(data).decode('utf-8', errors='replace') for data in streams)


class Feishu:
    COMMANDS = {
        ('auth', 'status'): ('--json', '--verify'),
        ('docs', '+search'): ('--query', '--page-size', '--page-token'),
        ('docs', '+fetch'): ('--doc', '--detail', '--scope', '--max-depth'),
        ('docs', '+create'): ('--content', '--title', '--doc-format'),
        ('docs', '+update'): ('--content', '--command', '--pattern', '--revision-id', '--doc-format'),
        ('base', '+url-resolve'): ('--url',),
        ('base', '+table-list'): ('--offset', '--limit'),
        ('base', '+field-list'): ('--table-id', '--offset', '--limit'),
        ('base', '+record-list'): ('--filter-json', '--sort-json', '--offset', '--limit', '--field-id'),
        ('base', '+record-get'): ('--record-id',),
        ('base', '+record-upsert'): ('--json', '--record-id'),
    }

    def __init__(self, config):
        self.path = config.directory / 'feishu.json'
        self.lock = threading.RLock()
        self.options = {'enabled': False, 'binary': '', 'profile': ''}
        self.verification = {'state': 'disabled'}
        self.checked_binary = None
        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            self.options.update({k: saved.get('config', {}).get(k, v) for k, v in self.options.items()})
            self.verification = saved.get('verification', self.verification)

    def _save(self):
        atomic_write(self.path, json.dumps(self.status(), ensure_ascii=False).encode('utf-8'))
        private_file_mode(self.path)

    def status(self):
        with self.lock:
            return {'config': dict(self.options), 'verification': dict(self.verification)}

    def configure(self, values):
        if not isinstance(values, dict) or set(values) - self.options.keys():
            raise ValueError('Invalid Feishu settings')
        with self.lock:
            options = {**self.options, **values}
            if not isinstance(options['enabled'], bool): raise ValueError('Invalid enabled setting')
            _text(options['binary'], 'CLI executable', empty=True)
            _text(options['profile'], 'CLI profile', empty=True, maximum=80)
            if options['profile'] and not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', options['profile']):
                raise ValueError('Invalid CLI profile')
            if options != self.options:
                self.options = options
                self.verification = {'state': 'unchecked' if options['enabled'] else 'disabled'}
                self.checked_binary = None
                self._save()
            return self.status()

    def _binary(self):
        selected = self.options['binary']
        if selected:
            path = Path(selected).expanduser()
            if not path.is_absolute(): raise ValueError('CLI executable must be an absolute path')
            candidates = [path]
        else:
            found = shutil.which('lark-cli')
            candidates = [Path(found)] if found else []
            # Resolve the official npm layout, never execute .cmd/.ps1 wrappers.
            for directory in [Path(found).parent if found else None,
                              Path(os.environ['APPDATA']) / 'npm' if os.environ.get('APPDATA') else None]:
                if directory:
                    candidates.append(directory / 'node_modules/@larksuite/cli/bin' / ('lark-cli.exe' if os.name == 'nt' else 'lark-cli'))
            if os.name != 'nt' and found:
                candidates.append(Path(found).resolve().parents[1] / 'bin/lark-cli')
        for path in candidates:
            if path.resolve().suffix.lower() in ('.cmd', '.bat', '.ps1', '.js'): continue
            if os.name == 'nt' and path.suffix.lower() != '.exe': continue
            if path.is_file() and (os.name == 'nt' or os.access(path, os.X_OK)):
                return path.resolve()
        raise FeishuError('cli_not_installed', 'Install lark-cli externally or select its native executable')

    def _run(self, args, *, content=None):
        return run_cli(self._binary(), args, profile=self.options['profile'], content=content)

    def _compatible(self):
        binary = self._binary()
        stat = binary.stat()
        fingerprint = (str(binary), stat.st_mtime_ns, stat.st_size, self.options['profile'])
        if self.checked_binary == fingerprint: return
        for command, flags in self.COMMANDS.items():
            code, out, _ = self._run([*command, '--help'])
            required = flags if command[0] == 'auth' else (*flags, '--as', '--format')
            if code or any(flag not in out for flag in required):
                raise FeishuError('cli_incompatible', 'This lark-cli lacks required commands or flags; update it externally')
        self.checked_binary = fingerprint

    @staticmethod
    def _failure(payload):
        error = payload.get('error', {})
        if not isinstance(error, dict): error = {}
        diagnostic = ' '.join(str(error.get(k, '')) for k in ('type', 'subtype', 'message')).lower()
        code = ('not_configured' if error.get('type') == 'config' or any(x in diagnostic for x in ('not_configured', 'not configured', 'app_id', 'app_secret', 'app id', 'app secret', 'config_missing')) else
                'not_logged_in' if any(x in diagnostic for x in ('token_missing', 'not_logged', 'login_required', 'no user')) else
                'login_expired' if any(x in diagnostic for x in ('expired', 'invalid_token', 'token_invalid')) else
                'network_error' if any(x in diagnostic for x in ('network', 'timeout', 'connection', 'dns')) else
                'permission_denied' if error.get('type') in ('authorization', 'policy') or any(x in diagnostic for x in ('permission', 'scope', 'forbidden', 'access_denied')) else
                'write_conflict' if any(x in diagnostic for x in ('conflict', 'revision', 'stale_version')) else
                'confirmation_required' if 'confirmation_required' in diagnostic else
                'invalid_request' if error.get('type') == 'validation' else 'cli_failed')
        details = error.get('details', {})
        details = details if isinstance(details, dict) else {}
        scopes = error.get('missing_scopes', details.get('missing_scopes', payload.get('missing_scopes', [])))
        scopes = [s for s in scopes if isinstance(s, str) and re.fullmatch(r'[\w:.-]{1,160}', s)] if isinstance(scopes, list) else []
        upstream = error.get('code')
        subtype = error.get('subtype', '')
        if str(upstream) == '800010116':
            return FeishuError('invalid_request', 'The table reference resolves to a document block, not a Base table',
                               error_source='feishu_cli', upstream_code=upstream, missing_scopes=[],
                               hint='List Base tables and use a returned table ID; do not copy an unverified table query parameter from the URL')
        return FeishuError(code, 'Feishu operation failed; check CLI login and resource permissions externally',
                           error_source='feishu_cli',
                           missing_scopes=scopes,
                           cli_error_subtype=subtype if isinstance(subtype, str) and re.fullmatch(r'[\w.-]{1,80}', subtype) else '',
                           upstream_code=upstream if isinstance(upstream, (int, str)) and re.fullmatch(r'[\w.-]{1,80}', str(upstream)) else None)

    def _json(self, args, *, content=None):
        code, out, err = self._run(args, content=content)
        try:
            value = json.loads(out if code == 0 else err or out)
        except (ValueError, TypeError) as error:
            raise FeishuError('invalid_cli_response', 'lark-cli did not return a JSON response') from error
        if not isinstance(value, dict): raise FeishuError('invalid_cli_response', 'Expected a CLI JSON object')
        if code or value.get('ok') is False:
            raise self._failure(value)
        if value.get('ok') is not True:
            raise FeishuError('invalid_cli_response', 'Expected a CLI success envelope')
        if value.get('identity') != 'user':
            raise FeishuError('identity_mismatch', 'lark-cli did not use the requested user identity')
        data = value.get('data', {})
        result = data.get('result') if isinstance(data, dict) else None
        ignored = data.get('ignored_fields') if isinstance(data, dict) else None
        record = data.get('record') if isinstance(data, dict) else None
        if isinstance(record, dict): ignored = ignored or record.get('ignored_fields')
        if result in ('partial_success', 'failed') or ignored:
            raise FeishuError('partial_write', 'Feishu reported an incomplete write; read the resource before retrying',
                               result=result or 'ignored_fields')
        return _clean(value)

    def verify(self):
        with self.lock:
            state = {'state': 'disabled', 'verified_at': dt.datetime.now(dt.timezone.utc).isoformat()}
            if self.options['enabled']:
                try:
                    code, version, _ = self._run(['--version'])
                    if code: raise FeishuError('cli_incompatible', 'Unable to identify lark-cli version')
                    state['version'] = version.strip()[:120]
                    self._compatible()
                    code, out, err = self._run(['auth', 'status', '--json', '--verify'])
                    try: value = json.loads(out if code == 0 else err or out)
                    except ValueError: raise FeishuError('invalid_cli_response', 'Invalid CLI account status')
                    if not isinstance(value, dict): raise FeishuError('invalid_cli_response', 'Invalid CLI account status')
                    if code or value.get('ok') is False: raise self._failure(value)
                    identities = value.get('identities', {})
                    user = identities.get('user', {}) if isinstance(identities, dict) else None
                    if not isinstance(user, dict): raise FeishuError('invalid_cli_response', 'Invalid CLI user status')
                    if not value.get('appId'):
                        state['state'] = 'not_configured'
                    elif user.get('available') is not True:
                        diagnostic = str(user.get('tokenStatus', '')) + str(user.get('status', '')) + str(user.get('message', ''))
                        state['state'] = 'login_expired' if re.search(r'expired|invalid|revoked', diagnostic, re.I) else 'not_logged_in'
                    elif user.get('verified') is not True:
                        diagnostic = str(user.get('tokenStatus', '')) + str(user.get('status', '')) + str(user.get('message', ''))
                        state['state'] = 'network_error' if re.search(r'network|timeout|connection|dns|no such host|dial tcp', diagnostic, re.I) else 'login_expired'
                    else:
                        state.update(state='connected', identity='user',
                                     user_name=str(user.get('userName', ''))[:200],
                                     open_id=str(user.get('openId', ''))[:200])
                except FeishuError as error:
                    state['state'] = {'cli_not_installed': 'not_installed', 'cli_unavailable': 'not_installed',
                                      'cli_incompatible': 'incompatible', 'cli_timeout': 'network_error'}.get(error.code, error.code)
                except (ValueError, OSError):
                    state['state'] = 'invalid_configuration'
            self.verification = state
            self._save()
            return self.status()

    def account_status(self, verify=False):
        state = self.verify() if verify else self.status()
        return {'ok': True, 'enabled': state['config']['enabled'], 'profile': state['config']['profile'],
                **state['verification']}

    def _ready(self):
        if not self.options['enabled']: raise FeishuError('integration_disabled', 'Enable Feishu in LeafLoom settings')
        self._compatible()

    @staticmethod
    def _arg(name, value):
        return '--' + name + '=' + _text(value, name)

    def docs_read(self, action, document='', query='', limit=15, page_token=''):
        with self.lock:
            self._ready()
            if action == 'search':
                if type(limit) is not int or not 1 <= limit <= 20: raise ValueError('Search limit must be 1-20')
                args = ['docs', '+search', self._arg('query', query), '--page-size=' + str(limit)]
                if page_token: args.append(self._arg('page-token', page_token))
            elif action == 'fetch':
                args = ['docs', '+fetch', self._arg('doc', document), '--detail=full']
            else: raise ValueError('Unknown document read action')
            return self._json([*args, '--as=user', '--format=json'])

    def docs_write(self, action, content, document='', title='', expected_revision=None, old_text=''):
        with self.lock:
            self._ready()
            _text(content, 'content', empty=True, maximum=512 * 1024)
            if action == 'create':
                args = ['docs', '+create', self._arg('title', title)]
            elif action in ('append', 'replace_text'):
                if type(expected_revision) is not int or expected_revision < 1:
                    raise ValueError('Use the document revision_id returned by fetch')
                # The remote update endpoint can accept stale revision_id values.
                # Check current metadata ourselves before sending any mutation.
                # This is a preflight guard, not a cross-client atomic CAS.
                observed = self._json(['docs', '+fetch', self._arg('doc', document), '--scope=outline',
                                       '--max-depth=1', '--detail=simple', '--as=user', '--format=json'])
                current = observed.get('data', {}).get('document', {}).get('revision_id')
                if type(current) is not int or current < 1:
                    raise FeishuError('invalid_cli_response', 'Unable to verify current document revision')
                if current != expected_revision:
                    raise FeishuError('write_conflict', 'Document changed; fetch the current revision before editing',
                                       current_revision=current)
                args = ['docs', '+update', self._arg('doc', document), '--revision-id=' + str(expected_revision),
                        '--command=' + ('append' if action == 'append' else 'str_replace')]
                if action == 'replace_text': args.append(self._arg('pattern', old_text))
            else: raise ValueError('Unknown document write action')
            return self._json([*args, '--doc-format=markdown', '--content=-', '--as=user', '--format=json'], content=content)

    def base_read(self, action, base_token='', table_id='', url='', record_id='', limit=50, offset=0,
                  filter=None, sort=None, fields=None):
        with self.lock:
            self._ready()
            commands = {'resolve': '+url-resolve', 'tables': '+table-list', 'fields': '+field-list',
                        'records': '+record-list', 'get_record': '+record-get'}
            if action not in commands: raise ValueError('Unknown Base read action')
            args = ['base', commands[action]]
            if action == 'resolve': args.append(self._arg('url', url))
            else:
                args.append(self._arg('base-token', base_token))
                if action != 'tables': args.append(self._arg('table-id', table_id))
                if action == 'get_record': args.append(self._arg('record-id', record_id))
                else:
                    if type(limit) is not int or not 1 <= limit <= (100 if action == 'tables' else 200): raise ValueError('Invalid page limit')
                    if type(offset) is not int or offset < 0: raise ValueError('Invalid page offset')
                    args.extend(['--limit=' + str(limit), '--offset=' + str(offset)])
            if action == 'records':
                if filter is not None:
                    if not isinstance(filter, dict): raise ValueError('filter must be an object')
                    args.append('--filter-json=' + json.dumps(filter, ensure_ascii=False, allow_nan=False))
                if sort is not None:
                    if not isinstance(sort, list): raise ValueError('sort must be an array')
                    args.append('--sort-json=' + json.dumps(sort, ensure_ascii=False, allow_nan=False))
            if action in ('records', 'get_record'):
                for field in fields or []: args.append(self._arg('field-id', field))
            result = self._json([*args, '--as=user', '--format=json'])
            if action in ('tables', 'fields', 'records'):
                data = result.get('data', {})
                if not isinstance(data, dict): raise FeishuError('invalid_cli_response', 'Invalid Base response')
                # Base v3 records use a cell matrix in data.data, paired with
                # record_id_list/fields; tables and fields use object arrays.
                rows = data.get(action, data.get('items', data.get('data', []) if action == 'records' else []))
                if not isinstance(rows, list): raise FeishuError('invalid_cli_response', 'Invalid Base rows')
                total = data.get('total')
                more = data.get('has_more')
                if more is None:
                    more = offset + len(rows) < total if type(total) is int else len(rows) == limit
                data.update(has_more=bool(more), next_offset=offset + len(rows) if more and rows else None)
            return result

    def base_write(self, action, base_token, table_id, fields, record_id=''):
        with self.lock:
            self._ready()
            if action not in ('create_record', 'update_record'): raise ValueError('Unknown Base write action')
            if not isinstance(fields, dict) or not fields: raise ValueError('fields must be a non-empty field map')
            # Read every schema page; never infer writable fields from one partial page.
            available = {}
            offset = 0
            for _ in range(100):
                schema = self.base_read('fields', base_token, table_id, limit=200, offset=offset)
                data = schema.get('data', {})
                rows = data.get('fields', data.get('items', []))
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise FeishuError('invalid_cli_response', 'Unrecognized Base field schema')
                for row in rows:
                    for key in ('field_id', 'field_name', 'id', 'name'):
                        if isinstance(row.get(key), str): available[row[key]] = row
                if not data.get('has_more'): break
                if not rows: raise FeishuError('invalid_cli_response', 'Base schema pagination did not advance')
                offset += len(rows)
            else: raise FeishuError('output_limit', 'Base field schema exceeds the pagination limit')
            seen = set()
            for key in fields:
                row = available.get(key)
                if row is None: raise ValueError('Unknown Base field; read the current schema')
                identity = row.get('field_id', row.get('id', key))
                if identity in seen: raise ValueError('Duplicate field name and ID')
                seen.add(identity)
                kind = row.get('type', row.get('field_type'))
                if kind not in ('text', 'number', 'select', 'multiselect', 'datetime', 'checkbox',
                                'user', 'group_chat', 'link', 'location', 'phone', 'url',
                                1, 2, 3, 4, 5, 7, 11, 13, 15, 18, 22, 23) or row.get('is_readonly') or row.get('readonly'):
                    raise ValueError('System, computed and attachment fields are not writable through this tool')
                if kind in ('select', 'multiselect', 3, 4):
                    properties = row.get('property') or {}
                    options = row.get('options', properties.get('options', []) if isinstance(properties, dict) else [])
                    allowed = {option.get('name', option.get('id')) for option in options if isinstance(option, dict)} if isinstance(options, list) else set()
                    values = fields[key] if isinstance(fields[key], list) else [fields[key]]
                    if any(value is not None and (not isinstance(value, str) or value not in allowed) for value in values):
                        raise ValueError('Select values must use existing schema options; adding options is not supported')
            payload = json.dumps(fields, ensure_ascii=False, allow_nan=False)
            _text(payload, 'fields', maximum=16 * 1024)
            args = ['base', '+record-upsert', self._arg('base-token', base_token), self._arg('table-id', table_id), '--json=' + payload]
            if action == 'update_record': args.append(self._arg('record-id', record_id))
            elif record_id: raise ValueError('create_record must not specify record_id')
            return self._json([*args, '--as=user', '--format=json'])
