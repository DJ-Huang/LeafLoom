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
import tempfile
import time
from urllib.parse import unquote, urlsplit

from vault_rag.local_state import atomic_write
from vault_rag.note_operations import NoteError
from vault_rag.platform_support import private_file_mode
from vault_rag.feishu_files import FeishuFiles


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


def run_cli(binary, args, *, profile='', content=None, timeout=45, output_limit=2 * 1024 * 1024,
            cwd=None, monitor=None):
    """No shell/shims; bounded concurrent pipe readers, with stdin for document text."""
    argv = [str(binary), *(['--profile=' + profile] if profile else []), *args]
    if os.name == 'nt' and len(subprocess.list2cmdline(argv)) > 30000:
        raise FeishuError('invalid_request', 'CLI arguments exceed the Windows limit; narrow the query or field map')
    env = {**os.environ, 'LARKSUITE_CLI_NO_UPDATE_NOTIFIER': '1', 'LARKSUITE_CLI_NO_SKILLS_NOTIFIER': '1'}
    try:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   shell=False, env=env, cwd=str(cwd or Path(binary).parent),
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
        deadline = time.monotonic() + timeout
        while True:
            if monitor:
                monitor()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            try:
                process.wait(timeout=min(.25, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    except subprocess.TimeoutExpired as error:
        process.kill(); process.wait()
        raise FeishuError('cli_timeout', 'lark-cli timed out; a write may have completed. Read the resource before retrying') from error
    except Exception:
        process.kill(); process.wait()
        raise
    finally:
        for thread in [*readers, writer]: thread.join(timeout=2)
    if overflow.is_set():
        raise FeishuError('output_limit', 'lark-cli output exceeded the limit; narrow the query before retrying')
    return process.returncode, *(bytes(data).decode('utf-8', errors='replace') for data in streams)


class Feishu:
    MANAGED_FLAGS = {'--as', '--profile', '--format', '--json', '--revision-id', '--yes',
                     '--help', '-h', '--version', '-v', '--print-schema', '--from-clipboard',
                     '--clipboard', '--watch', '--follow', '--stream', '--open-browser', '--jq',
                     '--access-token', '--user-access-token', '--tenant-access-token', '--refresh-token',
                     '--app-secret', '--client-secret', '--config-file', '--config-path'}

    def __init__(self, config):
        self.path = config.directory / 'feishu.json'
        self.lock = threading.RLock()
        self.options = {'enabled': False, 'binary': '', 'profile': ''}
        self.verification = {'state': 'disabled'}
        self.checked_binary = None
        self.discovery = {}
        self.cli_version = ''
        self.files = FeishuFiles(config)
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

    def _run(self, args, *, content=None, **kwargs):
        return run_cli(self._binary(), args, profile=self.options['profile'], content=content, **kwargs)

    def _compatible(self):
        binary = self._binary()
        stat = binary.stat()
        fingerprint = (str(binary), stat.st_mtime_ns, stat.st_size, self.options['profile'])
        if self.checked_binary == fingerprint: return
        self.discovery.clear()
        code, version, _ = self._run(['--version'])
        if code:
            raise FeishuError('cli_incompatible', 'Unable to identify lark-cli version')
        self.cli_version = version.strip()[:120]
        for command, flags in [(['--help'], ('schema', 'skills', 'Lark domains:')),
                               (['auth', 'status', '--help'], ('--json', '--verify'))]:
            code, out, _ = self._run(command)
            if code or any(flag not in out for flag in flags):
                raise FeishuError('cli_incompatible', 'This lark-cli lacks discovery interfaces; update it externally')
            self.discovery[tuple(command)] = out
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
        available, bridge_error = False, ''
        if self.options['enabled']:
            try:
                self._ready()
                available = True
            except (FeishuError, ValueError, OSError) as error:
                bridge_error = error.code if isinstance(error, FeishuError) else 'invalid_configuration'
        return {'ok': True, 'enabled': state['config']['enabled'], 'profile': state['config']['profile'],
                **state['verification'], 'cli_version': self.cli_version, 'bridge_available': available,
                'bridge_error': bridge_error}

    def _ready(self):
        if not self.options['enabled']: raise FeishuError('integration_disabled', 'Enable Feishu in LeafLoom settings')
        self._compatible()

    @staticmethod
    def _arg(name, value):
        return '--' + name + '=' + _text(value, name)

    def _safe(self, value, cwd=None):
        paths = (str(cwd) if cwd else '', str(self.path.parent), str(self._binary().parent))
        def clean(item):
            if isinstance(item, dict):
                return {k: clean(v) for k, v in item.items()}
            if isinstance(item, list):
                return [clean(v) for v in item]
            if isinstance(item, str):
                for path in paths:
                    if path:
                        for form in (path, path.replace('\\', '/'), path.replace('\\', '\\\\')):
                            item = item.replace(form, '[local]')
                item = re.sub(r'(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+', r'\1[redacted]', item)
                item = re.sub(r'(?i)((?:access_token|refresh_token|app_secret|client_secret)[\s\"\x27:=]+)[^\s\"\x27,}]+',
                              r'\1[redacted]', item)
            return item
        return clean(_clean(value))

    def _help(self, command):
        key = (*command, '--help')
        if key not in self.discovery:
            code, out, _ = self._run(list(key))
            if code:
                raise FeishuError('command_unavailable', 'CLI command help is unavailable')
            self.discovery[key] = out
        return self.discovery[key]

    def _domains(self):
        root = self._help([])
        section = root.partition('Lark domains:')[2].split('Agent tooling:')[0]
        return set(re.findall(r'^  ([a-z][a-z0-9_]*)\s{2,}', section, re.M))

    def _business(self, command):
        if not command or command[0] not in self._domains() | {'api'}:
            raise FeishuError('command_unavailable', 'Only business commands are available through MCP')
        if any(not re.fullmatch(r'\+?[A-Za-z][A-Za-z0-9_.\-]*', part) for part in command):
            raise ValueError('Invalid command path')
        # Local servers, arbitrary programs and credential commands are never business forwarding.
        blocked = {'serve', 'server', 'watch', 'listen', 'dev', 'exec', 'shell', 'run',
                   'login', 'logout', 'token', 'credentials', 'config', 'profile'}
        if any(part.lstrip('+') in blocked for part in command[1:]):
            raise FeishuError('command_unavailable', 'Interactive, credential and local service commands are unavailable')

    @staticmethod
    def _flags(help_text):
        flags = {}
        for line in help_text.splitlines():
            if not line.lstrip().startswith('-'):
                continue
            declaration = re.split(r'\s{2,}', line.strip(), maxsplit=1)[0]
            match = re.fullmatch(r'(?:(-[A-Za-z]),\s+)?(--[\w-]+)(?:\s+(\S+))?', declaration)
            if match:
                short, long, kind = match.groups()
                flags[long] = (long, bool(kind))
                if short:
                    flags[short] = (long, bool(kind))
        return flags

    def inspect(self, action, argv=None, path=''):
        with self.lock:
            self._ready()
            argv = argv or []
            if not isinstance(argv, list) or any(not isinstance(a, str) for a in argv):
                raise ValueError('argv must be a string array')
            if action == 'help':
                if argv:
                    self._business(argv)
                return {'ok': True, 'exit_code': 0, 'text': self._safe(self._help(argv))}
            if action == 'schema':
                if not re.fullmatch(r'[a-zA-Z0-9_.-]+', path):
                    raise ValueError('Use a dotted schema command path')
                self._business([path.split('.')[0]])
                args = ['schema', path]
            elif action in ('skills_list', 'skills_read'):
                if path and (not re.fullmatch(r'[a-zA-Z0-9_./-]+', path) or '..' in path.split('/') or path.startswith('/')):
                    raise ValueError('Invalid embedded skill path')
                args = ['skills', 'list' if action == 'skills_list' else 'read']
                if path:
                    skill, _, reference = path.partition('/')
                    args.append(skill)
                    if reference:
                        if action == 'skills_read':
                            args.append(reference)
                        else:
                            args[-1] = path
                elif action == 'skills_read':
                    raise ValueError('A skill path is required')
            else:
                raise ValueError('Unknown inspection action')
            code, out, err = self._run(args)
            return self._result(code, out, err, text=True)

    def _parse(self, argv):
        if not isinstance(argv, list) or not 2 <= len(argv) <= 256:
            raise ValueError('argv must contain a business command and its arguments')
        for arg in argv:
            _text(arg, 'argument', empty=True, maximum=512 * 1024)
        if argv[0] == 'api':
            if len(argv) < 3 or argv[1] not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD'):
                raise ValueError('Raw API requires an HTTP method and /open-apis/ path')
            parsed = urlsplit(argv[2])
            decoded = unquote(unquote(parsed.path))
            if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or
                    decoded != parsed.path or not decoded.startswith('/open-apis/') or
                    any(p in ('.', '..', '') for p in decoded.split('/')[2:]) or '\\' in decoded or
                    re.search(r'(?i)(?:^|/)(?:auth|authen|oauth|oauth2|token|access_token|refresh_token)(?:/|$)', decoded)):
                raise ValueError('Raw API path is unavailable or accesses credentials')
            command, rest = ['api'], argv[3:]
        else:
            end = next((i for i, a in enumerate(argv) if a.startswith('-')), len(argv))
            command, rest = argv[:end], argv[end:]
        self._business(command)
        help_text = self._help(command)
        flags = self._flags(help_text)
        options, normalized = {}, list(argv[:3] if command == ['api'] else command)
        i = 0
        while i < len(rest):
            flag, sep, value = rest[i].partition('=')
            if flag not in flags:
                raise ValueError('Unknown flag or positional argument; inspect current CLI help')
            canonical, takes_value = flags[flag]
            if canonical in self.MANAGED_FLAGS:
                raise ValueError('Identity, output, revision and confirmation flags are managed by LeafLoom')
            if takes_value:
                if not sep:
                    i += 1
                    if i >= len(rest):
                        raise ValueError('Missing flag value')
                    value = rest[i]
                normalized.append(canonical + '=' + value)
            else:
                if sep and value not in ('true', 'false'):
                    raise ValueError('Invalid boolean flag')
                value = value if sep else 'true'
                normalized.append(canonical + '=' + value)
            options.setdefault(canonical, []).append(value)
            i += 1
        if '--as' not in flags or '--format' not in flags:
            raise FeishuError('command_unavailable', 'Command does not support fixed identity and JSON output')
        if command == ['api']:
            risk = 'high-risk-write'
        elif len(command) == 3 and not command[1].startswith('+'):
            key = ('schema', '.'.join(command))
            if key not in self.discovery:
                code, out, _ = self._run(list(key))
                try:
                    schema = json.loads(out) if not code else {}
                except ValueError:
                    schema = {}
                self.discovery[key] = schema
            schema = self.discovery[key]
            risk = schema.get('_meta', {}).get('risk') if isinstance(schema, dict) else None
        else:
            match = re.search(r'^Risk:\s*(read|write|high-risk-write)\b', help_text, re.M)
            risk = match[1] if match else None
        if risk not in ('read', 'write', 'high-risk-write'):
            raise FeishuError('unknown_risk', 'CLI did not provide a recognized command risk')
        return command, normalized, options, flags, risk

    def _revision(self, document, expected_revision):
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError('Use the positive document revision_id returned by fetch')
        observed = self._json(['docs', '+fetch', self._arg('doc', document), '--scope=outline',
                               '--max-depth=1', '--detail=simple', '--as=user', '--format=json'])
        current = observed.get('data', {}).get('document', {}).get('revision_id')
        if type(current) is not int or current < 1:
            raise FeishuError('invalid_cli_response', 'Unable to verify current document revision')
        if current != expected_revision:
            raise FeishuError('write_conflict', 'Document changed; fetch again before editing', current_revision=current)

    def _result(self, code, out, err, *, text=False, cwd=None):
        raw = out if code == 0 else err or out
        try:
            data = json.loads(raw)
        except ValueError:
            if text and code == 0:
                return {'ok': True, 'exit_code': code, 'text': self._safe(raw, cwd)}
            raise FeishuError('invalid_cli_response', 'CLI returned unstructured output; details withheld')
        data = self._safe(data, cwd)
        failed = code != 0 or isinstance(data, dict) and data.get('ok') is False
        result = {'ok': not failed, 'exit_code': code, 'data': data}
        if failed:
            error = self._failure(data if isinstance(data, dict) else {})
            result.update(error_code=error.code, error=str(error), **error.details)
        elif isinstance(data, dict):
            payload = data.get('data')
            if isinstance(payload, dict) and (payload.get('result') in ('partial_success', 'failed') or
                    payload.get('ignored_fields') or isinstance(payload.get('record'), dict) and payload['record'].get('ignored_fields')):
                result.update(ok=False, error_code='partial_write', error='CLI reported an incomplete write; read before retrying',
                              error_source='feishu_cli')
            if data.get('identity') not in (None, 'user'):
                raise FeishuError('identity_mismatch', 'CLI did not use the requested user identity')
        return result

    def execute(self, argv, *, write=False, stdin=None, input_files=None, confirm=False,
                expected_revision=None, owner, source_check, require_high_risk):
        with self.lock:
            self._ready()
            command, args, options, flags, risk = self._parse(argv)
            if type(confirm) is not bool:
                raise ValueError('confirm must be a boolean')
            if not write and risk != 'read':
                raise FeishuError('permission_denied', 'Use the write tool for this command', error_source='leafloom_mcp')
            if write and risk == 'read':
                raise ValueError('Use feishu_cli_read for this command')
            if risk == 'high-risk-write':
                require_high_risk()
                if not confirm:
                    raise FeishuError('confirmation_required', 'Obtain explicit confirmation for this operation, then pass confirm=true')
                if '--yes' in flags:
                    args.append('--yes')
            if stdin is not None:
                _text(stdin, 'stdin', empty=True, maximum=512 * 1024)
            def single(name):
                values = options.get(name, [])
                if len(values) != 1:
                    raise ValueError('Provide exactly one ' + name)
                return values[0]
            if command == ['docs', '+update']:
                self._revision(single('--doc'), expected_revision)
                args.append('--revision-id=' + str(expected_revision))
            if command == ['api'] and argv[1] not in ('GET', 'HEAD'):
                doc = re.match(r'^/open-apis/docx/v\d+/documents/([^/]+)(?:/|$)', argv[2])
                if doc:
                    self._revision(doc[1], expected_revision)
            with tempfile.TemporaryDirectory(prefix='job-', dir=self.files.root) as directory:
                job = Path(directory).resolve()
                inputs, sources = self.files.prepare(owner, source_check, job, input_files or {})
                # Validate generic CLI file flags and @file references before native execution.
                for flag, values in options.items():
                    for value in values:
                        if value.startswith('@'):
                            p = self.files.job_path(job, value[1:])
                            if p not in inputs:
                                raise ValueError('@file must reference a supplied input file')
                        elif flag in ('--file', '--output', '--output-dir', '--input', '--input-file', '--output-file'):
                            path = value.split('=', 1)[-1] if flag == '--file' else value
                            if path == '-' and flag == '--file':
                                continue
                            p = self.files.job_path(job, path)
                            if flag in ('--file', '--input', '--input-file') and p not in inputs:
                                raise ValueError('File input must reference a supplied input file')
                            if flag.startswith('--output'):
                                p.parent.mkdir(parents=True, exist_ok=True)
                file_mode = bool(inputs) or any('file' in flag or 'output' in flag for flag in options)
                code, out, err = self._run([*args, '--as=user', '--format=json'], content=stdin,
                    cwd=job, timeout=300 if file_mode else 45,
                    monitor=lambda: self.files.scan(owner, job, inputs))
                outputs = self.files.scan(owner, job, inputs)
                registered = []
                try:
                    for p in outputs:
                        registered.append({**self.files.register(owner, p, sources), 'path': p.relative_to(job).as_posix()})
                    result = self._result(code, out, err, cwd=job)
                except Exception:
                    for item in registered:
                        self.files.discard(item['file_id'])
                    raise
                result.update(risk=risk, files=registered)
                return result
