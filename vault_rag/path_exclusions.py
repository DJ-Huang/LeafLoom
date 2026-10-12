from __future__ import annotations

import logging
from pathlib import Path

import pathspec

from vault_rag.paths import is_under_dot_prefixed_dir_segment, is_under_excluded_dir, should_skip_path
from vault_rag.settings import Settings
from vault_rag.content_scope import indexed_path_is_in_scope

logger = logging.getLogger(__name__)


def _strip_comment(line: str) -> str:
    s = line.strip()
    if not s or s.startswith("#"):
        return ""
    return s


def build_pathspec(settings: Settings) -> pathspec.PathSpec | None:
    """
    Gitignore-style excludes: defaults + env + optional vault/.ragignore.
    Matched paths are skipped from indexing (relative POSIX path from vault root).
    """
    lines: list[str] = []
    lines.extend(settings.builtin_exclude_pathspec)
    lines.extend(settings.exclude_pathspec_extra)
    if settings.load_ragignore_file:
        rag = (settings.vault_root / ".ragignore").resolve()
        if rag.is_file():
            try:
                extra = [_strip_comment(l) for l in rag.read_text(encoding="utf-8").splitlines()]
                lines.extend([x for x in extra if x])
            except OSError as e:
                logger.warning("Could not read %s: %s", rag, e)
    lines = [_strip_comment(l) for l in lines if _strip_comment(l)]
    if not lines:
        return None
    return pathspec.PathSpec.from_lines("gitignore", lines)


def skip_file_for_index(
    rel: Path,
    rel_posix: str,
    settings: Settings,
    spec: pathspec.PathSpec | None,
    merged_exclude_dir_names: tuple[str, ...],
) -> bool:
    """True = do not index this markdown file."""
    if not indexed_path_is_in_scope(rel_posix, settings):
        return True
    if settings.exclude_dot_prefixed_dir_segments and is_under_dot_prefixed_dir_segment(rel):
        return True
    if is_under_excluded_dir(rel, merged_exclude_dir_names):
        return True
    if should_skip_path(rel_posix, settings.exclude_globs):
        return True
    if spec is not None and spec.match_file(rel_posix):
        return True
    return False


def frontmatter_requests_skip(meta: object) -> bool:
    """YAML-level opt-out before sanitization."""
    if not isinstance(meta, dict):
        return False
    if meta.get("vault_rag_exclude") in (True, "true", "yes", "True", "YES", 1, "1"):
        return True
    if "rag_index" not in meta:
        return False
    ri = meta["rag_index"]
    if ri in (False, 0, "false", "False", "no", "No", "0", "NO"):
        return True
    return False
