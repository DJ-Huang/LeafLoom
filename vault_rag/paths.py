from __future__ import annotations

from pathlib import Path


def is_under_excluded_dir(rel: Path, exclude_dir_names: tuple[str, ...]) -> bool:
    """True if any relative path segment (folder or file name) matches exclude_dir_names (case-insensitive)."""
    parts_lower = {p.lower() for p in rel.parts}
    ex = {e.lower() for e in exclude_dir_names}
    return bool(parts_lower & ex)


def is_under_dot_prefixed_dir_segment(rel: Path) -> bool:
    """
    True if any parent directory segment starts with '.' (e.g. `.obsidian/`, `.codely-cli/auto-saves/`).

    Only directory segments are considered (all ``rel.parts`` except the filename); a note named
    ``.draft.md`` at vault root is not excluded by this rule.
    """
    parts = rel.parts
    if len(parts) < 2:
        return False
    return any(p.startswith(".") for p in parts[:-1])


def should_skip_path(rel_posix: str, exclude_globs: tuple[str, ...]) -> bool:
    r = rel_posix.replace("\\", "/").lower()
    for g in exclude_globs:
        if g and g.lower() in r:
            return True
    return False
