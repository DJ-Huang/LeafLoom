from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from vault_rag.settings import Settings

CONTENT_SCOPE_VERSION = 1


def iter_scoped_markdown(settings: Settings) -> Iterator[Path]:
    """Visit one content subtree; never follow directory symlinks outside it."""
    root = settings.resolved_content_root()
    if not root.is_dir():
        raise FileNotFoundError(f"VAULT_CONTENT_FOLDER is not a directory: {root}; no whole-vault fallback")
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix != ".md" or not path.is_file():
                continue
            if not path.resolve().is_relative_to(root):
                continue
            yield path


def indexed_path_is_in_scope(file_path: str, settings: Settings) -> bool:
    """Validate persisted paths before returning search candidates or chunks."""
    path = Path(file_path.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        return False
    prefix = Path(settings.vault_content_folder)
    if not path.is_relative_to(prefix) or path == prefix:
        return False
    local = path.relative_to(prefix)
    if any(p.lower() in {"navigation", "attachments"} for p in local.parts[:-1]):
        return False
    if path.name.lower() in {"readme.md", "_readme.md"}:
        return False
    return (settings.vault_root.expanduser().resolve() / path).resolve().is_relative_to(
        settings.resolved_content_root()
    )
