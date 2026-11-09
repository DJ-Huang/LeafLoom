"""Install allowlisted bundled skills into the current local user's profile."""
from pathlib import Path
import threading
import uuid

from vault_rag.local_state import atomic_write

_lock = threading.Lock()
_SKILLS = {
    'leafloom': ('.agents', ('SKILL.md', 'references/knowledge.md', 'references/tasks.md',
                           'references/work-hub.md', 'references/workspace.md',
                           'references/imports.md', 'references/tasks-reports.md',
                           'references/feishu.md', 'references/gitlab.md', 'references/settings.md',
                           'references/feishu-sync.md', 'assets/workspace.base',
                           'scripts/leafloom.py', 'scripts/task_sync.py', 'scripts/feishu_sync.py')),
}
# Prior installable skills replaced by the unified leafloom bundle.
_SUPERSEDED = {'leafloom': ('wiki-search', 'work-hub')}


def is_bundled_skill(name: str) -> bool:
    return name in _SKILLS


def skill_spec(name):
    if not is_bundled_skill(name):
        raise ValueError('Unknown bundled skill')
    return _SKILLS[name]


def skill_source(name: str = 'leafloom') -> Path:
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


def skill_target(name: str = 'leafloom') -> Path:
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


def skill_status(name: str = 'leafloom') -> dict:
    target = skill_target(name)
    files = resources(name)
    installed = target.is_file()
    return {'name': name, 'path': str(target), 'installed': installed,
            'up_to_date': installed and all(p.is_file() and p.read_bytes() == data for p, data in files)}


def _skills_root(name: str) -> Path:
    directory, _ = skill_spec(name)
    home = Path.home().resolve()
    root = home / directory / 'skills'
    component = home
    for part in root.relative_to(home).parts:
        component = component / part
        if component.is_symlink():
            raise ValueError(f'安装位置包含符号链接，请先检查 {directory}/skills')
        if component.exists() and component != root and not component.is_dir():
            raise ValueError('安装位置的父路径不是目录')
    return root


def _retire_superseded(name: str) -> list[str]:
    """Move replaced skill directories aside after a successful leafloom install."""
    retired = []
    root = _skills_root(name)
    for old in _SUPERSEDED.get(name, ()):
        target = root / old
        if not target.exists():
            continue
        if target.is_symlink() or not target.is_dir():
            raise ValueError(f'旧技能位置不可用，请先检查 skills/{old}')
        if not (target / 'SKILL.md').is_file():
            continue
        backup = target.with_name(target.name + '.' + uuid.uuid4().hex + '.bak')
        target.rename(backup)
        retired.append(str(backup))
    return retired


def install_skill(name: str = 'leafloom') -> dict:
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
        retired = _retire_superseded(name)
        return {**skill_status(name), 'backup': backups[0] if backups else None, 'backups': backups,
                'retired': retired}
