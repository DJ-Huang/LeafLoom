"""Shared, standard-library-only desktop installer. Usable before app dependencies exist."""
from __future__ import annotations

import argparse
from collections import deque
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import uuid
import zipfile

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))
from vault_rag.i18n import t
TRANSIENT = re.compile(r'timed? ?out|connection (?:reset|refused|aborted)|temporar|\b(?:429|502|503|504)\b|name resolution|network is unreachable', re.I)


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def platform_key():
    machine = platform.machine().lower()
    if sys.platform == 'win32' and machine in ('amd64', 'x86_64'):
        # A translated x64 Python on Windows ARM is not a supported platform.
        if 'arm' not in (os.getenv('PROCESSOR_ARCHITEW6432', '') + os.getenv('PROCESSOR_ARCHITECTURE', '')).lower():
            if sys.getwindowsversion().major >= 10:
                return 'windows-x64'
    if sys.platform == 'darwin' and machine == 'arm64' and int(platform.mac_ver()[0].split('.')[0]) >= 14:
        return 'macos-arm64'
    raise RuntimeError('支持 Windows 10/11 x64 或 macOS 14+ Apple 芯片；当前系统/架构不受支持。')


class InstallLock:
    """OS-owned lock: a crash never leaves a stale installation lock."""
    def __init__(self, path, *, timeout=0):
        self.path = Path(path)
        self.timeout = timeout

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open('a+b')
        self.stream.seek(0)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.stream.seek(0)
                if sys.platform == 'win32':
                    import msvcrt
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if time.monotonic() >= deadline:
                    self.stream.close()
                    raise RuntimeError('另一个安装或启动操作正在进行，请等待完成后重试。') from error
                time.sleep(.1)
        if os.fstat(self.stream.fileno()).st_size == 0:
            self.stream.write(b'0'); self.stream.flush()
        return self

    def __exit__(self, *_):
        self.stream.close()


class Installer:
    def __init__(self, repository, state, *, key=None):
        self.repo = Path(repository).resolve()
        self.state = Path(state).resolve()
        self.key = key or platform_key()
        self.manifest = json.loads((self.repo / 'scripts/runtimes.json').read_text(encoding='utf-8'))
        self.runtime = self.state / 'runtimes'
        self.python = self.repo / ('.venv/Scripts/python.exe' if self.key == 'windows-x64' else '.venv/bin/python')
        self.uv = self.runtime / ('uv-' + self.manifest['uv_version']) / ('uv.exe' if self.key == 'windows-x64' else 'uv')
        self.marker = self.state / 'install.json'
        self.stage = '检查安装状态'
        self.log = None
        self.env = dict(os.environ, VAULT_RAG_HOME=str(self.state), PYTHONUTF8='1', PYTHONUNBUFFERED='1', HF_HUB_DISABLE_XET='1',
                        UV_PYTHON_INSTALL_DIR=str(self.runtime / 'python'), UV_PYTHON_BIN_DIR=str(self.runtime / 'python-bin'),
                        UV_CACHE_DIR=str(self.runtime / 'uv-cache'), UV_PROJECT_ENVIRONMENT=str(self.repo / '.venv'))
        # Ambient Python/index overrides must not change the repository's locked installation.
        for name in ('VIRTUAL_ENV', 'CONDA_PREFIX', 'PYTHONHOME', 'PYTHONPATH', 'UV_PYTHON', 'UV_INDEX',
                     'UV_INDEX_URL', 'UV_EXTRA_INDEX_URL', 'UV_DEFAULT_INDEX', 'UV_NO_SYNC', 'UV_FROZEN', 'UV_OFFLINE'):
            self.env.pop(name, None)

    def emit(self, line):
        line = t(str(line), self.state)
        # Do not expose credentials carried by proxy/download URLs.
        line = re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@', r'\1<redacted>@', str(line))
        line = re.sub(r'Bearer\s+[^\s"\']+', 'Bearer <redacted>', line)
        if sys.stdout:
            print(line, flush=True)
        if self.log:
            self.log.write(line + '\n'); self.log.flush()

    def step(self, title):
        self.stage = t(title, self.state)
        self.emit('\n[' + self.stage + ']')

    def run(self, args, *, retry=False, capture=False):
        args = [str(a) for a in args]
        for attempt in range(1, 4 if retry else 2):
            lines = deque(maxlen=25)
            output = []
            process = subprocess.Popen(args, cwd=self.repo, env=self.env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                                       **({'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}))
            for line in process.stdout:
                line = line.rstrip()
                lines.append(line)
                if capture: output.append(line)
                else: self.emit(line)
            process.stdout.close()
            code = process.wait()
            if code == 0:
                return '\n'.join(output) if capture else None
            detail = '\n'.join(lines)
            if retry and attempt < 3 and TRANSIENT.search(detail):
                self.emit(f'暂时性网络错误，重试 {attempt}/2…'); time.sleep(attempt * 2)
                continue
            raise RuntimeError(f'命令退出码 {code}: {Path(args[0]).name}\n{detail}')

    def input_hash(self):
        # App sources are editable; changing a tray/launcher does not require
        # reinstalling dependencies or rebuilding the website.
        paths = [self.repo / name for name in ('pyproject.toml', 'uv.lock', 'scripts/runtimes.json')]
        return hashlib.sha256((self.hash_paths(paths) + self.web_input_hash()).encode()).hexdigest()

    def web_input_hash(self):
        paths = [self.repo / name for name in ('web/package.json', 'web/package-lock.json')]
        paths.extend(sorted((self.repo / 'web').glob('*.ts*')))
        paths.extend(sorted((self.repo / 'web').glob('*.js*')))
        paths.append(self.repo / 'web/index.html')
        paths.extend(sorted((self.repo / 'web/src').rglob('*')))
        paths.extend(sorted((self.repo / 'web/public').rglob('*')))
        paths.extend(sorted((self.repo / 'vault_rag/locales').glob('*.json')))
        return self.hash_paths(paths)

    def dependency_hash(self):
        return self.hash_paths([self.repo / name for name in ('pyproject.toml', 'uv.lock', 'scripts/runtimes.json')])

    def dependencies_ready(self):
        try:
            try:
                receipt = json.loads((self.state / 'python-install.json').read_text())
                unchanged = receipt['input_hash'] == self.dependency_hash() and receipt['python'] == str(self.python)
            except FileNotFoundError:
                # Adopt a previous successful installation without syncing its packages again.
                receipt = json.loads(self.marker.read_text())
                unchanged = (receipt['input_hash'] == self.input_hash() and receipt['python'] == str(self.python)
                             and receipt['repository'] == str(self.repo) and receipt['platform'] == self.key)
            if not unchanged or not self.compatible():
                return False
            self.run([self.python, '-X', 'utf8', self.repo / 'scripts/install_actions.py', 'check'], capture=True)
            return True
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            return False

    def hash_paths(self, paths):
        digest = hashlib.sha256()
        for path in paths:
            if path.is_file():
                digest.update(path.relative_to(self.repo).as_posix().encode()); digest.update(bytes.fromhex(sha256(path)))
        return digest.hexdigest()

    def web_files(self):
        root = self.repo / 'vault_rag/static'
        if not (root / 'index.html').is_file():
            return {}
        files = {p.relative_to(root).as_posix(): sha256(p) for p in root.rglob('*') if p.is_file()}
        return files if any(name.startswith('assets/') for name in files) else {}

    def model_ready(self):
        try:
            receipt = json.loads((self.state / 'models/model-lock.json').read_text(encoding='utf-8'))
            root = self.state / 'models/bge-m3'
            files = receipt.get('files', {})
            if receipt.get('model') != 'BAAI/bge-m3' or not receipt.get('revision') or not files:
                return False  # Legacy models are checked/upgraded locally during prepare.
            for name, meta in files.items():
                path = root / name
                if not path.resolve().is_relative_to(root.resolve()) or not path.is_file() or path.stat().st_size != meta['size']:
                    return False
                if meta.get('sha256') and meta['size'] <= 1024 * 1024 and sha256(path) != meta['sha256']:
                    return False
            return (root / 'config.json').is_file() and (root / 'tokenizer_config.json').is_file() and \
                any((root / name).is_file() and (root / name).stat().st_size > 0 for name in ('model.safetensors', 'pytorch_model.bin')) and \
                any((root / name).is_file() and (root / name).stat().st_size > 0 for name in ('tokenizer.json', 'sentencepiece.bpe.model', 'spiece.model'))
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def compatible(self):
        try:
            probe = "import sys,platform,json; print(json.dumps([list(sys.version_info[:3]),sys.platform,platform.machine().lower(),sys.maxsize>2**32]))"
            result = json.loads(self.run([self.python, '-c', probe], capture=True))
            expected = 'win32' if self.key == 'windows-x64' else 'darwin'
            arch = ('amd64', 'x86_64') if self.key == 'windows-x64' else ('arm64',)
            return result[0] == [int(part) for part in self.manifest['python'].split('.')] and result[1] == expected and result[2] in arch and result[3]
        except (OSError, RuntimeError, ValueError, IndexError, TypeError):
            return False

    def ready(self):
        try:
            marker = json.loads(self.marker.read_text(encoding='utf-8'))
            if marker['repository'] != str(self.repo) or marker['platform'] != self.key or marker['input_hash'] != self.input_hash():
                return False
            if marker.get('desktop', True) != (os.environ.get('VAULT_RAG_INSTALL_TEST_SERVER') != '1'):
                return False
            if marker['python'] != str(self.python) or not self.compatible() or not self.model_ready():
                return False
            if not marker.get('web_files') or marker['web_files'] != self.web_files():
                return False
            self.run([self.python, '-X', 'utf8', self.repo / 'scripts/install_actions.py', 'check-runtime'], capture=True)
            return True
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            return False

    def prepare_environment(self):
        root = self.repo / '.venv'
        healthy = self.compatible() if root.exists() else False
        if root.exists() and not healthy:
            backup = self.repo / ('.venv-backup-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
            # Rename the entry itself; never follow a junction/symlink or delete its target.
            if root.parent.resolve() != self.repo or backup.parent.resolve() != self.repo:
                raise RuntimeError('环境备份路径不在仓库内')
            try:
                root.rename(backup)
            except OSError as error:
                raise RuntimeError(f'无法备份旧环境，请关闭使用本项目 Python 的程序后重试。原文件已保留。\n{error}') from error
            self.emit('旧环境已保留：' + str(backup))

    def download(self, spec):
        self.runtime.mkdir(parents=True, exist_ok=True)
        path = self.runtime / spec['url'].rsplit('/', 1)[-1]
        if path.is_file() and sha256(path) == spec['sha256']:
            return path
        partial = path.with_name(path.name + '.part')
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(spec['url'], timeout=60) as response, partial.open('wb') as stream:
                    shutil.copyfileobj(response, stream)
                if sha256(partial) != spec['sha256']:
                    raise RuntimeError('下载文件 SHA256 校验失败：' + path.name)
                partial.replace(path)
                return path
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                if attempt == 3 or (isinstance(error, urllib.error.HTTPError) and error.code not in (429, 502, 503, 504)):
                    raise
                self.emit(f'下载暂时失败，重试 {attempt}/2…'); time.sleep(attempt * 2)
            finally:
                partial.unlink(missing_ok=True)

    def node(self):
        name = 'node-' + self.manifest['node_version'] + ('-win-x64' if self.key == 'windows-x64' else '-darwin-arm64')
        directory = self.runtime / name
        node = directory / ('node.exe' if self.key == 'windows-x64' else 'bin/node')
        npm_cli = directory / ('node_modules/npm/bin/npm-cli.js' if self.key == 'windows-x64' else 'lib/node_modules/npm/bin/npm-cli.js')
        spec = self.manifest['platforms'][self.key]['node']
        valid = False
        try:
            valid = npm_cli.is_file() and self.run([node, '--version'], capture=True).strip() == self.manifest['node_version'] and (directory / '.verified').read_text() == spec['sha256']
        except (OSError, RuntimeError):
            pass
        if not valid:
            archive = self.download(spec)
            staging = self.runtime / (name + '-extract-' + uuid.uuid4().hex)
            staging.mkdir()
            try:
                if archive.suffix == '.zip':
                    with zipfile.ZipFile(archive) as source:
                        for item in source.infolist():
                            if not (staging / item.filename).resolve().is_relative_to(staging.resolve()):
                                raise RuntimeError('运行环境压缩包包含越界路径')
                        source.extractall(staging)
                else:
                    with tarfile.open(archive) as source:
                        source.extractall(staging, filter='data')
                extracted = staging / name
                (extracted / '.verified').write_text(spec['sha256'])
                if directory.exists():
                    directory.rename(self.runtime / (name + '-old-' + uuid.uuid4().hex[:8]))
                extracted.rename(directory)
            finally:
                if staging.parent.resolve() == self.runtime.resolve():
                    shutil.rmtree(staging)
        self.env['PATH'] = str(node.parent) + os.pathsep + self.env.get('PATH', '')
        return [node, npm_cli]

    def stop_owned(self, *, include_ui=True):
        # These controllers use only the standard library; they also work with a broken old venv.
        sys.path.insert(0, str(self.repo))
        if os.environ.get('VAULT_RAG_INSTALL_TEST_SERVER') == '1':
            if (self.state / 'test-server.started').exists() and self.python.exists():
                self.run([self.python, '-X', 'utf8', self.repo / 'scripts/install_actions.py', 'uninstall'])
            return
        if self.key == 'windows-x64':
            from types import SimpleNamespace
            from vault_rag.windows_service import wait_stopped
            config = SimpleNamespace(directory=self.state)
            wait_stopped(config)
            if include_ui: wait_stopped(config, 'tray')
        else:
            import plistlib
            if include_ui:
                # Cooperatively close the compatibility menu, including Finder launches.
                (self.state / 'menubar.stop').touch()
                lock = self.state / 'menubar.lock'
                deadline = time.monotonic() + 15
                while lock.exists():
                    try:
                        owner = int((lock / 'pid').read_text())
                        os.kill(owner, 0)
                    except (OSError, ValueError): break
                    if time.monotonic() >= deadline: break
                    time.sleep(.2)
            for label in ('com.djhuang.vault-rag', 'com.djhuang.vault-rag.menubar'):
                if not include_ui and label.endswith('menubar'): continue
                path = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
                if path.exists():
                    data = plistlib.loads(path.read_bytes())
                    old_state = data.get('EnvironmentVariables', {}).get('VAULT_RAG_HOME')
                    if label.endswith('menubar'):
                        old_state = data.get('VaultRagState')
                    if old_state and Path(old_state).resolve() != self.state:
                        raise RuntimeError('macOS 登录项属于另一配置目录，未停止或覆盖。')
                    subprocess.run(['/bin/launchctl', 'bootout', f'gui/{os.getuid()}/{label}'], capture_output=True)

    def install(self):
        self.step('安装网页依赖并生成网页')
        build_marker = self.state / 'web-build.json'
        try: cached = json.loads(build_marker.read_text())
        except (OSError, ValueError): cached = {}
        web_hash = self.web_input_hash()
        if cached.get('input_hash') != web_hash or not self.web_files() or cached.get('web_files') != self.web_files():
            self.step('准备 Node 运行环境')
            npm = self.node()
            self.run([*npm, 'ci', '--prefix', 'web', '--no-audit', '--no-fund'], retry=True)
            self.run([*npm, 'run', 'build', '--prefix', 'web'])
            if not self.web_files():
                raise RuntimeError('网页构建没有生成 index.html 和 assets 资源')
            atomic_json(build_marker, {'input_hash': web_hash, 'web_files': self.web_files()})
        else:
            self.emit('网页完整且未变化，跳过依赖安装与构建。')
        dependencies_ready = self.dependencies_ready()
        self.step('正常停止旧服务并准备项目环境')
        self.stop_owned()
        # Keep the previous success record if stopping the old service failed.
        # From here onward the environment is being modified and needs recheck.
        self.marker.unlink(missing_ok=True)
        if not dependencies_ready:
            self.prepare_environment()
            self.step('同步缺失或更新的 Python 依赖及项目')
            extra = []
            if self.compatible():
                try:
                    self.run([self.python, '-X', 'utf8', self.repo / 'scripts/install_actions.py', 'check-runtime'], capture=True)
                except (OSError, RuntimeError):
                    pass  # Missing packages can be filled in by ordinary sync.
                else:
                    try:
                        self.run([self.python, '-X', 'utf8', self.repo / 'scripts/install_actions.py', 'check'], capture=True)
                    except (OSError, RuntimeError):
                        extra = ['--reinstall']  # Present packages with broken native libraries need repair.
            self.run([self.uv, 'sync', '--locked', '--no-dev', '--python', sys.executable, *extra], retry=True)
            self.step('检查原生依赖')
            self.run([self.python, '-X', 'utf8', self.repo / 'scripts/install_actions.py', 'check'])
            atomic_json(self.state / 'python-install.json', {'input_hash': self.dependency_hash(), 'python': str(self.python)})
        else:
            atomic_json(self.state / 'python-install.json', {'input_hash': self.dependency_hash(), 'python': str(self.python)})
            self.emit('Python 依赖完整且未变化，跳过安装。')
        self.step('准备 BGE-M3 模型')
        if not self.model_ready():
            self.run([self.python, '-X', 'utf8', '-m', 'vault_rag.cli', 'model-prepare'], retry=True)
        else:
            self.emit('模型完整，跳过准备。')
        if not self.model_ready():
            raise RuntimeError('模型文件不完整，安装未完成')
        self.step('配置并启动后台服务')
        self.run([self.python, '-X', 'utf8', self.repo / 'scripts/write_mcp_fragment.py'])
        self.run([self.python, '-X', 'utf8', self.repo / 'scripts/install_actions.py', 'install'])
        self.step('验证服务与网页')
        self.run([self.python, '-X', 'utf8', self.repo / 'scripts/install_actions.py', 'verify'])
        marker = {'schema': 1, 'repository': str(self.repo), 'platform': self.key, 'python': str(self.python),
                  'desktop': os.environ.get('VAULT_RAG_INSTALL_TEST_SERVER') != '1',
                  'input_hash': self.input_hash(), 'lock_hash': sha256(self.repo / 'uv.lock').upper(),
                  'web_files': self.web_files(), 'installed_at': time.time()}
        atomic_json(self.marker, marker)
        if self.key == 'windows-x64':
            atomic_json(self.state / 'windows-install.json', marker)  # legacy launchers remain usable
        self.emit('安装完成。日志：' + str(self.state / 'logs/setup.log'))

    def execute(self, action, *, no_open=False, no_install=False):
        if action == 'check':
            return 0 if self.ready() else 3
        self.state.mkdir(parents=True, exist_ok=True)
        logs = self.state / 'logs'; logs.mkdir(exist_ok=True)
        with (logs / ('setup.log' if action == 'install' else 'launcher.log')).open('a', encoding='utf-8', buffering=1) as log:
            self.log = log
            with ExitStack() as locks:
                wait = 90 if action == 'open' else 0
                locks.enter_context(InstallLock(self.state / 'install.lock', timeout=wait))
                locks.enter_context(InstallLock(self.repo / '.install.lock', timeout=wait))
                if action == 'stop':
                    self.stop_owned(include_ui=False); return 0
                ready = self.ready()
                if ready and action == 'install':
                    try:
                        self.run([self.python, '-X', 'utf8', self.repo / 'scripts/install_actions.py', 'check'], capture=True)
                    except (OSError, RuntimeError):
                        ready = False
                if not ready:
                    if no_install: return 3
                    self.install()
                elif action == 'install':
                    atomic_json(self.state / 'python-install.json', {'input_hash': self.dependency_hash(), 'python': str(self.python)})
                    self.emit('当前环境完整且已是最新，跳过安装。')
                if not no_open:
                    self.step('打开本地知识库')
                    self.run([self.python, '-X', 'utf8', self.repo / 'scripts/install_actions.py', 'open'])
        self.log = None
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', type=Path, default=REPOSITORY)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--action', choices=['install', 'open', 'stop', 'check'], default='install')
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--no-install', action='store_true')
    args = parser.parse_args(argv)
    installer = None
    try:
        installer = Installer(args.repository, args.state)
        return installer.execute(args.action, no_open=args.no_open, no_install=args.no_install)
    except Exception as error:
        stage = installer.stage if installer else '检查系统'
        message = f'失败阶段：{stage}\n{error}\n日志：{args.state / "logs"}\n再次双击入口可重试。'
        # execute's context manager has closed the stream on exceptions.
        if installer: installer.log = None
        print(message, file=sys.stderr, flush=True)
        if args.action != 'check':
            args.state.mkdir(parents=True, exist_ok=True)
            logs = args.state / 'logs'; logs.mkdir(exist_ok=True)
            with (logs / 'setup.log').open('a', encoding='utf-8') as stream:
                stream.write(message + '\n')
            if not args.no_open:
                sys.path.insert(0, str(args.repository))
                from vault_rag.platform_support import show_error
                show_error(message[-3500:])
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
