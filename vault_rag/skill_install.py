"""Install the bundled read-only search skill for the current local user."""
from pathlib import Path
import threading
import uuid

from vault_rag.local_state import atomic_write

_lock = threading.Lock()


def skill_source() -> Path:
    repository = Path(__file__).resolve().parents[1] / 'wiki-search' / 'SKILL.md'
    if repository.is_file():
        return repository
    return Path(__file__).parent / 'skills' / 'wiki-search' / 'SKILL.md'


def skill_target() -> Path:
    home = Path.home().resolve()
    target = home / '.agent' / 'skills' / 'wiki-search' / 'SKILL.md'
    for component in (target.parents[2], target.parents[1], target.parent, target):
        if component.is_symlink():
            raise ValueError('安装位置包含符号链接，请先检查 .agent/skills/wiki-search')
    return target


def skill_status() -> dict:
    target = skill_target()
    installed = target.is_file()
    return {'name': 'wiki-search', 'path': str(target), 'installed': installed,
            'up_to_date': installed and target.read_bytes() == skill_source().read_bytes()}


def install_skill() -> dict:
    with _lock:
        source = skill_source().read_bytes()
        target = skill_target()
        if target.exists() and not target.is_file():
            raise ValueError('安装位置已被同名目录占用')
        previous = target.read_bytes() if target.is_file() else None
        backup = None
        if previous is not None and previous != source:
            backup = target.with_name('SKILL.md.' + uuid.uuid4().hex + '.bak')
            atomic_write(backup, previous)
        if previous != source:
            atomic_write(target, source)
        if target.read_bytes() != source:
            raise OSError('安装文件校验失败')
        return {'name': 'wiki-search', 'path': str(target), 'installed': True,
                'up_to_date': True, 'backup': str(backup) if backup else None}
