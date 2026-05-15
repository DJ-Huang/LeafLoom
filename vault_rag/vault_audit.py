from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

import frontmatter

from vault_rag.path_exclusions import (
    build_pathspec,
    frontmatter_requests_skip,
    skip_file_for_index,
)
from vault_rag.settings import Settings

logger = logging.getLogger(__name__)


def audit_vault(settings: Settings, project_root: Path) -> dict[str, Any]:
    """
    Scan vault for RAG preflight: counts, largest files, exclusion preview, YAML opt-outs.
    Does not modify files.
    """
    root = settings.vault_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(str(root))

    spec = build_pathspec(settings)
    merged_dirs = settings.merged_exclude_dir_names()
    ragignore = (root / ".ragignore").resolve()

    skipped_path: list[str] = []
    skipped_yaml: list[str] = []
    top_level = Counter()
    sizes: list[tuple[int, str]] = []

    indexed = 0
    for path in root.rglob("*.md"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        rel_posix = rel.as_posix()
        top_level[rel.parts[0] if rel.parts else ""] += 1

        if skip_file_for_index(rel, rel_posix, settings, spec, merged_dirs):
            skipped_path.append(rel_posix)
            continue
        try:
            st = path.stat()
            sizes.append((st.st_size, rel_posix))
        except OSError:
            pass
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning("Unreadable %s: %s", path, e)
            continue
        post = frontmatter.loads(raw)
        raw_meta = post.metadata if isinstance(post.metadata, dict) else {}
        if frontmatter_requests_skip(raw_meta):
            skipped_yaml.append(rel_posix)
            continue
        indexed += 1

    sizes.sort(reverse=True)
    return {
        "vault_root": str(root),
        "index_will_use": str(settings.resolved_index_dir(project_root)),
        "index_in_vault": settings.index_in_vault,
        "vault_index_folder": settings.vault_index_folder,
        "exclude_dir_names_effective": list(settings.merged_exclude_dir_names()),
        "ragignore_exists": ragignore.is_file(),
        "ragignore_path": str(ragignore) if ragignore.is_file() else None,
        "markdown_files_total": sum(top_level.values()),
        "estimated_indexed_md": indexed,
        "skipped_by_path_rules": len(skipped_path),
        "skipped_by_yaml_opt_out": len(skipped_yaml),
        "top_level_folder_counts": dict(top_level.most_common(40)),
        "largest_md_bytes": [{"path": p, "bytes": b} for b, p in sizes[:25]],
        "sample_skipped_paths": skipped_path[:40],
        "sample_yaml_opt_outs": skipped_yaml[:40],
    }


def write_audit_report_md(
    settings: Settings,
    project_root: Path,
    out_path: Path | None = None,
) -> Path:
    data = audit_vault(settings, project_root)
    if out_path is None:
        out_path = settings.resolved_index_dir(project_root) / "AUDIT-last.md"
    lines = [
        "---",
        "title: vault-rag audit",
        "tags: [vault-rag, meta]",
        "---",
        "",
        f"Vault: `{data['vault_root']}`",
        f"Index directory: `{data['index_will_use']}`",
        "",
        "## Summary",
        "",
        f"- Markdown files (all): **{data['markdown_files_total']}**",
        f"- Estimated **indexed** after rules: **{data['estimated_indexed_md']}**",
        f"- Skipped by path rules: **{data['skipped_by_path_rules']}**",
        f"- Skipped by YAML (`rag_index: false` / `vault_rag_exclude: true`): **{data['skipped_by_yaml_opt_out']}**",
        f"- `.ragignore` present: **{data['ragignore_exists']}**",
        "",
        "## Directory-name excludes (path segment match)",
        "",
        "Any path component matching one of these names (case-insensitive) skips indexing:",
        "",
        "```text",
        ", ".join(data["exclude_dir_names_effective"]),
        "```",
        "",
        "## Top-level folder counts",
        "",
        "```json",
        json.dumps(data["top_level_folder_counts"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Largest Markdown files",
        "",
        "```json",
        json.dumps(data["largest_md_bytes"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Sample path-excluded files",
        "",
        "\n".join(f"- `{p}`" for p in data["sample_skipped_paths"]) or "_none in sample_",
        "",
        "## Sample YAML opt-out files",
        "",
        "\n".join(f"- `{p}`" for p in data["sample_yaml_opt_outs"]) or "_none in sample_",
        "",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
