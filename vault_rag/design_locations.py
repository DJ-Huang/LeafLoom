"""Resolve design project paths inside the vault or a registered external directory."""
from __future__ import annotations
import re
from pathlib import Path, PurePosixPath

from vault_rag.local_state import relative
from vault_rag.platform_support import is_link, is_windows, path_key

DRIVE = re.compile(r'^[A-Za-z]:/')


def external_key(value) -> str:
    """Canonical POSIX form of an absolute local directory key."""
    text = str(value or '').strip()
    if not text:
        raise ValueError('请选择外部工程目录')
    drive = bool(DRIVE.match(text.replace('\\', '/')))
    if drive and not is_windows():
        raise ValueError('当前系统不支持盘符路径')
    path = Path(text).expanduser()
    if is_windows() and path.drive.startswith('\\\\'):
        raise ValueError('不支持网络共享目录中的外部工程')
    if not path.is_absolute():
        raise ValueError('外部工程目录必须是绝对路径')
    return path.resolve().as_posix().rstrip('/') or '/'


def is_external_key(value) -> bool:
    text = str(value or '').replace('\\', '/')
    return bool(DRIVE.match(text)) or text.startswith('/')


class DesignLocations:
    """Translate a project key to a path without widening LocalConfig.path_for()."""

    def __init__(self, config):
        self.config = config

    def key(self, directory) -> str:
        text = str(directory or '')
        if not is_external_key(text):
            return relative(text)
        # A vault file often arrives as an absolute Path. Normalize it back to a
        # vault-relative key so vault projects never look like external ones.
        try:
            root = self.config.root
            resolved = Path(text).expanduser().resolve()
            if resolved.is_relative_to(root):
                return relative(resolved.relative_to(root).as_posix())
        except (ValueError, OSError):
            pass
        return external_key(text)

    def is_external(self, directory) -> bool:
        text = str(directory or '')
        if not is_external_key(text):
            return False
        try:
            return not Path(text).expanduser().resolve().is_relative_to(self.config.root)
        except (ValueError, OSError):
            return True

    def entries(self) -> list[dict]:
        return [dict(item) for item in self.config.data.get('design_external_projects', [])
                if isinstance(item, dict) and item.get('path')]

    def project(self, directory) -> dict | None:
        """The registration owning this key, preferring the most specific root."""
        key = path_key(self.key(directory))
        matches = [item for item in self.entries()
                   if key == path_key(item['path']) or key.startswith(path_key(item['path']) + '/')]
        return max(matches, key=lambda item: len(path_key(item['path'])), default=None)

    def path(self, directory, *, writable=False) -> Path:
        key = self.key(directory)
        if not self.is_external(key):
            return self.config.path_for(key, writable=writable)
        item = self.project(key)
        if item is None:
            raise ValueError('该目录不是已注册的外部工程')
        if writable and not item.get('writable'):
            raise ValueError('外部工程未启用编辑，请先在工作台启用')
        root = Path(item['path'])
        if is_link(root) or (is_windows() and any(is_link(parent) for parent in root.parents)):
            raise ValueError('外部工程不能位于符号链接或 junction 中')
        if not root.is_dir():
            raise FileNotFoundError('外部工程目录不存在或已移动')
        parts = PurePosixPath(key).parts[len(PurePosixPath(item['path']).parts):]
        current = root
        for part in parts:
            current = current / part
            if is_link(current):
                raise ValueError('不通过符号链接或 junction 访问外部工程')
        if not current.resolve().is_relative_to(root.resolve()):
            raise ValueError('路径越出外部工程目录')
        return current

    def register(self, directory) -> dict:
        key = self.key(directory)
        if not self.is_external(key):
            raise ValueError('请选择 vault 之外的本地目录')
        path = Path(key)
        if is_link(path) or (is_windows() and any(is_link(parent) for parent in path.parents)):
            raise ValueError('外部工程不能位于符号链接或 junction 中')
        if not path.is_dir():
            raise ValueError('外部工程目录不存在')
        root = self.config.root
        if path.resolve().is_relative_to(root) or root.is_relative_to(path.resolve()):
            raise ValueError('外部工程不能与已关联目录重叠')
        for item in self.entries():
            if path_key(item['path']) == path_key(key):
                return item
        item = {'path': key, 'writable': False}
        self.save_entries([*self.entries(), item])
        return item

    def set_writable(self, directory, writable) -> dict:
        item = self.project(directory)
        if item is None:
            raise ValueError('该目录不是已注册的外部工程')
        updated = []
        for value in self.entries():
            if path_key(value['path']) == path_key(item['path']):
                value['writable'] = bool(writable)
                item = value
            updated.append(value)
        self.save_entries(updated)
        return item

    def remove(self, directory) -> dict:
        item = self.project(directory)
        if item is None:
            raise ValueError('该目录不是已注册的外部工程')
        self.save_entries([value for value in self.entries()
                           if path_key(value['path']) != path_key(item['path'])])
        return item

    def save_entries(self, entries) -> None:
        self.config.save({'design_external_projects': entries})
