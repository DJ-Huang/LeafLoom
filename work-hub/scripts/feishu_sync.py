#!/usr/bin/env python3
"""One-way Feishu page-tree mirror using lark-cli and LeafLoom's local APIs.

No Feishu writes. Media bytes stay outside the model and notes directory.
Only Python's standard library is required; LeafLoom and lark-cli must be running.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
import hashlib
from html import unescape
from html.parser import HTMLParser
import http.client
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import quote, urlencode, urlsplit


class SyncError(Exception):
    pass


class APIError(SyncError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(f'LeafLoom HTTP {status}: {message}')


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def file_digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.name, delete=False) as stream:
            temp = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp:
            temp.unlink(missing_ok=True)


def safe_path(root, relative):
    """Reject hidden paths, traversal and symlinks, including existing parents."""
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p.startswith('.') for p in parts):
        raise SyncError('Use a visible directory inside the connected vault')
    current = Path(root)
    for part in parts:
        if any(c in part for c in ('\\', '\x00', ':')):
            raise SyncError('Unsafe path')
        current /= part
        if current.is_symlink():
            raise SyncError('Sync paths cannot contain symbolic links')
    return current


@contextmanager
def exclusive_lock(path):
    with Path(path).open('a+b') as stream:
        if sys.platform == 'win32':
            import msvcrt
            stream.seek(0)
            stream.write(b'0')
            stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise SyncError('This directory is already synchronizing') from None
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SyncError('This directory is already synchronizing') from None
        yield


def config_directory():
    if os.environ.get('VAULT_RAG_HOME'):
        return Path(os.environ['VAULT_RAG_HOME']).expanduser()
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/VaultRag'
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'VaultRag'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'VaultRag'


class LeafLoom:
    def __init__(self, config_dir=None):
        self.directory = Path(config_dir) if config_dir else config_directory()
        config = json.loads((self.directory / 'config.json').read_text(encoding='utf-8'))
        self.port = int(config.get('port', 18080))
        self.token = (self.directory / 'auth-token').read_text(encoding='utf-8').strip()
        self.root = str(Path(config['root']).resolve())
        self.revision = config.get('revision')
        self.guard()

    def guard(self):
        config = json.loads((self.directory / 'config.json').read_text(encoding='utf-8'))
        if config.get('root') != self.root or config.get('revision') != self.revision:
            raise SyncError('Connected vault/settings changed; rerun sync after checking the destination')

    def request(self, method, path, body=None, params=None, upload=None):
        self.guard()
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=120)
        headers = {'Authorization': 'Bearer ' + self.token}
        if params:
            path += '?' + urlencode(params)
        try:
            if upload:
                headers.update({'Content-Type': 'application/octet-stream',
                                'Content-Length': str(Path(upload).stat().st_size)})
                connection.putrequest(method, path)
                for key, value in headers.items():
                    connection.putheader(key, value)
                connection.endheaders()
                with Path(upload).open('rb') as stream:
                    while chunk := stream.read(1024 * 1024):
                        self.guard()
                        connection.send(chunk)
            else:
                data = None if body is None else json.dumps(body).encode()
                if data is not None:
                    headers['Content-Type'] = 'application/json'
                connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            data = response.read()
            try:
                value = json.loads(data)
            except ValueError:
                raise APIError(response.status, 'Invalid service response') from None
            if response.status >= 400:
                raise APIError(response.status, str(value.get('error', 'Request failed'))[:300])
            self.guard()
            return value
        finally:
            connection.close()

    def read(self, path):
        # Older local services report a missing file as HTTP 400. The helper
        # already requires host filesystem access, so check existence without
        # interpreting localized error strings or masking other HTTP errors.
        self.guard()
        if not safe_path(self.root, path).exists():
            self.guard()
            return None
        try:
            return self.request('GET', '/api/file', params={'path': path})
        except APIError as error:
            if error.status == 404:
                return None
            raise

    def mkdirs(self, path):
        relative = Path(path).relative_to(self.root)
        current = Path(self.root)
        for part in relative.parts:
            current /= part
            safe_path(self.root, current.relative_to(self.root))
            if not current.exists():
                self.request('POST', '/api/create', {'path': current.relative_to(self.root).as_posix(),
                                                   'directory': True})

    def write(self, path, text, current):
        safe_path(self.root, path)
        self.mkdirs((Path(self.root) / path).parent)
        if current is None:
            self.request('POST', '/api/create', {'path': path, 'text': text})
        else:
            self.request('PUT', '/api/file', {'path': path, 'text': text,
                                            'etag': current['etag'], 'root': self.root})

    def jobs(self):
        return self.request('GET', '/api/attachments/storage/jobs', params={'root': self.root})['jobs']

    def job(self, key):
        return self.request('GET', '/api/attachments/storage/jobs/' + quote(key, safe=''),
                            params={'root': self.root})


def cli(args, *, cwd=None, timeout=120):
    result = subprocess.run(['lark-cli', *args, '--as', 'user'], cwd=cwd,
                            capture_output=True, text=True, timeout=timeout)
    try:
        value = json.loads(result.stdout if result.returncode == 0 else result.stderr)
    except ValueError:
        raise SyncError('lark-cli returned an invalid response (inspect local CLI diagnostics)') from None
    if result.returncode or value.get('ok') is not True:
        error = value.get('error', {})
        # Never echo the full response: notices/auth diagnostics can contain secrets.
        raise SyncError('Feishu: ' + str(error.get('subtype') or error.get('type') or 'request_failed'))
    return value.get('data', {})


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    handle_startendtag = handle_starttag


def attributes(text):
    tags = Tags(text).tags
    return tags[0][1] if tags else {}


def children(text):
    return [a for tag, a in Tags(text).tags if tag == 'sub-page']


IMAGE_RE = re.compile(r'!\[(?P<alt>[^\]\n]*)\]\(https://(?:[\w.-]+\.)?(?:feishu\.cn|larksuite\.com)/file/(?P<token>[A-Za-z0-9_-]+)(?:\?[^\s)]*)?\)')
FILE_LINK_RE = re.compile(r'(?<!!)\[([^\]\n]+)\]\((https://(?:[\w.-]+\.)?(?:feishu\.cn|larksuite\.com)/(?:drive/)?file/([A-Za-z0-9_-]+))(?:\?[^\s)]*)?\)')
FIGURE_RE = re.compile(r'<figure\b[^>]*>.*?</figure>', re.S)
IMG_RE = re.compile(r'<img\b[^>]*?/?>', re.S)


def media(text):
    found = {}
    for match in IMAGE_RE.finditer(text):
        token = match['token']
        found[token] = {'token': token, 'kind': 'image', 'name': token, 'size': None}
    for tag, item in Tags(text).tags:
        token = item.get('token')
        mime = item.get('mime', '')
        name = item.get('name', token or '')
        guessed = mimetypes.guess_type(name)[0] or ''
        kind = ('image' if tag == 'img' or mime.startswith('image/') or guessed.startswith('image/')
                else 'video' if mime.startswith('video/') or guessed.startswith('video/') else None)
        if token and kind and tag in {'source', 'img'}:
            if not re.fullmatch(r'[A-Za-z0-9_-]+', token):
                raise SyncError('Invalid media token')
            size = item.get('size')
            found[token] = {'token': token, 'kind': kind, 'name': name,
                            'size': int(size) if size and size.isdigit() else None}
    return found


def md_label(text):
    return re.sub(r'[\[\]\r\n|]', ' ', unescape(text))


def render(document, pages, assets, source, destination):
    text = document['content']
    text = re.sub(r'<title>(.*?)</title>', lambda m: '# ' + unescape(m[1]), text, flags=re.S)
    # Docx column widgets are not Markdown HTML: flatten them in reading order
    # so the normal reader can still render their text and media blocks.
    text = re.sub(r'</?(?:grid|column)\b[^>]*>', '\n', text)

    def embed(token, fallback):
        item = assets.get(token, {})
        return '![[%s]]' % item['path'] if item.get('state') == 'completed' else fallback

    def image(match):
        asset = assets.get(match['token'], {})
        if asset.get('state') == 'completed' and match['alt']:
            return '![%s](%s)' % (match['alt'], asset['path'])
        return embed(match['token'], match[0])

    text = IMAGE_RE.sub(image, text)
    text = FILE_LINK_RE.sub(lambda m: (md_label(m[1]) + '\n\n' + embed(m[3], m[0]))
                           if assets.get(m[3], {}).get('state') == 'completed' else m[0], text)
    text = IMG_RE.sub(lambda m: embed(attributes(m[0]).get('token'),
                                     '[图片](%s)' % source), text)

    def figure(match):
        sources = [a for tag, a in Tags(match[0]).tags if tag == 'source']
        if not sources:
            return '[嵌入内容](%s)' % source
        result = []
        for item in sources:
            token = item.get('token', '')
            fallback = '[%s](https://feishu.cn/file/%s)' % (md_label(item.get('name', '附件')), quote(token))
            result.append(embed(token, fallback))
        return '\n\n'.join(result)

    text = FIGURE_RE.sub(figure, text)

    def subpage(match):
        item = attributes(match[0])
        page = pages.get(item.get('doc-id'))
        if page:
            return '- [[%s/%s|%s]]\n' % (destination, page['file'], md_label(page['title']))
        return '- [%s](%s)\n' % (md_label(item.get('title', '子页面')), source)

    text = re.sub(r'<sub-page(?=[\s/>])[^>]*?/?>', subpage, text)
    text = re.sub(r'</?sub-page-list\b[^>]*>', '', text)

    def reference(match):
        item = attributes(match[0])
        tag = Tags(match[0]).tags[0][0]
        if tag == 'task':
            url = 'https://applink.feishu.cn/client/task/open?guid=' + quote(item.get('task-id', ''))
            label = '飞书任务（%s）' % item.get('status', '见原文')
        elif tag == 'cite':
            token = item.get('doc-id', '')
            local = pages.get(token)
            if local:
                return '[[%s/%s|%s]]' % (destination, local['file'], md_label(local['title']))
            url = 'https://feishu.cn/%s/%s' % ('wiki' if item.get('file-type') == 'wiki' else 'docx', quote(token))
            label = item.get('title', '引用文档')
        else:
            url = item.get('href') or source
            label = '飞书嵌入内容（%s）' % item.get('type', tag)
        if not url.startswith(('https://', 'http://')):
            url = source
        return '[%s](%s)' % (md_label(label), url.replace(')', '%29'))

    text = re.sub(r'<(readonly-block|task|cite)\b[^>]*(?:/>|>.*?</\1>)', reference, text, flags=re.S)
    return text.rstrip() + '\n\n---\n来源：[%s](%s) · 飞书版本 %s\n' % (
        md_label(document['title']), source, document['revision_id'])


def save_note(api, path, text, baseline):
    """A lost checkpoint is recoverable; arbitrary local content is never adopted."""
    current = api.read(path)
    expected = digest(text)
    if current and current['etag'] == expected:
        return expected, False
    if current and current['etag'] != baseline:
        raise SyncError('Local changes preserved: ' + path)
    if not current and baseline:
        raise SyncError('Locally deleted page preserved: ' + path)
    api.write(path, text, current)
    return expected, True


def select_job(jobs, storage_id, name, sha256, size):
    matches = [job for job in jobs if job.get('kind') == 'upload' and
               job.get('source_id') == storage_id and
               Path(job.get('requested_path', '')).name == name and
               job.get('sha256') == sha256 and job.get('size') == size]
    if len(matches) > 1:
        raise SyncError('More than one matching upload; preserve for review')
    return matches[0] if matches else None


class Mirror:
    def __init__(self, api, destination, source=None, storage_id=None, workers=3):
        self.api = api
        root = Path(api.root)
        requested = Path(destination).expanduser()
        self.destination = (requested.relative_to(root) if requested.is_absolute() else requested).as_posix()
        safe_path(root, self.destination)
        self.state_dir = root / '.vault-rag' / 'work-hub-sync' / digest(self.destination)[:24]
        current = root
        for part in self.state_dir.relative_to(root).parts:
            current /= part
            if current.is_symlink():
                raise SyncError('Sync state cannot contain symbolic links')
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_file = self.state_dir / 'manifest.json'
        self.data = json.loads(self.state_file.read_text(encoding='utf-8')) if self.state_file.exists() else {
            'schema': 1, 'root': api.root, 'destination': self.destination, 'pages': {}, 'assets': {}}
        if self.data['root'] != api.root or self.data['destination'] != self.destination:
            raise SyncError('Sync manifest belongs to a different destination')
        previous = self.data.get('source')
        if source and previous and previous != source:
            raise SyncError('This destination already mirrors another source')
        self.data['source'] = source or previous
        if not self.data['source']:
            raise SyncError('First sync requires --source with the Feishu page URL')
        parsed = urlsplit(self.data['source'])
        if parsed.scheme != 'https' or not parsed.hostname or not re.fullmatch(
                r'(?:[\w-]+\.)*(?:feishu\.cn|larksuite\.com)', parsed.hostname):
            raise SyncError('Use a Feishu/Lark document URL')
        self.origin = parsed.scheme + '://' + parsed.netloc
        self.storage_id = storage_id or self.data.get('storage_id')
        if storage_id and self.data.get('storage_id') not in (None, storage_id):
            raise SyncError('Attachment source changed; inspect existing media before switching')
        self.workers = workers
        self.lock = threading.RLock()
        self.errors = []
        self.documents = {}
        self.seen = set()
        self.changed = 0

    def checkpoint(self):
        with self.lock:
            atomic_json(self.state_file, self.data)

    def discover(self):
        queue = [(self.data['source'], None, None)]
        scheduled = set()
        complete = True
        while queue:
            target, title, parent = queue.pop(0)
            try:
                document = cli(['docs', '+fetch', '--doc', target, '--doc-format', 'markdown'])['document']
                key = document['document_id']
                if not re.fullmatch(r'[A-Za-z0-9_-]+', key):
                    raise SyncError('Invalid document ID')
                if key in self.seen:
                    continue
                self.seen.add(key)
                title = title or re.sub(r'^#+\s*', '', document['content'].splitlines()[0]).strip()
                document['title'] = title
                page = self.data['pages'].setdefault(key, {})
                filename = 'README.md' if parent is None else re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', title).strip('. ')[:70] + '-' + key[:8] + '.md'
                page.update(title=title, file=page.get('file', filename), parent=parent,
                            source=self.data['source'] if parent is None else self.origin + '/docx/' + key,
                            revision=document['revision_id'], removed=False)
                self.documents[key] = document
                atomic_json(self.state_dir / (key + '.json'), document)
                for item in children(document['content']):
                    child = item.get('doc-id')
                    if child and item.get('file-type') in {'docx', 'wiki'} and child not in scheduled:
                        scheduled.add(child)
                        queue.append((self.origin + '/' + ('wiki' if item['file-type'] == 'wiki' else 'docx') + '/' + child,
                                      item.get('title'), key))
                self.checkpoint()
                print(json.dumps({'page': title, 'revision': document['revision_id']}, ensure_ascii=False), flush=True)
            except Exception as error:
                complete = False
                self.errors.append({'page': target, 'error': str(error)[:300]})
        if complete:
            for key, page in self.data['pages'].items():
                if key not in self.seen:
                    page['removed'] = True
        self.checkpoint()

    def validate_storage(self):
        settings = self.api.request('GET', '/api/attachments/storage', params={'root': self.api.root})
        self.storage_id = self.storage_id or settings['default_storage_id']
        storage = next((s for s in settings['storages'] if s['storage_id'] == self.storage_id and s.get('enabled')), None)
        if not storage or self.storage_id == 'local':
            raise SyncError('Select an enabled attachment server; local fallback is not permitted')
        self.data['storage_id'] = self.storage_id
        self.checkpoint()

    def transfer(self, spec):
        token = spec['token']
        with self.lock:
            asset = self.data['assets'].setdefault(token, dict(spec, state='pending'))
        if asset.get('state') == 'completed':
            # Validate the server receipt, including hash, before reusing a reference.
            job = self.api.job(asset['job_id'])
            self.verify_job(asset, job)
            local = Path(asset['local']) if asset.get('local') else None
            if local and local.is_file() and not local.is_symlink() and local.resolve().is_relative_to(self.state_dir.resolve()):
                if file_digest(local) == asset['sha256']:
                    local.unlink()
            return
        stage = self.state_dir / 'media' / token
        if stage.is_symlink() or stage.parent.is_symlink():
            raise SyncError('Media staging directory cannot be a symbolic link')
        stage.mkdir(parents=True, exist_ok=True, mode=0o700)
        local = Path(asset['local']) if asset.get('local') else None
        if local and (local.is_symlink() or not local.resolve().is_relative_to(self.state_dir.resolve())):
            raise SyncError('Staged media is outside this sync directory')
        if not local or not local.is_file():
            # Failed CLI downloads can leave truncated files; never adopt these.
            for stale in stage.iterdir():
                if stale.is_file() and not stale.is_symlink():
                    stale.unlink()
            if spec.get('download_kind') == 'drive':
                extension = Path(spec['name']).suffix.lower()
                cli(['drive', '+download', '--file-token', token, '--output', './asset' + extension], cwd=stage, timeout=1800)
            else:
                cli(['docs', '+media-download', '--token', token, '--output', './asset'], cwd=stage, timeout=1800)
            files = [p for p in stage.iterdir() if p.is_file() and not p.is_symlink()]
            if len(files) != 1:
                raise SyncError('Media download did not produce exactly one file')
            local = files[0]
            size = local.stat().st_size
            if spec.get('size') is not None and size != spec['size']:
                raise SyncError('Downloaded media size differs from Feishu metadata')
            suffix = local.suffix.lower() or Path(spec['name']).suffix.lower()
            mime = mimetypes.guess_type('asset' + suffix)[0] or ''
            if not mime.startswith(spec['kind'] + '/'):
                raise SyncError('Downloaded content type does not match the media reference')
            sha256 = file_digest(local)
            with self.lock:
                asset.update(local=str(local), size=size, sha256=sha256,
                             upload_name='feishu-' + token + '-' + sha256[:16] + suffix)
                self.checkpoint()
        if file_digest(local) != asset['sha256']:
            raise SyncError('Staged media changed; preserve for inspection')
        job = self.api.job(asset['job_id']) if asset.get('job_id') else select_job(
            self.api.jobs(), self.storage_id, asset['upload_name'], asset['sha256'], asset['size'])
        if job is None:
            if asset.get('upload_started'):
                # An uncertain HTTP result is not permission to send duplicate bytes.
                raise SyncError('Upload result uncertain; no matching server job yet. Rerun to reconcile before retrying')
            with self.lock:
                asset.update(upload_started=True, state='uploading')
                self.checkpoint()
            try:
                job = self.api.request('POST', '/api/upload', params={
                    'root': self.api.root, 'name': asset['upload_name'],
                    'central': 'true', 'storage_id': self.storage_id}, upload=local)
            except APIError as error:
                # A rejected request has no successful upload receipt. Transport
                # errors remain ambiguous and require job reconciliation.
                if error.status in {401, 403, 404, 413}:
                    with self.lock:
                        asset.pop('upload_started', None)
                        self.checkpoint()
                raise
        with self.lock:
            asset['job_id'] = job['job_id']
            self.checkpoint()
        if job['state'] in {'failed', 'cancelled', 'paused'}:
            job = self.api.request('POST', '/api/attachments/storage/jobs/' + quote(job['job_id'], safe='') + '/resume',
                                   {'root': self.api.root, 'confirm': True})
        deadline = time.monotonic() + 3600
        while not job.get('remote_saved'):
            if job['state'] in {'failed', 'cancelled', 'paused', 'interrupted', 'conflict', 'waiting_for_authorization', 'waiting_for_auth'} or job.get('retry_paused'):
                raise SyncError('Attachment job stopped: ' + str(job.get('error') or job['state'])[:200])
            if time.monotonic() > deadline:
                raise SyncError('Attachment remains queued; rerun to continue monitoring')
            time.sleep(2)
            job = self.api.job(asset['job_id'])
        self.verify_job(asset, job)
        with self.lock:
            asset.update(state='completed', path=job['path'], asset_id=job.get('asset_id'))
            asset.pop('error', None)
            self.checkpoint()
        local.unlink(missing_ok=True)
        print(json.dumps({'media': token, 'kind': spec['kind'], 'bytes': asset['size'], 'state': 'server_saved'}), flush=True)

    def verify_job(self, asset, job):
        if not (job.get('remote_saved') and job.get('verified') and
                job.get('source_id') == self.storage_id and
                job.get('size') == asset.get('size') and job.get('sha256') == asset.get('sha256')):
            raise SyncError('Server upload receipt is not verified or differs from local media')

    def write_pages(self):
        for key, document in self.documents.items():
            page = self.data['pages'][key]
            text = render(document, self.data['pages'], self.data['assets'], page['source'], self.destination)
            if page['parent'] is None:
                removed = [p for p in self.data['pages'].values() if p.get('removed')]
                if removed:
                    text += '\n## 来源已移除的本地副本\n\n' + '\n'.join(
                        '- [[%s/%s|%s]]（本地保留）' % (self.destination, p['file'], md_label(p['title'])) for p in removed) + '\n'
            path = self.destination + '/' + page['file']
            try:
                # A prior save can have completed before its checkpoint. Adopt
                # only its recorded content hash, even if Feishu changed again.
                if page.get('pending_hash'):
                    current = self.api.read(path)
                    if current and current['etag'] == page['pending_hash']:
                        page['local_hash'] = current['etag']
                page['pending_hash'] = digest(text)
                self.checkpoint()
                sha256, changed = save_note(self.api, path, text, page.get('local_hash'))
                page.update(local_hash=sha256, synced_revision=document['revision_id'])
                page.pop('pending_hash', None)
                page.pop('conflict', None)
                self.changed += int(changed)
            except SyncError as error:
                page['conflict'] = str(error)
                self.errors.append({'page': path, 'error': str(error)})
                atomic_json(self.state_dir / (key + '-incoming.json'), {'text': text, 'revision': document['revision_id']})
            self.checkpoint()

    def homepage(self):
        parent = Path(self.destination).parent
        path = (parent / 'README.md').as_posix()
        if path == self.destination + '/README.md':
            return
        current = self.api.read(path)
        if not current:
            return
        target = self.destination + '/README.md'
        if target in current['text']:
            return
        self.api.write(path, current['text'].rstrip() + '\n\n- [[%s|飞书工作记录]]：按需同步原页面及图片、视频。\n' % target, current)

    def run(self, inventory=False):
        self.discover()
        specs = {}
        for document in self.documents.values():
            specs.update(media(document['content']))
        # A video may be a normal Drive hyperlink rather than an attachment
        # widget. Inspect only direct file URLs, without following doc links.
        linked = {match[3]: match[2] for document in self.documents.values()
                  for match in FILE_LINK_RE.finditer(document['content']) if match[3] not in specs}
        for token, url in linked.items():
            try:
                info = cli(['drive', '+inspect', '--url', url])
                mime = mimetypes.guess_type(info.get('title', ''))[0] or ''
                kind = mime.split('/')[0]
                if info.get('type') == 'file' and kind in {'image', 'video'}:
                    specs[token] = {'token': token, 'kind': kind, 'name': info['title'],
                                    'size': None, 'download_kind': 'drive'}
            except SyncError as error:
                self.errors.append({'file_link': url, 'error': str(error)})
        if not inventory:
            self.validate_storage()
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                pending = {pool.submit(self.transfer, spec): token for token, spec in specs.items()}
                for future in as_completed(pending):
                    token = pending[future]
                    try:
                        future.result()
                    except Exception as error:
                        message = str(error)[:300]
                        with self.lock:
                            self.data['assets'][token].update(error=message, state='pending')
                            self.errors.append({'media': token, 'error': message})
                            self.checkpoint()
                        print(json.dumps({'media': token, 'error': message}, ensure_ascii=False), flush=True)
            self.write_pages()
            self.homepage()
        summary = {'destination': str(Path(self.api.root) / self.destination), 'pages': len(self.documents),
                   'pages_written': self.changed,
                   'images': sum(s['kind'] == 'image' for s in specs.values()),
                   'videos': sum(s['kind'] == 'video' for s in specs.values()),
                   'known_video_bytes': sum(s.get('size') or 0 for s in specs.values() if s['kind'] == 'video'),
                   'server_saved': sum(self.data['assets'].get(t, {}).get('state') == 'completed' for t in specs),
                   'errors': self.errors, 'inventory_only': inventory}
        self.data['last_run'] = summary
        self.checkpoint()
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', help='First sync: Feishu root wiki/docx URL; saved for later runs')
    parser.add_argument('--destination', default='工作中枢/工作目录', help='Vault-relative or absolute local directory')
    parser.add_argument('--config-dir', help='LeafLoom configuration directory (normally auto-detected)')
    parser.add_argument('--storage-id', help='Attachment server ID; initially defaults to the selected server, then pinned')
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=3)
    parser.add_argument('--inventory', action='store_true', help='Fetch page metadata/content without transferring media or writing notes')
    args = parser.parse_args()
    try:
        api = LeafLoom(args.config_dir)
        mirror = Mirror(api, args.destination, args.source, args.storage_id, args.workers)
        with exclusive_lock(mirror.state_dir / 'sync.lock'):
            # Re-read after acquiring the lock; another run may have just finished.
            if mirror.state_file.exists():
                fresh = json.loads(mirror.state_file.read_text(encoding='utf-8'))
                if fresh.get('source') not in (None, mirror.data['source']):
                    raise SyncError('Sync source changed while waiting for the lock')
                mirror.data = {**mirror.data, **fresh}
            result = mirror.run(args.inventory)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result['errors'] else 0
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({'ok': False, 'error': str(error)[:400]}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
