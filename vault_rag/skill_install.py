"""Install allowlisted bundled skills into the current local user's profile."""
from pathlib import Path
import threading
import uuid

from vault_rag.local_state import atomic_write

_lock = threading.Lock()
_SKILLS = {
    # Keep the original search skill's location and no-argument API compatible.
    'wiki-search': ('.agent', ('SKILL.md',)),
    'work-hub': ('.agents', ('SKILL.md', 'references/workspace.md',
                           'references/imports.md', 'references/tasks-reports.md',
                           'references/feishu.md', 'references/gitlab.md', 'references/settings.md',
                           'references/feishu-sync.md', 'assets/workspace.base',
                           'scripts/task_sync.py', 'scripts/feishu_sync.py')),
}


def skill_spec(name):
    if name not in _SKILLS:
        raise ValueError('Unknown bundled skill')
    return _SKILLS[name]


def skill_source(name: str = 'wiki-search') -> Path:
    skill_spec(name)
    repository = Path(__file__).resolve().parents[1] / name / 'SKILL.md'
    if repository.is_file():
        return repository
    return Path(__file__).parent / 'skills' / name / 'SKILL.md'


def checked_target(name, relative='SKILL.md') -> Path:
    directory, files = skill_spec(name)
    if relative not in files:
        raise ValueError('Unknown bundled skill resource')
    home = Path.home().resolve()
    target = home / directory / 'skills' / name / relative
    component = home
    for part in target.relative_to(home).parts:
        component = component / part
        if component.is_symlink():
            raise ValueError(f'安装位置包含符号链接，请先检查 {directory}/skills/{name}')
        if component.exists() and component != target and not component.is_dir():
            raise ValueError('安装位置的父路径不是目录')
    if target.exists() and not target.is_file():
        raise ValueError('安装位置已被同名目录占用')
    return target


def skill_target(name: str = 'wiki-search') -> Path:
    return checked_target(name)


def resources(name):
    _, files = skill_spec(name)
    root = skill_source(name).parent.resolve()
    result = []
    for relative in files:
        source = root / relative
        # Only package-owned regular files are installable; never follow links.
        component = root
        for part in Path(relative).parts:
            component = component / part
            if component.is_symlink():
                raise ValueError('Bundled skill resource contains a symbolic link')
        result.append((checked_target(name, relative), source.read_bytes()))
    return result


def skill_status(name: str = 'wiki-search') -> dict:
    target = skill_target(name)
    files = resources(name)
    installed = target.is_file()
    return {'name': name, 'path': str(target), 'installed': installed,
            'up_to_date': installed and all(p.is_file() and p.read_bytes() == data for p, data in files)}


def install_skill(name: str = 'wiki-search') -> dict:
    with _lock:
        files = resources(name)  # Preflight every source and destination before writing.
        backups = []
        for target, source in files:
            previous = target.read_bytes() if target.is_file() else None
            if previous is not None and previous != source:
                backup = target.with_name(target.name + '.' + uuid.uuid4().hex + '.bak')
                atomic_write(backup, previous)
                backups.append(str(backup))
            if previous != source:
                atomic_write(target, source)
        if any(target.read_bytes() != source for target, source in files):
            raise OSError('安装文件校验失败')
        return {**skill_status(name), 'backup': backups[0] if backups else None, 'backups': backups}
