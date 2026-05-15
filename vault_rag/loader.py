from __future__ import annotations

import logging
from pathlib import Path

import frontmatter
from llama_index.core import Document

from vault_rag.metadata_sanitize import sanitize_metadata_for_vector_store
from vault_rag.path_exclusions import (
    build_pathspec,
    frontmatter_requests_skip,
    skip_file_for_index,
)
from vault_rag.settings import Settings

logger = logging.getLogger(__name__)


def iter_markdown_documents(settings: Settings) -> list[Document]:
    """Load all Markdown files under vault as LlamaIndex Documents."""
    root = settings.vault_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"VAULT_ROOT is not a directory: {root}")

    spec = build_pathspec(settings)
    merged_dirs = settings.merged_exclude_dir_names()
    docs: list[Document] = []
    for path in root.rglob("*.md"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        rel_posix = rel.as_posix()
        if skip_file_for_index(rel, rel_posix, settings, spec, merged_dirs):
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning("Skip unreadable file %s: %s", path, e)
            continue
        post = frontmatter.loads(raw)
        raw_meta = post.metadata if isinstance(post.metadata, dict) else {}
        if frontmatter_requests_skip(raw_meta):
            continue
        meta = dict(raw_meta)
        meta["file_path"] = rel_posix
        meta["file_name"] = path.name
        meta = sanitize_metadata_for_vector_store(meta)
        docs.append(Document(text=post.content or "", metadata=meta))
    docs.sort(key=lambda d: d.metadata.get("file_path", ""))
    return docs
