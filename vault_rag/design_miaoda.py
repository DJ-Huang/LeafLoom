"""Page-scoped Design Studio publication to a dedicated Miaoda frontend app.

A job is journaled before remote writes. Interrupted or ambiguous operations are
never replayed automatically. Only registered repositories with a verified head
may be updated, and all git operations use a private checkout.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from vault_rag.local_state import ConflictError, atomic_write, relative
from vault_rag.design_presenter import audience_document
from vault_rag.design_export_selection import select_export
from vault_rag.feishu import FeishuError

TEMPLATE = Path(__file__).parent / 'design_assets' / 'miaoda'
RUNTIME = Path(__file__).parent / 'design_assets' / 'studio'
APP_ID = re.compile(r'^app_[A-Za-z0-9]+$')
TERMINAL = {'completed', 'failed', 'interrupted', 'awaiting_approval'}
# Reviewed original HMIRP course and its platform-generated dependency upgrade.
# A different legacy revision requires inspection rather than silent adoption.
LEGACY_COURSE_REVISIONS = frozenset({'f72a967f6f49bb195cb5b8034eb7900358badecc', '262836031fde478bf03f513ae2c24c1ab442fa8f'})


class GitAuthError(RuntimeError):
    pass


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())


def _git(repo, *args, timeout=180):
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0'}
    try:
        result = subprocess.run(['git', *args], cwd=repo, env=env, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError('Git unavailable or timed out; inspect the application before retrying') from error
    if result.returncode:
        if re.search(r'authentication failed|could not read username|credential|\b401\b|\b403\b', result.stderr, re.I):
            raise GitAuthError('Git authentication failed; refresh the Miaoda repository credentials')
        raise RuntimeError('Git operation failed; check credentials or remote changes before retrying')
    return result.stdout.strip()


def _destination(repo, name):
    """Never follow repository-supplied symlinks while replacing course files."""
    path = repo
    for part in Path(name).parts:
        if part in ('', '.', '..'):
            raise ValueError('Invalid application path')
        path = path / part
        if path.is_symlink():
            raise ValueError('The application contains a symbolic link in a course path')
    if not path.resolve().is_relative_to(repo.resolve()):
        raise ValueError('The application course path escapes its checkout')
    return path


def _tracked_files(repo):
    """Capture the complete staged Git tree except for our manifest itself."""
    result = {}
    for entry in _git(repo, 'ls-files', '--stage', '-z').split('\0'):
        if not entry:
            continue
        try:
            fields, name = entry.split('\t', 1)
            mode, object_id, stage = fields.split(' ')
        except ValueError as error:
            raise ValueError('Unable to verify the application file inventory') from error
        if stage != '0' or mode not in ('100644', '100755', '120000') or not re.fullmatch(r'[a-f0-9]{40,64}', object_id):
            raise ValueError('The application contains unsupported Git entries')
        if not name or name.startswith('/') or '\\' in name or '..' in PurePosixPath(name).parts:
            raise ValueError('The application contains an invalid Git path')
        if name != 'public/leafloom-course.json':
            result[name] = [mode, object_id]
    return result


def _verify_association(repo, head, project_id):
    if head in LEGACY_COURSE_REVISIONS:
        return
    manifest = _destination(repo, 'public/leafloom-course.json')
    try:
        value = json.loads(manifest.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise ConflictError('This course app has unrecognized remote changes; inspect it before association') from error
    recorded = value.get('tracked_files') if isinstance(value, dict) else None
    if not isinstance(value, dict) or value.get('version') != 2 or value.get('project_id') != project_id or not isinstance(recorded, dict) or not recorded or recorded != _tracked_files(repo):
        raise ConflictError('This course app has unrecognized remote changes; inspect it before association')


def _rewrite(value, urls, base=''):
    """Replace exact project paths without corrupting unrelated text or IDs."""
    import posixpath
    patterns = {}
    def walk(item, current):
        if isinstance(item, dict):
            nested = item.get('basePath', current)
            nested = nested if isinstance(nested, str) else current
            return {key: walk(child, nested) for key, child in item.items()}
        if isinstance(item, list):
            return [walk(child, current) for child in item]
        if not isinstance(item, str) or not urls:
            return item
        if current not in patterns:
            refs = {}
            for path, url in urls.items():
                for ref in ('__STUDIO_ASSET__/' + path, './' + path, '/' + path, path):
                    refs.setdefault(ref, url)
                if current:
                    directory = posixpath.dirname(current) if not current.endswith('/') and '.' in posixpath.basename(current) else current
                    refs.setdefault(posixpath.relpath(path, directory or '.'), url)
            expression = '|'.join(re.escape(ref) for ref in sorted(refs, key=len, reverse=True))
            patterns[current] = (re.compile(r'(?<![\w./-])(?:' + expression + r')(?![\w./-])'), refs)
        pattern, refs = patterns[current]
        return pattern.sub(lambda match: refs[match.group(0)], item)
    return walk(value, base)


def _remove_previous_text_assets(repo, project_id):
    """Remove only text resources recorded by an earlier workbench publication."""
    manifest = _destination(repo, 'public/leafloom-course.json')
    if not manifest.exists():
        return
    try:
        value = json.loads(manifest.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise ValueError('The previous course manifest is invalid') from error
    if not isinstance(value, dict) or value.get('project_id') != project_id:
        raise ValueError('The previous course manifest belongs to another project')
    names = value.get('generated_assets', [])
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise ValueError('The previous course asset manifest is invalid')
    reserved = {'course.html', 'course-data.js', 'course-runtime.js', 'course-runtime.css', 'leafloom-course.json'}
    for name in names:
        if not name or name.startswith('/') or '\\' in name or name in reserved or Path(name).suffix.lower() not in ('.js', '.mjs', '.css', '.html', '.htm', '.json', '.svg'):
            raise ValueError('The previous course asset manifest contains an invalid path')
        target = _destination(repo, 'public/' + name)
        if target.exists():
            if not target.is_file():
                raise ValueError('A previous course asset is not a file')
            target.unlink()


class MiaodaPublisher:
    def __init__(self, studio, feishu):
        self.studio, self.workspace = studio, studio.workspace
        self.config, self.files, self.feishu = studio.config, studio.files, feishu
        self.lock = threading.RLock()
        self.release_lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='miaoda-publish')
        self.active = set()

    def _state(self, *parts):
        return self.files.state_path('design-studio', 'miaoda', *parts)

    def _load(self, name, default):
        path = self._state(name)
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

    def _save_job(self, job):
        _write(self._state('jobs', job['job_id'] + '.json'), job)

    def _job(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r'[a-f0-9]{32}', job_id):
            raise ValueError('Invalid publishing job')
        path = self._state('jobs', job_id + '.json')
        if not path.is_file():
            raise ValueError('Publishing job not found')
        job = json.loads(path.read_text(encoding='utf-8'))
        if job['root'] != str(self.config.root):
            raise ConflictError('Connected folder changed')
        if job['status'] in ('queued', 'running') and job_id not in self.active:
            job.update(status='interrupted', last_stage=job['stage'], error='Publishing was interrupted. Inspect the remote app before starting another publication.')
            self._save_job(job)
        return job

    def _step(self, job, stage, **values):
        with self.lock:
            if job['root'] != str(self.config.root):
                raise ConflictError('Connected folder changed')
            job.update(stage=stage, **values)
            self._save_job(job)

    def _cli(self, args, *, cwd=None, timeout=300):
        with self.feishu.lock:
            self.feishu._ready()
            code, out, err = self.feishu._run([*args, '--as=user', '--format=json'], cwd=cwd, timeout=timeout)
            value = self.feishu._result(code, out, err, cwd=cwd)
        if not value.get('ok'):
            details = {key: value[key] for key in ('error_source', 'missing_scopes', 'cli_error_subtype', 'upstream_code') if key in value}
            raise FeishuError(value.get('error_code', 'cli_failed'), value.get('error', 'Feishu operation failed'), **details)
        envelope = value.get('data')
        if not isinstance(envelope, dict) or envelope.get('ok') is not True or envelope.get('identity') != 'user' or not isinstance(envelope.get('data'), dict):
            raise FeishuError('invalid_cli_response', 'Feishu did not return the expected user response')
        return envelope['data']

    def _validate_app_id(self, app_id):
        if not isinstance(app_id, str) or not APP_ID.fullmatch(app_id):
            raise ValueError('Enter a valid Miaoda app ID')
        return app_id

    def _apps(self):
        return self._load('applications.json', {'apps': {}})

    def applications(self, directory):
        relative(directory)
        state = self._apps()
        return {'apps': [dict(app) for app in state['apps'].values() if app.get('directory') == directory]}

    def _credentials(self, app_id):
        data = self._cli(['apps', '+git-credential-init', '--app-id=' + app_id])
        url = data.get('repository_url', '')
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname != 'miaoda-git.feishu.cn' or parsed.username or parsed.password:
            raise ValueError('Unexpected Miaoda repository URL')
        return data

    def _clone(self, app_id, target):
        data = self._credentials(app_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        _git(target.parent, 'clone', '--branch', 'sprint/default', '--single-branch', data['repository_url'], str(target), timeout=600)
        # Only repository-local identity is used; credentials remain with the CLI.
        if data.get('commit_author_name'):
            _git(target, 'config', 'user.name', data['commit_author_name'])
        if data.get('commit_author_email'):
            _git(target, 'config', 'user.email', data['commit_author_email'])
        return _git(target, 'rev-parse', 'HEAD')

    @staticmethod
    def _check_layout(repo, project_id=None):
        paths = [repo / 'src/app.tsx', repo / 'public/course.html', repo / 'public/course-data.js', repo / 'public/course-runtime.js']
        if not all(path.is_file() and not path.is_symlink() for path in paths):
            raise ValueError('This app is not a supported Design Studio course app')
        source = paths[2].read_text(encoding='utf-8')
        if 'LeafLoomStudioInstance' not in paths[0].read_text(encoding='utf-8') or not source.startswith('window.STUDIO_DOCUMENT='):
            raise ValueError('This app is not a supported Design Studio course app')
        if project_id is not None:
            try:
                prior = json.loads(source.removeprefix('window.STUDIO_DOCUMENT=').strip().removesuffix(';'))
            except (ValueError, TypeError) as error:
                raise ValueError('The course app document is invalid') from error
            if not isinstance(prior, dict) or prior.get('id') != project_id:
                raise ValueError('This course app belongs to a different design project')

    def associate(self, directory, app_id):
        directory = relative(directory); app_id = self._validate_app_id(app_id)
        project_id = self.workspace.documents.read(directory)['document']['id']
        with self.lock:
            if self.active:
                raise ConflictError('Another Miaoda publication is already running')
            self.active.add('association')
        try:
            data = self._cli(['apps', '+get', '--app-id=' + app_id])
            app = data.get('app', data)
            if app.get('app_type') != 'frontend':
                raise ValueError('Only frontend course apps can be associated')
            staging = self._state('associations', uuid.uuid4().hex)
            head = self._clone(app_id, staging)
            self._check_layout(staging, project_id)
            with self.lock:
                state = self._apps()
                existing = state['apps'].get(app_id)
                if existing and existing['directory'] != directory:
                    raise ConflictError('This app is already associated with another design project')
                if existing and existing['head'] != head:
                    raise ConflictError('The remote app changed after association or the last publication; review before continuing')
                if not existing:
                    _verify_association(staging, head, project_id)
                record = {'app_id': app_id, 'name': app.get('name', app_id), 'directory': directory, 'head': head}
                state['apps'][app_id] = record
                _write(self._state('applications.json'), state)
            return {'ok': True, 'app': record}
        finally:
            with self.lock: self.active.discard('association')

    def start(self, body):
        directory = relative(body.get('directory', ''))
        value = self.workspace.documents.read(directory)
        if value['revision'] != body.get('expected_revision'):
            raise ConflictError('Design changed; refresh before publishing')
        _, report = select_export(audience_document(value['document']), body.get('page_ids'))
        target = body.get('target')
        if not isinstance(target, dict) or target.get('type') not in ('new', 'existing'):
            raise ValueError('Choose a course application')
        if target['type'] == 'existing':
            app_id = self._validate_app_id(target.get('app_id'))
            if not any(item['app_id'] == app_id for item in self.applications(directory)['apps']):
                raise ValueError('Associate this course app before publishing')
        else:
            name = target.get('name', '').strip() if isinstance(target.get('name'), str) else ''
            if not name or len(name) > 100:
                raise ValueError('Enter an application name')
            target = {'type': 'new', 'name': name}
        with self.lock:
            if self.active:
                raise ConflictError('Another Miaoda publication is already running')
            if any(item['status'] in ('interrupted', 'awaiting_approval', 'release_pending', 'release_unknown') for item in self.jobs(directory)['jobs']):
                raise ConflictError('An earlier publication needs review before starting another')
            job_id = uuid.uuid4().hex
            job = {'job_id': job_id, 'root': str(self.config.root), 'directory': directory,
                   'revision': value['revision'], 'page_ids': body['page_ids'], 'target': target,
                   'status': 'queued', 'stage': 'queued', 'completed': 0, 'total': 0,
                   'missing_pages': report['missing_pages'], 'dynamic_warning': report['dynamic_warning'],
                   'reason': '发布 ' + (value['document'].get('name') or '设计工作台课件')[:120] + '，支持在线浏览和交互',
                   'app_id': target.get('app_id', ''), 'error': ''}
            self._save_job(job); self.active.add(job_id)
            self.pool.submit(self._run, job_id)
        return self.get(job_id)

    def get(self, job_id):
        with self.lock:
            job = self._job(job_id)
            return {k: v for k, v in job.items() if k != 'root'}

    def jobs(self, directory):
        directory = relative(directory)
        folder = self._state('jobs')
        jobs = []
        if folder.exists():
            for path in sorted(folder.glob('*.json'), key=lambda item: item.stat().st_mtime):
                try:
                    value = self._job(path.stem)
                    if value['directory'] == directory:
                        jobs.append({k: v for k, v in value.items() if k != 'root'})
                except (ValueError, OSError, KeyError, json.JSONDecodeError):
                    continue
        recent = jobs[-20:]
        pending = [job for job in jobs[:-20] if job['status'] in ('interrupted', 'awaiting_approval', 'release_pending', 'release_unknown')]
        return {'jobs': pending + recent}

    def refresh(self, job_id):
        with self.release_lock:
            with self.lock:
                job = self._job(job_id)
                if job_id in self.active and job['status'] == 'release_pending':
                    return self.get(job_id)
            if not job.get('release_id') or job['status'] not in ('awaiting_approval', 'release_pending', 'release_unknown'):
                raise ValueError('No pending release to check')
            self._release_status(job)
            if job.get('stage') == 'bootstrap_ready':
                with self.lock:
                    if self.active:
                        raise ConflictError('Another Miaoda publication is already running')
                    job.update(status='queued', stage='queued', resume=True, release_kind='course',
                               bootstrap_release_id=job['release_id'], release_id='')
                    self._save_job(job); self.active.add(job_id)
                    self.pool.submit(self._run, job_id)
            return self.get(job_id)

    def retry(self, job_id):
        with self.lock:
            job = self._job(job_id)
            if self.active:
                raise ConflictError('Another Miaoda publication is already running')
            if job['status'] != 'interrupted' or job.get('last_stage') != 'upload_assets' or not job.get('app_id'):
                raise ValueError('This operation has an uncertain remote outcome; inspect the app before starting again')
            self.active.add(job_id)
        try:
            pending = job.get('pending_asset', '')
            if pending:
                listing = self._cli(['apps', '+file-list', '--app-id=' + job['app_id'], '--name=' + pending, '--page-size=200'])
                matches = listing.get('items', [])
                if listing.get('has_more') or len(matches) != 1 or matches[0].get('file_name') != pending or not matches[0].get('download_url'):
                    raise ValueError('The last upload could not be uniquely confirmed; inspect app storage before retrying')
                cache = self._load('assets-' + job['app_id'] + '.json', {})
                cache[pending] = matches[0]['download_url']
                _write(self._state('assets-' + job['app_id'] + '.json'), cache)
                job['pending_asset'] = ''
            job.update(status='queued', stage='queued', error='', resume=True)
            self._save_job(job)
            self.pool.submit(self._run, job_id)
            return self.get(job_id)
        except Exception:
            with self.lock: self.active.discard(job_id)
            raise

    def acknowledge(self, job_id, confirmed):
        if confirmed is not True:
            raise ValueError('Confirm that the remote application has been inspected')
        with self.lock:
            job = self._job(job_id)
            if job['status'] != 'interrupted':
                raise ValueError('Only an interrupted publication can be acknowledged')
            job.update(status='resolved', stage='resolved')
            self._save_job(job)
            return self.get(job_id)

    def _release_status(self, job):
        data = self._cli(['apps', '+release-get', '--app-id=' + job['app_id'], '--release-id=' + job['release_id']])
        data = data.get('release', data)
        status = data.get('status', '')
        if status == 'finished':
            # Miaoda only permits visibility changes once the initial release exists.
            # A failed or ambiguous update stays pending until a later read confirms it.
            if job['target']['type'] == 'new' and not job.get('access_confirmed'):
                self._step(job, 'set_access', status='release_pending')
                try:
                    access = self._cli(['apps', '+access-scope-get', '--app-id=' + job['app_id']])
                    if str(access.get('scope', '')).lower() != 'tenant':
                        self._cli(['apps', '+access-scope-set', '--app-id=' + job['app_id'], '--scope=tenant'])
                        access = self._cli(['apps', '+access-scope-get', '--app-id=' + job['app_id']])
                    if str(access.get('scope', '')).lower() != 'tenant':
                        raise ValueError('Unable to confirm company-wide app access')
                    self._step(job, 'set_access', access_confirmed=True, error='')
                except Exception as error:
                    details = getattr(error, 'details', {})
                    self._step(job, 'set_access', status='release_unknown', error='The app was published, but company access could not be confirmed: ' + str(error)[:800],
                               error_code=getattr(error, 'code', ''), missing_scopes=details.get('missing_scopes', []) if isinstance(details, dict) else [])
                    return
            if job.get('release_kind') == 'bootstrap':
                self._step(job, 'bootstrap_ready', status='release_pending')
                return
            if job['target']['type'] == 'new' and job.get('release_kind') == 'course':
                access = self._cli(['apps', '+access-scope-get', '--app-id=' + job['app_id']])
                if str(access.get('scope', '')).lower() != 'tenant':
                    self._step(job, 'release_unknown', status='release_unknown', error='The app access scope changed; inspect it before sharing the course')
                    return
            url = data.get('online_url', '')
            parsed = urlparse(url) if isinstance(url, str) else urlparse('')
            if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
                self._step(job, 'release_unknown', status='release_unknown', error='The release finished, but Miaoda did not return a valid access link')
                return
            self._step(job, 'completed', status='completed', url=url, error='')
        elif status == 'failed':
            self._step(job, 'failed', status='failed', error='Miaoda release failed: ' + str(data.get('error_logs', ''))[:1000])
        elif (data.get('current_node_info') or {}).get('current_status') == 'PENDING':
            link = ((data.get('current_node_info') or {}).get('result') or {}).get('approval_url', '')
            parsed = urlparse(link)
            self._step(job, 'awaiting_approval', status='awaiting_approval', approval_url=link if parsed.scheme == 'https' and parsed.netloc else '')
        elif status == 'publishing' and time.time() - job.get('release_started_at', time.time()) < 300:
            self._step(job, 'release_pending', status='release_pending', release_status=status)
        else:
            self._step(job, 'release_unknown', status='release_unknown', release_status=status)

    def _run(self, job_id):
        job = None
        try:
            job = self._job_running(job_id)
            self._publish(job)
            # Keep advancing the publication even when its dialog is closed.
            # Approval and unknown outcomes remain paused for an explicit check.
            while job['status'] == 'release_pending':
                time.sleep(10)
                if job['root'] != str(self.config.root):
                    raise ConflictError('Connected folder changed')
                with self.release_lock:
                    self._release_status(job)
                if job.get('stage') == 'bootstrap_ready':
                    self._step(job, 'snapshot', status='running', resume=True, release_kind='course',
                               bootstrap_release_id=job['release_id'], release_id='')
                    self._publish(job)
        except Exception as error:
            # After an uncertain write the operation is deliberately not replayed.
            if job and job['root'] == str(self.config.root):
                details = getattr(error, 'details', {})
                release = bool(job.get('release_id'))
                self._step(job, 'release_unknown' if release else 'failed', status='release_unknown' if release else 'interrupted', last_stage=job['stage'], error=str(error)[:1000],
                           error_code=getattr(error, 'code', ''), missing_scopes=details.get('missing_scopes', []) if isinstance(details, dict) else [])
        finally:
            with self.lock:
                self.active.discard(job_id)

    def _job_running(self, job_id):
        with self.lock:
            job = self._job(job_id)
            job['status'] = 'running'; self._save_job(job)
            return job

    def _publish(self, job):
        if job['root'] != str(self.config.root):
            raise ConflictError('Connected folder changed')
        work = self._state('work', job['job_id'])
        work.mkdir(parents=True, exist_ok=True)
        payload = work / 'bundle'; payload.mkdir(exist_ok=True)
        if not job.get('resume'):
            self._step(job, 'snapshot')
            export = self.workspace.export(job['directory'], job['page_ids'], job['revision'], snapshot_dir=work / 'snapshot')
            bundle = Path(export['snapshot_path'])
            with zipfile.ZipFile(bundle) as archive:
                for info in archive.infolist():
                    name = info.filename
                    if info.is_dir(): continue
                    if name.startswith('/') or '..' in Path(name).parts or '\\' in name:
                        raise ValueError('Invalid export path')
                    dest = payload / name; dest.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, dest.open('wb') as target:
                        shutil.copyfileobj(source, target, 1024 * 1024)
        raw = (payload / 'document.js').read_text(encoding='utf-8')
        document = json.loads(raw.removeprefix('window.STUDIO_DOCUMENT=').strip().removesuffix(';'))
        target = job['target']; app_id = job['app_id']
        if job.get('resume'):
            repo = work / 'repo'; head = _git(repo, 'rev-parse', 'HEAD')
            if head != self._apps()['apps'][app_id]['head']:
                raise ConflictError('The app checkout changed; review before continuing')
            if target['type'] == 'new':
                access = self._cli(['apps', '+access-scope-get', '--app-id=' + app_id])
                if str(access.get('scope', '')).lower() != 'tenant':
                    raise ConflictError('The app access scope changed; inspect it before uploading the course')
        elif target['type'] == 'new':
            self._step(job, 'create_app')
            data = self._cli(['apps', '+create', '--app-type=frontend', '--name=' + target['name'], '--description=Design Studio interactive course'])
            app = data.get('app', data); app_id = self._validate_app_id(app.get('app_id'))
            self._step(job, 'initialize_app', app_id=app_id)
            self._cli(['apps', '+init', '--app-id=' + app_id, '--dir=repo'], cwd=work, timeout=1200)
            repo = work / 'repo'; head = _git(repo, 'rev-parse', 'HEAD')
            state = self._apps(); state['apps'][app_id] = {'app_id': app_id, 'name': target['name'], 'directory': job['directory'], 'head': head}
            _write(self._state('applications.json'), state)
            # Publish only the empty, newly initialized scaffold first. The real
            # course is uploaded only after tenant access has been confirmed.
            self._step(job, 'bootstrap_release')
            release = self._cli(['apps', '+release-create', '--app-id=' + app_id, '--branch=sprint/default', '--apply-reason=' + job['reason']])
            release_id = release.get('release_id')
            if not isinstance(release_id, str) or not release_id:
                raise ValueError('Miaoda did not return an initial release ID; inspect the app before retrying')
            self._step(job, 'release_pending', status='release_pending', release_kind='bootstrap', release_id=release_id, release_started_at=time.time())
            return
        else:
            self._step(job, 'check_app')
            app = self._apps()['apps'][app_id]
            repo = work / 'repo'; head = self._clone(app_id, repo)
            self._check_layout(repo, document['id'])
            if head != app['head']:
                raise ConflictError('The remote app changed after association or the last publication; review before continuing')
        assets = [p for p in payload.rglob('*') if p.is_file() and p.relative_to(payload).as_posix() not in ('index.html', 'document.js', 'runtime.js', 'runtime.css')]
        binary = [p for p in assets if p.suffix.lower() not in ('.js', '.mjs', '.css', '.html', '.htm', '.json', '.svg')]
        urls, hashes = {}, {}
        self._step(job, 'upload_assets', total=len(binary), completed=0)
        cache = self._load('assets-' + app_id + '.json', {})
        if cache:
            present, token, seen = set(), '', set()
            while True:
                args = ['apps', '+file-list', '--app-id=' + app_id, '--page-size=200']
                if token: args.append('--page-token=' + token)
                listing = self._cli(args)
                present.update(item.get('download_url') for item in listing.get('items', []) if isinstance(item, dict))
                if not listing.get('has_more'): break
                token = listing.get('page_token', '')
                if not token or token in seen or len(seen) >= 1000:
                    raise ValueError('Unable to verify the app asset inventory')
                seen.add(token)
            cache = {key: url for key, url in cache.items() if url in present}
        for index, path in enumerate(binary):
            rel = path.relative_to(payload).as_posix()
            if path.stat().st_size > 100 * 1024 * 1024:
                raise ValueError('An asset exceeds Miaoda’s 100 MB per-file limit: ' + rel)
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''): digest.update(chunk)
            digest = digest.hexdigest()
            key = digest + path.suffix.lower()
            if key not in cache:
                upload_dir = work / 'upload'; upload_dir.mkdir(exist_ok=True)
                staged = upload_dir / (digest + path.suffix.lower())
                if not staged.exists(): shutil.copyfile(path, staged)
                self._step(job, 'upload_assets', pending_asset=key)
                uploaded = self._cli(['apps', '+file-upload', '--app-id=' + app_id, '--file=./upload/' + staged.name], cwd=work, timeout=600)
                if job['root'] != str(self.config.root):
                    raise ConflictError('Connected folder changed; inspect the remote asset before retrying')
                url = uploaded.get('download_url', '')
                if not isinstance(url, str) or not (url.startswith('/spark/app/' + app_id + '/') or url.startswith('https://')):
                    raise ValueError('Miaoda did not return a usable asset URL')
                cache[key] = url; _write(self._state('assets-' + app_id + '.json'), cache)
            urls[rel] = cache[key]; hashes[rel] = key
            self._step(job, 'upload_assets', completed=index + 1, pending_asset='')
        document = _rewrite(document, urls)
        _remove_previous_text_assets(repo, document['id'])
        generated_assets = []
        for path in assets:
            if path in binary: continue
            rel = path.relative_to(payload).as_posix()
            if rel in ('course.html', 'course-data.js', 'course-runtime.js', 'course-runtime.css', 'leafloom-course.json'):
                raise ValueError('An export resource conflicts with a reserved course file: ' + rel)
            dest = _destination(repo, 'public/' + rel); dest.parent.mkdir(parents=True, exist_ok=True)
            content = path.read_text(encoding='utf-8')
            dest.write_text(_rewrite(content, urls, rel), encoding='utf-8')
            generated_assets.append(rel)
        _destination(repo, 'src').mkdir(exist_ok=True); _destination(repo, 'public').mkdir(exist_ok=True)
        for name in ('app.tsx', 'course.css'):
            shutil.copyfile(TEMPLATE / name, _destination(repo, 'src/' + name))
        shutil.copyfile(TEMPLATE / 'course.html', _destination(repo, 'public/course.html'))
        shutil.copyfile(RUNTIME / 'runtime.js', _destination(repo, 'public/course-runtime.js'))
        shutil.copyfile(RUNTIME / 'runtime.css', _destination(repo, 'public/course-runtime.css'))
        pages = [{'id': page['id'], 'name': page.get('name', page['id'])} for page in document['pages']]
        _destination(repo, 'src/course-pages.ts').write_text('export const courseTitle = ' + json.dumps(document['name'], ensure_ascii=False) + ';\nexport const coursePages = ' + json.dumps(pages, ensure_ascii=False) + ';\n', encoding='utf-8')
        _destination(repo, 'public/course-data.js').write_text('window.STUDIO_DOCUMENT=' + json.dumps(document, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c') + ';\n', encoding='utf-8')
        self._step(job, 'push')
        remote = _git(repo, 'ls-remote', 'origin', 'refs/heads/sprint/default').split()[0]
        if remote != head:
            raise ConflictError('The remote app changed during publication; no content was pushed')
        _git(repo, 'add', '--', 'src/app.tsx', 'src/course.css', 'src/course-pages.ts', 'public')
        _write(_destination(repo, 'public/leafloom-course.json'), {'version': 2, 'project_id': document['id'], 'page_ids': job['page_ids'], 'generated_assets': generated_assets, 'tracked_files': _tracked_files(repo)})
        _git(repo, 'add', '--', 'public/leafloom-course.json')
        changed = bool(_git(repo, 'status', '--porcelain'))
        if changed:
            _git(repo, 'commit', '-m', 'Update Design Studio course', timeout=600)
        new_head = _git(repo, 'rev-parse', 'HEAD')
        _verify_association(repo, new_head, document['id'])
        if changed:
            try:
                _git(repo, 'push', 'origin', 'sprint/default', timeout=600)
            except GitAuthError:
                self._credentials(app_id)
                if _git(repo, 'ls-remote', 'origin', 'refs/heads/sprint/default').split()[0] != head:
                    raise ConflictError('The remote app changed during publication; no content was pushed')
                _git(repo, 'push', 'origin', 'sprint/default', timeout=600)
        state = self._apps(); state['apps'][app_id]['head'] = new_head
        _write(self._state('applications.json'), state)
        self._step(job, 'release')
        release = self._cli(['apps', '+release-create', '--app-id=' + app_id, '--branch=sprint/default', '--apply-reason=' + job['reason']])
        release_id = release.get('release_id')
        if not isinstance(release_id, str) or not release_id:
            raise ValueError('Miaoda did not return a release ID; inspect the app before retrying')
        self._step(job, 'release_pending', status='release_pending', release_id=release_id, release_started_at=time.time())
        self._release_status(job)
